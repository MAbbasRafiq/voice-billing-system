"""HTTP end-to-end test against the running server (http://127.0.0.1:8000).

Usage: python scripts/test_e2e.py [--explore]
  --explore : just print results (no pass/fail), for eyeballing.
"""
import json
import statistics
import sys
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://127.0.0.1:8000"
EXPLORE = "--explore" in sys.argv
PACE = float(next((a.split("=")[1] for a in sys.argv if a.startswith("--pace=")), "4"))


def call(method, path, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            ctype = r.headers.get("content-type", "")
            dt = time.time() - t0
            return r.status, (json.loads(raw) if "json" in ctype else raw), dt
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), time.time() - t0


def names_of(item):
    out = []
    for m in item["matches"]:
        if m["name"] not in out:
            out.append(m["name"])
    return out


# (text, expectation)  expectation keys:
#   ignored: True            -> nothing added/reviewed
#   n_items: int             -> number of items returned
#   any: [(substr, qty)]     -> each must appear among item names (case-insens) with qty (None = any)
#   action: {substr: action}
#   max_names: int           -> item with this substr has <= N distinct names
CASES = [
    # ---- plain English ----
    ("2 back light complete", dict(any=[("BACK LIGHT COMPLETE", 2)], max_names={"BACK LIGHT COMPLETE": 1})),
    ("1 back light led", dict(any=[("BACK LIGHT LED", 1)])),
    ("3 back light lens", dict(any=[("LENS", 3)])),
    ("5 chain kit", dict(any=[("CHAIN KIT", 5)])),
    ("six chain lock", dict(any=[("CHAIN LOCK", 6)])),
    ("10 cdi unit", dict(any=[("C.D.I. UNIT", 10)])),
    ("two air filter", dict(any=[("AIR FILTER", 2)])),
    ("a dozen basket", dict(any=[("BASKET", 12)])),
    ("bearing 6203 qty 4", dict(any=[("6203", 4)])),
    ("side stand", dict(any=[("SIDE STAND", 1)])),
    ("7 clutch cable", dict(any=[("CLUTCH CABLE", 7)])),
    ("brake cable front 2", dict(any=[("BRAKE CABLE FRONT", 2)])),
    # ---- model-specific ----
    ("4 air filter for CD70", dict(any=[("AIR FILTER", 4)])),
    ("2 side stand victory", dict(any=[("SIDE STAND", 2)])),
    ("3 back light complete fire fly", dict(any=[("BACK LIGHT COMPLETE", 3)])),
    ("1 handle t only fairy t12", dict(any=[("HANDLE T ONLY", 1)], action={"HANDLE T ONLY": "auto_add"})),
    # ---- typos / case / spacing ----
    ("2 AIR FILTRE", dict(any=[("AIR FILTER", 2)])),
    ("3  back   light   complete  ", dict(any=[("BACK LIGHT COMPLETE", 3)])),
    ("2 clach cable", dict(any=[("CLUTCH CABLE", 2)])),
    ("5 chian kit", dict(any=[("CHAIN KIT", 5)])),
    # ---- multi-item ----
    ("2 back light complete, 1 back light LED, 3 CDI unit",
     dict(n_items=3, any=[("BACK LIGHT COMPLETE", 2), ("BACK LIGHT LED", 1), ("C.D.I. UNIT", 3)])),
    ("5 chain kit and 6 chain lock and 2 side stand",
     dict(n_items=3, any=[("CHAIN KIT", 5), ("CHAIN LOCK", 6), ("SIDE STAND", 2)])),
    ("4 air filter 12 basket 3 clutch cable",
     dict(n_items=3, any=[("AIR FILTER", 4), ("BASKET", 12), ("CLUTCH CABLE", 3)])),
    ("chain kit 5 chain lock 6", dict(n_items=2, any=[("CHAIN KIT", 5), ("CHAIN LOCK", 6)])),
    # ---- Urdu ----
    ("پانچ چین کٹ", dict(any=[("CHAIN KIT", 5)])),
    ("پنج بیک لائٹ کمپلیٹ", dict(any=[("BACK LIGHT COMPLETE", 5)])),
    ("چھ بیک لائٹ ایل ای ڈی 10 سی ڈی آئی یونٹ",
     dict(n_items=2, any=[("BACK LIGHT LED", 6), ("C.D.I. UNIT", 10)])),
    ("تین ایئر فلٹر", dict(any=[("AIR FILTER", 3)])),
    ("دو کلچ کیبل", dict(any=[("CLUTCH CABLE", 2)])),
    ("ایک باسکٹ", dict(any=[("BASKET", 1)])),
    # ---- Roman Urdu ----
    ("paanch chain kit", dict(any=[("CHAIN KIT", 5)])),
    ("teen air filter do basket", dict(n_items=2, any=[("AIR FILTER", 3), ("BASKET", 2)])),
    ("dus side stand", dict(any=[("SIDE STAND", 10)])),
    # ---- noise / junk (must not add anything) ----
    ("hello how are you background noise hmm", dict(ignored=True)),
    ("ok thanks bye", dict(ignored=True)),
    ("", dict(ignored=True)),
    ("   ", dict(ignored=True)),
    ("hmm", dict(ignored=True)),
    ("...", dict(ignored=True)),
    ("random chatter about cricket and the weather today", dict(ignored=True)),
    ("asdfgh qwerty zxcvb", dict(ignored=True)),
    ("1234", dict(ignored=True)),
    ("what time is it", dict(ignored=True)),
    ("آج موسم بہت اچھا ہے", dict(ignored=True)),
    ("السلام علیکم کیا حال ہے", dict(ignored=True)),
    ("ہیلو ہیلو ٹیسٹنگ", dict(ignored=True)),
    ("ایک دو تین", dict(ignored=True)),
    # ---- hostile input ----
    ("'; DROP TABLE items; --", dict(ignored=True)),
    ("<script>alert(1)</script> 2 basket", dict(any=[("BASKET", 2)])),
    ("2 basket " * 40, dict(no_error=True)),
    ("a" * 3000, dict(no_error=True)),
    ("2 basket \u0000 3 side stand", dict(no_error=True)),
    ("٢ باسکٹ", dict(any=[("BASKET", 2)])),  # arabic-indic digit
    ("0 basket", dict(no_error=True)),
    ("-3 basket", dict(no_error=True)),
    ("999999 basket", dict(no_error=True)),
]


