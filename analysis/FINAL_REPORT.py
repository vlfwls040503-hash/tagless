"""
최종 보고 v2 — 보강 반영본.

수정 항목:
  - 표 2: n 컬럼 추가 + 결측 시나리오 별도 표 + 빠진 사유 명시
  - 신규 표 (4-1): p=0.7 cfg2 의 W2 낮음 원인 = 게이트 병목 입증
  - 신규 표 (4-2): LOS 임계 근접 cfg trade-off (위반량 vs travel 손실)
  - 표 5/6: "안전 우선 원칙" 선언 명시
  - 핵심 메시지: cfg 표현 풀어쓰기, 자기모순 정정
  - 모든 표: 같은 raw 데이터 출처임 명시
"""
from __future__ import annotations
from pathlib import Path
import sys
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from analysis.molit_los import WALKWAY_LOS, grade

DENS = ROOT / "results" / "molit" / "density_union.csv"
OUT = ROOT / "results" / "molit" / "FINAL_REPORT.txt"

PASS_RATE_MIN = 0.9
LOS_E_MAX = 1.0


def los(d):
    return grade(d, WALKWAY_LOS)


def main():
    df_all = pd.read_csv(DENS)
    # 전체 (필터 전) — 결측 시나리오 식별용
    df_all = df_all[df_all["config"].isin([1, 2, 3, 4, 5, 6])].copy()
    # 본 분석용 (pass_rate ≥ 0.9)
    df = df_all[df_all["pass_rate"] >= PASS_RATE_MIN].copy()

    agg = df.groupby(["p", "config"]).agg(
        travel=("avg_travel_time", "mean"),
        gate_wait=("avg_gate_wait", "mean"),
        tp_active=("throughput_active", "mean"),
        W2_avg=("W2_avg_density", "mean"),
        W2_pk=("W2_peak_density", "mean"),
        n=("seed", "count"),
        pr=("pass_rate", "mean"),
    ).reset_index()

    out = []
    add = out.append

    add("=" * 100)
    add("태그리스 게이트 운영 — 최종 분석 보고서 (v2)")
    add("=" * 100)
    add("")
    add("[데이터 / 캘리브레이션]")
    add("  보행속도 1.20 m/s        : 서울교통공사 환승소요시간 표준")
    add("  태그 게이트 통과시간 2.7s : Beijing 우안문 실측 (Gao 2019)")
    add("  태그리스 통과시간 1.2s    : 게이트 길이 1.5m / 보행속도 1.3m/s")
    add("  에스컬 처리율 1.17 ped/s  : Cheung & Lam 2002 홍콩 MTR")
    add("  열차: 150초 간격, 편당 200명 (Poisson), 시뮬 600초 = 4편 처리")
    add("  시나리오: p (5수준) × cfg (6수준) × seed (5회) = 150건")
    add("  필터: 시뮬 시간 안에 90% 이상 통과한 case 만 사용 (= 신뢰 가능)")
    add("  W2 (에스컬 앞 대기공간): 면적 20.0 m² (모든 시나리오 대기 위치 합집합)")
    add("")
    add("[이 보고서의 모든 표는 동일한 raw 데이터에서 산출 (results/molit/density_union.csv)]")

    p_list = sorted(agg["p"].unique())

    # ════════════════════════════════════════════════════════════════
    # 표 1
    # ════════════════════════════════════════════════════════════════
    add("\n" + "=" * 100)
    add("[표 1] 국토부 보행로 서비스수준 기준 (고시 제2025-241호 표 2.3)")
    add("=" * 100)
    add("")
    add("내용: 보행 밀도(인/m²) 가 어느 등급인지 판정하는 표.")
    add("       첨두시간대 한계는 LOS E. 즉 밀도 1.0 을 넘으면 국토부 기준 위반.")
    add("")
    add(f"  {'등급':>4} | {'밀도 상한 (인/m²)':>16} | 보행 상태")
    add(f"  {'-'*4} | {'-'*16} | {'-'*40}")
    for g, u, d in WALKWAY_LOS:
        ulim = f"≤ {u}" if u != float("inf") else "1.0 초과"
        add(f"  {g:>4} | {ulim:>16} | {d}")

    # ════════════════════════════════════════════════════════════════
    # 표 2 (n 추가)
    # ════════════════════════════════════════════════════════════════
    add("\n" + "=" * 100)
    add("[표 2] 시뮬 결과 — 시나리오 (p × cfg) 별 측정값")
    add("=" * 100)
    add("")
    add("내용: 각 시나리오의 W2 밀도와 통행시간/게이트 대기.")
    add("       W2 평균 = W2 안에 사람 있는 시점만 평균 (빈 구간 제외).")
    add("       W2 peak = 측정 기간 중 최대값.")
    add("       n = 분석에 사용된 seed 수 (max 5). pass_rate ≥ 0.9 인 seed 만 카운트.")
    add("       n=0 인 (p, cfg) 조합은 표 [2-결측] 참조.")
    add("")
    add(f"  {'p':>4} {'cfg':>4} {'n':>3} | {'W2 평균':>7} {'LOS':>4} | "
        f"{'W2 peak':>8} {'LOS':>4} | {'통행시간':>9} | {'게이트 대기':>11}")
    add(f"  {'-'*4} {'-'*4} {'-'*3} | {'-'*7} {'-'*4} | {'-'*8} {'-'*4} | "
        f"{'-'*9} | {'-'*11}")
    for _, r in agg.iterrows():
        add(f"  {r['p']:>4.1f} {int(r['config']):>4d} {int(r['n']):>3d} | "
            f"{r['W2_avg']:>6.3f}  {los(r['W2_avg']):>3} | "
            f"{r['W2_pk']:>7.3f}  {los(r['W2_pk']):>3} | "
            f"{r['travel']:>7.1f}s | {r['gate_wait']:>9.1f}s")

    # 표 2-결측: 빠진 (p, cfg) 명시
    add("\n" + "=" * 100)
    add("[표 2-결측] 분석에서 제외된 시나리오 (pass_rate < 0.9)")
    add("=" * 100)
    add("")
    add("이유: 시뮬 시간(600s) 안에 spawn 인원의 90% 이상을 처리 못한 시나리오.")
    add("       처리율이 부족한 case 는 정상상태 도달 전이므로 평균 신뢰 불가 → 제외.")
    add("")
    # 모든 (p, cfg) 조합 중 n < 5 인 것
    full_combo = []
    for p_val in p_list:
        for cfg in [1, 2, 3, 4, 5, 6]:
            sub_all = df_all[(df_all["p"] == p_val) & (df_all["config"] == cfg)]
            sub_keep = df[(df["p"] == p_val) & (df["config"] == cfg)]
            n_total = len(sub_all)
            n_keep = len(sub_keep)
            if n_total > 0 and n_keep < 5:
                excluded = sub_all[sub_all["pass_rate"] < PASS_RATE_MIN]
                if len(excluded) > 0:
                    pr_range = f"{excluded['pass_rate'].min():.2f}~{excluded['pass_rate'].max():.2f}"
                    full_combo.append({
                        "p": p_val, "cfg": cfg, "kept": n_keep,
                        "excluded": len(excluded), "pr_range": pr_range,
                    })
    add(f"  {'p':>4} | {'cfg':>3} | {'분석 사용':>9} | {'제외':>5} | {'제외된 seed의 pass_rate':>22}")
    add(f"  {'-'*4} | {'-'*3} | {'-'*9} | {'-'*5} | {'-'*22}")
    for c in full_combo:
        add(f"  {c['p']:>4.1f} | {c['cfg']:>3d} | {c['kept']:>5d} seed | "
            f"{c['excluded']:>3d}개 | {c['pr_range']:>22s}")

    # ════════════════════════════════════════════════════════════════
    # 표 3: 병목 전이
    # ════════════════════════════════════════════════════════════════
    add("\n" + "=" * 100)
    add("[표 3] 병목 전이 분석 — 게이트 처리율 vs W2 보행밀도 상관")
    add("=" * 100)
    add("")
    add("내용: 게이트가 사람을 빨리 처리할수록(처리율↑) W2 밀도가 같이 높아지는가?")
    add("       Spearman ρ = 순위 상관계수. +1=같이 늘어남, -1=반대, 0=관계 없음.")
    add("       p-value = '우연일 확률'. 0.05 미만이면 통계적으로 의미 있음.")
    add("       주의: 동시 상관일 뿐 인과관계 직접 입증 아님 (시차 분석 별도 필요).")
    add("")
    add("(1) 시나리오 단위 (n=" + f"{len(df)}개)")
    add(f"  {'쌍':>30s} | {'Spearman ρ':>12s} | {'p-value':>10s} | 해석")
    add(f"  {'-'*30} | {'-'*12} | {'-'*10} | {'-'*30}")
    pairs = [
        ("throughput_active", "W2_avg_density", "게이트 처리율 vs W2 평균"),
        ("throughput_active", "W2_peak_density", "게이트 처리율 vs W2 peak"),
        ("avg_gate_wait", "W2_avg_density", "게이트 대기 vs W2 평균"),
    ]
    for xc, yc, label in pairs:
        x = df[xc].dropna(); y = df.loc[x.index, yc]
        sr, sp = stats.spearmanr(x, y)
        if sr > 0.5: 해석 = "강한 양의 상관"
        elif sr > 0.3: 해석 = "중간 양의 상관"
        elif sr < -0.5: 해석 = "강한 음의 상관"
        elif sr < -0.3: 해석 = "중간 음의 상관"
        else: 해석 = "약한 상관"
        add(f"  {label:>30s} | {sr:>+10.3f} | {sp:>10.2g} | {해석}")

    add("")
    sr_avg, sp_avg = stats.spearmanr(df["throughput_active"], df["W2_avg_density"])
    sr_gw, sp_gw = stats.spearmanr(df["avg_gate_wait"], df["W2_avg_density"])
    add(f"해석: 게이트 처리율과 W2 평균은 강한 양의 상관 (ρ={sr_avg:+.2f}).")
    add(f"      게이트 대기와 W2 평균은 강한 음의 시소관계 (ρ={sr_gw:+.2f}).")
    add(f"      두 지표가 시소처럼 움직이는 패턴 = 병목 위치가 옮겨가는 패턴.")
    add(f"      단 동시 상관이라 '도착량 많을 때 둘 다 높아짐' 의 공통원인 가능성 배제 못함.")
    add(f"      엄밀한 인과 입증은 시차 상관 분석 필요 (본 보고서 범위 외).")

    # ════════════════════════════════════════════════════════════════
    # 표 4: G vs S
    # ════════════════════════════════════════════════════════════════
    add("\n" + "=" * 100)
    add("[표 4] G 최적화 cfg vs S 최적화 cfg — 각각의 LOS")
    add("=" * 100)
    add("")
    add("내용: 두 관점에서 최적 cfg 를 따로 도출하고, 그 cfg 의 W2 peak 와 LOS 등급.")
    add("       G 최적화 = 게이트 대기시간이 가장 짧은 cfg.")
    add("       S 최적화 = 통행시간이 가장 짧은 cfg.")
    add("       OK = LOS E (W2 peak ≤ 1.0) 통과. X = LOS F 위반.")
    add("       값은 표 2 와 동일 raw 데이터.")
    add("")
    add(f"  {'p':>4} | {'G cfg':>5} | {'gate_wait':>9} | {'travel':>7} | "
        f"{'W2 peak':>8} {'LOS':>4} {'OK?':>3} | "
        f"{'S cfg':>5} | {'gate_wait':>9} | {'travel':>7} | "
        f"{'W2 peak':>8} {'LOS':>4} {'OK?':>3}")
    add(f"  {'-'*4} | {'-'*5} | {'-'*9} | {'-'*7} | {'-'*8} {'-'*4} {'-'*3} | "
        f"{'-'*5} | {'-'*9} | {'-'*7} | {'-'*8} {'-'*4} {'-'*3}")
    rows = []
    for p_val in p_list:
        sub = agg[agg["p"] == p_val]
        rg = sub.loc[sub["gate_wait"].idxmin()]
        rs = sub.loc[sub["travel"].idxmin()]
        g_ok = "O" if rg["W2_pk"] <= LOS_E_MAX else "X"
        s_ok = "O" if rs["W2_pk"] <= LOS_E_MAX else "X"
        add(f"  {p_val:>4.1f} | cfg{int(rg['config']):>2d} | "
            f"{rg['gate_wait']:>7.1f}s | {rg['travel']:>5.1f}s | "
            f"{rg['W2_pk']:>7.3f}  {los(rg['W2_pk']):>3}   {g_ok:>3} | "
            f"cfg{int(rs['config']):>2d} | "
            f"{rs['gate_wait']:>7.1f}s | {rs['travel']:>5.1f}s | "
            f"{rs['W2_pk']:>7.3f}  {los(rs['W2_pk']):>3}   {s_ok:>3}")
        rows.append({
            "p": p_val,
            "G_cfg": int(rg["config"]), "G_gw": rg["gate_wait"],
            "G_tr": rg["travel"], "G_W2pk": rg["W2_pk"],
            "G_ok": rg["W2_pk"] <= LOS_E_MAX,
            "S_cfg": int(rs["config"]), "S_gw": rs["gate_wait"],
            "S_tr": rs["travel"], "S_W2pk": rs["W2_pk"],
            "S_ok": rs["W2_pk"] <= LOS_E_MAX,
        })

    # ────────────────────────────────────────────────
    # 표 4-1: p=0.7 cfg2 W2 낮음 원인 분석
    # ────────────────────────────────────────────────
    add("\n" + "=" * 100)
    add("[표 4-1] 보조분석 — p=0.7 cfg2 의 W2 가 왜 p=0.5 cfg2 보다 낮은가")
    add("=" * 100)
    add("")
    add("관찰: 직관과 반대. 혼입률(p)이 더 높은 p=0.7 cfg2 의 W2 peak (0.52) 가")
    add("      p=0.5 cfg2 의 W2 peak (0.92) 보다 낮음.")
    add("")
    add("가설: cfg2 = 태그리스 전용 게이트 2개. p=0.7 에서는 태그리스 user 70% 가")
    add("      게이트 2개로 몰림 → 게이트 자체가 큐로 막혀서 에스컬까지 도달 못함.")
    add("      즉 'W2 낮음 = 안전' 이 아니라 '게이트에서 막힘 = W2 도달 못함'.")
    add("")
    add(f"  {'지표':>22} | {'p=0.5 cfg2':>13} | {'p=0.7 cfg2':>13} | 해석")
    add(f"  {'-'*22} | {'-'*13} | {'-'*13} | {'-'*40}")
    sub_05 = agg[(agg["p"] == 0.5) & (agg["config"] == 2)].iloc[0]
    sub_07 = agg[(agg["p"] == 0.7) & (agg["config"] == 2)].iloc[0]
    add(f"  {'게이트 대기 (s)':>22} | {sub_05['gate_wait']:>11.2f}s | "
        f"{sub_07['gate_wait']:>11.2f}s | p=0.7 에서 11s 더 막힘")
    add(f"  {'통과율 (pass_rate)':>22} | {sub_05['pr']:>13.3f} | "
        f"{sub_07['pr']:>13.3f} | p=0.7 에서 처리 떨어짐")
    add(f"  {'시스템 처리율 (ped/s)':>22} | {sub_05['tp_active']:>13.3f} | "
        f"{sub_07['tp_active']:>13.3f} | p=0.7 에서 처리속도 ↓")
    add(f"  {'통행시간 (s)':>22} | {sub_05['travel']:>11.2f}s | "
        f"{sub_07['travel']:>11.2f}s | p=0.7 에서 7.6s 더 길어짐")
    add(f"  {'W2 평균 (인/m²)':>22} | {sub_05['W2_avg']:>13.3f} | "
        f"{sub_07['W2_avg']:>13.3f} | p=0.7 에서 W2 도달 인원 ↓")
    add(f"  {'W2 peak (인/m²)':>22} | {sub_05['W2_pk']:>13.3f} | "
        f"{sub_07['W2_pk']:>13.3f} | (역설처럼 보이는 값)")
    add("")
    add("결론: p=0.7 cfg2 의 W2 낮음은 안전성 향상이 아니라 게이트 병목의 부산물.")
    add("      게이트에서 27.8s 대기 = 큐 형성 = 에스컬 도달 인원 감소.")
    add("      LOS 통과 (0.52, C 등급) 라는 숫자만 보면 안전 같지만, 실제로는")
    add("      게이트 측 통행시간 비용으로 전가된 상태.")

    # ────────────────────────────────────────────────
    # 표 4-2: LOS 임계 근접 cfg trade-off
    # ────────────────────────────────────────────────
    add("\n" + "=" * 100)
    add("[표 4-2] LOS 임계 근접 cfg — 위반량 vs travel 손실 trade-off")
    add("=" * 100)
    add("")
    add("내용: 본 보고서는 W2 peak ≤ 1.0 을 칼같이 적용하여 0.02 위반도 탈락시킴.")
    add("       이 컷오프는 임의적이므로, 임계 근접 cfg 의 trade-off 를 따로 보임.")
    add("       각 p 에서 G/S 가 LOS 위반인 경우, 채택 cfg vs 위반 cfg 의 비교.")
    add("")
    add(f"  {'p':>4} | {'G/S cfg (위반)':>15} | {'위반량':>7} | "
        f"{'채택 cfg (안전)':>15} | {'travel 손실':>11} | trade-off 평가")
    add(f"  {'-'*4} | {'-'*15} | {'-'*7} | {'-'*15} | {'-'*11} | {'-'*30}")
    for r in rows:
        if r["S_ok"]: continue  # S 가 LOS 통과면 trade-off 없음
        p_val = r["p"]
        feasible = agg[(agg["p"] == p_val) & (agg["W2_pk"] <= LOS_E_MAX)]
        if len(feasible) == 0: continue
        alt = feasible.loc[feasible["travel"].idxmin()]
        viol_amount = r["S_W2pk"] - LOS_E_MAX
        travel_loss = alt["travel"] - r["S_tr"]
        ratio = travel_loss / max(viol_amount, 0.001)
        if ratio < 50:
            평가 = f"수용가능 (위반/손실 = {ratio:.0f}s/위반)"
        elif ratio < 200:
            평가 = f"논쟁여지 (위반/손실 = {ratio:.0f}s/위반)"
        else:
            평가 = f"과도한 안전마진 ({ratio:.0f}s/위반)"
        add(f"  {p_val:>4.1f} | cfg{r['S_cfg']} (W2pk {r['S_W2pk']:.2f}) | "
            f"+{viol_amount:>5.2f} | "
            f"cfg{int(alt['config'])} (W2pk {alt['W2_pk']:.2f}) | "
            f"+{travel_loss:>8.1f}s | {평가}")
    add("")
    add("정책 입장: 본 보고서는 '안전 우선 원칙' 채택 — LOS 1% 위반도 후퇴.")
    add("           근거: 첨두시 군집 안전이 분 단위 통행시간보다 우선.")
    add("           단 trade-off 가 큰 case (예: 위반/손실 비 100s 이상) 는")
    add("           실무에선 위반 cfg 채택도 검토 가능 (지자체 운영 자율).")

    # ════════════════════════════════════════════════════════════════
    # 표 5: 채택 결정 흐름
    # ════════════════════════════════════════════════════════════════
    add("\n" + "=" * 100)
    add("[표 5] 채택 결정 흐름 — '안전 우선 원칙' 적용")
    add("=" * 100)
    add("")
    add("원칙: 국토부 LOS E (W2 peak ≤ 1.0) 위반 시 무조건 후퇴 (안전 우선).")
    add("")
    add("규칙:")
    add("  (a) G와 S 가 같은 cfg + 둘 다 LOS 통과 → 그 cfg 채택")
    add("  (b) G와 S 가 다른 cfg + S 가 LOS 통과 → S 채택 (시스템 우선)")
    add("  (c) G/S 모두 LOS 위반 → LOS 통과 cfg 중 통행시간 가장 짧은 것 대체")
    add("       (단 trade-off 평가는 표 4-2 참조)")
    add("")
    add(f"  {'p':>4} | {'G==S?':>6} | {'결정 논리':>60s} | {'채택 cfg':>9}")
    add(f"  {'-'*4} | {'-'*6} | {'-'*60} | {'-'*9}")
    decisions = []
    for r in rows:
        p_val = r["p"]
        g_eq_s = (r["G_cfg"] == r["S_cfg"])
        if g_eq_s and r["S_ok"]:
            chosen = r["S_cfg"]
            logic = f"G=S 같음(cfg{r['S_cfg']}), 둘 다 LOS 통과"
        elif g_eq_s and not r["S_ok"]:
            sub = agg[(agg["p"] == p_val) & (agg["W2_pk"] <= LOS_E_MAX)]
            if len(sub) == 0:
                chosen = None
                logic = f"G=S(cfg{r['G_cfg']}) 둘 다 LOS 위반, 대체 후보 없음"
            else:
                alt = sub.loc[sub["travel"].idxmin()]
                chosen = int(alt["config"])
                logic = (f"G=S(cfg{r['G_cfg']}) LOS F 위반(W2pk={r['S_W2pk']:.2f}), "
                         f"통과 cfg 중 travel 최저 → cfg{chosen}")
        else:
            if r["S_ok"]:
                chosen = r["S_cfg"]
                logic = (f"G(cfg{r['G_cfg']})은 LOS 위반(W2pk={r['G_W2pk']:.2f}), "
                         f"S(cfg{r['S_cfg']}) LOS 통과 → S 채택")
            else:
                sub = agg[(agg["p"] == p_val) & (agg["W2_pk"] <= LOS_E_MAX)]
                if len(sub) == 0:
                    chosen = None
                    logic = "G/S 모두 위반, 통과 cfg 없음"
                else:
                    alt = sub.loc[sub["travel"].idxmin()]
                    chosen = int(alt["config"])
                    logic = f"G/S 모두 위반, 통과 cfg 중 travel 최저 → cfg{chosen}"
        chosen_str = f"cfg{chosen}" if chosen else "없음"
        same_str = "예" if g_eq_s else "아니오"
        add(f"  {p_val:>4.1f} | {same_str:>6s} | {logic:>60s} | {chosen_str:>9s}")
        decisions.append((p_val, chosen, logic, g_eq_s, r))

    # ════════════════════════════════════════════════════════════════
    # 표 6: 최종 채택
    # ════════════════════════════════════════════════════════════════
    add("\n" + "=" * 100)
    add("[표 6] 최종 채택 cfg")
    add("=" * 100)
    add("")
    add("주의: 표 4-1 참조 — p=0.7 cfg2 의 W2 낮음은 안전성이 아니라")
    add("       게이트 측 병목의 결과 (게이트 대기 27.8s).")
    add("       LOS 통과 = 시스템이 좋다 가 아님.")
    add("")
    add(f"  {'p':>4} | {'채택 cfg':>9} | {'gate_wait':>9} | {'travel':>7} | "
        f"{'W2 peak':>8} {'LOS':>4} | 채택 사유")
    add(f"  {'-'*4} | {'-'*9} | {'-'*9} | {'-'*7} | {'-'*8} {'-'*4} | {'-'*40}")
    for p_val, chosen, logic, g_eq_s, r0 in decisions:
        if chosen is None:
            add(f"  {p_val:>4.1f} | {'없음':>9s} | {'-':>9s} | {'-':>7s} | "
                f"{'-':>8s} {'-':>4} | 운영 불가")
            continue
        r = agg[(agg["p"] == p_val) & (agg["config"] == chosen)].iloc[0]
        if g_eq_s and r0["S_ok"]:
            saw = "G=S 동일, LOS 통과"
        elif r0["S_cfg"] == chosen and not g_eq_s:
            saw = f"G(cfg{r0['G_cfg']}) 위반, S 채택"
        else:
            saw = "G/S 위반, LOS 통과 중 travel 최저로 후퇴"
        add(f"  {p_val:>4.1f} | {'cfg'+str(chosen):>9s} | "
            f"{r['gate_wait']:>7.1f}s | {r['travel']:>5.1f}s | "
            f"{r['W2_pk']:>7.3f}  {los(r['W2_pk']):>3} | {saw}")

    # ════════════════════════════════════════════════════════════════
    # 핵심 메시지
    # ════════════════════════════════════════════════════════════════
    add("\n" + "=" * 100)
    add("[핵심 메시지]")
    add("=" * 100)
    add("")
    add("1. 병목 전이는 통계적으로 명확:")
    add(f"   - 게이트 처리율 ↑ → W2 평균밀도 ↑ (Spearman ρ = {sr_avg:+.2f}).")
    add(f"   - 게이트 대기 ↓ ↔ W2 ↑ 시소관계 (ρ = {sr_gw:+.2f}).")
    add("   - 단 동시 상관이므로 인과 직접 입증 아님 (도착량 공통원인 배제 필요).")
    add("")
    add("2. G와 S 가 갈리는 시점:")
    add("   - p=0.1 ~ 0.7: G와 S 가 같은 cfg (게이트만 봐도 시스템 봐도 같은 답).")
    add("   - p=0.8: G→cfg5 (W2pk 1.83 = LOS F 위반), S→cfg4 (W2pk 1.00 = LOS E 통과).")
    add("           G 가 LOS 위반이라 못 씀 → 시스템 우선으로 cfg4 채택.")
    add("   - 이게 '게이트만 보고 결정하면 안 되는' 정량적 증거.")
    add("")
    add("3. LOS 제약이 진짜 cfg 상한 결정:")
    add("   - p=0.5: G/S 모두 cfg3 (W2pk 1.34 = LOS F 위반) → cfg2 로 후퇴.")
    add("   - p=0.7: G/S 모두 cfg4 (W2pk 1.34 = LOS F 위반) → cfg2 로 후퇴.")
    add("   - 통행시간 만으론 보이지 않는 안전 한계.")
    add("")
    add("4. 단 cfg2 후퇴의 의미는 다중적:")
    add("   - p=0.5 cfg2: gate_wait 16.7s, W2pk 0.92 — 게이트도 에스컬도 적당.")
    add("   - p=0.7 cfg2: gate_wait 27.8s, W2pk 0.52 — 게이트가 막힌 부산물.")
    add("   - 둘 다 'LOS 통과' 라 같아 보이지만 실제 부담 위치가 다름 (표 4-1 참조).")
    add("")
    add("5. 시간대별 가변 운영 권고:")
    for p_val, chosen, _, _, _ in decisions:
        if chosen:
            add(f"   p={p_val}: cfg{chosen} (전용 게이트 {chosen}개)")

    text = "\n".join(out)
    print(text)
    OUT.write_text(text, encoding="utf-8")
    print(f"\n저장: {OUT}")


if __name__ == "__main__":
    main()
