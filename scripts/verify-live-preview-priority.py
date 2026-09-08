#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src" / "v1" / "completed-worker-live-lock.ts").read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    required = [
        "export const MAX_PREVIEW_GENERATIONS_PER_TICK = 1;",
        "export function livePreviewPriorityRank(row: LivePreviewPriorityInput): number {",
        "if (!Number.isFinite(row.remainingMs) || row.remainingMs <= 0) return 99;",
        "if (row.remainingMs <= FINAL_LOCK_ARM_MS) return 0;",
        "if (!row.hasPreview && row.remainingMs <= PREVIEW_REQUIRED_MS) return 1;",
        "if (!row.hasPreview) return 2;",
        "if (!row.previewFresh) return 3;",
        "return 4;",
        ".sort((a, b) => livePreviewPriorityRank(a) - livePreviewPriorityRank(b) || a.remainingMs - b.remainingMs || a.raceId.localeCompare(b.raceId))",
    ]
    for marker in required:
        require(marker in SOURCE, f"LIVE_PREVIEW_PRIORITY_MARKER_MISSING:{marker}")

    # Contract simulation: with one generation per minute, every missing preview
    # outranks a stale refresh outside the final-lock window, so 15 selected races
    # can all receive a first preview in 15 ticks without refresh starvation.
    minute = 60_000

    def rank(remaining_ms: int, has_preview: bool, preview_fresh: bool) -> int:
        if remaining_ms <= 0:
            return 99
        if remaining_ms <= 30 * minute:
            return 0
        if not has_preview and remaining_ms <= 30 * minute:
            return 1
        if not has_preview:
            return 2
        if not preview_fresh:
            return 3
        return 4

    missing = [f"missing-{index + 1}" for index in range(15)]
    for _tick in range(15):
        candidates = [
            (race_id, (90 - index) * minute, False, False)
            for index, race_id in enumerate(missing)
        ] + [("stale-refresh", 31 * minute, True, False)]
        candidates.sort(key=lambda row: (rank(row[1], row[2], row[3]), row[1], row[0]))
        chosen = candidates[0]
        require(chosen[0] != "stale-refresh", "LIVE_PREVIEW_STALE_REFRESH_STARVES_MISSING")
        missing = [race_id for race_id in missing if race_id != chosen[0]]

    require(not missing, "LIVE_PREVIEW_15_RACES_NOT_COVERED_IN_15_TICKS")
    print("LIVE_PREVIEW_PRIORITY_OK missing_before_refresh=true max_generations_per_tick=1 selected_coverage_ticks=15")


if __name__ == "__main__":
    main()
