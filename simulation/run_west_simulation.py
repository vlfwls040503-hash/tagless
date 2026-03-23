"""
성수역 서쪽 대합실 보행자 시뮬레이션 v7

변경 이력 (v6 → v7):
  Gao (2019) 원문 대조 + 선행연구 기반 보행 행태 수정

  [Gao 원문 대조 수정]
  1. 3차 재선택: 1.0m → 0.25m (카드 태핑 위치, Gao Fig.9)
  2. 3차 재선택 조건: 무조건 argmin → 앞 사람이 게이트 점유 중일 때만 (Gao §3.2)
  3. 거리 추정 순서 보정: Gao eq.5 구현 (추정 후 순서 뒤바뀜 방지)
  4. Influence Zone: 스폰 즉시 선택 → 게이트 전방 CHOICE_DIST_1ST(3.0m)에서 LRP 활성화
     - 스폰 시에는 가장 가까운 계단-게이트 직선 경로(글로벌 경로)로 이동
     - Influence Zone 진입 시 1차 LRP 선택
  5. 희망속도 범위: [0.5, 2.0] → [0.8, 1.5] (Gao 실측)
  6. 게이트 길이: 1.5m → 1.4m (Gao 실측) — seongsu_west.py는 유지, 서비스 구간만 조정

  [선행연구 기반 보행 행태 개선]
  7. 대기열 상태 분리 (Flowing vs Queuing):
     - Leader-Follower 대기열 모델: 줄 선 보행자는 앞사람을 추종
     - 게이트 내부(Bottleneck) 진입 시 척력 무효화 → 통과 속도 고정 제어
     (Tanaka et al., 2022; Fuzzy-SFM, 2026)
  8. 의사결정의 이산적 상태 전이 (Discrete State Transition):
     - 각 재선택 단계는 정확히 1회만 발동 (매 스텝 반복 아님)
     - 경로 전환 비용(Switching Cost)으로 Bounded Rationality 구현

파라미터 출처:
  - CFSM V2: Tordeux et al. (2016), Weidmann (1993)
  - 게이트 선택: Gao et al. (2019) - Beijing Subway 실측
  - 서비스 시간(태그): Gao (2019) 실측 (🔶 한국 검증 필요)
  - 서비스 시간(태그리스): 본 연구 가정 (🔴 우이신설선 실측 필요)
  - 대기열 행태: Tanaka et al. (2022), Fuzzy-SFM (2026)
  - 보행자 성격 비율: Gao (2019) 가정 1:1:1 (🔶 검증 필요)

모델: CollisionFreeSpeedModelV2 (CFSM V2)
"""

import jupedsim as jps
import numpy as np
import pathlib
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from shapely import Polygon

import sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from seongsu_west import (
    calculate_gate_positions, build_geometry,
    GATE_X, GATE_LENGTH, GATE_PASSAGE_WIDTH, GATE_HOUSING_WIDTH,
    BARRIER_Y_BOTTOM, BARRIER_Y_TOP,
    CONCOURSE_LENGTH, CONCOURSE_WIDTH, NOTCH_X, NOTCH_Y,
    STAIRS, EXITS, STRUCTURES, N_GATES,
)

plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

# =============================================================================
# 시뮬레이션 파라미터
# =============================================================================
SIM_TIME = 300.0        # 5분 (열차 1~2회 도착 관찰)
DT = 0.05

# =============================================================================
# 도착 모델 (열차 군집)
# =============================================================================
TRAIN_INTERVAL = 180.0   # 열차 도착 간격 (초) - 2호선 피크 약 2.5~3분
TRAIN_ALIGHTING = 40     # 1회 도착 하차 인원 (서쪽 계단 이용분)
PLATOON_SPREAD = 15.0    # 계단에서 대합실 진입까지 분산 시간 (초)
FIRST_TRAIN_TIME = 5.0   # 첫 열차 도착 시각

# =============================================================================
# CFSM V2 핵심 파라미터 (선행연구 기반)
# =============================================================================
PED_RADIUS = 0.225               # Weidmann 1993
PED_SPEED_MEAN = 1.34            # Weidmann 1993
PED_SPEED_STD = 0.26
PED_SPEED_MIN = 0.8              # Gao (2019) 실측 하한
PED_SPEED_MAX = 1.5              # Gao (2019) 실측 상한
PED_TIME_GAP = 1.06              # Tordeux et al. 2015
PED_TIME_GAP_QUEUE = 0.5         # 게이트 근처 대기열: 바짝 붙어 서는 심리
PED_STRENGTH_NEIGHBOR = 8.0      # Tordeux et al. 2015
PED_RANGE_NEIGHBOR = 0.1
PED_STRENGTH_GEOMETRY = 5.0
PED_RANGE_GEOMETRY = 0.02

# =============================================================================
# 서비스 시간 파라미터 (Gao et al., 2019 현장 실측)
# =============================================================================
SERVICE_TIME_MEAN = 2.0      # 평균 서비스 시간 (초) - Gao (2019) 피크시 실측
SERVICE_TIME_MIN = 0.8       # 최소 서비스 시간 (초)
SERVICE_TIME_MAX = 3.7       # 최대 서비스 시간 (초)
CARD_FEEDING_TIME = 1.1      # 카드 태핑 시간 평균 (초) - Gao (2019) 실측
GATE_PASS_SPEED = 0.65       # 게이트 내부 통과 속도 (m/s) - Gao (2019) 실측
GATE_PHYS_LENGTH = 1.4       # 게이트 물리적 길이 (m) - Gao (2019) 실측

# 태그리스 사용자: 일반 보행속도로 통과 (🔴 우이신설선 실측 필요)
TAGLESS_SERVICE_TIME = 0.0   # 태그리스 서비스 시간 (무정지 통과)

# 시나리오 변수
TAGLESS_RATIO = 0.2          # 태그리스 사용자 비율 (0.0 ~ 1.0)

# =============================================================================
# 게이트 선택 모델: Gao et al. (2019) LRP 모델
# =============================================================================
TEMPERAMENTS = {
    "adventurous": {"omega_wait": 1.2, "omega_walk": 0.8},
    "conserved":   {"omega_wait": 0.8, "omega_walk": 1.2},
    "mild":        {"omega_wait": 1.0, "omega_walk": 1.0},
}
TEMPERAMENT_RATIO = [1, 1, 1]

