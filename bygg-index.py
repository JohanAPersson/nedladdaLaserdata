#!/usr/bin/env python3
"""
Bygger docs/data/rutor.json — den rutlista sidan använder för att slå upp
filnamn utan att fråga Lantmäteriets API i webbläsaren.

Kör om filen någon gång i månaden, eller när nya områden publiceras.

    pip install requests
    python3 bygg-index.py                    # utan inloggning
    LM_USER=... LM_PASS=... python3 bygg-index.py    # med, om API:et kräver det

Utdataformat:

    {
      "uppdaterad": "2026-08-18",
      "antal": 3412,
      "rutor": {
        "627_57": [{"o": "26a019", "d": "2026-04-18", "s": 326973707}]
      }
    }

  o = skanningsområde (behövs för filnamnet)
  d = insamlingsdatum
  s = filstorlek i byte

Nedladdningslänken byggs av sidan som:
  https://dl1.lantmateriet.se/hojd/data/pointcloud/sls/{o}/m{o}-{ruta}.copc.laz
"""

import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import requests

API = "https://api.lantmateriet.se/stac-hojd/v1"
COLLECTION = "dsm-skoglig-copc"
PAGE = 2000                      # API:et tillåter upp till 10 000
OUT = Path("docs/data/rutor.json")

ID_RE = re.compile(r"^([0-9a-zA-Z]+)-(\d+_\d+)$")

session = requests.Session()
user, password = os.environ.get("LM_USER"), os.environ.get("LM_PASS")
if user and password:
    session.auth = (user, password)
    print("Använder inloggning för %s" % user)
else:
    print("Kör utan inloggning — metadata är öppen i dagsläget.")


def pages():
    """Bläddrar igenom hela collectionen och ger en sida i taget."""
    url = "%s/collections/%s/items?limit=%d" % (API, COLLECTION, PAGE)
    n = 0
    while url:
        n += 1
        r = session.get(url, timeout=180)
        if r.status_code == 401:
            sys.exit("401: fel uppgifter. Använd ett systemkonto från Geotorget.")
        if r.status_code == 403:
            sys.exit("403: kontot saknar behörighet till Laserdata Skog.")
        r.raise_for_status()
        page = r.json()
        feats = page.get("features", [])
        print("  sida %-3d %5d items" % (n, len(feats)))
        yield feats
        url = next((l["href"] for l in page.get("links", [])
                    if l.get("rel") == "next"), None)


rutor = {}
skipped = 0
total_bytes = 0

print("Hämtar %s …" % COLLECTION)
for feats in pages():
    for f in feats:
        m = ID_RE.match(f.get("id", ""))
        if not m:
            skipped += 1
            continue
        area, key = m.group(1).lower(), m.group(2)
        data = (f.get("assets") or {}).get("data") or {}
        size = data.get("file:size") or 0
        total_bytes += size
        rutor.setdefault(key, []).append({
            "o": area,
            "d": str((f.get("properties") or {}).get("datetime") or "")[:10],
            "s": size,
        })

# nyast först inom varje ruta, så sidan kan ta index 0
for entries in rutor.values():
    entries.sort(key=lambda e: e["d"], reverse=True)

if not rutor:
    sys.exit("Inga rutor hittades — kontrollera nätverk och behörighet.")

payload = {
    "uppdaterad": date.today().isoformat(),
    "antal": len(rutor),
    "rutor": rutor,
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
               encoding="utf-8")

files = sum(len(v) for v in rutor.values())
print("")
print("%d rutor, %d filer, %.1f TB totalt i produkten"
      % (len(rutor), files, total_bytes / 1e12))
if skipped:
    print("%d items hoppades över (oväntat id-format)" % skipped)
print("Skrev %s (%.0f kB)" % (OUT, OUT.stat().st_size / 1024))
