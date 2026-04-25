"""
최종 보고 v2 — 표 + 표 설명 명시, 국토부 첨두 기준 LOS E (≤1.0) 적용.

용어:
  p              : 태그리스 이용 비율 (0.1=10%, 0.3=30%, ...)
  cfg            : 전용 게이트 수 (1, 2, 3, 4)
  W2 평균밀도     : 에스컬 앞 대기공간 (20.0 m²) 의 시간평균 밀도 (인/m²)
  W2 peak 밀도   : 같은 공간의 시점별 최대 밀도
  통행시간       : 게이트 진입~출구 도달 평균 시간
  게이트 대기시간 : 게이트 큐 진입~서비스 시작 평균 시간
  LOS            : 국토부 보행로 서비스수준 (A~F)

데이터 출처/캘리브레이션:
  - 보행속도 1.20 m/s    -- 서울교통공사 환승소요시간 표준
  - 태그 서비스시간 2.7s  -- Beijing 우안문 실측 (Gao 2019)
  - 태그리스 통과시간 1.2s -- 게이트 1.5m / 보행속도 1.3m/s
  - 에스컬 처리율 1.17 ped/s -- Cheung & Lam 2002 홍콩 MTR
"""
from __future__ import annotations
from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from analysis.molit_los import WALKWAY_LOS, grade

DENS = ROOT / "results" / "molit" / "density_union.csv"
OUT = ROOT / "results" / "molit" / "FINAL_REPORT_V2.txt"

