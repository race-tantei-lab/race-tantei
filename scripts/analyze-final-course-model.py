import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

ROOT = Path(__file__).resolve().parents[1]
V4_PATH = ROOT / "scripts" / "train-nonlinear-market-blend-v4.py"
POLICY_PATH = ROOT / "scripts" / "final-course-policy.py"
BASE_REPORT_PATH = ROOT / "analysis-results" / "nonlinear-market-blend-v4.json"
OUTPUT_PATH = ROOT / "final-course-model-analysis.json"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


v4 = load_module("final_course_v4_analysis", V4_PATH)
policy = load_module("final_course_policy", POLICY_PATH)


def train_selected_model(train_races, selected):
    x_train, y_train, base_weights = v4.flatten_runners(train_races)
    train_runner_odds = np.asarray(
        [runner["winOdds"] for race in train_races for runner in race["runners"]],
        dtype=np.float64,
    )
    weights = base_weights.copy()
    winners = y_train == 1
    power = float(selected.get("longshotPower", 0.0))
    weights[winners] *= np.minimum(
        6.0,
        np.power(np.maximum(1.0, train_runner_odds[winners]), power),
    )
    model = HistGradientBoostingClassifier(
        loss="log_loss",
        max_leaf_nodes=int(selected["max_leaf_nodes"]),
        learning_rate=float(selected["learning_rate"]),
        max_iter=int(selected["max_iter"]),
        l2_regularization=float(selected["l2_regularization"]),
        min_samples_leaf=40,
        random_state=42,
    )
    model.fit(x_train, y_train, sample_weight=weights)
    return model


def rounded_metrics(rows):
    result = {}
    for course, metrics in rows.items():
        result[course] = {}
        for key, value in metrics.items():
            if isinstance(value, dict):
                result[course][key] = {month: round(float(roi), 4) for month, roi in value.items()}
            elif isinstance(value, (int, float, np.floating)) and value is not None:
                result[course][key] = round(float(value), 4)
            else:
                result[course][key] = value
    return result


def save_state(report):
    v4.sql(
        """
        INSERT INTO rt_system_state (state_key,state_value,updated_at)
        VALUES (?,?,CURRENT_TIMESTAMP)
        ON CONFLICT(state_key) DO UPDATE SET state_value=excluded.state_value,updated_at=CURRENT_TIMESTAMP
        """,
        ["final_course_model:analysis", json.dumps(report, ensure_ascii=False, separators=(",", ":"))],
    )


def main():
    base_report = json.loads(BASE_REPORT_PATH.read_text(encoding="utf-8"))
    selected = base_report["selectedModel"]
    rows, payouts = v4.load_data()
    races = v4.build_dataset(rows, payouts)
    split = {
        name: [race for race in races if v4.split_name(race["raceDate"]) == name]
        for name in ("train", "validation", "holdout")
    }
    model = train_selected_model(split["train"], selected)
    blend = float(selected.get("blend", 1.0))
    validation = v4.attach_probabilities(model, split["validation"], blend)
    holdout = v4.attach_probabilities(model, split["holdout"], blend)
    validation_selected = v4.select_races(validation, 5, "disagreement")
    holdout_selected = v4.select_races(holdout, 5, "disagreement")
    validation_metrics = policy.evaluate(validation_selected)
    holdout_metrics = policy.evaluate(holdout_selected)
    target_roi = 200.0
    required_hit = 36.8
    promotion = all(
        (holdout_metrics[course]["roiPct"] or 0) >= target_roi
        and (holdout_metrics[course]["hitRatePct"] or 0) >= required_hit
        for course in policy.COURSES
    )
    report = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "modelVersion": policy.MODEL_VERSION,
        "method": "Nonlinear v4 runner ranking + fixed course-specific roi-policy-v1 ticket construction.",
        "predictionModel": selected,
        "raceSelection": {"mode": "disagreement", "racesPerVenueDay": 5},
        "courseTargetStakes": policy.COURSE_TARGET_STAKES,
        "coursePoliciesDistinct": True,
        "samples": {name: len(items) for name, items in split.items()},
        "selectedRaces": {"validation": len(validation_selected), "holdout": len(holdout_selected)},
        "validation": rounded_metrics(validation_metrics),
        "holdout": rounded_metrics(holdout_metrics),
        "targetRoiPct": target_roi,
        "requiredHitRatePct": required_hit,
        "promotionEligible": promotion,
        "holdoutCaveat": "July has been inspected in prior iterations and is no longer a pristine untouched holdout.",
    }
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    save_state(report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
