from fastapi import APIRouter, HTTPException, Request
from typing import List
from datetime import datetime, timezone

from app.core import store, sales_log, discounts
from app.core.config import settings
from app.models.schemas import EngagementCreate, EngagementOut
from app.services.pdf_service import generate_nda_pdf
from app.services.email_service import send_nda_to_client, send_provider_notification
from app.services import storage_service

router = APIRouter()


@router.post("", status_code=201)
async def create_engagement(payload: EngagementCreate, request: Request):
    """
    Called when client submits the signed NDA form.
    1. Resolves product from catalog
    2. Calculates final price
    3. Creates client + engagement records (JSON store)
    4. Generates NDA PDF server-side
    5. Sends PDF to client and notification to provider
    Returns engagement_id for reference.
    """
    # ── Resolve product ──────────────────────────────────────────
    product = store.products.find_one({"code": payload.product_code.upper(), "is_active": True})
    if not product:
        raise HTTPException(404, f"Product '{payload.product_code}' not found or inactive")

    # Localizar el producto al idioma del cliente: el PDF, el email y el
    # registro guardan los textos (nombre, milestones) en ese idioma.
    lang = store.normalize_lang(payload.lang)
    product = store.localize(product, lang)

    # ── Precio (siempre calculado en el servidor) ────────────────
    # 1. Precio base: del catálogo, o el monto manual ingresado por el
    #    cliente (obligatorio para CUSTOM o productos "a cotizar").
    base_price = product.get("base_price")
    if payload.agreed_price is not None:
        if payload.agreed_price <= 0:
            raise HTTPException(422, "El monto acordado debe ser mayor a 0.")
        base_price = round(payload.agreed_price, 2)

    if base_price is None:
        raise HTTPException(
            422,
            "Este producto requiere un monto acordado. Ingresá el importe a pagar.",
        )

    # 2. Descuento por pago anticipado (solo productos de catálogo con precio fijo).
    anticipado_pct = (
        product.get("discount_pct", 0)
        if payload.payment_mode == "anticipado" and payload.agreed_price is None
        else 0
    )
    price_after_mode = round(base_price * (1 - anticipado_pct / 100), 2)

    # 3. Código de descuento (opcional), re-validado acá — nunca se confía
    #    en el precio que envía el frontend.
    discount_meta = None
    final_price = price_after_mode
    if payload.discount_code and payload.discount_code.strip():
        try:
            disc = discounts.resolve_code(payload.discount_code, payload.product_code, lang=lang)
        except discounts.DiscountError as e:
            raise HTTPException(422, f"Código de descuento inválido: {e}")
        final_price = discounts.apply_discount(price_after_mode, disc)
        discount_meta = {**disc, "amount_saved": round(price_after_mode - final_price, 2)}

    # Descuento total efectivo (modalidad + código) sobre el precio base.
    discount_pct = round((1 - final_price / base_price) * 100, 2) if base_price else 0
    milestones = product.get("milestones", [])

    # ── Upsert client ────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    client_doc = payload.client.model_dump()
    client_doc["updated_at"] = now
    client_result = store.clients.upsert(
        {"email": payload.client.email},
        client_doc,
        on_insert={"created_at": now},
    )
    client_id = client_result["id"]

    # ── Create engagement ────────────────────────────────────────
    signed_at = now
    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else None)

    engagement_doc = {
        "client_id":           client_id,
        "client_name":         payload.client.full_name,
        "client_email":        payload.client.email,
        "product_code":        payload.product_code.upper(),
        "product_name":        product.get("full_name") or product.get("name"),
        "payment_mode":        payload.payment_mode,
        "agreed_price":        base_price,
        "discount_pct":        discount_pct,
        "discount_code":       discount_meta["code"] if discount_meta else None,
        "discount_detail":     discount_meta,
        "final_price":         final_price,
        "milestones_snapshot": milestones,
        "custom_description":  payload.custom_description,
        "payment_details":     payload.payment_details.model_dump() if payload.payment_details else None,
        "signature_type":      payload.signature_type,
        "signature_data":      payload.signature_data,
        "ip_address":          ip,
        "user_agent":          payload.user_agent or request.headers.get("user-agent"),
        "status":              "signed",
        "signed_at":           signed_at,
        "created_at":          signed_at,
        "updated_at":          signed_at,
        "nda_version":         "1.0",
    }

    engagement = store.engagements.insert(engagement_doc)
    engagement_id = engagement["id"]

    # ── Create payment rows ──────────────────────────────────────
    payment_docs = []
    if payload.payment_mode == "anticipado":
        payment_docs.append({
            "engagement_id":  engagement_id,
            "milestone_n":    1,
            "milestone_label":"Pago único anticipado",
            "amount_due":     final_price,
            "due_pct":        100,
            "status":         "pending",
            "created_at":     signed_at,
        })
    else:
        for m in milestones:
            amt = round(final_price * m["pct"] / 100, 2) if final_price else None
            payment_docs.append({
                "engagement_id":  engagement_id,
                "milestone_n":    m["milestone_n"],
                "milestone_label":m["label"],
                "amount_due":     amt,
                "due_pct":        m["pct"],
                "status":         "pending",
                "created_at":     signed_at,
            })

    if payment_docs:
        store.payments.insert_many(payment_docs)

    # ── Registro de venta en Mongo (best-effort, no-fatal) ───────
    await sales_log.record_sale({
        "engagement_id": engagement_id,
        "client_id":     client_id,
        "client_name":   payload.client.full_name,
        "client_email":  payload.client.email,
        "product_code":  payload.product_code.upper(),
        "product_name":  product.get("full_name") or product.get("name"),
        "payment_mode":  payload.payment_mode,
        "agreed_price":  base_price,
        "final_price":   final_price,
        "discount_pct":  discount_pct,
        "discount_code": discount_meta["code"] if discount_meta else None,
        "status":        "signed",
        "payment_status": "pending",
        "signed_at":     signed_at,
    })

    # ── Generate PDF ──────────────────────────────────────────────
    try:
        pdf_bytes = generate_nda_pdf(
            client_name=payload.client.full_name,
            client_email=payload.client.email,
            client_company=payload.client.company,
            client_country=payload.client.country or payload.client.jurisdiction,
            product_name=product.get("full_name") or product.get("name"),
            payment_mode=payload.payment_mode,
            total_amount=final_price,
            discount_pct=discount_pct,
            milestones=milestones,
            signature_data=payload.signature_data,
            engagement_id=engagement_id,
            signed_at=signed_at,
            custom_description=payload.custom_description,
            payment_details=payload.payment_details.model_dump() if payload.payment_details else None,
            lang=lang,
        )

        # ── Send emails ───────────────────────────────────────────
        await send_nda_to_client(
            client_name=payload.client.full_name,
            client_email=payload.client.email,
            product_name=product.get("full_name") or product.get("name"),
            total_amount=f"${final_price:,.2f}" if final_price else None,
            payment_mode=payload.payment_mode,
            pdf_bytes=pdf_bytes,
            engagement_id=engagement_id,
            lang=lang,
        )

        await send_provider_notification(
            client_name=payload.client.full_name,
            client_email=payload.client.email,
            client_company=payload.client.company,
            product_name=product.get("full_name") or product.get("name"),
            total_amount=f"${final_price:,.2f}" if final_price else "A cotizar",
            payment_mode=payload.payment_mode,
            engagement_id=engagement_id,
            custom_description=payload.custom_description,
        )

        # ── Backup PDF to R2 ─────────────────────────────────────
        pdf_r2_key = None
        if settings.r2_enabled:
            try:
                pdf_r2_key = await storage_service.upload_nda_pdf(
                    pdf_bytes=pdf_bytes,
                    engagement_id=engagement_id,
                    client_name=payload.client.full_name,
                )
                print(f"[ENGAGEMENT] NDA PDF backed up to R2: {pdf_r2_key}")
            except storage_service.StorageError as e:
                print(f"[ENGAGEMENT] R2 PDF backup failed (non-fatal): {e}")

        store.engagements.update_one(
            {"id": engagement_id},
            {
                "pdf_generated":  True,
                "pdf_r2_key":     pdf_r2_key,
                "storage_backend": "r2" if pdf_r2_key else "none",
            },
        )

    except Exception as e:
        print(f"[ENGAGEMENT] PDF/email error (non-fatal): {e}")

    return {
        "engagement_id": engagement_id,
        "status": "signed",
        "message": "NDA firmado. Revisá tu email para el PDF.",
    }


