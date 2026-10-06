from app.database.connection import get_connection
import re
from collections import Counter

c = get_connection()
total = c.execute("select count(1) as n from items").fetchone()["n"]
filled = c.execute(
    "select count(1) as n from items where urdu_name is not null and trim(urdu_name) not in ('','-')"
).fetchone()["n"]
print("total", total, "filled", filled, "missing", total - filled)

print("--- filled samples ---")
for r in c.execute(
    "select name, urdu_name from items where urdu_name is not null and trim(urdu_name) not in ('','-') limit 25"
):
    print(f"{r['name']} => {r['urdu_name']}")

rows = c.execute(
    "select distinct name from items where urdu_name is null or trim(urdu_name) in ('','-') order by name"
).fetchall()
print("distinct missing", len(rows))
words = Counter()
for r in rows:
    for w in re.findall(r"[A-Za-z]+", r["name"] or ""):
        words[w.upper()] += 1
print("--- top missing words ---")
for w, n in words.most_common(80):
    print(n, w)
