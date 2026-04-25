"""
병목 전이 분석 — 게이트 처리율 vs 에스컬 앞 (W2) 보행밀도 상관관계.

가설 (RQ1):
  게이트 처리율 ↑ → W2 (에스컬 앞 대기) 밀도 ↑
  = 병목이 게이트에서 에스컬 앞으로 전이

데이터:
  - 시나리오 150개 (5p × 6cfg × 5seed) — pass_rate≥0.9 만 사용
  - x: throughput_active (passed / 활성구간) — 게이트 시스템 처리율
  - x_alt: per_gate_active (= /7) — 게이트당 처리율
  - y: W2_avg_density (시간평균), W2_peak_density (peak)

분석:
  1. 전체 상관 (Spearman, Kendall — 비모수)
  2. p 통제 부분상관 (각 p 내 상관)
  3. 배합 평균 상관 (n=p×cfg)
  4. 산점도 + p별 색
"""
from __future__ import annotations
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from scipy import stats

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parent.parent
DENS = ROOT / "results" / "molit" / "density_union.csv"
OUT_TXT = ROOT / "results" / "molit" / "bottleneck_transfer_report.txt"
OUT_FIG = ROOT / "figures" / "molit" / "bottleneck_transfer.png"

PASS_RATE_MIN = 0.9
COLORS = {0.1:"#1F77B4", 0.3:"#2CA02C", 0.5:"#FF7F0E", 0.7:"#D62728", 0.8:"#9467BD"}


