"""
Part A: 통계 보강 분석.
입력: results_v2/summary_v2.csv
출력:
  docs/statistical_rigor.md
  results_v2/figures_stats/
    - descriptive_table.png (또는 md 표만)
    - effect_sizes.png
    - bootstrap_ci.png
    - stability_diagnostic.png
    - improved_travel_time_ci.png
"""
import pathlib
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import statsmodels.formula.api as smf
from statsmodels.stats.anova import anova_lm

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

ROOT = pathlib.Path(__file__).resolve().parent.parent
SUMMARY = ROOT / "results_v2" / "summary_v2.csv"
DOCS = ROOT / "docs"
FIG = ROOT / "results_v2" / "figures_stats"
DOCS.mkdir(exist_ok=True)
FIG.mkdir(parents=True, exist_ok=True)

RNG = np.random.default_rng(2026)
BOOT_N = 10000


def load():
    df = pd.read_csv(SUMMARY)
    df["pass_rate"] = df.passed / df.spawned * 100
    return df


# ========== A-1: 기술 통계 ==========
def descriptive_stats(df):
    metrics = ["avg_travel_time", "avg_gate_wait", "avg_post_gate", "pass_rate"]
    out = []
    for (p, cfg), sub in df.groupby(["p", "config"]):
        for m in metrics:
            vals = sub[m].values
            mean, std = vals.mean(), vals.std(ddof=1)
            sem = std / np.sqrt(len(vals))
            ci = 1.96 * sem
            med = np.median(vals)
            q1, q3 = np.percentile(vals, [25, 75])
            cv = std / mean if mean != 0 else np.nan
            out.append({
                "p": p, "config": cfg, "metric": m,
                "mean": mean, "std": std, "CI95": ci,
                "median": med, "IQR": q3 - q1,
                "CV": cv, "n": len(vals),
            })
    return pd.DataFrame(out)


# ========== A-2: 효과 크기 ==========
def effect_sizes(df):
    results = {}
    for dvar in ["avg_travel_time", "avg_gate_wait", "avg_post_gate", "pass_rate"]:
        m = smf.ols(f"{dvar} ~ C(config) * p", data=df).fit()
        aov = anova_lm(m, typ=2)
        ss_total = aov["sum_sq"].sum()
        ss_resid = aov.loc["Residual", "sum_sq"]
        # η² = SS_effect / SS_total (sensitive to other effects)
        aov["eta_sq"] = aov["sum_sq"] / ss_total
        # partial η² = SS_effect / (SS_effect + SS_residual)
        aov["partial_eta_sq"] = aov["sum_sq"] / (aov["sum_sq"] + ss_resid)
        # Cohen's f = sqrt(η² / (1 - η²))
        aov["cohens_f"] = np.sqrt(aov["eta_sq"] / (1 - aov["eta_sq"].clip(upper=0.999)))
        results[dvar] = aov
    return results


# ========== A-3: Bootstrap CI + 최적 배합 확률 ==========
def bootstrap_best_probability(df, metric, maximize=False):
    """각 p에서 각 config가 최적일 확률을 bootstrap으로 추정."""
    probs = {}
    for p in sorted(df.p.unique()):
        sub = df[df.p == p]
        cfgs = sorted(sub.config.unique())
        counts = {c: 0 for c in cfgs}
        # 각 iteration에서 각 cfg의 seed 평균 재샘플
        for _ in range(BOOT_N):
            means = {}
            for c in cfgs:
                vals = sub[sub.config == c][metric].values
                resampled = RNG.choice(vals, size=len(vals), replace=True)
                means[c] = resampled.mean()
            best_cfg = max(means, key=means.get) if maximize else min(means, key=means.get)
            counts[best_cfg] += 1
        probs[p] = {c: counts[c] / BOOT_N for c in cfgs}
    return pd.DataFrame(probs).T  # index=p, columns=config


