"""All database query helpers."""

from __future__ import annotations

from typing import Any, Optional

from app.database.connection import get_connection


def _row_to_dict(row) -> dict:
    return dict(row) if row is not None else {}


def count_items() -> int:
    conn = get_connection()
    try:
        return conn.execute("SELECT COUNT(*) AS c FROM items").fetchone()["c"]
    finally:
        conn.close()


def get_latest_import() -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM import_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def clear_items(conn) -> None:
    conn.execute("DELETE FROM items")


def insert_import_log(conn, file_modified: str, item_count: int) -> None:
    conn.execute(
        "INSERT INTO import_log (file_modified, item_count) VALUES (?, ?)",
        (file_modified, item_count),
    )


def search_items_by_name(name: str, model: Optional[str] = None, limit: int = 50) -> list[dict]:
    """Return ALL matching variants — never auto-select one."""
    conn = get_connection()
    try:
        name = (name or "").strip()
        model = (model or "").strip() if model else None
        if not name:
            return []

        params: list[Any] = [name, name, f"%{name}%", f"%{name}%"]
        sql = """
            SELECT * FROM items
            WHERE (name = ? COLLATE NOCASE OR urdu_name = ?
                   OR name LIKE ? COLLATE NOCASE OR urdu_name LIKE ?)
        """
        if model:
            sql += " AND model LIKE ? COLLATE NOCASE"
            params.append(f"%{model}%")
        sql += """
            ORDER BY
              CASE WHEN name = ? COLLATE NOCASE THEN 0 ELSE 1 END,
              LENGTH(name),
              name, model
            LIMIT ?
        """
        params.extend([name, limit])
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_item_by_id(item_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def get_item_by_code(item_code: str) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM items WHERE item_code = ? COLLATE NOCASE",
            (item_code,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_all_items_for_fuzzy() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, item_code, model, name, urdu_name, category, cp, foc_qty, foc_units "
            "FROM items"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def catalog_items(
    q: Optional[str] = None,
    category: Optional[str] = None,
    model: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict]:
    conn = get_connection()
    try:
        clauses = ["1=1"]
        params: list[Any] = []
        if q:
            clauses.append(
                "(name LIKE ? COLLATE NOCASE OR urdu_name LIKE ? "
                "OR item_code LIKE ? COLLATE NOCASE OR model LIKE ? COLLATE NOCASE)"
            )
            like = f"%{q}%"
            params.extend([like, like, like, like])
        if category:
            clauses.append("category = ?")
            params.append(category)
        if model:
            clauses.append("model LIKE ? COLLATE NOCASE")
            params.append(f"%{model}%")
        sql = f"SELECT * FROM items WHERE {' AND '.join(clauses)} ORDER BY name, model LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        return [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def list_categories() -> list[str]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT category FROM items WHERE category IS NOT NULL ORDER BY category"
        ).fetchall()
        return [r["category"] for r in rows]
    finally:
        conn.close()


def fuzzy_search(q: str, limit: int = 30) -> list[dict]:
    """Simple LIKE search; RapidFuzz ranking is done in fuzzy_search service."""
    return catalog_items(q=q, limit=limit)


def create_bill(customer: Optional[str], total: float, pdf_path: str, lines: list[dict]) -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO bills (customer, total, pdf_path) VALUES (?, ?, ?)",
            (customer or "", total, pdf_path),
        )
        bill_id = cur.lastrowid
        for line in lines:
            conn.execute(
                """
                INSERT INTO bill_items (bill_id, item_id, qty, unit_price, line_total, is_foc)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    bill_id,
                    line.get("item_id"),
                    line["qty"],
                    line["unit_price"],
                    line["line_total"],
                    1 if line.get("is_foc") else 0,
                ),
            )
        conn.commit()
        return bill_id
    finally:
        conn.close()


def update_bill_pdf(bill_id: int, pdf_path: str) -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE bills SET pdf_path = ? WHERE id = ?", (pdf_path, bill_id))
        conn.commit()
    finally:
        conn.close()


def get_bill(bill_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        bill = conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
        if not bill:
            return None
        items = conn.execute(
            """
            SELECT bi.*, i.item_code, i.model, i.name, i.urdu_name, i.category
            FROM bill_items bi
            LEFT JOIN items i ON i.id = bi.item_id
            WHERE bi.bill_id = ?
            ORDER BY bi.id
            """,
            (bill_id,),
        ).fetchall()
        result = _row_to_dict(bill)
        result["items"] = [_row_to_dict(r) for r in items]
        return result
    finally:
        conn.close()


def list_bills(limit: int = 100) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM bills ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()
