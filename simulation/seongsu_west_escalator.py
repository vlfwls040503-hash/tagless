"""
성수역 2F 대합실 서쪽 절반 (50m × 25m) - JuPedSim 기하구조
AnyLogic 도면 기반 좌표 변환

좌표계:
  x = 동서방향 (흐름방향: 계단→게이트→출구), 0=왼쪽
  y = 남북방향, 0=아래쪽

흐름: 계단(빨강, x≈3) → 게이트(초록, x≈12) → 출구(파랑, x≈27)
"""

import numpy as np
from shapely import Polygon
from shapely.ops import unary_union
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

# =============================================================================
# 1. 대합실 치수
# =============================================================================
CONCOURSE_LENGTH = 50.0   # x방향 (m)
CONCOURSE_WIDTH = 25.0    # y방향 (m)

# 상단 왼쪽 계단실 들여쓰기 (도면의 L자형 벽)
NOTCH_X = 12.0   # 들여쓰기 끝 x
NOTCH_Y = 22.0   # 들여쓰기 높이

# =============================================================================
# 2. 게이트 규격
# =============================================================================
GATE_X = 12.0              # 게이트 배리어 시작 x좌표
GATE_LENGTH = 1.5          # 게이트 통과 길이 (x방향)
GATE_PASSAGE_WIDTH = 0.55  # 일반 게이트 통로 폭 (y방향)
GATE_HOUSING_WIDTH = 0.30  # 게이트 사이 칸막이 폭 (y방향)
N_GATES = 7

# 게이트 배리어가 차지하는 y범위
BARRIER_Y_BOTTOM = 3.0
BARRIER_Y_TOP = 22.0

# =============================================================================
# 3. 계단 (보행자 출발 통로, 2026-04-18 공간 확장 v4)
# 대합실 = 승강장 2D 겹침. 계단은 가로 통로로 표현 (x=1~11, 10m).
# spawn: x_end (x=11, 승강장쪽 끝) → 계단 내부 x↓ → x_start (x=1, 연결부)
# 'x' 필드는 하위 호환 (= x_start)
# =============================================================================
STAIRS = [
    {"id": "upper", "x": 1.0, "x_start": 1.0, "x_end": 11.0,
     "y_start": 15.0, "y_end": 18.0},
    {"id": "lower", "x": 1.0, "x_start": 1.0, "x_end": 11.0,
     "y_start": 8.0,  "y_end": 11.0},
]

# =============================================================================
# 4. 출구 (보행자 도착선)
# =============================================================================
EXITS = [
    {"id": "upper", "x_start": 27.0, "x_end": 28.0, "y": 24.0},
    {"id": "lower", "x_start": 27.0, "x_end": 28.0, "y": 3.0},
]

# =============================================================================
# 4-b. 에스컬레이터 통로 (2026-04-18 공간 확장)
# 대합실 북쪽 벽(y=25)에 에스컬 4번(용답), 남쪽 벽(y=0)에 에스컬 1번(뚝섬)
# 모두 x=25~35 가로 통로, 폭 1m. 입구는 각 (25, 25) / (25, 0).
# =============================================================================
ESCALATOR_CORRIDOR_LEN = 10.0   # x 방향 길이 (m)
ESCALATOR_CORRIDOR_WIDTH = 1.0  # y 방향 폭 (m)
ESCALATOR_X_START = 25.0
ESCALATOR_X_END = ESCALATOR_X_START + ESCALATOR_CORRIDOR_LEN  # 35.0

ESCALATORS = [
    # 출구 1번 (뚝섬방면, 남쪽)
    {"id": "exit1", "direction": "뚝섬",
     "x_range": (ESCALATOR_X_START, ESCALATOR_X_END),
     "y_range": (-ESCALATOR_CORRIDOR_WIDTH, 0.0),
     "entry": (ESCALATOR_X_START, 0.0),
     "sink_x": ESCALATOR_X_END},
    # 출구 4번 (용답방면, 북쪽)
    {"id": "exit4", "direction": "용답",
     "x_range": (ESCALATOR_X_START, ESCALATOR_X_END),
     "y_range": (CONCOURSE_WIDTH, CONCOURSE_WIDTH + ESCALATOR_CORRIDOR_WIDTH),
     "entry": (ESCALATOR_X_START, CONCOURSE_WIDTH),
     "sink_x": ESCALATOR_X_END},
]

# =============================================================================
# 5. 비통행 구조물 (빗금 영역) — 에스컬레이터 난간 포함
# =============================================================================
# 에스컬레이터 난간(handrail)은 실존 구조물 (도시철도건설규칙 기준
# 1,000mm 폭, 난간 높이/두께 포함). 진입부 1m 폭 × 2m 길이 통로로
# 표현. 통로 내부는 추월 물리적 불가 → 자연 FIFO.
_HR_TH = 0.05   # 난간 두께
_HR_LEN = 1.0   # 난간 길이 (진입부 1m)

