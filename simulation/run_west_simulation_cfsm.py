"""
성수역 서쪽 대합실 양방향 시뮬레이션 (하차 + 승차)

run_demo.py 를 양방향으로 확장한 버전:
- 게이트별 방향 속성 (in/out): 단방향 분리 운영
- 하차류: 계단 → 게이트(out) → 출구
- 승차류: 출구 → 게이트(in) → 계단
- 모든 큐 로직(꼬리 흡수, 동적 wp, 시프트, jockeying, 동적 time_gap) 그대로
- 큐 head 위치만 방향별로 분리:
    out: HEAD = GATE_X - 0.3 (좌측)
    in : HEAD = GATE_X + GATE_LENGTH + 0.3 (우측)
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
    STAIRS, EXITS, STRUCTURES, N_GATES, EXIT_STAIR_WIDTH,
)

plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

# =============================================================================
# 시뮬레이션 파라미터
# =============================================================================
SIM_TIME = 360.0  # 데모: 열차 2편
DT = 0.05

# =============================================================================
# 양방향 운영 파라미터
# =============================================================================
# 게이트 방향 분배 (단방향 분리 운영)
# 'out': 하차 전용, 'in': 승차 전용
# 성수역 첨두 기준 — 하차가 압도적이므로 out 비율 ↑
GATE_DIRECTIONS = ['in', 'in', 'out', 'out', 'out', 'out', 'out']
INBOUND_GATES  = [i for i, d in enumerate(GATE_DIRECTIONS) if d == 'in']
OUTBOUND_GATES = [i for i, d in enumerate(GATE_DIRECTIONS) if d == 'out']

# 승차 도착률 (성수역 08-09시 970명/h ÷ 60 = 16.2명/min ÷ 60 = 0.27 ped/s)
INBOUND_RATE = 16.2 / 60.0   # ped/s, 균일 NHPP

# =============================================================================
# 도착 모델
# =============================================================================
TRAIN_INTERVAL = 180.0
TRAIN_ALIGHTING = 150  # 데모: 축소
PLATOON_SPREAD = 50.0  # (미사용, 물리 기반으로 대체)

# 성수역 물리 기반 도착 모델 파라미터
PLATFORM_LENGTH = 105.0       # 승강장 길이 (m)
ALIGHTING_DELAY_MAX = 10.0    # 하차 지연 최대 (s)
STAIR_DESCENT_TIME = 12.0     # 계단 하행 시간 (s) — ~10m, 0.85m/s
STAIR_TO_GATE_DIST = 11.0     # 계단 하부 → 게이트 구간 거리 (m)
WALK_SPEED_MEAN = 1.34        # 플랫폼 보행속도 평균 (m/s)
WALK_SPEED_STD = 0.26         # 플랫폼 보행속도 표준편차 (m/s)
FIRST_TRAIN_TIME = 5.0

# 계단 방출율 (Weidmann 1993: 1.25명/s/m, 하행)
STAIR_WIDTH = 3.7             # 성수역 계단 폭 (도면 계측)
STAIR_DISCHARGE_RATE = 1.25   # Weidmann 하행 최대
STAIR_CAPACITY = STAIR_WIDTH * STAIR_DISCHARGE_RATE  # ~4.6명/s per stair

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
CFSM_TIME_GAP = 0.80      # 시간 간격 (s) — 기본값 (밀도 기반 동적 조정)
CFSM_RADIUS = 0.15        # 보행자 반경 (m)

# 밀도 기반 동적 time_gap 파라미터
DYNAMIC_TIME_GAP = True
TIME_GAP_LOW  = 1.5    # 저밀도 (< 0.5 ped/m²): 넓은 간격
TIME_GAP_MID  = 1.0    # 중밀도 (0.5~1.5 ped/m²)
TIME_GAP_HIGH = 0.7    # 고밀도 (> 1.5 ped/m²): 촘촘한 간격
DENSITY_R = 2.0         # 밀도 측정 반경 (m)

# =============================================================================
# 서비스 시간 파라미터 (Gao et al., 2019)
# =============================================================================
SERVICE_TIME_MEAN = 2.0
SERVICE_TIME_MIN = 0.8
SERVICE_TIME_MAX = 3.7
CARD_FEEDING_TIME = 1.1
GATE_PASS_SPEED = 0.65
GATE_PHYS_LENGTH = 1.4

TAGLESS_SERVICE_TIME = 1.2    # 게이트 물리 통과 시간 (1.5m / 1.3m/s)
TAGLESS_RATIO = 0.0           # 데모: 태그 전용 (baseline)

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
CHOICE_DIST_1ST = 3.0   # 계단 직후 선택 (x~3~4에서 발동) -> 처음부터 해당 게이트로 직행
CHOICE_DIST_2ND = 1.7   # 조건부 재선택 (대기열 3명+ 일 때만)

# 대기열 내 재선택 (LRP)
QUEUE_RESELECT_ENABLED = True   # 큐 내 인접 게이트 조건부 jockeying
QUEUE_RESELECT_INTERVAL = 1.0   # 재선택 판단 주기 (초)
QUEUE_RESELECT_MIN_QUEUE = 3    # 현재 큐 최소 인원 (이상일 때만 재선택 고려)
QUEUE_RESELECT_MIN_DIFF = 2     # 새 큐가 이만큼 짧아야 이동
CHOICE_DIST_3RD = 1.0   # 제거됨 (사용 안 함)

# 게이트 통과 구간
GATE_ZONE_X_START = GATE_X - 0.3
GATE_ZONE_X_END = GATE_X + GATE_LENGTH + 0.3

# 소프트웨어 큐 파라미터
QUEUE_HEAD_X = GATE_X - 0.3   # 큐 head 위치 (게이트 0.3m 앞)
QUEUE_SPACING = 0.5            # 대기 간격
QUEUE_MAX_LENGTH = 999         # 큐 제한 없음
MAX_QUEUE_DEPTH_WP = 25        # 동적 waypoint 최대 큐 깊이
QUEUE_SHIFT_DURATION = 0.5     # 큐 시프트 모션 시간 (s) — head pop 시 보간


def ease_in_out(t):
    """t in [0,1] -> smoothstep"""
    if t <= 0:
        return 0.0
    if t >= 1:
        return 1.0
    return t * t * (3 - 2 * t)

OUTPUT_DIR = pathlib.Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


# =============================================================================
# 유틸 함수
# =============================================================================
def generate_arrival_schedule(rng, sim_time):
    """양방향 도착 스케줄 (하차 + 승차).

    하차류: 열차 도착 펄스 (run_demo.py 와 동일)
    승차류: 균일 NHPP (분당 16명, 출구에서 spawn)

    Returns: list of (time, kind, info) tuples
        kind='out': info=stair_idx
        kind='in':  info=spawn_y (출구 부근 y좌표)
    """
    min_gap = 1.0 / STAIR_CAPACITY

    arrivals = []

    # ── 하차류 (열차별 펄스) ──
    train_time = FIRST_TRAIN_TIME
    train_count = 0
    while train_time < sim_time:
        n_passengers = rng.poisson(TRAIN_ALIGHTING)
        stair_idx = train_count % 2

        times = []
        for _ in range(n_passengers):
            pos_on_platform = rng.uniform(0, PLATFORM_LENGTH)
            dist_to_stair = min(pos_on_platform, PLATFORM_LENGTH - pos_on_platform)
            walk_speed = max(0.8, rng.normal(WALK_SPEED_MEAN, WALK_SPEED_STD))
            alighting_delay = rng.uniform(0, ALIGHTING_DELAY_MAX)
            t_platform_walk = dist_to_stair / walk_speed
            t_stair_descent = STAIR_DESCENT_TIME
            t_stair_to_gate = STAIR_TO_GATE_DIST / walk_speed
            raw_t = train_time + alighting_delay + t_platform_walk + t_stair_descent + t_stair_to_gate
            times.append(raw_t)
        times.sort()

        for j in range(1, len(times)):
            earliest = times[j - 1] + min_gap
            if times[j] < earliest:
                times[j] = earliest

        for t in times:
            if t < sim_time:
                arrivals.append((t, 'out', stair_idx))

        train_time += TRAIN_INTERVAL
        train_count += 1

    # ── 승차류 (균일 NHPP, 출구에서 spawn) ──
    t = 0.0
    while t < sim_time:
        t += rng.exponential(1.0 / INBOUND_RATE)
        if t < sim_time:
            # 두 출구 중 무작위 (upper=0, lower=1)
            exit_idx = int(rng.choice([0, 1]))
            arrivals.append((t, 'in', exit_idx))

    arrivals.sort(key=lambda x: x[0])
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
                    current_gate_idx=None, allowed_gates=None):
    """LRP 게이트 선택. allowed_gates 가 주어지면 그 안에서만 선택 (방향 분리)."""
    omega = TEMPERAMENTS[temperament]
    omega_wait = omega["omega_wait"]
    omega_walk = omega["omega_walk"]
    n_gates = len(gates)

    if allowed_gates is None:
        allowed_gates = list(range(n_gates))

    if stage == "3rd":
        if (current_gate_idx is not None and gate_occupied is not None
                and gate_occupied[current_gate_idx]):
            candidates = []
            for delta in [-1, 1]:
                adj = current_gate_idx + delta
                if adj in allowed_gates and not gate_occupied[adj]:
                    d = abs(agent_pos[1] - gates[adj]["y"])
                    candidates.append((d, adj))
            if candidates:
                candidates.sort()
                return candidates[0][1]
        return current_gate_idx if current_gate_idx is not None else allowed_gates[0]

    l1_actual = np.array([
        np.hypot(agent_pos[0] - g["x"], agent_pos[1] - g["y"])
        for g in gates
    ])
    l1_est = estimate_distances_with_order_preservation(rng, l1_actual)

    costs = np.full(n_gates, np.inf)
    for j in allowed_gates:
        gate = gates[j]
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

    # softmax over allowed
    allowed_costs = costs[allowed_gates]
    shifted = allowed_costs - np.min(allowed_costs)
    exp_neg = np.exp(-shifted)
    probs = exp_neg / exp_neg.sum()
    return int(allowed_gates[int(rng.choice(len(allowed_gates), p=probs))])


# =============================================================================
# 시뮬레이션 생성 (CFSM V2, 소프트웨어 큐 기반)
# =============================================================================
def create_simulation():
    """양방향 시뮬레이션 생성.

    게이트 방향(out/in)에 따라:
    - out (하차): wp가 게이트 좌측 (x < GATE_X), 큐 head = GATE_X - 0.3
    - in  (승차): wp가 게이트 우측 (x > GATE_X+LEN), 큐 head = GATE_X + LEN + 0.3
    """
    gates = calculate_gate_positions()

    walkable, _, _ = build_geometry(gates, include_barrier=False)
    _, vis_obstacles, gate_openings = build_geometry(gates, include_barrier=True)

    model = jps.CollisionFreeSpeedModelV2()
    sim = jps.Simulation(model=model, geometry=walkable, dt=DT)

    gate_x_end = GATE_X + GATE_LENGTH
    QH_OUT = GATE_X - 0.3
    QH_IN  = gate_x_end + 0.3

    # 1단계: 접근 Waypoint (방향에 따라 좌/우)
    approach_wp_grid = []  # [gate][depth] -> wp_id
    for i, g in enumerate(gates):
        d = GATE_DIRECTIONS[i]
        gate_wps = []
        for depth in range(MAX_QUEUE_DEPTH_WP + 1):
            if d == 'out':
                wp_x = (QH_OUT - 0.8) if depth == 0 else (QH_OUT - depth * QUEUE_SPACING - 0.8)
                wp_x = max(wp_x, 2.0)
            else:  # 'in'
                wp_x = (QH_IN + 0.8) if depth == 0 else (QH_IN + depth * QUEUE_SPACING + 0.8)
                wp_x = min(wp_x, CONCOURSE_LENGTH - 2.0)
            wp_id = sim.add_waypoint_stage((wp_x, g["y"]), 0.5)
            gate_wps.append(wp_id)
        approach_wp_grid.append(gate_wps)
    approach_wp_ids = [approach_wp_grid[i][0] for i in range(N_GATES)]

    # 2단계: 게이트 통과 후 Waypoint
    # out: 우측 (출구 방향)  /  in: 좌측 (계단 방향)
    post_gate_wp_ids = []
    for i, g in enumerate(gates):
        d = GATE_DIRECTIONS[i]
        if d == 'out':
            wp_id = sim.add_waypoint_stage((gate_x_end + 0.5, g["y"]), 0.5)
        else:
            wp_id = sim.add_waypoint_stage((GATE_X - 0.5, g["y"]), 0.5)
        post_gate_wp_ids.append(wp_id)

    # 출구 (하차류 도착지) — 통로 폭에 맞춰서 exit stage 설정
    _ecx = (EXITS[0]["x_start"] + EXITS[0]["x_end"]) / 2  # 27.5
    _euw = EXIT_STAIR_WIDTH / 2                             # 1.25
    exit_upper = sim.add_exit_stage(Polygon([
        (_ecx - _euw, EXITS[0]["y"] - 0.5),
        (_ecx + _euw, EXITS[0]["y"] - 0.5),
        (_ecx + _euw, EXITS[0]["y"] + 0.5),
        (_ecx - _euw, EXITS[0]["y"] + 0.5),
    ]))
    exit_lower = sim.add_exit_stage(Polygon([
        (_ecx - _euw, EXITS[1]["y"] - 0.5),
        (_ecx + _euw, EXITS[1]["y"] - 0.5),
        (_ecx + _euw, EXITS[1]["y"] + 0.5),
        (_ecx - _euw, EXITS[1]["y"] + 0.5),
    ]))

    # 계단 (승차류 도착지) — 작은 polygon으로 exit stage 등록
    stair_exits = []
    for stair in STAIRS:
        eid = sim.add_exit_stage(Polygon([
            (stair["x"] - 0.4, stair["y_start"]),
            (stair["x"] + 0.4, stair["y_start"]),
            (stair["x"] + 0.4, stair["y_end"]),
            (stair["x"] - 0.4, stair["y_end"]),
        ]))
        stair_exits.append(eid)

    # 출구 통로 입구 Waypoint: 에이전트를 벽 모서리가 아닌 통로 중앙으로 유도
    # upper 통로 입구: (27.5, 22.5)  — 통로 y하단 근처
    # lower 통로 입구: (27.5, 4.5)   — 통로 y상단 근처
    exit_guide_upper = sim.add_waypoint_stage((_ecx, EXITS[0]["y"] - 1.5), 1.0)
    exit_guide_lower = sim.add_waypoint_stage((_ecx, EXITS[1]["y"] + 1.5), 1.0)

    # 접근 Journey: 큐 깊이별 동적 waypoint → post_gate → (출구 가이드) → 도착지
    journey_grid = []  # [gate][depth] -> journey_id
    for i, g in enumerate(gates):
        d = GATE_DIRECTIONS[i]
        if d == 'out':
            target = exit_upper if g["y"] > CONCOURSE_WIDTH / 2 else exit_lower
            guide = exit_guide_upper if g["y"] > CONCOURSE_WIDTH / 2 else exit_guide_lower
        else:
            target = stair_exits[0] if g["y"] > CONCOURSE_WIDTH / 2 else stair_exits[1]
            guide = None
        gate_jids = []
        for depth in range(MAX_QUEUE_DEPTH_WP + 1):
            wp_id = approach_wp_grid[i][depth]
            if guide:
                # 하차: approach → post_gate → 출구 가이드 → exit
                journey = jps.JourneyDescription([
                    wp_id, post_gate_wp_ids[i], guide, target
                ])
                journey.set_transition_for_stage(
                    wp_id,
                    jps.Transition.create_fixed_transition(post_gate_wp_ids[i]))
                journey.set_transition_for_stage(
                    post_gate_wp_ids[i],
                    jps.Transition.create_fixed_transition(guide))
                journey.set_transition_for_stage(
                    guide,
                    jps.Transition.create_fixed_transition(target))
            else:
                # 승차: approach → post_gate → 계단
                journey = jps.JourneyDescription([
                    wp_id, post_gate_wp_ids[i], target
                ])
                journey.set_transition_for_stage(
                    wp_id,
                    jps.Transition.create_fixed_transition(post_gate_wp_ids[i]))
                journey.set_transition_for_stage(
                    post_gate_wp_ids[i],
                    jps.Transition.create_fixed_transition(target))
            jid = sim.add_journey(journey)
            gate_jids.append(jid)
        journey_grid.append(gate_jids)
    journey_ids = [journey_grid[i][0] for i in range(N_GATES)]

    # Post-gate only Journey: 서비스 완료 후 재투입용
    post_journey_ids = []
    for i, g in enumerate(gates):
        d = GATE_DIRECTIONS[i]
        if d == 'out':
            target = exit_upper if g["y"] > CONCOURSE_WIDTH / 2 else exit_lower
            guide = exit_guide_upper if g["y"] > CONCOURSE_WIDTH / 2 else exit_guide_lower
            journey = jps.JourneyDescription([post_gate_wp_ids[i], guide, target])
            journey.set_transition_for_stage(
                post_gate_wp_ids[i],
                jps.Transition.create_fixed_transition(guide))
            journey.set_transition_for_stage(
                guide,
                jps.Transition.create_fixed_transition(target))
        else:
            target = stair_exits[0] if g["y"] > CONCOURSE_WIDTH / 2 else stair_exits[1]
            journey = jps.JourneyDescription([post_gate_wp_ids[i], target])
            journey.set_transition_for_stage(
                post_gate_wp_ids[i],
                jps.Transition.create_fixed_transition(target))
        jid = sim.add_journey(journey)
        post_journey_ids.append(jid)

    # 기본 journey: 하차류는 OUTBOUND 중간, 승차류는 INBOUND 중간
    default_out_gate = OUTBOUND_GATES[len(OUTBOUND_GATES) // 2]
    default_in_gate  = INBOUND_GATES[len(INBOUND_GATES) // 2]

    return (sim, gates, walkable, vis_obstacles, gate_openings,
            approach_wp_ids, approach_wp_grid, post_gate_wp_ids,
            journey_ids, journey_grid, post_journey_ids,
            default_out_gate, default_in_gate,
            exit_upper, exit_lower, stair_exits)


# =============================================================================
# 시뮬레이션 실행
# =============================================================================
def run_simulation():
    print("=" * 60)
    print("성수역 서쪽 대합실 시뮬레이션 (CFSM V2, 소프트웨어 큐)")
    print(f"  물리 엔진: CollisionFreeSpeedModelV2 (Tordeux et al., 2016)")
    print(f"  게이트 통과: 소프트웨어 큐 + 서비스 시간 모델")
    print(f"  게이트 선택: Gao (2019) LRP 모델")
    print(f"  3단계 재선택: {CHOICE_DIST_1ST}m / {CHOICE_DIST_2ND}m / {CHOICE_DIST_3RD}m")
    print(f"  서비스시간(태그): 평균 {SERVICE_TIME_MEAN}s")
    print(f"  태그리스 비율: {TAGLESS_RATIO*100:.0f}%")
    print(f"  희망속도: N({PED_SPEED_MEAN}, {PED_SPEED_STD})")
    print(f"  CFSM V2: time_gap={CFSM_TIME_GAP}s, radius={CFSM_RADIUS}m")
    print("=" * 60)

    (sim, gates, walkable, obstacles, gate_openings,
     approach_wp_ids, approach_wp_grid, post_gate_wp_ids,
     journey_ids, journey_grid, post_journey_ids,
     default_out_gate, default_in_gate,
     exit_upper, exit_lower, stair_exits) = create_simulation()

    # 방향별 큐 head x좌표 (자주 쓰임)
    QH_OUT = GATE_X - 0.3
    QH_IN  = GATE_X + GATE_LENGTH + 0.3

    rng = np.random.default_rng(42)
    total_steps = int(SIM_TIME / DT)

    arrival_times = generate_arrival_schedule(rng, SIM_TIME)
    arrival_idx = 0
    print(f"  도착 스케줄: {len(arrival_times)}명 예정")

    agent_data = {}
    spawned_count = 0

    stats = {
        "gate_counts": [0] * N_GATES,
        "service_times": [],
        "queue_history": [],
        "reroute_count": 0,
        "temperament_counts": {"adventurous": 0, "conserved": 0, "mild": 0},
        "tagless_count": 0,
        "stage3_triggers": 0,
        "spawned_out": 0,
        "spawned_in": 0,
        "passed_out": 0,
        "passed_in": 0,
    }

    # 각 게이트의 서비스 상태 추적
    # None 또는 {"agent_id": id, "start": time, "duration": dur}
    # 또는 {"clearing": True, "clear_start": time}
    gate_service = [None] * N_GATES
    passed_agents = set()  # 이미 통과 처리된 에이전트 ID (중복 카운트 방지)

    # 소프트웨어 큐: 게이트별 FIFO 리스트 (agent_id 저장)
    sw_queue = [[] for _ in range(N_GATES)]
    last_queue_entry_time = [-999.0] * N_GATES  # 게이트별 마지막 큐 진입 시각
    QUEUE_ENTRY_MIN_GAP = 0.7  # 큐 진입 최소 간격 (초) — 줄 서는 동작 시간

    video_frames = []
    frame_interval = int(0.5 / DT)

    # 궤적 데이터: [(time, agent_id, x, y, gate_idx, state)]
    trajectory_data = []
    traj_interval = int(0.1 / DT)  # 0.1초 간격 기록

    GATE_CLEAR_TIME = 0.5  # 게이트 문 닫히는 시간 (초)

    print("\n시뮬레이션 실행 중...")

    for step in range(total_steps):
        current_time = step * DT

        # ── 보행자 생성 (양방향) ──
        while (arrival_idx < len(arrival_times) and
               arrival_times[arrival_idx][0] <= current_time):
            arr_time, kind, info = arrival_times[arrival_idx]
            desired_speed = np.clip(
                rng.normal(PED_SPEED_MEAN, PED_SPEED_STD),
                PED_SPEED_MIN, PED_SPEED_MAX)
            temperament = assign_temperament(rng)
            is_tagless = rng.random() < TAGLESS_RATIO
            gate_queue = [len(q) for q in sw_queue]

            allowed = OUTBOUND_GATES if kind == 'out' else INBOUND_GATES
            default_gate_idx = default_out_gate if kind == 'out' else default_in_gate

            spawned = False
            for retry in range(5):
                if kind == 'out':
                    stair = STAIRS[info]
                    spawn_x = stair["x"] + rng.uniform(0.5, 2.5)
                    spawn_y = rng.uniform(stair["y_start"], stair["y_end"])
                    if retry > 0:
                        spawn_x += rng.uniform(0.5, 2.0)
                        spawn_y += rng.uniform(-1.0, 1.0)
                        spawn_y = np.clip(spawn_y, 2.0, NOTCH_Y - 2.0)
                    dist_to_gate = GATE_X - spawn_x   # 양수: 게이트 왼쪽
                else:  # 'in' 승차류 — 출구 통로 안에서 spawn
                    exit_idx = info  # 0=upper(y=24), 1=lower(y=3)
                    ex = EXITS[exit_idx]
                    # 통로 중심/폭
                    ecx = (ex['x_start'] + ex['x_end']) / 2  # 27.5
                    euw = EXIT_STAIR_WIDTH / 2                 # 1.25
                    # 통로 x범위 안에서 spawn
                    spawn_x = rng.uniform(ecx - euw + 0.3, ecx + euw - 0.3)
                    # upper: y=[23.5, 24.5], lower: y=[2.5, 3.5]
                    if exit_idx == 0:
                        spawn_y = ex['y'] - rng.uniform(0, 0.5)
                    else:
                        spawn_y = ex['y'] + rng.uniform(0, 0.5)
                    if retry > 0:
                        spawn_x += rng.uniform(-0.2, 0.2)
                        spawn_x = np.clip(spawn_x, ecx - euw + 0.2, ecx + euw - 0.2)
                    dist_to_gate = spawn_x - (GATE_X + GATE_LENGTH)

                if dist_to_gate <= CHOICE_DIST_1ST:
                    gate_idx = choose_gate_lrp(
                        rng, (spawn_x, spawn_y), desired_speed, temperament,
                        gates, gate_queue, stage="1st", allowed_gates=allowed)
                    choice_stage = 1
                    _depth = min(len(sw_queue[gate_idx]), MAX_QUEUE_DEPTH_WP)
                    jid = journey_grid[gate_idx][_depth]
                    sid = approach_wp_grid[gate_idx][_depth]
                else:
                    gate_idx = -1
                    choice_stage = 0
                    jid = journey_grid[default_gate_idx][0]
                    sid = approach_wp_grid[default_gate_idx][0]

                try:
                    agent_id = sim.add_agent(
                        jps.CollisionFreeSpeedModelV2AgentParameters(
                            journey_id=jid, stage_id=sid,
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
                        "kind": kind,                     # 'out' or 'in'
                        "spawn_time": current_time,
                        "service_time": sample_service_time(rng, is_tagless),
                        "original_speed": desired_speed,
                        "serviced": False,
                        "is_tagless": is_tagless,
                        "temperament": temperament,
                        "choice_stage": choice_stage,
                        "target_depth": min(len(sw_queue[gate_idx]), MAX_QUEUE_DEPTH_WP) if gate_idx >= 0 else 0,
                    }
                    spawned_count += 1
                    stats["temperament_counts"][temperament] += 1
                    if is_tagless:
                        stats["tagless_count"] += 1
                    if kind == 'out':
                        stats["spawned_out"] += 1
                    else:
                        stats["spawned_in"] += 1
                    spawned = True
                    break
                except Exception:
                    continue

            if not spawned:
                arrival_times.insert(arrival_idx + 1, (current_time + DT * 2, kind, info))

            arrival_idx += 1

        # ── 소프트웨어 큐: 접근 구역 도달 에이전트 흡수 (방향별) ──
        # tail 스냅샷 (방향에 따라 좌/우)
        queue_tail_snap = []
        for gi in range(N_GATES):
            d = GATE_DIRECTIONS[gi]
            n_q = len(sw_queue[gi])
            if d == 'out':
                if n_q == 0:
                    queue_tail_snap.append(QH_OUT - 0.8)
                else:
                    queue_tail_snap.append(QH_OUT - n_q * QUEUE_SPACING - 0.8)
            else:
                if n_q == 0:
                    queue_tail_snap.append(QH_IN + 0.8)
                else:
                    queue_tail_snap.append(QH_IN + n_q * QUEUE_SPACING + 0.8)

        gate_candidates = [[] for _ in range(N_GATES)]
        for agent in list(sim.agents()):
            aid = agent.id
            if aid not in agent_data:
                continue
            ad = agent_data[aid]
            if ad["serviced"] or ad.get("queued"):
                continue
            px = agent.position[0]
            gi = ad["gate_idx"]
            if gi < 0:
                continue
            if len(sw_queue[gi]) >= QUEUE_MAX_LENGTH:
                continue
            d = GATE_DIRECTIONS[gi]
            tail = queue_tail_snap[gi]
            # out: tail보다 오른쪽(px > tail)에 있으면 흡수
            # in : tail보다 왼쪽 (px < tail)에 있으면 흡수
            if (d == 'out' and px > tail) or (d == 'in' and px < tail):
                gate_candidates[gi].append((px, aid))

        for gi in range(N_GATES):
            d = GATE_DIRECTIONS[gi]
            # head에 가까운 순으로 정렬
            gate_candidates[gi].sort(reverse=(d == 'out'))
            for px_c, aid in gate_candidates[gi]:
                # 시간 제한: 게이트당 0.7초에 1명만 흡수 (자연스러운 줄 형성)
                if len(sw_queue[gi]) > 0 and current_time - last_queue_entry_time[gi] < QUEUE_ENTRY_MIN_GAP:
                    break
                ad = agent_data[aid]
                ad["queued"] = True
                ad["queue_enter_time"] = current_time
                sw_queue[gi].append(aid)
                _slot = len(sw_queue[gi]) - 1
                if d == 'out':
                    _qx = QH_OUT - _slot * QUEUE_SPACING
                else:
                    _qx = QH_IN + _slot * QUEUE_SPACING
                # 진입 ease: 자유보행 마지막 위치(px_c)에서 슬롯까지 보간
                ad["queue_visual_x"] = px_c
                ad["queue_target_x"] = _qx
                ad["queue_shift_from"] = px_c
                ad["queue_shift_start"] = current_time
                sim.mark_agent_for_removal(aid)
                last_queue_entry_time[gi] = current_time

        # ── 소프트웨어 큐 서비스 처리 ──
        for gi in range(N_GATES):
            # Phase A: 클리어링 중 -- 문 닫히는 시간 대기
            if gate_service[gi] is not None and gate_service[gi].get("clearing"):
                if current_time - gate_service[gi]["clear_start"] >= GATE_CLEAR_TIME:
                    gate_service[gi] = None  # 클리어 완료 -> 다음 사람 서비스 가능
                continue

            # Phase B: 서비스 중 -> 완료 시 에이전트 재투입 + 클리어링
            if gate_service[gi] is not None:
                svc = gate_service[gi]
                if current_time - svc["start"] >= svc["duration"]:
                    aid_done = svc["agent_id"]
                    ad = agent_data[aid_done]
                    gate_y = gates[gi]["y"]
                    d = GATE_DIRECTIONS[gi]
                    # 재투입 좌표: out=게이트 우측, in=게이트 좌측
                    if d == 'out':
                        respawn_pos = (GATE_X + GATE_LENGTH + 0.3, gate_y)
                    else:
                        respawn_pos = (GATE_X - 0.3, gate_y)
                    try:
                        new_aid = sim.add_agent(
                            jps.CollisionFreeSpeedModelV2AgentParameters(
                                journey_id=post_journey_ids[gi],
                                stage_id=post_gate_wp_ids[gi],
                                position=respawn_pos,
                                time_gap=CFSM_TIME_GAP,
                                desired_speed=ad["original_speed"],
                                radius=CFSM_RADIUS,
                                strength_neighbor_repulsion=8.0,
                                range_neighbor_repulsion=0.1,
                                strength_geometry_repulsion=5.0,
                                range_geometry_repulsion=0.02,
                            ))
                        agent_data[new_aid] = ad
                        ad["serviced"] = True
                        passed_agents.add(aid_done)
                        stats["service_times"].append(svc["duration"])
                        stats["gate_counts"][gi] += 1
                        if d == 'out':
                            stats["passed_out"] += 1
                        else:
                            stats["passed_in"] += 1
                    except Exception:
                        pass
                    gate_service[gi] = {"clearing": True, "clear_start": current_time}
                continue

            # Phase C: 게이트 비어있고 큐에 사람 있으면 서비스 시작
            if sw_queue[gi]:
                head_aid = sw_queue[gi].pop(0)
                ad = agent_data[head_aid]
                gate_service[gi] = {
                    "agent_id": head_aid,
                    "start": current_time,
                    "duration": ad["service_time"],
                }
                # 큐 시프트 모션: 남은 사람들의 타깃을 한 칸씩 앞으로 (방향별)
                d = GATE_DIRECTIONS[gi]
                qh = QH_OUT if d == 'out' else QH_IN
                sign = -1 if d == 'out' else +1
                for _j, _qaid in enumerate(sw_queue[gi]):
                    _qad = agent_data.get(_qaid)
                    if _qad is None:
                        continue
                    _new_target = qh + sign * _j * QUEUE_SPACING
                    if abs(_new_target - _qad.get("queue_target_x", _new_target)) > 1e-6:
                        _qad["queue_shift_from"] = _qad.get("queue_visual_x", _new_target)
                        _qad["queue_target_x"] = _new_target
                        _qad["queue_shift_start"] = current_time

        # ── 대기열 내 LRP 재선택 (방향별 분리) ──
        if QUEUE_RESELECT_ENABLED and step % int(QUEUE_RESELECT_INTERVAL / DT) == 0:
            gate_queue_snap = [len(q) for q in sw_queue]
            for gi in range(N_GATES):
                if gate_queue_snap[gi] < QUEUE_RESELECT_MIN_QUEUE:
                    continue
                d = GATE_DIRECTIONS[gi]
                allowed = OUTBOUND_GATES if d == 'out' else INBOUND_GATES
                qh = QH_OUT if d == 'out' else QH_IN
                sign = -1 if d == 'out' else +1
                moved = False
                candidates = list(sw_queue[gi][1:])
                for qaid in candidates:
                    if moved:
                        break
                    ad = agent_data.get(qaid)
                    if not ad:
                        continue
                    q_pos_idx = sw_queue[gi].index(qaid)
                    qx = qh + sign * q_pos_idx * QUEUE_SPACING
                    gate_y = gates[gi]["y"]
                    new_gate = choose_gate_lrp(
                        rng, (qx, gate_y), ad["original_speed"],
                        ad["temperament"], gates, gate_queue_snap, stage="2nd",
                        allowed_gates=allowed)
                    if (new_gate != gi and
                            abs(new_gate - gi) <= 1 and
                            new_gate in allowed and
                            gate_queue_snap[new_gate] < gate_queue_snap[gi] - QUEUE_RESELECT_MIN_DIFF):
                        sw_queue[gi].remove(qaid)
                        sw_queue[new_gate].append(qaid)
                        ad["gate_idx"] = new_gate
                        stats["reroute_count"] += 1
                        # 떠나는 게이트의 잔류 인원 시프트
                        for _j, _qaid in enumerate(sw_queue[gi]):
                            _qad = agent_data.get(_qaid)
                            if _qad is None:
                                continue
                            _new_target = qh + sign * _j * QUEUE_SPACING
                            if abs(_new_target - _qad.get("queue_target_x", _new_target)) > 1e-6:
                                _qad["queue_shift_from"] = _qad.get("queue_visual_x", _new_target)
                                _qad["queue_target_x"] = _new_target
                                _qad["queue_shift_start"] = current_time
                        # 옮긴 본인: 새 게이트의 마지막 슬롯으로 ease 시작
                        _new_dir = GATE_DIRECTIONS[new_gate]
                        _new_qh = QH_OUT if _new_dir == 'out' else QH_IN
                        _new_sign = -1 if _new_dir == 'out' else +1
                        _new_slot = len(sw_queue[new_gate]) - 1
                        _new_target = _new_qh + _new_sign * _new_slot * QUEUE_SPACING
                        ad["queue_shift_from"] = ad.get("queue_visual_x", _new_target)
                        ad["queue_target_x"] = _new_target
                        ad["queue_shift_start"] = current_time
                        # 스냅샷 업데이트
                        gate_queue_snap[gi] -= 1
                        gate_queue_snap[new_gate] += 1
                        moved = True

        # ── 게이트 점유 상태 (재선택용) ──
        gate_occupied = [gate_service[gi] is not None for gi in range(N_GATES)]

        # ── 게이트 선택 / 경로 변경: Gao (2019) ──
        gate_queue = [len(q) for q in sw_queue]

        # 서비스 중 에이전트 ID 집합 (재선택 방지)
        locked_aids = set()
        for gi_s in range(N_GATES):
            if gate_service[gi_s] is not None and "agent_id" in gate_service[gi_s]:
                locked_aids.add(gate_service[gi_s]["agent_id"])
            # 소프트웨어 큐에 있는 에이전트도 잠금 (시뮬레이션에서 이미 제거됨)
            for qaid in sw_queue[gi_s]:
                locked_aids.add(qaid)

        for agent in sim.agents():
            aid = agent.id
            if aid not in agent_data:
                continue
            ad = agent_data[aid]
            if ad["serviced"]:
                continue
            if aid in locked_aids:
                continue
            if ad.get("queued"):
                continue

            px, py = agent.position
            gi = ad["gate_idx"]
            kind = ad.get("kind", "out")
            allowed = OUTBOUND_GATES if kind == 'out' else INBOUND_GATES

            # 방향별 dist_to_gate (양수 = 게이트까지 남은 거리)
            if kind == 'out':
                dist_to_gate = GATE_X - px
            else:
                dist_to_gate = px - (GATE_X + GATE_LENGTH)

            # ── Phase 0: Influence Zone 진입 (1차 선택) ──
            _cur_gi = ad["gate_idx"] if ad["gate_idx"] >= 0 else allowed[0]
            if kind == 'out':
                _dist_from_tail = (GATE_X - queue_tail_snap[_cur_gi]) + 1.5
            else:
                _dist_from_tail = (queue_tail_snap[_cur_gi] - (GATE_X + GATE_LENGTH)) + 1.5
            _dynamic_dist = max(3.0, _dist_from_tail)
            if ad["choice_stage"] == 0 and dist_to_gate <= _dynamic_dist:
                gate_idx_new = choose_gate_lrp(
                    rng, (px, py), ad["original_speed"], ad["temperament"],
                    gates, gate_queue, stage="1st", allowed_gates=allowed)
                ad["gate_idx"] = gate_idx_new
                ad["choice_stage"] = 1
                _depth = min(gate_queue[gate_idx_new], MAX_QUEUE_DEPTH_WP)
                ad["target_depth"] = _depth
                try:
                    sim.switch_agent_journey(
                        aid, journey_grid[gate_idx_new][_depth],
                        approach_wp_grid[gate_idx_new][_depth])
                except Exception:
                    pass
                gi = gate_idx_new
                continue

            if gi < 0:
                continue

            if dist_to_gate <= 0:
                continue

            current_stage = ad["choice_stage"]
            current_gate = ad["gate_idx"]

            # ── 2차 재선택 ──
            if dist_to_gate <= CHOICE_DIST_2ND and current_stage < 2:
                ad["choice_stage"] = 2
                if gate_queue[current_gate] >= 3:
                    new_gate = choose_gate_lrp(
                        rng, (px, py), ad["original_speed"], ad["temperament"],
                        gates, gate_queue, stage="2nd", allowed_gates=allowed)
                    if (new_gate != current_gate and
                            gate_queue[new_gate] < gate_queue[current_gate] - 2):
                        _depth = min(gate_queue[new_gate], MAX_QUEUE_DEPTH_WP)
                        try:
                            sim.switch_agent_journey(
                                aid, journey_grid[new_gate][_depth],
                                approach_wp_grid[new_gate][_depth])
                            ad["gate_idx"] = new_gate
                            ad["target_depth"] = _depth
                            stats["reroute_count"] += 1
                        except Exception:
                            pass

        # ── 동적 waypoint 업데이트: 매 스텝 큐 깊이에 맞춰 접근 목표 전환 (방향별) ──
        if True:
            for agent in list(sim.agents()):
                aid = agent.id
                if aid not in agent_data:
                    continue
                ad = agent_data[aid]
                if ad["serviced"] or ad.get("queued"):
                    continue
                gi = ad["gate_idx"]
                if gi < 0:
                    continue
                d = GATE_DIRECTIONS[gi]
                qh = QH_OUT if d == 'out' else QH_IN
                sign = -1 if d == 'out' else +1
                new_depth = min(len(sw_queue[gi]), MAX_QUEUE_DEPTH_WP)
                # 새 waypoint 위치 (depth=0 → head 0.8m 뒤)
                if new_depth == 0:
                    wp_x = qh + sign * 0.8
                else:
                    wp_x = qh + sign * (new_depth * QUEUE_SPACING + 0.8)

                px = agent.position[0]
                # 이미 wp를 지나쳤으면 즉시 흡수
                #   out: px > wp_x (wp_x가 더 왼쪽) → 게이트 쪽
                #   in : px < wp_x (wp_x가 더 오른쪽) → 게이트 쪽
                past_wp = (d == 'out' and px > wp_x) or (d == 'in' and px < wp_x)
                if past_wp and len(sw_queue[gi]) < QUEUE_MAX_LENGTH:
                    if current_time - last_queue_entry_time[gi] >= QUEUE_ENTRY_MIN_GAP or len(sw_queue[gi]) == 0:
                        ad["queued"] = True
                        ad["queue_enter_time"] = current_time
                        sw_queue[gi].append(aid)
                        _slot = len(sw_queue[gi]) - 1
                        _qx = qh + sign * _slot * QUEUE_SPACING
                        # 진입 ease: 자유보행 위치(px)에서 슬롯까지 보간
                        ad["queue_visual_x"] = px
                        ad["queue_target_x"] = _qx
                        ad["queue_shift_from"] = px
                        ad["queue_shift_start"] = current_time
                        sim.mark_agent_for_removal(aid)
                        last_queue_entry_time[gi] = current_time
                        continue
                # depth 줄어들기만 허용
                cur_depth = ad.get("target_depth", new_depth)
                if new_depth < cur_depth:
                    ad["target_depth"] = new_depth
                    try:
                        sim.switch_agent_journey(
                            aid, journey_grid[gi][new_depth],
                            approach_wp_grid[gi][new_depth])
                    except Exception:
                        pass

        # ── 큐 시프트 visual_x 갱신 (ease-in-out) ──
        for gi in range(N_GATES):
            for qaid in sw_queue[gi]:
                ad = agent_data.get(qaid)
                if ad is None or ad.get("queue_shift_start") is None:
                    continue
                elapsed = current_time - ad["queue_shift_start"]
                if elapsed >= QUEUE_SHIFT_DURATION:
                    ad["queue_visual_x"] = ad["queue_target_x"]
                    ad["queue_shift_start"] = None
                else:
                    t = elapsed / QUEUE_SHIFT_DURATION
                    eased = ease_in_out(t)
                    ad["queue_visual_x"] = (
                        ad["queue_shift_from"]
                        + (ad["queue_target_x"] - ad["queue_shift_from"]) * eased
                    )

        # ── 궤적 기록 (kind 추가) ──
        if step % traj_interval == 0:
            for agent in sim.agents():
                aid = agent.id
                px, py = agent.position
                ad = agent_data.get(aid, {})
                gi = ad.get("gate_idx", -1)
                kind = ad.get("kind", "out")
                state = "passed" if ad.get("serviced") else "moving"
                trajectory_data.append((current_time, aid, px, py, gi, state, kind))

            for gi in range(N_GATES):
                gate_y = gates[gi]["y"]
                d = GATE_DIRECTIONS[gi]
                qh = QH_OUT if d == 'out' else QH_IN
                sign = -1 if d == 'out' else +1
                for j, qaid in enumerate(sw_queue[gi]):
                    ad = agent_data.get(qaid, {})
                    qx = ad.get("queue_visual_x", qh + sign * j * QUEUE_SPACING)
                    kind = ad.get("kind", "out")
                    trajectory_data.append((current_time, qaid, qx, gate_y, gi, "queue", kind))

        # ── 통계 & 프레임 ──
        if step % int(1.0 / DT) == 0:
            gq = [len(q) for q in sw_queue]
            stats["queue_history"].append((current_time, gq.copy()))

        if step % frame_interval == 0:
            frame_data = []
            for a in sim.agents():
                ad = agent_data.get(a.id, {})
                s = "passed" if ad.get("serviced") else "approach"
                tl = ad.get("is_tagless", False)
                kind = ad.get("kind", "out")
                frame_data.append((a.position[0], a.position[1], s, tl, kind))

            for gi in range(N_GATES):
                gate_y = gates[gi]["y"]
                d = GATE_DIRECTIONS[gi]
                qh = QH_OUT if d == 'out' else QH_IN
                sign = -1 if d == 'out' else +1
                for j, qaid in enumerate(sw_queue[gi]):
                    ad = agent_data.get(qaid, {})
                    qx = ad.get("queue_visual_x", qh + sign * j * QUEUE_SPACING)
                    tl = ad.get("is_tagless", False)
                    kind = ad.get("kind", "out")
                    frame_data.append((qx, gate_y, "queue", tl, kind))
                if gate_service[gi] is not None and "agent_id" in gate_service[gi]:
                    svc_aid = gate_service[gi]["agent_id"]
                    sad = agent_data.get(svc_aid, {})
                    tl = sad.get("is_tagless", False)
                    kind = sad.get("kind", "out")
                    head_x = (GATE_X - 0.1) if kind == 'out' else (GATE_X + GATE_LENGTH + 0.1)
                    frame_data.append((head_x, gate_y, "service", tl, kind))

            video_frames.append((current_time, frame_data))

        # ── 밀도 기반 동적 time_gap 조정 ──
        if DYNAMIC_TIME_GAP and step % 10 == 0:  # 매 10스텝 (0.5초)
            positions = []
            agent_ids_live = []
            for agent in sim.agents():
                positions.append(agent.position)
                agent_ids_live.append(agent.id)
            if positions:
                pos_arr = np.array(positions)
                for k, aid in enumerate(agent_ids_live):
                    px, py = pos_arr[k]
                    # 반경 내 이웃 수로 국소 밀도 계산
                    diffs = pos_arr - pos_arr[k]
                    dists = np.sqrt(diffs[:, 0]**2 + diffs[:, 1]**2)
                    n_neighbors = np.sum(dists < DENSITY_R) - 1  # 자기 제외
                    local_density = n_neighbors / (np.pi * DENSITY_R**2)

                    if local_density < 0.5:
                        new_tg = TIME_GAP_LOW
                    elif local_density < 1.5:
                        # 선형 보간
                        t = (local_density - 0.5) / 1.0
                        new_tg = TIME_GAP_LOW + t * (TIME_GAP_MID - TIME_GAP_LOW)
                    else:
                        t = min((local_density - 1.5) / 1.0, 1.0)
                        new_tg = TIME_GAP_MID + t * (TIME_GAP_HIGH - TIME_GAP_MID)

                    try:
                        agent = sim.agent(aid)
                        agent.model.time_gap = new_tg
                    except Exception:
                        pass

        sim.iterate()

        if step % int(30.0 / DT) == 0 and step > 0:
            queued_total = sum(len(q) for q in sw_queue)
            print(f"  t={current_time:.0f}s | agents: {sim.agent_count()} "
                  f"| queued: {queued_total} "
                  f"| out: spawn {stats['spawned_out']}/pass {stats['passed_out']}"
                  f"  in: spawn {stats['spawned_in']}/pass {stats['passed_in']} "
                  f"| re-route: {stats['reroute_count']}")

    # ── 결과 ──
    total_passed = sum(stats["gate_counts"])
    print(f"\n완료: 하차 {stats['spawned_out']}/{stats['passed_out']}, "
          f"승차 {stats['spawned_in']}/{stats['passed_in']}, "
          f"경로변경 {stats['reroute_count']}회")
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
                              f"G{ad['gate_idx']+1 if ad['gate_idx']>=0 else '?'} ")
                        break
            # 소프트웨어 큐 내 에이전트 진단
            for gi in range(N_GATES):
                if aid in sw_queue[gi]:
                    pos_in_q = sw_queue[gi].index(aid)
                    print(f"  [큐내] id={aid}: G{gi+1} 큐 위치 {pos_in_q}")
                    break
    if unserviced > 0:
        print(f"\n미통과 에이전트: {unserviced}명")

    print(f"\n출력 생성...")
    create_snapshots(video_frames, gates, obstacles, gate_openings)
    create_mp4(video_frames, gates, obstacles, gate_openings)
    plot_queue_history(stats["queue_history"])
    plot_service_time_dist(stats["service_times"])
    save_trajectories(trajectory_data)
    analyze_trajectories(trajectory_data, gates)

    return stats, spawned_count


# =============================================================================
# 시각화
# =============================================================================
STATE_COLORS = {
    "approach": "#1565C0",
    "queue":    "#EF6C00",
    "service":  "#C62828",
    "passed":   "#1565C0",
}
# 태그리스 에이전트 색상 (밝은 계열)
TAGLESS_COLORS = {
    "approach": "#00BFA5",
    "queue":    "#FFD600",
    "service":  "#FF6D00",
    "passed":   "#00BFA5",
}


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

    for j, opening in enumerate(gate_openings):
        ox, oy = opening.exterior.xy
        # 방향별 게이트 색상: 입구=teal, 출구=green
        gate_color = '#26A69A' if GATE_DIRECTIONS[j] == 'in' else '#66BB6A'
        ax.fill(ox, oy, color=gate_color, edgecolor='#2E7D32', linewidth=0.8, alpha=0.5, zorder=3)

    for j, g in enumerate(gates):
        label = f"{g['id']+1}{'입' if GATE_DIRECTIONS[j]=='in' else '출'}"
        ax.text(g["x"] + GATE_LENGTH / 2, g["y"], label,
                ha='center', va='center', fontsize=6, fontweight='bold', color='#1B5E20', zorder=4)

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
        # 5튜플 (x, y, state, is_tagless, kind) — 양방향 색상
        xs = [p[0] for p in positions]
        ys = [p[1] for p in positions]
        cs = []
        for p in positions:
            state = p[2]
            kind = p[4] if len(p) >= 5 else 'out'
            if state == 'queue':
                cs.append('#EF6C00')   # 큐 = 오렌지 (방향 무관)
            elif state == 'service':
                cs.append('#C62828')   # 서비스 = 빨강
            elif kind == 'in':
                cs.append('#00897B')   # 승차 = teal
            else:
                cs.append('#1565C0')   # 하차 = 파랑
        ax.scatter(xs, ys, s=25, c=cs, edgecolors='white',
                   linewidths=0.3, alpha=0.85, zorder=5)

    n_peds = len(positions) if positions else 0
    ax.text(0.5, NOTCH_Y - 0.5,
            f't = {time_sec:.1f}s | {n_peds} peds',
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
    fig.suptitle('성수역 서쪽 대합실 (CFSM V2, 소프트웨어 큐)',
                 fontsize=16, fontweight='bold')
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "snapshots_bidir.png", dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  스냅샷: {OUTPUT_DIR / 'snapshots_bidir.png'}")


def create_mp4(frames, gates, obstacles, gate_openings):
    from matplotlib.animation import FuncAnimation, FFMpegWriter
    import imageio_ffmpeg
    target_frames = [(t, pos) for t, pos in frames if t <= 120]
    if not target_frames:
        return
    fig, ax = plt.subplots(figsize=(14, 8))

    def animate(i):
        t, positions = target_frames[i]
        draw_frame(ax, positions, gates, obstacles, gate_openings, t)
        ax.set_title(f'성수역 서쪽 (CFSM V2, 소프트웨어 큐) | t = {t:.1f}s | {len(positions)} agents',
                     fontsize=12, fontweight='bold')

    anim = FuncAnimation(fig, animate, frames=len(target_frames), interval=100)
    mp4_path = OUTPUT_DIR / "simulation_bidir.mp4"
    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    plt.rcParams['animation.ffmpeg_path'] = ffmpeg_path
    writer = FFMpegWriter(fps=10, bitrate=2000,
                          extra_args=['-movflags', '+faststart', '-pix_fmt', 'yuv420p'])
    anim.save(str(mp4_path), writer=writer, dpi=120)
    plt.close(fig)
    print(f"  MP4: {mp4_path}")


def save_trajectories(trajectory_data):
    """궤적 데이터를 CSV로 저장 (kind 컬럼 추가)"""
    import csv
    traj_path = OUTPUT_DIR / "trajectories_bidir.csv"
    with open(traj_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(["time", "agent_id", "x", "y", "gate_idx", "state", "kind"])
        for row in trajectory_data:
            w.writerow(row)
    print(f"  궤적: {traj_path} ({len(trajectory_data)}행)")


def analyze_trajectories(trajectory_data, gates):
    """궤적 데이터에서 이상 행태 자동 감지"""
    print("\n" + "=" * 60)
    print("궤적 분석 (자동 행태 감지)")
    print("=" * 60)

    import pandas as pd
    df = pd.DataFrame(trajectory_data,
                      columns=["time", "agent_id", "x", "y", "gate_idx", "state", "kind"])

    issues = []

    # 1. 게이트 통과 시 y편차: 게이트 중앙에서 벗어나는지
    gate_zone = df[(df["x"] >= GATE_X) & (df["x"] <= GATE_X + GATE_LENGTH) &
                   (df["gate_idx"] >= 0)]
    if len(gate_zone) > 0:
        gate_ys = {g["id"]: g["y"] for g in gates}
        gate_zone = gate_zone.copy()
        gate_zone["gate_y"] = gate_zone["gate_idx"].map(gate_ys)
        gate_zone["y_dev"] = (gate_zone["y"] - gate_zone["gate_y"]).abs()
        max_dev = gate_zone["y_dev"].max()
        mean_dev = gate_zone["y_dev"].mean()
        bad_pass = gate_zone[gate_zone["y_dev"] > GATE_PASSAGE_WIDTH / 2]
        print(f"\n[게이트 통과 y편차]")
        print(f"  평균: {mean_dev:.3f}m, 최대: {max_dev:.3f}m")
        print(f"  통로 폭(0.55m) 벗어난 기록: {len(bad_pass)}건 "
              f"({len(bad_pass)/max(len(gate_zone),1)*100:.1f}%)")
        if len(bad_pass) > 0:
            issues.append(f"게이트 통과 시 통로 벗어남 {len(bad_pass)}건")

    # 2. 에이전트 간 최소 거리 (겹침 감지)
    times = df["time"].unique()
    min_dist_overall = float("inf")
    overlap_count = 0
    sample_times = times[::10]  # 매 10번째 시점만 검사
    for t in sample_times:
        snap = df[df["time"] == t]
        if len(snap) < 2:
            continue
        xs = snap["x"].values
        ys = snap["y"].values
        for i in range(len(xs)):
            for j in range(i + 1, len(xs)):
                d = np.hypot(xs[i] - xs[j], ys[i] - ys[j])
                if d < min_dist_overall:
                    min_dist_overall = d
                if d < 2 * CFSM_RADIUS:
                    overlap_count += 1
    print(f"\n[에이전트 간 최소 거리]")
    print(f"  전체 최소: {min_dist_overall:.3f}m (반경 합: {2*CFSM_RADIUS:.2f}m)")
    print(f"  겹침 (d < {2*CFSM_RADIUS:.2f}m): {overlap_count}건")
    if overlap_count > 0:
        issues.append(f"에이전트 겹침 {overlap_count}건")

    # 3. 벽 근접 행동 (게이트 배리어 영역에서 진동)
    barrier_zone = df[(df["x"] >= GATE_X - 0.5) & (df["x"] <= GATE_X + GATE_LENGTH + 0.5)]
    if len(barrier_zone) > 0:
        oscillation_agents = []
        for aid, grp in barrier_zone.groupby("agent_id"):
            if len(grp) < 3:
                continue
            dx = grp["x"].diff().dropna().values
            sign_changes = np.sum(np.diff(np.sign(dx)) != 0)
            if sign_changes >= 4:  # 2회 이상 방향 전환
                oscillation_agents.append(aid)
        print(f"\n[게이트 근처 진동 (방향 전환 4회+)]")
        print(f"  해당 에이전트: {len(oscillation_agents)}명")
        if oscillation_agents:
            issues.append(f"게이트 근처 진동 {len(oscillation_agents)}명")

    # 4. 대기열 위치: 게이트 뒤(+x)가 아닌 게이트 사이(y)에서 대기하는지
    queue_zone = df[(df["x"] >= GATE_X - 2.0) & (df["x"] < GATE_X) &
                    (df["gate_idx"] >= 0)]
    if len(queue_zone) > 0:
        gate_ys = {g["id"]: g["y"] for g in gates}
        queue_zone = queue_zone.copy()
        queue_zone["gate_y"] = queue_zone["gate_idx"].map(gate_ys)
        queue_zone["y_dev"] = (queue_zone["y"] - queue_zone["gate_y"]).abs()
        bad_queue = queue_zone[queue_zone["y_dev"] > 0.5]
        print(f"\n[대기열 y편차 (게이트 뒤가 아닌 옆에서 대기)]")
        print(f"  평균: {queue_zone['y_dev'].mean():.3f}m")
        print(f"  0.5m 이상 벗어난 기록: {len(bad_queue)}건")
        if len(bad_queue) > 0:
            issues.append(f"대기열 위치 이상 {len(bad_queue)}건")

    # 종합
    print(f"\n{'─' * 40}")
    if not issues:
        print("종합: 이상 행태 없음")
    else:
        print(f"종합: {len(issues)}개 이슈 감지")
        for iss in issues:
            print(f"  - {iss}")
    print("=" * 60)
    return issues


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
    ax.set_title('게이트별 대기 인원 변화 (CFSM V2, 소프트웨어 큐)')
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "queue_history_bidir.png", dpi=150)
    plt.close(fig)
    print(f"  대기열: {OUTPUT_DIR / 'queue_history_bidir.png'}")


def plot_service_time_dist(service_times):
    if not service_times:
        return
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(service_times, bins=25, color='#42A5F5', edgecolor='#1565C0', alpha=0.8)
    ax.axvline(np.mean(service_times), color='red', linestyle='--',
               label=f'평균: {np.mean(service_times):.2f}s')
    ax.set_xlabel('서비스 시간 (초)')
    ax.set_ylabel('빈도')
    ax.set_title('개찰구 서비스 시간 분포 (CFSM V2, 소프트웨어 큐)')
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUTPUT_DIR / "service_time_bidir.png", dpi=150)
    plt.close(fig)
    print(f"  서비스시간: {OUTPUT_DIR / 'service_time_bidir.png'}")


# =============================================================================
# 자동 평가
# =============================================================================
def evaluate_simulation(stats, spawned_count, sim_time):
    print("\n" + "=" * 60)
    print("시뮬레이션 평가 결과 (CFSM V2, 소프트웨어 큐)")
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