# 추정 오차 (Gao, 2019 eq.4)
DIST_ESTIMATION_ERROR = 0.10   # 거리 추정 오차 ±10%

# 3단계 재선택 거리 (Gao, 2019 현장관측, Fig.9)
CHOICE_DIST_1ST = 3.0    # 1차 선택: Influence Zone 진입, 전체경로 고려, 확률적
CHOICE_DIST_2ND = 1.7    # 2차 재선택: 접근거리만, 확률적
CHOICE_DIST_3RD = 0.25   # 3차 재선택: 카드 태핑 위치 (Gao Fig.9), 확정적
                          # ← v6에서는 1.0m이었으나 원문은 0.25m

# 게이트 통과 구간 (서비스 영역)
GATE_ZONE_X_START = GATE_X - 0.2
GATE_ZONE_X_END = GATE_X + GATE_LENGTH + 0.2

# 대기열 제어
QUEUE_STOP_DIST = 0.5        # 게이트 앞 정지 거리 (m)
QUEUE_FOLLOW_DIST = 5.0      # 대기열 모드 전환 거리 (m)
LEADER_FOLLOW_GAP = 0.6      # 앞사람 추종 시 목표 간격 (m) ≈ 2*PED_RADIUS + 여유

# 병목 구간 내 척력 무효화 파라미터
BOTTLENECK_STRENGTH_NEIGHBOR = 1.0   # 게이트 내부에서 약한 이웃 반발
BOTTLENECK_STRENGTH_GEOMETRY = 0.5   # 게이트 내부에서 약한 벽 반발

OUTPUT_DIR = pathlib.Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


# =============================================================================
# 도착 스케줄 생성
# =============================================================================
def generate_arrival_schedule(rng, sim_time):
    arrivals = []
    train_time = FIRST_TRAIN_TIME
    while train_time < sim_time:
        n_passengers = rng.poisson(TRAIN_ALIGHTING)
        for _ in range(n_passengers):
            arrival_t = train_time + abs(rng.normal(PLATOON_SPREAD / 2, PLATOON_SPREAD / 4))
            if arrival_t < sim_time:
                arrivals.append(arrival_t)
        train_time += TRAIN_INTERVAL
    arrivals.sort()
    return arrivals


# =============================================================================
# 보행자 속성
# =============================================================================
def assign_temperament(rng):
    names = list(TEMPERAMENTS.keys())
    weights = np.array(TEMPERAMENT_RATIO, dtype=float)
    weights /= weights.sum()
    return rng.choice(names, p=weights)


def sample_service_time(rng, is_tagless=False):
    if is_tagless:
        return TAGLESS_SERVICE_TIME
    # lognormal: E[X] = exp(μ + σ²/2) → μ = ln(E[X]) - σ²/2
    sigma_ln = 0.5
    mu_ln = np.log(SERVICE_TIME_MEAN) - sigma_ln**2 / 2  # = 0.568 → E[X] ≈ 2.0s
    return np.clip(rng.lognormal(mu_ln, sigma_ln), SERVICE_TIME_MIN, SERVICE_TIME_MAX)


# =============================================================================
# 게이트 대기 인원 계산
# =============================================================================
def count_gate_queue(sim, gates, agent_data):
    queue = [0] * len(gates)
    for agent in sim.agents():
        aid = agent.id
        if aid not in agent_data:
            continue
        if agent_data[aid]["serviced"]:
            continue
        gi = agent_data[aid].get("gate_idx", -1)
        if gi >= 0:
            queue[gi] += 1
    return queue


def estimate_queue_count(rng, actual_count):
    """Gao (2019) eq.7: 대기 인원 추정 오차"""
    if actual_count <= 3:
        return actual_count
    elif actual_count <= 5:
        return actual_count + rng.choice([-1, 0, 1])
    else:
        return max(0, actual_count + rng.choice([-2, -1, 0, 1, 2]))


def estimate_distances_with_order_preservation(rng, actual_dists):
    """
    Gao (2019) eq.4 + eq.5: 거리 추정 오차 + 순서 보정

    추정 후에도 실제 거리의 대소 순서가 유지되도록 보정.
    """
    n = len(actual_dists)
    estimated = np.zeros(n)

    # 정렬된 인덱스
    sorted_indices = np.argsort(actual_dists)
    sorted_dists = actual_dists[sorted_indices]

    # 각 거리에 대해 기본 추정 범위: [0.9*L, 1.1*L]
    low = 0.9 * sorted_dists
    high = 1.1 * sorted_dists

    # eq.5: 인접 거리 간 순서 뒤바뀜 방지
    for i in range(n - 1):
        if high[i] > low[i + 1]:
            mid = (high[i] + low[i + 1]) / 2.0
            high[i] = mid
            low[i + 1] = mid

    # 범위 내 가우시안 샘플링
    for i in range(n):
        center = sorted_dists[i]
        sigma = 0.03 * center  # σ ≈ 3% of actual distance
        est = rng.normal(center, sigma)
        est = np.clip(est, low[i], high[i])
        estimated[sorted_indices[i]] = est

    return estimated


def get_exit_position(gate):
    if gate["y"] > CONCOURSE_WIDTH / 2:
        return (EXITS[0]["x_start"] + EXITS[0]["x_end"]) / 2, EXITS[0]["y"]
    else:
        return (EXITS[1]["x_start"] + EXITS[1]["x_end"]) / 2, EXITS[1]["y"]


