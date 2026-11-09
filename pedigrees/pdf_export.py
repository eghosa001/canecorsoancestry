"""Mobile-viewable, printable pedigree PDF with a complete ancestry directory.

The first page preserves the four-generation family-tree relationships on an
A3 landscape sheet. Subsequent A4 portrait pages enumerate *every recorded
ancestry position* for the selected depth (4/5/6/8/10), including repeats.
The same visibility/auth policies as the existing CSV export apply at views.
"""
from io import BytesIO
from pathlib import Path

from django.http import HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, A4, landscape
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from .services import pedigree_export_rows

DARK = colors.HexColor("#17382F")
GREEN = colors.HexColor("#1E6B50")
LIGHT = colors.HexColor("#E9F1EC")
MUTED = colors.HexColor("#52645D")
FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"


def _fonts():
    """Use embedded Unicode fonts where available for names and kennel data."""
    global FONT_REGULAR, FONT_BOLD
    regular = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    bold = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    if regular.is_file() and bold.is_file():
        if "PedigreeSans" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("PedigreeSans", str(regular)))
            pdfmetrics.registerFont(TTFont("PedigreeSansBold", str(bold)))
        FONT_REGULAR, FONT_BOLD = "PedigreeSans", "PedigreeSansBold"


def _fit(value, font, size, width):
    """Shorten only visual chart labels; directory retains complete values."""
    value = str(value or "Not recorded").replace("\n", " ").strip()
    if pdfmetrics.stringWidth(value, font, size) <= width:
        return value
    while value and pdfmetrics.stringWidth(value + "...", font, size) > width:
        value = value[:-1]
    return value.rstrip() + "..."


def _path(generation, index):
    return " → ".join(
        "Dam" if (index >> shift) & 1 else "Sire"
        for shift in range(generation - 1, -1, -1)
    ) if generation else "Subject"


def _chart_page(pdf, dog, generations, positions, is_private):
    width, height = landscape(A3)
    pdf.setPageSize((width, height))
    pdf.setFillColor(DARK)
    pdf.rect(0, height - 95, width, 95, fill=1, stroke=0)
    pdf.setFont(FONT_BOLD, 20)
    pdf.setFillColor(colors.white)
    pdf.drawString(34, height - 38, _fit(dog.name, FONT_BOLD, 20, width - 68))
    pdf.setFont(FONT_REGULAR, 10)
    pdf.drawString(34, height - 61, f"Pedigree chart | {generations} generations selected")
    pdf.drawString(34, height - 78, "Private member pedigree - share carefully" if is_private else "Publicly visible ancestry only")

    left, right = 35, width - 35
    top, bottom = height - 139, 75
    chart_height = top - bottom
    column_width = (right - left) / 5
    card_width = column_width - 29

    for gen, heading in enumerate(("Dog", "Parents", "Grandparents", "Great-grandparents", "4th generation")):
        pdf.setFont(FONT_BOLD, 10)
        pdf.setFillColor(GREEN)
        pdf.drawCentredString(left + column_width * (gen + 0.5), height - 122, heading)

    def center_y(gen, i):
        return top - (i + 0.5) * chart_height / (2 ** gen)

    # Draw relationship lines first so every node remains legible.
    pdf.setStrokeColor(colors.HexColor("#A5BBAF"))
    pdf.setLineWidth(0.65)
    for gen in range(4):
        for i in range(2 ** gen):
            x1 = left + (gen + 1) * column_width - 26
            x2 = left + (gen + 1) * column_width + 12
            y1 = center_y(gen, i)
            for child_index in (i * 2, i * 2 + 1):
                y2 = center_y(gen + 1, child_index)
                pdf.line(x1, y1, x1 + 12, y1)
                pdf.line(x1 + 12, y1, x1 + 12, y2)
                pdf.line(x1 + 12, y2, x2, y2)

    for gen in range(5):
        span = chart_height / (2 ** gen)
        box_height = min(44, span - 6)
        for i in range(2 ** gen):
            x = left + gen * column_width + 7
            y = center_y(gen, i) - box_height / 2
            record = positions.get((gen, _path(gen, i)))
            pdf.setFillColor(colors.white if record else colors.HexColor("#F5F7F5"))
            pdf.setStrokeColor(GREEN if record else colors.HexColor("#D5DEDA"))
            pdf.roundRect(x, y, card_width, box_height, 5, fill=1, stroke=1)
            name = record["name"] if record else "Not recorded"
            font_size = 9 if gen < 3 else 7.1
            pdf.setFillColor(DARK if record else MUTED)
            pdf.setFont(FONT_BOLD if record else FONT_REGULAR, font_size)
            pdf.drawString(x + 6, y + box_height / 2 + 2, _fit(name, FONT_BOLD if record else FONT_REGULAR, font_size, card_width - 12))
            if record and box_height >= 30:
                pdf.setFont(FONT_REGULAR, 7)
                pdf.setFillColor(MUTED)
                extra = (record.get("sex") or "") + (" | Repeated" if record.get("repeated") == "yes" else "")
                pdf.drawString(x + 6, y + box_height / 2 - 10, _fit(extra, FONT_REGULAR, 7, card_width - 12))
    pdf.setFillColor(MUTED)
    pdf.setFont(FONT_REGULAR, 9)
    pdf.drawString(35, 48, "Unknown ancestors are shown as 'Not recorded', not invented.")
    pdf.drawString(35, 32, "The complete recorded ancestry through the selected depth follows on subsequent pages.")
    pdf.setFont(FONT_BOLD, 9)
    pdf.drawRightString(width - 35, 33, "1")
    pdf.showPage()