@router.get("", response_model=List[EngagementOut])
async def list_engagements(status: str = None, limit: int = 50):
    """Admin: list all engagements, optionally filtered by status."""
    filters = {"status": status} if status else None
    docs = store.engagements.find(filters, sort=("created_at", -1))[:limit]
    return [
        {
            "id":           doc["id"],
            "client_email": doc.get("client_email"),
            "client_name":  doc.get("client_name"),
            "product_code": doc.get("product_code"),
            "payment_mode": doc.get("payment_mode"),
            "final_price":  doc.get("final_price"),
            "status":       doc.get("status"),
            "signed_at":    doc.get("signed_at"),
            "created_at":   doc.get("created_at"),
        }
        for doc in docs
    ]


@router.get("/{engagement_id}/nda/download")
async def download_nda(engagement_id: str, expires: int = 3600):
    """
    Admin: generate a presigned URL to download the signed NDA PDF from R2.
    Expires after `expires` seconds (default 1 hour).
    """
    doc = store.engagements.find_one({"id": engagement_id})
    if not doc:
        raise HTTPException(404, "Engagement not found")

    key = doc.get("pdf_r2_key")
    if not key:
        raise HTTPException(
            404,
            "NDA PDF not found in cloud storage. "
            "May have been stored locally or generation failed."
        )

    try:
        url = storage_service.get_nda_url(key, expires_in=expires)
        return {
            "url":        url,
            "expires_in": expires,
            "note":       f"URL válida por {expires // 60} minutos.",
        }
    except storage_service.StorageError as e:
        raise HTTPException(500, f"No se pudo generar la URL de descarga: {e}")


@router.get("/{engagement_id}")
async def get_engagement(engagement_id: str):
    """Admin: fetch a single engagement (raw signature omitted)."""
    doc = store.engagements.find_one({"id": engagement_id})
    if not doc:
        raise HTTPException(404, "Engagement not found")
    doc = {k: v for k, v in doc.items() if k != "signature_data"}
    return doc


@router.patch("/{engagement_id}/status")
async def update_status(engagement_id: str, status: str):
    """Admin: update engagement lifecycle status."""
    valid = {"pending", "signed", "active", "completed", "cancelled"}
    if status not in valid:
        raise HTTPException(400, f"Status must be one of: {valid}")
    now = datetime.now(timezone.utc)
    result = store.engagements.update_one(
        {"id": engagement_id},
        {"status": status, "updated_at": now},
    )
    if result is None:
        raise HTTPException(404, "Engagement not found")
    await sales_log.update_sale_status(engagement_id, {"status": status, "updated_at": now})
    return {"engagement_id": engagement_id, "status": status}
