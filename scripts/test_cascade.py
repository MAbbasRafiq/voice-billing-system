"""Edge-case checks for exact-first catalog matching (no LLM needed)."""
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, ".")

from app.services.fuzzy_search import find_catalog_matches  # noqa: E402


def names(rows):
    seen, out = set(), []
    for r in rows:
        n = r["name"]
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


CASES = [
    # (query, model, must_include_substrings, must_exclude_substrings, expected_tier)
    ("CHAIN KIT", None, ["TIMING CHAIN KIT 82L", "CHAIN KIT (38X15"], ["CHAIN COVER", "CHAIN LOCK", "CHAIN SETTING"], "phrase"),
    ("چین کٹ", None, ["TIMING CHAIN KIT 84L", "CHAIN KIT (43X14"], ["CHAIN COVER", "CHAIN LOCK"], "phrase"),
    ("chain kits", None, ["CHAIN KIT (38X15"], ["CHAIN LOCK"], "phrase"),            # plural
    ("chain lock", None, ["CHAIN LOCK 420"], ["CHAIN KIT"], "phrase"),
    ("چین لوگ", None, ["CHAIN LOCK"], ["CHAIN KIT"], None),                           # Urdu fuzzy ok
    ("BACK LIGHT COMPLETE", None, ["BACK LIGHT COMPLETE", "BACK LIGHT COMPLETE (2003 MODEL)"], ["BACK LIGHT LED", "BACK LIGHT LENS"], "exact"),
    ("backlight complete", None, ["BACK LIGHT COMPLETE", "BACK LIGHT COMPLETE (2003 MODEL)"], ["HEAD LIGHT COMPLETE"], "exact"),
    ("backtack", None, ["BACK TACK"], ["BACK TAKE"], "exact"),
    ("بیک ٹیک", None, ["BACK TACK"], ["BACK LIGHT COMPLETE", "BACK TAKE"], "exact"),
    ("5 بیک ٹیک", None, ["BACK TACK"], ["BACK LIGHT COMPLETE", "BACK TAKE"], "exact"),
    ("BACK LIGHT LED", None, ["BACK LIGHT LED"], ["BACK LIGHT COMPLETE", "BACK LIGHT LENS"], "exact"),
    ("back light lens", None, ["BACK LIGHT LENS"], ["BACK LIGHT LED", "BACK LIGHT COMPLETE"], "exact"),
    ("BASKET", None, ["BASKET"], [], "exact"),
    ("basket", None, ["BASKET"], [], "exact"),
    ("cdi unit", None, ["C.D.I. UNIT"], ["CHAIN"], None),                              # dotted catalog name
    ("C.D.I. UNIT", None, ["C.D.I. UNIT"], ["CHAIN"], None),
    ("air filter", None, ["AIR FILTER"], ["CHAIN"], "exact"),
    ("filter air", None, ["AIR FILTER"], [], "words"),                                 # word order
    ("air filter cd70", None, ["AIR FILTER"], [], None),                               # model left in text
    ("air filter", "CD70", ["AIR FILTER"], [], "exact"),
    ("air filtre", None, ["AIR FILTER"], [], "exact"),                                 # clear typo → corrected exact
    ("carburator", None, ["CARBURETOR (PZ-18)", "CARBURETOR (PZ-22)"], [], "phrase"),
    ("clach cable", None, ["CLUTCH CABLE"], ["BRAKE CABLE", "METER CABLE"], "exact"),
    ("brak cable front", None, ["BRAKE CABLE FRONT"], ["BRAKE CABLE REAR"], "exact"),
    ("cdi unit lead", None, ["C.D.I UNIT LEED", "C.D.I UNIT LEED (MB100)"], ["BACK LIGHT LED"], "exact"),
    ("سی ڈی ای یونٹ لیڈ", None, ["C.D.I UNIT LEED", "C.D.I UNIT LEED (MB100)"], ["BACK LIGHT LED", "HEAD LIGHT LED"], "exact"),
    ("سی ڈی آئی یونٹ لیڈ", None, ["C.D.I UNIT LEED", "C.D.I UNIT LEED (MB100)"], ["BACK LIGHT LED", "HEAD LIGHT LED"], "exact"),
    ("bearing 6203", None, ["6203"], ["6000"], None),                                  # number token kept
]

ok = True
for q, model, inc, exc, tier in CASES:
    rows = find_catalog_matches(q, model, limit=60)
    ns = names(rows)
    blob = " | ".join(ns)
    t = rows[0].get("match_tier") if rows else None
    problems = []
    if not rows:
        problems.append("NO RESULTS")
    for s in inc:
        if s.lower() not in blob.lower():
            problems.append(f"missing '{s}'")
    for s in exc:
        if s.lower() in blob.lower():
            problems.append(f"unexpected '{s}'")
    if tier and t != tier:
        problems.append(f"tier={t} expected={tier}")
    status = "OK " if not problems else "BAD"
    if problems:
        ok = False
    print(f"{status} {q!r} model={model} tier={t} rows={len(rows)} names={len(ns)}")
    if problems:
        print("     ", problems)
        print("      ", ns[:8])

print("\nALL OK" if ok else "\nSOME FAILED")
