"""
LOS D (≤1.0 ped/m²) 기준 — 고정 vs 가변 운영 비교 + 안전여유 분석.

가설 (RQ3):
  혼입률(p) 시간대별로 변할 때, p별 최적 cfg(가변) 가 단일 cfg(고정)보다 유리.

비교 대상:
  - 고정 운영: 최악 시간대 (p=0.8) 기준 LOS D 만족 cfg 선택 → 비첨두에도 동일 cfg 적용
  - 가변 운영: 각 p에 LOS D 만족하면서 통행시간 최소인 cfg 선택

평가:
  1. 평균 통행시간 비교 (가변 - 고정)
  2. W2_peak 안전여유 (1.0 - W2pk) — 외란 robust 정도
  3. p별 운영 시나리오 표
"""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DENS = ROOT / "results" / "molit" / "density_union.csv"
OUT = ROOT / "results" / "molit" / "FIXED_VS_VARIABLE_LOS_D.txt"

PASS_RATE_MIN = 0.9
LOS_D = 1.0
LOS_C = 0.7

# 가정: 첨두/비첨두 비율 (성수역 일반 가정)
TIME_WEIGHT = {0.1: 0.30, 0.3: 0.30, 0.5: 0.20, 0.7: 0.15, 0.8: 0.05}


