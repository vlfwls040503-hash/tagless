"""
Part B-2: results/raw/ 아래 per-agent + zone CSV들을 summary.csv로 재집계.

batch_runner가 이미 생성한 summary.csv를 검증/재생성하는 용도.
"""
import csv
import pathlib
import sys
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scenarios"))
from scenario_matrix import iter_scenarios  # noqa: E402

RAW_DIR = ROOT / "results" / "raw"
SUMMARY_CSV = ROOT / "results" / "summary.csv"

ZONE_AREAS = {"z1": 50 * 25, "z2": 4 * 7, "z3": 2 * 3, "z4": 2 * 3}


def aggregate_one(sid, p, config, seed):
    agent_csv = RAW_DIR / f"agents_{sid}.csv"
    zone_csv = RAW_DIR / f"zones_{sid}.csv"
    if not agent_csv.exists() or not zone_csv.exists():
        return None

    travel_times = []
    spawned = 0
    passed = 0
    with open(agent_csv, "r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            spawned += 1
            if row.get("serviced") == "1":
                passed += 1
            tt = row.get("travel_time", "")
            if tt and tt != "None":
                travel_times.append(float(tt))
    travel_times = np.array(travel_times) if travel_times else np.array([])

    zone_series = {"z1": [], "z2": [], "z3": [], "z4": []}
    with open(zone_csv, "r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            for i, zk in enumerate(["z1", "z2", "z3", "z4"], 1):
                c = int(row[f"zone{i}_count"])
                zone_series[zk].append(c / ZONE_AREAS[zk])

    def _stat(series, fn, default=0.0):
        return float(fn(series)) if series else default

    return {
        "scenario_id": sid,
        "p": p, "config": config, "seed": seed,
        "spawned": spawned, "passed": passed,
        "avg_travel_time": float(travel_times.mean()) if len(travel_times) else 0.0,
        "p95_travel_time": float(np.percentile(travel_times, 95)) if len(travel_times) else 0.0,
        "n_completed": len(travel_times),
        "zone1_avg_density": _stat(zone_series["z1"], np.mean),
        "zone1_max_density": _stat(zone_series["z1"], np.max),
        "zone2_avg_density": _stat(zone_series["z2"], np.mean),
        "zone2_max_density": _stat(zone_series["z2"], np.max),
        "zone3_avg_density": _stat(zone_series["z3"], np.mean),
        "zone3_max_density": _stat(zone_series["z3"], np.max),
        "zone4_avg_density": _stat(zone_series["z4"], np.mean),
        "zone4_max_density": _stat(zone_series["z4"], np.max),
    }


def main():
    rows = []
    missing = []
    for sid, params in iter_scenarios():
        row = aggregate_one(sid, params["_p"], params["_config"], params["_seed"])
        if row is None:
            missing.append(sid)
            continue
        rows.append(row)
    if rows:
        with open(SUMMARY_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"Saved: {SUMMARY_CSV} ({len(rows)} 행)")
    if missing:
        print(f"누락 시나리오 {len(missing)}개: {missing[:5]}...")


if __name__ == "__main__":
    main()
