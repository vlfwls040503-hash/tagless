"""
최적 게이트 수 산정 — LOS E 제약 하에서 (G) 게이트만 vs (S) 시스템 비교.

목적:
  국토부 첨두 기준 LOS E (밀도 ≤ 1.0 인/m²) 를 위반하지 않으면서
  (G) 게이트 대기시간 최소 또는 (S) 시스템 통행시간 최소가 되는 cfg 도출.

제약 두 가지로 비교:
  (i)  W2 평균 (active-only) ≤ 1.0
  (ii) W2 peak               ≤ 1.0  (보수적)

W2 평균 (active-only) 정의:
  - W2 zone 안에 1명 이상 있는 시점만 분모로 (빈 시점 제외)
  - 빈 구간 포함하면 평균 희석되어 실제 혼잡 과소평가됨
"""
from __future__ import annotations
from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from analysis.molit_los import WALKWAY_LOS, grade

DENS = ROOT / "results" / "molit" / "density_union.csv"
OUT = ROOT / "results" / "molit" / "OPTIMAL_CFG_LOS_E.txt"

PASS_RATE_MIN = 0.9
LOS_E_MAX = 1.0


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
    add("최적 게이트 수 산정 — LOS E 제약 하에서 (G) vs (S)")
    add("=" * 100)
    add("")
    add("관점:")
    add("  (G) = 게이트 대기시간 (gate_wait) 최소화")
    add("  (S) = 시스템 통행시간 (travel)   최소화")
    add("")
    add("제약:")
    add("  국토부 LOS E (밀도 ≤ 1.0 인/m²) — 첨두시간대 한계 기준")
    add("  W2 평균 (active-only) 또는 W2 peak 이 1.0 을 넘는 cfg 는 후보에서 제외")
    add("")
    add("W2 평균 (active-only) = W2 zone 안에 1명 이상 있는 시점만 분모.")
    add("                       빈 구간 포함하면 혼잡 과소평가되므로 제외.")

    p_list = sorted(agg["p"].unique())

    # ─────────────────────────────────────────────────────────────────
    # [표 A] 제약 없을 때 — 참고용 (이전 결과)
    # ─────────────────────────────────────────────────────────────────
    add("\n" + "=" * 100)
    add("[표 A] 제약 없을 때 — (G) 게이트 최적 vs (S) 시스템 최적")
    add("=" * 100)
    add("")
    add("설명: LOS 제약 무시. cfg 모든 후보 중 G/S 각각의 최적.")
    add("       (이전 보고서의 표 3 과 동일)")
    add("")
    add(f"  {'p':>4} | {'G cfg':>5} | {'gate_wait':>9} | {'travel':>7} | "
        f"{'S cfg':>5} | {'gate_wait':>9} | {'travel':>7}")
    add(f"  {'-'*4} | {'-'*5} | {'-'*9} | {'-'*7} | {'-'*5} | {'-'*9} | {'-'*7}")
    for p_val in p_list:
        sub = agg[agg["p"] == p_val]
        rg = sub.loc[sub["gate_wait"].idxmin()]
        rs = sub.loc[sub["travel"].idxmin()]
        add(f"  {p_val:>4.1f} | cfg{int(rg['config']):>2d} | "
            f"{rg['gate_wait']:>7.1f}s | {rg['travel']:>5.1f}s | "
            f"cfg{int(rs['config']):>2d} | "
            f"{rs['gate_wait']:>7.1f}s | {rs['travel']:>5.1f}s")

    # ─────────────────────────────────────────────────────────────────
    # 헬퍼: 제약 + 관점별 최적 cfg 도출
    # ─────────────────────────────────────────────────────────────────
    def best_under(p_val, constraint_col):
        sub = agg[(agg["p"] == p_val) & (agg[constraint_col] <= LOS_E_MAX)]
        if len(sub) == 0:
            return None, None, None
        rg = sub.loc[sub["gate_wait"].idxmin()]
        rs = sub.loc[sub["travel"].idxmin()]
        return list(sub["config"].astype(int)), rg, rs

    # ─────────────────────────────────────────────────────────────────
    # [표 B] W2 평균 (active-only) ≤ 1.0 제약
    # ─────────────────────────────────────────────────────────────────
    add("\n" + "=" * 100)
    add("[표 B] LOS E 제약 — W2 평균 (active-only) ≤ 1.0")
    add("=" * 100)
    add("")
    add("설명: W2 평균이 1.0 이하인 cfg 만 후보. 그 중 G/S 각각 최적.")
    add("       평균 기준은 첨두 1분 평균에 가까운 측정 (peak 보다 완화).")
    add("")
    add(f"  {'p':>4} | {'기준 통과 cfg':>20} | "
        f"{'(G) cfg':>7} | {'gate_wait':>9} | {'travel':>7} | {'W2 평균':>7} | "
        f"{'(S) cfg':>7} | {'gate_wait':>9} | {'travel':>7} | {'W2 평균':>7}")
    add(f"  {'-'*4} | {'-'*20} | {'-'*7} | {'-'*9} | {'-'*7} | {'-'*7} | "
        f"{'-'*7} | {'-'*9} | {'-'*7} | {'-'*7}")
    for p_val in p_list:
        cfgs, rg, rs = best_under(p_val, "W2_avg")
        if cfgs is None:
            add(f"  {p_val:>4.1f} | {'없음 (운영 불가)':>20} | " +
                "-".rjust(7) + " | " + "-".rjust(9) + " | " + "-".rjust(7) +
                " | " + "-".rjust(7) + " | " +
                "-".rjust(7) + " | " + "-".rjust(9) + " | " + "-".rjust(7) +
                " | " + "-".rjust(7))
            continue
        cfg_str = ", ".join(f"cfg{c}" for c in cfgs)
        add(f"  {p_val:>4.1f} | {cfg_str:>20s} | "
            f"cfg{int(rg['config']):>4d} | {rg['gate_wait']:>7.1f}s | "
            f"{rg['travel']:>5.1f}s | {rg['W2_avg']:>6.3f} | "
            f"cfg{int(rs['config']):>4d} | {rs['gate_wait']:>7.1f}s | "
            f"{rs['travel']:>5.1f}s | {rs['W2_avg']:>6.3f}")

    # ─────────────────────────────────────────────────────────────────
    # [표 C] W2 peak ≤ 1.0 제약
    # ─────────────────────────────────────────────────────────────────
    add("\n" + "=" * 100)
    add("[표 C] LOS E 제약 — W2 peak ≤ 1.0  (보수적)")
    add("=" * 100)
    add("")
    add("설명: W2 peak 가 1.0 이하인 cfg 만 후보. 순간 최대도 위반 안 되어야 함.")
    add("       보수적 안전 기준 (한 순간이라도 LOS F 진입 금지).")
    add("")
    add(f"  {'p':>4} | {'기준 통과 cfg':>20} | "
        f"{'(G) cfg':>7} | {'gate_wait':>9} | {'travel':>7} | {'W2 peak':>7} | "
        f"{'(S) cfg':>7} | {'gate_wait':>9} | {'travel':>7} | {'W2 peak':>7}")
    add(f"  {'-'*4} | {'-'*20} | {'-'*7} | {'-'*9} | {'-'*7} | {'-'*7} | "
        f"{'-'*7} | {'-'*9} | {'-'*7} | {'-'*7}")
    for p_val in p_list:
        cfgs, rg, rs = best_under(p_val, "W2_pk")
        if cfgs is None:
            add(f"  {p_val:>4.1f} | {'없음 (운영 불가)':>20} | " +
                "-".rjust(7) + " | " + "-".rjust(9) + " | " + "-".rjust(7) +
                " | " + "-".rjust(7) + " | " +
                "-".rjust(7) + " | " + "-".rjust(9) + " | " + "-".rjust(7) +
                " | " + "-".rjust(7))
            continue
        cfg_str = ", ".join(f"cfg{c}" for c in cfgs)
        add(f"  {p_val:>4.1f} | {cfg_str:>20s} | "
            f"cfg{int(rg['config']):>4d} | {rg['gate_wait']:>7.1f}s | "
            f"{rg['travel']:>5.1f}s | {rg['W2_pk']:>6.3f} | "
            f"cfg{int(rs['config']):>4d} | {rs['gate_wait']:>7.1f}s | "
            f"{rs['travel']:>5.1f}s | {rs['W2_pk']:>6.3f}")

    # ─────────────────────────────────────────────────────────────────
    # [표 D] 권고 정리
    # ─────────────────────────────────────────────────────────────────
    add("\n" + "=" * 100)
    add("[표 D] 권고 — 관점 × 제약 조합별 최적 cfg")
    add("=" * 100)
    add("")
    add("설명: 4개 조합의 결론 한눈 정리.")
    add("       (G+평균) = 평균 제약 하 게이트 대기 최소")
    add("       (S+평균) = 평균 제약 하 통행시간 최소")
    add("       (G+peak) = peak 제약 하 게이트 대기 최소")
    add("       (S+peak) = peak 제약 하 통행시간 최소")
    add("")
    add(f"  {'p':>4} | {'(G+평균)':>10} | {'(S+평균)':>10} | "
        f"{'(G+peak)':>10} | {'(S+peak)':>10}")
    add(f"  {'-'*4} | {'-'*10} | {'-'*10} | {'-'*10} | {'-'*10}")
    for p_val in p_list:
        _, rg_a, rs_a = best_under(p_val, "W2_avg")
        _, rg_p, rs_p = best_under(p_val, "W2_pk")
        def f(r):
            return "없음" if r is None else f"cfg{int(r['config'])}"
        add(f"  {p_val:>4.1f} | {f(rg_a):>10s} | {f(rs_a):>10s} | "
            f"{f(rg_p):>10s} | {f(rs_p):>10s}")

    # ─────────────────────────────────────────────────────────────────
    # [표 E] 핵심 인사이트
    # ─────────────────────────────────────────────────────────────────
    add("\n" + "=" * 100)
    add("[표 E] 핵심 인사이트")
    add("=" * 100)
    add("")

    # G vs S 차이 검토
    add("관점 차이 발현 (LOS E 평균 제약 하):")
    diff_count = 0
    for p_val in p_list:
        _, rg, rs = best_under(p_val, "W2_avg")
        if rg is None or rs is None: continue
        if int(rg["config"]) != int(rs["config"]):
            diff = rg["travel"] - rs["travel"]
            add(f"  p={p_val}: G→cfg{int(rg['config'])} (gate {rg['gate_wait']:.1f}s, travel {rg['travel']:.1f}s)")
            add(f"          S→cfg{int(rs['config'])} (gate {rs['gate_wait']:.1f}s, travel {rs['travel']:.1f}s)")
            add(f"          차이 travel +{diff:.1f}s (G가 S보다 길어짐 = 역설)")
            diff_count += 1
    if diff_count == 0:
        add("  모든 p 에서 G와 S 동일 → 통행시간 단독으론 게이트 늘릴수록 유리")

    text = "\n".join(out)
    print(text)
    OUT.write_text(text, encoding="utf-8")
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()