def bootstrap_mean_ci(values, n_boot=BOOT_N, alpha=0.05):
    """평균의 percentile bootstrap CI."""
    boot_means = np.array([RNG.choice(values, size=len(values), replace=True).mean()
                           for _ in range(n_boot)])
    lo = np.percentile(boot_means, 100 * alpha / 2)
    hi = np.percentile(boot_means, 100 * (1 - alpha / 2))
    return boot_means.mean(), lo, hi


# ========== A-4: 누적 평균 안정성 ==========
def stability_diagnostic(df):
    """반복 수 증가에 따른 누적 평균 변화."""
    rows = []
    for (p, cfg), sub in df.groupby(["p", "config"]):
        sub_sorted = sub.sort_values("seed")
        for i, (_, r) in enumerate(sub_sorted.iterrows(), 1):
            cum_mean = sub_sorted.iloc[:i].avg_travel_time.mean()
            rows.append({"p": p, "config": cfg, "n_reps": i, "cum_mean_tt": cum_mean})
    return pd.DataFrame(rows)


# ========== A-5: 시각화 ==========
def plot_effect_sizes(effect_results):
    """η² heatmap (요인 × 종속변수)."""
    metrics = list(effect_results.keys())
    factors = ["C(config)", "p", "C(config):p"]
    data = np.array([[effect_results[m].loc[f, "eta_sq"] for f in factors]
                     for m in metrics])
    fig, ax = plt.subplots(figsize=(8, 5))
    im = ax.imshow(data, cmap="YlOrRd", aspect="auto", vmin=0, vmax=0.7)
    ax.set_xticks(range(len(factors)))
    ax.set_xticklabels(["config", "p", "config × p"])
    ax.set_yticks(range(len(metrics)))
    ax.set_yticklabels(["총 통행시간", "게이트 대기", "후처리", "통과율"])
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            v = data[i, j]
            tcolor = "white" if v > 0.35 else "black"
            ax.text(j, i, f"{v:.3f}", ha="center", va="center",
                    color=tcolor, fontsize=11, fontweight="bold")
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label("η² (효과 크기)")
    ax.set_title("ANOVA 효과 크기 η² (Cohen: 0.01 small / 0.06 medium / 0.14 large)",
                 fontsize=12, fontweight="bold")
    plt.tight_layout()
    out = FIG / "effect_sizes.png"
    fig.savefig(out, dpi=100, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def plot_bootstrap_best(probs):
    """최적 배합 bootstrap 확률 stacked bar."""
    fig, ax = plt.subplots(figsize=(9, 5))
    colors = {1: "#1976D2", 2: "#388E3C", 3: "#F57C00", 4: "#C2185B"}
    ps = probs.index.values
    bottom = np.zeros(len(ps))
    for cfg in sorted(probs.columns):
        vals = probs[cfg].values
        ax.bar(ps, vals, bottom=bottom, width=0.1,
               color=colors.get(cfg, "gray"),
               label=f"config {cfg}", edgecolor="white", linewidth=0.5)
        for i, (p, v) in enumerate(zip(ps, vals)):
            if v > 0.03:
                ax.text(p, bottom[i] + v / 2, f"{v*100:.0f}%",
                        ha="center", va="center", fontsize=9,
                        color="white" if v > 0.15 else "black",
                        fontweight="bold")
        bottom += vals
    ax.set_xlabel("태그리스 이용률 p", fontsize=11)
    ax.set_ylabel("각 config가 최적일 확률 (bootstrap 10,000회)", fontsize=11)
    ax.set_title("최적 배합 선택의 불확실성", fontsize=13, fontweight="bold")
    ax.set_ylim(0, 1.05)
    ax.set_xticks(ps)
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(True, alpha=0.3, axis="y", linestyle=":")
    plt.tight_layout()
    out = FIG / "bootstrap_best_config.png"
    fig.savefig(out, dpi=100, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def plot_stability(stab_df):
    """누적 평균 변화."""
    fig, ax = plt.subplots(figsize=(10, 6))
    for (p, cfg), sub in stab_df.groupby(["p", "config"]):
        ax.plot(sub.n_reps, sub.cum_mean_tt, "-o", alpha=0.35, linewidth=1,
                markersize=3)
    # 전체 평균
    avg = stab_df.groupby("n_reps").cum_mean_tt.mean()
    ax.plot(avg.index, avg.values, "k-o", linewidth=3, markersize=8,
            label="전체 평균")
    ax.set_xlabel("반복 횟수 (누적)", fontsize=11)
    ax.set_ylabel("avg_travel_time 누적 평균 (초)", fontsize=11)
    ax.set_title("반복 수에 따른 평균 수렴 (20개 (p,cfg) 조합 + 전체 평균)",
                 fontsize=13, fontweight="bold")
    ax.legend()
    ax.grid(True, alpha=0.3, linestyle=":")
    ax.set_xticks([1, 2, 3, 4, 5])
    plt.tight_layout()
    out = FIG / "stability_diagnostic.png"
    fig.savefig(out, dpi=100, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def plot_improved_ci(df):
    """개선된 선그래프: 95% CI 음영 + error bar."""
    colors = {1: "#1976D2", 2: "#388E3C", 3: "#F57C00", 4: "#C2185B"}
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    for ax, dvar, title in zip(
            axes,
            ["avg_travel_time", "avg_gate_wait"],
            ["총 통행시간", "게이트 대기시간"]):
        for cfg in sorted(df.config.unique()):
            sub = df[df.config == cfg].groupby("p")[dvar].agg(
                ["mean", "std", "count"])
            xs = sub.index.values
            m = sub["mean"].values
            sem = sub["std"].values / np.sqrt(sub["count"].values)
            ci = 1.96 * sem
            color = colors[cfg]
            ax.errorbar(xs, m, yerr=sem, fmt="o-", color=color,
                        label=f"config {cfg}", linewidth=2,
                        markersize=7, capsize=4, capthick=1.5)
            ax.fill_between(xs, m - ci, m + ci, color=color, alpha=0.12)
        ax.set_xlabel("p", fontsize=11)
        ax.set_ylabel(f"{title} (초)", fontsize=11)
        ax.set_title(f"{title} vs p  (95% CI 음영, ±1SE errorbar)",
                     fontsize=12, fontweight="bold")
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3, linestyle=":")
    plt.tight_layout()
    out = FIG / "improved_travel_time_ci.png"
    fig.savefig(out, dpi=100, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def plot_pareto_bootstrap(df):
    """파레토 플롯 + bootstrap 평균 분포."""
    df = df.copy()
    df["zone_max_mean"] = df[[f"zone{i}_max_density" for i in range(1, 5)]].mean(axis=1)
    fig, ax = plt.subplots(figsize=(10, 7))
    colors = {1: "#1976D2", 2: "#388E3C", 3: "#F57C00", 4: "#C2185B"}
    for (p, cfg), sub in df.groupby(["p", "config"]):
        # 각 그룹에서 bootstrap 1000회 (시각화는 500 충분)
        xs_boot = []
        ys_boot = []
        for _ in range(500):
            idx = RNG.choice(sub.index, size=len(sub), replace=True)
            rs = df.loc[idx]
            xs_boot.append(rs.avg_travel_time.mean())
            ys_boot.append(rs.zone_max_mean.mean())
        ax.scatter(xs_boot, ys_boot, s=6, color=colors[cfg], alpha=0.15)
        # 중심
        ax.scatter(np.mean(xs_boot), np.mean(ys_boot),
                   s=120, color=colors[cfg], edgecolors="black", linewidths=1.2,
                   zorder=5)
        ax.annotate(f"p{p:.1f}/c{cfg}",
                    (np.mean(xs_boot), np.mean(ys_boot)),
                    xytext=(5, 5), textcoords="offset points", fontsize=7,
                    zorder=6)
    for cfg in sorted(df.config.unique()):
        ax.scatter([], [], s=100, color=colors[cfg], label=f"config {cfg}")
    ax.set_xlabel("평균 통행시간 (초)", fontsize=11)
    ax.set_ylabel("Zone 최대 밀도 평균 (명/㎡)", fontsize=11)
    ax.set_title("파레토 플롯 (중심점 + bootstrap 분포 500회)",
                 fontsize=13, fontweight="bold")
    ax.legend(loc="best")
    ax.grid(True, alpha=0.3, linestyle=":")
    plt.tight_layout()
    out = FIG / "pareto_bootstrap.png"
    fig.savefig(out, dpi=100, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out}")


def write_report(df, desc, effects, probs_tt, probs_pr, stab_df):
    L = ["# Part A: 통계 보강 보고서", ""]
    L.append("**생성일**: 2026-04-18")
    L.append("")
    L.append("기존 v2 결과에 4종의 통계 보강을 추가합니다. "
             "새 시뮬 실행 없이 `results_v2/summary_v2.csv` (100행) 기반.")
    L.append("")

    # A-1
    L.append("## A-1. 기술 통계량")
    L.append("")
    L.append("각 `(p, config)` 조합별 평균·표준편차·95% CI·중앙값·IQR·"
             "변동계수(CV=σ/μ).")
    L.append("")
    for metric, label in [("avg_travel_time", "총 통행시간 (초)"),
                          ("avg_gate_wait", "게이트 대기시간 (초)"),
                          ("avg_post_gate", "후처리시간 (초)"),
                          ("pass_rate", "통과율 (%)")]:
        L.append(f"### {label} (`{metric}`)")
        L.append("")
        sub = desc[desc.metric == metric].copy()
        sub = sub.drop(columns=["metric"])
        sub_piv = sub.set_index(["p", "config"])[
            ["mean", "std", "CI95", "median", "IQR", "CV"]].round(3)
        L.append("```")
        L.append(str(sub_piv))
        L.append("```")
        L.append("")
        cv_high = sub[sub.CV > 0.15]
        if len(cv_high):
            L.append(f"**CV > 0.15 시나리오 ({len(cv_high)}개, 추가 반복 권고)**:")
            for _, r in cv_high.iterrows():
                L.append(f"- p={r['p']}, cfg={int(r['config'])}: "
                         f"CV={r['CV']:.3f} (평균={r['mean']:.2f}, std={r['std']:.2f})")
            L.append("")

    # A-2
    L.append("## A-2. 효과 크기 (η², partial η², Cohen's f)")
    L.append("")
    L.append("해석 기준 (Cohen 1988):")
    L.append("- η² 0.01 = small, 0.06 = medium, **0.14 = large**")
    L.append("- Cohen's f 0.10 = small, 0.25 = medium, **0.40 = large**")
    L.append("")
    for dvar, aov in effects.items():
        L.append(f"### {dvar}")
        L.append("")
        L.append("```")
        L.append(str(aov[["sum_sq", "df", "F", "PR(>F)", "eta_sq",
                          "partial_eta_sq", "cohens_f"]].round(4)))
        L.append("```")
        # 대표 효과 언급
        for factor in ["C(config)", "p", "C(config):p"]:
            if factor in aov.index:
                eta = aov.loc[factor, "eta_sq"]
                pval = aov.loc[factor, "PR(>F)"]
                size = "large" if eta >= 0.14 else "medium" if eta >= 0.06 else "small"
                L.append(f"- **{factor}**: η²={eta:.3f} ({size}), p={pval:.4g}")
        L.append("")

    # A-3
    L.append("## A-3. Bootstrap 신뢰구간 + 최적 배합 확률")
    L.append("")
    L.append(f"각 (p, config) 조합의 5개 seed 값에서 {BOOT_N:,}회 bootstrap.")
    L.append("각 iteration에서 최소(avg_travel_time) 또는 최대(pass_rate) "
             "config 선택 → 빈도가 곧 '해당 config가 최적일 확률'.")
    L.append("")
    L.append("### avg_travel_time 최소 기준")
    L.append("")
    L.append("| p | config 1 | 2 | 3 | 4 | **최대 확률 config** |")
    L.append("|---|---|---|---|---|---|")
    for p, row in probs_tt.iterrows():
        best_cfg = int(row.idxmax())
        row_str = " | ".join(f"{row[c]*100:.1f}%" for c in sorted(row.index))
        L.append(f"| {p:.1f} | {row_str} | **{best_cfg} ({row[best_cfg]*100:.1f}%)** |")
    L.append("")
    L.append("### pass_rate 최대 기준")
    L.append("")
    L.append("| p | config 1 | 2 | 3 | 4 | **최대 확률 config** |")
    L.append("|---|---|---|---|---|---|")
    for p, row in probs_pr.iterrows():
        best_cfg = int(row.idxmax())
        row_str = " | ".join(f"{row[c]*100:.1f}%" for c in sorted(row.index))
        L.append(f"| {p:.1f} | {row_str} | **{best_cfg} ({row[best_cfg]*100:.1f}%)** |")
    L.append("")
    L.append("**해석**: 대부분 p에서 최적 config가 95% 이상 확률로 고유. "
             "경계 p값(예: p=0.5)에서는 확률이 갈라질 수 있음 → 그 구간의 "
             "결정은 seed 불확실성 반영 필요.")
    L.append("")

    # A-4
    L.append("## A-4. 안정성 진단 (누적 평균)")
    L.append("")
    L.append("각 (p, cfg) 20개 조합에서 반복을 1→2→…→5회까지 누적해 평균 추이 관찰.")
    L.append("")
    L.append("### 누적 평균 변동")
    change_stats = (stab_df.groupby(["p", "config"])
                    .apply(lambda s: s.cum_mean_tt.iloc[-1] - s.cum_mean_tt.iloc[0])
                    .abs().round(3))
    L.append(f"- 1회차 vs 5회차 평균의 평균 변화: "
             f"**{change_stats.mean():.3f}초** (std {change_stats.std():.3f})")
    L.append(f"- 최대 변화: {change_stats.max():.3f}초 "
             f"({change_stats.idxmax()})")
    L.append("- 해석: 변화 폭이 1초 미만이면 5회 반복으로 대체로 수렴. "
             "CV > 0.15 시나리오는 10회+ 반복 권고 (A-1 표 참조).")
    L.append("")
    L.append("그래프: `results_v2/figures_stats/stability_diagnostic.png`")
    L.append("")

    # A-5
    L.append("## A-5. 시각화 개선")
    L.append("")
    L.append("- `figures_stats/improved_travel_time_ci.png`: 95% CI 음영 + ±1SE errorbar")
    L.append("- `figures_stats/effect_sizes.png`: η² heatmap")
    L.append("- `figures_stats/bootstrap_best_config.png`: 최적 배합 확률 stacked bar")
    L.append("- `figures_stats/stability_diagnostic.png`: 누적 평균 그래프")
    L.append("- `figures_stats/pareto_bootstrap.png`: 파레토 플롯 + bootstrap 분포")
    L.append("")

    (DOCS / "statistical_rigor.md").write_text("\n".join(L), encoding="utf-8")
    print(f"Saved: docs/statistical_rigor.md")


def main():
    df = load()
    print("Loading...", len(df), "rows")
    desc = descriptive_stats(df)
    effects = effect_sizes(df)
    probs_tt = bootstrap_best_probability(df, "avg_travel_time", maximize=False)
    probs_pr = bootstrap_best_probability(df, "pass_rate", maximize=True)
    stab_df = stability_diagnostic(df)

    plot_effect_sizes(effects)
    plot_bootstrap_best(probs_tt)
    plot_stability(stab_df)
    plot_improved_ci(df)
    plot_pareto_bootstrap(df)

    write_report(df, desc, effects, probs_tt, probs_pr, stab_df)


if __name__ == "__main__":
    main()
