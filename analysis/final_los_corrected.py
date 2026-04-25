"""
국토부 정본 LOS 기준 (D=0.8, E=1.0) 으로 최종 분석.

산출:
  1. MOLIT 기준표
  2. 시뮬 결과 표 (p, cfg, 측정 W2 평균/peak, LOS 등급)
  3. (G) 게이트만 vs (S) 시스템 — cfg 와 통행시간 비교
  4. LOS D (≤0.8) 만족하는 cfg 분석
  5. 가변 vs 고정 운영 비교

용어:
  - p: 태그리스 이용 비율
  - cfg: 전용 게이트 수 (1~4)
  - travel time: 평균 통행시간 (게이트 진입~출구 도달)
  - gate wait: 평균 게이트 대기시간
  - W2: 에스컬레이터 앞 대기공간 (도출 면적 20.0 m²)

데이터 출처/캘리브레이션:
  - 보행속도 평균 1.20 m/s (표준편차 0.20) — 서울교통공사 환승소요시간 표준
  - 태그 게이트 서비스시간 평균 2.7 s (lognormal) — Beijing 우안문 실측 (Gao 2019)
  - 태그리스 통과시간 1.2 s (고정, 1.5m / 1.3m/s)
  - 에스컬레이터 처리율 1.17 ped/s (2인 동시 탑승) — Cheung & Lam 2002 홍콩 MTR
  - 시뮬 시간 600s (열차 4편 처리), 5 seed × 5 p × 6 cfg = 150 시나리오
"""
from __future__ import annotations
from pathlib import Path
import sys
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from analysis.molit_los import WALKWAY_LOS, grade

DENS = ROOT / "results" / "molit" / "density_union.csv"
OUT = ROOT / "results" / "molit" / "FINAL_LOS_CORRECTED.txt"

PASS_RATE_MIN = 0.9
LOS_E_MAX = 1.0   # 국토부 E 등급 상한 — 첨두시간대 한계 기준
LOS_D_MAX = 0.8
TIME_WEIGHT = {0.1: 0.30, 0.3: 0.30, 0.5: 0.20, 0.7: 0.15, 0.8: 0.05}


def los(d):
    return grade(d, WALKWAY_LOS)


