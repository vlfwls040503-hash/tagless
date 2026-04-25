"""
성수역 서쪽 대합실 보행자 시뮬레이션 — CFSM V2 (소프트웨어 큐 기반)

v8 (GCFM) -> CFSM -> software queue 재구현:
  물리 엔진: CollisionFreeSpeedModelV2 (Tordeux et al., 2016)
  - 속도 기반 모델 (힘 기반이 아님) -> 계산 효율 UP
  - 충돌 없는 경로 예측 -> 좁은 통로 자연 통과

  게이트 통과 메커니즘 (소프트웨어 큐):
  - CFSM은 자유보행만 처리 (계단 → 게이트 접근 구역)
  - 에이전트가 게이트 접근 구역(x > 10.5) 도달 → 시뮬레이션에서 제거
  - 순수 Python FIFO 큐로 대기열 관리 (게이트별 list)
  - 서비스 완료 시 게이트 출구에 에이전트 재투입 → post_gate journey로 퇴장

  기존 유지:
  - 게이트 선택: Gao et al. (2019) LRP 모델 (3단계 재선택)
  - 서비스 시간: Gao (2019) 실측 기반 lognormal

논문 프레이밍:
  - 전략(의사결정): Gao et al. (2019) LRP 모델
  - 전술(물리적 보행): CFSM V2 (Tordeux et al., 2016)
  - 게이트 통과: 소프트웨어 큐 + 서비스 시간 모델
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
from seongsu_west_escalator import (
    calculate_gate_positions, build_geometry,
    GATE_X, GATE_LENGTH, GATE_PASSAGE_WIDTH, GATE_HOUSING_WIDTH,
    BARRIER_Y_BOTTOM, BARRIER_Y_TOP,
    CONCOURSE_LENGTH, CONCOURSE_WIDTH, NOTCH_X, NOTCH_Y,
    STAIRS, EXITS, STRUCTURES, N_GATES,
    ESCALATOR_X_START, ESCALATOR_X_END, ESCALATOR_CORRIDOR_WIDTH,
)
# v3+: SPACE에서 capture zone, waypoint, Zone 좌표 직접 읽음
from docs.space_layout import SPACE
_ESC_LOWER = next(e for e in SPACE["escalators"] if e["side"] == "lower")  # exit1
_ESC_UPPER = next(e for e in SPACE["escalators"] if e["side"] == "upper")  # exit4
_ZONES_BY_ID = {z["id"]: z for z in SPACE["zones"]}

def _zone_tuple(zid):
    z = _ZONES_BY_ID[zid]
    return (z["x_range"][0], z["x_range"][1], z["y_range"][0], z["y_range"][1])

plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

# =============================================================================
# 시뮬레이션 파라미터
# =============================================================================
SIM_TIME = 300.0  # p=0.7 cfg1 장기 정체 시각화 (batch 와 동일 조건)
DT = 0.05

# =============================================================================
# 도착 모델
# =============================================================================
TRAIN_INTERVAL = 180.0
TRAIN_ALIGHTING = 234  # 08-09시 평일 평균 (11,214명/h ÷ 24편 × 서쪽50%)
PLATOON_SPREAD = 50.0  # (미사용, 물리 기반으로 대체)

# 성수역 물리 기반 도착 모델 파라미터
PLATFORM_LENGTH = 105.0       # 승강장 길이 (m)
ALIGHTING_DELAY_MAX = 10.0    # 하차 지연 최대 (s)
STAIR_DESCENT_TIME = 12.0     # 계단 하행 시간 (s) — ~10m, 0.85m/s
STAIR_TO_GATE_DIST = 11.0     # 계단 하부 → 게이트 구간 거리 (m)
WALK_SPEED_MEAN = 1.20        # 한국 도시철도 통근자 표준 (서울교통공사 환승소요시간 기준)
WALK_SPEED_STD = 0.20         # 한국화로 분산 약간 축소
FIRST_TRAIN_TIME = 5.0

# 계단 방출율 (Weidmann 1993: 1.25명/s/m, 하행)
STAIR_WIDTH = 3.7             # 성수역 계단 폭 (도면 계측)
STAIR_DISCHARGE_RATE = 1.25   # Weidmann 하행 최대
STAIR_CAPACITY = STAIR_WIDTH * STAIR_DISCHARGE_RATE  # ~4.6명/s per stair

# =============================================================================
# 보행자 속도 파라미터
# =============================================================================
# N(1.20, 0.20), clip(0.8, 2.0)
# 근거: 서울교통공사 환승소요시간 기준 1.2 m/s, KOTI/국토부 환승편의시설 동일.
# 한국인 자유보행 1.29 m/s (이창희·김대현 2020) 보다 통근자 시설 내 표준이 더 낮음.
# Weidmann (1993) 1.34 m/s 는 서양 기준 — 한국 도시철도 약간 과대.
# Agent별 속성으로 spawn 시 1회 고정 (이후 상수 유지).
PED_SPEED_MEAN = 1.20
PED_SPEED_STD = 0.20
PED_SPEED_MIN = 0.8
PED_SPEED_MAX = 2.0

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
SERVICE_TIME_MEAN = 2.7        # 태그: 평균 2.7s (Beijing 실측 + 한국 플랩식, lognormal)
SERVICE_TIME_MIN = 1.0
SERVICE_TIME_MAX = 5.0
CARD_FEEDING_TIME = 1.1
GATE_PASS_SPEED = 0.65
GATE_PHYS_LENGTH = 1.4

TAGLESS_SERVICE_TIME = 1.2    # 태그리스: 물리 통과시간 (1.5m / 1.3m/s, Weidmann 기반)
TAGLESS_RATIO = 1.0           # 단일 sim 기본값 (배치는 scenario_matrix가 override)

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
# 배치 런 파라미터 (batch_runner가 monkey-patch, 기본값은 기존 동작 유지)
# =============================================================================
BATCH_SEED = 42                          # rng 시드
BATCH_TAGLESS_ONLY_GATES = frozenset({2, 4})   # cfg2: G3, G5 태그리스 전용
                                         # 비어있으면 기존 동작 (모든 게이트 공용)
BATCH_OUTPUT_SUFFIX = ""                 # 출력 파일 suffix (배치 시 시나리오 id)
BATCH_METRICS_OUT = None                 # pathlib.Path — per-agent CSV 저장 경로
BATCH_ZONE_CSV_OUT = None                # pathlib.Path — zone density CSV 저장 경로
BATCH_SKIP_HEAVY_OUTPUTS = False         # True: mp4/snapshots/큐 히스토리 생략
BATCH_ZONE_SAMPLE_INTERVAL = 5.0         # zone density 샘플링 간격 (s)
BATCH_SAVE_TRAJECTORY = False            # True: 배치 모드에도 trajectory CSV 저장
BATCH_TRAJECTORY_INTERVAL = 0.5          # trajectory 샘플링 간격 (s, downsample)
BATCH_TRAJECTORY_OUT = None              # pathlib.Path — trajectory CSV 경로

# 배치 오버라이드 가능 상수 (기본값은 그대로)
# TAGLESS_RATIO, SIM_TIME, TRAIN_INTERVAL, TRAIN_ALIGHTING는 이미 module-level


# =============================================================================
# 유틸 함수
# =============================================================================
def generate_arrival_schedule(rng, sim_time):
    """물리 기반 도착 스케줄 (성수역 구조 반영).

    도착시간 = 열차도착 + 하차지연 + 승강장보행 + 계단하행 + 계단→게이트 보행
    - 계단이 승강장 양 끝에 위치 → 가까운 쪽 계단으로 이동
    - 승객 위치: 열차 전체에 균등 분포
    - 열차가 교대로 도착하므로 계단도 교대.
    """
    min_gap = 1.0 / STAIR_CAPACITY

    arrivals = []
    train_time = FIRST_TRAIN_TIME
    train_count = 0
    while train_time < sim_time:
        n_passengers = rng.poisson(TRAIN_ALIGHTING)
        # 열차별 계단 1개: 짝수번째=upper(0), 홀수번째=lower(1)
        stair_idx = train_count % 2

        times = []
        for _ in range(n_passengers):
            # 1. 열차 내 위치 (균등분포, 0 = 계단 쪽 끝)
            pos_on_platform = rng.uniform(0, PLATFORM_LENGTH)

            # 2. 가까운 쪽 계단까지 거리 (양 끝에 계단)
            dist_to_stair = min(pos_on_platform, PLATFORM_LENGTH - pos_on_platform)

            # 3. 개인별 보행속도
            walk_speed = max(0.8, rng.normal(WALK_SPEED_MEAN, WALK_SPEED_STD))

            # 4. 하차 지연 (문 앞=0, 안쪽=최대 10초)
            alighting_delay = rng.uniform(0, ALIGHTING_DELAY_MAX)

            # 5. 총 도착시간
            t_platform_walk = dist_to_stair / walk_speed
            t_stair_descent = STAIR_DESCENT_TIME
            t_stair_to_gate = STAIR_TO_GATE_DIST / walk_speed
            raw_t = train_time + alighting_delay + t_platform_walk + t_stair_descent + t_stair_to_gate

            times.append(raw_t)
        times.sort()

        # 방출율 제약 (계단 용량)
        for j in range(1, len(times)):
            earliest = times[j - 1] + min_gap
            if times[j] < earliest:
                times[j] = earliest

        for t in times:
            if t < sim_time:
                arrivals.append((t, stair_idx))

        train_time += TRAIN_INTERVAL
        train_count += 1

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
# 시뮬레이션 생성 (CFSM V2, 소프트웨어 큐 기반)
# =============================================================================
def create_simulation():
    gates = calculate_gate_positions()

    # 기하구조: 배리어 없음 (소프트웨어 제어)
    walkable, _, _ = build_geometry(gates, include_barrier=False)
    # 시각화용: 실제 규격 (1.5m 두께, 0.55m 통로)
    _, vis_obstacles, gate_openings = build_geometry(gates, include_barrier=True)

    # ── 에스컬레이터 접근 깔때기 (invisible geometry) ──
    # 시각화에 표시 안 되지만 물리적으로 보행 경로를 좁힘.
    # 목적: x+ 방향 과도한 군집 방지 + 에스컬 앞 대기공간 압축
    # 2026-04-22: 채널 벽 제거. 게이트→에스컬 자연 대각선 경로 복원.
    # 코리도 동측 캡만 유지 (큐가 에스컬 동쪽으로 확산되지 않도록)
    from shapely.geometry import Polygon as _Poly
    _funnel_polys = [
        _Poly([(35.0, 25.0), (40.0, 25.0), (40.0, 26.2), (35.0, 26.2)]),
        _Poly([(35.0, -1.2), (40.0, -1.2), (40.0,  0.0), (35.0,  0.0)]),
    ]
    for _fp in _funnel_polys:
        if _fp.is_valid and _fp.area > 0:
            walkable = walkable.difference(_fp)

    # CFSM V2
    model = jps.CollisionFreeSpeedModelV2()
    sim = jps.Simulation(model=model, geometry=walkable, dt=DT)

    gate_x_end = GATE_X + GATE_LENGTH

    # 1단계: 접근 Waypoint (큐 깊이별 동적 위치)
    approach_wp_grid = []  # [gate][depth] -> wp_id
    for g in gates:
        gate_wps = []
        for depth in range(MAX_QUEUE_DEPTH_WP + 1):
            if depth == 0:
                wp_x = QUEUE_HEAD_X - 0.8  # 빈 큐: 큐 head 0.8m 뒤에서 감속
            else:
                wp_x = QUEUE_HEAD_X - depth * QUEUE_SPACING - 0.8
            wp_x = max(wp_x, 2.0)
            wp_id = sim.add_waypoint_stage((wp_x, g["y"]), 0.5)
            gate_wps.append(wp_id)
        approach_wp_grid.append(gate_wps)
    approach_wp_ids = [approach_wp_grid[i][0] for i in range(N_GATES)]

    # 2단계: 게이트 출구 Waypoint (서비스 완료 후 재투입 지점)
    post_gate_wp_ids = []
    for g in gates:
        wp_id = sim.add_waypoint_stage((gate_x_end + 0.5, g["y"]), 0.5)
        post_gate_wp_ids.append(wp_id)

    # 에스컬레이터 진입 waypoint — capture zone 동쪽 끝 내부
    # 2026-04-22: 에스컬 위치 +5m 이동 + corridor 1.2m 폭
    escalator_wp_upper = sim.add_waypoint_stage((33.0, 25.6), 0.3)
    escalator_wp_lower = sim.add_waypoint_stage((33.0, -0.6), 0.3)

    # 2026-04-22: 중간 waypoint 단일화 — 에스컬 직전 1개 목적지
    # 게이트→이 waypoint 로 직접 이동 (자연 대각선 경로)
    # 위치: corridor 진입 직전, 경계벽 관통 없이 slot 도달 가능한 (28.5, 24.5) / (28.5, 0.5)
    esc_approach_upper = sim.add_waypoint_stage((28.5, 24.5), 0.60)
    esc_approach_lower = sim.add_waypoint_stage((28.5,  0.5), 0.60)
    # bridge = approach (같은 위치 — transition 호환성 유지용)
    esc_bridge_upper = esc_approach_upper
    esc_bridge_lower = esc_approach_lower

    # Dummy exit stage (JuPedSim journey는 보통 마지막에 exit_stage 필요)
    # walkable 내 멀리 떨어진 구석에 배치 — escalator_wp fixed_transition 으로
    # 넘어가면 그쪽으로 이동하나, Python 로직이 escalator_wp 근처에서
    # 에이전트를 remove 하므로 실제 도달 불가.
    # 2026-04-22: structures x 이동(+5)에 맞춰 dummy_exit도 유효 walkable 내로
    dummy_exit = sim.add_exit_stage(Polygon([
        (34.5, 12.0), (35.0, 12.0), (35.0, 13.0), (34.5, 13.0),
    ]))

    # 접근 Journey: 큐 깊이별 동적 waypoint → post_gate → esc_approach → escalator_wp → dummy_exit
    # esc_approach는 corridor 입구 직전 정렬점 (부채꼴 축소)
    journey_grid = []
    for i, g in enumerate(gates):
        is_upper = g["y"] > CONCOURSE_WIDTH / 2
        approach_wp = esc_approach_upper if is_upper else esc_approach_lower
        target_wp = escalator_wp_upper if is_upper else escalator_wp_lower
        gate_jids = []
        for depth in range(MAX_QUEUE_DEPTH_WP + 1):
            wp_id = approach_wp_grid[i][depth]
            journey = jps.JourneyDescription([
                wp_id, post_gate_wp_ids[i],
                esc_approach_upper, esc_approach_lower,
                escalator_wp_upper, escalator_wp_lower, dummy_exit
            ])
            journey.set_transition_for_stage(
                wp_id,
                jps.Transition.create_fixed_transition(post_gate_wp_ids[i]))
            journey.set_transition_for_stage(
                post_gate_wp_ids[i],
                jps.Transition.create_fixed_transition(approach_wp))
            # approach_wp 도달 → (대기, Python 큐가 슬롯 배정)
            jid = sim.add_journey(journey)
            gate_jids.append(jid)
        journey_grid.append(gate_jids)
    journey_ids = [journey_grid[i][0] for i in range(N_GATES)]

    # Post-gate only Journey: 재투입 에이전트용 (서비스 완료 후 post_gate에서 시작)
    post_journey_ids = []
    for i, g in enumerate(gates):
        is_upper = g["y"] > CONCOURSE_WIDTH / 2
        approach_wp = esc_approach_upper if is_upper else esc_approach_lower
        journey = jps.JourneyDescription([
            post_gate_wp_ids[i],
            esc_approach_upper, esc_approach_lower, dummy_exit
        ])
        journey.set_transition_for_stage(
            post_gate_wp_ids[i],
            jps.Transition.create_fixed_transition(approach_wp))
        # approach_wp 도달 → Python 큐가 슬롯 배정
        jid = sim.add_journey(journey)
        post_journey_ids.append(jid)

    # 에스컬레이터 소프트웨어 큐 슬롯 waypoint + journey 생성
    # 각 슬롯 = 하나의 waypoint. 에이전트는 해당 슬롯 journey로 switch_agent_journey 됨.
    # 슬롯 idx=0이 에스컬 직전(x=24.2), 뒷 슬롯이 서쪽(x-)으로 늘어남
    # 에이전트는 x+ 방향(동쪽)으로 전진하며 capture zone(x=24.5-26) 진입
    # ★ 슬롯을 corridor 내부(y=25-26)에만 배치 → 대합실 통행로와 충돌 방지
    # 2026-04-22: 2열 × 5행 = 10슬롯 (쌍 캡처 방식)
    # 슬롯 순서: [0,1]=row0(front pair), [2,3]=row1, ..., [8,9]=row4(rear)
    # 짝수 인덱스 = col A (y=25.4 or -0.8), 홀수 = col B (y=25.8 or -0.4)
    # 5행 꽉 차면 그 이후는 자유 대기 (stop-and-go)
    _ESC_SLOTS_LOCAL = {
        "upper": [
            (31.2, 25.4), (31.2, 25.8),  # row 0 (front, 먼저 탑승)
            (30.6, 25.4), (30.6, 25.8),
            (30.0, 25.4), (30.0, 25.8),
            (29.4, 25.4), (29.4, 25.8),
            (28.8, 25.4), (28.8, 25.8),  # row 4 (rear)
        ],
        "lower": [
            (31.2, -0.8), (31.2, -0.4),
            (30.6, -0.8), (30.6, -0.4),
            (30.0, -0.8), (30.0, -0.4),
            (29.4, -0.8), (29.4, -0.4),
            (28.8, -0.8), (28.8, -0.4),
        ],
    }
    _ESC_WP_R_LOCAL = 0.28
    esc_queue_wps = {"upper": [], "lower": []}
    esc_queue_journeys = {"upper": [], "lower": []}
    for side in ["upper", "lower"]:
        for pos in _ESC_SLOTS_LOCAL[side]:
            wp = sim.add_waypoint_stage(pos, _ESC_WP_R_LOCAL)
            esc_queue_wps[side].append(wp)
            j = jps.JourneyDescription([wp, dummy_exit])
            # 전이 없음 → 슬롯 도착 후 대기 (Python 큐가 다음 동작 결정)
            jid = sim.add_journey(j)
            esc_queue_journeys[side].append(jid)

    # 하위 호환을 위해 exit_upper/exit_lower 이름 보존 (escalator_wp로 alias)
    exit_upper = escalator_wp_upper
    exit_lower = escalator_wp_lower

    mid_gate = N_GATES // 2
    default_journey_id = journey_ids[mid_gate]
    default_stage_id = approach_wp_ids[mid_gate]

    return (sim, gates, walkable, vis_obstacles, gate_openings,
            approach_wp_ids, approach_wp_grid, post_gate_wp_ids,
            journey_ids, journey_grid, post_journey_ids,
            default_journey_id, default_stage_id,
            exit_upper, exit_lower,
            esc_queue_wps, esc_queue_journeys)


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
     default_journey_id, default_stage_id,
     exit_upper, exit_lower,
     esc_queue_wps, esc_queue_journeys) = create_simulation()

    rng = np.random.default_rng(BATCH_SEED)
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
        "escalator_processed": {"upper": 0, "lower": 0},
        "escalator_queue_history": [],  # (t, upper_q, lower_q)
    }

    # 각 게이트의 서비스 상태 추적
    # None 또는 {"agent_id": id, "start": time, "duration": dur}
    # 또는 {"clearing": True, "clear_start": time}
    gate_service = [None] * N_GATES
    passed_agents = set()  # 이미 통과 처리된 에이전트 ID (중복 카운트 방지)

    # ── 에스컬레이터 소프트웨어 큐 (SPACE에서 capture zone 읽음) ──
    # 실제 에스컬레이터(30 m/min, 1.0m 폭) 처리율 ≈ 1.17 ped/s (Cheung & Lam 2002)
    ESCALATOR_SERVICE_TIME = _ESC_LOWER["service_time"]
    # Capture zone: (xmin, xmax, ymin, ymax) 튜플
    _cz_u = _ESC_UPPER["capture_zone"]
    _cz_l = _ESC_LOWER["capture_zone"]
    CAPTURE_UPPER = (_cz_u["x_range"][0], _cz_u["x_range"][1],
                     _cz_u["y_range"][0], _cz_u["y_range"][1])
    CAPTURE_LOWER = (_cz_l["x_range"][0], _cz_l["x_range"][1],
                     _cz_l["y_range"][0], _cz_l["y_range"][1])
    escalator_state = {
        "upper": {"busy_until": 0.0, "captured": [], "queue_len": 0},
        "lower": {"busy_until": 0.0, "captured": [], "queue_len": 0},
    }
    # 에스컬레이터 소프트웨어 큐 (슬롯 배정된 agent 순서 리스트)
    esc_sw_queue = {"upper": [], "lower": []}

    # ── 시야 기반 대기 로직 (에스컬레이터 존) ──
    # CFSM V2 등방성 한계 보완: 목표 방향 전방 시야 콘 안에 다른 에이전트가
    # 있고, 그 에이전트가 wp에 더 가까우면 본 에이전트 정지. FIFO 보장.
    ESC_WP_UPPER = tuple(_ESC_UPPER["waypoint"])
    ESC_WP_LOWER = tuple(_ESC_LOWER["waypoint"])
    ESC_ZONE_R = 1.2            # 에스컬레이터 직근 영향 반경 (m)
    VISION_R = 2.5              # 시야 반경 (m)
    VISION_DOT_TH = 0.64        # 전방 시야각 100° (cos50°=0.643) — 2026-04-22
    ESC_SPEED_STOP = 0.02       # 정지 시 desired_speed (완전 0 금지)
    # 에스컬 큐 제어 파라미터
    STOPPED_SPREAD_R = 8.0      # 시야 로직 적용 반경 (기준: ESC_WP)
    # 앞사람이 거의 멈춰있을 때만 blocked (앞이 움직이면 나도 움직임)
    FRONT_SLOW_TH = 0.3         # 앞 agent 속도 이 이하면 정체 판정 (2026-04-22: 0.6→0.3)
    # ── 에스컬레이터 소프트웨어 큐 슬롯 정의 (2열 × 5행 = 10슬롯, 쌍 캡처) ──
    # 2026-04-22: 대기행렬 5행 고정. 뒷쪽 agents 는 자유 대기 (stop-and-go)
    # [slot 0, slot 1] = 쌍 (앞줄) → 에스컬 서비스 1사이클마다 함께 탑승
    ESC_QUEUE_SLOTS = {
        "upper": [
            (31.2, 25.4), (31.2, 25.8),  # row 0 (front pair)
            (30.6, 25.4), (30.6, 25.8),
            (30.0, 25.4), (30.0, 25.8),
            (29.4, 25.4), (29.4, 25.8),
            (28.8, 25.4), (28.8, 25.8),  # row 4 (rear)
        ],
        "lower": [
            (31.2, -0.8), (31.2, -0.4),
            (30.6, -0.8), (30.6, -0.4),
            (30.0, -0.8), (30.0, -0.4),
            (29.4, -0.8), (29.4, -0.4),
            (28.8, -0.8), (28.8, -0.4),
        ],
    }
    ESC_QUEUE_MAX = len(ESC_QUEUE_SLOTS["upper"])   # 슬롯 수/에스컬
    ESC_QUEUE_WP_R = 0.28        # 슬롯 waypoint 캡처 반경
    ESC_SLOT_STOP_R  = 0.35      # 이 거리 이내면 "슬롯 도착" 판정
    ESC_V0_DEC_ALPHA = 0.35     # 감속 지수 평활 계수 (빠른 감속)
    ESC_V0_ACC_ALPHA = 0.20     # 가속 지수 평활 계수 (완만한 출발)
    # ★ 2026-04-22 FIFO 강화: staging 감지를 approach_wp 위치에서
    # 게이트에서 자연 대각선 이동 → approach 도달 시 큐 진입 (FIFO)
    ESC_STAGING_R  = 0.80        # approach_wp 근처 감지 반경
    ESC_APPROACH_UPPER = (28.5, 24.5)  # approach_wp upper 좌표와 일치
    ESC_APPROACH_LOWER = (28.5,  0.5)
    PROX_SCALE_MIN = 0.4        # SPREAD_INNER 지점 속도 스케일 (v0 대비)
    # 측면 접근 페널티 (Y_WEIGHT 에스컬 버전 — x방향 접근 시 감속)
    LATERAL_UX_TH = 0.3         # |ux| > 이 값부터 측면 접근 판정
    LATERAL_PENALTY_MIN = 0.3   # 완전 측면(|ux|=1.0) 시 속도 스케일
    STOPPED_SPEED_TH = 0.15     # 이 속도 이하는 "정지"로 판정 (m/s)

    # 소프트웨어 큐: 게이트별 FIFO 리스트 (agent_id 저장)
    sw_queue = [[] for _ in range(N_GATES)]
    last_queue_entry_time = [-999.0] * N_GATES  # 게이트별 마지막 큐 진입 시각
    QUEUE_ENTRY_MIN_GAP = 0.5  # 큐 진입 최소 간격 (초) — 1명 줄 서는 시간

    video_frames = []
    frame_interval = int(0.5 / DT)

    # 궤적 데이터: [(time, agent_id, x, y, gate_idx, state)]
    trajectory_data = []
    # 배치 모드: downsample (기본 0.5s), 비배치: 0.1s (기존)
    _traj_dt = BATCH_TRAJECTORY_INTERVAL if BATCH_SAVE_TRAJECTORY else 0.1
    traj_interval = int(_traj_dt / DT)

    GATE_CLEAR_TIME = 0.5  # 게이트 문 닫히는 시간 (초)

    print("\n시뮬레이션 실행 중...")

    for step in range(total_steps):
        current_time = step * DT

        # ── 보행자 생성 (모든 큐 꽉 차면 스폰 지연 = 승강장 대기) ──
        while (arrival_idx < len(arrival_times) and
               arrival_times[arrival_idx][0] <= current_time):
            if all(len(sw_queue[gi]) >= QUEUE_MAX_LENGTH for gi in range(N_GATES)):
                break
            arr_time, stair_idx = arrival_times[arrival_idx]
            stair = STAIRS[stair_idx]
            desired_speed = np.clip(
                rng.normal(PED_SPEED_MEAN, PED_SPEED_STD),
                PED_SPEED_MIN, PED_SPEED_MAX)

            temperament = assign_temperament(rng)
            is_tagless = rng.random() < TAGLESS_RATIO

            # 예상 큐 = 현재 큐 + 시야 내(앞쪽 8m) 다른 보행자가 향하는 게이트 카운트
            # 유한 시야 가정: Moussaïd et al. (2011) 기반
            VISION_RANGE = 8.0
            gate_queue = [len(q) for q in sw_queue]

            # 배치 모드: 전용 게이트 필터 (태그리스 전용 vs 태그 전용 상호 배타)
            # 금지 게이트는 큐 카운트를 크게 하여 LRP 선택에서 배제
            if BATCH_TAGLESS_ONLY_GATES:
                if is_tagless:
                    _forbidden = set(range(N_GATES)) - set(BATCH_TAGLESS_ONLY_GATES)
                else:
                    _forbidden = set(BATCH_TAGLESS_ONLY_GATES)
                for _gi in _forbidden:
                    gate_queue[_gi] = 99999
            _my_x = stair["x"]  # 계단 위치 기준 (spawn 직전)
            for _other in sim.agents():
                _oad = agent_data.get(_other.id, {})
                if _oad.get("serviced") or _oad.get("queued"):
                    continue
                _ogi = _oad.get("gate_idx", -1)
                if _ogi < 0:
                    continue
                _ox = _other.position[0]
                # 내 앞쪽(+x) + 8m 이내만 관찰
                if _my_x < _ox < _my_x + VISION_RANGE:
                    gate_queue[_ogi] += 1

            # ★ 2026-04-22: spawn y 를 목표 게이트 y에 비례 배치 (동선 교차 완화)
            # 1) 계단 중앙 기준 LRP 1회 호출 → 목표 게이트 결정
            # 2) 게이트 y 를 stair y 범위로 선형 매핑 → spawn y 결정
            stair_center_x = stair["x"] + 1.5
            stair_center_y = (stair["y_start"] + stair["y_end"]) / 2
            gate_idx = choose_gate_lrp(
                rng, (stair_center_x, stair_center_y), desired_speed, temperament,
                gates, gate_queue, stage="1st")
            choice_stage = 1
            _depth = min(len(sw_queue[gate_idx]), MAX_QUEUE_DEPTH_WP)
            jid = journey_grid[gate_idx][_depth]
            sid = approach_wp_grid[gate_idx][_depth]

            # 게이트 y 범위 -> stair y 범위 선형 매핑
            _gy_min = min(g["y"] for g in gates)
            _gy_max = max(g["y"] for g in gates)
            _gy = gates[gate_idx]["y"]
            _norm = (_gy - _gy_min) / (_gy_max - _gy_min) if _gy_max > _gy_min else 0.5
            _stair_yspan = stair["y_end"] - stair["y_start"]
            spawn_y_target = stair["y_start"] + _norm * _stair_yspan

            spawned = False
            for retry in range(5):
                spawn_x = stair["x"] + rng.uniform(0.5, 2.5)
                # spawn_y: 목표 게이트 y 매핑 + 작은 노이즈
                spawn_y = spawn_y_target + rng.uniform(-0.3, 0.3)
                spawn_y = np.clip(spawn_y, stair["y_start"], stair["y_end"])
                if retry > 0:
                    spawn_x += rng.uniform(0.5, 2.0)
                    spawn_y += rng.uniform(-0.4, 0.4)
                    spawn_y = np.clip(spawn_y, stair["y_start"], stair["y_end"])

                try:
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
                        "target_depth": min(len(sw_queue[gate_idx]), MAX_QUEUE_DEPTH_WP) if gate_idx >= 0 else 0,
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
                arrival_times.insert(arrival_idx + 1, (current_time + DT * 2, stair_idx))

            arrival_idx += 1

        # ── 소프트웨어 큐: 접근 구역 도달 에이전트 제거 (sim.iterate 전) ──
        # 스텝 시작 시 큐 tail 위치 스냅샷 (연쇄 진입 방지)
        queue_tail_snap = []
        for gi in range(N_GATES):
            n_q = len(sw_queue[gi])
            if n_q == 0:
                queue_tail_snap.append(QUEUE_HEAD_X - 0.8)  # 빈 큐: 0.8m 뒤에서 흡수
            else:
                queue_tail_snap.append(QUEUE_HEAD_X - n_q * QUEUE_SPACING - 0.8)

        # queue_tail을 지나친 에이전트 전부 수집 (게이트별, px 내림차순)
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
            if px > queue_tail_snap[gi] and len(sw_queue[gi]) < QUEUE_MAX_LENGTH:
                gate_candidates[gi].append((px, aid))

        for gi in range(N_GATES):
            gate_candidates[gi].sort(reverse=True)
            for px_c, aid in gate_candidates[gi]:
                # 시간 기반 제한: 빈 큐면 즉시, 아니면 0.5초 간격
                if len(sw_queue[gi]) > 0 and current_time - last_queue_entry_time[gi] < QUEUE_ENTRY_MIN_GAP:
                    break
                ad = agent_data[aid]
                ad["queued"] = True
                ad["queue_enter_time"] = current_time
                sw_queue[gi].append(aid)
                # 시각화: 현재 위치(px_c)에서 슬롯까지 ease-in 보간 (역행 점프 방지)
                _slot = len(sw_queue[gi]) - 1
                _qx = QUEUE_HEAD_X - _slot * QUEUE_SPACING
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
                    # ★ 2026-04-24: 재투입 실패 방지 — 위치 조정 재시도
                    # 기존: 단일 위치 (13.5, gate_y) 에서 실패 시 agent 소실
                    # 개선: post_gate 근처 여러 위치 시도 (x, y 노이즈) + 실패 시 대기
                    gate_y = gates[gi]["y"]
                    _reinject_ok = False
                    _base_x = GATE_X + GATE_LENGTH + 0.3
                    for _rx in range(6):
                        _try_x = _base_x + _rx * 0.15   # x 0.15m 간격으로 6회
                        for _ry_off in [0.0, 0.15, -0.15, 0.25, -0.25]:
                            _try_y = gate_y + _ry_off
                            try:
                                new_aid = sim.add_agent(
                                    jps.CollisionFreeSpeedModelV2AgentParameters(
                                        journey_id=post_journey_ids[gi],
                                        stage_id=post_gate_wp_ids[gi],
                                        position=(_try_x, _try_y),
                                        time_gap=CFSM_TIME_GAP,
                                        desired_speed=ad["original_speed"],
                                        radius=CFSM_RADIUS,
                                        strength_neighbor_repulsion=8.0,
                                        range_neighbor_repulsion=0.1,
                                        strength_geometry_repulsion=5.0,
                                        range_geometry_repulsion=0.02,
                                    ))
                                # 새 ID 에 기존 데이터 매핑
                                agent_data[new_aid] = ad
                                ad["serviced"] = True
                                passed_agents.add(aid_done)
                                stats["service_times"].append(svc["duration"])
                                stats["gate_counts"][gi] += 1
                                _reinject_ok = True
                                break
                            except Exception:
                                continue
                        if _reinject_ok:
                            break
                    if not _reinject_ok:
                        # 재투입 모두 실패 → 서비스 상태 유지, 다음 step 재시도
                        stats.setdefault("reinject_retry", 0)
                        stats["reinject_retry"] += 1
                        continue
                    gate_service[gi] = {"clearing": True, "clear_start": current_time}
                continue

            # Phase C: 게이트 비어있고 큐에 사람 있으면 서비스 시작
            if sw_queue[gi]:
                head_aid = sw_queue[gi].pop(0)
                ad = agent_data[head_aid]
                # 배치: 실제 게이트 서비스 시작 시각 (큐 대기 종료)
                ad["service_start_time"] = current_time
                # 태그/태그리스 공통: 서비스 시작 (서비스 시간은 sample_service_time에서 결정)
                gate_service[gi] = {
                    "agent_id": head_aid,
                    "start": current_time,
                    "duration": ad["service_time"],
                }
                # 큐 시프트 모션: 남은 사람들의 타깃을 한 칸씩 앞으로
                for _j, _qaid in enumerate(sw_queue[gi]):
                    _qad = agent_data.get(_qaid)
                    if _qad is None:
                        continue
                    _new_target = QUEUE_HEAD_X - _j * QUEUE_SPACING
                    if abs(_new_target - _qad.get("queue_target_x", _new_target)) > 1e-6:
                        _qad["queue_shift_from"] = _qad.get("queue_visual_x", _new_target)
                        _qad["queue_target_x"] = _new_target
                        _qad["queue_shift_start"] = current_time

        # ── 대기열 내 LRP 재선택 ──
        # 배치 모드(전용 게이트): 잭키잉 시 필터 무시로 전용 게이트가 섞이는 문제 방지 → 비활성
        _jockey_active = QUEUE_RESELECT_ENABLED and not BATCH_TAGLESS_ONLY_GATES
        if _jockey_active and step % int(QUEUE_RESELECT_INTERVAL / DT) == 0:
            gate_queue_snap = [len(q) for q in sw_queue]
            for gi in range(N_GATES):
                if gate_queue_snap[gi] < QUEUE_RESELECT_MIN_QUEUE:
                    continue
                # head(서비스 직전)는 제외, 뒤에서부터 검토
                # 게이트당 1명만 이동 (동시 대량 이탈 방지)
                moved = False
                candidates = list(sw_queue[gi][1:])
                for qaid in candidates:
                    if moved:
                        break
                    ad = agent_data.get(qaid)
                    if not ad:
                        continue
                    # LRP로 최적 게이트 판단 (현재 큐 위치 기준)
                    q_pos_idx = sw_queue[gi].index(qaid)
                    qx = GATE_X - 0.3 - q_pos_idx * 0.5
                    gate_y = gates[gi]["y"]
                    new_gate = choose_gate_lrp(
                        rng, (qx, gate_y), ad["original_speed"],
                        ad["temperament"], gates, gate_queue_snap, stage="2nd")
                    if (new_gate != gi and
                            abs(new_gate - gi) <= 1 and          # 인접 게이트만 (jockeying)
                            gate_queue_snap[new_gate] < gate_queue_snap[gi] - QUEUE_RESELECT_MIN_DIFF):
                        sw_queue[gi].remove(qaid)
                        sw_queue[new_gate].append(qaid)
                        ad["gate_idx"] = new_gate
                        stats["reroute_count"] += 1
                        # 큐 시프트 모션: 떠나는 게이트의 잔류 인원 앞당김
                        for _j, _qaid in enumerate(sw_queue[gi]):
                            _qad = agent_data.get(_qaid)
                            if _qad is None:
                                continue
                            _new_target = QUEUE_HEAD_X - _j * QUEUE_SPACING
                            if abs(_new_target - _qad.get("queue_target_x", _new_target)) > 1e-6:
                                _qad["queue_shift_from"] = _qad.get("queue_visual_x", _new_target)
                                _qad["queue_target_x"] = _new_target
                                _qad["queue_shift_start"] = current_time
                        # 옮긴 본인: 새 게이트의 마지막 슬롯으로 ease 시작
                        _new_slot = len(sw_queue[new_gate]) - 1
                        _new_target = QUEUE_HEAD_X - _new_slot * QUEUE_SPACING
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
            dist_to_gate = GATE_X - px

            # 1차/2차 자유보행 재선택 제거 — spawn 시 1회 결정만 사용 (DO NOT REVERT)
            if gi < 0:
                continue
            if dist_to_gate <= 0:
                continue

        # ── 동적 waypoint 업데이트: 큐 깊이 변경 시 접근 목표 전환 ──
        if step % int(0.5 / DT) == 0:
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
                new_depth = min(len(sw_queue[gi]), MAX_QUEUE_DEPTH_WP)
                # 새 waypoint 위치 계산
                if new_depth == 0:
                    wp_x = QUEUE_HEAD_X - 0.8
                else:
                    wp_x = QUEUE_HEAD_X - new_depth * QUEUE_SPACING - 0.8
                # 이미 waypoint보다 앞에 있으면 역행 방지 → 즉시 흡수
                px = agent.position[0]
                if px > wp_x and len(sw_queue[gi]) < QUEUE_MAX_LENGTH:
                    if current_time - last_queue_entry_time[gi] >= QUEUE_ENTRY_MIN_GAP or len(sw_queue[gi]) == 0:
                        ad["queued"] = True
                        ad["queue_enter_time"] = current_time
                        sw_queue[gi].append(aid)
                        _slot = len(sw_queue[gi]) - 1
                        _qx = QUEUE_HEAD_X - _slot * QUEUE_SPACING
                        # 시각화: 현재 위치(px)에서 슬롯까지 ease 보간
                        ad["queue_visual_x"] = px
                        ad["queue_target_x"] = _qx
                        ad["queue_shift_from"] = px
                        ad["queue_shift_start"] = current_time
                        sim.mark_agent_for_removal(aid)
                        last_queue_entry_time[gi] = current_time
                        continue
                # 큐 길이 변화 시 wp 갱신 (커지든 작아지든) — 항상 현재 tail로 향하게
                cur_depth = ad.get("target_depth", new_depth)
                if new_depth != cur_depth:
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

        # ── 에스컬 큐 visual 위치 갱신 (2D ease-in-out) ──
        ESC_SHIFT_DURATION = 0.8  # 슬롯 이동 시간 (s)
        for _side in ("upper", "lower"):
            for _aid in esc_sw_queue[_side]:
                _ad = agent_data.get(_aid)
                if _ad is None or _ad.get("esc_shift_start") is None:
                    continue
                _elapsed = current_time - _ad["esc_shift_start"]
                if _elapsed >= ESC_SHIFT_DURATION:
                    _ad["esc_visual_x"] = _ad["esc_target_x"]
                    _ad["esc_visual_y"] = _ad["esc_target_y"]
                    _ad["esc_shift_start"] = None
                else:
                    _t = _elapsed / ESC_SHIFT_DURATION
                    _eased = ease_in_out(_t)
                    _ad["esc_visual_x"] = (
                        _ad["esc_shift_from_x"]
                        + (_ad["esc_target_x"] - _ad["esc_shift_from_x"]) * _eased
                    )
                    _ad["esc_visual_y"] = (
                        _ad["esc_shift_from_y"]
                        + (_ad["esc_target_y"] - _ad["esc_shift_from_y"]) * _eased
                    )

        # ── 궤적 기록 ──
        if step % traj_interval == 0:
            # 시뮬레이션 내 활성 에이전트
            for agent in sim.agents():
                aid = agent.id
                px, py = agent.position
                ad = agent_data.get(aid, {})
                gi = ad.get("gate_idx", -1)
                state = "passed" if ad.get("serviced") else "moving"
                trajectory_data.append((current_time, aid, px, py, gi, state))

            # 소프트웨어 큐 내 에이전트 (시각화 위치 = visual_x)
            for gi in range(N_GATES):
                gate_y = gates[gi]["y"]
                for j, qaid in enumerate(sw_queue[gi]):
                    ad = agent_data.get(qaid, {})
                    qx = ad.get("queue_visual_x", QUEUE_HEAD_X - j * QUEUE_SPACING)
                    trajectory_data.append((current_time, qaid, qx, gate_y, gi, "queue"))

            # 에스컬 소프트웨어 큐 에이전트 (visual 위치)
            for _side in ("upper", "lower"):
                for _aid in esc_sw_queue[_side]:
                    _ad = agent_data.get(_aid, {})
                    _vx = _ad.get("esc_visual_x")
                    _vy = _ad.get("esc_visual_y")
                    if _vx is not None and _vy is not None:
                        trajectory_data.append((current_time, _aid, _vx, _vy, -1, "esc_queue"))

        # ── 통계 & 프레임 ──
        if step % int(1.0 / DT) == 0:
            gq = [len(q) for q in sw_queue]
            stats["queue_history"].append((current_time, gq.copy()))

        if step % frame_interval == 0:
            frame_data = []
            # 시뮬레이션 내 활성 에이전트 (JuPedSim 에 남아있는 것만)
            for a in sim.agents():
                ad = agent_data.get(a.id, {})
                if ad.get("esc_slot") == "staging":
                    s = "esc_staging"
                elif ad.get("serviced"):
                    s = "passed"
                else:
                    s = "approach"
                tl = ad.get("is_tagless", False)
                frame_data.append((a.position[0], a.position[1], s, tl))

            # 게이트 소프트웨어 큐 에이전트 (시각화 위치 = visual_x, ease 적용)
            for gi in range(N_GATES):
                gate_y = gates[gi]["y"]
                for j, qaid in enumerate(sw_queue[gi]):
                    ad = agent_data.get(qaid, {})
                    qx = ad.get("queue_visual_x", QUEUE_HEAD_X - j * QUEUE_SPACING)
                    tl = ad.get("is_tagless", False)
                    frame_data.append((qx, gate_y, "queue", tl))
                # 서비스 중 에이전트 (게이트 head에 표시)
                if gate_service[gi] is not None and "agent_id" in gate_service[gi]:
                    svc_aid = gate_service[gi]["agent_id"]
                    tl = agent_data.get(svc_aid, {}).get("is_tagless", False)
                    frame_data.append((GATE_X - 0.1, gate_y, "service", tl))

            # 에스컬 소프트웨어 큐 에이전트 (visual 위치, 2D ease)
            for _side in ("upper", "lower"):
                for _aid in esc_sw_queue[_side]:
                    _ad = agent_data.get(_aid, {})
                    _vx = _ad.get("esc_visual_x")
                    _vy = _ad.get("esc_visual_y")
                    if _vx is None or _vy is None:
                        continue
                    _tl = _ad.get("is_tagless", False)
                    frame_data.append((_vx, _vy, "esc_queue", _tl))

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

                    # 에스컬 큐 슬롯 에이전트: 밀집 정렬 time_gap 고정
                    # (슬롯 간격 0.5m, time_gap=0.20 → 원하는 간격 0.27m < 0.5m → 진동 없음)
                    _esc_slot = agent_data.get(aid, {}).get("esc_slot")
                    if isinstance(_esc_slot, int):
                        try:
                            sim.agent(aid).model.time_gap = 0.20
                        except Exception:
                            pass
                        continue

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

        # ── 에스컬 큐 에이전트 stop-and-go (지수 평활 가감속) ──
        # esc_advancing=True  → 새 슬롯으로 이동 중 → v0 target = original_speed
        # esc_advancing=False → 슬롯 도착 대기   → v0 target = 0
        # 실제 v0는 지수 평활으로 부드럽게 변화 (JuPedSim 런타임 속성: model.v0)
        for _agent in sim.agents():
            _aid = _agent.id
            _ad = agent_data.get(_aid)
            if _ad is None or not isinstance(_ad.get("esc_slot"), int):
                continue
            _px, _py = _agent.position
            _side = _ad.get("esc_side", "upper")
            _sidx = _ad["esc_slot"]
            _slots = ESC_QUEUE_SLOTS[_side]
            # 슬롯 도착 감지
            if _ad.get("esc_advancing", True) and _sidx < len(_slots):
                _sx, _sy = _slots[_sidx]
                if np.hypot(_px - _sx, _py - _sy) < ESC_SLOT_STOP_R:
                    _ad["esc_advancing"] = False
            # 지수 평활로 v0 조정
            _target_v0 = _ad["original_speed"] if _ad.get("esc_advancing", True) else 0.0
            _cur_v0 = _ad.get("_esc_v0", _ad["original_speed"])
            _alpha = ESC_V0_DEC_ALPHA if _target_v0 < _cur_v0 else ESC_V0_ACC_ALPHA
            _new_v0 = _cur_v0 + _alpha * (_target_v0 - _cur_v0)
            if _new_v0 < 0.03:
                _new_v0 = 0.0
            _ad["_esc_v0"] = _new_v0
            try:
                sim.agent(_aid).model.desired_speed = _new_v0
            except Exception:
                pass

        # ── 시야 기반 대기 로직 (에스컬 존, 2스텝마다) ──
        # serviced 완료 + 슬롯 미배정 에이전트 대상
        # 전방 72° 콘 안에 wp에 더 가깝고 느린(< FRONT_SLOW_TH) 에이전트 있으면 감속
        # front-most(wp 가장 가까운) 에이전트는 면제 → 교착 방지
        if step % 2 == 0:
            _approachers = {}
            for _ag in sim.agents():
                _aid2 = _ag.id
                _ad2 = agent_data.get(_aid2)
                if _ad2 is None or not _ad2.get("serviced"):
                    continue
                if isinstance(_ad2.get("esc_slot"), int) or _ad2.get("esc_slot") == "captured":
                    continue
                _px2, _py2 = _ag.position
                _du2 = np.hypot(_px2 - ESC_WP_UPPER[0], _py2 - ESC_WP_UPPER[1])
                _dl2 = np.hypot(_px2 - ESC_WP_LOWER[0], _py2 - ESC_WP_LOWER[1])
                _side2 = "upper" if _du2 < _dl2 else "lower"
                _d_wp2 = _du2 if _side2 == "upper" else _dl2
                if _d_wp2 > STOPPED_SPREAD_R:
                    continue
                _approachers[_aid2] = (_px2, _py2, _side2, _d_wp2)
            # side별 front-most 면제
            _front = {}
            for _s2 in ("upper", "lower"):
                _cands = [(a, d) for a, (_, _, s, d) in _approachers.items() if s == _s2]
                if _cands:
                    _front[_s2] = min(_cands, key=lambda x: x[1])[0]
            for _aid2, (_px2, _py2, _side2, _d_wp2) in _approachers.items():
                _wp2 = ESC_WP_UPPER if _side2 == "upper" else ESC_WP_LOWER
                _ad2 = agent_data[_aid2]
                if _front.get(_side2) == _aid2:
                    try:
                        sim.agent(_aid2).model.desired_speed = _ad2["original_speed"]
                    except Exception:
                        pass
                    continue
                if _d_wp2 < ESC_ZONE_R:
                    try:
                        sim.agent(_aid2).model.desired_speed = ESC_SPEED_STOP
                    except Exception:
                        pass
                    continue
                _dxw2 = _wp2[0] - _px2; _dyw2 = _wp2[1] - _py2
                _dw2 = np.hypot(_dxw2, _dyw2)
                if _dw2 < 0.01:
                    continue
                _ux2, _uy2 = _dxw2 / _dw2, _dyw2 / _dw2
                _blocked2 = False
                for _oid2, (_ox2, _oy2, _os2, _od_wp2) in _approachers.items():
                    if _oid2 == _aid2 or _os2 != _side2:
                        continue
                    _dist2 = np.hypot(_ox2 - _px2, _oy2 - _py2)
                    if _dist2 > VISION_R or _dist2 < 0.01:
                        continue
                    if (_ux2 * (_ox2 - _px2) + _uy2 * (_oy2 - _py2)) / _dist2 < VISION_DOT_TH:
                        continue
                    if _od_wp2 >= _d_wp2:
                        continue
                    try:
                        _ov2 = sim.agent(_oid2).model.desired_speed
                    except Exception:
                        _ov2 = 0.0
                    if _ov2 < FRONT_SLOW_TH:
                        _blocked2 = True
                        break
                try:
                    _cv2 = sim.agent(_aid2).model.desired_speed
                    _tv2 = ESC_SPEED_STOP if _blocked2 else _ad2["original_speed"]
                    _av2 = 0.3 if _tv2 < _cv2 else 0.15
                    _nv2 = _cv2 + _av2 * (_tv2 - _cv2)
                    sim.agent(_aid2).model.desired_speed = max(_nv2, ESC_SPEED_STOP if _blocked2 else 0.0)
                except Exception:
                    pass

        # ── 에스컬레이터 소프트웨어 큐 관리 ──
        # ① staging 감지: esc_bridge_wp 근처에 도달한 serviced 에이전트 등록
        # ② 슬롯 배정: 큐 여유 있으면 staging → 맨 뒤 슬롯으로 switch_agent_journey
        # ③ capture: 에스컬 준비 완료 + 큐 비어있지 않으면 맨 앞 에이전트 방출
        # ★ 2026-04-22 역행 방지: 큐 full 시 bridge_wp 접근 에이전트 속도 감속
        # ① staging 감지 (매 스텝)
        for _agent in sim.agents():
            _aid = _agent.id
            _ad = agent_data.get(_aid)
            if _ad is None or not _ad.get("serviced") or _ad.get("esc_slot") is not None:
                continue
            _px, _py = _agent.position
            _du = (_px - ESC_APPROACH_UPPER[0])**2 + (_py - ESC_APPROACH_UPPER[1])**2
            _dl = (_px - ESC_APPROACH_LOWER[0])**2 + (_py - ESC_APPROACH_LOWER[1])**2
            if _du < ESC_STAGING_R**2 or _dl < ESC_STAGING_R**2:
                _side = "upper" if _du <= _dl else "lower"
                _ad["esc_slot"] = "staging"
                _ad["esc_side"] = _side
                _ad["esc_queue_enter"] = current_time

        # ★ 역행 방지 + FIFO 강화: staging 에이전트는 큐에 자리 날 때까지 감속
        # approach_wp에서 staging 감지 → 큐 여유 있으면 즉시 슬롯 배정, 없으면 approach에서 대기
        # 큐 full or staging 인데 슬롯 못 받은 에이전트는 approach 위치 부근에서 감속
        for _side in ("upper", "lower"):
            _queue_full = len(esc_sw_queue[_side]) >= ESC_QUEUE_MAX
            if not _queue_full:
                continue  # 슬롯 여유 있으면 자연 흐름
            for _agent in sim.agents():
                _aid_h = _agent.id
                _ad_h = agent_data.get(_aid_h)
                if _ad_h is None or not _ad_h.get("serviced"):
                    continue
                if _ad_h.get("esc_slot") != "staging":
                    continue
                if _ad_h.get("esc_side") != _side:
                    continue
                try:
                    sim.agent(_aid_h).model.desired_speed = ESC_SPEED_STOP
                except Exception:
                    pass

        # ② 슬롯 배정: staging 에이전트 → 큐 맨 뒤 슬롯 (게이트 큐와 동일 방식)
        # JuPedSim 에서 제거 + 가상 slot 위치로 ease-in (시각적 줄서기)
        for _side in ("upper", "lower"):
            _queue = esc_sw_queue[_side]
            if len(_queue) >= ESC_QUEUE_MAX:
                continue
            _staging = sorted(
                [(_aid, agent_data[_aid]["esc_queue_enter"])
                 for _agent in sim.agents()
                 for _aid in [_agent.id]
                 if agent_data.get(_aid, {}).get("esc_slot") == "staging"
                 and agent_data.get(_aid, {}).get("esc_side") == _side],
                key=lambda x: x[1]
            )
            for _aid, _ in _staging:
                if len(_queue) >= ESC_QUEUE_MAX:
                    break
                _slot_idx = len(_queue)
                _slot_x, _slot_y = ESC_QUEUE_SLOTS[_side][_slot_idx]
                try:
                    _cur = sim.agent(_aid).position
                    _queue.append(_aid)
                    _ad = agent_data[_aid]
                    _ad["esc_slot"] = _slot_idx
                    _ad["esc_visual_x"] = _cur[0]
                    _ad["esc_visual_y"] = _cur[1]
                    _ad["esc_shift_from_x"] = _cur[0]
                    _ad["esc_shift_from_y"] = _cur[1]
                    _ad["esc_target_x"] = _slot_x
                    _ad["esc_target_y"] = _slot_y
                    _ad["esc_shift_start"] = current_time
                    sim.mark_agent_for_removal(_aid)
                except Exception:
                    pass

        # ③ capture + 큐 전진
        for _side in ("upper", "lower"):
            _s = escalator_state[_side]
            _queue = esc_sw_queue[_side]

            # 서비스 완료 체크 — 직전 사이클에 캡처된 모든 에이전트 (pair) 방출
            if current_time >= _s["busy_until"] and _s["captured"]:
                while _s["captured"]:
                    _done = _s["captured"].pop(0)
                    stats["escalator_processed"][_side] += 1
                    if _done in agent_data:
                        agent_data[_done]["sink_time"] = current_time
                        agent_data[_done]["sink_side"] = _side
                _s["busy_until"] = 0.0

            # 강제 진입: 큐 비었을 때 capture zone 내 가장 가까운 2명(pair) 흡수
            if current_time >= _s["busy_until"] and not _queue:
                _cz = _cz_u if _side == "upper" else _cz_l
                _wp_ref = ESC_WP_UPPER if _side == "upper" else ESC_WP_LOWER
                _cands = []
                for _ag in sim.agents():
                    _aad = agent_data.get(_ag.id)
                    if _aad is None or not _aad.get("serviced"):
                        continue
                    if _aad.get("esc_slot") == "captured":
                        continue
                    _ax, _ay = _ag.position
                    if (_cz["x_range"][0] <= _ax <= _cz["x_range"][1] and
                            _cz["y_range"][0] <= _ay <= _cz["y_range"][1]):
                        _d = np.hypot(_ax - _wp_ref[0], _ay - _wp_ref[1])
                        _cands.append((_d, _ag.id))
                _cands.sort()
                _pair_ids = [c[1] for c in _cands[:2]]  # 가장 가까운 2명
                if _pair_ids:
                    try:
                        for _cid in _pair_ids:
                            sim.mark_agent_for_removal(_cid)
                            _s["captured"].append(_cid)
                            agent_data[_cid]["escalator_enter_time"] = current_time
                            agent_data[_cid]["esc_slot"] = "captured"
                        _s["busy_until"] = current_time + ESCALATOR_SERVICE_TIME
                    except Exception:
                        pass

            # 준비 완료 + 큐 있으면 앞 2명(pair) 동시 방출 (가상 큐 - mark_for_removal 불필요)
            if current_time >= _s["busy_until"] and _queue:
                _pair_popped = []
                for _ in range(min(2, len(_queue))):
                    _pair_popped.append(_queue.pop(0))
                for _front in _pair_popped:
                    _s["captured"].append(_front)
                    if _front in agent_data:
                        agent_data[_front]["escalator_enter_time"] = current_time
                        agent_data[_front]["esc_slot"] = "captured"
                _s["busy_until"] = current_time + ESCALATOR_SERVICE_TIME

                # 큐 전진: 나머지 agents 의 target slot 을 2칸 앞으로 shift
                for _new_idx, _aid in enumerate(_queue):
                    _ad = agent_data[_aid]
                    _new_x, _new_y = ESC_QUEUE_SLOTS[_side][_new_idx]
                    if (abs(_new_x - _ad.get("esc_target_x", _new_x)) > 1e-6 or
                            abs(_new_y - _ad.get("esc_target_y", _new_y)) > 1e-6):
                        _ad["esc_shift_from_x"] = _ad.get("esc_visual_x", _new_x)
                        _ad["esc_shift_from_y"] = _ad.get("esc_visual_y", _new_y)
                        _ad["esc_target_x"] = _new_x
                        _ad["esc_target_y"] = _new_y
                        _ad["esc_shift_start"] = current_time
                    _ad["esc_slot"] = _new_idx

            _s["queue_len"] = len(_queue)


        # 에스컬레이터 큐 길이 기록 (통계)
        if step % int(1.0 / DT) == 0:
            stats["escalator_queue_history"].append((
                current_time,
                escalator_state["upper"]["queue_len"],
                escalator_state["lower"]["queue_len"],
            ))

        # ── 배치: Zone density 샘플링 (v3: 세분화된 Zone) ──
        # Zone 3a/3b/3c (exit1쪽): 접근 / 대기 / 서비스
        # Zone 4a/4b/4c (exit4쪽): 접근 / 대기 / 서비스
        if (BATCH_ZONE_CSV_OUT is not None
                and step % int(BATCH_ZONE_SAMPLE_INTERVAL / DT) == 0):
            z1 = z2 = 0
            z3a = z3b = z3c = 0
            z4a = z4b = z4c = 0
            # v4: SPACE에서 직접 읽음
            Z1  = _zone_tuple("Z1")
            Z2  = _zone_tuple("Z2")
            Z3A = _zone_tuple("Z3A")
            Z3B = _zone_tuple("Z3B")
            Z3C = _zone_tuple("Z3C")
            Z4A = _zone_tuple("Z4A")
            Z4B = _zone_tuple("Z4B")
            Z4C = _zone_tuple("Z4C")
            for _a in sim.agents():
                _x, _y = _a.position
                if Z1[0] <= _x <= Z1[1] and Z1[2] <= _y <= Z1[3]: z1 += 1
                if Z2[0] <= _x <= Z2[1] and Z2[2] <= _y <= Z2[3]: z2 += 1
                if Z3A[0] <= _x <= Z3A[1] and Z3A[2] <= _y <= Z3A[3]: z3a += 1
                if Z3B[0] <= _x <= Z3B[1] and Z3B[2] <= _y <= Z3B[3]: z3b += 1
                if Z3C[0] <= _x <= Z3C[1] and Z3C[2] <= _y <= Z3C[3]: z3c += 1
                if Z4A[0] <= _x <= Z4A[1] and Z4A[2] <= _y <= Z4A[3]: z4a += 1
                if Z4B[0] <= _x <= Z4B[1] and Z4B[2] <= _y <= Z4B[3]: z4b += 1
                if Z4C[0] <= _x <= Z4C[1] and Z4C[2] <= _y <= Z4C[3]: z4c += 1
            _queued = sum(len(q) for q in sw_queue)
            z2 += _queued
            z1 += _queued
            # 에스컬 가상 큐 (슬롯 대기) agent 를 Z3B/Z4B 에 포함 — 2026-04-22
            # (esc_sw_queue agent 들은 sim.agents()에서 제거됨)
            z3b += len(esc_sw_queue["lower"])   # lower = exit1 = Z3B
            z4b += len(esc_sw_queue["upper"])   # upper = exit4 = Z4B
            z1  += len(esc_sw_queue["lower"]) + len(esc_sw_queue["upper"])
            # 에스컬 capture 에이전트는 Z3C/Z4C (서비스 중)에 포함
            z3c += len(escalator_state["lower"]["captured"])
            z4c += len(escalator_state["upper"]["captured"])
            z1 += len(escalator_state["lower"]["captured"])
            z1 += len(escalator_state["upper"]["captured"])
            stats.setdefault("zone_history", []).append(
                (current_time, z1, z2, z3a, z3b, z3c, z4a, z4b, z4c))

        # ── 배치: approach_enter_time 기록 (매 스텝, Zone 3a/4a 첫 진입 시각) ──
        if BATCH_METRICS_OUT is not None:
            for _a in sim.agents():
                _aid = _a.id
                _ad = agent_data.get(_aid)
                if _ad is None or _ad.get("approach_enter_time") is not None:
                    continue
                _x, _y = _a.position
                # Zone 3A 또는 4A 첫 진입 검출 (v4: SPACE에서 좌표 읽음)
                _z3a = _zone_tuple("Z3A")
                _z4a = _zone_tuple("Z4A")
                in_3a = _z3a[0] <= _x <= _z3a[1] and _z3a[2] <= _y <= _z3a[3]
                in_4a = _z4a[0] <= _x <= _z4a[1] and _z4a[2] <= _y <= _z4a[3]
                if in_3a or in_4a:
                    _ad["approach_enter_time"] = current_time

        sim.iterate()

        if step % int(30.0 / DT) == 0 and step > 0:
            queued_total = sum(len(q) for q in sw_queue)
            # 디버그: CAPTURE 내 에이전트 수
            up_cap_count = 0
            lo_cap_count = 0
            for a in sim.agents():
                x, y = a.position
                if CAPTURE_UPPER[0] <= x <= CAPTURE_UPPER[1] and CAPTURE_UPPER[2] <= y <= CAPTURE_UPPER[3]:
                    up_cap_count += 1
                if CAPTURE_LOWER[0] <= x <= CAPTURE_LOWER[1] and CAPTURE_LOWER[2] <= y <= CAPTURE_LOWER[3]:
                    lo_cap_count += 1
            esc_up = stats["escalator_processed"]["upper"]
            esc_lo = stats["escalator_processed"]["lower"]
            print(f"  t={current_time:.0f}s | agents: {sim.agent_count()} "
                  f"| queued: {queued_total} "
                  f"| spawned: {spawned_count} | passed: {sum(stats['gate_counts'])} "
                  f"| escalator: up_cap={up_cap_count}/proc={esc_up} "
                  f"lo_cap={lo_cap_count}/proc={esc_lo}")

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

    # 에스컬레이터 통계
    esc_up = stats["escalator_processed"]["upper"]
    esc_lo = stats["escalator_processed"]["lower"]
    q_hist = stats["escalator_queue_history"]
    if q_hist:
        max_q_up = max(q[1] for q in q_hist)
        max_q_lo = max(q[2] for q in q_hist)
    else:
        max_q_up = max_q_lo = 0
    print(f"\n에스컬레이터 (SERVICE_TIME=0.85s, 목표 1.17 ped/s):")
    print(f"  upper: 처리 {esc_up}명, 최대 큐 {max_q_up}명, "
          f"실효처리율 {esc_up / max(SIM_TIME, 1):.2f} ped/s")
    print(f"  lower: 처리 {esc_lo}명, 최대 큐 {max_q_lo}명, "
          f"실효처리율 {esc_lo / max(SIM_TIME, 1):.2f} ped/s")

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

    # ── 배치: per-agent CSV 저장 (dict id로 중복 제거: 게이트 통과 후 재투입된 ID는 원본과 같은 dict 참조) ──
    if BATCH_METRICS_OUT is not None:
        import csv
        with open(BATCH_METRICS_OUT, "w", newline="", encoding="utf-8") as _f:
            _w = csv.writer(_f)
            _w.writerow(["agent_id", "spawn_time", "queue_enter_time",
                         "service_start_time", "approach_enter_time",
                         "capture_enter_time", "escalator_enter_time",
                         "sink_time", "travel_time",
                         "gate_wait_time", "post_gate_time",
                         "esc_wait_precise", "desired_speed",
                         "gate_idx", "is_tagless", "sink_side", "serviced"])
            _seen = set()
            for _aid, _ad in agent_data.items():
                _key = id(_ad)
                if _key in _seen:
                    continue
                _seen.add(_key)
                _st = _ad.get("spawn_time")
                _qt = _ad.get("queue_enter_time")
                _sst = _ad.get("service_start_time")
                _aet = _ad.get("approach_enter_time")
                _cet = _ad.get("capture_enter_time")
                _eet = _ad.get("escalator_enter_time")
                _kt = _ad.get("sink_time")
                _tt = (_kt - _st) if (_st is not None and _kt is not None) else None
                _gwt = (_sst - _qt) if (_qt is not None and _sst is not None) else None
                _pgt = (_kt - _sst) if (_sst is not None and _kt is not None) else None
                _ewp = (_eet - _aet) if (_aet is not None and _eet is not None) else None
                _w.writerow([_aid, _st, _qt, _sst, _aet, _cet, _eet, _kt, _tt,
                             _gwt, _pgt, _ewp,
                             _ad.get("original_speed"),
                             _ad.get("gate_idx"),
                             int(_ad.get("is_tagless", False)),
                             _ad.get("sink_side", ""),
                             int(_ad.get("serviced", False))])
        print(f"  [배치] per-agent metrics -> {BATCH_METRICS_OUT}")

    # ── 배치: zone density CSV 저장 ──
    if BATCH_ZONE_CSV_OUT is not None and stats.get("zone_history"):
        import csv
        with open(BATCH_ZONE_CSV_OUT, "w", newline="", encoding="utf-8") as _f:
            _w = csv.writer(_f)
            _w.writerow(["time", "zone1_count", "zone2_count",
                         "zone3a_count", "zone3b_count", "zone3c_count",
                         "zone4a_count", "zone4b_count", "zone4c_count"])
            for _row in stats["zone_history"]:
                _w.writerow(_row)
        print(f"  [배치] zone density -> {BATCH_ZONE_CSV_OUT}")

    # 배치: trajectory CSV 저장 (heavy outputs 스킵 중에도 별도 옵션으로)
    if BATCH_SAVE_TRAJECTORY and BATCH_TRAJECTORY_OUT is not None:
        import csv
        with open(BATCH_TRAJECTORY_OUT, "w", newline="", encoding="utf-8") as _f:
            _w = csv.writer(_f)
            _w.writerow(["time", "agent_id", "x", "y", "gate_idx", "state"])
            _w.writerows(trajectory_data)
        print(f"  [배치] trajectory -> {BATCH_TRAJECTORY_OUT} "
              f"({len(trajectory_data)} rows)")

    if not BATCH_SKIP_HEAVY_OUTPUTS:
        print(f"\n출력 생성...")
        create_snapshots(video_frames, gates, obstacles, gate_openings)
        create_mp4(video_frames, gates, obstacles, gate_openings)
        plot_queue_history(stats["queue_history"])
        plot_service_time_dist(stats["service_times"])
        save_trajectories(trajectory_data)
        analyze_trajectories(trajectory_data, gates)
    else:
        print(f"\n[배치] heavy outputs 스킵")

    return stats, spawned_count


# =============================================================================
# 시각화
# =============================================================================
STATE_COLORS = {
    "approach": "#1565C0",
    "queue":    "#EF6C00",
    "service":  "#C62828",
    "passed":   "#1565C0",
    "esc_queue":   "#6A1B9A",   # 에스컬 슬롯 배정 (보라)
    "esc_staging": "#AD1457",   # 에스컬 staging 대기 (자홍)
}
# 태그리스 에이전트 색상 (밝은 계열)
TAGLESS_COLORS = {
    "approach": "#00BFA5",
    "queue":    "#FFD600",
    "service":  "#FF6D00",
    "passed":   "#00BFA5",
    "esc_queue":   "#CE93D8",
    "esc_staging": "#F8BBD0",
}


def draw_frame(ax, positions, gates, obstacles, gate_openings, time_sec):
    """v4: SPACE 기반 시뮬 프레임 그리기 (도면 평면도와 동일한 스타일)."""
    ax.clear()

    # 외부 (벽 밖) 짙은 회색 배경
    ax.add_patch(mpatches.Rectangle((-5, -5), 60, 35,
                 facecolor='#37474F', alpha=0.25, zorder=0))
    # walkable (외곽 polygon 흰색 채움)
    ax.add_patch(mpatches.Polygon(SPACE["outer_boundary"], closed=True,
                 facecolor='white', edgecolor='none', zorder=1))
    # 외곽 벽 (검은 굵은 실선)
    ax.add_patch(mpatches.Polygon(SPACE["outer_boundary"], closed=True,
                 facecolor='none', edgecolor='#212121', linewidth=2.5, zorder=10))

    # 비통행 구조물
    for s in SPACE["structures"]:
        x0, x1 = s["x_range"]; y0, y1 = s["y_range"]
        ax.add_patch(mpatches.Rectangle((x0, y0), x1 - x0, y1 - y0,
                     facecolor='#BDBDBD', edgecolor='#424242',
                     hatch='///', alpha=0.6, linewidth=0.8, zorder=2))

    # 게이트 배리어 (이미 obstacles에 들어 있음)
    for obs in obstacles:
        if obs.geom_type == 'Polygon':
            ox, oy = obs.exterior.xy
            ax.fill(ox, oy, color='#546E7A', edgecolor='#263238', linewidth=0.3, zorder=3)
        elif obs.geom_type == 'MultiPolygon':
            for geom in obs.geoms:
                ox, oy = geom.exterior.xy
                ax.fill(ox, oy, color='#546E7A', edgecolor='#263238', linewidth=0.3, zorder=3)

    for opening in gate_openings:
        ox, oy = opening.exterior.xy
        ax.fill(ox, oy, color='#66BB6A', edgecolor='#2E7D32',
                linewidth=0.8, alpha=0.5, zorder=4)

    for g in gates:
        ax.text(g["x"] + GATE_LENGTH / 2, g["y"], str(g["id"] + 1),
                ha='center', va='center', fontsize=7, fontweight='bold',
                color='#1B5E20', zorder=5)

    # 계단 통로
    for stair in STAIRS:
        xs_s, xs_e = stair["x_start"], stair["x_end"]
        ys_s, ys_e = stair["y_start"], stair["y_end"]
        ax.add_patch(mpatches.Rectangle((xs_s, ys_s), xs_e - xs_s, ys_e - ys_s,
                     facecolor='#FFCCBC', edgecolor='#D84315',
                     linewidth=1.0, alpha=0.45, zorder=2))

    # 에스컬레이터 corridor (v4: SPACE 기반)
    for esc in SPACE["escalators"]:
        cx0, cx1 = esc["corridor"]["x_range"]
        cy0, cy1 = esc["corridor"]["y_range"]
        ax.add_patch(mpatches.Rectangle((cx0, cy0), cx1 - cx0, cy1 - cy0,
                     facecolor='#A5D6A7', edgecolor='#1B5E20',
                     linewidth=1.5, alpha=0.7, zorder=3))
        # corridor 진행 화살표
        ax.annotate("", xy=(cx1 - 0.5, (cy0 + cy1) / 2),
                    xytext=(cx0 + 0.7, (cy0 + cy1) / 2),
                    arrowprops=dict(arrowstyle='->', color='#1B5E20',
                                    lw=2, alpha=0.6), zorder=4)
        # capture zone (점선 사각형)
        cz = esc["capture_zone"]
        zx0, zx1 = cz["x_range"]; zy0, zy1 = cz["y_range"]
        ax.add_patch(mpatches.Rectangle((zx0, zy0), zx1 - zx0, zy1 - zy0,
                     facecolor='#1976D2', edgecolor='#0D47A1',
                     linestyle='--', linewidth=1.5, alpha=0.35, zorder=5))
        # 에스컬 핸드레일/벽 (우측만) — 좌측 벽은 실제 물리벽 없어 삭제 (2026-04-20)
        wall_y = cy1 if esc["side"] == "lower" else cy0
        if cx1 > zx1:
            ax.plot([zx1, cx1], [wall_y, wall_y], color='#212121',
                    linewidth=3, solid_capstyle='butt', zorder=11)
        # sink 짧은 막대
        ax.plot([esc["sink_x"], esc["sink_x"]], [cy0, cy1],
                color='#0D47A1', linewidth=4, solid_capstyle='butt', zorder=6)

    # Agent 점 (4튜플 우선)
    if positions:
        if len(positions[0]) >= 4:
            xs = [p[0] for p in positions]
            ys = [p[1] for p in positions]
            cs = [TAGLESS_COLORS.get(p[2], "#00BFA5") if p[3] else STATE_COLORS.get(p[2], "#1565C0") for p in positions]
        elif len(positions[0]) == 3:
            xs = [p[0] for p in positions]
            ys = [p[1] for p in positions]
            cs = [STATE_COLORS.get(p[2], "#1565C0") for p in positions]
        else:
            xs, ys = zip(*positions)
            cs = '#1565C0'
        ax.scatter(xs, ys, s=28, c=cs, edgecolors='white',
                   linewidths=0.4, alpha=0.9, zorder=8)

    n_peds = len(positions) if positions else 0
    ax.text(0.5, NOTCH_Y - 0.5,
            f't = {time_sec:.1f}s | {n_peds} peds',
            fontsize=10, fontweight='bold', color='#333',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white',
                      edgecolor='#999', alpha=0.9), zorder=11)

    ax.set_xlim(-1.5, 38)
    ax.set_ylim(-2.0, CONCOURSE_WIDTH + 2.0)
    ax.set_aspect('equal')
    ax.set_xlabel('x (m)', fontsize=9)
    ax.set_ylabel('y (m)', fontsize=9)
    ax.grid(True, alpha=0.2, linestyle=':', zorder=0)


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
    fig.savefig(OUTPUT_DIR / "snapshots_escalator.png", dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f"  스냅샷: {OUTPUT_DIR / 'snapshots_escalator.png'}")


def create_mp4(frames, gates, obstacles, gate_openings):
    from matplotlib.animation import FuncAnimation, FFMpegWriter
    import imageio_ffmpeg
    target_frames = [(t, pos) for t, pos in frames if t <= SIM_TIME]
    if not target_frames:
        return
    fig, ax = plt.subplots(figsize=(14, 8))

    def animate(i):
        t, positions = target_frames[i]
        draw_frame(ax, positions, gates, obstacles, gate_openings, t)
        ax.set_title(f'성수역 서쪽 (CFSM V2, 소프트웨어 큐) | t = {t:.1f}s | {len(positions)} agents',
                     fontsize=12, fontweight='bold')

    anim = FuncAnimation(fig, animate, frames=len(target_frames), interval=100)
    mp4_path = OUTPUT_DIR / "simulation_escalator.mp4"
    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    plt.rcParams['animation.ffmpeg_path'] = ffmpeg_path
    writer = FFMpegWriter(fps=10, bitrate=2000,
                          extra_args=['-movflags', '+faststart', '-pix_fmt', 'yuv420p'])
    anim.save(str(mp4_path), writer=writer, dpi=120)
    plt.close(fig)
    print(f"  MP4: {mp4_path}")


def save_trajectories(trajectory_data):
    """궤적 데이터를 CSV로 저장"""
    import csv
    traj_path = OUTPUT_DIR / "trajectories_escalator.csv"
    with open(traj_path, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(["time", "agent_id", "x", "y", "gate_idx", "state"])
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
                      columns=["time", "agent_id", "x", "y", "gate_idx", "state"])

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
    fig.savefig(OUTPUT_DIR / "queue_history_escalator.png", dpi=150)
    plt.close(fig)
    print(f"  대기열: {OUTPUT_DIR / 'queue_history_escalator.png'}")


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
    fig.savefig(OUTPUT_DIR / "service_time_escalator.png", dpi=150)
    plt.close(fig)
    print(f"  서비스시간: {OUTPUT_DIR / 'service_time_escalator.png'}")


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
