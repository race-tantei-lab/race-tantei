#!/usr/bin/env python3
from __future__ import annotations

import argparse
import collections
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://race-tantei-phase0.race-tantei.workers.dev"

CONDITION_MARKERS = (
    "予想のしくみ",
    "完成モデル＋継続学習",
    "当日結果も次レースへ反映",
    "直近30日＋当日終了レース",
    "同じ日の終了済みレースを強く反映",
    "対象レース自身や未来の結果は使いません",
    "JRA公式オッズだけ",
    "合成オッズ・推定オッズ",
    "発走16分前以内で確定対象に入れる",
    "発走15分前以降は再計算しない",
    "推定・合成オッズでは代用しません",
    "確定後はDBでも変更不可",
    "ln(予測確率) + 0.4 × ln(JRA公式オッズ)",
)
GUIDE_MARKERS = (
    "開催中も予想は更新",
    "継続学習について",
    "完成済みベースモデルは固定したまま",
    "同じ日の終了レースを強く反映",
    "市場オッズはJRA公式値だけを使用します",
    "合成オッズや推定オッズで代用して確定することはありません",
)


def expected_ui() -> str:
    config = json.loads((ROOT / "wrangler.jsonc").read_text(encoding="utf-8"))
    value = str(config.get("vars", {}).get("DEPLOY_REVISION", "")).strip()
    if not value:
        raise AssertionError("wrangler DEPLOY_REVISION is missing")
    return value


def fetch(path: str, timeout: float = 10.0) -> tuple[int, str, dict[str, str]]:
    request = urllib.request.Request(f"{BASE}{path}", headers={"user-agent": "race-tantei-production-smoke/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return int(response.status), raw.decode(charset, errors="replace"), {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        charset = exc.headers.get_content_charset() or "utf-8"
        return int(exc.code), raw.decode(charset, errors="replace"), {k.lower(): v for k, v in exc.headers.items()}


def parse_json(text: str, label: str):
    try:
        return json.loads(text)
    except Exception as exc:
        raise AssertionError(f"{label} is not valid JSON: {exc}") from exc


def validate_once() -> dict[str, object]:
    today = datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat()
    expected = expected_ui()

    home_code, home, _ = fetch("/")
    conditions_code, conditions, conditions_headers = fetch("/conditions")
    guide_code, guide, _ = fetch("/guide")
    day8_code, day8_raw, _ = fetch("/api/public/day?date=2026-08-08")
    day9_code, day9_raw, _ = fetch("/api/public/day?date=2026-08-09")
    today_code, today_raw, _ = fetch(f"/api/public/day?date={today}")
    legacy_code, _, _ = fetch("/_ops/live-tick")

    ui = conditions_headers.get("x-race-ui-version", "")
    codes = {
        "home": home_code,
        "conditions": conditions_code,
        "guide": guide_code,
        "day8": day8_code,
        "day9": day9_code,
        "today": today_code,
        "legacyLiveTick": legacy_code,
    }
    if any(codes[key] != 200 for key in ("home", "conditions", "guide", "day8", "day9", "today")):
        raise AssertionError(f"public endpoint HTTP mismatch: {codes}")
    if legacy_code != 404:
        raise AssertionError(f"legacy live-tick must be 404, got {legacy_code}")
    if ui != expected:
        raise AssertionError(f"production UI mismatch: actual={ui!r} expected={expected!r}")

    required_simple = {
        "home": (home, ("レース探偵", "予想は当日も継続更新", "JRA公式オッズだけで評価")),
        "conditions": (conditions, CONDITION_MARKERS),
        "guide": (guide, GUIDE_MARKERS),
    }
    for label, (text, markers) in required_simple.items():
        missing = [marker for marker in markers if marker not in text]
        if missing:
            raise AssertionError(f"{label} missing markers: {missing}")

    for label, text in (("conditions", conditions), ("guide", guide)):
        if "予測データを使って買い目を確定しました" in text:
            raise AssertionError(f"{label} contains obsolete probability-finalization copy")

    if "<summary><b>全体</b>" not in home or "会場別回収率" not in home:
        raise AssertionError("home shared ROI section missing")
    if any(f"<summary><b>{course}</b>" in home for course in ("ライト", "スタンダード", "プレミアム")):
        raise AssertionError("home contains duplicate per-course ROI summary")

    day8 = parse_json(day8_raw, "day8")
    day9 = parse_json(day9_raw, "day9")
    current = parse_json(today_raw, "today")
    r8 = day8.get("races") if isinstance(day8, dict) else None
    r9 = day9.get("races") if isinstance(day9, dict) else None
    rt = current.get("races") if isinstance(current, dict) else None
    if not isinstance(r8, list) or not r8:
        raise AssertionError("day8 API race shape invalid")
    if not isinstance(r9, list) or not r9:
        raise AssertionError("day9 API race shape invalid")
    if not isinstance(rt, list):
        raise AssertionError("today API race shape invalid")

    selected = next((r for r in r9 if (r.get("publicState") or {}).get("code") == "buy" and r.get("raceId")), None)
    if not selected:
        raise AssertionError("historical selected race sample missing")
    race_code, race, _ = fetch(f"/races/{selected['raceId']}")
    if race_code != 200:
        raise AssertionError(f"historical race detail HTTP mismatch: {race_code}")
    if not all(course in race for course in ("ライト", "スタンダード", "プレミアム")):
        raise AssertionError("historical race detail course display missing")

    venue_counts = collections.Counter(str(r.get("venue") or "") for r in rt if r.get("venue"))
    states = collections.Counter(str((r.get("publicState") or {}).get("code") or "") for r in rt)
    structured = len(venue_counts) >= 2 and all(value == 12 for value in venue_counts.values())
    now = datetime.now(ZoneInfo("Asia/Tokyo"))
    frozen_projection = True
    if structured and now.hour >= 9:
        expected_selected = 5 * len(venue_counts)
        selected_like = sum(states.get(code, 0) for code in ("target", "buy", "hit", "miss", "overdue", "missing", "refund"))
        expected_skip = 7 * len(venue_counts)
        frozen_projection = states.get("pending", 0) == 0 and selected_like == expected_selected and states.get("skip", 0) == expected_skip
    if not frozen_projection:
        raise AssertionError(
            "today frozen selection projection mismatch: "
            f"venues={dict(venue_counts)} states={dict(states)} hour={now.hour}"
        )

    return {
        "expectedUi": expected,
        "actualUi": ui,
        "codes": codes,
        "day8RaceCount": len(r8),
        "day9RaceCount": len(r9),
        "todayRaceCount": len(rt),
        "todayVenues": dict(venue_counts),
        "todayStates": dict(states),
        "historicalRaceSample": selected["raceId"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--delay-seconds", type=float, default=5.0)
    args = parser.parse_args()
    attempts = max(1, args.attempts)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            result = validate_once()
            print("PRODUCTION_SMOKE_OK", json.dumps(result, ensure_ascii=False, sort_keys=True))
            return
        except Exception as exc:
            last_error = exc
            print(f"PRODUCTION_SMOKE_RETRY attempt={attempt}/{attempts}: {exc}", file=sys.stderr)
            if attempt < attempts:
                time.sleep(max(0.0, args.delay_seconds))
    raise AssertionError(f"production smoke failed after {attempts} attempts: {last_error}")


if __name__ == "__main__":
    main()
