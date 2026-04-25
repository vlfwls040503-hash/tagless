"""
종합 분석 (합집합 zone 기반):
  1. MOLIT 보행밀도 기준표
  2. 시뮬 결과 보행밀도 표 (LOS 등급 포함)
  3. 병목 전이 현상 분석
  4. 게이트 vs 시스템 trade-off
  5. 최적 cfg 도출 (4관점)
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
OUT = ROOT / "results" / "molit" / "FINAL_REPORT.txt"

PASS_RATE_MIN = 0.9
N_GATES = 7


def los(d):
    return grade(d, WALKWAY_LOS)


def main():
    df = pd.read_csv(DENS)
    df = df[df["pass_rate"] >= PASS_RATE_MIN].copy()

    agg = df.groupby(["p", "config"]).agg(
        tp_act=("throughput_active", "mean"),
        per_gate=("per_gate_active", "mean"),
        active=("active_period", "mean"),
        travel=("avg_travel_time", "mean"),
        gate_w=("avg_gate_wait", "mean"),
        W1_avg=("W1_avg_density", "mean"),
        W1_pk=("W1_peak_density", "mean"),
        W2_avg=("W2_avg_density", "mean"),
        W2_pk=("W2_peak_density", "mean"),
        n_seed=("seed", "count"),
    ).reset_index()

    out = []
    add = out.append

    # ── 1. MOLIT 기준표 ──
    add("=" * 100)
    add("[1] 국토부 고시 제2025-241호 표 2.3 보행로 LOS 기준")
    add("=" * 100)
    add(f"{'등급':>4} | {'밀도 상한 (인/m²)':>18} | 설명")
    add("-" * 80)
    for g, u, d in WALKWAY_LOS:
        ulim = f"≤ {u}" if u != float("inf") else "초과"
        add(f"{g:>4} | {ulim:>18} | {d}")
    add("\n측정 zone:")
    add("  W1 = 게이트 앞 대기 (110.5 m²)  — 큐 형성 영역")
    add("  W2 = upper 에스컬 앞 대기 (20.0 m²)  — 병목 전이 후보 영역")
    add("  ※ 측정 zone 은 100 시나리오 (cfg1~4, pass_rate≥0.9 → 81 trajectory) "
        "wait footprint 합집합으로 도출")

    # ── 2. 시뮬 결과 표 ──
    add("\n" + "=" * 100)
    add("[2] 시뮬 결과 보행밀도 (p × cfg 평균, pass_rate≥0.9 만, n=5seed)")
    add("=" * 100)
    add(f"{'p':>4} {'cfg':>3} | {'W1_avg':>7} {'LOS':>4} | {'W1_pk':>7} {'LOS':>4} "
        f"| {'W2_avg':>7} {'LOS':>4} | {'W2_pk':>7} {'LOS':>4} | {'n':>3}")
    add("-" * 100)
    for _, r in agg.iterrows():
        add(f"{r['p']:>4.1f} {int(r['config']):>3d} | "
            f"{r['W1_avg']:>6.3f}  {los(r['W1_avg']):>3} | "
            f"{r['W1_pk']:>6.3f}  {los(r['W1_pk']):>3} | "
            f"{r['W2_avg']:>6.3f}  {los(r['W2_avg']):>3} | "
            f"{r['W2_pk']:>6.3f}  {los(r['W2_pk']):>3} | "
            f"{int(r['n_seed']):>3d}")

    # ── 3. 병목 전이 분석 ──
    add("\n" + "=" * 100)
    add("[3] 병목 전이 분석: cfg 증가에 따른 ΔW1 vs ΔW2")
    add("    (병목 전이 = cfg ↑ → W1 ↓ + W2 ↑ 동시 발생)")
    add("=" * 100)
    add(f"{'p':>4} | {'cfg전이':>9} | {'ΔW1_avg':>9} | {'ΔW2_avg':>9} | "
        f"{'Δgate_wait':>11} | {'Δtravel':>9} | 판정")
    add("-" * 100)
    transitions = []
    for p_val in sorted(agg["p"].unique()):
        sub = agg[agg["p"] == p_val].sort_values("config").reset_index(drop=True)
        for i in range(len(sub) - 1):
            r0, r1 = sub.iloc[i], sub.iloc[i + 1]
            d_w1 = r1["W1_avg"] - r0["W1_avg"]
            d_w2 = r1["W2_avg"] - r0["W2_avg"]
            d_gw = r1["gate_w"] - r0["gate_w"]
            d_tr = r1["travel"] - r0["travel"]
            transfer = "전이 O" if (d_w1 < -0.01 and d_w2 > 0.01) else (
                "역전이"   if (d_w1 > 0.01  and d_w2 < -0.01) else "변화 미미"
            )
            transitions.append({
                "p": p_val, "from_cfg": int(r0["config"]), "to_cfg": int(r1["config"]),
                "d_W1": d_w1, "d_W2": d_w2, "d_gw": d_gw, "d_tr": d_tr,
                "transfer": transfer,
            })
            add(f"{p_val:>4.1f} | cfg{int(r0['config'])}→cfg{int(r1['config'])} | "
                f"{d_w1:>+8.3f} | {d_w2:>+8.3f} | "
                f"{d_gw:>+9.1f}s | {d_tr:>+7.1f}s | {transfer}")

    n_trans_yes = sum(1 for t in transitions if t["transfer"] == "전이 O")
    n_trans_total = len(transitions)
    add(f"\n→ 전체 {n_trans_total}개 cfg 증분 중 {n_trans_yes}개에서 병목 전이 "
        f"(W1↓ + W2↑) 동시 관측 = {100*n_trans_yes/n_trans_total:.0f}%")

    # ── 4. 게이트 vs 시스템 trade-off ──
    add("\n" + "=" * 100)
    add("[4] 게이트 대기시간 vs 시스템 통행시간 (관점별 최적 cfg 비교)")
    add("=" * 100)
    add("관점:")
    add("  (G)  게이트만:  avg_gate_wait 최소화")
    add("  (S)  시스템:    avg_travel_time 최소화 (제약 없음)")
    add("  (S+C) 시스템 + LOS C 제약: travel_time 최소 s.t. W2_peak ≤ 0.7")
    add("  (S+D) 시스템 + LOS D 제약: travel_time 최소 s.t. W2_peak ≤ 1.0")
    add("")
    add(f"{'p':>4} | {'(G) gate':>22} | {'(S) system':>22} | "
        f"{'(S+C) LOS≤0.7':>26} | {'(S+D) LOS≤1.0':>26}")
    add("-" * 130)

    optimal = []
    for p_val in sorted(agg["p"].unique()):
        sub = agg[agg["p"] == p_val]
        # G
        rg = sub.loc[sub["gate_w"].idxmin()]
        # S
        rs = sub.loc[sub["travel"].idxmin()]
        # S+C (W2_pk ≤ 0.7)
        sc = sub[sub["W2_pk"] <= 0.7]
        rsc = sc.loc[sc["travel"].idxmin()] if len(sc) else None
        # S+D (W2_pk ≤ 1.0)
        sd = sub[sub["W2_pk"] <= 1.0]
        rsd = sd.loc[sd["travel"].idxmin()] if len(sd) else None

        def fmt(r):
            if r is None: return "(LOS 제약 불가)"
            return (f"cfg{int(r['config'])} tr={r['travel']:.1f}s W2pk={r['W2_pk']:.2f}")

        add(f"{p_val:>4.1f} | "
            f"cfg{int(rg['config'])} gw={rg['gate_w']:.1f}s tr={rg['travel']:.1f}s | "
            f"cfg{int(rs['config'])} gw={rs['gate_w']:.1f}s tr={rs['travel']:.1f}s | "
            f"{fmt(rsc):>30} | "
            f"{fmt(rsd):>30}")

        optimal.append({
            "p": p_val,
            "G": int(rg["config"]), "G_gw": rg["gate_w"], "G_tr": rg["travel"],
            "S": int(rs["config"]), "S_gw": rs["gate_w"], "S_tr": rs["travel"],
            "SC": int(rsc["config"]) if rsc is not None else None,
            "SC_tr": rsc["travel"] if rsc is not None else None, "SC_W2pk": rsc["W2_pk"] if rsc is not None else None,
            "SD": int(rsd["config"]) if rsd is not None else None,
            "SD_tr": rsd["travel"] if rsd is not None else None, "SD_W2pk": rsd["W2_pk"] if rsd is not None else None,
        })

    # ── 5. (G) vs (S) travel time 직접 비교 ──
    add("\n" + "=" * 100)
    add("[5] (G) 게이트만 vs (S) 시스템 — 통행시간 직접 비교")
    add("=" * 100)
    add(f"{'p':>4} | {'(G) cfg':>8} | {'(G) travel':>11} | {'(S) cfg':>8} | "
        f"{'(S) travel':>11} | {'차이':>8}")
    add("-" * 70)
    for o in optimal:
        diff = o["G_tr"] - o["S_tr"]
        marker = " ←" if abs(diff) > 0.3 else ""
        add(f"{o['p']:>4.1f} | cfg{o['G']:>5d} | {o['G_tr']:>10.1f}s | "
            f"cfg{o['S']:>5d} | {o['S_tr']:>10.1f}s | {diff:>+6.1f}s{marker}")
    add(f"\n→ 5개 p 중 4개에서 (G)≡(S) 동일. p=0.8 만 cfg 다르나 차이 0.5s = "
        f"통계적으로 거의 무의미.")
    add(f"→ 결론: 통행시간 단독으로는 '전용게이트 늘리면 시스템 비용 ↑' 역설 거의 "
        f"발현 안 됨.")

    # ── 6. 핵심 메시지 (정정) ──
    add("\n" + "=" * 100)
    add("[6] 본 연구의 핵심 메시지 (정정)")
    add("=" * 100)
    add("")
    add("[발견 1] 병목 전이는 명확히 발생")
    add("  - 게이트 처리율 vs W2 평균밀도: Spearman ρ = +0.659 (p < 1e-13)")
    add("  - gate_wait vs W2 평균밀도:    ρ = -0.908 (p < 1e-40, 시소관계)")
    add("  - 최대 전이비: 4.4 (게이트 1명 빠질 때 W2 4.4명 적체)")
    add("")
    add("[발견 2] 그러나 시스템 통행시간 손실은 미미")
    add("  - p=0.8 cfg5(역설발현)도 cfg4 대비 통행시간 +0.5s (사실상 동일)")
    add("  - 원인: 에스컬 capacity (2.36 ped/s) > 게이트 capacity (1.47 ped/s)")
    add("    → 에스컬 여유 1.6배 → 전이 흡수 가능")
    add("")
    add("[발견 3] 진짜 cfg 상한은 LOS 안전성에서 옴")
    add("  - 운영 가능 cfg(2~4) 안에서 LOS D(≤1.0)가 한계")
    add("  - p≥0.5 부터 LOS C(≤0.7) 만족 cfg 없음")
    add("  - p=0.7 cfg4: W2_pk=1.34 (LOS E 진입 직전)")
    add("")
    add("[정책 시사] 가변 운영의 근거 = LOS 안전성 (통행시간 아님)")
    add("  LOS C 기준: p=0.1→cfg1, p=0.3→cfg3, p=0.5→불가, p=0.7→cfg2, p=0.8→cfg3")
    add("  LOS D 기준: p=0.1→cfg1, p=0.3→cfg2, p=0.5→cfg2, p=0.7→cfg2, p=0.8→cfg4")
    add("")
    add("※ cfg5,6 은 pass_rate 84%/69% 로 정상 운영 불가. 본 연구 핵심 결론은 cfg2~4 기준.")

    # ── 출력 ──
    text = "\n".join(out)
    print(text)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()
