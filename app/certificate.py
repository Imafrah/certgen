"""Certificate rendering. One fixed template, drawn with reportlab (PDF)."""
from datetime import date
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

NAVY = HexColor("#1f3a5f")
GOLD = HexColor("#b8923a")
GREY = HexColor("#555555")


def _fit_font_size(text: str, font: str, max_size: int, max_width: float) -> int:
    size = max_size
    while size > 12 and stringWidth(text, font, size) > max_width:
        size -= 1
    return size


def render_certificate(
    path: Path,
    *,
    name: str,
    event_name: str,
    issuer: str,
    issue_date: date,
    course: str | None = None,
) -> None:
    """Write a single-page landscape A4 PDF certificate to `path`."""
    width, height = landscape(A4)
    cx = width / 2
    c = canvas.Canvas(str(path), pagesize=(width, height))
    c.setTitle(f"Certificate - {name}")

    # Double border
    c.setStrokeColor(GOLD)
    c.setLineWidth(4)
    c.rect(25, 25, width - 50, height - 50)
    c.setStrokeColor(NAVY)
    c.setLineWidth(1)
    c.rect(36, 36, width - 72, height - 72)

    max_w = width - 160

    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 40)
    c.drawCentredString(cx, height - 130, "CERTIFICATE")
    c.setFont("Helvetica", 16)
    c.setFillColor(GOLD)
    c.drawCentredString(cx, height - 158, "OF PARTICIPATION")

    c.setFillColor(GREY)
    c.setFont("Helvetica", 14)
    c.drawCentredString(cx, height - 210, "This is proudly presented to")

    c.setFillColor(NAVY)
    size = _fit_font_size(name, "Helvetica-Bold", 38, max_w)
    c.setFont("Helvetica-Bold", size)
    c.drawCentredString(cx, height - 262, name)
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.5)
    c.line(cx - 220, height - 275, cx + 220, height - 275)

    c.setFillColor(GREY)
    c.setFont("Helvetica", 14)
    c.drawCentredString(cx, height - 315, "for participating in")

    c.setFillColor(NAVY)
    size = _fit_font_size(event_name, "Helvetica-Bold", 24, max_w)
    c.setFont("Helvetica-Bold", size)
    c.drawCentredString(cx, height - 350, event_name)

    if course:
        c.setFillColor(GREY)
        size = _fit_font_size(course, "Helvetica-Oblique", 15, max_w)
        c.setFont("Helvetica-Oblique", size)
        c.drawCentredString(cx, height - 378, course)

    # Footer: date and issuer
    c.setFillColor(GREY)
    c.setFont("Helvetica", 12)
    c.drawString(90, 85, f"Date: {issue_date.strftime('%d %B %Y')}")
    c.drawRightString(width - 90, 85, f"Issued by: {issuer}"[:70])

    c.showPage()
    c.save()
