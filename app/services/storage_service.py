"""
storage_service.py — Cloudflare R2 via boto3 (S3-compatible)

Responsabilidades:
  - Subir archivos al bucket R2 (comprobantes + PDFs firmados)
  - Generar presigned URLs privadas (acceso temporal desde el backend)
  - Eliminar objetos
  - Listar objetos por prefijo

Estructura de claves en el bucket:
  receipts/{engagement_id}/{milestone_n}_{uuid}.{ext}
  ndas/{engagement_id}/NDA_{engagement_id[:8]}.pdf
  signatures/{engagement_id}/sig_{engagement_id[:8]}.png   ← opcional

El bucket es PRIVADO. Todo acceso pasa por presigned URLs generadas
por este servicio con expiración configurable (default 1 hora).
"""

import io
import uuid
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from typing import Optional

from app.core.config import settings


# ── Singleton client ─────────────────────────────────────────────

_s3_client = None


def get_r2_client():
    """
    Lazy singleton. El cliente se crea la primera vez que se llama.
    Cloudflare R2 endpoint format:
        https://<account_id>.r2.cloudflarestorage.com
    """
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            "s3",
            endpoint_url=settings.R2_ENDPOINT_URL,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            config=Config(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "adaptive"},
            ),
            region_name="auto",   # R2 uses "auto" as region
        )
    return _s3_client


# ── Core upload ──────────────────────────────────────────────────

async def upload_file(
    file_bytes: bytes,
    object_key: str,
    content_type: str = "application/octet-stream",
    metadata: Optional[dict] = None,
) -> str:
    """
    Upload raw bytes to R2. Returns the object key on success.
    Raises StorageError on failure.

    Args:
        file_bytes:   Raw file content
        object_key:   Full key path in bucket, e.g. "receipts/abc123/1_xyz.pdf"
        content_type: MIME type
        metadata:     Optional dict of string key/value pairs stored with the object

    Returns:
        object_key (same value — useful for chaining)
    """
    client = get_r2_client()
    extra = {"ContentType": content_type}
    if metadata:
        # R2/S3 metadata values must be strings
        extra["Metadata"] = {k: str(v) for k, v in metadata.items()}

    try:
        client.put_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=object_key,
            Body=file_bytes,
            **extra,
        )
        print(f"[R2] Uploaded: {object_key} ({len(file_bytes):,} bytes)")
        return object_key
    except ClientError as e:
        raise StorageError(f"R2 upload failed for '{object_key}': {e}") from e


async def upload_fileobj(
    file_obj: io.IOBase,
    object_key: str,
    content_type: str = "application/octet-stream",
    metadata: Optional[dict] = None,
) -> str:
    """Upload from a file-like object (e.g. BytesIO)."""
    return await upload_file(file_obj.read(), object_key, content_type, metadata)


# ── Presigned URL (private download) ────────────────────────────

def generate_presigned_url(
    object_key: str,
    expires_in: int = None,
) -> str:
    """
    Generate a time-limited presigned GET URL for a private object.
    The URL is usable without credentials until it expires.

    Args:
        object_key: Key of the object in the bucket
        expires_in: Seconds until expiry (default: R2_PRESIGNED_EXPIRY from config)

    Returns:
        Presigned URL string
    """
    client = get_r2_client()
    expiry = expires_in or settings.R2_PRESIGNED_EXPIRY

    try:
        url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.R2_BUCKET_NAME, "Key": object_key},
            ExpiresIn=expiry,
        )
        return url
    except ClientError as e:
        raise StorageError(f"Could not generate presigned URL for '{object_key}': {e}") from e


# ── Delete ───────────────────────────────────────────────────────

async def delete_file(object_key: str) -> bool:
    """
    Delete an object from R2. Returns True on success, False if not found.
    Does NOT raise on 404 (idempotent delete).
    """
    client = get_r2_client()
    try:
        client.delete_object(Bucket=settings.R2_BUCKET_NAME, Key=object_key)
        print(f"[R2] Deleted: {object_key}")
        return True
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("NoSuchKey", "404"):
            return False
        raise StorageError(f"R2 delete failed for '{object_key}': {e}") from e


# ── List ─────────────────────────────────────────────────────────

def list_objects(prefix: str) -> list[dict]:
    """
    List all objects under a prefix. Returns list of dicts with key + size + last_modified.
    Example: list_objects("receipts/abc123/")
    """
    client = get_r2_client()
    try:
        resp = client.list_objects_v2(Bucket=settings.R2_BUCKET_NAME, Prefix=prefix)
        return [
            {
                "key":           obj["Key"],
                "size":          obj["Size"],
                "last_modified": obj["LastModified"].isoformat(),
            }
            for obj in resp.get("Contents", [])
        ]
    except ClientError as e:
        raise StorageError(f"R2 list failed for prefix '{prefix}': {e}") from e


# ── High-level helpers ───────────────────────────────────────────

async def upload_receipt(
    file_bytes: bytes,
    engagement_id: str,
    milestone_n: int,
    original_filename: str,
    client_email: str = "",
) -> str:
    """
    Upload a payment receipt to R2.
    Key format: receipts/{engagement_id}/{milestone_n}_{uuid8}.{ext}
    Returns the object key.
    """
    import os
    ext = os.path.splitext(original_filename)[-1].lower() or ".bin"
    uid = uuid.uuid4().hex[:8]
    key = f"receipts/{engagement_id}/{milestone_n}_{uid}{ext}"

    content_type = _mime_for_ext(ext)
    metadata = {
        "engagement_id": engagement_id,
        "milestone_n":   str(milestone_n),
        "client_email":  client_email,
        "original_name": original_filename,
    }

    return await upload_file(file_bytes, key, content_type, metadata)


async def upload_nda_pdf(
    pdf_bytes: bytes,
    engagement_id: str,
    client_name: str = "",
) -> str:
    """
    Upload the signed NDA PDF backup to R2.
    Key format: ndas/{engagement_id}/NDA_{engagement_id[:8].upper()}.pdf
    Returns the object key.
    """
    safe_id = engagement_id[:8].upper()
    key = f"ndas/{engagement_id}/NDA_{safe_id}.pdf"
    metadata = {
        "engagement_id": engagement_id,
        "client_name":   client_name,
        "document_type": "signed_nda",
    }
    return await upload_file(pdf_bytes, key, "application/pdf", metadata)


def get_receipt_url(object_key: str, expires_in: int = 3600) -> str:
    """Presigned URL for a receipt file. Default expiry: 1 hour."""
    return generate_presigned_url(object_key, expires_in)


def get_nda_url(object_key: str, expires_in: int = 3600) -> str:
    """Presigned URL for a signed NDA PDF. Default expiry: 1 hour."""
    return generate_presigned_url(object_key, expires_in)


# ── Utilities ────────────────────────────────────────────────────

def _mime_for_ext(ext: str) -> str:
    return {
        ".pdf":  "application/pdf",
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png":  "image/png",
    }.get(ext.lower(), "application/octet-stream")


class StorageError(Exception):
    """Raised when an R2 operation fails."""
    pass