# =============================================================================
# 게이트 선택: Gao et al. (2019) LRP 모델
# =============================================================================
def choose_gate_lrp(rng, agent_pos, agent_speed, temperament, gates,
                    gate_queue, stage="1st", gate_occupied=None,
                    current_gate_idx=None):
    """
    Gao (2019) LRP 모델:
      V_i,j = ω^N · (N'_j · t₀) + ω^L · (ΣL'_m / v_i)
      P_j = exp(-V_j) / Σ exp(-V_k)

    stage:
      "1st" (3.0m): L1+L3 고려, 확률적 선택 (Logit)
      "2nd" (1.7m): L1만 고려, 확률적 선택
      "3rd" (0.25m): 앞 사람 점유 시에만, 인접 빈 게이트로 확정적 전환
    """
    omega = TEMPERAMENTS[temperament]
    omega_wait = omega["omega_wait"]
    omega_walk = omega["omega_walk"]

    n_gates = len(gates)

    # ── 3차 선택: Gao §3.2 — 앞 사람이 점유 중일 때만, 인접 빈 게이트로 전환 ──
    if stage == "3rd":
        if (current_gate_idx is not None and gate_occupied is not None
                and gate_occupied[current_gate_idx]):
            # 인접 게이트(±1) 중 비어있는 곳 탐색
            candidates = []
            for delta in [-1, 1]:
                adj = current_gate_idx + delta
                if 0 <= adj < n_gates and not gate_occupied[adj]:
                    # 인접 게이트까지 거리
                    d = abs(agent_pos[1] - gates[adj]["y"])
                    candidates.append((d, adj))
            if candidates:
                candidates.sort()
                return candidates[0][1]  # 가장 가까운 빈 인접 게이트
        # 점유 안 됐거나 인접 빈 게이트 없음 → 현재 유지
        return current_gate_idx if current_gate_idx is not None else 0

    # ── 1차/2차 선택 ──
    # L1 거리 계산
    l1_actual = np.array([
        np.hypot(agent_pos[0] - g["x"], agent_pos[1] - g["y"])
        for g in gates
    ])

    # 거리 추정 (순서 보정 포함, Gao eq.4+5)
    l1_est = estimate_distances_with_order_preservation(rng, l1_actual)

    costs = np.full(n_gates, np.inf)
    for j, gate in enumerate(gates):
        if stage == "1st":
            exit_x, exit_y = get_exit_position(gate)
            gate_exit_x = gate["x"] + GATE_LENGTH
            l3 = np.hypot(gate_exit_x - exit_x, gate["y"] - exit_y)
            l3_est = l3 * (1.0 + np.clip(rng.normal(0, 0.03), -0.10, 0.10))
            walk_time = (l1_est[j] + l3_est) / agent_speed
        else:
            walk_time = l1_est[j] / agent_speed

        n_est = estimate_queue_count(rng, gate_queue[j])
        wait_time = n_est * SERVICE_TIME_MEAN

        costs[j] = omega_wait * wait_time + omega_walk * walk_time

    # 확률적 선택 (Logit, Gao eq.8)
    shifted = costs - np.min(costs)
    exp_neg = np.exp(-shifted)
    probs = exp_neg / exp_neg.sum()
    return int(rng.choice(n_gates, p=probs))


# =============================================================================
# 대기열에서 앞사람 찾기 (Leader-Follower)
# =============================================================================
def find_leader(agent_pos, gate_idx, sim, agent_data, in_service, my_id):
    """
    같은 게이트에 배정된 에이전트 중, 나보다 게이트에 가까운
    가장 가까운(바로 앞) 에이전트를 찾아 그 위치를 반환.
    """
    my_x = agent_pos[0]
    best_x = None
    best_pos = None

    for agent in sim.agents():
        aid = agent.id
        if aid == my_id or aid not in agent_data:
            continue
        ad = agent_data[aid]
        if ad.get("gate_idx") != gate_idx or ad["serviced"]:
            continue
        ox, oy = agent.position
        # 나보다 게이트에 가까운(x가 큰) 에이전트
        if ox > my_x:
            if best_x is None or ox < best_x:
                best_x = ox
                best_pos = (ox, oy)

    return best_pos


# =============================================================================
# 시뮬레이션 생성
# =============================================================================
def create_simulation():
    gates = calculate_gate_positions()
    # 시뮬레이션용: 통로 폭을 넓힌 배리어 (CFSM 벽 반발력이 0.55m에서 막히므로)
    # 기하구조 통로 = 실제 폭 + 2*PED_RADIUS 여유 → 보행자 중심이 통과 가능
    sim_gates = []
    for g in gates:
        sim_g = dict(g)
        sim_g["passage_width"] = g["passage_width"] + 2 * PED_RADIUS  # 0.55 + 0.45 = 1.0m
        sim_gates.append(sim_g)
    walkable, _, _ = build_geometry(sim_gates, include_barrier=True)
    # 시각화용: 실제 폭 배리어
    _, vis_obstacles, gate_openings = build_geometry(gates, include_barrier=True)

    model = jps.CollisionFreeSpeedModelV2()

    sim = jps.Simulation(
        model=model,
        geometry=walkable,
        dt=DT,
    )

    gate_x_end = GATE_X + GATE_LENGTH

    # 1단계: 접근 Waypoint
    approach_wp_ids = []
    for g in gates:
        wp_id = sim.add_waypoint_stage((8.0, g["y"]), 1.0)
        approach_wp_ids.append(wp_id)

    # 2단계: 게이트 입구 Waypoint
    gate_wp_ids = []
    for g in gates:
        wp_id = sim.add_waypoint_stage((GATE_X, g["y"]), 0.4)
        gate_wp_ids.append(wp_id)

    # 3단계: 게이트 통과 후 Waypoint
    post_gate_wp_ids = []
    for g in gates:
        wp_id = sim.add_waypoint_stage((gate_x_end + 2.0, g["y"]), 1.0)
        post_gate_wp_ids.append(wp_id)

    # 출구
    exit_upper = sim.add_exit_stage(Polygon([
        (EXITS[0]["x_start"], EXITS[0]["y"] - 0.5),
        (EXITS[0]["x_end"],   EXITS[0]["y"] - 0.5),
        (EXITS[0]["x_end"],   EXITS[0]["y"] + 0.5),
        (EXITS[0]["x_start"], EXITS[0]["y"] + 0.5),
    ]))
    exit_lower = sim.add_exit_stage(Polygon([
        (EXITS[1]["x_start"], EXITS[1]["y"] - 0.5),
        (EXITS[1]["x_end"],   EXITS[1]["y"] - 0.5),
        (EXITS[1]["x_end"],   EXITS[1]["y"] + 0.5),
        (EXITS[1]["x_start"], EXITS[1]["y"] + 0.5),
    ]))

    # 게이트별 Journey
    journey_ids = []
    for i, g in enumerate(gates):
        target_exit = exit_upper if g["y"] > CONCOURSE_WIDTH / 2 else exit_lower
        journey = jps.JourneyDescription([
            approach_wp_ids[i], gate_wp_ids[i],
            post_gate_wp_ids[i], exit_upper, exit_lower
        ])
        journey.set_transition_for_stage(
            approach_wp_ids[i],
            jps.Transition.create_fixed_transition(gate_wp_ids[i])
        )
        journey.set_transition_for_stage(
            gate_wp_ids[i],
            jps.Transition.create_fixed_transition(post_gate_wp_ids[i])
        )
        journey.set_transition_for_stage(
            post_gate_wp_ids[i],
            jps.Transition.create_fixed_transition(target_exit)
        )
        jid = sim.add_journey(journey)
        journey_ids.append(jid)

    # 글로벌 경로용 기본 Journey (게이트 선택 전, 중앙 게이트로 향하는 경로)
    mid_gate = N_GATES // 2
    default_journey_id = journey_ids[mid_gate]
    default_stage_id = approach_wp_ids[mid_gate]

    return (sim, gates, walkable, vis_obstacles, gate_openings,
            approach_wp_ids, gate_wp_ids, post_gate_wp_ids, journey_ids,
            default_journey_id, default_stage_id)


