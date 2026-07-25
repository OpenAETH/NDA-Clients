import io
import base64
from datetime import datetime
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader


W, H = A4
MARGIN = 18 * mm

# ── i18n del PDF ───────────────────────────────────────────────────
# Todo el texto fijo del documento, por idioma. El contenido dinámico
# (nombre, producto, milestones) ya llega localizado desde el router.
MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
             "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

PDF_STRINGS = {
    "en": {
        "signed_copy":   "Signed copy — Confidential",
        "field_client":  "Client",
        "field_email":   "Email",
        "field_country": "Country / Jurisdiction",
        "field_product": "Contracted product",
        "field_requirement": "Requirement",
        "field_mode":    "Payment mode",
        "field_total":   "Agreed total",
        "field_ref":     "Reference",
        "field_signed_date": "Signature date",
        "mode_hitos":    "Milestone payment (3 installments)",
        "mode_anticipado": "Single upfront payment",
        "to_quote":      "To be quoted",
        "na":            "N/A",
        "milestone_when": ["On signing", "On progress", "On completion"],
        "intro":         "This agreement is entered into between Agraound Consulting / AETHERYON Systems and {client}, dated {date}.",
        "th_milestone":  "Milestone",
        "th_when":       "When",
        "th_amount":     "Amount (USD)",
        "total":         "TOTAL",
        "pay_section":   "Agreed payment method",
        "pay_mode":      "Mode",
        "pay_method":    "Method",
        "pay_token":     "Token",
        "pay_network":   "Network",
        "pay_address":   "Address",
        "sig_title":     "Client Digital Signature",
        "signed_by":     "Signed by: {name}",
        "email_line":    "Email: {email}",
        "datetime_line": "Date and time: {dt}",
        "ref_line":      "Reference: {ref}",
        "provider_sig":  "Provider signature",
        "footer":        "Confidential — Agraound Consulting / AETHERYON Systems — agraound.com",
        "juris_default": "[Jurisdiction to be defined]",
        "clauses": [
            ("1. Purpose.",
             "Evaluation, development and implementation of data systems, APIs and/or code per the accepted proposal."),
            ("2. Confidential Information.",
             "Includes datasets, codebases, infrastructure, credentials and business information shared between the parties."),
            ("3. Obligations.",
             "Exclusive use for the purposes of the project. All disclosure prohibited. Reasonable protection measures applied."),
            ("4. Access & Security.",
             "Read-only access where possible. No security bypass. Any vulnerabilities found will be reported."),
            ("5. Exclusions.",
             "Public information, prior knowledge, independent development or legally mandated disclosure."),
            ("6. Term.",
             "Valid for 2 years. Confidentiality survives termination of the agreement."),
            ("7. Data Handling.",
             "Used only during the project. Deleted upon request. No unnecessary retention."),
            ("8. Payment Terms.",
             "40% on signing, 30% at intermediate milestone, 30% on final delivery. Work begins after the initial payment."),
            ("9. No IP Transfer.",
             "No intellectual property rights are transferred except by additional written agreement."),
            ("10. Limitation of Liability.",
             "No liability for indirect or consequential damages."),
            ("12. Acceptance.",
             "This agreement is valid via digital signature. Execution of the initial payment implies full acceptance."),
        ],
        "clause11_num":  "11. Governing Law.",
    },
    "es": {
        "signed_copy":   "Copia firmada — Confidencial",
        "field_client":  "Cliente",
        "field_email":   "Email",
        "field_country": "País / Jurisdicción",
        "field_product": "Producto contratado",
        "field_requirement": "Requerimiento",
        "field_mode":    "Modalidad de pago",
        "field_total":   "Total acordado",
        "field_ref":     "Referencia",
        "field_signed_date": "Fecha de firma",
        "mode_hitos":    "Pago por hitos (3 cuotas)",
        "mode_anticipado": "Pago único anticipado",
        "to_quote":      "A cotizar",
        "na":            "N/D",
        "milestone_when": ["Al firmar", "Al avanzar", "Al finalizar"],
        "intro":         "Este acuerdo es celebrado entre Agraound Consulting / AETHERYON Systems y {client}, con fecha {date}.",
        "th_milestone":  "Hito",
        "th_when":       "Cuándo",
        "th_amount":     "Monto (USD)",
        "total":         "TOTAL",
        "pay_section":   "Medio de pago acordado",
        "pay_mode":      "Modalidad",
        "pay_method":    "Método",
        "pay_token":     "Token",
        "pay_network":   "Red",
        "pay_address":   "Dirección",
        "sig_title":     "Firma Digital del Cliente",
        "signed_by":     "Firmado por: {name}",
        "email_line":    "Email: {email}",
        "datetime_line": "Fecha y hora: {dt}",
        "ref_line":      "Referencia: {ref}",
        "provider_sig":  "Firma del proveedor",
        "footer":        "Confidencial — Agraound Consulting / AETHERYON Systems — agraound.com",
        "juris_default": "[Jurisdicción a definir]",
        "clauses": [
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
            ("12. Aceptación.",
             "Este acuerdo es válido mediante firma digital. La ejecución del pago inicial implica aceptación total."),
        ],
        "clause11_num":  "11. Ley Aplicable.",
    },
}


