"""
합집합 zone bbox 로 모든 시나리오 밀도 재집계.

입력:
  - docs/union_zones.json (derive_union_zones.py 산출)
  - results_cfsm_latest/raw/trajectory_*.csv (cfg 1~4)
  - results_cfsm_latest/raw/agents_*.csv (active throughput 용)

출력:
  - results/molit/density_union.csv (시나리오별 zone 밀도 + active throughput)
  - results/molit/density_union_summary.txt (p×cfg 평균표)
"""
from __future__ import annotations
from pathlib import Path
import json
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "results_cfsm_latest" / "raw"
SUMMARY = ROOT / "results_cfsm_latest" / "summary.csv"
ZONES_JSON = ROOT / "docs" / "union_zones.json"
OUT_CSV = ROOT / "results" / "molit" / "density_union.csv"
OUT_TXT = ROOT / "results" / "molit" / "density_union_summary.txt"
OUT_CSV.parent.mkdir(parents=True, exist_ok=True)

PASS_RATE_MIN = 0.9
N_GATES = 7
SAMPLE_DT = 0.5  # trajectory sampling


def main():
    zones = json.load(open(ZONES_JSON, encoding="utf-8"))["zones"]
    print("로드된 zone:")
    for z in zones:
        print(f"  {z['id']} {z['name']}: x={z['x_range']} y={z['y_range']} "
              f"area={z['area_m2']:.1f}m^2")

    summary = pd.read_csv(SUMMARY)
    summary["pass_rate"] = summary["passed"] / summary["spawned"].clip(lower=1)

    rows = []
    for _, sr in summary.iterrows():
        sid = sr["scenario_id"]
        cfg = int(sr["config"])
        if cfg not in (1, 2, 3, 4, 5, 6):
            continue
        agent_csv = RAW / f"agents_{sid}.csv"
        traj_csv = RAW / f"trajectory_{sid}.csv"
        if not (agent_csv.exists() and traj_csv.exists()):
            continue

        # active throughput (agent CSV)
        a = pd.read_csv(agent_csv)
        served = a.dropna(subset=["service_start_time"])
        if len(served) >= 2:
            t_first = served["service_start_time"].min()
            t_last = served["service_start_time"].max()
            active = max(t_last - t_first, 1e-6)
            tp_active = len(served) / active
        else:
            t_first = t_last = active = tp_active = np.nan

        # zone 밀도 (trajectory)
        td = pd.read_csv(traj_csv)
        # warm-up 제외
        td = td[td["time"] >= 90.0]
        # 시점별 zone count → 시간평균 → /면적
        # 평균은 '존에 1명 이상 있던 시점' 만 분모로 (빈 구간 제외)
        zone_dens = {}
        zone_peak = {}
        times = sorted(td["time"].unique())
        for z in zones:
            x0, x1 = z["x_range"]; y0, y1 = z["y_range"]
            in_zone = ((td["x"] >= x0) & (td["x"] <= x1) &
                       (td["y"] >= y0) & (td["y"] <= y1))
            sub = td[in_zone]
            counts_per_t = sub.groupby("time").size().reindex(times, fill_value=0)
            active = counts_per_t[counts_per_t > 0]
            avg = (active.mean() / z["area_m2"]) if len(active) else 0.0
            peak = counts_per_t.max() / z["area_m2"]
            zone_dens[z["id"]] = avg
            zone_peak[z["id"]] = peak

        row = {
            "scenario_id": sid,
            "p": sr["p"], "config": cfg, "seed": sr["seed"],
            "spawned": sr["spawned"], "passed": sr["passed"],
            "pass_rate": sr["pass_rate"],
            "avg_travel_time": sr["avg_travel_time"],
            "avg_gate_wait": sr["avg_gate_wait"],
            "t_first_pass": t_first, "t_last_pass": t_last,
            "active_period": active,
            "throughput_active": tp_active,
            "per_gate_active": tp_active / N_GATES if not np.isnan(tp_active) else np.nan,
        }
        for z in zones:
            row[f"{z['id']}_avg_density"] = zone_dens[z["id"]]
            row[f"{z['id']}_peak_density"] = zone_peak[z["id"]]
        rows.append(row)

    df = pd.DataFrame(rows)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"\n저장: {OUT_CSV} ({len(df)} rows)")

    # p × cfg 평균
    valid = df[df["pass_rate"] >= PASS_RATE_MIN].copy()
    excluded = df[df["pass_rate"] < PASS_RATE_MIN][["scenario_id", "pass_rate"]]

    agg_cols = ["throughput_active", "per_gate_active", "active_period",
                "avg_travel_time", "avg_gate_wait"]
    for z in zones:
        agg_cols.append(f"{z['id']}_avg_density")
        agg_cols.append(f"{z['id']}_peak_density")
    agg = valid.groupby(["p", "config"])[agg_cols].mean().reset_index()

    lines = []
    lines.append("=" * 110)
    lines.append("합집합 zone 기반 밀도 재집계 (pass_rate >= 0.9 만 사용)")
    lines.append("=" * 110)
    lines.append(f"\n사용 zone:")
    for z in zones:
        lines.append(f"  {z['id']} {z['name']}: x={z['x_range']} y={z['y_range']} "
                     f"area={z['area_m2']:.1f}m^2")
    lines.append(f"\n제외 시나리오 ({len(excluded)}): pass_rate < 0.9")
    for _, r in excluded.iterrows():
        lines.append(f"  {r['scenario_id']}: pass_rate={r['pass_rate']:.2f}")

    lines.append("\n" + "=" * 110)
    header = f"{'p':>4} {'cfg':>3} {'tp_act':>7} {'per_g':>6} {'active':>6} {'travel':>7} {'gate_w':>7}"
    for z in zones:
        header += f" {z['id']+'_avg':>8} {z['id']+'_pk':>7}"
    lines.append(header)
    lines.append("-" * len(header))
    for _, r in agg.iterrows():
        line = (f"{r['p']:>4.1f} {int(r['config']):>3d} "
                f"{r['throughput_active']:>5.2f}p/s "
                f"{r['per_gate_active']:>4.2f}p/s "
                f"{r['active_period']:>5.0f}s "
                f"{r['avg_travel_time']:>6.1f}s "
                f"{r['avg_gate_wait']:>6.1f}s")
        for z in zones:
            line += f" {r[z['id']+'_avg_density']:>7.3f} {r[z['id']+'_peak_density']:>6.3f}"
        lines.append(line)
    text = "\n".join(lines)
    print("\n" + text)
    OUT_TXT.write_text(text, encoding="utf-8")
    print(f"\n저장: {OUT_TXT}")


if __name__ == "__main__":
    main()