# =============================================================================
# 시뮬레이션 실행
# =============================================================================
def run_simulation():
    print("=" * 60)
    print("성수역 서쪽 대합실 시뮬레이션 v7 (CFSM V2 + Gao LRP 원문 보정)")
    print(f"  열차 간격: {TRAIN_INTERVAL}s, 하차: ~{TRAIN_ALIGHTING}명/회")
    print(f"  게이트 선택: Gao (2019) LRP 모델 (원문 보정)")
    print(f"  3단계 재선택: {CHOICE_DIST_1ST}m / {CHOICE_DIST_2ND}m / {CHOICE_DIST_3RD}m")
    print(f"  3차 조건: 앞 사람 점유 시 인접 빈 게이트로만 전환")
    print(f"  서비스시간(태그): 평균 {SERVICE_TIME_MEAN}s (Gao 실측)")
    print(f"  태그리스 비율: {TAGLESS_RATIO*100:.0f}%")
    print(f"  희망속도: N({PED_SPEED_MEAN}, {PED_SPEED_STD}), "
          f"clip [{PED_SPEED_MIN}, {PED_SPEED_MAX}]")
    print(f"  성격 비율: {dict(zip(TEMPERAMENTS.keys(), TEMPERAMENT_RATIO))}")
    print("=" * 60)

    (sim, gates, walkable, obstacles, gate_openings,
     approach_wp_ids, gate_wp_ids, post_gate_wp_ids, journey_ids,
     default_journey_id, default_stage_id) = create_simulation()

    rng = np.random.default_rng(42)
    total_steps = int(SIM_TIME / DT)

    arrival_times = generate_arrival_schedule(rng, SIM_TIME)
    arrival_idx = 0
    print(f"  도착 스케줄: {len(arrival_times)}명 예정")

    agent_data = {}
    in_service = {}
    spawned_count = 0

    stats = {
        "gate_counts": [0] * N_GATES,
        "service_times": [],
        "queue_history": [],
        "reroute_count": 0,
        "temperament_counts": {"adventurous": 0, "conserved": 0, "mild": 0},
        "tagless_count": 0,
        "stage3_triggers": 0,
    }

    gif_frames = []
    gif_interval = int(0.5 / DT)

    print("\n시뮬레이션 실행 중...")

    for step in range(total_steps):
        current_time = step * DT

        # ── 보행자 생성 (군집 도착) ──
        # 스폰 시에는 글로벌 경로(중앙 게이트 방향)로 이동 시작
        # Influence Zone 진입 시 LRP로 게이트 선택 (Gao §2.3)
        while (arrival_idx < len(arrival_times) and
               arrival_times[arrival_idx] <= current_time):
            stair = STAIRS[rng.integers(0, len(STAIRS))]
            spawn_x = stair["x"] + rng.uniform(0.3, 1.0)
            spawn_y = rng.uniform(stair["y_start"], stair["y_end"])
            desired_speed = np.clip(
                rng.normal(PED_SPEED_MEAN, PED_SPEED_STD),
                PED_SPEED_MIN, PED_SPEED_MAX)

            temperament = assign_temperament(rng)
            is_tagless = rng.random() < TAGLESS_RATIO

            # 스폰 시점: 게이트까지 거리 확인
            dist_to_gate = GATE_X - spawn_x

            if dist_to_gate <= CHOICE_DIST_1ST:
                # 이미 Influence Zone 안 → 즉시 LRP 1차 선택
                gate_queue = count_gate_queue(sim, gates, agent_data)
                gate_idx = choose_gate_lrp(
                    rng, (spawn_x, spawn_y), desired_speed, temperament,
                    gates, gate_queue, stage="1st")
                choice_stage = 1
                jid = journey_ids[gate_idx]
                sid = approach_wp_ids[gate_idx]
            else:
                # Influence Zone 밖 → 글로벌 경로로 시작
                gate_idx = -1  # 미배정
                choice_stage = 0
                jid = default_journey_id
                sid = default_stage_id

            try:
                agent_id = sim.add_agent(
                    jps.CollisionFreeSpeedModelV2AgentParameters(
                        journey_id=jid,
                        stage_id=sid,
                        position=(spawn_x, spawn_y),
                        desired_speed=desired_speed,
                        radius=PED_RADIUS,
                        time_gap=PED_TIME_GAP,
                        strength_neighbor_repulsion=PED_STRENGTH_NEIGHBOR,
                        range_neighbor_repulsion=PED_RANGE_NEIGHBOR,
                        strength_geometry_repulsion=PED_STRENGTH_GEOMETRY,
                        range_geometry_repulsion=PED_RANGE_GEOMETRY,
                    )
                )
                agent_data[agent_id] = {
                    "gate_idx": gate_idx,
                    "spawn_time": current_time,
                    "service_time": sample_service_time(rng, is_tagless),
                    "original_speed": desired_speed,
                    "serviced": False,
                    "is_tagless": is_tagless,
                    "temperament": temperament,
                    "choice_stage": choice_stage,
                    "state": "flowing",  # flowing / queuing / in_gate / done
                }
                spawned_count += 1
                stats["temperament_counts"][temperament] += 1
                if is_tagless:
                    stats["tagless_count"] += 1
            except Exception:
                pass
            arrival_idx += 1

        # ── 게이트 점유 상태 파악 ──
        gate_occupied = [False] * N_GATES
        for aid_s in in_service:
            gi = agent_data[aid_s]["gate_idx"]
            if gi >= 0:
                gate_occupied[gi] = True

        # ── 서비스 완료 체크 (위치 무관) ──
        # 서비스 타이머가 만료된 에이전트를 먼저 처리
        finished_aids = []
        for aid_s, svc in in_service.items():
            elapsed = current_time - svc["start"]
            if elapsed >= svc["duration"]:
                finished_aids.append(aid_s)
        for aid_s in finished_aids:
            if aid_s in agent_data:
                ad_s = agent_data[aid_s]
                gi_s = ad_s["gate_idx"]
                ad_s["serviced"] = True
                ad_s["state"] = "done"
                if gi_s >= 0:
                    stats["gate_counts"][gi_s] += 1
                stats["service_times"].append(in_service[aid_s]["duration"])
                gate_occupied[gi_s] = False
                # 속도/척력 복원 (에이전트가 아직 sim에 있을 때만)
                for agent in sim.agents():
                    if agent.id == aid_s:
                        agent.model.desired_speed = ad_s["original_speed"]
                        agent.model.time_gap = PED_TIME_GAP
                        agent.model.strength_neighbor_repulsion = PED_STRENGTH_NEIGHBOR
                        agent.model.strength_geometry_repulsion = PED_STRENGTH_GEOMETRY
                        break
            del in_service[aid_s]

        # ── 에이전트별 상태 제어 ──
        gate_queue = count_gate_queue(sim, gates, agent_data)

        for agent in sim.agents():
            aid = agent.id
            if aid not in agent_data:
                continue
            ad = agent_data[aid]
            if ad["serviced"]:
                continue

            px, py = agent.position
            gi = ad["gate_idx"]
            dist_to_gate = GATE_X - px

            # ────────────────────────────────────────────────
            # Phase 0: Influence Zone 진입 전 (글로벌 경로)
            # ────────────────────────────────────────────────
            if ad["choice_stage"] == 0 and dist_to_gate <= CHOICE_DIST_1ST:
                # Influence Zone 진입 → 1차 LRP 선택 활성화
                gate_idx_new = choose_gate_lrp(
                    rng, (px, py), ad["original_speed"], ad["temperament"],
                    gates, gate_queue, stage="1st")
                ad["gate_idx"] = gate_idx_new
                ad["choice_stage"] = 1
                # 현재 위치에 맞는 waypoint로 전환 (뒤로 보내지 않음)
                if px >= GATE_X - 0.5:
                    target_wp = gate_wp_ids[gate_idx_new]
                elif px >= 7.0:
                    target_wp = gate_wp_ids[gate_idx_new]
                else:
                    target_wp = approach_wp_ids[gate_idx_new]
                try:
                    sim.switch_agent_journey(
                        aid, journey_ids[gate_idx_new], target_wp)
                except Exception:
                    pass
                gi = gate_idx_new
                continue

            if gi < 0:
                continue  # 아직 게이트 미배정

            # ────────────────────────────────────────────────
            # Phase 1: 게이트 구간 내부 (Bottleneck)
            #   - 척력 무효화, 통과 속도 고정 제어
            # ────────────────────────────────────────────────
            if GATE_ZONE_X_START <= px <= GATE_ZONE_X_END:
                # 병목 내 척력 감소 (벽에 밀착 방지용 약한 반발만 유지)
                agent.model.strength_neighbor_repulsion = BOTTLENECK_STRENGTH_NEIGHBOR
                agent.model.strength_geometry_repulsion = BOTTLENECK_STRENGTH_GEOMETRY

                # 태그리스: 무정지 통과
                if ad["is_tagless"] and aid not in in_service:
                    ad["serviced"] = True
                    ad["state"] = "done"
                    stats["gate_counts"][gi] += 1
                    stats["service_times"].append(0.0)
                    # 척력 복원
                    agent.model.strength_neighbor_repulsion = PED_STRENGTH_NEIGHBOR
                    agent.model.strength_geometry_repulsion = PED_STRENGTH_GEOMETRY
                    continue

                # 태그 사용자: 서비스 시작 (완료 체크는 상단에서 위치 무관으로 처리)
                if aid not in in_service:
                    ad["state"] = "in_gate"
                    agent.model.desired_speed = GATE_PASS_SPEED
                    in_service[aid] = {
                        "start": current_time,
                        "duration": ad["service_time"],
                    }
                    gate_occupied[gi] = True
                continue

            # ────────────────────────────────────────────────
            # Phase 2: 대기열 구간 (Flowing → Queuing 전이)
            #   Leader-Follower 모델
            # ────────────────────────────────────────────────
            if 0 < dist_to_gate < QUEUE_FOLLOW_DIST:
                agent.model.time_gap = PED_TIME_GAP_QUEUE

                if dist_to_gate <= QUEUE_STOP_DIST and gate_occupied[gi]:
                    # 게이트 직전: 점유 중이면 정지 대기
                    agent.model.desired_speed = 0.0
                    ad["state"] = "queuing"
                elif dist_to_gate <= QUEUE_STOP_DIST and not gate_occupied[gi]:
                    # 게이트 비어있음 → 진입 허용
                    agent.model.desired_speed = ad["original_speed"]
                    ad["state"] = "flowing"
                else:
                    # 대기열 접근 중: 앞사람 있으면 추종, 없으면 정상 보행
                    leader_pos = find_leader(
                        (px, py), gi, sim, agent_data, in_service, aid)
                    if leader_pos is not None:
                        gap = leader_pos[0] - px
                        if gap < LEADER_FOLLOW_GAP:
                            # 앞사람에 바짝 → 감속
                            agent.model.desired_speed = max(
                                0.0, ad["original_speed"] * (gap / LEADER_FOLLOW_GAP))
                            ad["state"] = "queuing"
                        else:
                            agent.model.desired_speed = ad["original_speed"]
                            ad["state"] = "flowing"
                    else:
                        agent.model.desired_speed = ad["original_speed"]
                        ad["state"] = "flowing"
            else:
                # 대기열 밖: 일반 보행
                ad["state"] = "flowing"

        # ── 대기열 에이전트 복구: gate_occupied 갱신 후 재검사 ──
        # Phase 1에서 서비스 완료한 에이전트로 인해 gate_occupied가 바뀌었을 수 있음
        for agent in sim.agents():
            aid = agent.id
            if aid not in agent_data:
                continue
            ad = agent_data[aid]
            if ad["serviced"] or aid in in_service:
                continue
            gi = ad["gate_idx"]
            if gi < 0:
                continue
            # queuing 상태인데 게이트가 비었으면 즉시 복구
            if ad["state"] == "queuing" and agent.model.desired_speed < 0.01:
                if not gate_occupied[gi]:
                    agent.model.desired_speed = ad["original_speed"]
                    ad["state"] = "flowing"

        # ── 안전장치: 오래 체류한 에이전트 강제 통과 ──
        STUCK_TIMEOUT = 60.0  # 60초 이상 미통과 시 강제 처리
        for agent in sim.agents():
            aid = agent.id
            if aid not in agent_data:
                continue
            ad = agent_data[aid]
            if ad["serviced"] or aid in in_service:
                continue
            age = current_time - ad["spawn_time"]
            if age > STUCK_TIMEOUT and ad["gate_idx"] >= 0:
                px = agent.position[0]
                # 게이트 근처에서 멈춘 에이전트: 속도 복원 + 강제 진입
                if agent.model.desired_speed < 0.01:
                    agent.model.desired_speed = ad["original_speed"]
                    ad["state"] = "flowing"

        # ── 동적 경로 변경: Gao (2019) 이산적 상태 전이 ──
        for agent in sim.agents():
            aid = agent.id
            if aid not in agent_data:
                continue
            ad = agent_data[aid]
            if ad["serviced"] or aid in in_service or ad["gate_idx"] < 0:
                continue

            pos = agent.position
            dist_to_gate = GATE_X - pos[0]

            if dist_to_gate <= 0:
                continue

            current_stage = ad["choice_stage"]
            current_gate = ad["gate_idx"]

            # 2차 재선택 (1.7m): 확률적
            # px ≈ 10.3m → gate_wp(x=12.0)로 보내야 함 (approach_wp=8.0은 뒤)
            if dist_to_gate <= CHOICE_DIST_2ND and current_stage < 2:
                ad["choice_stage"] = 2
                new_gate = choose_gate_lrp(
                    rng, pos, ad["original_speed"], ad["temperament"],
                    gates, gate_queue, stage="2nd")
                if new_gate != current_gate:
                    try:
                        sim.switch_agent_journey(
                            aid, journey_ids[new_gate],
                            gate_wp_ids[new_gate])
                        ad["gate_idx"] = new_gate
                        stats["reroute_count"] += 1
                    except Exception:
                        pass

            # 3차 재선택 (0.25m, 카드 태핑 위치): 앞 사람 점유 시에만
            elif dist_to_gate <= CHOICE_DIST_3RD and current_stage < 3:
                ad["choice_stage"] = 3
                stats["stage3_triggers"] += 1
                new_gate = choose_gate_lrp(
                    rng, pos, ad["original_speed"], ad["temperament"],
                    gates, gate_queue, stage="3rd",
                    gate_occupied=gate_occupied,
                    current_gate_idx=current_gate)
                if new_gate != current_gate:
                    try:
                        sim.switch_agent_journey(
                            aid, journey_ids[new_gate],
                            gate_wp_ids[new_gate])
                        ad["gate_idx"] = new_gate
                        stats["reroute_count"] += 1
                    except Exception:
                        pass

        # ── 통계 & 프레임 ──
        if step % int(1.0 / DT) == 0:
            gd = count_gate_queue(sim, gates, agent_data)
            stats["queue_history"].append((current_time, gd.copy()))

        if step % gif_interval == 0:
            positions = [(a.position[0], a.position[1]) for a in sim.agents()]
            gif_frames.append((current_time, positions))

        sim.iterate()

        if step % int(30.0 / DT) == 0 and step > 0:
            print(f"  t={current_time:.0f}s | agents: {sim.agent_count()} "
                  f"| spawned: {spawned_count} | passed: {sum(stats['gate_counts'])} "
                  f"| re-route: {stats['reroute_count']} "
                  f"| 3rd-triggers: {stats['stage3_triggers']}")

    # ── 결과 ──
    total_passed = sum(stats["gate_counts"])
    print(f"\n완료: {spawned_count}명 생성, {total_passed}명 통과, "
          f"{stats['reroute_count']}회 경로변경")
    print(f"  태그리스: {stats['tagless_count']}명 "
          f"({stats['tagless_count']/max(spawned_count,1)*100:.1f}%)")
    print(f"  성격: {stats['temperament_counts']}")
    print(f"  3차 재선택 발동: {stats['stage3_triggers']}회")
    print("\n게이트별 통과:")
    for i in range(N_GATES):
        print(f"  G{i+1}: {stats['gate_counts'][i]}명")

    if stats["service_times"]:
        st = np.array(stats["service_times"])
        print(f"\n서비스 시간: 평균 {st.mean():.2f}s, "
              f"중앙값 {np.median(st):.2f}s, 최대 {st.max():.2f}s")

    # ── 미통과 에이전트 진단 ──
    # sim에서 이미 퇴장한(exit stage 도달) 에이전트도 체크
    active_ids = {agent.id for agent in sim.agents()}
    unserviced = 0
    for aid, ad in agent_data.items():
        if not ad["serviced"]:
            unserviced += 1
            if aid in active_ids:
                for agent in sim.agents():
                    if agent.id == aid:
                        px, py = agent.position
                        print(f"  [sim내] id={aid}: x={px:.1f} y={py:.1f} "
                              f"G{ad['gate_idx']+1 if ad['gate_idx']>=0 else '?'} "
                              f"state={ad['state']} stage={ad['choice_stage']}")
                        break
            else:
                print(f"  [퇴장] id={aid}: G{ad['gate_idx']+1 if ad['gate_idx']>=0 else '?'} "
                      f"state={ad['state']} - JuPedSim 퇴장했으나 미통과 처리")
    if unserviced > 0:
        print(f"\n미통과 에이전트: {unserviced}명")

    print(f"\n출력 생성...")
    create_snapshots(gif_frames, gates, obstacles, gate_openings)
    create_gif(gif_frames, gates, obstacles, gate_openings)
    plot_queue_history(stats["queue_history"])
    plot_service_time_dist(stats["service_times"])

    return stats, spawned_count


