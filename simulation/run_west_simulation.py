"""
성수역 서쪽 대합실 보행자 시뮬레이션 v6

변경 이력 (v5 → v6):
  1. 게이트 선택 모델: Haghani 로짓 → Gao et al. (2019) LRP 모델
     - 효용함수: 예상 소요시간 = ω^N·대기시간 + ω^L·보행시간
     - 보행시간에 L3(게이트→출구 거리) 포함
     - 거리 추정 오차 ±10%, 대기 인원 추정 오차 반영
  2. 보행자 성격 유형: adventurous/conserved/mild (Gao, 2019)
     - VOT 가중치: (1.2/0.8), (0.8/1.2), (1.0/1.0)
  3. 3단계 재선택 (Gao, 2019 현장관측):
     - 1차(3.0m): 전체경로 + 대기열 → 확률적 선택 (Logit)
     - 2차(1.7m): 접근거리만 + 대기열 → 확률적 선택
     - 3차(1.0m): 접근거리만 → 확정적 선택 (최소 비용)
  4. 서비스 파라미터: Gao (2019) 현장 실측
     - 게이트 통과 속도: 0.65 m/s, 카드 태핑: 1.1s
     - 서비스 시간 t₀ = 2.0s (피크 실측 평균)
  5. 태그리스 사용자: 일반 보행속도로 통과 (서비스 시간 ≈ 0)
  [유지] 도착 모델, CFSM V2, 게이트 근처 time_gap 감소

파라미터 출처:
  - CFSM V2: Tordeux et al. (2016), Weidmann (1993)
  - 게이트 선택: Gao et al. (2019) - Beijing Subway 실측
  - 서비스 시간(태그): Gao (2019) 실측 (🔶 한국 검증 필요)
  - 서비스 시간(태그리스): 본 연구 가정 (🔴 우이신설선 실측 필요)
  - 대기열 time_gap: 본 연구 설정 (🔶 검증 필요)
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

# 태그리스 사용자: 일반 보행속도로 통과 (🔴 우이신설선 실측 필요)
TAGLESS_SERVICE_TIME = 0.0   # 태그리스 서비스 시간 (무정지 통과)

# 시나리오 변수
TAGLESS_RATIO = 0.2          # 태그리스 사용자 비율 (0.0 ~ 1.0)

# =============================================================================
# 게이트 선택 모델: Gao et al. (2019) LRP 모델
# =============================================================================
# 보행자 성격별 시간가치(VOT) 가중치 (🔶 검증 필요)
# adventurous: 대기 싫어함 → 먼 빈 게이트로 우회
# conserved: 걷기 싫어함 → 가까운 게이트에서 대기
# mild: 중립
TEMPERAMENTS = {
    "adventurous": {"omega_wait": 1.2, "omega_walk": 0.8},
    "conserved":   {"omega_wait": 0.8, "omega_walk": 1.2},
    "mild":        {"omega_wait": 1.0, "omega_walk": 1.0},
}
TEMPERAMENT_RATIO = [1, 1, 1]  # 모험:보수:중립 비율 (🔶 검증 필요)

# 추정 오차 (Gao, 2019)
DIST_ESTIMATION_ERROR = 0.10   # 거리 추정 오차 ±10%

# 3단계 재선택 거리 (Gao, 2019 현장관측) (🔶 검증 필요)
CHOICE_DIST_1ST = 3.0    # 1차 선택: 전체경로 고려, 확률적 (Logit)
CHOICE_DIST_2ND = 1.7    # 2차 재선택: 접근거리만, 확률적
CHOICE_DIST_3RD = 1.0    # 3차 재선택: 접근거리만, 확정적 (최소 비용)

# 게이트 통과 구간
GATE_ZONE_X_START = GATE_X - 0.2
GATE_ZONE_X_END = GATE_X + GATE_LENGTH + 0.2

OUTPUT_DIR = pathlib.Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


# =============================================================================
# 도착 스케줄 생성
# =============================================================================
def generate_arrival_schedule(rng, sim_time):
    """
    열차 도착 군집 모델:
    - 열차가 TRAIN_INTERVAL 간격으로 도착
    - 각 열차에서 TRAIN_ALIGHTING명이 하차
    - 계단에서 PLATOON_SPREAD초에 걸쳐 분산 도착 (정규분포)
    """
    arrivals = []
    train_time = FIRST_TRAIN_TIME
    while train_time < sim_time:
        n_passengers = rng.poisson(TRAIN_ALIGHTING)
        # 계단 도착 시각: 열차 도착 후 정규분포로 분산
        for _ in range(n_passengers):
            arrival_t = train_time + abs(rng.normal(PLATOON_SPREAD / 2, PLATOON_SPREAD / 4))
            if arrival_t < sim_time:
                arrivals.append(arrival_t)
        train_time += TRAIN_INTERVAL
    arrivals.sort()
    return arrivals


# =============================================================================
# 서비스 시간 샘플링
# =============================================================================
def assign_temperament(rng):
    """보행자 성격 유형 랜덤 배정 (Gao, 2019)"""
    names = list(TEMPERAMENTS.keys())
    weights = np.array(TEMPERAMENT_RATIO, dtype=float)
    weights /= weights.sum()
    return rng.choice(names, p=weights)


def sample_service_time(rng, is_tagless=False):
    """서비스 시간 샘플링 (Gao, 2019 실측 기반)"""
    if is_tagless:
        return TAGLESS_SERVICE_TIME
    # 태그 사용자: 양의 왜도 분포, 범위 0.8~3.7s, 평균 2.0s (Gao, 2019)
    return np.clip(rng.lognormal(
        np.log(SERVICE_TIME_MEAN) - 0.25, 0.5), SERVICE_TIME_MIN, SERVICE_TIME_MAX)


# =============================================================================
# 게이트 대기 인원 계산
# =============================================================================
def count_gate_queue(sim, gates, agent_data):
    """각 게이트에 배정된 전체 대기 인원 (서비스 완료자 제외)"""
    queue = [0] * len(gates)
    for agent in sim.agents():
        aid = agent.id
        if aid not in agent_data:
            continue
        if agent_data[aid]["serviced"]:
            continue
        gi = agent_data[aid]["gate_idx"]
        queue[gi] += 1
    return queue


def estimate_queue_count(rng, actual_count):
    """대기 인원 추정 (Gao, 2019 eq.7): 인원 많을수록 오차 증가"""
    if actual_count <= 3:
        return actual_count
    elif actual_count <= 5:
        return actual_count + rng.choice([-1, 0, 1])
    else:
        return max(0, actual_count + rng.choice([-2, -1, 0, 1, 2]))


def estimate_distance(rng, actual_dist):
    """거리 추정 (Gao, 2019 eq.4): ±10% 가우시안 오차"""
    k = np.clip(rng.normal(0, 0.03), -DIST_ESTIMATION_ERROR, DIST_ESTIMATION_ERROR)
    return actual_dist * (1.0 + k)


def get_exit_position(gate):
    """게이트 통과 후 향할 출구 좌표 반환"""
    if gate["y"] > CONCOURSE_WIDTH / 2:
        return (EXITS[0]["x_start"] + EXITS[0]["x_end"]) / 2, EXITS[0]["y"]
    else:
        return (EXITS[1]["x_start"] + EXITS[1]["x_end"]) / 2, EXITS[1]["y"]


# =============================================================================
# 게이트 선택: Gao et al. (2019) LRP 모델
# =============================================================================
def choose_gate_lrp(rng, agent_pos, agent_speed, temperament, gates,
                    gate_queue, dist_to_gate, stage="1st"):
    """
    Gao (2019) LRP 모델:
      V_i,j = ω^N · (N'_j · t₀) + ω^L · ((L1' + L3') / v_i)
      P_j = exp(-V_j) / Σ exp(-V_k)

    stage:
      "1st" (3.0m): L1+L3 고려, 확률적 선택 (Logit)
      "2nd" (1.7m): L1만 고려, 확률적 선택
      "3rd" (1.0m): L1만 고려, 확정적 선택 (최소 비용)
    """
    omega = TEMPERAMENTS[temperament]
    omega_wait = omega["omega_wait"]
    omega_walk = omega["omega_walk"]

    n_gates = len(gates)
    costs = np.full(n_gates, np.inf)

    for j, gate in enumerate(gates):
        # L1: 현재 위치 → 게이트 입구 거리
        l1 = np.hypot(agent_pos[0] - gate["x"], agent_pos[1] - gate["y"])
        l1_est = estimate_distance(rng, l1)

        # 보행시간 계산
        if stage == "1st":
            # L3: 게이트 출구 → 다음 목적지 거리
            exit_x, exit_y = get_exit_position(gate)
            gate_exit_x = gate["x"] + GATE_LENGTH
            l3 = np.hypot(gate_exit_x - exit_x, gate["y"] - exit_y)
            l3_est = estimate_distance(rng, l3)
            walk_time = (l1_est + l3_est) / agent_speed
        else:
            # 2차/3차: 게이트에 가까우므로 L1만 고려 (Gao, 2019 eq.12)
            walk_time = l1_est / agent_speed

        # 대기시간: 추정 인원 × 평균 서비스 시간 (Gao, 2019 eq.6)
        n_est = estimate_queue_count(rng, gate_queue[j])
        wait_time = n_est * SERVICE_TIME_MEAN

        # 총 예상 소요시간 (Gao, 2019 eq.2)
        costs[j] = omega_wait * wait_time + omega_walk * walk_time

    # 3차 선택: 확정적 (Gao, 2019 eq.13)
    if stage == "3rd":
        return int(np.argmin(costs))

    # 1차/2차: 확률적 (Logit, Gao 2019 eq.8)
    # P_j = exp(-V_j) / Σ exp(-V_k), 비용이 작을수록 선택 확률 높음
    shifted = costs - np.min(costs)
    exp_neg = np.exp(-shifted)
    probs = exp_neg / exp_neg.sum()
    return int(rng.choice(n_gates, p=probs))


# =============================================================================
# 시뮬레이션 생성
# =============================================================================
def create_simulation():
    gates = calculate_gate_positions()
    # 시뮬레이션: 배리어 없는 열린 공간 (게이트 통과는 코드로 제어)
    walkable, obstacles, gate_openings = build_geometry(gates, include_barrier=False)
    # 시각화용: 배리어 포함
    _, vis_obstacles, _ = build_geometry(gates, include_barrier=True)

    model = jps.CollisionFreeSpeedModelV2()

    sim = jps.Simulation(
        model=model,
        geometry=walkable,
        dt=DT,
    )

    gate_x_end = GATE_X + GATE_LENGTH

    # 1단계: 접근 Waypoint (게이트 y좌표로 정렬, 줄 합류)
    approach_wp_ids = []
    for g in gates:
        wp_id = sim.add_waypoint_stage((8.0, g["y"]), 1.0)
        approach_wp_ids.append(wp_id)

    # 2단계: 게이트 입구 Waypoint (작은 반경 → 한 줄 대기)
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

    # 게이트별 Journey (3단계: 접근 → 게이트 입구 → 통과 후 → 출구)
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

    return (sim, gates, walkable, vis_obstacles, gate_openings,
            approach_wp_ids, gate_wp_ids, post_gate_wp_ids, journey_ids)


# =============================================================================
# 시뮬레이션 실행
# =============================================================================
def run_simulation():
    print("=" * 60)
    print("성수역 서쪽 대합실 시뮬레이션 v6 (CFSM V2 + Gao LRP)")
    print(f"  열차 간격: {TRAIN_INTERVAL}s, 하차: ~{TRAIN_ALIGHTING}명/회")
    print(f"  게이트 선택: Gao (2019) LRP 모델")
    print(f"  3단계 재선택: {CHOICE_DIST_1ST}m / {CHOICE_DIST_2ND}m / {CHOICE_DIST_3RD}m")
    print(f"  서비스시간(태그): 평균 {SERVICE_TIME_MEAN}s (Gao 실측)")
    print(f"  태그리스 비율: {TAGLESS_RATIO*100:.0f}%")
    print(f"  성격 비율: {dict(zip(TEMPERAMENTS.keys(), TEMPERAMENT_RATIO))}")
    print("=" * 60)

    (sim, gates, walkable, obstacles, gate_openings,
     approach_wp_ids, gate_wp_ids, post_gate_wp_ids, journey_ids) = create_simulation()

    rng = np.random.default_rng(42)
    total_steps = int(SIM_TIME / DT)

    # 도착 스케줄 생성
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
    }

    gif_frames = []
    gif_interval = int(0.5 / DT)

    print("\n시뮬레이션 실행 중...")

    for step in range(total_steps):
        current_time = step * DT

        # ── 보행자 생성 (군집 도착) ──
        while (arrival_idx < len(arrival_times) and
               arrival_times[arrival_idx] <= current_time):
            stair = STAIRS[rng.integers(0, len(STAIRS))]
            spawn_x = stair["x"] + rng.uniform(0.3, 1.0)
            spawn_y = rng.uniform(stair["y_start"], stair["y_end"])
            desired_speed = np.clip(
                rng.normal(PED_SPEED_MEAN, PED_SPEED_STD), 0.5, 2.0)

            # 보행자 속성 결정
            temperament = assign_temperament(rng)
            is_tagless = rng.random() < TAGLESS_RATIO

            # 1차 게이트 선택 (Gao LRP)
            gate_queue = count_gate_queue(sim, gates, agent_data)
            gate_idx = choose_gate_lrp(
                rng, (spawn_x, spawn_y), desired_speed, temperament,
                gates, gate_queue, GATE_X - spawn_x, stage="1st")

            try:
                agent_id = sim.add_agent(
                    jps.CollisionFreeSpeedModelV2AgentParameters(
                        journey_id=journey_ids[gate_idx],
                        stage_id=approach_wp_ids[gate_idx],
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
                svc_time = sample_service_time(rng, is_tagless)
                agent_data[agent_id] = {
                    "gate_idx": gate_idx,
                    "spawn_time": current_time,
                    "service_time": svc_time,
                    "original_speed": desired_speed,
                    "serviced": False,
                    "is_tagless": is_tagless,
                    "temperament": temperament,
                    "choice_stage": 1,  # 현재까지 완료된 선택 단계
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
        for aid_s, svc in in_service.items():
            gi = agent_data[aid_s]["gate_idx"]
            gate_occupied[gi] = True

        # ── 서비스 시간 + 대기열 제어 ──
        for agent in sim.agents():
            aid = agent.id
            if aid not in agent_data or agent_data[aid]["serviced"]:
                continue
            px, py = agent.position
            gi = agent_data[aid]["gate_idx"]

            # 게이트 구간 안에 있는 에이전트: 서비스 처리
            if GATE_ZONE_X_START <= px <= GATE_ZONE_X_END:
                # 태그리스: 무정지 통과 (서비스 불필요, 일반 속도 유지)
                if agent_data[aid]["is_tagless"] and aid not in in_service:
                    agent_data[aid]["serviced"] = True
                    stats["gate_counts"][gi] += 1
                    stats["service_times"].append(0.0)
                    # gate_occupied에 영향 없음 (통과만 하므로)
                    continue

                # 태그 사용자: 서비스 처리
                if aid not in in_service:
                    agent.model.desired_speed = GATE_PASS_SPEED  # 0.65 m/s (Gao 실측)
                    in_service[aid] = {
                        "start": current_time,
                        "duration": agent_data[aid]["service_time"],
                    }
                    gate_occupied[gi] = True
                else:
                    elapsed = current_time - in_service[aid]["start"]
                    if elapsed >= in_service[aid]["duration"]:
                        agent.model.desired_speed = agent_data[aid]["original_speed"]
                        agent.model.time_gap = PED_TIME_GAP
                        agent_data[aid]["serviced"] = True
                        stats["gate_counts"][gi] += 1
                        stats["service_times"].append(in_service[aid]["duration"])
                        del in_service[aid]
                        gate_occupied[gi] = False
                continue

            # 게이트 구간 밖: 대기열 제어
            dist_to_gate = GATE_X - px
            if 0 < dist_to_gate < 5.0:
                agent.model.time_gap = PED_TIME_GAP_QUEUE
                # 게이트 직전(0.5m 이내)에서만 점유 확인 후 정지
                # 그 외에는 줄 서서 접근 (CFSM V2가 자연스럽게 감속)
                if dist_to_gate < 0.5 and gate_occupied[gi]:
                    agent.model.desired_speed = 0.0
                else:
                    agent.model.desired_speed = agent_data[aid]["original_speed"]

        # ── 동적 경로 변경: Gao (2019) 3단계 재선택 ──
        gate_queue = count_gate_queue(sim, gates, agent_data)
        for agent in sim.agents():
            aid = agent.id
            if aid not in agent_data:
                continue
            if agent_data[aid]["serviced"] or aid in in_service:
                continue

            pos = agent.position
            dist_to_gate = GATE_X - pos[0]

            if dist_to_gate <= 0:
                continue

            ad = agent_data[aid]
            current_stage = ad["choice_stage"]

            # 단계 판정: 거리에 따라 재선택 트리거
            if dist_to_gate <= CHOICE_DIST_3RD and current_stage < 3:
                stage = "3rd"
                ad["choice_stage"] = 3
            elif dist_to_gate <= CHOICE_DIST_2ND and current_stage < 2:
                stage = "2nd"
                ad["choice_stage"] = 2
            else:
                continue  # 아직 재선택 거리에 도달하지 않음

            current_gate = ad["gate_idx"]
            new_gate = choose_gate_lrp(
                rng, pos, ad["original_speed"], ad["temperament"],
                gates, gate_queue, dist_to_gate, stage=stage)

            if new_gate != current_gate:
                try:
                    sim.switch_agent_journey(
                        aid, journey_ids[new_gate], approach_wp_ids[new_gate])
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
                  f"| re-route: {stats['reroute_count']}")

    # ── 결과 ──
    total_passed = sum(stats["gate_counts"])
    print(f"\n완료: {spawned_count}명 생성, {total_passed}명 통과, "
          f"{stats['reroute_count']}회 경로변경")
    print(f"  태그리스: {stats['tagless_count']}명 "
          f"({stats['tagless_count']/max(spawned_count,1)*100:.1f}%)")
    print(f"  성격: {stats['temperament_counts']}")
    print("\n게이트별 통과:")
    for i in range(N_GATES):
        print(f"  G{i+1}: {stats['gate_counts'][i]}명")

    if stats["service_times"]:
        st = np.array(stats["service_times"])
        print(f"\n서비스 시간: 평균 {st.mean():.2f}s, "
              f"중앙값 {np.median(st):.2f}s, 최대 {st.max():.2f}s")

    print(f"\n출력 생성...")
    create_snapshots(gif_frames, gates, obstacles, gate_openings)
    create_gif(gif_frames, gates, obstacles, gate_openings)
    plot_queue_history(stats["queue_history"])
    plot_service_time_dist(stats["service_times"])

    return stats


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
    """열차 도착 전후 스냅샷: 도착 직전, 피크, 해소 과정"""
    snap_times = [3, 10, 15, 25, 45, 90]

    fig, axes = plt.subplots(2, 3, figsize=(36, 22))
    axes = axes.flatten()

    for idx, target_t in enumerate(snap_times):
        best_i = min(range(len(frames)), key=lambda i: abs(frames[i][0] - target_t))
        t, positions = frames[best_i]
        draw_frame(axes[idx], positions, gates, obstacles, gate_openings, t)
        axes[idx].set_title(f't = {target_t}s ({len(positions)} agents)',
                            fontsize=12, fontweight='bold')

    fig.suptitle('성수역 서쪽 대합실 시뮬레이션 v6 (Gao LRP + CFSM V2)',
                 fontsize=16, fontweight='bold')
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "snapshots_v6.png", dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  스냅샷: {OUTPUT_DIR / 'snapshots_v6.png'}")


def create_gif(frames, gates, obstacles, gate_openings):
    """첫 번째 열차 도착 구간(0~60s) GIF 생성"""
    from matplotlib.animation import FuncAnimation, PillowWriter

    # 0~60초 구간만 추출 (1초 간격으로 샘플링)
    target_frames = []
    for t, pos in frames:
        if t > 60:
            break
        target_frames.append((t, pos))
    # 1초 간격으로 다운샘플 (0.5초 간격 프레임 → 매 2번째)
    target_frames = target_frames[::2]

    if not target_frames:
        return

    fig, ax = plt.subplots(figsize=(14, 8))

    def animate(i):
        t, positions = target_frames[i]
        draw_frame(ax, positions, gates, obstacles, gate_openings, t)
        ax.set_title(f'성수역 서쪽 v6 | t = {t:.1f}s | {len(positions)} agents',
                     fontsize=12, fontweight='bold')

    anim = FuncAnimation(fig, animate, frames=len(target_frames), interval=200)
    gif_path = OUTPUT_DIR / "simulation_v6.gif"
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

    # 열차 도착 시점 표시
    train_t = FIRST_TRAIN_TIME
    while train_t < SIM_TIME:
        ax.axvline(train_t, color='red', linestyle='--', alpha=0.3, linewidth=1)
        train_t += TRAIN_INTERVAL

    ax.set_xlabel('시간 (초)')
    ax.set_ylabel('게이트 앞 밀도 (명)')
    ax.set_title('게이트별 대기 밀도 변화 (v6) - 빨간 점선: 열차 도착')
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "queue_history_v6.png", dpi=150)
    plt.close(fig)
    print(f"  대기열: {OUTPUT_DIR / 'queue_history_v6.png'}")


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
    fig.savefig(OUTPUT_DIR / "service_time_v6.png", dpi=150)
    plt.close(fig)
    print(f"  서비스시간: {OUTPUT_DIR / 'service_time_v6.png'}")


if __name__ == "__main__":
    run_simulation()
