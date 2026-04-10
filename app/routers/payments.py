import os
import uuid
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from typing import Optional
from datetime import datetime, timezone
from bson import ObjectId

from app.core.database import get_db
from app.core.config import settings
from app.models.schemas import PaymentUpdate
from app.services.email_service import send_payment_receipt_notification
from app.services import storage_service

router = APIRouter()

ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
MAX_BYTES = settings.MAX_UPLOAD_MB * 1024 * 1024


@router.post("/{engagement_id}/receipt", status_code=201)
async def upload_receipt(
    engagement_id: str,
    file: UploadFile = File(...),
    milestone_n: int = Form(1),
    method: Optional[str] = Form(None),
    method_detail: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
):
    """
    Client uploads payment receipt (PDF/image).
    - R2 configured: uploads to Cloudflare R2, stores object key in MongoDB.
    - No R2: fallback to local UPLOAD_DIR (dev only).
    Notifies provider by email regardless of storage backend.
    """
    db = get_db()

    # ── Validate engagement ──────────────────────────────────────
    try:
        oid = ObjectId(engagement_id)
    except Exception:
        raise HTTPException(400, "Invalid engagement_id")

    engagement = await db.engagements.find_one({"_id": oid})
    if not engagement:
        raise HTTPException(404, "Engagement not found")

    # ── Validate file ────────────────────────────────────────────
    ext = os.path.splitext(file.filename or "")[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            400,
            f"Tipo de archivo no permitido. Formatos aceptados: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    content = await file.read()
    if len(content) > MAX_BYTES:
        raise HTTPException(413, f"Archivo demasiado grande. Máximo: {settings.MAX_UPLOAD_MB} MB")

    # ── Store file ───────────────────────────────────────────────
    storage_key: str
    storage_backend: str

    if settings.r2_enabled:
        try:
            storage_key = await storage_service.upload_receipt(
                file_bytes=content,
                engagement_id=engagement_id,
                milestone_n=milestone_n,
                original_filename=file.filename or f"receipt{ext}",
                client_email=engagement.get("client_email", ""),
            )
            storage_backend = "r2"
        except storage_service.StorageError as e:
            print(f"[PAYMENT] R2 upload failed, falling back to local: {e}")
            storage_key = _save_local(content, engagement_id, milestone_n, ext)
            storage_backend = "local_fallback"
    else:
        storage_key = _save_local(content, engagement_id, milestone_n, ext)
        storage_backend = "local"

    # ── Update payment record ────────────────────────────────────
    now = datetime.now(timezone.utc)
    result = await db.payments.find_one_and_update(
        {"engagement_id": engagement_id, "milestone_n": milestone_n},
        {
            "$set": {
                "receipt_key":     storage_key,
                "storage_backend": storage_backend,
                "receipt_notes":   notes,
                "method":          method,
                "method_detail":   method_detail,
                "status":          "received",
                "paid_at":         now,
                "updated_at":      now,
            }
        },
        return_document=True,
    )

    if not result:
        raise HTTPException(404, f"No se encontró el registro de pago para hito {milestone_n}")

    # ── Notify provider ──────────────────────────────────────────
    try:
        await send_payment_receipt_notification(
            engagement_id=engagement_id,
            client_name=engagement.get("client_name", ""),
            client_email=engagement.get("client_email", ""),
            milestone_label=result.get("milestone_label", f"Hito {milestone_n}"),
            amount=result.get("amount_due") or 0,
            method=method or "N/D",
            filename=os.path.basename(storage_key),
        )
    except Exception as e:
        print(f"[PAYMENT] Email notification failed (non-fatal): {e}")

    return {
        "message": "Comprobante recibido. Lo verificaremos a la brevedad.",
        "storage_backend": storage_backend,
        "payment_status": "received",
    }


@router.get("/{engagement_id}/receipt/{milestone_n}/download")
async def download_receipt(engagement_id: str, milestone_n: int, expires: int = 3600):
    """
    Admin: generate a presigned URL to download a receipt from R2.
    Expires after `expires` seconds (default 1 hour).
    """
    db = get_db()
    payment = await db.payments.find_one(
        {"engagement_id": engagement_id, "milestone_n": milestone_n}
    )
    if not payment:
        raise HTTPException(404, "Payment record not found")

    key = payment.get("receipt_key")
    if not key:
        raise HTTPException(404, "No receipt file found for this payment")

    backend = payment.get("storage_backend", "local")

    if backend == "r2":
        try:
            url = storage_service.get_receipt_url(key, expires_in=expires)
            return {
                "url":        url,
                "expires_in": expires,
                "backend":    "r2",
                "note":       f"URL válida por {expires // 60} minutos.",
            }
        except storage_service.StorageError as e:
            raise HTTPException(500, f"No se pudo generar la URL de descarga: {e}")
    else:
        return {
            "path":    key,
            "backend": backend,
            "note":    "Archivo almacenado localmente.",
        }


@router.get("/{engagement_id}")
async def get_payments(engagement_id: str):
    """Get all payment records for an engagement."""
    db = get_db()
    cursor = db.payments.find({"engagement_id": engagement_id}).sort("milestone_n", 1)
    docs = []
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        doc.pop("receipt_key", None)    # Never expose raw storage keys to clients
        docs.append(doc)
    return docs


@router.patch("/{engagement_id}/{milestone_n}/verify")
async def verify_payment(engagement_id: str, milestone_n: int, payload: PaymentUpdate):
    """Admin: mark a payment as verified or rejected."""
    db = get_db()
    now = datetime.now(timezone.utc)

    update_data: dict = {"status": payload.status, "updated_at": now}
    if payload.status == "verified":
        update_data["verified_at"] = now
        update_data["verified_by"] = payload.verified_by or "admin"
    if payload.notes:
        update_data["receipt_notes"] = payload.notes

    result = await db.payments.find_one_and_update(
        {"engagement_id": engagement_id, "milestone_n": milestone_n},
        {"$set": update_data},
        return_document=True,
    )
    if not result:
        raise HTTPException(404, "Payment record not found")

    # Activar engagement cuando se verifica el primer pago
    if milestone_n == 1 and payload.status == "verified":
        await db.engagements.update_one(
            {"_id": ObjectId(engagement_id)},
            {"$set": {"status": "active", "updated_at": now}},
        )

    result["id"] = str(result.pop("_id"))
    result.pop("receipt_key", None)
    return result


def _save_local(content: bytes, engagement_id: str, milestone_n: int, ext: str) -> str:
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    filename = f"{engagement_id[:8]}_{milestone_n}_{uuid.uuid4().hex[:8]}{ext}"
    filepath = os.path.join(settings.UPLOAD_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(content)
    return filepath
