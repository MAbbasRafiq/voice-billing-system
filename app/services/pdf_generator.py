"""PDF bill generation with reportlab."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[2]
BILLS_DIR = ROOT / "data" / "bills"


def generate_bill_pdf(
    bill_id: int,
    customer: str | None,
    created_at: str | None,
    lines: list[dict],
    total: float,
    shop_name: str | None = None,
) -> str:
    BILLS_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = BILLS_DIR / f"bill_{bill_id}.pdf"
    shop = shop_name or os.getenv("SHOP_NAME", "Spare Parts Shop")

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph(shop, styles["Title"]))
    story.append(Paragraph(f"Bill #{bill_id}", styles["Heading2"]))
    story.append(
        Paragraph(
            f"Date: {created_at or datetime.now().strftime('%Y-%m-%d %H:%M')}",
            styles["Normal"],
        )
    )
    if customer:
        story.append(Paragraph(f"Customer: {customer}", styles["Normal"]))
    story.append(Spacer(1, 8 * mm))

    header = ["Item Code", "Model", "Name", "Qty", "Unit Price", "Line Total", ""]
    data = [header]
    for line in lines:
        foc_label = "FOC (Free)" if line.get("is_foc") else ""
        data.append(
            [
                str(line.get("item_code") or ""),
                str(line.get("model") or ""),
                str(line.get("name") or ""),
                str(line.get("qty") or ""),
                f"{float(line.get('unit_price') or 0):.2f}",
                f"{float(line.get('line_total') or 0):.2f}",
                foc_label,
            ]
        )
    data.append(["", "", "", "", "Grand Total", f"{float(total):.2f}", "PKR"])

    table = Table(data, colWidths=[70, 70, 160, 35, 65, 65, 55])
    style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("ALIGN", (3, 1), (5, -1), "RIGHT"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#e2e8f0")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for i, line in enumerate(lines, start=1):
        if line.get("is_foc"):
            style_commands.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#dcfce7")))
            style_commands.append(("TEXTCOLOR", (0, i), (-1, i), colors.HexColor("#166534")))

    table.setStyle(TableStyle(style_commands))
    story.append(table)
    doc.build(story)
    return str(pdf_path)