def _directory(pdf, dog, generations, rows, is_private):
    width, height = A4
    pdf.setPageSize(A4)
    left, right = 39, width - 39
    max_width = right - left
    page = 2
    y = 0

    def heading():
        nonlocal y
        pdf.setFillColor(DARK)
        pdf.rect(0, height - 85, width, 85, stroke=0, fill=1)
        pdf.setFillColor(colors.white)
        pdf.setFont(FONT_BOLD, 14)
        pdf.drawString(left, height - 33, "Complete recorded ancestry")
        pdf.setFont(FONT_REGULAR, 9)
        pdf.drawString(left, height - 51, _fit(dog.name, FONT_REGULAR, 9, max_width))
        pdf.drawString(left, height - 66, f"{generations} generations | {len(rows)} recorded positions" +
                       (" | Private" if is_private else " | Public"))
        pdf.setFont(FONT_REGULAR, 8)
        pdf.setFillColor(MUTED)
        pdf.drawRightString(right, 27, f"Page {page}")
        y = height - 109

    heading()
    if not rows:
        pdf.setFillColor(MUTED)
        pdf.setFont(FONT_REGULAR, 11)
        pdf.drawString(left, y, "No recorded ancestors are available.")
    for row in rows:
        relation = row["path"]
        # Long relationship paths and full kennel names wrap rather than clip.
        relation_lines = simpleSplit(relation, FONT_REGULAR, 8, max_width - 5)
        name = str(row.get("name") or "Not recorded")
        meta = " | ".join(
            part for part in (
                str(row.get("sex") or ""),
                str(row.get("date_of_birth") or ""),
                str(row.get("country") or ""),
                ("Repeated ancestor" if row.get("repeated") == "yes" else ""),
            ) if part
        )
        name_lines = simpleSplit(name, FONT_BOLD, 9, max_width - 10)
        meta_lines = simpleSplit(meta, FONT_REGULAR, 7.3, max_width - 10) if meta else []
        kennel = str(row.get("kennel") or "")
        kennel_lines = simpleSplit("Kennel: " + kennel, FONT_REGULAR, 7.3, max_width - 10) if kennel else []
        block_height = 36 + 10 * len(relation_lines) + 12 * len(name_lines) + 10 * (len(meta_lines) + len(kennel_lines))
        if y - block_height < 51:
            pdf.showPage()
            page += 1
            heading()
        pdf.setFillColor(LIGHT)
        pdf.roundRect(left, y - 15, max_width, 17, 3, fill=1, stroke=0)
        pdf.setFillColor(GREEN)
        pdf.setFont(FONT_BOLD, 8)
        pdf.drawString(left + 6, y - 10, f"Generation {row['generation']}")
        y -= 24
        pdf.setFillColor(MUTED)
        pdf.setFont(FONT_REGULAR, 8)
        for line in relation_lines:
            pdf.drawString(left + 4, y, line)
            y -= 10
        pdf.setFillColor(DARK)
        pdf.setFont(FONT_BOLD, 9)
        for line in name_lines:
            pdf.drawString(left + 4, y, line)
            y -= 12
        pdf.setFillColor(MUTED)
        pdf.setFont(FONT_REGULAR, 7.3)
        for line in meta_lines + kennel_lines:
            pdf.drawString(left + 4, y, line)
            y -= 10
        y -= 12
    pdf.save()


def pedigree_pdf_response(dog, generations, *, public_only=True):
    """A real PDF download that phones can open without a spreadsheet app."""
    _fonts()
    rows = pedigree_export_rows(dog, generations, public_only=public_only)
    positions = {(int(r["generation"]), r["path"]): r for r in rows}
    output = BytesIO()
    pdf = Canvas(output, pagesize=landscape(A3), pageCompression=1)
    pdf.setTitle(f"{dog.name} - {generations} generation pedigree")
    pdf.setAuthor("Cane Corso Ancestry")
    pdf.setSubject("Family-tree chart and complete recorded pedigree positions")
    _chart_page(pdf, dog, generations, positions, is_private=not public_only)
    _directory(pdf, dog, generations, rows, is_private=not public_only)
    response = HttpResponse(output.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="{dog.slug}-pedigree-{generations}g.pdf"'
    )
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, no-store"
    return response
