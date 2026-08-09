import importlib.util
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
COLLECTOR = ROOT / "scripts" / "collect-jra-official-odds.py"
SELECTION = ROOT / "analysis-results" / "final-aug9-selection.json"
REPORT = ROOT / "analysis-results" / "aug9-selected-payout-sync.json"

spec = importlib.util.spec_from_file_location("payout_collector", COLLECTOR)
if spec is None or spec.loader is None:
    raise RuntimeError("COLLECTOR_IMPORT_FAILED")
collector = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = collector
spec.loader.exec_module(collector)

BET_TYPES = ("単勝", "複勝", "枠連", "ワイド", "馬連", "馬単", "3連複", "3連単")


def normalize_bet_type(value: str):
    compact = re.sub(r"\s+", "", value).replace("３", "3")
    return next((t for t in BET_TYPES if compact == t), None)


def normalize_combination(value: str):
    normalized = re.sub(r"[‐‑–—−ー→、,]", "-", value)
    normalized = re.sub(r"\s+", "", normalized)
    normalized = re.sub(r"[^0-9-]", "", normalized)
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized if re.fullmatch(r"\d{1,2}(?:-\d{1,2}){0,2}", normalized) else None


def parse_table_payouts(page: str):
    payouts = []; current_type = None
    for cells in collector.parsed_rows(page):
        explicit = next((normalize_bet_type(cell) for cell in cells if normalize_bet_type(cell)), None)
        if explicit: current_type = explicit
        if not current_type: continue
        for amount_index, cell in enumerate(cells):
            m = re.search(r"([0-9,]+)\s*円", cell)
            if not m: continue
            combination = None
            for i in range(amount_index - 1, -1, -1):
                combination = normalize_combination(cells[i])
                if combination or normalize_bet_type(cells[i]): break
            if not combination: continue
            rest = " ".join(cells[amount_index + 1 :]); pop = re.search(r"(\d+)\s*番人気", rest)
            payouts.append({"betType":current_type,"combination":combination,"payoutYen":int(m.group(1).replace(",","")),"popularity":int(pop.group(1)) if pop else None})
    return payouts


def parse_text_payouts(page: str):
    text = collector.page_text(page).replace("３", "3")
    marker = re.search(r"払戻金\s+単勝\s+", text)
    if not marker: return []
    segment = text[marker.start():]
    endings = [p for p in (segment.find("・ 勝馬投票"), segment.find("勝馬の紹介")) if p > 0]
    if endings: segment = segment[:min(endings)]
    type_matches = list(re.finditer(r"(?:^|\s)(単勝|複勝|枠連|ワイド|馬連|馬単|3連複|3連単)(?=\s)", segment))
    payouts = []
    for idx, tm in enumerate(type_matches):
        bet_type = tm.group(1); start = tm.end(); end = type_matches[idx+1].start() if idx+1 < len(type_matches) else len(segment); chunk = segment[start:end]
        arity = 1 if bet_type in ("単勝","複勝") else 2 if bet_type in ("枠連","ワイド","馬連","馬単") else 3
        combo_pattern = r"\d{1,2}" + (r"(?:-\d{1,2})" + "{" + str(arity-1) + "}")
        for m in re.finditer(rf"({combo_pattern})\s+([0-9,]+)\s*円(?:\s+(\d+)\s*番人気)?", chunk):
            combo = normalize_combination(m.group(1))
            if combo: payouts.append({"betType":bet_type,"combination":combo,"payoutYen":int(m.group(2).replace(",","")),"popularity":int(m.group(3)) if m.group(3) else None})
    return payouts


def parse_payouts(page: str):
    payouts = parse_table_payouts(page) or parse_text_payouts(page); unique = {}
    for row in payouts: unique[(row["betType"],row["combination"])] = row
    return list(unique.values())


def selected_ids():
    payload = json.loads(SELECTION.read_text(encoding="utf-8"))
    if payload.get("resultDataUsedForTargetDay") is not False: raise RuntimeError("TARGET_RESULTS_USED_FOR_SELECTION")
    ids = [str(x["raceId"]) for x in payload.get("selected", [])]
    if len(ids) != 15: raise RuntimeError(f"SELECTED_COUNT_INVALID:{len(ids)}")
    return ids


def upsert_race_payouts(race_id: str, payouts: list[dict]):
    values = ",".join("(?,?,?,?,?,CURRENT_TIMESTAMP)" for _ in payouts); params = []
    for p in payouts: params.extend([race_id,p["betType"],p["combination"],p["payoutYen"],p["popularity"]])
    collector.d1_query(f"""INSERT INTO rt_payouts(race_id,bet_type,combination,payout_yen,popularity,updated_at) VALUES {values} ON CONFLICT(race_id,bet_type,combination) DO UPDATE SET payout_yen=excluded.payout_yen,popularity=excluded.popularity,updated_at=CURRENT_TIMESTAMP""", params)


def main():
    ids = selected_ids(); placeholders = ",".join("?" for _ in ids)
    races = collector.d1_query(f"SELECT race_id AS raceId,race_date AS raceDate,venue,race_no AS raceNo,result_url AS resultUrl,status FROM rt_races WHERE race_id IN ({placeholders}) ORDER BY venue,race_no", ids)
    finished = [r for r in races if str(r.get("status")) == "finished"]; synced=[];errors=[];inserted=0
    for race in finished:
        race_id=str(race["raceId"]);result_url=str(race.get("resultUrl") or "")
        if not result_url: errors.append(f"{race_id}:RESULT_URL_MISSING");continue
        try:
            page=collector.fetch_url(result_url);identity=collector.parse_page_identity(page);expected=(str(race["raceDate"]),str(race["venue"]),int(race["raceNo"]))
            if identity!=expected: raise RuntimeError(f"RESULT_IDENTITY_MISMATCH:{identity}:{expected}")
            payouts=parse_payouts(page)
            if not payouts: raise RuntimeError("NO_PAYOUT_ROWS")
            types={p["betType"] for p in payouts}
            if not {"単勝","馬連","馬単","ワイド","3連複","3連単"}.issubset(types): raise RuntimeError(f"PAYOUT_TYPES_INCOMPLETE:{sorted(types)}")
            upsert_race_payouts(race_id,payouts);inserted+=len(payouts);synced.append({"raceId":race_id,"payoutRows":len(payouts),"betTypes":sorted(types)})
        except Exception as error: errors.append(f"{race_id}:{type(error).__name__}:{error}")
    audit=collector.d1_query(f"SELECT r.race_id AS raceId,COUNT(p.race_id) AS payoutRows FROM rt_races r LEFT JOIN rt_payouts p ON p.race_id=r.race_id WHERE r.race_id IN ({placeholders}) AND r.status='finished' GROUP BY r.race_id ORDER BY r.race_id",ids)
    missing=[x["raceId"] for x in audit if int(x.get("payoutRows") or 0)==0]
    payload={"selectedRaceCount":len(ids),"finishedRaceCount":len(finished),"resultDataUsedOnlyForSettlement":True,"synced":synced,"upsertedPayoutRows":inserted,"audit":audit,"missingPayoutRaces":missing,"errors":errors}
    REPORT.parent.mkdir(parents=True,exist_ok=True);REPORT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");print(json.dumps(payload,ensure_ascii=False,indent=2),flush=True)
    if errors or missing: raise RuntimeError(f"AUG9_PAYOUT_SYNC_INCOMPLETE:{len(errors)}:{len(missing)}")

if __name__=="__main__": main()
