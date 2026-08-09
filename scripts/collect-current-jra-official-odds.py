import importlib.util
import re
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "collect-jra-official-odds-runtime.py"
spec = importlib.util.spec_from_file_location("current_official_odds_runtime", SOURCE)
if spec is None or spec.loader is None:
    raise RuntimeError("CURRENT_OFFICIAL_ODDS_RUNTIME_IMPORT_FAILED")
runtime = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runtime
spec.loader.exec_module(runtime)


def current_race_no_from_cname(cname: str) -> int | None:
    decoded = urllib.parse.unquote(runtime.base.html_module.unescape(cname))
    # Current JRA CNAMEs can place a marker such as "Z" between YYYYMMDD and "/".
    # Example verified on 2026-08-09:
    # pw151ouS301202601061120260809Z/EA -> race 11.
    values = [
        int(value)
        for value in re.findall(r"(\d{2})(?=20\d{6}[A-Za-z0-9]*?(?:/|$))", decoded)
    ]
    return next((value for value in reversed(values) if 1 <= value <= 12), None)


# Patch only the identity parser used by the already-audited official-odds runtime.
runtime.race_no_from_cname = current_race_no_from_cname


def self_test() -> None:
    cases = {
        "pw15oren0101202601051120260808/AA": 11,
        "pw151ouS301202601061120260809Z/EA": 11,
        "pw151ouS301202601060920260809Z/40": 9,
        "pw157ouS301202601061120260809Z99/64": 11,
    }
    for cname, expected in cases.items():
        actual = current_race_no_from_cname(cname)
        if actual != expected:
            raise AssertionError(f"CURRENT_CNAME_RACE_NUMBER:{cname}:{actual}:{expected}")


if __name__ == "__main__":
    self_test()
    runtime.main()
