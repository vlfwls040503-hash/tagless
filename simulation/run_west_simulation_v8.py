"""
성수역 서쪽 대합실 보행자 시뮬레이션 v8

v7 → v8 변경:
  1. 물리 엔진: CFSM V2 → GCFM (Generalized Centrifugal Force Model)
     - 타원형 보행자 (속도에 따라 어깨축 축소) → 좁은 통로 적합
     - Chraibi et al. (2010), JuPedSim 자체 개발팀 모델
  2. 게이트 통과: 물리 연산 → Queueing Service Node
     - 개찰구를 '물리적 공간'이 아닌 '대기열 서비스 노드'로 취급
     - 게이트 도착 → 정지(물리 정지) → 서비스 시간 대기 → 텔레포트(출구측)
     - 배리어와 물리적 상호작용 제로 → 타임아웃/끼임 원천 제거

논문 프레이밍:
  - 의사결정(전략): Gao et al. (2019) LRP 모델 (게이트 선택)
  - 물리적 보행(전술): GCFM (협소 공간 특화 타원형 모델)
  - 개찰구 서비스: Hybrid Continuous-Queueing (물리-큐 하이브리드)

모델: GeneralizedCentrifugalForceModel (GCFM, Chraibi et al. 2010)
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
SIM_TIME = 300.0
DT = 0.05

# =============================================================================
# 도착 모델
# =============================================================================
TRAIN_INTERVAL = 180.0
TRAIN_ALIGHTING = 40
PLATOON_SPREAD = 15.0
FIRST_TRAIN_TIME = 5.0

# =============================================================================
# GCFM 파라미터 (Chraibi et al. 2010)
# =============================================================================
PED_SPEED_MEAN = 1.34          # Weidmann 1993
PED_SPEED_STD = 0.26
PED_SPEED_MIN = 0.8            # Gao 실측 하한
PED_SPEED_MAX = 1.5            # Gao 실측 상한

# GCFM 에이전트 파라미터
GCFM_MASS = 1.0
GCFM_TAU = 0.5                 # 가속 시정수 (초)
GCFM_A_V = 1.0                 # 타원 이동방향 스트레치
GCFM_A_MIN = 0.2               # 이동방향 최소 반축
GCFM_B_MIN = 0.2               # 어깨방향 최소 반축 (좁은 통로용)
GCFM_B_MAX = 0.4               # 어깨방향 최대 반축 (정지 시)

# GCFM 모델 파라미터
GCFM_STRENGTH_NEIGHBOR = 0.3
GCFM_STRENGTH_GEOMETRY = 0.2
GCFM_MAX_NEIGHBOR_DIST = 2.0
GCFM_MAX_GEOMETRY_DIST = 2.0

# =============================================================================
# 서비스 시간 파라미터 (Gao et al., 2019)
# =============================================================================
SERVICE_TIME_MEAN = 2.0
SERVICE_TIME_MIN = 0.8
SERVICE_TIME_MAX = 3.7
CARD_FEEDING_TIME = 1.1
GATE_PASS_SPEED = 0.65
GATE_PHYS_LENGTH = 1.4

TAGLESS_SERVICE_TIME = 0.0
TAGLESS_RATIO = 0.2

# =============================================================================
# 게이트 선택 모델: Gao (2019) LRP
# =============================================================================
TEMPERAMENTS = {
    "adventurous": {"omega_wait": 1.2, "omega_walk": 0.8},
    "conserved":   {"omega_wait": 0.8, "omega_walk": 1.2},
    "mild":        {"omega_wait": 1.0, "omega_walk": 1.0},
}
TEMPERAMENT_RATIO = [1, 1, 1]

DIST_ESTIMATION_ERROR = 0.10
CHOICE_DIST_1ST = 3.0
CHOICE_DIST_2ND = 1.7
CHOICE_DIST_3RD = 1.0

# =============================================================================
# Queueing Service Node 파라미터
# =============================================================================
# 큐 포인트: 배리어 2m 전 (물리적 접촉 없는 안전 거리)
QUEUE_POINT_X = GATE_X - 2.0     # x=10.0
# 텔레포트 도착점: 배리어 출구 + 0.5m
TELEPORT_X = GATE_X + GATE_LENGTH + 0.5  # x=14.0
# 큐 진입 판정 거리
QUEUE_ENTER_DIST = 0.5  # 큐 포인트 ± 0.5m 이내 도달 시 진입

# 대기열 최대 길이 (게이트 방향으로 줄 서는 간격)
QUEUE_SPACING = 0.7     # 대기자 간 간격 (m)

OUTPUT_DIR = pathlib.Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


# =============================================================================
# 유틸 함수 (v7에서 재사용)
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


def assign_temperament(rng):
    names = list(TEMPERAMENTS.keys())
    weights = np.array(TEMPERAMENT_RATIO, dtype=float)
    weights /= weights.sum()
    return rng.choice(names, p=weights)


def sample_service_time(rng, is_tagless=False):
    if is_tagless:
        return TAGLESS_SERVICE_TIME
    sigma_ln = 0.5
    mu_ln = np.log(SERVICE_TIME_MEAN) - sigma_ln**2 / 2
    return np.clip(rng.lognormal(mu_ln, sigma_ln), SERVICE_TIME_MIN, SERVICE_TIME_MAX)


def estimate_distances_with_order_preservation(rng, actual_dists):
    n = len(actual_dists)
    estimated = np.zeros(n)
    sorted_indices = np.argsort(actual_dists)
    sorted_dists = actual_dists[sorted_indices]
    low = 0.9 * sorted_dists
    high = 1.1 * sorted_dists
    for i in range(n - 1):
        if high[i] > low[i + 1]:
            mid = (high[i] + low[i + 1]) / 2.0
            high[i] = mid
            low[i + 1] = mid
    for i in range(n):
        center = sorted_dists[i]
        sigma = 0.03 * center
        est = rng.normal(center, sigma)
        est = np.clip(est, low[i], high[i])
        estimated[sorted_indices[i]] = est
    return estimated


def estimate_queue_count(rng, actual_count):
    if actual_count <= 3:
        return actual_count
    elif actual_count <= 5:
        return actual_count + rng.choice([-1, 0, 1])
    else:
        return max(0, actual_count + rng.choice([-2, -1, 0, 1, 2]))


def get_exit_position(gate):
    if gate["y"] > CONCOURSE_WIDTH / 2:
        return (EXITS[0]["x_start"] + EXITS[0]["x_end"]) / 2, EXITS[0]["y"]
    else:
        return (EXITS[1]["x_start"] + EXITS[1]["x_end"]) / 2, EXITS[1]["y"]


def choose_gate_lrp(rng, agent_pos, agent_speed, temperament, gates,
                    gate_queue, stage="1st", gate_occupied=None,
                    current_gate_idx=None):
    omega = TEMPERAMENTS[temperament]
    omega_wait = omega["omega_wait"]
    omega_walk = omega["omega_walk"]
    n_gates = len(gates)

    if stage == "3rd":
        if (current_gate_idx is not None and gate_occupied is not None
                and gate_occupied[current_gate_idx]):
            candidates = []
            for delta in [-1, 1]:
                adj = current_gate_idx + delta
                if 0 <= adj < n_gates and not gate_occupied[adj]:
                    d = abs(agent_pos[1] - gates[adj]["y"])
                    candidates.append((d, adj))
            if candidates:
                candidates.sort()
                return candidates[0][1]
        return current_gate_idx if current_gate_idx is not None else 0

    l1_actual = np.array([
        np.hypot(agent_pos[0] - g["x"], agent_pos[1] - g["y"])
        for g in gates
    ])
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

    shifted = costs - np.min(costs)
    exp_neg = np.exp(-shifted)
    probs = exp_neg / exp_neg.sum()
    return int(rng.choice(n_gates, p=probs))


# =============================================================================
# 시뮬레이션 생성 (GCFM + 배리어 없는 기하구조)
# =============================================================================
def create_simulation():
    gates = calculate_gate_positions()

    # 시뮬레이션 기하구조: 배리어 없음 (Queueing Node가 대체)
    # 보행자는 배리어에 물리적으로 접촉하지 않음
    walkable, _, _ = build_geometry(gates, include_barrier=False)
    # 시각화용: 배리어 포함
    _, vis_obstacles, gate_openings = build_geometry(gates, include_barrier=True)

    model = jps.GeneralizedCentrifugalForceModel(
        strength_neighbor_repulsion=GCFM_STRENGTH_NEIGHBOR,
        strength_geometry_repulsion=GCFM_STRENGTH_GEOMETRY,
        max_neighbor_interaction_distance=GCFM_MAX_NEIGHBOR_DIST,
        max_geometry_interaction_distance=GCFM_MAX_GEOMETRY_DIST,
    )

    sim = jps.Simulation(model=model, geometry=walkable, dt=DT)

    gate_x_end = GATE_X + GATE_LENGTH

    # 큐 포인트 Waypoint (배리어 2m 전)
    queue_wp_ids = []
    for g in gates:
        wp_id = sim.add_waypoint_stage((QUEUE_POINT_X, g["y"]), QUEUE_ENTER_DIST)
        queue_wp_ids.append(wp_id)

    # 텔레포트 후 Waypoint (배리어 출구측)
    post_gate_wp_ids = []
    for g in gates:
        wp_id = sim.add_waypoint_stage((TELEPORT_X + 1.0, g["y"]), 2.0)
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

    # Journey: 큐 포인트 → (텔레포트) → 출구
    # 스폰 시에는 큐 포인트를 목표로 이동
    # 텔레포트 후에는 새 에이전트가 post_gate → exit journey로 생성
    pre_gate_journey_ids = []
    for i, g in enumerate(gates):
        journey = jps.JourneyDescription([queue_wp_ids[i]])
        jid = sim.add_journey(journey)
        pre_gate_journey_ids.append(jid)

    post_gate_journey_ids = []
    for i, g in enumerate(gates):
        target_exit = exit_upper if g["y"] > CONCOURSE_WIDTH / 2 else exit_lower
        journey = jps.JourneyDescription([post_gate_wp_ids[i], target_exit])
        journey.set_transition_for_stage(
            post_gate_wp_ids[i],
            jps.Transition.create_fixed_transition(target_exit))
        jid = sim.add_journey(journey)
        post_gate_journey_ids.append(jid)

    # 글로벌 경로 (게이트 미배정 시 중앙 게이트 방향)
    mid_gate = N_GATES // 2
    default_journey_id = pre_gate_journey_ids[mid_gate]
    default_stage_id = queue_wp_ids[mid_gate]

    return (sim, gates, walkable, vis_obstacles, gate_openings,
            queue_wp_ids, post_gate_wp_ids,
            pre_gate_journey_ids, post_gate_journey_ids,
            default_journey_id, default_stage_id,
            exit_upper, exit_lower)


# =============================================================================
# 대기열 관리
# =============================================================================
def count_gate_queue(gate_queues):
    """각 게이트의 대기 인원 수 반환"""
    return [len(q) for q in gate_queues]


def get_queue_position(gate, queue_rank):
    """대기열에서 rank번째 위치 계산 (0=맨 앞, 1=두번째, ...)"""
    return (QUEUE_POINT_X - queue_rank * QUEUE_SPACING, gate["y"])


# =============================================================================
# 시뮬레이션 실행
# =============================================================================
def run_simulation():
    print("=" * 60)
    print("성수역 서쪽 대합실 시뮬레이션 v8 (GCFM + Queueing Service Node)")
    print(f"  물리 엔진: GCFM (Chraibi et al. 2010)")
    print(f"  게이트 통과: Queueing Service Node (텔레포트)")
    print(f"  게이트 선택: Gao (2019) LRP 모델")
    print(f"  3단계 재선택: {CHOICE_DIST_1ST}m / {CHOICE_DIST_2ND}m / {CHOICE_DIST_3RD}m")
    print(f"  서비스시간(태그): 평균 {SERVICE_TIME_MEAN}s")
    print(f"  태그리스 비율: {TAGLESS_RATIO*100:.0f}%")
    print(f"  희망속도: N({PED_SPEED_MEAN}, {PED_SPEED_STD})")
    print("=" * 60)

    (sim, gates, walkable, obstacles, gate_openings,
     queue_wp_ids, post_gate_wp_ids,
     pre_gate_journey_ids, post_gate_journey_ids,
     default_journey_id, default_stage_id,
     exit_upper, exit_lower) = create_simulation()

    rng = np.random.default_rng(42)
    total_steps = int(SIM_TIME / DT)

    arrival_times = generate_arrival_schedule(rng, SIM_TIME)
    arrival_idx = 0
    print(f"  도착 스케줄: {len(arrival_times)}명 예정")

    agent_data = {}        # aid → agent 속성
    gate_queues = [[] for _ in range(N_GATES)]  # 각 게이트의 대기열 (aid 리스트)
    in_service = {}        # aid → {"start": t, "duration": d, "gate_idx": gi}
    gate_occupied = [False] * N_GATES  # 현재 서비스 중인 게이트
    pending_teleport = []  # 텔레포트 대기 (다음 스텝에서 처리)
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

        # ── 텔레포트 처리: 이전 스텝에서 제거된 에이전트를 출구측에 재생성 ──
        new_teleports = []
        for tp in pending_teleport:
            tp_gate = tp["gate_idx"]
            tp_pos = (TELEPORT_X, gates[tp_gate]["y"])
            try:
                new_aid = sim.add_agent(
                    jps.GeneralizedCentrifugalForceModelAgentParameters(
                        journey_id=post_gate_journey_ids[tp_gate],
                        stage_id=post_gate_wp_ids[tp_gate],
                        position=tp_pos,
                        desired_speed=tp["original_speed"],
                        mass=GCFM_MASS, tau=GCFM_TAU,
                        a_v=GCFM_A_V, a_min=GCFM_A_MIN,
                        b_min=GCFM_B_MIN, b_max=GCFM_B_MAX,
                    ))
                # 새 에이전트 데이터 등록 (통과 완료 상태)
                agent_data[new_aid] = {
                    "gate_idx": tp_gate,
                    "spawn_time": tp["spawn_time"],
                    "service_time": tp["service_time"],
                    "original_speed": tp["original_speed"],
                    "serviced": True,
                    "is_tagless": tp["is_tagless"],
                    "temperament": tp["temperament"],
                    "choice_stage": 99,  # 완료
                    "state": "done",
                    "in_queue": False,
                }
            except Exception:
                pass
        pending_teleport.clear()

        # ── 보행자 생성 (군집 도착) ──
        while (arrival_idx < len(arrival_times) and
               arrival_times[arrival_idx] <= current_time):
            stair = STAIRS[rng.integers(0, len(STAIRS))]
            desired_speed = np.clip(
                rng.normal(PED_SPEED_MEAN, PED_SPEED_STD),
                PED_SPEED_MIN, PED_SPEED_MAX)

            temperament = assign_temperament(rng)
            is_tagless = rng.random() < TAGLESS_RATIO

            # 스폰 시도 (겹침 시 위치 변경하여 재시도)
            spawned = False
            for retry in range(5):
                spawn_x = stair["x"] + rng.uniform(0.3, 2.0)
                spawn_y = rng.uniform(stair["y_start"], stair["y_end"])
                if retry > 0:
                    # 재시도: y 범위 확장
                    spawn_y += rng.uniform(-1.0, 1.0)
                    spawn_y = np.clip(spawn_y, 1.0, NOTCH_Y - 1.0)

                dist_to_queue = QUEUE_POINT_X - spawn_x

                if dist_to_queue <= CHOICE_DIST_1ST:
                    gq = count_gate_queue(gate_queues)
                    gate_idx = choose_gate_lrp(
                        rng, (spawn_x, spawn_y), desired_speed, temperament,
                        gates, gq, stage="1st")
                    choice_stage = 1
                    jid = pre_gate_journey_ids[gate_idx]
                    sid = queue_wp_ids[gate_idx]
                else:
                    gate_idx = -1
                    choice_stage = 0
                    jid = default_journey_id
                    sid = default_stage_id

                try:
                    agent_id = sim.add_agent(
                        jps.GeneralizedCentrifugalForceModelAgentParameters(
                            journey_id=jid,
                            stage_id=sid,
                            position=(spawn_x, spawn_y),
                            desired_speed=desired_speed,
                            mass=GCFM_MASS, tau=GCFM_TAU,
                            a_v=GCFM_A_V, a_min=GCFM_A_MIN,
                            b_min=GCFM_B_MIN, b_max=GCFM_B_MAX,
                        ))
                    agent_data[agent_id] = {
                        "gate_idx": gate_idx,
                        "spawn_time": current_time,
                        "service_time": sample_service_time(rng, is_tagless),
                        "original_speed": desired_speed,
                        "serviced": False,
                        "is_tagless": is_tagless,
                        "temperament": temperament,
                        "choice_stage": choice_stage,
                        "state": "walking",
                        "in_queue": False,
                    }
                    spawned_count += 1
                    stats["temperament_counts"][temperament] += 1
                    if is_tagless:
                        stats["tagless_count"] += 1
                    spawned = True
                    break
                except Exception:
                    continue

            if not spawned:
                # 지연 생성: 다음 스텝으로 미룸
                arrival_times.insert(arrival_idx + 1, current_time + DT * 2)

            arrival_idx += 1

        # ── 서비스 완료 → 텔레포트 예약 ──
        finished_aids = []
        for aid_s, svc in in_service.items():
            elapsed = current_time - svc["start"]
            if elapsed >= svc["duration"]:
                finished_aids.append(aid_s)

        for aid_s in finished_aids:
            svc = in_service[aid_s]
            gi = svc["gate_idx"]
            ad = agent_data[aid_s]

            stats["gate_counts"][gi] += 1
            stats["service_times"].append(svc["duration"])
            gate_occupied[gi] = False

            # 에이전트 제거 → 다음 스텝에서 텔레포트
            sim.mark_agent_for_removal(aid_s)
            pending_teleport.append({
                "gate_idx": gi,
                "spawn_time": ad["spawn_time"],
                "service_time": ad["service_time"],
                "original_speed": ad["original_speed"],
                "is_tagless": ad["is_tagless"],
                "temperament": ad["temperament"],
            })

            # 대기열에서 제거
            if aid_s in gate_queues[gi]:
                gate_queues[gi].remove(aid_s)

            del in_service[aid_s]
            # agent_data는 유지 (통계용)
            ad["serviced"] = True
            ad["state"] = "done"

        # ── 에이전트별 상태 제어 ──
        gq_counts = count_gate_queue(gate_queues)

        for agent in sim.agents():
            aid = agent.id
            if aid not in agent_data:
                continue
            ad = agent_data[aid]
            if ad["serviced"] or ad.get("in_queue"):
                continue

            px, py = agent.position
            gi = ad["gate_idx"]
            dist_to_queue = QUEUE_POINT_X - px

            # ── Phase 0: Influence Zone 진입 전 ──
            if ad["choice_stage"] == 0 and dist_to_queue <= CHOICE_DIST_1ST:
                gate_idx_new = choose_gate_lrp(
                    rng, (px, py), ad["original_speed"], ad["temperament"],
                    gates, gq_counts, stage="1st")
                ad["gate_idx"] = gate_idx_new
                ad["choice_stage"] = 1
                try:
                    sim.switch_agent_journey(
                        aid, pre_gate_journey_ids[gate_idx_new],
                        queue_wp_ids[gate_idx_new])
                except Exception:
                    pass
                gi = gate_idx_new
                continue

            if gi < 0:
                continue

            # ── 2차 재선택 (큐 포인트 3.0m 전) ──
            if dist_to_queue <= CHOICE_DIST_2ND + QUEUE_ENTER_DIST and ad["choice_stage"] < 2:
                ad["choice_stage"] = 2
                new_gate = choose_gate_lrp(
                    rng, (px, py), ad["original_speed"], ad["temperament"],
                    gates, gq_counts, stage="2nd")
                if new_gate != gi:
                    try:
                        sim.switch_agent_journey(
                            aid, pre_gate_journey_ids[new_gate],
                            queue_wp_ids[new_gate])
                        ad["gate_idx"] = new_gate
                        gi = new_gate
                        stats["reroute_count"] += 1
                    except Exception:
                        pass

            # ── 3차 재선택 (큐 포인트 1.5m 전) ──
            if dist_to_queue <= CHOICE_DIST_3RD + QUEUE_ENTER_DIST and ad["choice_stage"] < 3:
                ad["choice_stage"] = 3
                stats["stage3_triggers"] += 1
                new_gate = choose_gate_lrp(
                    rng, (px, py), ad["original_speed"], ad["temperament"],
                    gates, gq_counts, stage="3rd",
                    gate_occupied=gate_occupied,
                    current_gate_idx=gi)
                if new_gate != gi:
                    try:
                        sim.switch_agent_journey(
                            aid, pre_gate_journey_ids[new_gate],
                            queue_wp_ids[new_gate])
                        ad["gate_idx"] = new_gate
                        gi = new_gate
                        stats["reroute_count"] += 1
                    except Exception:
                        pass

            # ── 큐 포인트 도달 판정 ──
            if dist_to_queue <= QUEUE_ENTER_DIST:
                ad["in_queue"] = True
                gate_queues[gi].append(aid)
                # 즉시 정지
                agent.model.desired_speed = 0.0
                agent.model.speed = 0.0
                ad["state"] = "queuing"

        # ── 대기열 서비스 로직 ──
        for gi in range(N_GATES):
            queue = gate_queues[gi]
            if not queue:
                continue

            # 맨 앞 에이전트: 서비스 가능하면 시작
            front_aid = queue[0]
            if front_aid not in in_service and not gate_occupied[gi]:
                ad = agent_data[front_aid]
                if ad["is_tagless"]:
                    # 태그리스: 즉시 통과 (서비스 시간 0)
                    gate_occupied[gi] = True
                    in_service[front_aid] = {
                        "start": current_time,
                        "duration": 0.0,
                        "gate_idx": gi,
                    }
                    ad["state"] = "in_service"
                else:
                    # 태그: 서비스 시간 적용
                    gate_occupied[gi] = True
                    in_service[front_aid] = {
                        "start": current_time,
                        "duration": ad["service_time"],
                        "gate_idx": gi,
                    }
                    ad["state"] = "in_service"

        # ── 통계 & 프레임 ──
        if step % int(1.0 / DT) == 0:
            stats["queue_history"].append(
                (current_time, count_gate_queue(gate_queues).copy()))

        if step % gif_interval == 0:
            positions = [(a.position[0], a.position[1]) for a in sim.agents()]
            gif_frames.append((current_time, positions))

        sim.iterate()

        if step % int(30.0 / DT) == 0 and step > 0:
            in_sim = sim.agent_count()
            total_passed = sum(stats["gate_counts"])
            print(f"  t={current_time:.0f}s | agents: {in_sim} "
                  f"| spawned: {spawned_count} | passed: {total_passed} "
                  f"| re-route: {stats['reroute_count']} "
                  f"| queuing: {sum(len(q) for q in gate_queues)}")

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
        tag_st = st[st > 0]
        print(f"\n서비스 시간 (전체): 평균 {st.mean():.2f}s, "
              f"중앙값 {np.median(st):.2f}s, 최대 {st.max():.2f}s")
        if len(tag_st) > 0:
            print(f"서비스 시간 (태그만): 평균 {tag_st.mean():.2f}s, "
                  f"중앙값 {np.median(tag_st):.2f}s, 범위 {tag_st.min():.2f}~{tag_st.max():.2f}s")

    # 잔류 대기열 진단
    total_queuing = sum(len(q) for q in gate_queues)
    if total_queuing > 0:
        print(f"\n잔류 대기열: {total_queuing}명")
        for gi, q in enumerate(gate_queues):
            if q:
                print(f"  G{gi+1}: {len(q)}명")

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

    # 큐 포인트 라인
    ax.axvline(QUEUE_POINT_X, color='#FF9800', linewidth=1, linestyle='--', alpha=0.5)

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
    fig.suptitle('성수역 서쪽 대합실 v8 (GCFM + Queueing Service Node)',
                 fontsize=16, fontweight='bold')
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "snapshots_v8.png", dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  스냅샷: {OUTPUT_DIR / 'snapshots_v8.png'}")


def create_gif(frames, gates, obstacles, gate_openings):
    from matplotlib.animation import FuncAnimation, PillowWriter
    target_frames = [(t, pos) for t, pos in frames if t <= 60]
    target_frames = target_frames[::2]
    if not target_frames:
        return
    fig, ax = plt.subplots(figsize=(14, 8))

    def animate(i):
        t, positions = target_frames[i]
        draw_frame(ax, positions, gates, obstacles, gate_openings, t)
        ax.set_title(f'성수역 서쪽 v8 (GCFM) | t = {t:.1f}s | {len(positions)} agents',
                     fontsize=12, fontweight='bold')

    anim = FuncAnimation(fig, animate, frames=len(target_frames), interval=200)
    gif_path = OUTPUT_DIR / "simulation_v8.gif"
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
    ax.set_ylabel('게이트 앞 대기 인원 (명)')
    ax.set_title('게이트별 대기 인원 변화 (v8 GCFM) - 빨간 점선: 열차 도착')
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "queue_history_v8.png", dpi=150)
    plt.close(fig)
    print(f"  대기열: {OUTPUT_DIR / 'queue_history_v8.png'}")


def plot_service_time_dist(service_times):
    if not service_times:
        return
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(service_times, bins=25, color='#42A5F5', edgecolor='#1565C0', alpha=0.8)
    ax.axvline(np.mean(service_times), color='red', linestyle='--',
               label=f'평균: {np.mean(service_times):.2f}s')
    ax.set_xlabel('서비스 시간 (초)')
    ax.set_ylabel('빈도')
    ax.set_title('개찰구 서비스 시간 분포 (v8)')
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "service_time_v8.png", dpi=150)
    plt.close(fig)
    print(f"  서비스시간: {OUTPUT_DIR / 'service_time_v8.png'}")


# =============================================================================
# 자동 평가 척도
# =============================================================================
def evaluate_simulation(stats, spawned_count, sim_time):
    print("\n" + "=" * 60)
    print("시뮬레이션 평가 결과 (v8 GCFM + Queueing Node)")
    print("=" * 60)

    total_passed = sum(stats["gate_counts"])
    issues = []

    throughput = total_passed / max(spawned_count, 1) * 100
    status = "PASS" if throughput >= 90 else ("WARN" if throughput >= 70 else "FAIL")
    print(f"\n[{status}] 통과율: {total_passed}/{spawned_count} ({throughput:.1f}%)")
    if status != "PASS":
        issues.append(f"통과 못한 에이전트 {spawned_count - total_passed}명")

    if total_passed > 0:
        proportions = np.array(stats["gate_counts"]) / total_passed
        mean_prop = 1.0 / N_GATES
        md = np.sum(np.abs(proportions - mean_prop)) / N_GATES * 100
        status = "PASS" if md < 15 else ("WARN" if md < 25 else "FAIL")
        print(f"[{status}] 게이트 이용 균형도 (MD): {md:.1f}%")
        print(f"         게이트별: {' | '.join(f'G{i+1}:{c}명({p*100:.0f}%)' for i, (c, p) in enumerate(zip(stats['gate_counts'], proportions)))}")
        zero_gates = [i+1 for i, c in enumerate(stats["gate_counts"]) if c == 0]
        if zero_gates:
            print(f"  [WARN] 미사용 게이트: {zero_gates}")
            issues.append(f"게이트 {zero_gates} 미사용")

    if stats["service_times"]:
        st = np.array(stats["service_times"])
        tag_times = st[st > 0]
        if len(tag_times) > 0:
            mean_st = tag_times.mean()
            status = "PASS" if 1.5 <= mean_st <= 2.5 else "WARN"
            print(f"[{status}] 태그 서비스시간: 평균 {mean_st:.2f}s "
                  f"(Gao 실측: 2.0s, 범위 {tag_times.min():.2f}~{tag_times.max():.2f}s)")
            if status != "PASS":
                issues.append(f"서비스 시간 평균 {mean_st:.2f}s")

    reroute_ratio = stats["reroute_count"] / max(spawned_count, 1) * 100
    status = "PASS" if reroute_ratio < 150 else ("WARN" if reroute_ratio < 300 else "FAIL")
    print(f"[{status}] 경로 변경: {stats['reroute_count']}회 (인당 {reroute_ratio:.0f}%)")

    if stats["queue_history"]:
        queues = np.array([q for _, q in stats["queue_history"]])
        peak_per_gate = queues.max(axis=0)
        overall_peak = peak_per_gate.max()
        status = "PASS" if overall_peak <= 10 else ("WARN" if overall_peak <= 15 else "FAIL")
        print(f"[{status}] 대기열 피크: 최대 {overall_peak}명 "
              f"(게이트별: {' '.join(f'G{i+1}:{int(p)}' for i, p in enumerate(peak_per_gate))})")

    print(f"\n  성격 분포: {stats['temperament_counts']}")
    print(f"  3차 재선택 발동: {stats.get('stage3_triggers', 0)}회")

    print("\n" + "-" * 40)
    if not issues:
        print("종합: PASS")
    else:
        severity = "FAIL" if any("통과 못한" in i for i in issues) else "WARN"
        print(f"종합: {severity} — 검토 필요:")
        for issue in issues:
            print(f"  - {issue}")
    print("=" * 60)
    return issues


if __name__ == "__main__":
    stats, spawned_count = run_simulation()
    evaluate_simulation(stats, spawned_count, SIM_TIME)
