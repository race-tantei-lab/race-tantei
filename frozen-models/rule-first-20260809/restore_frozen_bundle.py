from pathlib import Path
import base64,gzip,hashlib,json,tarfile,io
root=Path(__file__).parent
parts=sorted(root.glob("rules.part*.b64"))
if not parts: raise SystemExit("rule chunks missing")
encoded="".join(p.read_text().strip() for p in parts)
rules=gzip.decompress(base64.b64decode(encoded))
expected="ad81f4be88064e9b08756bd585019b487b8f96b3f4fc262710d02d8d149143c1"
got=hashlib.sha256(rules).hexdigest()
if got!=expected: raise SystemExit(f"rules SHA256 mismatch: {got}")
(root/"consolidated_rules_v2.json").write_bytes(rules)
print(f"restored {len(json.loads(rules))} rules; sha256={got}")
sp=root/"source_scripts.tar.gz.b64"
if sp.exists():
    archive=base64.b64decode(sp.read_text().strip())
    with tarfile.open(fileobj=io.BytesIO(archive),mode="r:gz") as tf: tf.extractall(root/"source-scripts")
    print("restored source scripts")
