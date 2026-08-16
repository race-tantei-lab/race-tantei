#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "src" / "public-site-entry-v30.ts"
WRANGLER = ROOT / "wrangler.jsonc"
CURRENT_DAY = ROOT / "src" / "v1" / "current-day-public-api.ts"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    entry = ENTRY.read_text(encoding="utf-8")
    wrangler = WRANGLER.read_text(encoding="utf-8")
    current = CURRENT_DAY.read_text(encoding="utf-8")

    require('"main": "src/public-site-entry-v30.ts"' in wrangler, "CLEAR_LANGUAGE_ENTRY_NOT_CANONICAL")
    require('import publicSite from "./public-site-entry-v29.js"' in entry, "CLEAR_LANGUAGE_V29_CHAIN_MISSING")

    required_phrases = [
        "発走15分前",
        "予想のしくみ",
        "買い目の理由",
        "この組合せが当たる推定確率",
        "買い目の評価点",
        "最近30日間のレース結果を反映",
        "1着になる推定確率",
        "5レースすべて的中する推定確率",
        "各レースの1着予想と、最近の結果の反映状況",
        "通常と異なる方法で買い目を確定",
        "取得できていないオッズは表示していません",
    ]
    for phrase in required_phrases:
        require(phrase in entry, f"CLEAR_LANGUAGE_PHRASE_MISSING:{phrase}")

    require("フォールバックで買い目を固定しました" in entry, "CLEAR_LANGUAGE_FALLBACK_SOURCE_MARKER_MISSING")
    require("JRA公式オッズを取得できなかったため、発走15分前" in entry, "CLEAR_LANGUAGE_ODDS_FAILURE_EXPLANATION_MISSING")
    require("replace(/T[-–](\\d+)/g" in entry, "CLEAR_LANGUAGE_T_MINUS_NORMALIZER_MISSING")
    require("発走15分前までに買い目確定" in current, "CURRENT_DAY_CLEAR_DEADLINE_MISSING")

    print("PUBLIC_LANGUAGE_OK t_minus=plain_japanese probability=explained learning=explained fallback=hidden nav=plain_japanese")


if __name__ == "__main__":
    main()
