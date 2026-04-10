import io
import base64
from datetime import datetime
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib import colors


W, H = A4
MARGIN = 18 * mm
BRAND_DARK = colors.HexColor("#1A1A2E")
BRAND_ACCENT = colors.HexColor("#E94560")
BRAND_MID = colors.HexColor("#0F3460")
GRAY_LIGHT = colors.HexColor("#F5F6FA")
GRAY_MID = colors.HexColor("#E0E3EC")
WHITE = colors.white
MUTED = colors.HexColor("#6B7280")


def _hex(h: str):
    return colors.HexColor(h)


def generate_nda_pdf(
    client_name: str,
    client_email: str,
    client_company: Optional[str],
    client_country: Optional[str],
    product_name: str,
    payment_mode: str,
    total_amount: Optional[float],
    discount_pct: float,
    milestones: list,
    signature_data: str,        # base64 PNG
    engagement_id: str,
    signed_at: Optional[datetime] = None,
) -> bytes:
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    _draw_page(c, client_name, client_email, client_company, client_country,
               product_name, payment_mode, total_amount, discount_pct,
               milestones, signature_data, engagement_id, signed_at)
    c.save()
    return buf.getvalue()


def _draw_page(c, client_name, client_email, client_company, client_country,
               product_name, payment_mode, total_amount, discount_pct,
               milestones, signature_data, engagement_id, signed_at):

    # ── Header bar ───────────────────────────────────────────────
    c.setFillColor(BRAND_DARK)
    c.rect(0, H - 32*mm, W, 32*mm, fill=1, stroke=0)
    c.setFillColor(BRAND_ACCENT)
    c.rect(0, H - 34.5*mm, W, 2.5*mm, fill=1, stroke=0)

    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor("#AAAACC"))
    c.drawCentredString(W/2, H - 10*mm, "AGRAOUND CONSULTING / AETHERYON SYSTEMS")
    c.setFont("Helvetica-Bold", 13)
    c.setFillColor(WHITE)
    c.drawCentredString(W/2, H - 18*mm, "NON-DISCLOSURE & ENGAGEMENT AGREEMENT")
    c.setFont("Helvetica", 8)
    c.setFillColor(colors.HexColor("#AAAACC"))
    c.drawCentredString(W/2, H - 25*mm, "Signed copy — Confidential")

    y = H - 40*mm

    # ── Info block ───────────────────────────────────────────────
    box_h = 50*mm
    c.setFillColor(GRAY_LIGHT)
    c.roundRect(MARGIN, y - box_h, W - 2*MARGIN, box_h, 3*mm, fill=1, stroke=0)

    today = (signed_at or datetime.utcnow()).strftime("%d de %B de %Y")
    mode_label = "Pago por hitos (3 cuotas)" if payment_mode == "hitos" else "Pago único anticipado"
    amount_str = f"${total_amount:,.2f}" if total_amount else "A cotizar"
    company_str = f" — {client_company}" if client_company else ""

    fields = [
        ("Cliente",              f"{client_name}{company_str}"),
        ("Email",                client_email),
        ("País / Jurisdicción",  client_country or "N/D"),
        ("Producto contratado",  product_name),
        ("Modalidad de pago",    mode_label),
        ("Total acordado",       f"{amount_str} USD"),
        ("Referencia",           engagement_id[:16].upper()),
        ("Fecha de firma",       today),
    ]

    fy = y - 8*mm
    for label, val in fields:
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(BRAND_MID)
        c.drawString(MARGIN + 4*mm, fy, label + ":")
        c.setFont("Helvetica", 8)
        c.setFillColor(BRAND_DARK)
        c.drawString(MARGIN + 52*mm, fy, val[:70])
        fy -= 5.5*mm

    y = y - box_h - 8*mm

    # ── NDA Title ────────────────────────────────────────────────
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(BRAND_DARK)
    c.drawCentredString(W/2, y, "NON-DISCLOSURE & ENGAGEMENT AGREEMENT")
    y -= 5*mm
    c.setFont("Helvetica", 7.5)
    c.setFillColor(MUTED)
    intro = (f"Este acuerdo es celebrado entre Agraound Consulting / AETHERYON Systems "
             f"y {client_name}, con fecha {today}.")
    _wrapped_text(c, intro, MARGIN, y, W - 2*MARGIN, 7.5, MUTED, line_height=4.5*mm)
    y -= 10*mm

    # ── Clauses ──────────────────────────────────────────────────
    clauses = [
        ("1. Objeto.",
         "Evaluación, desarrollo e implementación de sistemas de datos, APIs y/o código según la propuesta aceptada."),
        ("2. Información Confidencial.",
         "Incluye datasets, bases de código, infraestructura, credenciales e información de negocio compartida entre las partes."),
        ("3. Obligaciones.",
         "Uso exclusivo para los fines del proyecto. Prohibida toda divulgación. Aplicar medidas razonables de protección."),
        ("4. Acceso & Seguridad.",
         "Acceso de solo lectura cuando sea posible. Sin evasión de seguridad. Las vulnerabilidades encontradas serán reportadas."),
        ("5. Exclusiones.",
         "Información pública, conocimiento previo, desarrollo independiente o divulgación legal obligatoria."),
        ("6. Vigencia.",
         "Válido por 2 años. La confidencialidad persiste tras la terminación del acuerdo."),
        ("7. Manejo de Datos.",
         "Usados únicamente durante el proyecto. Eliminados bajo solicitud. Sin retención innecesaria."),
        ("8. Condiciones de Pago.",
         "40% al firmar, 30% en hito intermedio, 30% en entrega final. El trabajo comienza después del pago inicial."),
        ("9. Sin Transferencia de PI.",
         "No se transfieren derechos de propiedad intelectual salvo acuerdo escrito adicional."),
        ("10. Limitación de Responsabilidad.",
         "Sin responsabilidad por daños indirectos o consecuentes."),
        ("11. Ley Aplicable.",
         client_country or "[Jurisdicción a definir]"),
        ("12. Aceptación.",
         "Este acuerdo es válido mediante firma digital. La ejecución del pago inicial implica aceptación total."),
    ]

    for num, text in clauses:
        if y < 70*mm:
            c.showPage()
            y = H - MARGIN
        c.setFont("Helvetica-Bold", 8.5)
        c.setFillColor(BRAND_DARK)
        num_w = c.stringWidth(num, "Helvetica-Bold", 8.5)
        c.drawString(MARGIN, y, num)
        c.setFont("Helvetica", 8.5)
        c.setFillColor(colors.HexColor("#3C3C50"))
        lines = _wrap(text, W - 2*MARGIN - num_w - 2*mm, "Helvetica", 8.5, c)
        c.drawString(MARGIN + num_w + 2*mm, y, lines[0])
        for line in lines[1:]:
            y -= 4.5*mm
            c.drawString(MARGIN + num_w + 2*mm, y, line)
        y -= 7*mm

    # ── Milestone table ──────────────────────────────────────────
    if y < 60*mm:
        c.showPage()
        y = H - MARGIN

    y -= 3*mm
    c.setFillColor(BRAND_MID)
    c.rect(MARGIN, y - 6*mm, W - 2*MARGIN, 6*mm, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(WHITE)
    c.drawString(MARGIN + 3*mm, y - 4.5*mm, "Hito")
    c.drawString(MARGIN + 70*mm, y - 4.5*mm, "%")
    c.drawString(MARGIN + 90*mm, y - 4.5*mm, "Monto (USD)")
    y -= 6*mm

    for i, m in enumerate(milestones):
        fill_col = GRAY_LIGHT if i % 2 == 0 else WHITE
        c.setFillColor(fill_col)
        c.rect(MARGIN, y - 5.5*mm, W - 2*MARGIN, 5.5*mm, fill=1, stroke=0)
        amt = (total_amount or 0) * m["pct"] / 100 if total_amount else 0
        c.setFont("Helvetica", 8)
        c.setFillColor(BRAND_DARK)
        c.drawString(MARGIN + 3*mm, y - 4*mm, m["label"])
        c.drawString(MARGIN + 70*mm, y - 4*mm, f"{m['pct']:.0f}%")
        c.drawString(MARGIN + 90*mm, y - 4*mm, f"${amt:,.2f}" if total_amount else "A cotizar")
        y -= 5.5*mm

    # Total row
    c.setFillColor(BRAND_DARK)
    c.rect(MARGIN, y - 6*mm, W - 2*MARGIN, 6*mm, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(WHITE)
    c.drawString(MARGIN + 3*mm, y - 4.5*mm, "TOTAL")
    c.setFillColor(BRAND_ACCENT)
    total_str = f"${total_amount:,.2f} USD" if total_amount else "A cotizar"
    c.drawString(MARGIN + 90*mm, y - 4.5*mm, total_str)
    y -= 10*mm

    # ── Signature section ────────────────────────────────────────
    if y < 55*mm:
        c.showPage()
        y = H - MARGIN

    c.setStrokeColor(GRAY_MID)
    c.line(MARGIN, y, W - MARGIN, y)
    y -= 7*mm

    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(BRAND_DARK)
    c.drawString(MARGIN, y, "Firma Digital del Cliente")

    # Embed signature image
    sig_ok = False
    if signature_data:
        try:
            raw = signature_data
            if "," in raw:
                raw = raw.split(",", 1)[1]
            sig_bytes = base64.b64decode(raw)
            sig_buf = io.BytesIO(sig_bytes)
            y -= 3*mm
            c.drawImage(sig_buf, MARGIN, y - 22*mm, width=75*mm, height=22*mm,
                        preserveAspectRatio=True, mask="auto")
            y -= 25*mm
            sig_ok = True
        except Exception as e:
            print(f"[PDF] Signature embed failed: {e}")

    if not sig_ok:
        y -= 20*mm

    c.setFont("Helvetica", 8)
    c.setFillColor(MUTED)
    signed_str = (signed_at or datetime.utcnow()).strftime("%d/%m/%Y %H:%M UTC")
    c.drawString(MARGIN, y, f"Firmado por: {client_name}")
    y -= 5*mm
    c.drawString(MARGIN, y, f"Email: {client_email}")
    y -= 5*mm
    c.drawString(MARGIN, y, f"Fecha y hora: {signed_str}")
    y -= 5*mm
    c.drawString(MARGIN, y, f"Referencia: {engagement_id[:24].upper()}")

    # Provider sig line
    sig_x = W - MARGIN - 65*mm
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(BRAND_DARK)
    c.drawString(sig_x, y + 20*mm, "Agraound Consulting /")
    c.drawString(sig_x, y + 15*mm, "AETHERYON Systems")
    c.setStrokeColor(MUTED)
    c.line(sig_x, y + 10*mm, sig_x + 60*mm, y + 10*mm)
    c.setFont("Helvetica", 7.5)
    c.setFillColor(MUTED)
    c.drawString(sig_x, y + 7*mm, "Firma del proveedor")

    # ── Footer ───────────────────────────────────────────────────
    c.setFillColor(BRAND_DARK)
    c.rect(0, 0, W, 12*mm, fill=1, stroke=0)
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor("#666688"))
    c.drawCentredString(W/2, 4.5*mm,
        "Confidencial — Agraound Consulting / AETHERYON Systems — agraound.com")


def _wrap(text: str, max_w: float, font: str, size: float, c) -> list:
    words = text.split()
    lines, line = [], ""
    for w in words:
        test = (line + " " + w).strip()
        if c.stringWidth(test, font, size) <= max_w:
            line = test
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines or [""]


def _wrapped_text(c, text, x, y, max_w, size, color, line_height=5*mm):
    lines = _wrap(text, max_w, "Helvetica", size, c)
    c.setFont("Helvetica", size)
    c.setFillColor(color)
    for line in lines:
        c.drawString(x, y, line)
        y -= line_height
