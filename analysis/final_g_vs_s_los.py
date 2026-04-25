"""
G vs S 최적화 cfg → 각각의 LOS → 채택 결정.

흐름:
  1. 각 p 에서 G 최적화 cfg (게이트 대기 최소) 도출
  2. 각 p 에서 S 최적화 cfg (통행시간 최소) 도출
  3. 각 cfg 의 W2 peak 와 LOS 등급 표시
  4. LOS E (≤1.0) 통과 여부 판정
  5. 채택 결정:
     - G와 S 가 같으면 그 cfg 채택
     - G와 S 가 다르면: S 의 LOS 가 통과면 S 채택 (시스템 우선)
                       S 도 위반이면 LOS 통과 cfg 중 travel 최저 채택
"""
from __future__ import annotations
from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from analysis.molit_los import WALKWAY_LOS, grade

DENS = ROOT / "results" / "molit" / "density_union.csv"
OUT = ROOT / "results" / "molit" / "G_VS_S_DECISION.txt"

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
        W2_pk=("W2_peak_density", "mean"),
    ).reset_index()

    out = []
    add = out.append

    add("=" * 100)
    add("G 최적화 cfg vs S 최적화 cfg — LOS 비교 후 채택 결정")
    add("=" * 100)
    add("")
    add("정의:")
    add("  G 최적화 cfg = 평균 게이트 대기시간 최소가 되는 cfg")
    add("  S 최적화 cfg = 평균 통행시간 최소가 되는 cfg")
    add("  채택 기준    = 국토부 LOS E (W2 peak ≤ 1.0)")
    add("")
    add("결정 논리:")
    add("  (a) G와 S 가 같은 cfg → 그 cfg 채택 (단, LOS 통과해야 함)")
    add("  (b) G와 S 가 다른 cfg → S 채택 (시스템 우선), LOS 통과 확인")
    add("  (c) G 또는 S 가 LOS 위반 → LOS 통과 cfg 중 통행시간 최저로 대체")

    p_list = sorted(agg["p"].unique())

    # ── 표 1: G/S cfg 와 각각의 LOS ──
    add("\n" + "=" * 100)
    add("[표 1] p 별 G 최적화 cfg vs S 최적화 cfg — 각각의 LOS")
    add("=" * 100)
    add("")
    add("설명: 제약 없이 G/S 각각의 최적 cfg 도출 후, 그 cfg 의 W2 peak 밀도와 LOS 등급.")
    add("       LOS E (≤1.0) 통과면 'O', 위반(LOS F) 이면 'X'.")
    add("")
    add(f"  {'p':>4} | {'G cfg':>5} | {'G gate_wait':>11} | {'G travel':>9} | "
        f"{'G W2pk':>7} {'LOS':>4} {'OK?':>3} | "
        f"{'S cfg':>5} | {'S gate_wait':>11} | {'S travel':>9} | "
        f"{'S W2pk':>7} {'LOS':>4} {'OK?':>3}")
    add(f"  {'-'*4} | {'-'*5} | {'-'*11} | {'-'*9} | {'-'*7} {'-'*4} {'-'*3} | "
        f"{'-'*5} | {'-'*11} | {'-'*9} | {'-'*7} {'-'*4} {'-'*3}")

    rows = []
    for p_val in p_list:
        sub = agg[agg["p"] == p_val]
        rg = sub.loc[sub["gate_wait"].idxmin()]
        rs = sub.loc[sub["travel"].idxmin()]
        g_ok = "O" if rg["W2_pk"] <= LOS_E_MAX else "X"
        s_ok = "O" if rs["W2_pk"] <= LOS_E_MAX else "X"
        add(f"  {p_val:>4.1f} | cfg{int(rg['config']):>2d} | "
            f"{rg['gate_wait']:>9.1f}s | {rg['travel']:>7.1f}s | "
            f"{rg['W2_pk']:>6.3f}  {los(rg['W2_pk']):>3}   {g_ok:>3} | "
            f"cfg{int(rs['config']):>2d} | "
            f"{rs['gate_wait']:>9.1f}s | {rs['travel']:>7.1f}s | "
            f"{rs['W2_pk']:>6.3f}  {los(rs['W2_pk']):>3}   {s_ok:>3}")
        rows.append({
            "p": p_val,
            "G_cfg": int(rg["config"]), "G_gw": rg["gate_wait"],
            "G_tr": rg["travel"], "G_W2pk": rg["W2_pk"], "G_los": los(rg["W2_pk"]),
            "G_ok": rg["W2_pk"] <= LOS_E_MAX,
            "S_cfg": int(rs["config"]), "S_gw": rs["gate_wait"],
            "S_tr": rs["travel"], "S_W2pk": rs["W2_pk"], "S_los": los(rs["W2_pk"]),
            "S_ok": rs["W2_pk"] <= LOS_E_MAX,
        })

    # ── 표 2: 채택 결정 흐름 ──
    add("\n" + "=" * 100)
    add("[표 2] 채택 결정 흐름 — G/S 의 LOS 보고 어느 cfg 를 채택할지")
    add("=" * 100)
    add("")
    add("설명: 표 1 의 G cfg 와 S cfg 의 LOS 를 보고 채택 결정.")
    add("       G 도 위반, S 도 위반이면 LOS E 통과 cfg 중 통행시간 최저 cfg 로 대체.")
    add("")
    add(f"  {'p':>4} | {'G==S?':>6} | {'결정 논리':>50} | {'채택 cfg':>9}")
    add(f"  {'-'*4} | {'-'*6} | {'-'*50} | {'-'*9}")
    decisions = []
    for r in rows:
        p_val = r["p"]
        g_eq_s = (r["G_cfg"] == r["S_cfg"])
        if g_eq_s and r["S_ok"]:
            chosen = r["S_cfg"]
            logic = f"G와 S 같음(cfg{r['S_cfg']}), 둘 다 LOS 통과 → cfg{r['S_cfg']} 채택"
        elif g_eq_s and not r["S_ok"]:
            # 둘 다 같고 둘 다 위반: LOS 통과 cfg 중 travel 최저 대체
            sub = agg[(agg["p"] == p_val) & (agg["W2_pk"] <= LOS_E_MAX)]
            if len(sub) == 0:
                chosen = None
                logic = f"G/S 같지만(cfg{r['G_cfg']}) LOS 위반, 대체 후보 없음 → 운영 불가"
            else:
                alt = sub.loc[sub["travel"].idxmin()]
                chosen = int(alt["config"])
                logic = (f"G/S 같지만(cfg{r['G_cfg']}) LOS 위반(W2pk={r['S_W2pk']:.2f}=F), "
                         f"통과 cfg 중 travel 최저 = cfg{chosen}")
        else:
            # G ≠ S
            if r["S_ok"]:
                chosen = r["S_cfg"]
                logic = (f"G≠S, S(cfg{r['S_cfg']}) LOS 통과 → 시스템 우선 cfg{r['S_cfg']} 채택"
                         f" (G cfg{r['G_cfg']} 는 W2pk={r['G_W2pk']:.2f})")
            else:
                sub = agg[(agg["p"] == p_val) & (agg["W2_pk"] <= LOS_E_MAX)]
                if len(sub) == 0:
                    chosen = None
                    logic = f"G/S 모두 LOS 위반, 통과 cfg 없음 → 운영 불가"
                else:
                    alt = sub.loc[sub["travel"].idxmin()]
                    chosen = int(alt["config"])
                    logic = (f"G/S 모두 LOS 위반, 통과 cfg 중 travel 최저 = cfg{chosen}")
        chosen_str = f"cfg{chosen}" if chosen else "없음"
        same_str = "예" if g_eq_s else "아니오"
        add(f"  {p_val:>4.1f} | {same_str:>6s} | {logic:>50s} | {chosen_str:>9s}")
        decisions.append((p_val, chosen, logic))

    # ── 표 3: 최종 채택 cfg 와 그 성능 ──
    add("\n" + "=" * 100)
    add("[표 3] 최종 채택 cfg 와 그 성능")
    add("=" * 100)
    add("")
    add(f"  {'p':>4} | {'채택 cfg':>9} | {'gate_wait':>9} | {'travel':>7} | "
        f"{'W2 peak':>8} {'LOS':>4} | 채택 사유")
    add(f"  {'-'*4} | {'-'*9} | {'-'*9} | {'-'*7} | {'-'*8} {'-'*4} | {'-'*40}")
    for p_val, chosen, logic in decisions:
        if chosen is None:
            add(f"  {p_val:>4.1f} | {'없음':>9s} | {'-':>9s} | {'-':>7s} | "
                f"{'-':>8s} {'-':>4} | 운영 불가")
            continue
        r = agg[(agg["p"] == p_val) & (agg["config"] == chosen)].iloc[0]
        # 사유 단순화
        original = next(d for d in rows if d["p"] == p_val)
        if original["G_cfg"] == original["S_cfg"] == chosen and original["S_ok"]:
            sayuyu = "G=S 동일, LOS 통과"
        elif original["S_cfg"] == chosen:
            sayuyu = f"S 채택 (G cfg{original['G_cfg']} 는 LOS 위반)"
        else:
            sayuyu = "G/S 위반, LOS 통과 중 travel 최저 대체"
        add(f"  {p_val:>4.1f} | {'cfg'+str(chosen):>9s} | "
            f"{r['gate_wait']:>7.1f}s | {r['travel']:>5.1f}s | "
            f"{r['W2_pk']:>7.3f}  {los(r['W2_pk']):>3} | {sayuyu}")

    text = "\n".join(out)
    print(text)
    OUT.write_text(text, encoding="utf-8")
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()
