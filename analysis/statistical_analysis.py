"""
Part C-2,3: 통계 분석 (2-way ANOVA + 회귀) + 최적 배합 도출.

출력: results/stats_report.md (텍스트 결과)
"""
import pathlib
import numpy as np
import pandas as pd

try:
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    from statsmodels.stats.anova import anova_lm
    HAS_SM = True
except ImportError:
    HAS_SM = False

ROOT = pathlib.Path(__file__).resolve().parent.parent
SUMMARY_CSV = ROOT / "results" / "summary.csv"
REPORT_PATH = ROOT / "results" / "stats_report.md"


def two_way_anova(df, dvar):
    """2-way ANOVA: dvar ~ C(config) + p + C(config):p (교호작용)."""
    if not HAS_SM:
        return f"(statsmodels 미설치 — ANOVA 스킵)"
    model = smf.ols(f"{dvar} ~ C(config) * p", data=df).fit()
    aov = anova_lm(model, typ=2)
    # 효과 크기 (η² = SS_effect / SS_total)
    ss_total = aov["sum_sq"].sum()
    aov["eta_sq"] = aov["sum_sq"] / ss_total
    return aov, model


def regression_analysis(df, dvar):
    """회귀: dvar = β0 + β1·p + β2·config + β3·(p×config)"""
    if not HAS_SM:
        return "(statsmodels 미설치)"
    model = smf.ols(f"{dvar} ~ p + config + p:config", data=df).fit()
    return model


def best_config_by_p(df, metric):
    """각 p 수준에서 metric 최소화 배합."""
    agg = df.groupby(["p", "config"])[metric].mean().reset_index()
    best = agg.loc[agg.groupby("p")[metric].idxmin()]
    return best[["p", "config", metric]]


def pareto_optimal_configs(df):
    """(p, config) 조합 중 파레토 최적(통행시간+밀도 둘 다 최소화)."""
    df = df.copy()
    df["zone_max_mean"] = df[[f"zone{i}_max_density" for i in range(1, 5)]].mean(axis=1)
    agg = df.groupby(["p", "config"]).agg(
        avg_tt=("avg_travel_time", "mean"),
        zmax=("zone_max_mean", "mean"),
    ).reset_index()

    pareto_by_p = {}
    for p in sorted(agg["p"].unique()):
        sub = agg[agg["p"] == p].copy()
        pts = sub[["avg_tt", "zmax"]].values
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
        pareto_by_p[p] = sub[is_pareto]
    return pareto_by_p


def main():
    df = pd.read_csv(SUMMARY_CSV)
    lines = [f"# 통계 분석 리포트", ""]
    lines.append(f"시나리오 수: {len(df)} "
                 f"(p={[float(x) for x in sorted(df['p'].unique())]}, "
                 f"config={[int(x) for x in sorted(df['config'].unique())]}, "
                 f"seeds={[int(x) for x in sorted(df['seed'].unique())]})")
    lines.append("")

    targets = [
        ("avg_travel_time", "평균 통행시간 (초)"),
        ("zone2_avg_density", "게이트 앞 평균 밀도 (명/㎡)"),
    ]
    # 에스컬 밀도: 파생 컬럼
    df["esc_max_density_sum"] = df["zone3_max_density"] + df["zone4_max_density"]
    targets.append(("esc_max_density_sum", "에스컬 앞 최대 밀도 합 (명/㎡)"))

    for dvar, label in targets:
        lines.append(f"\n## {label} (`{dvar}`)")
        lines.append("")
        # 2-way ANOVA
        if HAS_SM:
            aov, model = two_way_anova(df, dvar)
            lines.append("### 2-way ANOVA")
            lines.append("")
            lines.append("```")
            lines.append(str(aov.round(4)))
            lines.append("```")
            lines.append("")
            # 회귀
            reg = regression_analysis(df, dvar)
            lines.append("### 회귀분석")
            lines.append(f"R² = {reg.rsquared:.4f}, 관측치 = {int(reg.nobs)}")
            lines.append("")
            lines.append("```")
            coef_df = pd.DataFrame({
                "coef": reg.params,
                "std_err": reg.bse,
                "p_value": reg.pvalues,
            }).round(4)
            lines.append(str(coef_df))
            lines.append("```")
            lines.append("")
        # 각 p 최적
        lines.append("### p별 최적 배합")
        lines.append("")
        best = best_config_by_p(df, dvar)
        lines.append("```")
        lines.append(str(best.to_string(index=False)))
        lines.append("```")
        lines.append("")

    # 파레토 최적
    lines.append("\n## 파레토 최적 배합 (p별)")
    lines.append("")
    pareto_by_p = pareto_optimal_configs(df)
    for p, sub in pareto_by_p.items():
        lines.append(f"### p = {p}")
        lines.append("```")
        lines.append(str(sub.round(3).to_string(index=False)))
        lines.append("```")
        lines.append("")

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Saved: {REPORT_PATH}")
    print("\n--- 미리보기 ---")
    print("\n".join(lines[:40]))


if __name__ == "__main__":
    main()
