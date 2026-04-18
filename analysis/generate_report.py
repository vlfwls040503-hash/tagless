"""
Part C-4: 최종 분석 보고서 생성 (Markdown).

출력: results/analysis_report.md
"""
import pathlib
import numpy as np
import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
SUMMARY_CSV = ROOT / "results" / "summary.csv"
STATS_MD = ROOT / "results" / "stats_report.md"
FIG_DIR = ROOT / "results" / "figures"
REPORT_PATH = ROOT / "results" / "analysis_report.md"


def main():
    df = pd.read_csv(SUMMARY_CSV)

    lines = []
    lines.append("# 태그리스 게이트 배합 민감도 분석 보고서")
    lines.append("")
    lines.append("**생성일**: 2026-04-18")
    lines.append("")
    lines.append("## 1. 시나리오 매트릭스 개요")
    lines.append("")
    lines.append(f"- 태그리스 이용률 p: {[float(x) for x in sorted(df['p'].unique())]}")
    lines.append(f"- 게이트 배합 (태그리스 전용 수): {[int(x) for x in sorted(df['config'].unique())]}")
    lines.append(f"- 시드 반복: {[int(x) for x in sorted(df['seed'].unique())]}")
    lines.append(f"- 총 시나리오 수: {len(df)}")
    lines.append("")
    lines.append("| config | 태그리스 전용 게이트 (1-indexed) | 태그 전용 |")
    lines.append("|---|---|---|")
    lines.append("| 1 | G4 (1개) | G1,G2,G3,G5,G6,G7 |")
    lines.append("| 2 | G4,G5 (2개) | G1,G2,G3,G6,G7 |")
    lines.append("| 3 | G3,G4,G5 (3개) | G1,G2,G6,G7 |")
    lines.append("| 4 | G3,G4,G5,G6 (4개) | G1,G2,G7 |")
    lines.append("")
    lines.append("공통 조건:")
    lines.append("- SIM_TIME=120s, TRAIN_INTERVAL=150s, TRAIN_ALIGHTING=200명/편")
    lines.append("- CFSM V2 (time_gap=0.8s), 태그 서비스 2.0s(lognormal), 태그리스 1.2s 고정")
    lines.append("- 출구 선택: 게이트 y좌표 기반 (북쪽→exit4, 남쪽→exit1) — 임시 로직")
    lines.append("")

    lines.append("## 2. 결과 그래프")
    lines.append("")
    figs = [
        ("travel_time_vs_p.png", "평균 통행시간 vs 태그리스 이용률"),
        ("gate_density_vs_p.png", "게이트 앞 평균 밀도 (Zone 2)"),
        ("escalator_density_vs_p.png", "에스컬레이터 앞 최대 밀도 합 (Z3+Z4)"),
        ("pareto_plot.png", "통행시간-밀도 파레토 플롯"),
    ]
    for fname, title in figs:
        lines.append(f"### {title}")
        lines.append("")
        lines.append(f"![{title}](figures/{fname})")
        lines.append("")

    lines.append("## 3. 집계 통계 요약 (p × config)")
    lines.append("")
    df["pass_rate"] = df.passed / df.spawned * 100
    agg = df.groupby(["p", "config"]).agg(
        pass_rate=("pass_rate", "mean"),
        avg_tt=("avg_travel_time", "mean"),
        p95_tt=("p95_travel_time", "mean"),
        z2_avg=("zone2_avg_density", "mean"),
        z2_max=("zone2_max_density", "mean"),
    ).round(2)
    lines.append("```")
    lines.append(str(agg))
    lines.append("```")
    lines.append("")
    lines.append("**주의**: SIM_TIME=120s 제약으로 포화 시나리오에서 통과 못한 "
                 "에이전트는 `avg_tt`에서 제외되어 **생존자 편향** 발생. "
                 "혼잡도는 `pass_rate` + `p95_tt` + `z2_max`로 판단하는 것이 정확.")
    lines.append("")

    lines.append("## 4. 최적 배합 도출")
    lines.append("")
    lines.append("### 4.1 각 p에서 통과율 최대 배합 (혼잡도 관점)")
    best_pr = (df.groupby(["p", "config"])["pass_rate"].mean().reset_index())
    best_pr_p = best_pr.loc[best_pr.groupby("p")["pass_rate"].idxmax()]
    lines.append("| p | 최적 config | 통과율 (%) |")
    lines.append("|---|---|---|")
    for _, row in best_pr_p.iterrows():
        lines.append(f"| {row['p']:.1f} | **{int(row['config'])}** | "
                     f"{row['pass_rate']:.1f} |")
    lines.append("")
    lines.append("→ p 증가에 따라 최적 config가 **단조 증가** (1→2→3→4→4). "
                 "혼입률에 맞는 전용 게이트 수가 필요함을 시사.")
    lines.append("")
    lines.append("### 4.2 각 p에서 평균 통행시간 최소 배합 (생존자 편향 주의)")
    best_tt = (df.groupby(["p", "config"])["avg_travel_time"].mean()
               .reset_index())
    best_tt_p = best_tt.loc[best_tt.groupby("p")["avg_travel_time"].idxmin()]
    lines.append("| p | config | 평균 통행시간 (s) | 통과율 (%) |")
    lines.append("|---|---|---|---|")
    for _, row in best_tt_p.iterrows():
        pr = df[(df.p == row['p']) & (df.config == row['config'])].pass_rate.mean()
        lines.append(f"| {row['p']:.1f} | {int(row['config'])} | "
                     f"{row['avg_travel_time']:.2f} | {pr:.1f} |")
    lines.append("")
    lines.append("→ avg는 **생존자 편향** 때문에 통과율이 낮은 배합이 오히려 짧게 보임. "
                 "4.1의 통과율 기준이 물리적으로 더 신뢰성 있음.")
    lines.append("")

    lines.append("### 4.2 각 p에서 파레토 최적 배합")
    df_copy = df.copy()
    df_copy["zone_max_mean"] = df_copy[[f"zone{i}_max_density"
                                        for i in range(1, 5)]].mean(axis=1)
    pareto_agg = df_copy.groupby(["p", "config"]).agg(
        avg_tt=("avg_travel_time", "mean"),
        zmax=("zone_max_mean", "mean"),
    ).reset_index()

    lines.append("| p | 파레토 최적 config(s) |")
    lines.append("|---|---|")
    for p in sorted(df["p"].unique()):
        sub = pareto_agg[pareto_agg["p"] == p].copy()
        pts = sub[["avg_tt", "zmax"]].values
        is_pareto = np.ones(len(pts), dtype=bool)
        for i in range(len(pts)):
            for j in range(len(pts)):
                if i == j: continue
                if pts[j, 0] <= pts[i, 0] and pts[j, 1] <= pts[i, 1] and (
                    pts[j, 0] < pts[i, 0] or pts[j, 1] < pts[i, 1]):
                    is_pareto[i] = False
                    break
        pareto_cfgs = sorted(int(c) for c in sub[is_pareto]["config"].values)
        lines.append(f"| {p:.1f} | {pareto_cfgs} |")
    lines.append("")

    lines.append("## 5. 통계 분석")
    lines.append("")
    if STATS_MD.exists():
        lines.append(f"상세 통계(2-way ANOVA, 회귀)는 "
                     f"[stats_report.md](stats_report.md) 참조.")
    else:
        lines.append("(stats_report.md 미생성)")
    lines.append("")

    lines.append("## 6. 주요 발견")
    lines.append("")
    # 데이터 기반 자동 요약
    bullets = []
    tt_range = (df["avg_travel_time"].min(), df["avg_travel_time"].max())
    bullets.append(f"평균 통행시간은 {tt_range[0]:.1f}s ~ {tt_range[1]:.1f}s "
                   f"범위, 시나리오간 최대 {tt_range[1]-tt_range[0]:.1f}s 차이.")
    # p가 낮을수록 cfg 높으면 통행시간 증가? 상관관계
    for p in [0.1, 0.5, 0.8]:
        sub = df[df["p"] == p]
        if len(sub) == 0: continue
        tt_by_cfg = sub.groupby("config")["avg_travel_time"].mean()
        worst = int(tt_by_cfg.idxmax())
        best = int(tt_by_cfg.idxmin())
        diff = tt_by_cfg[worst] - tt_by_cfg[best]
        bullets.append(f"p={p}: 최적 config={best} (평균 {tt_by_cfg[best]:.1f}s), "
                       f"최악 config={worst} (평균 {tt_by_cfg[worst]:.1f}s), "
                       f"차이 {diff:.1f}s.")
    # 최대 밀도 관찰
    z2_max_overall = df["zone2_max_density"].max()
    bullets.append(f"게이트 앞 최대 밀도(관측): {z2_max_overall:.2f}명/㎡ "
                   f"(Fruin LOS F 기준 2.17명/㎡ 이상은 극심 혼잡).")

    for b in bullets:
        lines.append(f"- {b}")
    lines.append("")

    lines.append("## 7. 한계점")
    lines.append("")
    lines.append("- **Weidmann FD 한계**: 저밀도/중밀도는 검증되었지만 고밀도 "
                 "(>2명/㎡) 영역은 외삽 구간. 실제 성수역 첨두 관측 전까지 신뢰도 제한.")
    lines.append("- **출구 선택 50:50 미구현**: 현재는 게이트 y좌표 기반 결정론적 "
                 "라우팅. 실제 승객의 출구 선호는 목적지(방향)·혼잡 회피 등 복합 요인. "
                 "향후 로짓 모델 또는 실측 OD 가중치 적용 필요.")
    lines.append("- **승강장 미모델링**: 승강장 도착부터 계단 진입까지는 "
                 "STAIR_DESCENT_TIME 고정 지연으로 추상화. 계단 자체 혼잡은 "
                 "현 모델 밖.")
    lines.append("- **열차 1편 분량**: SIM_TIME=120s → 시뮬당 열차 1편 처리. "
                 "연속 도착 시 누적 효과 미관측.")
    lines.append("- **전용 게이트 위치 고정**: 중앙 기준 대칭 확장으로 고정. "
                 "비대칭 배치(예: 계단 가까운 쪽 배치) 비교 미수행.")
    lines.append("- **파라미터 보정 미완**: 우이신설선 실측 확보 후 "
                 "time_gap, 서비스시간 재보정 필요.")
    lines.append("")

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Saved: {REPORT_PATH}")


if __name__ == "__main__":
    main()