STRUCTURES = [
    {"id": "upper_right", "coords": [(30, 16), (48, 16), (48, 24), (30, 24)]},
    {"id": "lower_right", "coords": [(30, 3),  (48, 3),  (48, 11), (30, 11)]},
]


# =============================================================================
# 6. 게이트 위치 계산
# =============================================================================
def calculate_gate_positions():
    """7개 게이트의 중심 y좌표를 계산 (배리어 중앙에 배치)"""
    # 게이트 클러스터 전체 높이
    cluster_height = (
        N_GATES * GATE_PASSAGE_WIDTH +
        (N_GATES + 1) * GATE_HOUSING_WIDTH
    )
    # 배리어 중앙에 정렬
    barrier_center_y = (BARRIER_Y_BOTTOM + BARRIER_Y_TOP) / 2
    cluster_bottom = barrier_center_y - cluster_height / 2

    gates = []
    for i in range(N_GATES):
        # 첫 칸막이 + i번째 게이트까지의 거리
        y = (cluster_bottom
             + GATE_HOUSING_WIDTH              # 첫 칸막이
             + i * (GATE_PASSAGE_WIDTH + GATE_HOUSING_WIDTH)
             + GATE_PASSAGE_WIDTH / 2)         # 통로 중심

        gates.append({
            "id": i,
            "x": GATE_X,
            "y": y,
            "passage_width": GATE_PASSAGE_WIDTH,
        })

    return gates


# =============================================================================
# 7. 기하구조 생성
# =============================================================================
def build_geometry(gates, include_barrier=True, passage_width_override=None,
                   barrier_thickness=None):
    """
    walkable area 생성

    include_barrier=True:  게이트 배리어를 물리적 장애물로 포함
    include_barrier=False: 배리어 없이 열린 공간
    passage_width_override: 시뮬레이션용 통로 폭 (None이면 게이트 원래 폭 사용)
    barrier_thickness: 배리어 두께 (None이면 GATE_LENGTH 사용)
        - 시뮬레이션: 0.2m (얇은 벽 → 낑김 방지, 우회 차단)
        - 시각화: None (원래 1.5m)
    """
    bt = barrier_thickness if barrier_thickness else GATE_LENGTH

    # 외곽 경계 (상단 왼쪽 들여쓰기 + 남/북쪽 에스컬레이터 통로 돌출)
    outer = Polygon([
        (0, 0),
        (ESCALATOR_X_START, 0),                                 # 에스컬 1 서쪽 진입
        (ESCALATOR_X_START, -ESCALATOR_CORRIDOR_WIDTH),         # 에스컬 1 남서
        (ESCALATOR_X_END, -ESCALATOR_CORRIDOR_WIDTH),           # 에스컬 1 남동
        (ESCALATOR_X_END, 0),                                   # 에스컬 1 복귀
        (CONCOURSE_LENGTH, 0),
        (CONCOURSE_LENGTH, CONCOURSE_WIDTH),
        (ESCALATOR_X_END, CONCOURSE_WIDTH),                     # 에스컬 4 동쪽 진입
        (ESCALATOR_X_END, CONCOURSE_WIDTH + ESCALATOR_CORRIDOR_WIDTH),
        (ESCALATOR_X_START, CONCOURSE_WIDTH + ESCALATOR_CORRIDOR_WIDTH),
        (ESCALATOR_X_START, CONCOURSE_WIDTH),                   # 에스컬 4 복귀
        (NOTCH_X, CONCOURSE_WIDTH),
        (NOTCH_X, NOTCH_Y),
        (0, NOTCH_Y),
    ])

    # 비통행 구조물 — visible=False 는 walkable에서 빼지만 시각화 리스트엔 제외
    obstacles_all = []       # walkable 차감용 (모든 구조물)
    obstacles_visible = []   # 시각화용 (visible=True만)
    for s in STRUCTURES:
        poly = Polygon(s["coords"])
        obstacles_all.append(poly)
        if s.get("visible", True):
            obstacles_visible.append(poly)

    # 게이트 배리어
    gate_openings = []
    for g in gates:
        pw = passage_width_override if passage_width_override else g["passage_width"]
        opening = Polygon([
            (GATE_X - 0.01, g["y"] - pw / 2),
            (GATE_X + bt + 0.01, g["y"] - pw / 2),
            (GATE_X + bt + 0.01, g["y"] + pw / 2),
            (GATE_X - 0.01, g["y"] + pw / 2),
        ])
        gate_openings.append(opening)

    if include_barrier:
        barrier_full = Polygon([
            (GATE_X, BARRIER_Y_BOTTOM),
            (GATE_X + bt, BARRIER_Y_BOTTOM),
            (GATE_X + bt, BARRIER_Y_TOP),
            (GATE_X, BARRIER_Y_TOP),
        ])
        barrier_solid = barrier_full
        for opening in gate_openings:
            barrier_solid = barrier_solid.difference(opening)
        obstacles_all.append(barrier_solid)
        obstacles_visible.append(barrier_solid)

    # walkable = 외곽 - 모든 장애물 (숨겨진 깔때기 포함)
    walkable = outer
    for obs in obstacles_all:
        if obs.is_valid and obs.area > 0:
            walkable = walkable.difference(obs)

    # 시각화에는 visible=True 만 반환
    return walkable, obstacles_visible, gate_openings


