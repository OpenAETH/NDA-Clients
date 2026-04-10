import httpx
import base64
from typing import Optional
from app.core.config import settings


RESEND_URL = "https://api.resend.com/emails"


async def _send(payload: dict) -> bool:
    """Low-level Resend API call."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            RESEND_URL,
            headers={
                "Authorization": f"Bearer {settings.RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        if resp.status_code not in (200, 201):
            print(f"[EMAIL] Resend error {resp.status_code}: {resp.text}")
            return False
        return True


async def send_nda_to_client(
    client_name: str,
    client_email: str,
    product_name: str,
    total_amount: str,
    payment_mode: str,
    pdf_bytes: bytes,
    engagement_id: str,
) -> bool:
    """Send signed NDA PDF to the client."""

    pdf_b64 = base64.b64encode(pdf_bytes).decode()
    mode_label = "pago por hitos" if payment_mode == "hitos" else "pago único anticipado"

    html_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
      <div style="background:#1A1A2E;padding:28px 32px;border-radius:8px 8px 0 0;">
        <p style="color:#aaaacc;font-size:11px;margin:0 0 8px;text-transform:uppercase;letter-spacing:0.1em;">
          Agraound Consulting / AETHERYON Systems
        </p>
        <h1 style="color:#ffffff;font-size:20px;margin:0;">Tu NDA ha sido firmado</h1>
      </div>
      <div style="background:#f5f6fa;padding:28px 32px;">
        <p style="color:#444;margin:0 0 16px;">Hola <strong>{client_name}</strong>,</p>
        <p style="color:#444;margin:0 0 16px;">
          Adjunto encontrás tu <strong>Non-Disclosure &amp; Engagement Agreement</strong> firmado
          correspondiente al servicio <strong>{product_name}</strong>.
        </p>
        <table style="width:100%;border-collapse:collapse;margin:0 0 20px;font-size:13px;">
          <tr style="background:#e0e3ec;">
            <td style="padding:8px 12px;font-weight:600;color:#1A1A2E;">Ref. de acuerdo</td>
            <td style="padding:8px 12px;font-family:monospace;">{engagement_id}</td>
          </tr>
          <tr style="background:#eef0f8;">
            <td style="padding:8px 12px;font-weight:600;color:#1A1A2E;">Producto</td>
            <td style="padding:8px 12px;">{product_name}</td>
          </tr>
          <tr style="background:#e0e3ec;">
            <td style="padding:8px 12px;font-weight:600;color:#1A1A2E;">Total acordado</td>
            <td style="padding:8px 12px;color:#E94560;font-weight:700;">{total_amount} USD</td>
          </tr>
          <tr style="background:#eef0f8;">
            <td style="padding:8px 12px;font-weight:600;color:#1A1A2E;">Modalidad</td>
            <td style="padding:8px 12px;">{mode_label.capitalize()}</td>
          </tr>
        </table>
        <div style="background:#fff3cd;border-left:4px solid #f5a623;padding:12px 16px;border-radius:4px;margin-bottom:20px;">
          <p style="margin:0;font-size:13px;color:#7a4f00;">
            <strong>Próximo paso:</strong> Para activar el proyecto, enviá el comprobante del pago
            inicial al email <a href="mailto:{settings.EMAIL_PROVIDER_TO}" style="color:#7a4f00;">{settings.EMAIL_PROVIDER_TO}</a>
            o subilo desde el formulario.
          </p>
        </div>
        <p style="color:#888;font-size:12px;margin:0;">
          Este email es generado automáticamente. El NDA adjunto es válido como documento digital firmado.
        </p>
      </div>
      <div style="background:#1A1A2E;padding:14px 32px;border-radius:0 0 8px 8px;text-align:center;">
        <p style="color:#666;font-size:11px;margin:0;">
          Agraound Consulting / AETHERYON Systems — Confidential
        </p>
      </div>
    </div>
    """

    return await _send({
        "from": f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>",
        "to": [client_email],
        "subject": f"NDA firmado — {product_name} · Ref {engagement_id[:8].upper()}",
        "html": html_body,
        "attachments": [
            {
                "filename": f"NDA_Agraound_{engagement_id[:8].upper()}.pdf",
                "content": pdf_b64,
            }
        ],
    })