PASS_RATE_MIN = 0.9
LOS_E_MAX = 1.0   # 국토부 첨두 기준
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
        n=("seed", "count"),
    ).reset_index()

    out = []
    add = out.append

    add("=" * 100)
    add("태그리스 게이트 운영 방안 — 최종 보고")
    add("=" * 100)
    add("")
    add("[데이터 출처/캘리브레이션]")
    add("  보행속도 1.20 m/s     : 서울교통공사 환승소요시간 표준")
    add("  태그 서비스시간 2.7s  : Beijing 우안문 실측 (Gao 2019, lognormal)")
    add("  태그리스 통과시간 1.2s : 게이트 길이 1.5m / 보행속도 1.3m/s")
    add("  에스컬 처리율 1.17 ped/s : Cheung & Lam 2002 홍콩 MTR")
    add("  열차 도착 간격 150s, 편당 200명 (Poisson), 시뮬 600s = 4편 처리")
    add("  시나리오: 5 seed × 5 p × 6 cfg = 150 전체")
    add("  필터: pass_rate ≥ 0.9 (시뮬 시간 내 90% 이상 처리된 case만 — 신뢰 가능 데이터)")

    # ════ 표 1: LOS 기준 ════
    add("\n" + "=" * 100)
    add("[표 1] 국토부 고시 제2025-241호 표 2.3 보행로 서비스수준")
    add("=" * 100)
    add("")
    add("설명: 보행 밀도 (인/m²) 가 어느 등급에 해당하는지 판정하는 국토부 공식 기준.")
    add("       지침 2.2.3(2) 에 따라 첨두시간대 한계 기준은 LOS E (밀도 ≤ 1.0).")
    add("       즉 W2 peak 밀도가 1.0 을 넘으면 국토부 기준 위반.")
    add("")
    add(f"  {'등급':>4} | {'밀도 상한 (인/m²)':>16} | 보행 상태")
    add(f"  {'-'*4} | {'-'*16} | {'-'*40}")
    for g, u, d in WALKWAY_LOS:
        ulim = f"≤ {u}" if u != float("inf") else "1.0 초과"
        add(f"  {g:>4} | {ulim:>16} | {d}")

    # ════ 표 2: 시뮬 결과 ════
    add("\n" + "=" * 100)
    add("[표 2] 시뮬 결과 — (p, cfg) 별 측정 보행밀도와 LOS 등급")
    add("=" * 100)
    add("")
    add("설명: 각 행은 한 시나리오 (태그리스 비율 p × 전용 게이트 수 cfg) 의 결과.")
    add("       W2 = 에스컬 앞 대기공간 (20.0 m²) 에서 측정한 보행밀도.")
    add("       W2 평균 = 시뮬 600초 동안의 시간평균. W2 peak = 같은 기간 중 최대값.")
    add("       LOS 등급은 표 1 기준으로 판정. 5 seed 평균 값을 사용.")
    add("")
    add(f"  {'p':>4} {'cfg':>4} | {'W2 평균':>7} {'LOS':>4} | {'W2 peak':>8} {'LOS':>4} | "
        f"{'통행시간':>9} | {'게이트 대기':>11}")
    add(f"  {'-'*4} {'-'*4} | {'-'*7} {'-'*4} | {'-'*8} {'-'*4} | "
        f"{'-'*9} | {'-'*11}")
    for _, r in agg.iterrows():
        add(f"  {r['p']:>4.1f} {int(r['config']):>4d} | "
            f"{r['W2_avg']:>6.3f}  {los(r['W2_avg']):>3} | "
            f"{r['W2_pk']:>7.3f}  {los(r['W2_pk']):>3} | "
            f"{r['travel']:>7.1f}s | {r['gate_wait']:>9.1f}s")

    # ════ 표 3: G vs S 통행시간 ════
    add("\n" + "=" * 100)
    add("[표 3] (G) 게이트만 최적 cfg vs (S) 시스템 최적 cfg — 통행시간 비교")
    add("=" * 100)
    add("")
    add("설명: 두 관점에서 어떤 cfg 가 가장 좋은지 비교.")
    add("       (G) = 게이트 대기시간 (gate_wait) 만 최소화 → '게이트만' 보면 최적인 cfg")
    add("       (S) = 통행시간 (travel) 전체를 최소화 → '시스템' 전체로 보면 최적인 cfg")
    add("       두 cfg 가 같으면 '게이트만 보든 시스템 전체로 보든 같은 답'.")
    add("       두 cfg 가 다르면 '게이트는 줄지만 통행시간은 오히려 길어지는 역설 발현'.")
    add("")
    add(f"  {'p':>4} | {'G cfg':>5} | {'G 통행시간':>9} | {'S cfg':>5} | "
        f"{'S 통행시간':>9} | {'두 cfg 다른가?':>14}")
    add(f"  {'-'*4} | {'-'*5} | {'-'*9} | {'-'*5} | {'-'*9} | {'-'*14}")
    for p_val in sorted(agg["p"].unique()):
        sub = agg[agg["p"] == p_val]
        rg = sub.loc[sub["gate_wait"].idxmin()]
        rs = sub.loc[sub["travel"].idxmin()]
        same = int(rg["config"]) == int(rs["config"])
        mark = "같음" if same else "다름 (역설!)"
        add(f"  {p_val:>4.1f} | cfg{int(rg['config']):>2d} | "
            f"{rg['travel']:>7.1f}s | cfg{int(rs['config']):>2d} | "
            f"{rs['travel']:>7.1f}s | {mark:>14s}")

    # ════ 표 4: LOS E 만족 cfg ════
    add("\n" + "=" * 100)
    add("[표 4] LOS E (밀도 ≤ 1.0) 만족하는 cfg — 국토부 첨두 기준 통과 cfg 목록")
    add("=" * 100)
    add("")
    add("설명: 각 p 에서 W2 peak 밀도가 1.0 이하인 (= 국토부 기준 통과) cfg 후보들.")
    add("       그 중에서 통행시간이 가장 짧은 cfg 가 '권고' 대상.")
    add("       '없음' 으로 표시되면 어떤 cfg 도 기준 통과 못함 = 시설 자체가 부족.")
    add("")
    add(f"  {'p':>4} | {'기준 통과 cfg 후보':>20s} | {'권고 cfg':>8} | {'통행시간':>9} | "
        f"{'W2 peak':>8} {'LOS':>4}")
    add(f"  {'-'*4} | {'-'*20} | {'-'*8} | {'-'*9} | {'-'*8} {'-'*4}")
    los_e_choice = {}
    for p_val in sorted(agg["p"].unique()):
        feasible = agg[(agg["p"] == p_val) & (agg["W2_pk"] <= LOS_E_MAX)]
        if len(feasible) == 0:
            add(f"  {p_val:>4.1f} | {'없음':>20s} | {'-':>8s} | {'-':>9s} | "
                f"{'-':>8s} {'-':>4}")
            los_e_choice[p_val] = None
            continue
        best = feasible.loc[feasible["travel"].idxmin()]
        cfg_str = ", ".join(f"cfg{int(c)}" for c in feasible["config"])
        add(f"  {p_val:>4.1f} | {cfg_str:>20s} | {'cfg'+str(int(best['config'])):>8s} | "
            f"{best['travel']:>7.1f}s | {best['W2_pk']:>7.3f}  {los(best['W2_pk']):>3}")
        los_e_choice[p_val] = (int(best["config"]), best["travel"], best["W2_pk"])

    # ════ 표 5: 고정 운영 가능성 ════
    add("\n" + "=" * 100)
    add("[표 5] 고정 운영 검토 — 모든 시간대를 같은 cfg 로 운영 가능한가?")
    add("=" * 100)
    add("")
    add("설명: 시간대별로 cfg 를 바꾸지 않고 '한 가지 cfg 만 계속 운영' 하는 방식.")
    add("       이 표는 '어떤 cfg 가 모든 p (10%~80% 혼입률) 시간대에서 LOS E 통과하는가'")
    add("       를 검토. 한 cfg 라도 모든 p 에서 통과하면 '고정 운영 가능'.")
    add("       모든 cfg 가 일부 p 에서 LOS E 위반하면 '고정 운영 불가능 → 가변 운영 필수'.")
    add("")
    p_list = sorted(agg["p"].unique())
    header = f"  {'cfg':>3} | "
    for p_val in p_list:
        header += f"p={p_val:.1f} W2pk LOS | "
    header += f"{'모든 p에서 통과?':>16}"
    add(header)
    add(f"  {'-'*3} | " + " | ".join(["-" * 14] * len(p_list)) +
        f" | {'-'*16}")
    fixed_candidates = []
    for cfg in sorted(agg["config"].unique()):
        sub = agg[agg["config"] == cfg].set_index("p")
        line = f"  cfg{int(cfg)} | "
        all_ok = True
        for p_val in p_list:
            if p_val not in sub.index:
                line += f"   (없음)      | "
                all_ok = False
                continue
            r = sub.loc[p_val]
            ok = r["W2_pk"] <= LOS_E_MAX
            line += f"{r['W2_pk']:>5.2f}  {los(r['W2_pk']):>3}    | "
            if not ok: all_ok = False
        line += f"{'예 (가능)' if all_ok else '아니오 (불가)':>16}"
        add(line)
        if all_ok:
            fixed_candidates.append(int(cfg))

    # ════ 표 6: 가변 vs 고정 ════
    add("\n" + "=" * 100)
    add("[표 6] 가변 운영 vs 고정 운영 — 통행시간 비교")
    add("=" * 100)
    add("")
    add("설명: 가변 = 시간대별로 다른 cfg 채택 (각 p 에 대해 LOS E 통과 + 통행시간 최저)")
    add("       고정 = 단일 cfg 채택 (모든 p 에서 LOS E 통과 보장하는 cfg)")
    add("       가중평균 통행시간 = Σ (각 p 의 통행시간 × 그 p 의 시간대 비율)")
    add(f"       가중치 (시간대 비율): " +
        ", ".join(f"p={p}={int(w*100)}%" for p, w in TIME_WEIGHT.items()))
    add("")
    if not fixed_candidates:
        add("  → 단일 cfg 로 모든 p 에서 LOS E 통과 = 불가능")
        add("  → 결론: 가변 운영이 필수")
    else:
        for cfg in fixed_candidates:
            sub = agg[agg["config"] == cfg].set_index("p")
            tw = sum(sub.loc[p, "travel"] * TIME_WEIGHT.get(p, 0)
                     for p in p_list if p in sub.index)
            add(f"  고정 cfg{int(cfg)}: 가중평균 통행시간 = {tw:.1f}s")
        if all(los_e_choice[p] is not None for p in p_list):
            var_tw = sum(los_e_choice[p][1] * TIME_WEIGHT.get(p, 0) for p in p_list)
            best_fixed_cfg = fixed_candidates[0]
            sub = agg[agg["config"] == best_fixed_cfg].set_index("p")
            best_fixed_tw = sum(sub.loc[p, "travel"] * TIME_WEIGHT.get(p, 0)
                                for p in p_list if p in sub.index)
            add(f"  가변 운영      : 가중평균 통행시간 = {var_tw:.1f}s")
            diff = best_fixed_tw - var_tw
            pct = 100 * diff / best_fixed_tw
            add(f"  → 가변이 고정 cfg{best_fixed_cfg} 대비 {diff:+.1f}s ({pct:+.1f}%) 절감")
        else:
            add(f"  가변 운영: 일부 p 에서 LOS E 통과 cfg 없음 → 가변도 불완전")

    # ════ 표 7: 권고 ════
    add("\n" + "=" * 100)
    add("[표 7] 최종 권고 — p 별 운영 cfg")
    add("=" * 100)
    add("")
    add("설명: 표 4 의 'LOS E 통과 + 통행시간 최저 cfg' 를 정리한 권고안.")
    add("       각 시간대 (p) 별로 어느 cfg 를 운영할지 결정한 표.")
    add("")
    add(f"  {'p':>4} | {'권고 cfg':>8} | {'통행시간':>9} | {'W2 peak':>8} {'LOS':>4} | "
        f"비고")
    add(f"  {'-'*4} | {'-'*8} | {'-'*9} | {'-'*8} {'-'*4} | {'-'*40}")
    for p_val in p_list:
        if los_e_choice[p_val] is None:
            add(f"  {p_val:>4.1f} | {'없음':>8s} | {'-':>9s} | {'-':>8s} {'-':>4} | "
                f"기준 통과 cfg 없음 (시설 부족)")
        else:
            cfg, tr, w2pk = los_e_choice[p_val]
            add(f"  {p_val:>4.1f} | {'cfg'+str(cfg):>8s} | {tr:>7.1f}s | "
                f"{w2pk:>7.3f}  {los(w2pk):>3} | LOS E 통과 + 통행시간 최저")

    text = "\n".join(out)
    print(text)
    OUT.write_text(text, encoding="utf-8")
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()
