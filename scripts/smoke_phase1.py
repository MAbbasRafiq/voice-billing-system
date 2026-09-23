"""Smoke test: import Excel and parse a sample order (no frontend)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database.connection import init_db
from app.database.queries import search_items_by_name
from app.services.ai_parser import parse_order
from app.services.excel_importer import import_all_sheets


def main() -> None:
    init_db()
    summary = import_all_sheets(force=True)
    print("=== Excel import summary ===")
    print(f"Total items: {summary['total']}")
    for sheet, count in summary.get("per_sheet", {}).items():
        print(f"  [{sheet}]: {count}")
    print(f"File modified: {summary.get('file_modified')}")
    print()

    sample = "2 air filter for CD70 and 5 bearing 6203"
    print(f"=== Sample parse: {sample!r} ===")
    result = parse_order(sample)
    enriched = []
    for item in result["results"]:
        matches = search_items_by_name(item.get("item") or "", item.get("model"))
        if not matches and item.get("model"):
            matches = search_items_by_name(item.get("item") or "", None)
        confidence = item.get("confidence") or "ambiguous"
        if len(matches) != 1:
            confidence = "ambiguous"
        enriched.append(
            {
                **item,
                "confidence": confidence,
                "match_count": len(matches),
                "matches": [
                    {
                        "id": m["id"],
                        "item_code": m["item_code"],
                        "model": m["model"],
                        "name": m["name"],
                        "cp": m["cp"],
                    }
                    for m in matches[:8]
                ],
            }
        )
    print(f"Mode: {result['mode']}")
    print(json.dumps(enriched, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