def main():
    df = pd.read_csv(DENS)
    df_all = df.copy()
    df = df[df["pass_rate"] >= PASS_RATE_MIN].copy()

    out = []
    add = out.append

    add("=" * 90)
    add("병목 전이 분석 — 게이트 처리율 vs 에스컬 앞 (W2) 보행밀도")
    add(f"  데이터: {len(df_all)} 시나리오 중 pass_rate>={PASS_RATE_MIN} → {len(df)} 사용")
    add("=" * 90)

    add(f"\nx축 (게이트 처리율):")
    add(f"  throughput_active = passed / (last_pass - first_pass)  — 시스템 활성 처리율")
    add(f"  per_gate_active   = throughput_active / 7              — 게이트당 처리율")
    add(f"y축 (에스컬 앞 밀도):")
    add(f"  W2_avg = 시간평균 ped/m² (zone 20.0 m²)")
    add(f"  W2_pk  = 시점별 max")

    # ── 1. 전체 상관 ──
    add("\n" + "-" * 90)
    add("[1] 전체 시나리오 상관 (n={})".format(len(df)))
    add("-" * 90)
    add(f"{'쌍':>30s} | {'Spearman ρ':>14s} | {'Kendall τ':>14s} | {'Pearson r':>14s}")
    add("-" * 90)
    pairs = [
        ("throughput_active", "W2_avg_density", "tp_active vs W2_avg"),
        ("throughput_active", "W2_peak_density", "tp_active vs W2_peak"),
        ("per_gate_active",   "W2_avg_density", "per_gate vs W2_avg"),
        ("per_gate_active",   "W2_peak_density", "per_gate vs W2_peak"),
        ("avg_gate_wait",     "W2_avg_density", "gate_wait vs W2_avg (역상관 기대)"),
    ]
    for xc, yc, label in pairs:
        x = df[xc].dropna(); y = df.loc[x.index, yc]
        sr, sp = stats.spearmanr(x, y)
        kr, kp = stats.kendalltau(x, y)
        pr, pp = stats.pearsonr(x, y)
        add(f"{label:>30s} | {sr:>+8.3f} (p={sp:.2g}) | "
            f"{kr:>+8.3f} (p={kp:.2g}) | {pr:>+8.3f} (p={pp:.2g})")

    # ── 2. p 통제 부분상관 ──
    add("\n" + "-" * 90)
    add("[2] p 통제 시 부분상관 (각 p 내, 비모수 Spearman)")
    add("-" * 90)
    add(f"{'p':>4} | {'n':>3} | {'tp vs W2_avg':>22s} | {'tp vs W2_pk':>22s} | "
        f"{'tp 평균':>10s} | {'W2_avg 평균':>10s}")
    add("-" * 90)
    for p_val in sorted(df["p"].unique()):
        sub = df[df["p"] == p_val]
        if len(sub) < 4:
            add(f"{p_val:>4.1f} | {len(sub):>3d} | (표본 부족)")
            continue
        sa, pa = stats.spearmanr(sub["throughput_active"], sub["W2_avg_density"])
        sk, pk = stats.spearmanr(sub["throughput_active"], sub["W2_peak_density"])
        add(f"{p_val:>4.1f} | {len(sub):>3d} | "
            f"ρ={sa:>+5.3f} (p={pa:.2g}) | ρ={sk:>+5.3f} (p={pk:.2g}) | "
            f"{sub['throughput_active'].mean():>7.2f}p/s | "
            f"{sub['W2_avg_density'].mean():>8.3f}")

    # ── 3. 배합 평균 ──
    add("\n" + "-" * 90)
    add("[3] 배합 평균 상관 (p × cfg, 각 점은 5 seed 평균)")
    add("-" * 90)
    agg = df.groupby(["p", "config"]).agg(
        tp=("throughput_active", "mean"),
        per_g=("per_gate_active", "mean"),
        W2_avg=("W2_avg_density", "mean"),
        W2_pk=("W2_peak_density", "mean"),
    ).reset_index()
    add(f"배합 수 (n) = {len(agg)}")
    for xc, yc, label in [("tp", "W2_avg", "tp vs W2_avg"),
                           ("tp", "W2_pk",  "tp vs W2_pk"),
                           ("per_g", "W2_avg", "per_gate vs W2_avg")]:
        sr, sp = stats.spearmanr(agg[xc], agg[yc])
        pr, pp = stats.pearsonr(agg[xc], agg[yc])
        add(f"  {label:>20s}: Spearman ρ={sr:+.3f} (p={sp:.2g}), "
            f"Pearson r={pr:+.3f} (p={pp:.2g})")

    # ── 4. 시각화 ──
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), dpi=100)

    # (a) 전체 산점도
    ax = axes[0]
    for p_val in sorted(df["p"].unique()):
        sub = df[df["p"] == p_val]
        ax.scatter(sub["throughput_active"], sub["W2_avg_density"],
                   c=COLORS[p_val], s=35, alpha=0.7, edgecolors="white",
                   label=f"p={p_val}")
    sr, sp = stats.spearmanr(df["throughput_active"], df["W2_avg_density"])
    ax.set_title(f"(a) 전체 (n={len(df)}): Spearman ρ={sr:+.3f}, p={sp:.2g}")
    ax.set_xlabel("게이트 처리율 (ped/s, 활성구간 기준)")
    ax.set_ylabel("W2 평균밀도 (ped/m²)")
    ax.axhline(0.7, color="orange", ls=":", alpha=0.6, label="LOS C 상한")
    ax.axhline(1.0, color="red",    ls=":", alpha=0.6, label="LOS D 상한")
    ax.legend(fontsize=8); ax.grid(alpha=0.3)

    # (b) 배합 평균 산점도 (cfg label)
    ax = axes[1]
    for p_val in sorted(agg["p"].unique()):
        sub = agg[agg["p"] == p_val]
        ax.scatter(sub["tp"], sub["W2_avg"], c=COLORS[p_val], s=120,
                   edgecolors="black", label=f"p={p_val}")
        for _, r in sub.iterrows():
            ax.annotate(f"cfg{int(r['config'])}", (r["tp"], r["W2_avg"]),
                        fontsize=7, ha="left", va="bottom")
    sr2, sp2 = stats.spearmanr(agg["tp"], agg["W2_avg"])
    ax.set_title(f"(b) 배합 평균 (n={len(agg)}): Spearman ρ={sr2:+.3f}, p={sp2:.2g}")
    ax.set_xlabel("게이트 처리율 (ped/s)")
    ax.set_ylabel("W2 평균밀도 (ped/m²)")
    ax.axhline(0.7, color="orange", ls=":", alpha=0.6)
    ax.axhline(1.0, color="red",    ls=":", alpha=0.6)
    ax.legend(fontsize=8); ax.grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(OUT_FIG, dpi=100, bbox_inches="tight")
    plt.close()

    text = "\n".join(out)
    print(text)
    OUT_TXT.write_text(text, encoding="utf-8")
    print(f"\n저장: {OUT_TXT}")
    print(f"그림: {OUT_FIG}")


if __name__ == "__main__":
    main()