# =============================================================================
# 8. 시각화
# =============================================================================
def plot_station(gates, obstacles, gate_openings, save_path=None):
    """대합실 레이아웃 시각화"""
    fig, ax = plt.subplots(1, 1, figsize=(18, 10))

    gate_x_end = GATE_X + GATE_LENGTH

    # 구역 배경
    # 유료구역 (게이트 왼쪽 = 승강장쪽)
    ax.axvspan(0, GATE_X, color='#E3F2FD', alpha=0.3, label='유료구역')
    # 무료구역 (게이트 오른쪽 = 출구쪽)
    ax.axvspan(gate_x_end, CONCOURSE_LENGTH, color='#FFF3E0', alpha=0.3, label='무료구역')

    # 장애물 (벽, 구조물)
    for obs in obstacles:
        if obs.geom_type == 'Polygon':
            ox, oy = obs.exterior.xy
            ax.fill(ox, oy, color='#616161', edgecolor='#212121', linewidth=0.8)
        elif obs.geom_type == 'MultiPolygon':
            for geom in obs.geoms:
                ox, oy = geom.exterior.xy
                ax.fill(ox, oy, color='#616161', edgecolor='#212121', linewidth=0.8)

    # 게이트 통로
    for i, opening in enumerate(gate_openings):
        ox, oy = opening.exterior.xy
        ax.fill(ox, oy, color='#4CAF50', edgecolor='#1B5E20', linewidth=1, alpha=0.5)
        # 게이트 번호
        g = gates[i]
        ax.text(g["x"] + GATE_LENGTH / 2, g["y"], str(i + 1),
                ha='center', va='center', fontsize=8, fontweight='bold', color='#1B5E20')

    # 계단 (가로 통로 — 승강장 겹침)
    for stair in STAIRS:
        xs_s, xs_e = stair["x_start"], stair["x_end"]
        ys_s, ys_e = stair["y_start"], stair["y_end"]
        rect = mpatches.Rectangle(
            (xs_s, ys_s), xs_e - xs_s, ys_e - ys_s,
            facecolor='#FFCCBC', edgecolor='#D84315', linewidth=1.5, alpha=0.6)
        ax.add_patch(rect)
        ax.text((xs_s + xs_e) / 2, (ys_s + ys_e) / 2,
                f'계단 ({stair["id"]})\nx={xs_s:.0f}~{xs_e:.0f}',
                ha='center', va='center', fontsize=9,
                color='#D84315', fontweight='bold')
        # spawn 위치 마커 (승강장쪽 끝)
        ax.plot(xs_e, (ys_s + ys_e) / 2, 'o', color='#0288D1', markersize=8)
        # 연결부 (x_start, 대합실쪽)
        ax.plot([xs_s, xs_s], [ys_s, ys_e],
                color='#D84315', linewidth=3, solid_capstyle='round')

    # 에스컬레이터 통로 + 입구/sink
    for esc in ESCALATORS:
        xs_s, xs_e = esc["x_range"]
        ys_s, ys_e = esc["y_range"]
        rect = mpatches.Rectangle(
            (xs_s, ys_s), xs_e - xs_s, ys_e - ys_s,
            facecolor='#C8E6C9', edgecolor='#2E7D32', linewidth=1.5, alpha=0.8)
        ax.add_patch(rect)
        ax.text((xs_s + xs_e) / 2, (ys_s + ys_e) / 2,
                f'에스컬 {esc["id"]}\n({esc["direction"]})',
                ha='center', va='center', fontsize=8,
                color='#2E7D32', fontweight='bold')
        # 입구 (대합실쪽)
        ex, ey = esc["entry"]
        ax.plot(ex, ey, 'o', color='blue', markersize=9)
        # sink (외부 출구)
        ax.plot([esc["sink_x"], esc["sink_x"]], [ys_s, ys_e],
                color='blue', linewidth=3)

    # 외곽 벽 (에스컬 돌출 + 상단 왼쪽 들여쓰기 반영)
    outer_x = [
        0, ESCALATOR_X_START, ESCALATOR_X_START, ESCALATOR_X_END,
        ESCALATOR_X_END, CONCOURSE_LENGTH, CONCOURSE_LENGTH,
        ESCALATOR_X_END, ESCALATOR_X_END, ESCALATOR_X_START,
        ESCALATOR_X_START, NOTCH_X, NOTCH_X, 0, 0,
    ]
    outer_y = [
        0, 0, -ESCALATOR_CORRIDOR_WIDTH, -ESCALATOR_CORRIDOR_WIDTH,
        0, 0, CONCOURSE_WIDTH,
        CONCOURSE_WIDTH, CONCOURSE_WIDTH + ESCALATOR_CORRIDOR_WIDTH,
        CONCOURSE_WIDTH + ESCALATOR_CORRIDOR_WIDTH, CONCOURSE_WIDTH,
        CONCOURSE_WIDTH, NOTCH_Y, NOTCH_Y, 0,
    ]
    ax.plot(outer_x, outer_y, color='#E65100', linewidth=2)

    # 비통행 구조물 빗금 (visible=False 제외 — 숨겨진 내부 장치)
    for s in STRUCTURES:
        if not s.get("visible", True):
            continue
        coords = s["coords"]
        xs = [c[0] for c in coords] + [coords[0][0]]
        ys = [c[1] for c in coords] + [coords[0][1]]
        rect = mpatches.Rectangle(
            (min(xs), min(ys)), max(xs) - min(xs), max(ys) - min(ys),
            linewidth=1, edgecolor='#E65100', facecolor='#FFE0B2',
            hatch='///', alpha=0.5)
        ax.add_patch(rect)

    # 흐름 화살표
    ax.annotate('', xy=(GATE_X - 0.5, CONCOURSE_WIDTH / 2),
                xytext=(4.5, CONCOURSE_WIDTH / 2),
                arrowprops=dict(arrowstyle='->', color='#1565C0', lw=2.5, alpha=0.5))
    ax.annotate('', xy=(gate_x_end + 3, CONCOURSE_WIDTH / 2),
                xytext=(gate_x_end + 0.5, CONCOURSE_WIDTH / 2),
                arrowprops=dict(arrowstyle='->', color='#E65100', lw=2.5, alpha=0.5))

    # 구역 라벨
    ax.text(5, CONCOURSE_WIDTH / 2 + 1.5, '유료구역\n(승강장쪽)',
            ha='center', fontsize=10, color='#1565C0', fontweight='bold', alpha=0.7)
    ax.text(gate_x_end + 2, CONCOURSE_WIDTH / 2 + 1.5, '무료구역\n(출구쪽)',
            ha='center', fontsize=10, color='#E65100', fontweight='bold', alpha=0.7)

    ax.set_xlim(-1, CONCOURSE_LENGTH + 1)
    ax.set_ylim(-ESCALATOR_CORRIDOR_WIDTH - 1,
                CONCOURSE_WIDTH + ESCALATOR_CORRIDOR_WIDTH + 1)
    ax.set_aspect('equal')
    ax.set_xlabel('x (m)')
    ax.set_ylabel('y (m)')
    ax.set_title('성수역 2F 대합실 (서쪽 50m) — v4 공간 확장 (계단 가로통로 + 에스컬레이터)',
                 fontsize=13, fontweight='bold')
    ax.grid(True, alpha=0.2, linestyle=':')

    plt.tight_layout()
    if save_path:
        fig.savefig(save_path, dpi=90, bbox_inches='tight')
        print(f"Saved: {save_path}")
    return fig, ax


# =============================================================================
# 메인
# =============================================================================
if __name__ == "__main__":
    import pathlib

    gates = calculate_gate_positions()
    walkable, obstacles, gate_openings = build_geometry(gates)

    print(f"게이트 {len(gates)}개:")
    for g in gates:
        print(f"  G{g['id']+1}: x={g['x']:.1f}, y={g['y']:.2f}, 폭={g['passage_width']*100:.0f}cm")

    cluster_bottom = gates[0]["y"] - GATE_PASSAGE_WIDTH / 2 - GATE_HOUSING_WIDTH
    cluster_top = gates[-1]["y"] + GATE_PASSAGE_WIDTH / 2 + GATE_HOUSING_WIDTH
    print(f"\n게이트 클러스터: y={cluster_bottom:.2f} ~ {cluster_top:.2f} ({cluster_top - cluster_bottom:.2f}m)")
    print(f"Walkable area: {walkable.area:.1f} m²")

    output_dir = pathlib.Path(__file__).parent.parent / "output"
    output_dir.mkdir(exist_ok=True)
    plot_station(gates, obstacles, gate_openings,
                 save_path=str(output_dir / "seongsu_west_escalator_layout.png"))
    plt.show()
