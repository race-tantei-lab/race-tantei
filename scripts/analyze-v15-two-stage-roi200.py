import importlib.util
import json
import math
import shutil
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

ROOT = Path(__file__).resolve().parents[1]
V14_PATH = ROOT / "scripts" / "analyze-v14-historical-roi200.py"
V15_OUTPUT = ROOT / "v15-two-stage-roi200-search.json"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


v14 = load_module("v15_base", V14_PATH)
if not hasattr(v14.v7, "month_sequence"):
    v14.v7.month_sequence = v14.v7.v7.month_sequence

v14.MODEL_VERSION = "v15-two-stage-hit-payout-roi200"
v14.MAX_TRAIN_ROWS_PER_TYPE = 180_000
v14.MODEL_PRIOR_WEIGHTS = (0.75, 0.90, 1.0)
v14.ALLOCATION_POWERS = (1.0, 2.0, 4.0, 8.0)
v14.MAX_TICKET_SHARE = {"ライト": 0.70, "スタンダード": 0.70, "プレミアム": 0.80}
v14.RACE_SCORE_MODES = ("minimum", "mean", "lower_mean", "light")


class TwoStageModel:
    def __init__(self, classifier, payout_model, probability_scale, payout_fallback):
        self.classifier = classifier
        self.payout_model = payout_model
        self.probability_scale = probability_scale
        self.payout_fallback = payout_fallback

    def predict_return(self, x):
        hit_probability = self.classifier.predict_proba(x)[:, 1]
        hit_probability = np.clip(hit_probability * self.probability_scale, 0.0, 1.0)
        if self.payout_model is None:
            conditional_payout = np.full(len(x), self.payout_fallback, dtype=float)
        else:
            conditional_payout = np.expm1(self.payout_model.predict(x))
            conditional_payout = np.clip(conditional_payout, 1.0, v14.TARGET_CAP_MULTIPLE)
        return hit_probability * conditional_payout


def reservoir_indexes(size, target_size, rng):
    if size <= target_size:
        return np.arange(size, dtype=int)
    return np.asarray(rng.choice(size, target_size, replace=False), dtype=int)


