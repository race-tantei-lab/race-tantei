#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP = ROOT / "src" / "public-site-entry-v31.ts"
ENTRY = ROOT / "src" / "public-site-entry-v30.ts"
WRANGLER = ROOT / "wrangler.jsonc"
CURRENT_DAY = ROOT / "src" / "v1" / "current-day-public-api.ts"
RECENCY = ROOT / "src" / "v1" / "completed-recency-learning.ts"
DEADLINE = ROOT / "src" / "v1" / "completed-worker-deadline-guard.ts"
INVARIANTS = ROOT / "src" / "v1" / "completed-final-invariants.ts"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    top = TOP.read_text(encoding="utf-8")
    entry = ENTRY.read_text(encoding="utf-8")
    wrangler = WRANGLER.read_text(encoding="utf-8")
    current = CURRENT_DAY.read_text(encoding="utf-8")
    recency = RECENCY.read_text(encoding="utf-8")
    deadline = DEADLINE.read_text(encoding="utf-8")
    invariants = INVARIANTS.read_text(encoding="utf-8")

    require('"main": "src/public-site-entry-v31.ts"' in wrangler, "CLEAR_LANGUAGE_ENTRY_NOT_CANONICAL")
    require('import publicSite from "./public-site-entry-v30.js"' in top, "CLEAR_LANGUAGE_V31_CHAIN_MISSING")
    require('import publicSite from "./public-site-entry-v29.js"' in entry, "CLEAR_LANGUAGE_V29_CHAIN_MISSING")

    current_method_phrases = [
        "予想のしくみ",
        "完成モデル＋継続学習",
        "当日結果も次レースへ反映",
        "直近30日＋当日終了レース",
        "同じ日の終了済みレース",
        "完成済みベースモデルの重みは固定",
        "対象レース自身や未来の結果は使いません",
        "JRA公式オッズだけ",
        "合成オッズ・推定オッズ",
        "発走15分前までに確定",
        "発走16分前以内で確定対象に入れる",
        "発走15分前以降は再計算しない",
        "推定・合成オッズで代用せず買い目を確定しません",
        "確定後はDBでも変更不可",
        "予想は当日も継続更新",
        "使い方",
    ]
    for phrase in current_method_phrases:
        require(phrase in top, f"CURRENT_METHODOLOGY_PHRASE_MISSING:{phrase}")

    reader_facing_phrases = [
        "買い目の理由",
        "この組合せが当たる推定確率",
        "買い目の評価点",
        "1着になる推定確率",
        "5レースすべて的中する推定確率",
    ]
    for phrase in reader_facing_phrases:
        require(phrase in entry, f"CLEAR_LANGUAGE_PHRASE_MISSING:{phrase}")

    # The top wrapper must neutralize obsolete public copy that described a
    # probability/estimated-odds emergency finalization route.
    require("JRA公式オッズを取得できない場合は、推定・合成オッズで代用せず買い目を確定しません。" in top,
            "PUBLIC_FAIL_CLOSED_COPY_MISSING")
    require('["フォールバック", "保存済み予想"]' in top, "PUBLIC_FALLBACK_JARGON_NORMALIZER_MISSING")
    require("予測データを使って買い目を確定" not in top, "OBSOLETE_PROBABILITY_FINALIZATION_REINTRODUCED_IN_TOP")

    # Public copy must match the actual runtime invariants.
    require("COMPLETED_RECENCY_HISTORY_DAYS = 30" in recency, "RECENCY_30_DAY_RUNTIME_MISSING")
    require("COMPLETED_RECENCY_HALF_LIFE_DAYS = 7" in recency, "RECENCY_7_DAY_HALF_LIFE_RUNTIME_MISSING")
    require("sameDayFinishedResultsAllowed: true" in recency, "SAME_DAY_LEARNING_RUNTIME_MISSING")
    require("dayDiff === 0 ? 6 : dayDiff === 1 ? 4 : dayDiff <= 7 ? 2 : 1" in recency,
            "RECENCY_DATE_MULTIPLIERS_CHANGED")
    require("DEADLINE_GUARD_MS = 15 * 60 * 1000" in deadline, "T15_RUNTIME_MISSING")
    require("DEADLINE_GUARD_ARM_MS = 16 * 60 * 1000" in deadline, "T16_SAFETY_ARM_RUNTIME_MISSING")
    require("PROBABILITY_FALLBACK_FORBIDDEN" in invariants, "PROBABILITY_FALLBACK_DB_GUARD_MISSING")
    require("OFFICIAL_JRA_ODDS_REQUIRED" in invariants, "OFFICIAL_ODDS_DB_GUARD_MISSING")
    require("'jra-fast-official', 'jra-crawl-official'" in invariants, "OFFICIAL_ODDS_ALLOWLIST_MISSING")

    require("発走15分前までに買い目確定" in current, "CURRENT_DAY_CLEAR_DEADLINE_MISSING")

    print(
        "PUBLIC_LANGUAGE_OK methodology=current continuous_learning=same_day official_odds_only=true "
        "fail_closed=true immutable_after_lock=true t15_safety_arm=t16 canonical=v31_v30"
    )


if __name__ == "__main__":
    main()