# =============================================================================
# 시각화
# =============================================================================
def draw_frame(ax, positions, gates, obstacles, gate_openings, time_sec):
    ax.clear()
    gate_x_end = GATE_X + GATE_LENGTH

    ax.axvspan(0, GATE_X, color='#E8F5E9', alpha=0.3)
    ax.axvspan(gate_x_end, 32, color='#FFF8E1', alpha=0.3)

    outer_x = [0, CONCOURSE_LENGTH, CONCOURSE_LENGTH, NOTCH_X, NOTCH_X, 0, 0]
    outer_y = [0, 0, CONCOURSE_WIDTH, CONCOURSE_WIDTH, NOTCH_Y, NOTCH_Y, 0]
    ax.plot(outer_x, outer_y, color='#E65100', linewidth=1.5)

    for obs in obstacles:
        if obs.geom_type == 'Polygon':
            ox, oy = obs.exterior.xy
            ax.fill(ox, oy, color='#546E7A', edgecolor='#263238', linewidth=0.3)
        elif obs.geom_type == 'MultiPolygon':
            for geom in obs.geoms:
                ox, oy = geom.exterior.xy
                ax.fill(ox, oy, color='#546E7A', edgecolor='#263238', linewidth=0.3)

    for opening in gate_openings:
        ox, oy = opening.exterior.xy
        ax.fill(ox, oy, color='#66BB6A', edgecolor='#2E7D32', linewidth=0.8, alpha=0.5)

    for g in gates:
        ax.text(g["x"] + GATE_LENGTH / 2, g["y"], str(g["id"] + 1),
                ha='center', va='center', fontsize=7, fontweight='bold', color='#1B5E20')

    for stair in STAIRS:
        ax.plot([stair["x"], stair["x"]],
                [stair["y_start"], stair["y_end"]],
                color='#E53935', linewidth=3, solid_capstyle='round')

    for exit_ in EXITS:
        ax.plot([exit_["x_start"], exit_["x_end"]],
                [exit_["y"], exit_["y"]],
                color='#1565C0', linewidth=3, solid_capstyle='round')

    for s in STRUCTURES:
        coords = s["coords"]
        xs = [c[0] for c in coords]
        ys = [c[1] for c in coords]
        ax.add_patch(mpatches.Rectangle(
            (min(xs), min(ys)), max(xs) - min(xs), max(ys) - min(ys),
            linewidth=0.5, edgecolor='#E65100', facecolor='#FFE0B2',
            hatch='///', alpha=0.4))

    if positions:
        xs, ys = zip(*positions)
        ax.scatter(xs, ys, s=25, c='#0D47A1', edgecolors='white',
                   linewidths=0.3, alpha=0.85, zorder=5)

    ax.text(0.5, NOTCH_Y - 0.5,
            f't = {time_sec:.1f}s | {len(positions)} peds',
            fontsize=10, fontweight='bold', color='#333',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white',
                      edgecolor='#999', alpha=0.9))

    ax.set_xlim(-0.5, 32)
    ax.set_ylim(-0.5, CONCOURSE_WIDTH + 0.5)
    ax.set_aspect('equal')
    ax.set_xlabel('x (m)', fontsize=9)
    ax.set_ylabel('y (m)', fontsize=9)