def fit_two_stage_models(races, primitives_by_type, seed):
    rng = np.random.default_rng(seed)
    models = {}
    priors = {}
    audit = {}

    for type_index, bet_type in enumerate(v14.BET_TYPES):
        primitives = primitives_by_type[bet_type]
        x_rows = []
        hit_targets = []
        payout_targets = []
        primitive_totals = defaultdict(float)
        primitive_counts = defaultdict(int)
        primitive_hits = defaultdict(int)
        primitive_hit_payouts = defaultdict(list)

        for race in races:
            for primitive in primitives:
                payout_multiple = v14.base.primitive_payout(race, primitive) / 100.0
                capped = min(v14.TARGET_CAP_MULTIPLE, max(0.0, payout_multiple))
                x_rows.append(v14.primitive_features(race, primitive))
                hit_targets.append(int(capped > 0.0))
                payout_targets.append(capped)
                primitive_totals[primitive[0]] += capped
                primitive_counts[primitive[0]] += 1
                if capped > 0:
                    primitive_hits[primitive[0]] += 1
                    primitive_hit_payouts[primitive[0]].append(capped)

        x_all = np.asarray(x_rows, dtype=np.float32)
        y_hit_all = np.asarray(hit_targets, dtype=np.int8)
        y_payout_all = np.asarray(payout_targets, dtype=np.float32)
        positives = np.flatnonzero(y_hit_all == 1)
        negatives = np.flatnonzero(y_hit_all == 0)

        max_rows = v14.MAX_TRAIN_ROWS_PER_TYPE
        minimum_negative_rows = min(len(negatives), max(len(positives) * 8, 20_000))
        allowed_negative_rows = min(len(negatives), max(minimum_negative_rows, max_rows - len(positives)))
        sampled_negative = negatives if len(negatives) <= allowed_negative_rows else rng.choice(negatives, allowed_negative_rows, replace=False)
        classifier_indexes = np.concatenate([positives, np.asarray(sampled_negative, dtype=int)])
        rng.shuffle(classifier_indexes)
        x_classifier = x_all[classifier_indexes]
        y_classifier = y_hit_all[classifier_indexes]

        classifier = HistGradientBoostingClassifier(
            loss="log_loss",
            max_leaf_nodes=31,
            learning_rate=0.045,
            max_iter=170,
            l2_regularization=14.0,
            min_samples_leaf=70,
            max_bins=63,
            random_state=seed + type_index,
        )
        classifier.fit(x_classifier, y_classifier)

        raw_train_probability = classifier.predict_proba(x_classifier)[:, 1]
        sampled_rate = float(np.mean(y_classifier))
        true_rate = float(np.mean(y_hit_all))
        mean_raw = float(np.mean(raw_train_probability))
        sampling_correction = true_rate / max(1e-9, sampled_rate)
        probability_scale = sampling_correction * sampled_rate / max(1e-9, mean_raw)
        probability_scale = float(np.clip(probability_scale, 0.02, 2.0))

        payout_model = None
        positive_payouts = y_payout_all[positives]
        if len(positives) >= 180:
            payout_indexes = positives
            if len(payout_indexes) > 80_000:
                payout_indexes = np.asarray(rng.choice(payout_indexes, 80_000, replace=False), dtype=int)
            payout_model = HistGradientBoostingRegressor(
                loss="squared_error",
                max_leaf_nodes=23,
                learning_rate=0.035,
                max_iter=140,
                l2_regularization=18.0,
                min_samples_leaf=max(25, min(80, len(payout_indexes) // 20)),
                max_bins=63,
                random_state=seed + 100 + type_index,
            )
            payout_model.fit(x_all[payout_indexes], np.log1p(y_payout_all[payout_indexes]))

        payout_fallback = float(np.median(positive_payouts)) if len(positive_payouts) else 1.0
        models[bet_type] = TwoStageModel(classifier, payout_model, probability_scale, payout_fallback)

        overall_return = float(np.mean(y_payout_all))
        priors[bet_type] = {}
        for primitive in primitives:
            code = primitive[0]
            count = primitive_counts[code]
            prior = (primitive_totals[code] + overall_return * 120.0) / (count + 120.0)
            priors[bet_type][code] = float(prior)

        audit[bet_type] = {
            "allRows": len(y_hit_all),
            "classifierRows": len(y_classifier),
            "positiveRows": int(len(positives)),
            "trueHitRatePct": true_rate * 100.0,
            "probabilityScale": probability_scale,
            "medianHitPayoutMultiple": payout_fallback,
            "meanCappedReturnMultiple": overall_return,
            "payoutRegressorUsed": payout_model is not None,
        }

    return models, priors, audit


def predict_two_stage_scores(races, models, priors, primitives_by_type, model_weight):
    output = []
    for race in races:
        scores = {}
        for bet_type, primitives in primitives_by_type.items():
            x = np.asarray([v14.primitive_features(race, primitive) for primitive in primitives], dtype=np.float32)
            expected_returns = models[bet_type].predict_return(x)
            for primitive, expected_return in zip(primitives, expected_returns):
                prior = priors[bet_type][primitive[0]]
                score = model_weight * float(expected_return) + (1.0 - model_weight) * float(prior)
                scores[primitive[0]] = max(0.0, score)
        item = dict(race)
        item["primitiveScores"] = scores
        output.append(item)
    return output


v14.fit_value_models = fit_two_stage_models
v14.predict_scores = predict_two_stage_scores

_original_future_predictions = v14.future_predictions


def safe_future_predictions(*args, **kwargs):
    try:
        return _original_future_predictions(*args, **kwargs)
    except RuntimeError as error:
        if str(error) != "V14_SELECTED_BELOW_FIVE":
            raise
        return {
            "generated": False,
            "error": "UPCOMING_ENTRIES_BELOW_FIVE_PER_VENUE_DAY",
            "futureRaces": 0,
            "selectedRaces": 0,
            "coverage": [],
            "races": [],
        }


v14.future_predictions = safe_future_predictions
v14.main()

if v14.V14_OUTPUT.exists():
    shutil.copyfile(v14.V14_OUTPUT, V15_OUTPUT)
    report = json.loads(V15_OUTPUT.read_text(encoding="utf-8"))
    report["modelVersion"] = v14.MODEL_VERSION
    report["twoStageMethod"] = {
        "hitProbabilityModel": "HistGradientBoostingClassifier",
        "conditionalPayoutModel": "HistGradientBoostingRegressor on log payout for hit rows",
        "expectedReturn": "predicted hit probability multiplied by predicted conditional payout",
        "maximumTicketShare": v14.MAX_TICKET_SHARE,
    }
    V15_OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    v14.OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print(json.dumps({
    "modelVersion": v14.MODEL_VERSION,
    "report": str(V15_OUTPUT.name),
}, ensure_ascii=False))
