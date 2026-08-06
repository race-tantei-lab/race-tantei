import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "race-tantei-fixed-constraints.json"

EXPECTED = {
    "version": 1,
    "immutableProjectRules": {
        "minimumRacesPerVenueDay": 5,
        "mayIncreaseRaces": True,
        "mayDecreaseBelowMinimum": False,
        "officialOddsOnly": True,
        "syntheticOddsForbidden": True,
        "postResultLeakageForbidden": True,
    },
    "courses": {
        "ライト": {
            "budgetYen": 2000,
            "ticketCount": 6,
            "allowedBetTypes": ["単勝", "ワイド", "馬連"],
            "requireEveryAllowedBetType": True,
        },
        "スタンダード": {
            "budgetYen": 5000,
            "ticketCount": 15,
            "allowedBetTypes": ["単勝", "ワイド", "馬連", "馬単", "3連複"],
            "requireEveryAllowedBetType": True,
        },
        "プレミアム": {
            "budgetYen": 10000,
            "ticketCount": 16,
            "allowedBetTypes": ["単勝", "ワイド", "馬連", "馬単", "3連複", "3連単"],
            "requireEveryAllowedBetType": True,
        },
    },
}


def main() -> None:
    actual = json.loads(CONFIG.read_text(encoding="utf-8"))
    if actual != EXPECTED:
        raise SystemExit(
            "FIXED_CONSTRAINTS_CHANGED: "
            "minimum five races, current three-course structure, official odds only, "
            "and no synthetic odds are immutable project rules."
        )
    print("Fixed constraints verified.")


if __name__ == "__main__":
    main()