def main():
    df = pd.read_csv(DENS)
    df = df[df["pass_rate"] >= PASS_RATE_MIN].copy()
    # 운영 가능 cfg 만 (cfg5,6 은 pass_rate 84%/69% 로 정상 운영 불가)
    df = df[df["config"].isin([1, 2, 3, 4])].copy()

    agg = df.groupby(["p", "config"]).agg(
        travel=("avg_travel_time", "mean"),
        gate_wait=("avg_gate_wait", "mean"),
        W2_avg=("W2_avg_density", "mean"),
        W2_pk=("W2_peak_density", "mean"),
        n=("seed", "count"),
    ).reset_index()

    out = []
    add = out.append

    # ── 0. 분석 메타 ──
    add("=" * 100)
    add("국토부 LOS D 기준 최종 분석 — 태그리스 게이트 운영 방안")
    add("=" * 100)
    add("\n[데이터 출처/캘리브레이션]")
    add("  - 보행속도: 1.20 m/s (표준편차 0.20)  -- 서울교통공사 환승소요시간 표준")
    add("  - 태그 서비스시간: 2.7s (lognormal)   -- Beijing 우안문 실측 (Gao 2019)")
    add("  - 태그리스 통과시간: 1.2s (고정)       -- 게이트 1.5m / 보행속도 1.3m/s")
    add("  - 에스컬레이터 처리율: 1.17 ped/s     -- Cheung & Lam 2002 홍콩 MTR")
    add("  - 시뮬 시간: 600s (열차 4편 처리)")
    add("  - 시나리오: 5 seed × 5 p × 4 cfg = 100 (cfg5,6 운영 불가로 제외)")
    add("  - W2 (에스컬 앞 대기공간): 100 시나리오 wait footprint 합집합 = 20.0 m²")

    # ── 1. MOLIT 기준표 ──
    add("\n" + "=" * 100)
    add("[표 1] 국토부 고시 제2025-241호 표 2.3 보행로 서비스수준")
    add("=" * 100)
    add(f"{'등급':>4} | {'밀도 상한 (인/m²)':>16} | 보행 상태")
    add("-" * 80)
    for g, u, d in WALKWAY_LOS:
        ulim = f"≤ {u}" if u != float("inf") else "1.0 초과"
        add(f"{g:>4} | {ulim:>16} | {d}")

    # ── 2. 시뮬 결과 표 ──
    add("\n" + "=" * 100)
    add("[표 2] 시뮬 결과 — p × cfg 별 측정 보행밀도와 LOS 등급")
    add("    p   = 태그리스 이용 비율")
    add("    cfg = 전용 게이트 수")
    add("    W2  = 에스컬 앞 대기공간 측정 밀도 (5 seed 평균)")
    add("=" * 100)
    add(f"{'p':>4} {'cfg':>3} | {'W2 평균밀도':>10} {'LOS':>4} | "
        f"{'W2 peak 밀도':>11} {'LOS':>4} | {'평균 통행시간':>11} | "
        f"{'평균 게이트 대기':>14}")
    add("-" * 100)
    for _, r in agg.iterrows():
        add(f"{r['p']:>4.1f} {int(r['config']):>3d} | "
            f"{r['W2_avg']:>9.3f}  {los(r['W2_avg']):>3} | "
            f"{r['W2_pk']:>10.3f}  {los(r['W2_pk']):>3} | "
            f"{r['travel']:>9.1f}s | "
            f"{r['gate_wait']:>12.1f}s")

    # ── 3. (G) vs (S) — cfg + 통행시간 직접 비교 ──
    add("\n" + "=" * 100)
    add("[표 3] (G) 게이트만 최적 vs (S) 시스템 최적 — cfg 와 통행시간 비교")
    add("    (G) = 평균 게이트 대기시간 최소가 되는 cfg")
    add("    (S) = 평균 통행시간 최소가 되는 cfg")
    add("=" * 100)
    add(f"{'p':>4} | {'G cfg':>5} | {'G 통행시간':>10} | {'S cfg':>5} | "
        f"{'S 통행시간':>10} | {'통행시간 차이':>12}")
    add("-" * 80)
    optimal = []
    for p_val in sorted(agg["p"].unique()):
        sub = agg[agg["p"] == p_val]
        rg = sub.loc[sub["gate_wait"].idxmin()]
        rs = sub.loc[sub["travel"].idxmin()]
        diff = rg["travel"] - rs["travel"]
        marker = " ← cfg 다름" if int(rg["config"]) != int(rs["config"]) else ""
        add(f"{p_val:>4.1f} | cfg{int(rg['config'])}  | "
            f"{rg['travel']:>9.1f}s | cfg{int(rs['config'])}  | "
            f"{rs['travel']:>9.1f}s | {diff:>+10.1f}s{marker}")
        optimal.append({"p": p_val, "G_cfg": int(rg["config"]),
                        "S_cfg": int(rs["config"]),
                        "G_tr": rg["travel"], "S_tr": rs["travel"]})

    # ── 4. LOS D (≤0.8) 만족 cfg ──
    add("\n" + "=" * 100)
    add("[표 4] LOS D (≤0.8 인/m²) 만족하는 cfg — peak 밀도 기준")
    add("    국토부 지침 2.2.3(2) 첨두시간대 LOS D 이상 준수")
    add("=" * 100)
    add(f"{'p':>4} | {'LOS D 만족 cfg':>20} | {'그 중 통행시간 최저 cfg':>22} | "
        f"{'통행시간':>9} | {'W2 peak':>8}")
    add("-" * 100)
    los_d_choice = {}
    for p_val in sorted(agg["p"].unique()):
        feasible = agg[(agg["p"] == p_val) & (agg["W2_pk"] <= LOS_D_MAX)]
        if len(feasible) == 0:
            add(f"{p_val:>4.1f} | {'없음 (운영 불가)':>20} | - | - | -")
            los_d_choice[p_val] = None
            continue
        best = feasible.loc[feasible["travel"].idxmin()]
        cfg_str = ", ".join(f"cfg{int(c)}" for c in feasible["config"])
        add(f"{p_val:>4.1f} | {cfg_str:>20s} | {'cfg'+str(int(best['config'])):>22s} | "
            f"{best['travel']:>7.1f}s | {best['W2_pk']:>7.3f}")
        los_d_choice[p_val] = (int(best["config"]), best["travel"], best["W2_pk"])

    # ── 5. 모든 p에서 LOS D 만족하는 단일 cfg 탐색 ──
    add("\n" + "=" * 100)
    add("[표 5] 단일 cfg 로 모든 p 에서 LOS D 만족 가능한지 검토")
    add("    (= 시간대 무관 고정 운영 가능성)")
    add("=" * 100)
    p_list = sorted(agg["p"].unique())
    header = f"{'cfg':>3} | "
    for p_val in p_list:
        header += f"p={p_val:.1f} W2pk LOS | "
    header += f"{'모든 p에서 LOS D?':>17}"
    add(header)
    add("-" * len(header))
    fixed_candidates = []
    for cfg in sorted(agg["config"].unique()):
        sub = agg[agg["config"] == cfg].set_index("p")
        line = f"cfg{int(cfg)} | "
        all_ok = True
        for p_val in p_list:
            if p_val not in sub.index:
                line += f"   (없음)        | "
                all_ok = False
                continue
            r = sub.loc[p_val]
            ok = r["W2_pk"] <= LOS_D_MAX
            line += f"{r['W2_pk']:>5.2f}  {los(r['W2_pk']):>3}    | "
            if not ok: all_ok = False
        line += f"{'예 (고정 가능)' if all_ok else '아니오':>17}"
        add(line)
        if all_ok:
            fixed_candidates.append(cfg)

    # ── 6. 가변 vs 고정 운영 비교 ──
    add("\n" + "=" * 100)
    add("[표 6] 가변 운영 vs 고정 운영 — 통행시간 비교")
    add("    가변: 각 p 에서 LOS D 만족하면서 통행시간 최저인 cfg 채택")
    add("    고정: 모든 p 에서 LOS D 만족하는 단일 cfg 채택")
    add(f"    가중치 (시간대 비율): " +
        ", ".join(f"p={p}={int(w*100)}%" for p, w in TIME_WEIGHT.items()))
    add("=" * 100)

    if not fixed_candidates:
        add("\n  단일 cfg 로 모든 p에서 LOS D 만족 = 불가능 → 가변 운영 필수")
        fixed_cfg = None
    else:
        # 고정 cfg 별 가중평균 통행시간
        for cfg in fixed_candidates:
            sub = agg[agg["config"] == cfg].set_index("p")
            tw = sum(sub.loc[p, "travel"] * TIME_WEIGHT.get(p, 0)
                     for p in p_list if p in sub.index)
            add(f"  고정 cfg{int(cfg)}: 가중평균 통행시간 = {tw:.1f}s")
        fixed_cfg = fixed_candidates[0]
        sub = agg[agg["config"] == fixed_cfg].set_index("p")
        fixed_tw = sum(sub.loc[p, "travel"] * TIME_WEIGHT.get(p, 0)
                       for p in p_list if p in sub.index)

        # 가변 가중평균
        if all(los_d_choice[p] is not None for p in p_list):
            var_tw = sum(los_d_choice[p][1] * TIME_WEIGHT.get(p, 0) for p in p_list)
            add(f"\n  가변 운영: 가중평균 통행시간 = {var_tw:.1f}s")
            diff = fixed_tw - var_tw
            pct = 100 * diff / fixed_tw
            add(f"  → 가변이 고정 대비 {diff:+.1f}s ({pct:+.1f}%) 절감")
        else:
            add(f"\n  가변 운영: 일부 p에서 LOS D 만족 cfg 없음")

    # ── 7. 최종 권고 ──
    add("\n" + "=" * 100)
    add("[표 7] 최종 권고 — p별 운영 cfg")
    add("=" * 100)
    add(f"{'p':>4} | {'권고 cfg':>8} | {'통행시간':>9} | {'W2 peak':>8} {'LOS':>4} | "
        f"근거")
    add("-" * 100)
    for p_val in p_list:
        if los_d_choice[p_val] is None:
            add(f"{p_val:>4.1f} | {'없음':>8s} | {'-':>9s} | {'-':>8s} {'-':>4} | LOS D 만족 cfg 없음")
        else:
            cfg, tr, w2pk = los_d_choice[p_val]
            add(f"{p_val:>4.1f} | {'cfg'+str(cfg):>8s} | {tr:>7.1f}s | {w2pk:>7.3f}  "
                f"{los(w2pk):>3} | LOS D 만족 + 통행시간 최저")

    text = "\n".join(out)
    print(text)
    OUT.write_text(text, encoding="utf-8")
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()
