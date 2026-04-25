"""
최종 권고 — W2 peak ≤ 1.0 (LOS E 보수적) 기준 채택.

이 보고서는 peak 제약 하에서:
  1. p별 권고 cfg
  2. 가변 vs 고정 운영 비교
  3. 정책 시사점
을 정리.
"""
from __future__ import annotations
from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from analysis.molit_los import WALKWAY_LOS, grade

DENS = ROOT / "results" / "molit" / "density_union.csv"
OUT = ROOT / "results" / "molit" / "FINAL_RECOMMENDATION_PEAK.txt"

PASS_RATE_MIN = 0.9
LOS_E_MAX = 1.0
TIME_WEIGHT = {0.1: 0.30, 0.3: 0.30, 0.5: 0.20, 0.7: 0.15, 0.8: 0.05}


def los(d):
    return grade(d, WALKWAY_LOS)


def main():
    df = pd.read_csv(DENS)
    df = df[df["pass_rate"] >= PASS_RATE_MIN].copy()
    df = df[df["config"].isin([1, 2, 3, 4, 5, 6])].copy()

    agg = df.groupby(["p", "config"]).agg(
        travel=("avg_travel_time", "mean"),
        gate_wait=("avg_gate_wait", "mean"),
        W2_avg=("W2_avg_density", "mean"),
        W2_pk=("W2_peak_density", "mean"),
    ).reset_index()

    out = []
    add = out.append

    add("=" * 100)
    add("최종 권고 — 태그리스 게이트 운영 cfg")
    add("  채택 기준: W2 peak ≤ 1.0 (국토부 LOS E 첨두 한계, 보수적)")
    add("=" * 100)
    add("")
    add("선택 근거:")
    add("  - W2 평균 (active-only) 기준은 거의 모든 cfg 가 통과 → 변별력 약함")
    add("  - W2 peak 기준은 한 순간이라도 LOS F (>1.0) 진입 금지 → 안전 우선")
    add("  - 학술/정책 표준 = 첨두 1분 평균이지만, 시뮬 측정 단위(0.5초)에서는 peak 가")
    add("    더 보수적 안전 지표")

    p_list = sorted(agg["p"].unique())

    # ── 표 1: p별 권고 cfg ──
    add("\n" + "=" * 100)
    add("[표 1] p별 권고 cfg — peak 제약 하에서 통행시간 최저")
    add("=" * 100)
    add("")
    add("설명: 각 p 에서 W2 peak ≤ 1.0 통과한 cfg 후보들 중 평균 통행시간이 가장 짧은 cfg.")
    add("       괄호 안은 그 외 통과 cfg (참고용 — 통행시간이 더 길거나 같음).")
    add("")
    add(f"  {'p':>4} | {'권고 cfg':>9} | {'통행시간':>9} | {'게이트 대기':>11} | "
        f"{'W2 peak':>8} {'LOS':>4} | {'기타 통과 cfg':>20}")
    add(f"  {'-'*4} | {'-'*9} | {'-'*9} | {'-'*11} | {'-'*8} {'-'*4} | {'-'*20}")
    recommended = {}
    for p_val in p_list:
        feasible = agg[(agg["p"] == p_val) & (agg["W2_pk"] <= LOS_E_MAX)]
        if len(feasible) == 0:
            add(f"  {p_val:>4.1f} | {'없음':>9s} | {'-':>9s} | {'-':>11s} | "
                f"{'-':>8s} {'-':>4} | (운영 불가)")
            recommended[p_val] = None
            continue
        best = feasible.loc[feasible["travel"].idxmin()]
        others = feasible[feasible["config"] != best["config"]]
        other_str = ", ".join(f"cfg{int(c)}" for c in others["config"]) if len(others) else "-"
        add(f"  {p_val:>4.1f} | {'cfg'+str(int(best['config'])):>9s} | "
            f"{best['travel']:>7.1f}s | {best['gate_wait']:>9.1f}s | "
            f"{best['W2_pk']:>7.3f}  {los(best['W2_pk']):>3} | {other_str:>20s}")
        recommended[p_val] = (int(best["config"]), best["travel"],
                              best["gate_wait"], best["W2_pk"])

    # ── 표 2: 고정 운영 가능 cfg + 가중평균 ──
    add("\n" + "=" * 100)
    add("[표 2] 고정 운영 — 모든 p 에서 LOS E 통과하는 단일 cfg")
    add("=" * 100)
    add("")
    add("설명: 시간대 무관 한 cfg 만 계속 운영하는 방식.")
    add("       모든 p (10~80%) 에서 W2 peak ≤ 1.0 인 cfg 만 후보.")
    add("")

    fixed_candidates = []
    for cfg in sorted(agg["config"].unique()):
        sub = agg[agg["config"] == cfg].set_index("p")
        if all(p in sub.index and sub.loc[p, "W2_pk"] <= LOS_E_MAX for p in p_list):
            fixed_candidates.append(int(cfg))

    if not fixed_candidates:
        add("  → 어떤 cfg 도 모든 p 에서 LOS E 통과 못함 = 가변 운영 필수")
    else:
        for cfg in fixed_candidates:
            sub = agg[agg["config"] == cfg].set_index("p")
            add(f"  cfg{int(cfg)}: 모든 p 에서 통과")
            for p_val in p_list:
                r = sub.loc[p_val]
                add(f"     p={p_val}: travel {r['travel']:.1f}s, "
                    f"gate {r['gate_wait']:.1f}s, W2pk {r['W2_pk']:.3f} ({los(r['W2_pk'])})")

    # ── 표 3: 가변 vs 고정 통행시간 ──
    add("\n" + "=" * 100)
    add("[표 3] 가변 운영 vs 고정 운영 — 가중평균 통행시간 비교")
    add("=" * 100)
    add("")
    add(f"가중치 (시간대 비율): " +
        ", ".join(f"p={p}={int(w*100)}%" for p, w in TIME_WEIGHT.items()))
    add("")

    if fixed_candidates and all(recommended[p] is not None for p in p_list):
        var_tw = sum(recommended[p][1] * TIME_WEIGHT.get(p, 0) for p in p_list)
        add(f"  가변 운영 (p별 권고 cfg): 가중평균 통행시간 = {var_tw:.1f}s")
        add(f"  세부:")
        for p_val in p_list:
            cfg, tr, gw, w2pk = recommended[p_val]
            add(f"     p={p_val}: cfg{cfg}, travel {tr:.1f}s × 가중치 {TIME_WEIGHT[p_val]} "
                f"= {tr*TIME_WEIGHT[p_val]:.2f}s")

        add("")
        for cfg in fixed_candidates:
            sub = agg[agg["config"] == cfg].set_index("p")
            tw = sum(sub.loc[p, "travel"] * TIME_WEIGHT.get(p, 0)
                     for p in p_list if p in sub.index)
            add(f"  고정 cfg{cfg}: 가중평균 통행시간 = {tw:.1f}s")
            add(f"  세부:")
            for p_val in p_list:
                if p_val not in sub.index: continue
                tr = sub.loc[p_val, "travel"]
                add(f"     p={p_val}: travel {tr:.1f}s × 가중치 {TIME_WEIGHT[p_val]} "
                    f"= {tr*TIME_WEIGHT[p_val]:.2f}s")

        best_fixed = fixed_candidates[0]
        sub = agg[agg["config"] == best_fixed].set_index("p")
        fixed_tw = sum(sub.loc[p, "travel"] * TIME_WEIGHT.get(p, 0)
                       for p in p_list if p in sub.index)
        diff = fixed_tw - var_tw
        pct = 100 * diff / fixed_tw
        add(f"\n  → 가변이 고정 cfg{best_fixed} 대비 {diff:+.1f}s ({pct:+.1f}%) 절감")
    elif not fixed_candidates:
        add(f"  고정 운영 불가 → 가변만 가능")
        if all(recommended[p] is not None for p in p_list):
            var_tw = sum(recommended[p][1] * TIME_WEIGHT.get(p, 0) for p in p_list)
            add(f"  가변 운영 가중평균 통행시간 = {var_tw:.1f}s")

    # ── 표 4: 정책 시사 ──
    add("\n" + "=" * 100)
    add("[표 4] 정책 시사")
    add("=" * 100)
    add("")
    add("[1] 가변 운영의 효익:")
    if fixed_candidates and all(recommended[p] is not None for p in p_list):
        add(f"     - 통행시간 {pct:+.1f}% 절감 (고정 cfg{best_fixed} 대비)")
        add(f"     - 동시에 모든 시간대에서 국토부 LOS E 통과 보장")

    add("")
    add("[2] 시간대별 권고 cfg:")
    for p_val in p_list:
        if recommended[p_val] is None:
            add(f"     p={p_val}: 운영 불가 (시설 부족)")
        else:
            cfg, tr, gw, w2pk = recommended[p_val]
            add(f"     p={p_val}: cfg{cfg} (전용 게이트 {cfg}개)")

    add("")
    add("[3] 고정 운영 시 대안:")
    if fixed_candidates:
        for cfg in fixed_candidates:
            add(f"     - cfg{cfg} 단일 운영 가능 (LOS 보장, 통행시간 절감 포기)")
    else:
        add(f"     - 고정 운영 불가능. 가변 운영 필수.")

    text = "\n".join(out)
    print(text)
    OUT.write_text(text, encoding="utf-8")
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()
