"""
게이트 활성 처리구간 기준 throughput 재계산.

기존: passed / SIM_TIME (600s) — 빈 시간대 포함되어 과소평가
수정: passed / (last_service - first_service) — 첫 통과부터 마지막 통과까지

agent CSV의 service_start_time 컬럼 사용.
"""
from __future__ import annotations
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "results_cfsm_latest" / "raw"
SUMMARY = ROOT / "results_cfsm_latest" / "summary.csv"
OUT = ROOT / "results" / "molit"
OUT.mkdir(parents=True, exist_ok=True)

SIM_TIME = 600.0

# 시나리오 메타 (summary.csv) 로드
df = pd.read_csv(SUMMARY)
df["pass_rate"] = df["passed"] / df["spawned"]

# 게이트 수 (cfg = 전용 게이트 수, 총 7개 중)
N_GATES = 7

# 각 시나리오별 active throughput 계산
records = []
for _, row in df.iterrows():
    sid = row["scenario_id"]
    agent_csv = RAW / f"agents_{sid}.csv"
    if not agent_csv.exists():
        continue
    a = pd.read_csv(agent_csv)
    # service_start_time 이 채워진 (= 실제 게이트 통과한) agent 만
    served = a.dropna(subset=["service_start_time"])
    if len(served) < 2:
        continue
    t_first = served["service_start_time"].min()
    t_last = served["service_start_time"].max()
    active = max(t_last - t_first, 1e-6)
    passed = len(served)
    tp_active = passed / active
    tp_full = passed / SIM_TIME
    records.append({
        "scenario_id": sid,
        "p": row["p"],
        "config": row["config"],
        "seed": row["seed"],
        "passed": passed,
        "t_first_pass": t_first,
        "t_last_pass": t_last,
        "active_period": active,
        "throughput_active": tp_active,
        "throughput_full": tp_full,
        "per_gate_active": tp_active / N_GATES,
        "z_bmax": max(row["zone3b_avg_density"], row["zone4b_avg_density"]),
    })

tp_df = pd.DataFrame(records)
tp_df.to_csv(OUT / "throughput_active.csv", index=False, encoding="utf-8-sig")

# cfg 1~4 (신뢰 데이터) 만 집계
keep = tp_df[tp_df["config"].isin([1, 2, 3, 4])]
agg = keep.groupby(["p", "config"]).agg(
    tp_active=("throughput_active", "mean"),
    tp_full=("throughput_full", "mean"),
    per_gate_active=("per_gate_active", "mean"),
    active_period=("active_period", "mean"),
    z_bmax=("z_bmax", "mean"),
).reset_index()

print("=" * 100)
print("게이트 처리율: 활성구간 기준 vs 전체 600s 기준 (총 7게이트)")
print("=" * 100)
print(f"{'p':>4} | {'cfg':>3} | {'active구간':>10s} | {'tp_active':>11s} | "
      f"{'tp_full':>10s} | {'per_gate':>10s} | {'Z_bmax':>7s}")
print("-" * 100)
for p_val in sorted(agg["p"].unique()):
    sub = agg[agg["p"] == p_val]
    for _, r in sub.iterrows():
        print(f"{r['p']:>4.1f} | {int(r['config']):>3d} | "
              f"{r['active_period']:>8.0f}s | "
              f"{r['tp_active']:>8.2f}p/s | "
              f"{r['tp_full']:>7.2f}p/s | "
              f"{r['per_gate_active']:>7.3f}p/s | "
              f"{r['z_bmax']:>5.2f}")
    print()

print("\n해석:")
print("- tp_active: 첫 게이트 통과부터 마지막 통과까지의 처리율 (시스템 실효)")
print("- tp_full:   600s 전체 평균 (빈 시간대 포함)")
print("- per_gate:  tp_active / 7게이트")
print(f"\n저장: {OUT / 'throughput_active.csv'}")
