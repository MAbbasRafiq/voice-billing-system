# -*- coding: utf-8 -*-
"""Polish a few transliteration glitches after fill_missing_urdu."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openpyxl import load_workbook

from app.database.connection import get_connection
from app.database.queries import invalidate_items_cache
from scripts.fill_missing_urdu import transliterate_name

EXCEL = ROOT / "data" / "C_P_LIST.xlsx"


def main() -> None:
    conn = get_connection()
    # Fix MT size token wrongly phoneticized
    conn.execute(
        "UPDATE items SET urdu_name = REPLACE(urdu_name, 'مٹ', 'MT') "
        "WHERE urdu_name LIKE '%مٹ%'"
    )
    # Re-generate for names that still look off for known English words
    rows = conn.execute(
        """
        SELECT id, name, urdu_name FROM items
        WHERE name LIKE '%BASE%'
           OR name LIKE '%AXLE%'
           OR name LIKE '%CENTER%'
           OR name LIKE '%ARMATURE%'
           OR name LIKE '%(MT %'
           OR name LIKE '%(MT)%'
        """
    ).fetchall()
    updates = []
    for r in rows:
        # Prefer regenerate from English for these families
        ur = transliterate_name(r["name"] or "")
        if ur and ur != (r["urdu_name"] or ""):
            updates.append((ur, r["id"]))
    conn.executemany("UPDATE items SET urdu_name = ? WHERE id = ?", updates)
    conn.commit()
    print(f"polished rows: {len(updates)} + MT replace")
    conn.close()
    invalidate_items_cache()

    # Mirror polish into Excel for matching empty-was-filled names: rewrite all urdu
    # from DB for safety on those names
    if not EXCEL.exists():
        return
    by_name = {}
    conn = get_connection()
    for r in conn.execute("SELECT name, urdu_name FROM items"):
        key = (r["name"] or "").strip().upper()
        if key and r["urdu_name"]:
            by_name[key] = r["urdu_name"]
    conn.close()

    wb = load_workbook(EXCEL)
    n = 0
    for ws in wb.worksheets:
        header_row = name_col = urdu_col = None
        for r in range(1, min(20, ws.max_row or 1) + 1):
            vals = [ws.cell(r, c).value for c in range(1, min(25, (ws.max_column or 1) + 1))]
            norms = [
                " ".join(str(v).strip().lower().split()) if v is not None else "" for v in vals
            ]
            if "name" not in norms:
                continue
            header_row = r
            name_col = norms.index("name") + 1
            urdu_col = (
                norms.index("urdu name") + 1 if "urdu name" in norms else name_col + 1
            )
            break
        if not header_row:
            continue
        for r in range(header_row + 1, (ws.max_row or 0) + 1):
            name = ws.cell(r, name_col).value
            if not name:
                continue
            ur = by_name.get(str(name).strip().upper())
            if not ur:
                continue
            if ws.cell(r, urdu_col).value != ur:
                ws.cell(r, urdu_col).value = ur
                n += 1
    wb.save(EXCEL)
    print(f"excel synced cells: {n}")


if __name__ == "__main__":
    main()