def main():
    df = pd.read_csv(DENS)
    df = df[df["pass_rate"] >= PASS_RATE_MIN].copy()
    # 운영 가능 cfg 만 (cfg5,6 제외)
    df = df[df["config"].isin([1, 2, 3, 4])].copy()

    agg = df.groupby(["p", "config"]).agg(
        travel=("avg_travel_time", "mean"),
        gate_w=("avg_gate_wait", "mean"),
        W2_avg=("W2_avg_density", "mean"),
        W2_pk=("W2_peak_density", "mean"),
        n=("seed", "count"),
    ).reset_index()

    out = []
    add = out.append
    add("=" * 100)
    add("LOS D (≤1.0 ped/m²) 기준 — 고정 vs 가변 운영 비교")
    add("  국토부 지침 2.2.3(2) '첨두시간대 LOS D 이상' 준거")
    add(f"  데이터: 운영 가능 cfg(1~4), pass_rate≥{PASS_RATE_MIN}")
    add("=" * 100)

    # ── 1. 가변 운영 — p별 최적 cfg (LOS D 제약) ──
    add(f"\n[1] 가변 운영 — p별 LOS D 만족 + 통행시간 최소 cfg")
    add(f"{'p':>4} | {'cfg*':>4} | {'travel':>7} | {'gate_w':>7} | "
        f"{'W2_pk':>6} | {'안전여유 (1.0 - W2pk)':>22} | {'LOS':>4}")
    add("-" * 90)
    variable_choices = {}
    for p_val in sorted(agg["p"].unique()):
        feasible = agg[(agg["p"] == p_val) & (agg["W2_pk"] <= LOS_D)]
        if len(feasible) == 0:
            add(f"{p_val:>4.1f} | (LOS D 만족 cfg 없음 — 운영 불가)")
            variable_choices[p_val] = None
            continue
        best = feasible.loc[feasible["travel"].idxmin()]
        margin = LOS_D - best["W2_pk"]
        marker = "  안전" if margin > 0.2 else ("  주의" if margin > 0.05 else "  임계")
        add(f"{p_val:>4.1f} | cfg{int(best['config'])} | "
            f"{best['travel']:>6.1f}s | {best['gate_w']:>6.1f}s | "
            f"{best['W2_pk']:>5.2f} | {margin:>+18.2f}{marker} | "
            f"{'D' if best['W2_pk']<=1.0 else 'E':>4}")
        variable_choices[p_val] = (int(best["config"]),
                                    best["travel"], best["W2_pk"])

    # ── 2. 고정 운영 — 모든 p 통합 만족 cfg ──
    add(f"\n[2] 고정 운영 — 단일 cfg 가 모든 p에서 LOS D 만족")
    add(f"     (= 최악 p에서 LOS D 만족 + 평균 통행시간 최소)")
    p_list = sorted(agg["p"].unique())
    line = f"{'cfg':>3} | "
    for p_val in p_list:
        line += f"p={p_val:.1f} W2pk | "
    line += f"{'모두만족?':>9} | {'평균 travel':>11}"
    add(line)
    add("-" * 110)

    feasible_cfgs = []
    for cfg in sorted(agg["config"].unique()):
        sub = agg[agg["config"] == cfg].set_index("p")
        line = f"cfg{int(cfg)} | "
        all_ok = True
        weighted_travel = 0.0
        for p_val in p_list:
            if p_val not in sub.index:
                line += f"  (no data)  | "
                all_ok = False
                continue
            r = sub.loc[p_val]
            ok = r["W2_pk"] <= LOS_D
            mark = "OK" if ok else "X "
            line += f"{r['W2_pk']:>5.2f} {mark}    | "
            if not ok: all_ok = False
            weighted_travel += r["travel"] * TIME_WEIGHT.get(p_val, 0)
        line += f"{'전부 OK' if all_ok else '실패':>9} | {weighted_travel:>9.1f}s"
        add(line)
        if all_ok:
            feasible_cfgs.append((cfg, weighted_travel))

    if feasible_cfgs:
        feasible_cfgs.sort(key=lambda x: x[1])
        fixed_cfg, fixed_travel = feasible_cfgs[0]
        add(f"\n→ 고정 운영 최적: cfg{int(fixed_cfg)} (가중평균 통행시간 {fixed_travel:.1f}s)")
    else:
        add(f"\n→ 모든 p에서 LOS D 만족하는 단일 cfg 없음")
        fixed_cfg = None

    # ── 3. 가변 vs 고정 정량 비교 ──
    add(f"\n[3] 가변 vs 고정 — 통행시간 절감 정량 (가중평균 기준)")
    add(f"     가중치 (시간대 비율): " +
        ", ".join(f"p={p}:{w*100:.0f}%" for p, w in TIME_WEIGHT.items()))

    if fixed_cfg is None:
        add(f"\n  고정 운영 자체 불가 → 가변 운영 필수")
    else:
        var_travel = 0.0
        for p_val in p_list:
            if variable_choices[p_val] is None:
                continue
            _, tr, _ = variable_choices[p_val]
            var_travel += tr * TIME_WEIGHT.get(p_val, 0)
        add(f"\n  고정 운영 (cfg{int(fixed_cfg)})  : 가중평균 통행시간 = {fixed_travel:.1f}s")
        add(f"  가변 운영 (p별 cfg*) : 가중평균 통행시간 = {var_travel:.1f}s")
        diff = fixed_travel - var_travel
        pct = 100 * diff / fixed_travel
        add(f"  → 가변 절감: {diff:+.1f}s ({pct:+.1f}%)")

    # ── 4. LOS C 도전 (가능한 경우) ──
    add(f"\n[4] (참고) LOS C (≤0.7) 가변 운영 가능성")
    add(f"{'p':>4} | LOS C 만족 cfg | travel(최저) | W2_pk")
    add("-" * 60)
    for p_val in p_list:
        feasible = agg[(agg["p"] == p_val) & (agg["W2_pk"] <= LOS_C)]
        if len(feasible) == 0:
            add(f"{p_val:>4.1f} | (LOS C 만족 cfg 없음)")
            continue
        best = feasible.loc[feasible["travel"].idxmin()]
        cfgs = ",".join(f"cfg{int(c)}" for c in feasible["config"])
        add(f"{p_val:>4.1f} | {cfgs:>14s} | cfg{int(best['config'])} {best['travel']:.1f}s | "
            f"{best['W2_pk']:.2f}")

    # ── 5. 핵심 요약 ──
    add(f"\n" + "=" * 100)
    add(f"[5] 정책 권고")
    add(f"=" * 100)
    add(f"")
    add(f"국토부 임계 LOS = D (≤1.0 ped/m²) 기준:")
    add(f"  - 가변 운영 권장 cfg:")
    for p_val in p_list:
        if variable_choices[p_val] is None:
            add(f"    p={p_val:.1f}: 운영 불가 (LOS D 만족 cfg 없음)")
        else:
            cfg, tr, w2 = variable_choices[p_val]
            add(f"    p={p_val:.1f}: cfg{cfg} (travel {tr:.1f}s, W2pk {w2:.2f})")
    if fixed_cfg is not None:
        add(f"  - 고정 운영 강제 시: cfg{int(fixed_cfg)} (모든 p에서 LOS D 만족 가능)")
        add(f"  - 가변 vs 고정 절감: {pct:+.1f}% 통행시간")
    else:
        add(f"  - 고정 운영 불가 → 가변 운영이 유일한 해")

    text = "\n".join(out)
    print(text)
    OUT.write_text(text, encoding="utf-8")
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    # workaround for 'add' func without end param
    main()
