"""
시나리오 매트릭스 정의 (5 × 4 × 5 = 100 runs).

독립변수:
  - p (태그리스 이용률): 0.1, 0.3, 0.5, 0.7, 0.8
  - config (게이트 배합): 1~4 (태그리스 전용 게이트 수 1~4개)
  - seed: 5개 반복

태그리스 전용 게이트 위치 (v2: 대칭 배합):
  게이트 클러스터 중심은 G4 (idx=3). 중앙 기준 대칭 확장.
    config 1 (1개): {3}            = {G4}       → exit1 전부 (1개는 불가피)
    config 2 (2개): {2, 4}         = {G3, G5}   → exit1:1, exit4:1 (대칭)
    config 3 (3개): {2, 3, 4}      = {G3, G4, G5} → exit1:2, exit4:1 (3개는 불가피)
    config 4 (4개): {1, 2, 4, 5}   = {G2, G3, G5, G6} → exit1:2, exit4:2 (완전 대칭)
  나머지 게이트는 태그 전용 (상호 배타).

열차 스폰:
  - TRAIN_INTERVAL = 150 s
  - TRAIN_ALIGHTING = 200 명
  - SIM_TIME = 300 s → 열차 2편 처리, 생존자 편향 완화
"""

N_GATES = 7

P_LEVELS = [0.1, 0.3, 0.5, 0.7, 0.8]
CONFIG_LEVELS = [1, 2, 3, 4, 5, 6]   # 2026-04-22 확장: cfg5(5개), cfg6(6개)
SEEDS = [42, 43, 44, 45, 46]

# v2: 대칭 배합 (중앙 G4 기준)
# cfg7 = 모든 게이트 태그리스 → 태그 사용자 처리 불가로 제외
TAGLESS_ONLY_BY_CONFIG = {
    1: frozenset({3}),                       # G4
    2: frozenset({2, 4}),                    # G3,G5
    3: frozenset({2, 3, 4}),                 # G3,G4,G5
    4: frozenset({1, 2, 4, 5}),              # G2,G3,G5,G6
    5: frozenset({1, 2, 3, 4, 5}),           # G2~G6 (양 끝 G1,G7만 태그)
    6: frozenset({0, 1, 2, 3, 4, 5}),        # G1~G6 (G7만 태그)
}

# 배치 오버라이드 상수
TRAIN_INTERVAL = 150.0
TRAIN_ALIGHTING = 200
SIM_TIME = 600.0  # 2026-04-24: 300→600s 확장, pass_rate 편향 제거 (2편 완전 처리)


def iter_scenarios():
    """시나리오 100개를 (scenario_id, params_dict) 로 yield."""
    for p in P_LEVELS:
        for cfg in CONFIG_LEVELS:
            for seed in SEEDS:
                scenario_id = f"p{int(p*100):02d}_cfg{cfg}_s{seed}"
                yield scenario_id, {
                    "TAGLESS_RATIO": p,
                    "BATCH_TAGLESS_ONLY_GATES": TAGLESS_ONLY_BY_CONFIG[cfg],
                    "BATCH_SEED": seed,
                    "TRAIN_INTERVAL": TRAIN_INTERVAL,
                    "TRAIN_ALIGHTING": TRAIN_ALIGHTING,
                    "SIM_TIME": SIM_TIME,
                    "_p": p,
                    "_config": cfg,
                    "_seed": seed,
                }


if __name__ == "__main__":
    scenarios = list(iter_scenarios())
    print(f"총 시나리오: {len(scenarios)}")
    print(f"p 수준: {P_LEVELS}")
    print(f"config: {CONFIG_LEVELS}")
    print(f"seeds: {SEEDS}")
    print(f"\nconfig별 태그리스 전용 게이트 (0-indexed):")
    for c, gs in TAGLESS_ONLY_BY_CONFIG.items():
        g1 = sorted(g + 1 for g in gs)  # 1-indexed 표시
        print(f"  config {c}: G{g1} (태그리스 {len(gs)}, 태그 {N_GATES - len(gs)})")
    print(f"\n첫 5개 시나리오:")
    for sid, p in scenarios[:5]:
        print(f"  {sid}: p={p['_p']}, cfg={p['_config']}, seed={p['_seed']}")
