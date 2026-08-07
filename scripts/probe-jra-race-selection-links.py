import html
import json
import re
import urllib.request
from pathlib import Path

URL = "https://www.jra.go.jp/JRADB/accessS.html?CNAME=pw01sde1008202403050120240504%2F55"
OUT = Path("artifacts/jra-race-selection-links-probe.json")

req = urllib.request.Request(URL, headers={
    "User-Agent": "Mozilla/5.0 (compatible; RaceTantei/1.0; +https://www.jra.go.jp/)",
    "Accept-Language": "ja,en;q=0.8",
})
with urllib.request.urlopen(req, timeout=60) as r:
    raw = r.read()
    charset = r.headers.get_content_charset() or "utf-8"
text = raw.decode(charset, errors="replace")

# Keep only navigation/action evidence; do not save the full result page.
patterns = [
    r'href\s*=\s*["\'][^"\']+["\']',
    r'onclick\s*=\s*["\'][^"\']+["\']',
    r'action\s*=\s*["\'][^"\']+["\']',
    r'CNAME=[^"\'&<>\s]+',
]
all_tokens = []
for pattern in patterns:
    all_tokens.extend(re.findall(pattern, text, flags=re.I))

keywords = (
    "accessS", "CNAME", "レース選択", "開催選択", "京都", "20240504",
    "sli", "srl", "sde", "pw01", "race"
)
filtered = []
for token in all_tokens:
    decoded = html.unescape(token)
    if any(k.lower() in decoded.lower() for k in keywords):
        filtered.append(decoded)

# Also save compact source fragments surrounding the navigation Japanese labels.
fragments = []
for needle in ("レース選択", "開催選択", "3回京都5日"):
    for m in re.finditer(needle, text):
        a = max(0, m.start() - 500)
        b = min(len(text), m.end() + 500)
        fragments.append(re.sub(r"\s+", " ", text[a:b]))

report = {
    "url": URL,
    "bytes": len(raw),
    "charset": charset,
    "filteredTokens": list(dict.fromkeys(filtered))[:500],
    "fragments": fragments[:30],
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"bytes": len(raw), "tokens": len(report["filteredTokens"]), "fragments": len(report["fragments"]), "output": str(OUT)}, ensure_ascii=False))
