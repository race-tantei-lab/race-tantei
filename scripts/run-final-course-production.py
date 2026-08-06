import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "scripts" / "publish-nonlinear-v4-production.py"
POLICY_PATH = ROOT / "scripts" / "final-course-policy.py"


def load_policy():
    spec = importlib.util.spec_from_file_location("final_course_policy", POLICY_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("FINAL_POLICY_MODULE_LOAD_FAILED")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_production_namespace():
    source = SOURCE_PATH.read_text(encoding="utf-8")
    import_needle = "v4 = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(v4)"
    import_replacement = (
        "v4 = importlib.util.module_from_spec(spec)\n"
        "import sys\n"
        "sys.modules[spec.name] = v4\n"
        "spec.loader.exec_module(v4)"
    )
    if import_needle not in source:
        raise RuntimeError("FINAL_PRODUCTION_IMPORT_PATCH_TARGET_MISSING")
    source = source.replace(import_needle, import_replacement, 1)

    insert_needle = '''def insert_many(table_sql, rows, columns_per_row):
    if not rows:
        return
    placeholders = ",".join(["(" + ",".join(["?"] * columns_per_row) + ")"] * len(rows))
    params = [value for row in rows for value in row]
    execute(table_sql.format(values=placeholders), params)
'''
    insert_replacement = '''def insert_many(table_sql, rows, columns_per_row):
    if not rows:
        return
    chunk_size = max(1, 80 // max(1, columns_per_row))
    for start in range(0, len(rows), chunk_size):
        chunk = rows[start:start + chunk_size]
        placeholders = ",".join(["(" + ",".join(["?"] * columns_per_row) + ")"] * len(chunk))
        params = [value for row in chunk for value in row]
        execute(table_sql.format(values=placeholders), params)
'''
    if insert_needle not in source:
        raise RuntimeError("FINAL_PRODUCTION_BATCH_PATCH_TARGET_MISSING")
    source = source.replace(insert_needle, insert_replacement, 1)

    bet_needle = '''    if bet_values:
        placeholders = ",".join(["(?,?,?,?,?,?,?,?,'pending')"] * len(bet_values))
        execute(
            """INSERT INTO rt_bets (
              prediction_id,race_id,bet_type,combination,stake_yen,assumed_odds,
              hit_probability,expected_value_pct,settlement_status
            ) VALUES """ + placeholders,
            [value for row in bet_values for value in row],
        )
'''
    bet_replacement = '''    if bet_values:
        for start in range(0, len(bet_values), 8):
            chunk = bet_values[start:start + 8]
            placeholders = ",".join(["(?,?,?,?,?,?,?,?,'pending')"] * len(chunk))
            execute(
                """INSERT INTO rt_bets (
                  prediction_id,race_id,bet_type,combination,stake_yen,assumed_odds,
                  hit_probability,expected_value_pct,settlement_status
                ) VALUES """ + placeholders,
                [value for row in chunk for value in row],
            )
'''
    if bet_needle not in source:
        raise RuntimeError("FINAL_PRODUCTION_BET_BATCH_PATCH_TARGET_MISSING")
    source = source.replace(bet_needle, bet_replacement, 1)
    source = source.replace("production-nonlinear-v4.json", "production-final-course-model.json")

    namespace = {
        "__name__": "final_course_production_module",
        "__file__": str(SOURCE_PATH),
    }
    exec(compile(source, str(SOURCE_PATH), "exec"), namespace, namespace)
    return namespace


def configure_namespace(namespace, policy):
    namespace["MODEL_VERSION"] = policy.MODEL_VERSION
    namespace["COURSE_BUDGETS"] = dict(policy.COURSE_TARGET_STAKES)
    namespace["build_bets"] = policy.build_bets
    return namespace


def main():
    policy = load_policy()
    namespace = configure_namespace(load_production_namespace(), policy)
    namespace["main"]()


if __name__ == "__main__":
    main()