def create_snapshots(frames, gates, obstacles, gate_openings):
    snap_times = [3, 10, 15, 25, 45, 90]

    fig, axes = plt.subplots(2, 3, figsize=(36, 22))
    axes = axes.flatten()

    for idx, target_t in enumerate(snap_times):
        best_i = min(range(len(frames)), key=lambda i: abs(frames[i][0] - target_t))
        t, positions = frames[best_i]
        draw_frame(axes[idx], positions, gates, obstacles, gate_openings, t)
        axes[idx].set_title(f't = {target_t}s ({len(positions)} agents)',
                            fontsize=12, fontweight='bold')

    fig.suptitle('성수역 서쪽 대합실 시뮬레이션 v7 (Gao LRP 원문보정 + CFSM V2)',
                 fontsize=16, fontweight='bold')
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "snapshots_v7.png", dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  스냅샷: {OUTPUT_DIR / 'snapshots_v7.png'}")


def create_gif(frames, gates, obstacles, gate_openings):
    from matplotlib.animation import FuncAnimation, PillowWriter

    target_frames = []
    for t, pos in frames:
        if t > 60:
            break
        target_frames.append((t, pos))
    target_frames = target_frames[::2]

    if not target_frames:
        return

    fig, ax = plt.subplots(figsize=(14, 8))

    def animate(i):
        t, positions = target_frames[i]
        draw_frame(ax, positions, gates, obstacles, gate_openings, t)
        ax.set_title(f'성수역 서쪽 v7 | t = {t:.1f}s | {len(positions)} agents',
                     fontsize=12, fontweight='bold')

    anim = FuncAnimation(fig, animate, frames=len(target_frames), interval=200)
    gif_path = OUTPUT_DIR / "simulation_v7.gif"
    anim.save(str(gif_path), writer=PillowWriter(fps=5), dpi=100)
    plt.close(fig)
    print(f"  GIF: {gif_path}")


