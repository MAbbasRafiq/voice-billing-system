"""Smoke test catalog-grounded order agent."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.order_agent import resolve_order


def show(label, result):
    print(f"\n=== {label} ===")
    print("mode:", result.get("mode"))
    print("summary:", result.get("summary"))
    print("message:", result.get("message"))
    for it in result.get("items") or []:
        print(
            f"  [{it.get('action')}] qty={it.get('qty')} item={it.get('item')!r} "
            f"matches={len(it.get('matches') or [])} "
            f"models={[m.get('model') for m in (it.get('matches') or [])[:4]]}"
        )
    for ig in result.get("ignored") or []:
        print("  ignored:", ig)


if __name__ == "__main__":
    show("noise", resolve_order("umm ah"))
    show("empty-ish", resolve_order("..."))
    show(
        "english clear bearing",
        resolve_order("5 bearing 6203"),
    )
    show(
        "english multi model",
        resolve_order("2 air filter for CD70"),
    )
    show(
        "english two lines",
        resolve_order("2 air filter CD70F and 5 bearing 6203"),
    )
    show("urdu lota", resolve_order("دو ایئر لوٹا"))