def check(text, exp, r):
    errs = []
    items = r.get("items", [])
    if exp.get("ignored"):
        if items:
            errs.append(f"expected ignored, got {[ (i['item'], i['qty']) for i in items]}")
    if "n_items" in exp and len(items) != exp["n_items"]:
        errs.append(f"expected {exp['n_items']} items, got {len(items)}: {[i['item'] for i in items]}")
    for sub, qty in exp.get("any", []):
        hit = None
        for it in items:
            blob = " ".join(names_of(it) + [it["item"]]).upper()
            if sub.upper() in blob:
                hit = it
                break
        if hit is None:
            errs.append(f"no item matching {sub!r}; got {[ (i['item'], i['qty']) for i in items]}")
        elif qty is not None and hit["qty"] != qty:
            errs.append(f"{sub!r} qty {hit['qty']} != {qty}")
    for sub, act in exp.get("action", {}).items():
        for it in items:
            if sub.upper() in " ".join(names_of(it) + [it["item"]]).upper():
                if it["action"] != act:
                    errs.append(f"{sub!r} action {it['action']} != {act}")
                break
    for sub, mx in exp.get("max_names", {}).items():
        for it in items:
            if sub.upper() in it["item"].upper():
                if len(names_of(it)) > mx:
                    errs.append(f"{sub!r} has {len(names_of(it))} names > {mx}")
                break
    return errs


def bill_flow():
    """parse → preview → save → PDF → history → repeat → recent customers."""
    errs = []

    def need(cond, msg):
        if not cond:
            errs.append(msg)
        return cond

    st, r, dt = call("POST", "/api/parse-order", {"text": "2 side stand and 3 chain lock"})
    need(st == 200 and r["items"], f"parse failed {st}")
    lines = []
    for it in r["items"]:
        m = it["matches"][0]
        lines.append({"item_id": m["id"], "qty": it["qty"]})
    st, pv, _ = call("POST", "/api/bill/preview", {"customer": "E2E Test", "lines": lines})
    need(st == 200 and pv["total"] > 0, f"preview {st} {str(pv)[:100]}")
    expected_total = round(sum(l["line_total"] for l in pv["lines"]), 2) if st == 200 else None
    need(st != 200 or abs(pv["total"] - expected_total) < 0.01, "preview total mismatch")

    st, b, _ = call("POST", "/api/bill", {"customer": "E2E Test", "lines": lines})
    need(st == 200 and b.get("id"), f"create bill {st} {str(b)[:100]}")
    bill_id = b.get("id") if st == 200 else None
    if bill_id:
        need(abs(b["total"] - pv["total"]) < 0.01, "saved total != preview total")
        st, pdf, _ = call("GET", f"/api/bill/{bill_id}/pdf")
        need(st == 200 and isinstance(pdf, (bytes, bytearray)) and pdf[:4] == b"%PDF", f"pdf {st}")
        st, got, _ = call("GET", f"/api/bill/{bill_id}")
        need(st == 200 and len(got.get("items", [])) >= len(lines), "get bill items")
        st, h, _ = call("GET", "/api/history")
        need(st == 200 and any(x["id"] == bill_id for x in h["bills"]), "bill missing from history")
        need(st == 200 and h["today"]["total"] > 0 and h["today"]["bill_count"] >= 1, f"today summary {h.get('today')}")
        st, lat, _ = call("GET", "/api/bills/latest")
        need(st == 200 and lat.get("id") == bill_id, f"latest bill {st} {str(lat)[:80]}")
        st, rc, _ = call("GET", "/api/customers/recent")
        need(st == 200 and "E2E Test" in json.dumps(rc), "recent customers")
    # validation / error paths
    st, _, _ = call("POST", "/api/bill", {"customer": "x", "lines": []})
    need(st == 400, f"empty bill should be 400, got {st}")
    st, _, _ = call("POST", "/api/bill", {"customer": "x", "lines": [{"item_id": 99999999, "qty": 1}]})
    need(st == 400, f"unknown item should be 400, got {st}")
    st, _, _ = call("POST", "/api/bill", {"customer": "x", "lines": [{"item_id": lines[0]["item_id"], "qty": 0}]})
    need(st == 422, f"qty 0 should be 422, got {st}")
    st, _, _ = call("GET", "/api/bill/99999999")
    need(st == 404, f"missing bill should be 404, got {st}")
    st, _, _ = call("GET", "/api/bill/99999999/pdf")
    need(st == 404, f"missing pdf should be 404, got {st}")
    st, _, _ = call("POST", "/api/parse-order", {})
    need(st == 422, f"missing text should be 422, got {st}")
    # misc endpoints
    for path in ("/", "/history", "/catalog", "/settings", "/api/status", "/api/catalog?limit=5",
                 "/api/search?q=air%20filter&limit=5"):
        st, _, dt = call("GET", path)
        need(st == 200, f"GET {path} -> {st}")
        need(dt < 1.5, f"GET {path} slow: {dt:.2f}s")
    return errs, bill_id


