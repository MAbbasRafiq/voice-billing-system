"""Unit checks for the LLM-free fast path (no network)."""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")
from app.services.local_parser import local_parse  # noqa: E402

# text -> list of (qty, item-substring) or None (must defer to the LLM)
CASES = {
    "2 back light complete": [(2, "back light complete")],
    "5 chain kit": [(5, "chain kit")],
    "5 chain kit, 6 chain lock": [(5, "chain kit"), (6, "chain lock")],
    "5 chain kit and 6 chain lock and 2 side stand": [(5, "chain kit"), (6, "chain lock"), (2, "side stand")],
    "2 back light complete 1 back light led 3 cdi unit": [(2, "back light complete"), (1, "back light led"), (3, "cdi unit")],
    "2 back light complete, 1 back light LED, 3 CDI unit": [(2, "back light complete"), (1, "back light LED"), (3, "CDI unit")],
    "4 air filter 12 basket 3 clutch cable": [(4, "air filter"), (12, "basket"), (3, "clutch cable")],
    "two air filter": [(2, "air filter")],
    "six chain lock": [(6, "chain lock")],
    "a dozen basket": [(12, "basket")],
    "half dozen basket": [(6, "basket")],
    "5x basket": [(5, "basket")],
    "please give me 3 basket": [(3, "basket")],
    "side stand": [(1, "side stand")],
    "paanch chain kit": [(5, "chain kit")],
    "teen air filter, do basket": [(3, "air filter"), (2, "basket")],
    "dus side stand": [(10, "side stand")],
    "4 air filter for CD70": [(4, "air filter")],
    "bearing 6203": [(1, "bearing 6203")],
    # -> must defer to the LLM
    "teen air filter do basket": None,       # word-qty mid-sentence → LLM
    # Clear catalog-grounded typo is now safe on the local fast path.
    "air filtre": [(1, "air filtre")],
    "2 clach cable": [(2, "clach cable")],   # clear catalog-grounded typo
    "chain kit 5": None,                     # trailing qty
    "chain kit 5 chain lock 6": None,        # trailing qtys
    "bearing 6203 qty 4": None,              # explicit qty word after
    "پانچ چین کٹ": None,                      # Urdu script
    "hello how are you": None,
    "<script>alert(1)</script> 2 basket": None,
    "'; DROP TABLE items; --": None,
    "": None,
    "2": None,
    "2 asdfgh": None,
    "2 basket and 3 asdfgh": None,           # one bad segment poisons all
    "x" * 500: None,
}

bad = 0
for text, want in CASES.items():
    got = local_parse(text)
    if want is None:
        ok = got is None
    else:
        ok = (
            got is not None
            and len(got) == len(want)
            and all(g["qty"] == q and sub.lower() in g["item"].lower() for g, (q, sub) in zip(got, want))
        )
    bad += not ok
    shown = None if got is None else [(g["qty"], g["item"]) for g in got]
    print(("OK   " if ok else "FAIL ") + repr(text[:60]) + " -> " + str(shown))
print("\nALL OK" if not bad else f"\n{bad} FAILED")
sys.exit(1 if bad else 0)
