import sys
import types
from pathlib import Path


def load_production_base(name: str, source_path: Path, *, patch_writes: bool = False):
    source = source_path.read_text(encoding="utf-8")
    import_needle = "v4 = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(v4)"
    import_replacement = (
        "v4 = importlib.util.module_from_spec(spec)\n"
        "import sys\n"
        "sys.modules[spec.name] = v4\n"
        "spec.loader.exec_module(v4)"
    )
    if import_needle not in source:
        raise RuntimeError("PRODUCTION_BASE_IMPORT_PATCH_TARGET_MISSING")
    source = source.replace(import_needle, import_replacement, 1)

    if patch_writes:
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
            raise RuntimeError("PRODUCTION_BASE_BATCH_PATCH_TARGET_MISSING")
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
            raise RuntimeError("PRODUCTION_BASE_BET_BATCH_PATCH_TARGET_MISSING")
        source = source.replace(bet_needle, bet_replacement, 1)

    module = types.ModuleType(name)
    module.__file__ = str(source_path)
    module.__package__ = None
    sys.modules[name] = module
    exec(compile(source, str(source_path), "exec"), module.__dict__, module.__dict__)
    return module
