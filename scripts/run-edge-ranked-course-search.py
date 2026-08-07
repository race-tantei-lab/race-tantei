import importlib.util
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COURSE_PATH = ROOT / "scripts" / "analyze-course-specific-regime-search.py"
FULL_PATH = ROOT / "scripts" / "analyze-full-period-online-search.py"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


course = load("edge_ranked_course", COURSE_PATH)
full = load("edge_ranked_full", FULL_PATH)
base = course.base
regime = base
ctx = base.ctx

VALUE_RANK_MODES = (
    "edge_only",
    "edge_probability",
    "edge_outsider",
    "edge_form",
)


def number(value, default=0.0):
    return base.number(value, default)


def edge_rank_race(race, mode):
    item = dict(race)
    runners = []
    for row in race.get("runners", []):
        copied = dict(row)
        copied["regimeFormSignal"] = base.form_signal(copied)
        edge = max(1e-9, number(copied.get("edge"), 1.0))
        probability = max(1e-9, number(copied.get("probability")))
        market = max(1e-9, number(copied.get("market")))
        popularity = max(1.0, number(copied.get("popularity"), 18.0))
        form = number(copied.get("regimeFormSignal"))
        if mode == "edge_only":
            score = math.log(edge)
        elif mode == "edge_probability":
            score = math.log(edge) + 0.35 * math.log(probability)
        elif mode == "edge_outsider":
            score = math.log(edge) + 0.14 * math.log(popularity) + 0.10 * math.log(probability)
        else:
            score = math.log(edge) + 0.18 * math.log(probability) + 0.16 * form
        copied["valueRankScore"] = score
        copied["valueOriginalMarket"] = market
        runners.append(copied)
    runners.sort(
        key=lambda row: (
            -number(row.get("valueRankScore")),
            -number(row.get("edge")),
            int(number(row.get("horseNo"))),
        )
    )
    item["runners"] = runners
    if runners:
        item["topProbability"] = number(runners[0].get("probability"))
        item["probabilityGap"] = (
            number(runners[0].get("probability")) - number(runners[1].get("probability"))
            if len(runners) > 1 else number(runners[0].get("probability"))
        )
        item["top3Concentration"] = sum(number(row.get("probability")) for row in runners[:3])
        item["maxEdge"] = max(number(row.get("edge"), 1.0) for row in runners[:8])
        item["disagreement"] = sum(
            abs(number(row.get("probability")) - number(row.get("market")))
            for row in runners
        )
    return item


def process_segment(predicted, store, mode, update=True):
    records = []
    for race in sorted(
        predicted,
        key=lambda row: (row["raceDate"], row["venue"], int(number(row.get("raceNo")))),
    ):
        ranked = edge_rank_race(race, mode)
        keys, summary = base.candidate_summary(ranked, store)
        records.append(base.race_signal_record(ranked, summary))
        if update:
            for primitive in ctx.PRIMITIVES:
                probability = base.event_probability(ranked, primitive)
                returned = base.primitive_return_multiple(ranked, primitive)
                base.update_store(store, primitive, keys, returned, probability)
    return records


def simulate_development(enriched_races, rank_mode):
    store = {}
    records = []
    archive_start = min(race["raceDate"] for race in enriched_races)
    for start, end in full.development_segments(archive_start, course.FINAL_START):
        training = [race for race in enriched_races if race["raceDate"] < start]
        target = [race for race in enriched_races if start <= race["raceDate"] < end]
        if not target:
            continue
        predicted, _ = full.ranking_predictions(training, target)
        records.extend(process_segment(predicted, store, rank_mode, update=True))
    return records, store


def final_records(enriched_races, rank_mode, frozen_store):
    training = [race for race in enriched_races if race["raceDate"] < course.FINAL_START]
    target = [race for race in enriched_races if race["raceDate"] >= course.FINAL_START]
    predicted, _ = full.ranking_predictions(training, target)
    return process_segment(predicted, frozen_store, rank_mode, update=False)


course.base.simulate_development = simulate_development
course.base.final_records = final_records
course.base.RANK_MODES = VALUE_RANK_MODES
course.EXPLORATION_ID = "edge-ranked-course"
course.OUTPUT = ROOT / "analysis-results" / "exploration-edge-ranked-course.json"

course.main()