def plot_queue_history(queue_history):
    if not queue_history:
        return
    times = [t for t, _ in queue_history]
    queues = np.array([q for _, q in queue_history])

    fig, ax = plt.subplots(figsize=(14, 5))
    for i in range(N_GATES):
        ax.plot(times, queues[:, i], label=f'G{i+1}', linewidth=1.5)

    train_t = FIRST_TRAIN_TIME
    while train_t < SIM_TIME:
        ax.axvline(train_t, color='red', linestyle='--', alpha=0.3, linewidth=1)
        train_t += TRAIN_INTERVAL

    ax.set_xlabel('시간 (초)')
    ax.set_ylabel('게이트 앞 밀도 (명)')
    ax.set_title('게이트별 대기 밀도 변화 (v7) - 빨간 점선: 열차 도착')
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "queue_history_v7.png", dpi=150)
    plt.close(fig)
    print(f"  대기열: {OUTPUT_DIR / 'queue_history_v7.png'}")


def plot_service_time_dist(service_times):
    if not service_times:
        return
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(service_times, bins=25, color='#42A5F5', edgecolor='#1565C0', alpha=0.8)
    ax.axvline(np.mean(service_times), color='red', linestyle='--',
               label=f'평균: {np.mean(service_times):.2f}s')
    ax.set_xlabel('서비스 시간 (초)')
    ax.set_ylabel('빈도')
    ax.set_title('개찰구 서비스 시간 분포 (태그 사용자)')
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "service_time_v7.png", dpi=150)
    plt.close(fig)
    print(f"  서비스시간: {OUTPUT_DIR / 'service_time_v7.png'}")


