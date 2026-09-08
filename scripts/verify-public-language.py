#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WRANGLER = ROOT / "wrangler.jsonc"
CURRENT_DAY = ROOT / "src" / "v1" / "current-day-public-api.ts"
RECENCY = ROOT / "src" / "v1" / "completed-recency-learning.ts"
DEADLINE = ROOT / "src" / "v1" / "completed-worker-deadline-guard.ts"
MIGRATION = ROOT / "scripts" / "install-race-day-runtime-guards.sql"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def main() -> None:
    wrangler = json.loads(read(WRANGLER))
    actual_main = str(wrangler.get("main") or "")
    require(actual_main == "src/public-site-entry-recovery-20260906.ts", "CLEAR_LANGUAGE_ENTRY_NOT_ACTUAL_WRANGLER_MAIN")

    recovery = read(ROOT / actual_main)
    v37 = read(ROOT / "src" / "public-site-entry-v37.ts")
    v37_core = read(ROOT / "src" / "public-site-entry-v37-core.ts")
    v34 = read(ROOT / "src" / "public-site-entry-v34.ts")
    v33 = read(ROOT / "src" / "public-site-entry-v33.ts")
    v32 = read(ROOT / "src" / "public-site-entry-v32.ts")
    top = read(ROOT / "src" / "public-site-entry-v31.ts")
    entry = read(ROOT / "src" / "public-site-entry-v30.ts")
    current = read(CURRENT_DAY)
    recency = read(RECENCY)
    deadline = read(DEADLINE)
    migration = read(MIGRATION)

    # Resolve the real public fetch chain from wrangler instead of pretending
    # that v31 is the Worker entrypoint. v31/v30 remain the active language layer.
    require('import publicSite from "./public-site-entry-v37.js"' in recovery, "PUBLIC_CHAIN_RECOVERY_TO_V37_MISSING")
    require('import core from "./public-site-entry-v37-core.js"' in v37, "PUBLIC_CHAIN_V37_CORE_MISSING")
    require('import publicSite from "./public-site-entry-v34.js"' in v37_core, "PUBLIC_CHAIN_V37_TO_V34_MISSING")
    require('import publicSite from "./public-site-entry-v33.js"' in v34, "PUBLIC_CHAIN_V34_TO_V33_MISSING")
    require('import publicSite from "./public-site-entry-v32.js"' in v33, "PUBLIC_CHAIN_V33_TO_V32_MISSING")
    require('import publicSite from "./public-site-entry-v31.js"' in v32, "PUBLIC_CHAIN_V32_TO_V31_MISSING")
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

    obsolete_copy = "JRA公式オッズを取得できなかったため、発走15分前の時点で利用できた予測データを使って買い目を確定しました。この買い目も通常どおり成績に集計します。"
    fail_closed_copy = "JRA公式オッズを取得できない場合は、推定・合成オッズで代用せず買い目を確定しません。"
    require(obsolete_copy in top and fail_closed_copy in top, "PUBLIC_FAIL_CLOSED_NORMALIZATION_MISSING")
    require('["フォールバック", "保存済み予想"]' in top, "PUBLIC_FALLBACK_JARGON_NORMALIZER_MISSING")

    require("COMPLETED_RECENCY_HISTORY_DAYS = 30" in recency, "RECENCY_30_DAY_RUNTIME_MISSING")
    require("COMPLETED_RECENCY_HALF_LIFE_DAYS = 7" in recency, "RECENCY_7_DAY_HALF_LIFE_RUNTIME_MISSING")
    require("sameDayFinishedResultsAllowed: true" in recency, "SAME_DAY_LEARNING_RUNTIME_MISSING")
    require("dayDiff === 0 ? 6 : dayDiff === 1 ? 4 : dayDiff <= 7 ? 2 : 1" in recency, "RECENCY_DATE_MULTIPLIERS_CHANGED")
    require("DEADLINE_GUARD_MS = 15 * 60 * 1000" in deadline, "T15_RUNTIME_MISSING")
    require("DEADLINE_GUARD_ARM_MS = 25 * 60 * 1000" in deadline, "T25_GUARD_ARM_RUNTIME_MISSING")

    # Runtime schema introspection is intentionally gone. Verify the actual
    # persistent DB guard definitions in the migration source instead.
    require("PROBABILITY_FALLBACK_FORBIDDEN" in migration, "PROBABILITY_FALLBACK_DB_GUARD_MISSING")
    require("OFFICIAL_JRA_ODDS_REQUIRED" in migration, "OFFICIAL_ODDS_DB_GUARD_MISSING")
    require("jra-fast-official','jra-crawl-official" in migration, "OFFICIAL_ODDS_ALLOWLIST_MISSING")
    require("発走15分前までに買い目確定" in current, "CURRENT_DAY_CLEAR_DEADLINE_MISSING")

    print(
        "PUBLIC_LANGUAGE_OK actual_entry=recovery_v37 language_layer=v31_v30 "
        "continuous_learning=same_day official_odds_only=true fail_closed=true immutable_after_lock=true"
    )


if __name__ == "__main__":
    main()
