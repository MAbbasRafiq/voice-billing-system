"""Excel price list → SQLite importer (openpyxl only)."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from openpyxl import load_workbook

from app.database.connection import get_connection
from app.database.queries import clear_items, count_items, get_latest_import, insert_import_log

ROOT = Path(__file__).resolve().parents[2]
EXCEL_PATH = ROOT / "data" / "C_P_LIST.xlsx"

SHEET_COLUMN_MAP = {
    "s no": "s_no",
    "s №": "s_no",
    "s n": "s_no",
    "item code": "item_code",
    "model": "model",
    "name": "name",
    "urdu name": "urdu_name",
    "ctn qty": "ctn_qty",
    "ctn  qty": "ctn_qty",
    "cp": "cp",
    "qty": "foc_qty",
    "foc": "foc_units",
    "q.r.c. runs": "qrc_runs",
    "qrc runs": "qrc_runs",
}


def _normalize_col(val: Any) -> str:
    if val is None:
        return ""
    text = str(val).strip().lower()
    return " ".join(text.split())


def _to_int(val: Any) -> Optional[int]:
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def _to_float(val: Any) -> Optional[float]:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _map_headers(header_cells: list[Any]) -> dict[str, int]:
    """Map canonical field name -> column index."""
    mapping: dict[str, int] = {}
    for idx, cell in enumerate(header_cells):
        key = _normalize_col(cell)
        if not key:
            continue
        if key in SHEET_COLUMN_MAP:
            mapping[SHEET_COLUMN_MAP[key]] = idx
        elif key.startswith("s ") and "s_no" not in mapping:
            mapping["s_no"] = idx

    # Unlabeled Urdu column sitting right after NAME
    if "urdu_name" not in mapping and "name" in mapping:
        name_idx = mapping["name"]
        occupied = set(mapping.values())
        candidate = name_idx + 1
        if candidate < len(header_cells) and candidate not in occupied:
            # Accept blank/unknown header as urdu
            mapping["urdu_name"] = candidate

    return mapping


def file_mtime_iso(path: Path = EXCEL_PATH) -> str:
    return datetime.fromtimestamp(os.path.getmtime(path)).isoformat()


def needs_reimport(path: Path = EXCEL_PATH) -> bool:
    if not path.exists():
        return False
    if count_items() == 0:
        return True
    latest = get_latest_import()
    if not latest:
        return True
    return latest.get("file_modified") != file_mtime_iso(path)


def import_all_sheets(force: bool = False, path: Path = EXCEL_PATH) -> dict:
    """
    Read all sheets from the Excel file into the items table.
    Returns summary: {total, per_sheet, file_modified}.
    """
    if not path.exists():
        raise FileNotFoundError(f"Excel file not found: {path}")

    if not force and not needs_reimport(path):
        latest = get_latest_import()
        return {
            "skipped": True,
            "total": latest.get("item_count", count_items()) if latest else count_items(),
            "per_sheet": {},
            "file_modified": latest.get("file_modified") if latest else None,
        }

    wb = load_workbook(path, read_only=True, data_only=True)
    per_sheet: dict[str, int] = {}
    total = 0

    conn = get_connection()
    try:
        clear_items(conn)

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            header_row_idx = None
            header_cells: list[Any] = []

            for i, row in enumerate(ws.iter_rows(values_only=True)):
                values = [
                    str(v).strip().upper() if v is not None else ""
                    for v in row
                ]
                if "ITEM CODE" in values:
                    header_row_idx = i
                    header_cells = list(row)
                    break

            if header_row_idx is None:
                per_sheet[sheet_name] = 0
                continue

            colmap = _map_headers(header_cells)
            if "item_code" not in colmap or "name" not in colmap:
                per_sheet[sheet_name] = 0
                continue

            rows_out = []
            # Re-iterate: openpyxl read_only can't rewind easily — re-open sheet rows
            # by continuing from rows after header in a second pass.
            # Since we already consumed iterator to find header, load sheet again.
            ws2 = wb[sheet_name]
            for i, row in enumerate(ws2.iter_rows(values_only=True)):
                if i <= header_row_idx:
                    continue
                cells = list(row)
                if colmap["item_code"] >= len(cells) or colmap["name"] >= len(cells):
                    continue

                def cell(field: str):
                    idx = colmap.get(field)
                    if idx is None or idx >= len(cells):
                        return None
                    return cells[idx]

                item_code = cell("item_code")
                name = cell("name")
                if item_code is None or str(item_code).strip() == "":
                    continue
                if name is None or str(name).strip() == "":
                    continue
                cp = _to_float(cell("cp"))
                if cp is None:
                    continue

                model = cell("model")
                urdu = cell("urdu_name")
                rows_out.append(
                    (
                        str(item_code).strip(),
                        None if model is None or str(model).strip() == "" else str(model).strip(),
                        str(name).strip(),
                        None if urdu is None or str(urdu).strip() == "" else str(urdu).strip(),
                        sheet_name,
                        _to_int(cell("ctn_qty")),
                        cp,
                        _to_int(cell("foc_qty")),
                        _to_int(cell("foc_units")),
                        _to_int(cell("qrc_runs")),
                    )
                )

            conn.executemany(
                """
                INSERT INTO items
                (item_code, model, name, urdu_name, category, ctn_qty, cp, foc_qty, foc_units, qrc_runs)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows_out,
            )
            per_sheet[sheet_name] = len(rows_out)
            total += len(rows_out)

        mtime = file_mtime_iso(path)
        insert_import_log(conn, mtime, total)
        conn.commit()
    finally:
        conn.close()
        wb.close()

    return {
        "skipped": False,
        "total": total,
        "per_sheet": per_sheet,
        "file_modified": mtime,
    }


if __name__ == "__main__":
    from app.database.connection import init_db

    init_db()
    summary = import_all_sheets(force=True)
    print("Excel import summary")
    print(f"  Total items: {summary['total']}")
    for sheet, count in summary.get("per_sheet", {}).items():
        print(f"  [{sheet}]: {count}")
    print(f"  File modified: {summary.get('file_modified')}")