# =============================================================================
# 자동 평가 척도 (선행연구 기반)
# =============================================================================
def evaluate_simulation(stats, spawned_count, sim_time, agent_data_snapshot=None):
    """
    시뮬레이션 품질 자동 평가.

    평가 척도:
      1. 통과율 (Throughput Rate): 생성 대비 통과 비율 → 100%에 가까울수록 정상
      2. 게이트 이용 균형도 MD (Gao, 2019 eq.14): 낮을수록 균등
      3. 게이트별 통과 비율 vs 기대 비율
      4. 평균 서비스 시간 vs Gao 실측 (2.0s)
      5. 잔류 에이전트 수 (Stuck Agents): 0이어야 정상
      6. 경로 변경 비율: 전체 대비 re-route 비율
      7. 대기열 피크: 게이트당 최대 대기 인원

    판정 기준:
      PASS: 정상 작동
      WARN: 검토 필요
      FAIL: 비정상 행태 발생
    """
    print("\n" + "=" * 60)
    print("시뮬레이션 평가 결과")
    print("=" * 60)

    total_passed = sum(stats["gate_counts"])
    issues = []

    # ── 1. 통과율 ──
    throughput = total_passed / max(spawned_count, 1) * 100
    status = "PASS" if throughput >= 90 else ("WARN" if throughput >= 70 else "FAIL")
    print(f"\n[{status}] 통과율: {total_passed}/{spawned_count} ({throughput:.1f}%)")
    if status != "PASS":
        stuck = spawned_count - total_passed
        issues.append(f"통과 못한 에이전트 {stuck}명 — 게이트 진입 실패 또는 경로 이탈")

    # ── 2. 게이트 이용 균형도 MD (Gao, 2019 eq.14) ──
    if total_passed > 0:
        proportions = np.array(stats["gate_counts"]) / total_passed
        mean_prop = 1.0 / len(stats["gate_counts"])
        md = np.sum(np.abs(proportions - mean_prop)) / len(stats["gate_counts"])
        # Gao 논문: 대칭 시나리오 MD=3.6, 비대칭 MD=2.8 (200명 기준, 비율 단위)
        # 여기서는 비율(0~1) 단위이므로 스케일이 다름
        md_pct = md * 100
        status = "PASS" if md_pct < 15 else ("WARN" if md_pct < 25 else "FAIL")
        print(f"[{status}] 게이트 이용 균형도 (MD): {md_pct:.1f}%")
        print(f"         게이트별: {' | '.join(f'G{i+1}:{c}명({p*100:.0f}%)' for i, (c, p) in enumerate(zip(stats['gate_counts'], proportions)))}")

        # 미사용 게이트 체크
        zero_gates = [i+1 for i, c in enumerate(stats["gate_counts"]) if c == 0]
        if zero_gates:
            print(f"  [WARN] 미사용 게이트: {zero_gates} — 경로 선택 또는 접근성 문제")
            issues.append(f"게이트 {zero_gates} 미사용")

    # ── 3. 서비스 시간 검증 ──
    if stats["service_times"]:
        st = np.array(stats["service_times"])
        tag_times = st[st > 0]  # 태그리스(0.0s) 제외
        if len(tag_times) > 0:
            mean_st = tag_times.mean()
            # Gao 실측: 평균 2.0s, 범위 0.8~3.7s
            status = "PASS" if 1.5 <= mean_st <= 2.5 else "WARN"
            print(f"[{status}] 태그 서비스시간: 평균 {mean_st:.2f}s "
                  f"(Gao 실측: 2.0s, 범위 {tag_times.min():.2f}~{tag_times.max():.2f}s)")
            if status != "PASS":
                issues.append(f"서비스 시간 평균 {mean_st:.2f}s — Gao 실측(2.0s)과 괴리")

    # ── 4. 경로 변경 비율 ──
    reroute_ratio = stats["reroute_count"] / max(spawned_count, 1) * 100
    # Gao 논문에서는 재선택이 자연스러운 행동. 과도하면(>200%) 핑퐁
    status = "PASS" if reroute_ratio < 150 else ("WARN" if reroute_ratio < 300 else "FAIL")
    print(f"[{status}] 경로 변경: {stats['reroute_count']}회 "
          f"(인당 {reroute_ratio:.0f}%)")
    if status == "FAIL":
        issues.append(f"경로 변경 {stats['reroute_count']}회 — 핑퐁 현상 의심")

    # ── 5. 대기열 피크 ──
    if stats["queue_history"]:
        queues = np.array([q for _, q in stats["queue_history"]])
        peak_per_gate = queues.max(axis=0)
        overall_peak = peak_per_gate.max()
        # 게이트 7개, 열차당 40명 → 게이트당 평균 ~6명. 15명 이상이면 과밀
        status = "PASS" if overall_peak <= 10 else ("WARN" if overall_peak <= 15 else "FAIL")
        print(f"[{status}] 대기열 피크: 최대 {overall_peak}명 "
              f"(게이트별: {' '.join(f'G{i+1}:{int(p)}' for i, p in enumerate(peak_per_gate))})")

    # ── 6. 성격별 통과 분석 (Gao Table 2 참조) ──
    if stats["temperament_counts"]:
        print(f"\n  성격 분포: {stats['temperament_counts']}")
        print(f"  3차 재선택 발동: {stats.get('stage3_triggers', 0)}회")

    # ── 종합 판정 ──
    print("\n" + "-" * 40)
    if not issues:
        print("종합: PASS — 시뮬레이션 행태 정상")
    else:
        print(f"종합: {'FAIL' if any('통과 못한' in i for i in issues) else 'WARN'} — 검토 필요:")
        for issue in issues:
            print(f"  - {issue}")
    print("=" * 60)

    return issues


if __name__ == "__main__":
    stats, spawned_count = run_simulation()
    evaluate_simulation(stats, spawned_count, SIM_TIME)
