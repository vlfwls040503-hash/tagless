"""
Part C-1: 그래프 4종 생성.

입력: results/summary.csv
출력: results/figures/{travel_time_vs_p, gate_density_vs_p, escalator_density_vs_p, pareto_plot}.png
"""
import pathlib
import matplotlib.pyplot as plt
import matplotlib
matplotlib.use("Agg")
import numpy as np
import pandas as pd

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

ROOT = pathlib.Path(__file__).resolve().parent.parent
SUMMARY_CSV = ROOT / "results" / "summary.csv"
FIG_DIR = ROOT / "results" / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

CONFIG_COLORS = {1: "#1976D2", 2: "#388E3C", 3: "#F57C00", 4: "#C2185B"}
CONFIG_LABELS = {
    1: "배합 1 (태그리스 1, 태그 6)",
    2: "배합 2 (태그리스 2, 태그 5)",
    3: "배합 3 (태그리스 3, 태그 4)",
    4: "배합 4 (태그리스 4, 태그 3)",
}


def _line_with_ci(ax, df, ycol, title, ylabel, save_path):
    for cfg in sorted(df["config"].unique()):
        sub = df[df["config"] == cfg].groupby("p")[ycol].agg(["mean", "std", "count"])
        p_vals = sub.index.values
        mean = sub["mean"].values
        se = sub["std"].values / np.sqrt(sub["count"].values)
        ci = 1.96 * se
        color = CONFIG_COLORS[cfg]
        ax.plot(p_vals, mean, "o-", color=color, label=CONFIG_LABELS[cfg],
                linewidth=2, markersize=6)
        ax.fill_between(p_vals, mean - ci, mean + ci, color=color, alpha=0.15)
    ax.set_xlabel("태그리스 이용률 p", fontsize=11)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.legend(loc="best", fontsize=9)
    ax.grid(True, alpha=0.3, linestyle=":")


def plot_travel_time(df):
    fig, ax = plt.subplots(figsize=(9, 6))
    _line_with_ci(ax, df, "avg_travel_time",
                  "평균 통행시간 vs 태그리스 이용률",
                  "평균 통행시간 (초)", None)
    plt.tight_layout()
    out = FIG_DIR / "travel_time_vs_p.png"
    fig.savefig(out, dpi=100, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def plot_gate_density(df):
    fig, ax = plt.subplots(figsize=(9, 6))
    _line_with_ci(ax, df, "zone2_avg_density",
                  "게이트 앞 평균 밀도 vs 태그리스 이용률",
                  "Zone 2 평균 밀도 (명/㎡)", None)
    plt.tight_layout()
    out = FIG_DIR / "gate_density_vs_p.png"
    fig.savefig(out, dpi=100, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def plot_escalator_density(df):
    # zone3_max + zone4_max 합
    df = df.copy()
    df["esc_max_density_sum"] = df["zone3_max_density"] + df["zone4_max_density"]
    fig, ax = plt.subplots(figsize=(9, 6))
    _line_with_ci(ax, df, "esc_max_density_sum",
                  "에스컬레이터 앞 최대 밀도 합 vs 태그리스 이용률",
                  "Z3+Z4 최대 밀도 합 (명/㎡)", None)
    plt.tight_layout()
    out = FIG_DIR / "escalator_density_vs_p.png"
    fig.savefig(out, dpi=100, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def plot_pareto(df):
    """x=avg_travel_time, y=전체 zone max density 평균. 각 점 = (p, config) 조합 1개."""
    df = df.copy()
    df["zone_max_mean"] = df[[f"zone{i}_max_density" for i in range(1, 5)]].mean(axis=1)
    # (p, config) 평균으로 집계
    agg = df.groupby(["p", "config"]).agg(
        x=("avg_travel_time", "mean"),
        y=("zone_max_mean", "mean"),
    ).reset_index()

    fig, ax = plt.subplots(figsize=(9, 7))
    for cfg in sorted(agg["config"].unique()):
        sub = agg[agg["config"] == cfg]
        ax.scatter(sub["x"], sub["y"], s=60, color=CONFIG_COLORS[cfg],
                   label=CONFIG_LABELS[cfg], edgecolors="white", linewidths=0.5,
                   zorder=3)
        for _, row in sub.iterrows():
            ax.annotate(f"p={row['p']:.1f}",
                        (row["x"], row["y"]),
                        xytext=(5, 5), textcoords="offset points",
                        fontsize=8, color=CONFIG_COLORS[cfg])

    # 파레토 프론티어 (두 지표 모두 최소화)
    pts = agg[["x", "y"]].values
    is_pareto = np.ones(len(pts), dtype=bool)
    for i in range(len(pts)):
        for j in range(len(pts)):
            if i == j:
                continue
            if pts[j, 0] <= pts[i, 0] and pts[j, 1] <= pts[i, 1] and (
                pts[j, 0] < pts[i, 0] or pts[j, 1] < pts[i, 1]
            ):
                is_pareto[i] = False
                break
    front = agg[is_pareto].sort_values("x")
    ax.plot(front["x"], front["y"], "--", color="red", linewidth=1.5,
            alpha=0.7, label="파레토 프론티어", zorder=2)
    ax.scatter(front["x"], front["y"], s=160, facecolors="none",
               edgecolors="red", linewidths=2, zorder=4)

    ax.set_xlabel("평균 통행시간 (초)", fontsize=11)
    ax.set_ylabel("Zone 최대 밀도 평균 (명/㎡)", fontsize=11)
    ax.set_title("통행비용-밀도 파레토 플롯", fontsize=13, fontweight="bold")
    ax.legend(loc="best", fontsize=9)
    ax.grid(True, alpha=0.3, linestyle=":")
    plt.tight_layout()
    out = FIG_DIR / "pareto_plot.png"
    fig.savefig(out, dpi=100, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def main():
    df = pd.read_csv(SUMMARY_CSV)
    print(f"Loaded {len(df)} rows from {SUMMARY_CSV}")
    plot_travel_time(df)
    plot_gate_density(df)
    plot_escalator_density(df)
    plot_pareto(df)


if __name__ == "__main__":
    main()