def _strings(lang: str) -> dict:
    return PDF_STRINGS.get(lang) if lang in PDF_STRINGS else PDF_STRINGS["en"]


def _format_signed_date(dt, lang: str) -> str:
    """Fecha larga localizada (sin depender del locale del sistema)."""
    if lang == "es":
        return f"{dt.day} de {MONTHS_ES[dt.month - 1]} de {dt.year}"
    return dt.strftime("%B %d, %Y")


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
    custom_description: Optional[str] = None,
    payment_details: Optional[dict] = None,
    lang: str = "en",
) -> bytes:
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    _draw_page(c, client_name, client_email, client_company, client_country,
               product_name, payment_mode, total_amount, discount_pct,
               milestones, signature_data, engagement_id, signed_at,
               custom_description, payment_details, lang)
    c.save()
    return buf.getvalue()


def _draw_page(c, client_name, client_email, client_company, client_country,
               product_name, payment_mode, total_amount, discount_pct,
               milestones, signature_data, engagement_id, signed_at,
               custom_description=None, payment_details=None, lang="en"):

    S = _strings(lang)
    MILESTONE_WHEN = S["milestone_when"]

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
    c.drawCentredString(W/2, H - 25*mm, S["signed_copy"])

    y = H - 40*mm

    # ── Info block ───────────────────────────────────────────────
    today = _format_signed_date(signed_at or datetime.utcnow(), lang)
    mode_label = S["mode_hitos"] if payment_mode == "hitos" else S["mode_anticipado"]
    amount_str = f"${total_amount:,.2f}" if total_amount else S["to_quote"]
    company_str = f" — {client_company}" if client_company else ""

    fields = [
        (S["field_client"],   f"{client_name}{company_str}"),
        (S["field_email"],    client_email),
        (S["field_country"],  client_country or S["na"]),
        (S["field_product"],  product_name),
    ]
    if custom_description:
        fields.append((S["field_requirement"], custom_description))
    fields += [
        (S["field_mode"],        mode_label),
        (S["field_total"],       f"{amount_str} USD" if total_amount else amount_str),
        (S["field_ref"],         engagement_id[:16].upper()),
        (S["field_signed_date"], today),
    ]

    box_h = (len(fields) * 5.5 + 5) * mm
    c.setFillColor(GRAY_LIGHT)
    c.roundRect(MARGIN, y - box_h, W - 2*MARGIN, box_h, 3*mm, fill=1, stroke=0)

    fy = y - 7*mm
    for label, val in fields:
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(BRAND_MID)
        c.drawString(MARGIN + 4*mm, fy, label + ":")
        c.setFont("Helvetica", 8)
        c.setFillColor(BRAND_DARK)
        c.drawString(MARGIN + 52*mm, fy, str(val)[:70])
        fy -= 5.5*mm

    y = y - box_h - 8*mm

    # ── NDA Title ────────────────────────────────────────────────
    c.setFont("Helvetica-Bold", 10)
    c.setFillColor(BRAND_DARK)
    c.drawCentredString(W/2, y, "NON-DISCLOSURE & ENGAGEMENT AGREEMENT")
    y -= 5*mm
    c.setFont("Helvetica", 7.5)
    c.setFillColor(MUTED)
    intro = S["intro"].format(client=client_name, date=today)
    _wrapped_text(c, intro, MARGIN, y, W - 2*MARGIN, 7.5, MUTED, line_height=4.5*mm)
    y -= 10*mm

    # ── Clauses ──────────────────────────────────────────────────
    # Cláusulas fijas (localizadas) + la 11 (ley aplicable) intercalada con la
    # jurisdicción concreta del cliente, respetando el orden numérico.
    clauses = list(S["clauses"])
    clauses.insert(10, (S["clause11_num"], client_country or S["juris_default"]))

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
    c.drawString(MARGIN + 3*mm, y - 4.5*mm, S["th_milestone"])
    c.drawString(MARGIN + 60*mm, y - 4.5*mm, "%")
    c.drawString(MARGIN + 74*mm, y - 4.5*mm, S["th_when"])
    c.drawString(MARGIN + 118*mm, y - 4.5*mm, S["th_amount"])
    y -= 6*mm

    for i, m in enumerate(milestones):
        fill_col = GRAY_LIGHT if i % 2 == 0 else WHITE
        c.setFillColor(fill_col)
        c.rect(MARGIN, y - 5.5*mm, W - 2*MARGIN, 5.5*mm, fill=1, stroke=0)
        amt = (total_amount or 0) * m["pct"] / 100 if total_amount else 0
        c.setFont("Helvetica", 8)
        c.setFillColor(BRAND_DARK)
        c.drawString(MARGIN + 3*mm, y - 4*mm, m["label"])
        c.drawString(MARGIN + 60*mm, y - 4*mm, f"{m['pct']:.0f}%")
        c.drawString(MARGIN + 74*mm, y - 4*mm, MILESTONE_WHEN[i] if i < len(MILESTONE_WHEN) else "")
        c.drawString(MARGIN + 118*mm, y - 4*mm, f"${amt:,.2f}" if total_amount else S["to_quote"])
        y -= 5.5*mm

    # Total row
    c.setFillColor(BRAND_DARK)
    c.rect(MARGIN, y - 6*mm, W - 2*MARGIN, 6*mm, fill=1, stroke=0)
    c.setFont("Helvetica-Bold", 8.5)
    c.setFillColor(WHITE)
    c.drawString(MARGIN + 3*mm, y - 4.5*mm, S["total"])
    c.setFillColor(BRAND_ACCENT)
    total_str = f"${total_amount:,.2f} USD" if total_amount else S["to_quote"]
    c.drawString(MARGIN + 118*mm, y - 4.5*mm, total_str)
    y -= 10*mm

    # ── Medio de pago acordado ───────────────────────────────────
    # Detalle del método/medio elegido por el cliente (fiat o cripto), para
    # que el documento firmado contenga todos los datos del acuerdo.
    pay_rows = _payment_rows(payment_mode, payment_details, S)
    if pay_rows:
        if y < 60*mm:
            c.showPage()
            y = H - MARGIN
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(BRAND_DARK)
        c.drawString(MARGIN, y, S["pay_section"])
        y -= 6*mm
        for label, val in pay_rows:
            if y < 30*mm:
                c.showPage()
                y = H - MARGIN
            c.setFont("Helvetica-Bold", 8)
            c.setFillColor(BRAND_MID)
            c.drawString(MARGIN + 2*mm, y, label + ":")
            c.setFont("Helvetica", 8)
            c.setFillColor(BRAND_DARK)
            lines = _wrap(str(val), W - 2*MARGIN - 52*mm, "Helvetica", 8, c)
            c.drawString(MARGIN + 52*mm, y, lines[0])
            for line in lines[1:]:
                y -= 4.5*mm
                c.drawString(MARGIN + 52*mm, y, line)
            y -= 5.5*mm
        y -= 4*mm

    # ── Signature section ────────────────────────────────────────
    if y < 55*mm:
        c.showPage()
        y = H - MARGIN

    c.setStrokeColor(GRAY_MID)
    c.line(MARGIN, y, W - MARGIN, y)
    y -= 7*mm

    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(BRAND_DARK)
    c.drawString(MARGIN, y, S["sig_title"])

    # Embed signature image
    sig_ok = False
    if signature_data:
        try:
            raw = signature_data
            if "," in raw:
                raw = raw.split(",", 1)[1]
            sig_bytes = base64.b64decode(raw)
            # ReportLab drawImage necesita un ImageReader (o ruta), no un
            # BytesIO crudo — de lo contrario falla con "expected str, bytes
            # or os.PathLike object, not BytesIO".
            sig_img = ImageReader(io.BytesIO(sig_bytes))
            y -= 3*mm
            c.drawImage(sig_img, MARGIN, y - 22*mm, width=75*mm, height=22*mm,
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
    c.drawString(MARGIN, y, S["signed_by"].format(name=client_name))
    y -= 5*mm
    c.drawString(MARGIN, y, S["email_line"].format(email=client_email))
    y -= 5*mm
    c.drawString(MARGIN, y, S["datetime_line"].format(dt=signed_str))
    y -= 5*mm
    c.drawString(MARGIN, y, S["ref_line"].format(ref=engagement_id[:24].upper()))

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
    c.drawString(sig_x, y + 7*mm, S["provider_sig"])

    # ── Footer ───────────────────────────────────────────────────
    c.setFillColor(BRAND_DARK)
    c.rect(0, 0, W, 12*mm, fill=1, stroke=0)
    c.setFont("Helvetica", 7)
    c.setFillColor(colors.HexColor("#666688"))
    c.drawCentredString(W/2, 4.5*mm, S["footer"])


def _payment_rows(payment_mode, payment_details, S) -> list:
    """Pares [etiqueta, valor] con el medio de pago elegido (fiat o cripto)."""
    rows = []
    rows.append((
        S["pay_mode"],
        S["mode_hitos"] if payment_mode == "hitos" else S["mode_anticipado"],
    ))
    if not payment_details:
        return rows

    pd = payment_details
    if pd.get("method_label"):
        rows.append((S["pay_method"], pd["method_label"]))

    if (pd.get("currency") or "").upper() == "CRYPTO":
        if pd.get("token"):
            rows.append((S["pay_token"], pd["token"]))
        if pd.get("network"):
            rows.append((S["pay_network"], pd["network"]))
        if pd.get("address"):
            rows.append((S["pay_address"], pd["address"]))
    else:
        for f in (pd.get("fields") or []):
            if f.get("value"):
                rows.append((f.get("label", ""), f["value"]))
    return rows


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
