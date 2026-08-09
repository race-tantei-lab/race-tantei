import argparse, collections, importlib.util, itertools, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    pmod = load(ROOT / "scripts" / "generate-final-preday-selection.py", "preday_bins")
    lmod = load(ROOT / "scripts" / "generate-final-live-bets.py", "live_helpers")
    collector = lmod.load_collector(ROOT)
    rmod = lmod.load_rules_module(ROOT)
    rules = rmod.load_rules()
    if len(rules) != 316:
        raise RuntimeError(f"RULE_COUNT_INVALID:{len(rules)}")

    rules_by_bet = collections.defaultdict(list)
    for rule in rules:
        bet = next((v for n, v in rule["conditions"] if n == "bet"), None)
        if bet is None:
            for bt in range(6):
                rules_by_bet[bt].append(rule)
        else:
            rules_by_bet[int(bet)].append(rule)

    race_rows = collector.d1_query(
        """
        SELECT race_id AS raceId,race_date AS raceDate,venue,race_no AS raceNo,
               race_name AS raceName,conditions,surface,distance_m AS distanceM,
               direction,start_time_jst AS startTimeJst
        FROM rt_races
        WHERE race_date=? AND venue IN ('札幌','新潟','中京')
        ORDER BY venue,race_no
        """,
        [args.date],
    )
    if len(race_rows) != 36:
        raise RuntimeError(f"TARGET_RACE_COUNT_INVALID:{len(race_rows)}")

    ids = [str(r["raceId"]) for r in race_rows]
    runners = []
    for i in range(0, len(ids), 8):
        batch = ids[i:i+8]
        q = ",".join("?" for _ in batch)
        rows = collector.d1_query(
            f"SELECT race_id AS raceId,horse_no AS horseNo,horse_name AS horseName,jockey,trainer,runner_status AS runnerStatus FROM rt_runners WHERE race_id IN ({q}) ORDER BY race_id,horse_no",
            batch,
        )
        runners.extend(r for r in rows if (r.get("runnerStatus") or "active") == "active")

    by_race = collections.defaultdict(list)
    for row in runners:
        by_race[str(row["raceId"])].append(row)

    raw_hf = {}
    for i in range(0, len(runners), 32):
        raw_hf.update(lmod.history_features_remote(collector, args.date, runners[i:i+32]))

    hf_all = collections.defaultdict(dict)
    for (rid, hno), (form, speed, jr, trr, starts, top3, has) in raw_hf.items():
        hf_all[rid][hno] = (
            pmod.formcode(form, has), pmod.formcode(speed, has),
            pmod.ratecode(jr), pmod.ratecode(trr), pmod.startsbin(starts), top3,
        )

    venue_map = {v: i for i, v in enumerate(pmod.VENUES)}
    targets = []
    specs = [(0,1,False),(1,2,False),(2,2,False),(3,2,True),(4,3,False),(5,3,True)]
    for race in race_rows:
        rid = str(race["raceId"])
        rs = by_race.get(rid, [])
        n = len(rs)
        if n < 3:
            raise RuntimeError(f"RUNNERS_TOO_FEW:{rid}:{n}")
        venue = str(race["venue"])
        surface = str(race.get("surface") or "障害")
        dm = int(race.get("distanceM") or 0)
        rn = int(race["raceNo"])
        if dm <= 0:
            raise RuntimeError(f"DISTANCE_INVALID:{rid}:{dm}")
        base = {
            "venue": venue_map[venue],
            "surface": {"芝":0,"ダート":1,"障害":2}.get(surface,2),
            "dist": pmod.distbin(dm),
            "field": pmod.fieldbin(n),
            "raceNo": pmod.rnobin(rn),
            "season": pmod.seasonbin(int(args.date[5:7])),
            "rclass": pmod.classbin(race.get("raceName"), race.get("conditions")),
            "direction": pmod.directionbin(venue, surface, dm, race.get("direction")),
        }
        horse_nos = [int(r["horseNo"]) for r in rs]
        hfeat = hf_all[rid]
        race_score = 0.0
        best = []
        for bt, k, ordered in specs:
            positions = itertools.permutations(range(n), k) if ordered else itertools.combinations(range(n), k)
            for pos in positions:
                try:
                    fs = [hfeat[horse_nos[i]] for i in pos]
                except KeyError as error:
                    raise RuntimeError(f"HISTORY_FEATURE_MISSING:{rid}:{error}")
                vals = dict(base)
                vals["bet"] = bt
                vals.update({
                    "goodcnt": min(3, sum(1 for q in fs if q[0] >= 3)),
                    "bestform": max(q[0] for q in fs),
                    "bestspeed": max(q[1] for q in fs),
                    "bestj": max(q[2] for q in fs),
                    "bestt": max(q[3] for q in fs),
                    "expcnt": min(3, sum(1 for q in fs if q[4] >= 2)),
                    "top3lastsum": min(7, sum(q[5] for q in fs)),
                })
                score = lmod.rule_score(rules_by_bet, bt, vals, preday=True)
                if score > race_score:
                    race_score = score
                    best = [{"bet": bt, "horses": [horse_nos[i] for i in pos], "predayScore": score}]
                elif score == race_score and score > 0 and len(best) < 8:
                    best.append({"bet": bt, "horses": [horse_nos[i] for i in pos], "predayScore": score})
        targets.append({
            "raceId": rid, "raceDate": args.date, "venue": venue, "raceNo": rn,
            "raceName": race.get("raceName"), "startTimeJst": race.get("startTimeJst"),
            "surface": surface, "distanceM": dm, "raceScore": race_score,
            "bestPredayTickets": best,
        })

    selected = []
    for venue in ("札幌","新潟","中京"):
        rows = [x for x in targets if x["venue"] == venue]
        rows.sort(key=lambda x: (-x["raceScore"], x["raceNo"]))
        chosen = rows[:5]
        if len(chosen) != 5:
            raise RuntimeError(f"INSUFFICIENT_TARGET_RACES:{venue}:{len(chosen)}")
        for row in chosen:
            row["selected"] = True
        selected.extend(chosen)

    payload = {
        "date": args.date,
        "selected": selected,
        "allRaces": targets,
        "sourceRuleCount": 316,
        "selectionRule": "previous-day score, top five per venue, tie raceNo ascending",
        "resultDataUsedForTargetDay": False,
        "dataSource": "production D1 direct; target-date results excluded",
    }
    Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"selected": [(x["venue"], x["raceNo"], round(x["raceScore"], 3)) for x in selected]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
