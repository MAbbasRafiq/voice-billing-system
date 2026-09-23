"""FOC (free of cost) calculation."""

from __future__ import annotations


def calculate_foc(cp: float, qty: int, foc_qty: int | None, foc_units: int | None) -> list[dict]:
    """
    If qty purchased >= foc_qty threshold, admin gets foc_units free.
    Returns line items including FOC row if applicable.
    """
    lines = []
    line_total = round(float(cp) * int(qty), 2)
    lines.append(
        {
            "qty": int(qty),
            "unit_price": float(cp),
            "line_total": line_total,
            "is_foc": False,
        }
    )
    if foc_qty and foc_units and int(qty) >= int(foc_qty):
        lines.append(
            {
                "qty": int(foc_units),
                "unit_price": 0.0,
                "line_total": 0.0,
                "is_foc": True,
            }
        )
    return lines
