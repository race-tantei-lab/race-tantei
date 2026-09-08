#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def config(path: str) -> dict:
    return json.loads(text(path))


def scheduled_body(source: str) -> str:
    marker = "async scheduled("
    start = source.index(marker)
    return source[start:]


def assert_gate_before_d1(entry_path: str, label: str) -> None:
    body = scheduled_body(text(entry_path))
    gate = body.index("await shouldRunOnJraRaceDay")
    stop = body.index("if (!raceDay.shouldRun)", gate)
    early_return = body.index("return;", stop)
    first_db = body.find("env.DB")
    require(first_db >= 0, f"{label}_D1_REFERENCE_MISSING")
    require(gate < stop < early_return < first_db, f"{label}_NON_RACE_DAY_GATE_NOT_BEFORE_D1")


def main() -> None:
    gate = text("src/v1/race-day-gate.ts")
    public_cfg = config("wrangler.jsonc")
    primary_cfg = config("wrangler.live-deadline.jsonc")
    backup_cfg = config("wrangler.live-deadline-backup.jsonc")

    public_main = str(public_cfg.get("main") or "")
    primary_main = str(primary_cfg.get("main") or "")
    backup_main = str(backup_cfg.get("main") or "")
    require((ROOT / public_main).exists(), "PUBLIC_WRANGLER_MAIN_MISSING")
    require((ROOT / primary_main).exists(), "PRIMARY_WRANGLER_MAIN_MISSING")
    require((ROOT / backup_main).exists(), "BACKUP_WRANGLER_MAIN_MISSING")
    require(primary_main == backup_main, "PRIMARY_BACKUP_ENTRY_MISMATCH")

    require("D1Database" not in gate and ".DB" not in gate, "RACE_DAY_GATE_MUST_NOT_TOUCH_D1")
    require("officialCalendarUrl" in gate and "parseOfficialCalendar" in gate, "RACE_DAY_GATE_OFFICIAL_DAILY_CALENDAR_MISSING")
    require("officialMonthCalendarUrl" in gate and "monthCalendarListsDay" in gate, "RACE_DAY_GATE_OFFICIAL_MONTH_FALLBACK_MISSING")
    require("HTTP_(?:404|410)" in gate, "RACE_DAY_GATE_404_410_STOP_MISSING")
    require('shouldRun: false, reason: "no_calendar"' in gate, "RACE_DAY_GATE_404_STOP_RESULT_MISSING")
    require('shouldRun: false, reason: "not_listed_in_official_month_calendar"' in gate, "RACE_DAY_GATE_MONTH_STOP_RESULT_MISSING")
    require('reason: "probe_failed_fail_open"' in gate, "RACE_DAY_GATE_NETWORK_FAIL_OPEN_MISSING")
    require('reason: "unparsed_calendar_fail_open"' in gate, "RACE_DAY_GATE_PARSER_FAIL_OPEN_MISSING")

    assert_gate_before_d1(primary_main, "LIVE")

    public = scheduled_body(text(public_main))
    public_gate = public.index("await shouldRunOnJraRaceDay")
    public_stop = public.index("if (!raceDay.shouldRun)", public_gate)
    public_return = public.index("return;", public_stop)
    public_maintenance = public.index("runBoundedPublicMaintenance", public_return)
    require(public_gate < public_stop < public_return < public_maintenance, "PUBLIC_NON_RACE_DAY_GATE_NOT_BEFORE_MAINTENANCE")

    require(primary_cfg.get("triggers", {}).get("crons", []) == ["* * * * *"], "PRIMARY_CRON_CHANGED")
    require(backup_cfg.get("triggers", {}).get("crons", []) == ["2-59/5 * * * *"], "BACKUP_CRON_NOT_FIVE_MINUTES")

    print(f"RACE_DAY_GATE_OK public={public_main} live={primary_main} no_d1_before_official_race_day=true primary=1m backup=5m")


if __name__ == "__main__":
    main()
