"""
agents_*.csv + zones_*.csv 에서 summary.csv 전체 재구성.

spawned = agent CSV row count
passed  = service_start_time 채워진 row count
나머지 컬럼은 batch_runner_parallel 의 aggregate_summary_row 와 동일 로직.
"""
from __future__ import annotations
from pathlib import Path
import sys
import csv
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scenarios"))
sys.path.insert(0, str(ROOT / "simulation"))
from scenario_matrix import iter_scenarios
from batch_runner_parallel import aggregate_summary_row

RAW = ROOT / "results_cfsm_latest" / "raw"
OUT = ROOT / "results_cfsm_latest" / "summary.csv"


def main():
    rows = []
    for sid, params in iter_scenarios():
        agent_csv = RAW / f"agents_{sid}.csv"
        if not agent_csv.exists():
            continue
        a = pd.read_csv(agent_csv)
        spawned = len(a)
        passed = a["service_start_time"].notna().sum()
        # batch_runner 의 aggregate_summary_row 사용
        row = aggregate_summary_row(sid, params,
                                    {"gate_counts": [int(passed)]},
                                    int(spawned), int(passed), RAW)
        rows.append(row)
    if not rows:
        print("재구성할 데이터 없음")
        return
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    df = pd.DataFrame(rows)
    print(f"재구성 완료: {len(rows)} 행 -> {OUT}")
    print("\ncfg별 요약:")
    print(df.groupby("config").agg(
        n=("scenario_id", "count"),
        spawned_mean=("spawned", "mean"),
        passed_mean=("passed", "mean"),
        pass_rate_mean=("passed", lambda s: (s / df.loc[s.index, "spawned"].clip(lower=1)).mean()),
    ))


if __name__ == "__main__":
    main()
