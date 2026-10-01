"""End-to-end resolve_order checks (uses the configured LLM)."""
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

from app.services.order_agent import resolve_order  # noqa: E402

TESTS = [
    "پانچ چین کٹ",
    "پنج بیک لائٹ کمپلیٹ",
    "چھ بیک لائٹ ایل ای ڈی 10 سی ڈی آئی یونٹ",
    "2 back light complete, 1 back light LED, 3 CDI unit",
    "پانچ چین کٹ چھ چین لوگ تین کیبل دو سی ڈی آئی یونٹ ایک باسکٹ چھ بیک لائٹ ایل ای ڈی سات بیک لائٹ کمپلیٹ",
    "4 air filter for CD70, 12 basket",
    "hello how are you background noise hmm",
]

for text in TESTS:
    t0 = time.time()
    r = resolve_order(text)
    dt = time.time() - t0
    print(f"\n=== {text}\n    {dt:.1f}s mode={r['mode']} summary={r['summary']}")
    for it in r["items"]:
        names = []
        for m in it["matches"]:
            if m["name"] not in names:
                names.append(m["name"])
        print(f"  x{it['qty']:<3} {it['action']:<12} item={it['item']!r} rows={len(it['matches'])} names={len(names)}")
        print(f"        {names[:4]}{' …' if len(names) > 4 else ''}")
    for ig in r["ignored"]:
        print("  ignored:", ig)
