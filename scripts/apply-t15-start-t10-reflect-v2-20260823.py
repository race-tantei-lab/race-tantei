from pathlib import Path
import runpy

# Apply the full runtime patch first.
runpy.run_path('scripts/apply-t15-start-t10-reflect-20260823.py', run_name='__main__')

# Preserve the canonical official-odds marker spelling expected by the safety verifier.
p = Path('src/v1/completed-final-invariants.ts')
t = p.read_text(encoding='utf-8')
t = t.replace("NOT IN ('jra-fast-official','jra-crawl-official')", "NOT IN ('jra-fast-official', 'jra-crawl-official')")
p.write_text(t, encoding='utf-8')