async def send_provider_notification(
    client_name: str,
    client_email: str,
    client_company: Optional[str],
    product_name: str,
    total_amount: str,
    payment_mode: str,
    engagement_id: str,
    custom_description: Optional[str] = None,
) -> bool:
    """Notify the provider that a new NDA was signed."""

    mode_label = "Pago por hitos" if payment_mode == "hitos" else "Pago único anticipado"
    custom_block = ""
    if custom_description:
        custom_block = f"""
        <tr style="background:#fff3cd;">
          <td style="padding:8px 12px;font-weight:600;color:#1A1A2E;">Descripción custom</td>
          <td style="padding:8px 12px;">{custom_description}</td>
        </tr>"""

    html_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
      <div style="background:#0F3460;padding:24px 32px;border-radius:8px 8px 0 0;">
        <p style="color:#aaaacc;font-size:11px;margin:0 0 6px;text-transform:uppercase;letter-spacing:0.1em;">
          Agraound — Panel interno
        </p>
        <h1 style="color:#ffffff;font-size:18px;margin:0;">&#9888; Nuevo NDA firmado</h1>
      </div>
      <div style="background:#f5f6fa;padding:28px 32px;">
        <table style="width:100%;border-collapse:collapse;font-size:13px;margin-bottom:20px;">
          <tr style="background:#e0e3ec;">
            <td style="padding:8px 12px;font-weight:600;">Ref. engagement</td>
            <td style="padding:8px 12px;font-family:monospace;">{engagement_id}</td>
          </tr>
          <tr style="background:#eef0f8;">
            <td style="padding:8px 12px;font-weight:600;">Cliente</td>
            <td style="padding:8px 12px;">{client_name}{' — ' + client_company if client_company else ''}</td>
          </tr>
          <tr style="background:#e0e3ec;">
            <td style="padding:8px 12px;font-weight:600;">Email</td>
            <td style="padding:8px 12px;"><a href="mailto:{client_email}">{client_email}</a></td>
          </tr>
          <tr style="background:#eef0f8;">
            <td style="padding:8px 12px;font-weight:600;">Producto</td>
            <td style="padding:8px 12px;">{product_name}</td>
          </tr>
          <tr style="background:#e0e3ec;">
            <td style="padding:8px 12px;font-weight:600;">Total</td>
            <td style="padding:8px 12px;color:#E94560;font-weight:700;">{total_amount} USD</td>
          </tr>
          <tr style="background:#eef0f8;">
            <td style="padding:8px 12px;font-weight:600;">Modalidad</td>
            <td style="padding:8px 12px;">{mode_label}</td>
          </tr>
          {custom_block}
        </table>
        <p style="color:#888;font-size:12px;">
          Verificar comprobante de pago y activar el proyecto desde el panel de administración.
        </p>
      </div>
    </div>
    """

    return await _send({
        "from": f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>",
        "to": [settings.EMAIL_PROVIDER_TO],
        "subject": f"[NUEVO NDA] {client_name} — {product_name} — {total_amount} USD",
        "html": html_body,
    })


async def send_payment_receipt_notification(
    engagement_id: str,
    client_name: str,
    client_email: str,
    milestone_label: str,
    amount: float,
    method: str,
    filename: str,
) -> bool:
    """Notify provider that a payment receipt was uploaded."""

    html_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
      <h2 style="color:#0F3460;">Comprobante de pago recibido</h2>
      <p><strong>Cliente:</strong> {client_name} ({client_email})</p>
      <p><strong>Engagement:</strong> <code>{engagement_id}</code></p>
      <p><strong>Hito:</strong> {milestone_label}</p>
      <p><strong>Monto:</strong> <span style="color:#E94560;font-weight:700;">${amount:,.2f} USD</span></p>
      <p><strong>Método:</strong> {method}</p>
      <p><strong>Archivo:</strong> {filename}</p>
      <hr>
      <p style="color:#888;font-size:12px;">Verificar y actualizar estado en el panel de administración.</p>
    </div>
    """

    return await _send({
        "from": f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>",
        "to": [settings.EMAIL_PROVIDER_TO],
        "subject": f"[COMPROBANTE] {client_name} — {milestone_label} — ${amount:,.0f} USD",
        "html": html_body,
    })
