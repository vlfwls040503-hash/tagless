"""
성수역 서쪽 대합실 보행자 시뮬레이션 — CFSM V2

v8 (GCFM) → CFSM 변경:
  물리 엔진: GCFM → CollisionFreeSpeedModelV2 (Tordeux et al., 2016)
  - 속도 기반 모델 (힘 기반이 아님) → 계산 효율 ↑
  - 충돌 없는 경로 예측 → 좁은 통로 자연 통과

  게이트 통과 메커니즘:
  - CFSM 기하구조에 배리어 포함 (include_barrier=True)
  - 게이트 통과는 waypoint + 속도 제어로 구현:
    1. 에이전트가 게이트 입구 waypoint 도달
    2. 게이트 점유 중이면 대기 (극저속)
    3. 비어있으면 서비스 속도(0.65 m/s)로 감속하며 게이트 통과
    4. 서비스 시간 만료 → 속도 복원 → 출구 이동
  - 물리적으로 게이트 공간을 걸어서 통과 (텔레포트 아님)

  기존 유지:
  - 게이트 선택: Gao et al. (2019) LRP 모델 (3단계 재선택)
  - 대기열: Leader-Follower, 게이트 점유 시 대기
  - 서비스 시간: Gao (2019) 실측 기반 lognormal

논문 프레이밍:
  - 전략(의사결정): Gao et al. (2019) LRP 모델
  - 전술(물리적 보행): CFSM V2 (Tordeux et al., 2016)
  - 게이트 통과: Gao (2019) 서비스 시간 모델 + 속도 제어
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
SIM_TIME = 330.0  # 2차 열차 도착 후 잔류 에이전트 완전 소화 여유
DT = 0.05

# =============================================================================
# 도착 모델
# =============================================================================
TRAIN_INTERVAL = 180.0
TRAIN_ALIGHTING = 40
PLATOON_SPREAD = 15.0
FIRST_TRAIN_TIME = 5.0

# =============================================================================
# 보행자 속도 파라미터
# =============================================================================
PED_SPEED_MEAN = 1.34
PED_SPEED_STD = 0.26
PED_SPEED_MIN = 0.8
PED_SPEED_MAX = 1.5

# =============================================================================
# CFSM V2 에이전트 파라미터 (Tordeux et al., 2016)
# =============================================================================
CFSM_TIME_GAP = 0.80      # 시간 간격 (s) — 병목 유량 캘리브레이션 결과 (Tordeux 원논문: 1.06)
CFSM_RADIUS = 0.15        # 보행자 반경 (m)

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

# 게이트 통과 구간
GATE_ZONE_X_START = GATE_X - 0.3
GATE_ZONE_X_END = GATE_X + GATE_LENGTH + 0.3

# 대기열 제어
QUEUE_STOP_DIST = 1.0     # 게이트 1m 전에서 대기 (0.5m → 1.0m: 통로 진입 방지)
QUEUE_FOLLOW_DIST = 5.0
LEADER_FOLLOW_GAP = 0.6
QUEUE_MIN_SPEED = 0.0    # CFSM: 완전 정지 가능 (GCFM과 달리 벽 반발 불필요)

OUTPUT_DIR = pathlib.Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


# =============================================================================
# 유틸 함수
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
    if actual_count <= 3:
        return actual_count
    elif actual_count <= 5:
        return actual_count + rng.choice([-1, 0, 1])
    else:
        return max(0, actual_count + rng.choice([-2, -1, 0, 1, 2]))


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


def find_leader(agent_pos, gate_idx, sim, agent_data, in_service, my_id):
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
        if ox > my_x:
            if best_x is None or ox < best_x:
                best_x = ox
                best_pos = (ox, oy)
    return best_pos


# =============================================================================
# 속도 제어 헬퍼 — CFSM V2에서 v0 접근
# =============================================================================
def set_agent_speed(agent, speed):
    """CFSM V2 에이전트의 희망 속도를 설정한다."""
    agent.model.desired_speed = speed


def get_agent_speed(agent):
    """CFSM V2 에이전트의 현재 희망 속도를 반환한다."""
    return agent.model.desired_speed


# =============================================================================
# 시뮬레이션 생성 (CFSM V2, 배리어 포함 기하구조)
# =============================================================================
def create_simulation():
    gates = calculate_gate_positions()

    # 기하구조: 배리어 포함 + 넓은 통로 (우회 방지 + 낑김 방지)
    # - 물리적 벽: 게이트 사이를 막아서 우회 불가
    # - 넓은 통로(1.2m): CFSM 에이전트가 자유롭게 통과 (낑김 없음)
    # - 실제 처리량: 서비스 시간 모델이 제어 (물리적 폭이 아님)
    SIM_PASSAGE_WIDTH = 0.70  # 시뮬레이션용 통로 폭 (실제 0.55m → 0.70m, 벽 0.15m 유지)
    walkable, _, _ = build_geometry(gates, include_barrier=True,
                                    passage_width_override=SIM_PASSAGE_WIDTH)
    # 시각화용: 실제 폭(0.55m)으로 표시
    _, vis_obstacles, gate_openings = build_geometry(gates, include_barrier=True)

    # CFSM V2 — 반발력 파라미터는 에이전트별 설정 (모델 자체는 파라미터 없음)
    model = jps.CollisionFreeSpeedModelV2()

    sim = jps.Simulation(model=model, geometry=walkable, dt=DT)

    gate_x_end = GATE_X + GATE_LENGTH

    # 1단계: 접근 Waypoint (게이트 전방)
    approach_wp_ids = []
    for g in gates:
        wp_id = sim.add_waypoint_stage((8.0, g["y"]), 1.0)
        approach_wp_ids.append(wp_id)

    # 2단계: 게이트 입구 Waypoint
    gate_wp_ids = []
    for g in gates:
        wp_id = sim.add_waypoint_stage((GATE_X, g["y"]), 0.4)
        gate_wp_ids.append(wp_id)

    # 3단계: 게이트 출구 Waypoint (에이전트가 물리적으로 통과하는 지점)
    post_gate_wp_ids = []
    for g in gates:
        wp_id = sim.add_waypoint_stage((gate_x_end + 1.0, g["y"]), 1.5)
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

    # 게이트별 Journey: approach → gate → post_gate → exit
    journey_ids = []
    for i, g in enumerate(gates):
        target_exit = exit_upper if g["y"] > CONCOURSE_WIDTH / 2 else exit_lower
        journey = jps.JourneyDescription([
            approach_wp_ids[i], gate_wp_ids[i],
            post_gate_wp_ids[i], exit_upper, exit_lower
        ])
        journey.set_transition_for_stage(
            approach_wp_ids[i],
            jps.Transition.create_fixed_transition(gate_wp_ids[i]))
        journey.set_transition_for_stage(
            gate_wp_ids[i],
            jps.Transition.create_fixed_transition(post_gate_wp_ids[i]))
        journey.set_transition_for_stage(
            post_gate_wp_ids[i],
            jps.Transition.create_fixed_transition(target_exit))
        jid = sim.add_journey(journey)
        journey_ids.append(jid)

    mid_gate = N_GATES // 2
    default_journey_id = journey_ids[mid_gate]
    default_stage_id = approach_wp_ids[mid_gate]

    return (sim, gates, walkable, vis_obstacles, gate_openings,
            approach_wp_ids, gate_wp_ids, post_gate_wp_ids, journey_ids,
            default_journey_id, default_stage_id,
            exit_upper, exit_lower)


# =============================================================================
# 시뮬레이션 실행
# =============================================================================
def run_simulation():
    print("=" * 60)
    print("성수역 서쪽 대합실 시뮬레이션 (CFSM V2)")
    print(f"  물리 엔진: CollisionFreeSpeedModelV2 (Tordeux et al., 2016)")
    print(f"  게이트 통과: waypoint 기반 속도 제어 (물리적 통과)")
    print(f"  게이트 선택: Gao (2019) LRP 모델")
    print(f"  3단계 재선택: {CHOICE_DIST_1ST}m / {CHOICE_DIST_2ND}m / {CHOICE_DIST_3RD}m")
    print(f"  서비스시간(태그): 평균 {SERVICE_TIME_MEAN}s")
    print(f"  태그리스 비율: {TAGLESS_RATIO*100:.0f}%")
    print(f"  희망속도: N({PED_SPEED_MEAN}, {PED_SPEED_STD})")
    print(f"  CFSM V2: time_gap={CFSM_TIME_GAP}s, radius={CFSM_RADIUS}m")
    print("=" * 60)

    (sim, gates, walkable, obstacles, gate_openings,
     approach_wp_ids, gate_wp_ids, post_gate_wp_ids, journey_ids,
     default_journey_id, default_stage_id,
     exit_upper, exit_lower) = create_simulation()

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

        # ── 보행자 생성 ──
        while (arrival_idx < len(arrival_times) and
               arrival_times[arrival_idx] <= current_time):
            stair = STAIRS[rng.integers(0, len(STAIRS))]
            desired_speed = np.clip(
                rng.normal(PED_SPEED_MEAN, PED_SPEED_STD),
                PED_SPEED_MIN, PED_SPEED_MAX)

            temperament = assign_temperament(rng)
            is_tagless = rng.random() < TAGLESS_RATIO

            spawned = False
            for retry in range(5):
                spawn_x = stair["x"] + rng.uniform(0.5, 2.5)
                spawn_y = rng.uniform(stair["y_start"], stair["y_end"])
                if retry > 0:
                    spawn_x += rng.uniform(0.5, 2.0)
                    spawn_y += rng.uniform(-1.0, 1.0)
                    spawn_y = np.clip(spawn_y, 2.0, NOTCH_Y - 2.0)

                dist_to_gate = GATE_X - spawn_x
                if dist_to_gate <= CHOICE_DIST_1ST:
                    gate_queue = count_gate_queue(sim, gates, agent_data)
                    gate_idx = choose_gate_lrp(
                        rng, (spawn_x, spawn_y), desired_speed, temperament,
                        gates, gate_queue, stage="1st")
                    choice_stage = 1
                    jid = journey_ids[gate_idx]
                    sid = approach_wp_ids[gate_idx]
                else:
                    gate_idx = -1
                    choice_stage = 0
                    jid = default_journey_id
                    sid = default_stage_id

                try:
                    # CFSM V2 에이전트 파라미터 — Tordeux et al. (2016)
                    agent_id = sim.add_agent(
                        jps.CollisionFreeSpeedModelV2AgentParameters(
                            journey_id=jid,
                            stage_id=sid,
                            position=(spawn_x, spawn_y),
                            time_gap=CFSM_TIME_GAP,
                            desired_speed=desired_speed,
                            radius=CFSM_RADIUS,
                            strength_neighbor_repulsion=8.0,
                            range_neighbor_repulsion=0.1,
                            strength_geometry_repulsion=5.0,
                            range_geometry_repulsion=0.02,
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
                        "state": "flowing",
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
                arrival_times.insert(arrival_idx + 1, current_time + DT * 2)

            arrival_idx += 1

        # ── 게이트 점유 상태 ──
        # in_service(서비스 중) + in_gate_walking(통로 통과 중) 모두 점유로 처리
        # CFSM에서 0.55m 통로에 2명이 동시 진입하면 교착(deadlock) 발생
        gate_occupied = [False] * N_GATES
        for aid_s in in_service:
            gi = agent_data[aid_s]["gate_idx"]
            if gi >= 0:
                gate_occupied[gi] = True
        for agent in sim.agents():
            aid = agent.id
            if aid in agent_data and agent_data[aid]["state"] == "in_gate_walking":
                gi = agent_data[aid]["gate_idx"]
                if gi >= 0:
                    gate_occupied[gi] = True

        # ── 서비스 완료 체크: AnyLogic Linear Service 방식 ──
        # Phase 1: 서비스 시간 만료 → 게이트 출구 waypoint로 걸어서 이동
        finished_aids = []
        for aid_s, svc in in_service.items():
            if current_time - svc["start"] >= svc["duration"]:
                finished_aids.append(aid_s)
        for aid_s in finished_aids:
            if aid_s in agent_data:
                ad_s = agent_data[aid_s]
                gi_s = ad_s["gate_idx"]
                # 서비스 시간 완료 → 게이트 출구까지 걸어서 나감 (텔레포트 X)
                ad_s["state"] = "in_gate_walking"
                ad_s["gate_walk_start"] = current_time
                stats["service_times"].append(in_service[aid_s]["duration"])
                gate_occupied[gi_s] = False  # 게이트 해제 (다음 사람 진입 가능)
                for agent in sim.agents():
                    if agent.id == aid_s:
                        set_agent_speed(agent, GATE_PASS_SPEED)  # 0.65 m/s로 걸어나감
                        try:
                            sim.switch_agent_journey(
                                aid_s, journey_ids[gi_s], post_gate_wp_ids[gi_s])
                        except Exception:
                            pass
                        break
            del in_service[aid_s]

        # Phase 2: 게이트 출구 통과 완료 체크 (물리적으로 게이트를 빠져나갔는지)
        gate_x_end = GATE_X + GATE_LENGTH
        for agent in sim.agents():
            aid = agent.id
            if aid not in agent_data:
                continue
            ad = agent_data[aid]
            if ad["state"] != "in_gate_walking":
                continue
            px, py = agent.position
            # 게이트 출구(x_end) 넘어갔으면 → 서비스 완전 완료
            if px > gate_x_end + 0.3:
                gi_s = ad["gate_idx"]
                ad["serviced"] = True
                ad["state"] = "done"
                if gi_s >= 0:
                    stats["gate_counts"][gi_s] += 1
                set_agent_speed(agent, ad["original_speed"])
                gy = gates[gi_s]["y"]
                target_exit = exit_upper if gy > CONCOURSE_WIDTH / 2 else exit_lower
                try:
                    sim.switch_agent_journey(
                        aid, journey_ids[gi_s], target_exit)
                except Exception:
                    pass

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

            # 게이트 통과 중인 에이전트는 건드리지 않음
            if ad["state"] == "in_gate_walking":
                continue

            # ── Phase 0: Influence Zone 진입 ──
            if ad["choice_stage"] == 0 and dist_to_gate <= CHOICE_DIST_1ST:
                gate_idx_new = choose_gate_lrp(
                    rng, (px, py), ad["original_speed"], ad["temperament"],
                    gates, gate_queue, stage="1st")
                ad["gate_idx"] = gate_idx_new
                ad["choice_stage"] = 1
                if px >= 7.0:
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
                continue

            # ── Phase 1: 게이트 구간 (서비스 영역) ──
            if GATE_ZONE_X_START <= px <= GATE_ZONE_X_END:
                # 물리적 위치 기반 게이트 보정
                if aid not in in_service:
                    dists_to_gates = [abs(py - g["y"]) for g in gates]
                    nearest_gate = int(np.argmin(dists_to_gates))
                    if nearest_gate != gi:
                        gi = nearest_gate
                        ad["gate_idx"] = gi
                        try:
                            sim.switch_agent_journey(
                                aid, journey_ids[gi], post_gate_wp_ids[gi])
                        except Exception:
                            pass

                # 게이트 점유 중이면 진입 불가 — 정지 후 대기
                if gate_occupied[gi] and aid not in in_service:
                    set_agent_speed(agent, QUEUE_MIN_SPEED)
                    ad["state"] = "queuing"
                    continue

                # 태그리스: 일반 보행속도로 게이트를 걸어서 통과 (무정지)
                if ad["is_tagless"] and aid not in in_service:
                    ad["state"] = "in_gate_walking"
                    ad["gate_walk_start"] = current_time
                    stats["service_times"].append(0.0)
                    gate_occupied[gi] = True  # 태그리스도 통과 중 점유
                    set_agent_speed(agent, ad["original_speed"])
                    try:
                        sim.switch_agent_journey(
                            aid, journey_ids[gi], post_gate_wp_ids[gi])
                    except Exception:
                        pass
                    continue

                # 태그 사용자: 서비스 시작 (속도 감소하며 통과)
                if aid not in in_service:
                    ad["state"] = "in_gate"
                    set_agent_speed(agent, GATE_PASS_SPEED)
                    in_service[aid] = {
                        "start": current_time,
                        "duration": ad["service_time"],
                    }
                    gate_occupied[gi] = True
                continue

            # ── Phase 2: 대기열 구간 ──
            if 0 < dist_to_gate < QUEUE_FOLLOW_DIST:
                if dist_to_gate <= QUEUE_STOP_DIST and gate_occupied[gi]:
                    set_agent_speed(agent, QUEUE_MIN_SPEED)
                    ad["state"] = "queuing"
                elif dist_to_gate <= QUEUE_STOP_DIST and not gate_occupied[gi]:
                    set_agent_speed(agent, ad["original_speed"])
                    ad["state"] = "flowing"
                else:
                    leader_pos = find_leader(
                        (px, py), gi, sim, agent_data, in_service, aid)
                    if leader_pos is not None:
                        gap = leader_pos[0] - px
                        if gap < LEADER_FOLLOW_GAP:
                            set_agent_speed(agent, max(
                                QUEUE_MIN_SPEED,
                                ad["original_speed"] * (gap / LEADER_FOLLOW_GAP)))
                            ad["state"] = "queuing"
                        else:
                            set_agent_speed(agent, ad["original_speed"])
                            ad["state"] = "flowing"
                    else:
                        set_agent_speed(agent, ad["original_speed"])
                        ad["state"] = "flowing"
            else:
                ad["state"] = "flowing"

        # ── 대기열 복구 ──
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
            if ad["state"] == "queuing" and get_agent_speed(agent) < 0.1:
                if not gate_occupied[gi]:
                    set_agent_speed(agent, ad["original_speed"])
                    ad["state"] = "flowing"

        # ── 안전장치: in_gate_walking 교착 해소 ──
        GATE_WALK_TIMEOUT = 15.0  # 15초 이상 게이트 통과 중이면 강제 완료
        for agent in sim.agents():
            aid = agent.id
            if aid not in agent_data:
                continue
            ad = agent_data[aid]
            if ad["state"] != "in_gate_walking":
                continue
            # in_gate_walking 진입 시간 기록
            if "gate_walk_start" not in ad:
                ad["gate_walk_start"] = current_time
            elif current_time - ad["gate_walk_start"] > GATE_WALK_TIMEOUT:
                gi_s = ad["gate_idx"]
                ad["serviced"] = True
                ad["state"] = "done"
                if gi_s >= 0:
                    stats["gate_counts"][gi_s] += 1
                set_agent_speed(agent, ad["original_speed"])
                gy = gates[gi_s]["y"]
                target_exit = exit_upper if gy > CONCOURSE_WIDTH / 2 else exit_lower
                try:
                    sim.switch_agent_journey(aid, journey_ids[gi_s], target_exit)
                except Exception:
                    pass

        # ── 안전장치: 일반 ──
        STUCK_TIMEOUT = 60.0
        for agent in sim.agents():
            aid = agent.id
            if aid not in agent_data:
                continue
            ad = agent_data[aid]
            if ad["serviced"] or aid in in_service:
                continue
            age = current_time - ad["spawn_time"]
            if age > STUCK_TIMEOUT and ad["gate_idx"] >= 0:
                if get_agent_speed(agent) < 0.1:
                    set_agent_speed(agent, ad["original_speed"])
                    ad["state"] = "flowing"

        # ── 경로 변경: Gao (2019) ──
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
                  f"| 3rd: {stats['stage3_triggers']}")

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

    # 미통과 진단
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
                              f"state={ad['state']}")
                        break
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

    # 배리어 (시각화용)
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
        ax.fill(ox, oy, color='#66BB6A', edgecolor='#2E7D32', linewidth=0.8, alpha=0.5, zorder=3)

    for g in gates:
        ax.text(g["x"] + GATE_LENGTH / 2, g["y"], str(g["id"] + 1),
                ha='center', va='center', fontsize=7, fontweight='bold', color='#1B5E20', zorder=4)

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
    fig.suptitle('성수역 서쪽 대합실 (CFSM V2)',
                 fontsize=16, fontweight='bold')
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "snapshots_cfsm.png", dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  스냅샷: {OUTPUT_DIR / 'snapshots_cfsm.png'}")


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
        ax.set_title(f'성수역 서쪽 (CFSM V2) | t = {t:.1f}s | {len(positions)} agents',
                     fontsize=12, fontweight='bold')

    anim = FuncAnimation(fig, animate, frames=len(target_frames), interval=200)
    gif_path = OUTPUT_DIR / "simulation_cfsm.gif"
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
    ax.set_title('게이트별 대기 인원 변화 (CFSM V2)')
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "queue_history_cfsm.png", dpi=150)
    plt.close(fig)
    print(f"  대기열: {OUTPUT_DIR / 'queue_history_cfsm.png'}")


def plot_service_time_dist(service_times):
    if not service_times:
        return
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(service_times, bins=25, color='#42A5F5', edgecolor='#1565C0', alpha=0.8)
    ax.axvline(np.mean(service_times), color='red', linestyle='--',
               label=f'평균: {np.mean(service_times):.2f}s')
    ax.set_xlabel('서비스 시간 (초)')
    ax.set_ylabel('빈도')
    ax.set_title('개찰구 서비스 시간 분포 (CFSM V2)')
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "service_time_cfsm.png", dpi=150)
    plt.close(fig)
    print(f"  서비스시간: {OUTPUT_DIR / 'service_time_cfsm.png'}")


# =============================================================================
# 자동 평가
# =============================================================================
def evaluate_simulation(stats, spawned_count, sim_time):
    print("\n" + "=" * 60)
    print("시뮬레이션 평가 결과 (CFSM V2)")
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
            issues.append(f"게이트 {zero_gates} 미사용")

    if stats["service_times"]:
        st = np.array(stats["service_times"])
        tag_times = st[st > 0]
        if len(tag_times) > 0:
            mean_st = tag_times.mean()
            status = "PASS" if 1.5 <= mean_st <= 2.5 else "WARN"
            print(f"[{status}] 태그 서비스시간: 평균 {mean_st:.2f}s "
                  f"(Gao 실측: 2.0s, 범위 {tag_times.min():.2f}~{tag_times.max():.2f}s)")

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
        print(f"종합: {severity}")
        for issue in issues:
            print(f"  - {issue}")
    print("=" * 60)
    return issues


if __name__ == "__main__":
    stats, spawned_count = run_simulation()
    evaluate_simulation(stats, spawned_count, SIM_TIME)
