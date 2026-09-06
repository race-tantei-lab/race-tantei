#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def scheduled_body(source: str) -> str:
    marker = "async scheduled("
    start = source.index(marker)
    return source[start:]


def main() -> None:
    gate = text("src/v1/race-day-gate.ts")
    live = scheduled_body(text("src/live-deadline-entry-v3.ts"))
    public = scheduled_body(text("src/public-site-entry-recovery-20260906.ts"))
    primary_cfg = text("wrangler.live-deadline.jsonc")
    backup_cfg = text("wrangler.live-deadline-backup.jsonc")

    require("D1Database" not in gate and ".DB" not in gate, "RACE_DAY_GATE_MUST_NOT_TOUCH_D1")
    require("officialCalendarUrl" in gate and "parseOfficialCalendar" in gate, "RACE_DAY_GATE_OFFICIAL_DAILY_CALENDAR_MISSING")
    require("officialMonthCalendarUrl" in gate and "monthCalendarListsDay" in gate, "RACE_DAY_GATE_OFFICIAL_MONTH_FALLBACK_MISSING")
    require("HTTP_(?:404|410)" in gate, "RACE_DAY_GATE_404_410_STOP_MISSING")
    require('shouldRun: false, reason: "no_calendar"' in gate, "RACE_DAY_GATE_404_STOP_RESULT_MISSING")
    require('shouldRun: false, reason: "not_listed_in_official_month_calendar"' in gate, "RACE_DAY_GATE_MONTH_STOP_RESULT_MISSING")
    require('reason: "probe_failed_fail_open"' in gate, "RACE_DAY_GATE_NETWORK_FAIL_OPEN_MISSING")
    require('reason: "unparsed_calendar_fail_open"' in gate, "RACE_DAY_GATE_PARSER_FAIL_OPEN_MISSING")

    live_gate = live.index("await shouldRunOnJraRaceDay")
    live_stop = live.index("if (!raceDay.shouldRun)", live_gate)
    live_return = live.index("return;", live_stop)
    live_first_db = live.index("env.DB")
    require(live_gate < live_stop < live_return < live_first_db, "LIVE_NON_RACE_DAY_GATE_NOT_BEFORE_D1")

    public_gate = public.index("await shouldRunOnJraRaceDay")
    public_stop = public.index("if (!raceDay.shouldRun)", public_gate)
    public_return = public.index("return;", public_stop)
    public_maintenance = public.index("runBoundedPublicMaintenance", public_return)
    require(public_gate < public_stop < public_return < public_maintenance, "PUBLIC_NON_RACE_DAY_GATE_NOT_BEFORE_MAINTENANCE")

    require('"* * * * *"' in primary_cfg, "PRIMARY_CRON_CHANGED")
    require('"2-59/5 * * * *"' in backup_cfg, "BACKUP_CRON_NOT_FIVE_MINUTES")

    print("RACE_DAY_GATE_OK no_d1_before_official_race_day=true primary=1m backup=5m ambiguous_fail_open=true")


if __name__ == "__main__":
    main()