def cleanup_test_bills():
    """The suite saves real bills (customer 'E2E Test'); remove them + their PDFs."""
    import os
    import sqlite3

    db = os.path.join(os.path.dirname(__file__), "..", "database.db")
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("select id, pdf_path from bills where customer = 'E2E Test'").fetchall()
        for bid, pdf in rows:
            if pdf and os.path.isfile(pdf):
                os.remove(pdf)
            conn.execute("delete from bill_items where bill_id = ?", (bid,))
            conn.execute("delete from bills where id = ?", (bid,))
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def concurrency():
    import concurrent.futures as cf

    texts = ["2 air filter", "3 chain kit", "5 basket", "1 side stand", "2 clutch cable", "4 cdi unit"]
    t0 = time.time()
    with cf.ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda t: call("POST", "/api/parse-order", {"text": t}), texts))
    wall = time.time() - t0
    bad = [t for t, (st, r, _) in zip(texts, res) if st != 200 or not r["items"]]
    return wall, bad


def main():
    fails, times, modes = 0, [], {}
    for text, exp in CASES:
        status, r, dt = call("POST", "/api/parse-order", {"text": text})
        times.append(dt)
        label = text if len(text) < 70 else text[:67] + "..."
        if status != 200:
            errs = [f"HTTP {status}: {str(r)[:150]}"]
            if exp.get("no_error") is None and not exp.get("ignored"):
                pass
        else:
            errs = check(text, exp, r)
        if EXPLORE:
            print(f"\n[{dt:4.1f}s] {label!r} -> HTTP {status}")
            if status == 200:
                print("   mode", r["mode"], r["summary"], r.get("message") or "")
                for it in r["items"]:
                    ns = names_of(it)
                    print(f"   x{it['qty']:<3} {it['action']:<12} {it['item']!r} rows={len(it['matches'])} names={len(ns)} {ns[:3]}")
            continue
        mode = r.get("mode") if status == 200 else "-"
        modes[mode] = modes.get(mode, 0) + 1
        flag = "OK  " if not errs else "FAIL"
        print(f"{flag} [{dt:4.1f}s] {mode:<6} {label!r}")
        for e in errs:
            print("       -", e)
        fails += bool(errs)
        if mode in ("groq", "gemini"):
            time.sleep(PACE)  # stay under the provider tokens-per-minute limit
    if EXPLORE:
        return
    print(f"\nparse-order: {len(CASES) - fails}/{len(CASES)} passed")
    print("modes:", modes)
    print(f"latency: mean={statistics.mean(times):.2f}s median={statistics.median(times):.2f}s "
          f"p90={sorted(times)[int(len(times)*.9)]:.2f}s max={max(times):.2f}s")

    errs, bill_id = bill_flow()
    print(f"\nbill flow (bill #{bill_id}): {'OK' if not errs else 'FAIL'}")
    for e in errs:
        print("   -", e)
    removed = cleanup_test_bills()
    print(f"cleanup: removed {removed} test bill(s)")
    wall, bad = concurrency()
    print(f"concurrency: 6 parallel orders in {wall:.1f}s, failures={bad}")
    sys.exit(1 if (fails or errs or bad) else 0)


main()
