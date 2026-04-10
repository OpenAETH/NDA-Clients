from fastapi import APIRouter, HTTPException, Request
from typing import List
from datetime import datetime, timezone
from bson import ObjectId

from app.core.database import get_db
from app.models.schemas import EngagementCreate, EngagementOut
from app.services.pdf_service import generate_nda_pdf
from app.services.email_service import send_nda_to_client, send_provider_notification
from app.services import storage_service

router = APIRouter()


def _serialize(doc) -> dict:
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.post("", status_code=201)
async def create_engagement(payload: EngagementCreate, request: Request):
    """
    Called when client submits the signed NDA form.
    1. Resolves product from catalog
    2. Calculates final price
    3. Creates client + engagement documents in MongoDB
    4. Generates NDA PDF server-side
    5. Sends PDF to client and notification to provider
    Returns engagement_id for reference.
    """
    db = get_db()

    # ── Resolve product ──────────────────────────────────────────
    product = await db.products.find_one({"code": payload.product_code.upper(), "is_active": True})
    if not product:
        raise HTTPException(404, f"Product '{payload.product_code}' not found or inactive")

    base_price = product.get("base_price")
    discount_pct = product.get("discount_pct", 0) if payload.payment_mode == "anticipado" else 0

    # Custom products can pass a pre-agreed price
    if payload.agreed_price is not None:
        base_price = payload.agreed_price
        discount_pct = 0

    final_price = round(base_price * (1 - discount_pct / 100), 2) if base_price else None
    milestones = product.get("milestones", [])

    # ── Upsert client ────────────────────────────────────────────
    client_doc = payload.client.model_dump()
    client_doc["updated_at"] = datetime.now(timezone.utc)
    client_result = await db.clients.find_one_and_update(
        {"email": payload.client.email},
        {"$set": client_doc, "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
        upsert=True,
        return_document=True,
    )
    client_id = str(client_result["_id"])

    # ── Create engagement ────────────────────────────────────────
    signed_at = datetime.now(timezone.utc)
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
        "final_price":         final_price,
        "milestones_snapshot": milestones,
        "custom_description":  payload.custom_description,
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

    result = await db.engagements.insert_one(engagement_doc)
    engagement_id = str(result.inserted_id)

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
            amt = round(base_price * m["pct"] / 100, 2) if base_price else None
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
        await db.payments.insert_many(payment_docs)

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
        )

        # ── Send emails ───────────────────────────────────────────
        await send_nda_to_client(
            client_name=payload.client.full_name,
            client_email=payload.client.email,
            product_name=product.get("full_name") or product.get("name"),
            total_amount=f"${final_price:,.2f}" if final_price else "A cotizar",
            payment_mode=payload.payment_mode,
            pdf_bytes=pdf_bytes,
            engagement_id=engagement_id,
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

        await db.engagements.update_one(
            {"_id": ObjectId(engagement_id)},
            {"$set": {
                "pdf_generated":  True,
                "pdf_r2_key":     pdf_r2_key,
                "storage_backend": "r2" if pdf_r2_key else "none",
            }},
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
    db = get_db()
    query = {}
    if status:
        query["status"] = status
    cursor = db.engagements.find(query).sort("created_at", -1).limit(limit)
    docs = []
    async for doc in cursor:
        docs.append({
            "id":           str(doc["_id"]),
            "client_email": doc.get("client_email"),
            "client_name":  doc.get("client_name"),
            "product_code": doc.get("product_code"),
            "payment_mode": doc.get("payment_mode"),
            "final_price":  doc.get("final_price"),
            "status":       doc.get("status"),
            "signed_at":    doc.get("signed_at"),
            "created_at":   doc.get("created_at"),
        })
    return docs


@router.get("/{engagement_id}/nda/download")
async def download_nda(engagement_id: str, expires: int = 3600):
    """
    Admin: generate a presigned URL to download the signed NDA PDF from R2.
    Expires after `expires` seconds (default 1 hour).
    """
    db = get_db()
    try:
        oid = ObjectId(engagement_id)
    except Exception:
        raise HTTPException(400, "Invalid engagement_id")

    doc = await db.engagements.find_one({"_id": oid}, {"pdf_r2_key": 1, "storage_backend": 1})
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



    db = get_db()
    try:
        oid = ObjectId(engagement_id)
    except Exception:
        raise HTTPException(400, "Invalid engagement_id")
    doc = await db.engagements.find_one({"_id": oid})
    if not doc:
        raise HTTPException(404, "Engagement not found")
    doc.pop("signature_data", None)   # Don't expose raw signature in GET
    return _serialize(doc)


@router.patch("/{engagement_id}/status")
async def update_status(engagement_id: str, status: str):
    """Admin: update engagement lifecycle status."""
    valid = {"pending", "signed", "active", "completed", "cancelled"}
    if status not in valid:
        raise HTTPException(400, f"Status must be one of: {valid}")
    db = get_db()
    try:
        oid = ObjectId(engagement_id)
    except Exception:
        raise HTTPException(400, "Invalid engagement_id")
    result = await db.engagements.update_one(
        {"_id": oid},
        {"$set": {"status": status, "updated_at": datetime.now(timezone.utc)}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Engagement not found")
    return {"engagement_id": engagement_id, "status": status}
