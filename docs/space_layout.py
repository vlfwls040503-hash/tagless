# -*- coding: utf-8 -*-
"""
공간 레이아웃 단일 진실 원천 (Single Source of Truth).

좌표계:
  원점 (0, 0):  대합실 남서쪽 모서리 (= 게이트 클러스터 서쪽, 출구 1번 남쪽 벽)
  +x 방향:      동쪽 (계단 → 게이트 → 에스컬레이터 → 지상 출구)
  +y 방향:      북쪽 (출구 1번 → 게이트 클러스터 → 출구 4번)
  단위:         미터 (m)

주요 좌표 기준 (모두 sim runner 코드와 1:1 일치):
  - 대합실 50m × 25m (서쪽 절반)
  - 게이트 클러스터: x=12.0, y=9.95~15.05 (G1~G7)
  - 에스컬레이터 통로: x=25~35
    - exit1 (뚝섬, 남쪽 돌출): y=-1~0
    - exit4 (용답, 북쪽 돌출): y=25~26
  - 에스컬레이터 capture zone (실제 흡수 위치): (27~28, 3~4.5) / (27~28, 22.5~24)
  - 좌상단 들여쓰기: x=0~12, y=22~25 (계단실 잘림)

공간 수정 워크플로우:
  1. 본 파일의 SPACE dict 수정
  2. python docs/space_layout.py 실행 → validate + visualize
  3. 이상 없으면 시뮬 실행
"""

# =============================================================================
# 좌표계 메타
# =============================================================================
COORD_SYSTEM = {
    "origin": "대합실 남서쪽 모서리",
    "x_direction": "+x: 동쪽 (계단→게이트→에스컬→지상)",
    "y_direction": "+y: 북쪽 (출구1→게이트→출구4)",
    "unit": "m",
}

# =============================================================================
# outer_boundary 자동 derive 함수 (SPACE 정의 후 SPACE에 삽입)
# =============================================================================
def _compute_outer_boundary(space):
    """concourse + escalator corridor + notch 로부터 외곽 polygon 생성."""
    c = space["concourse"]
    L, W = c["length"], c["width"]
    nx, ny = c["notch"]["x"], c["notch"]["y"]
    # 남쪽 에스컬 (side=lower), 북쪽 에스컬 (side=upper)
    south = next(e["corridor"] for e in space["escalators"] if e["side"] == "lower")
    north = next(e["corridor"] for e in space["escalators"] if e["side"] == "upper")
    sx0, sx1 = south["x_range"]; sy0, sy1 = south["y_range"]  # y_range: (-1, 0)
    nx0, nx1 = north["x_range"]; ny0, ny1 = north["y_range"]  # y_range: (25, 26)
    return [
        (0.0, 0.0),
        (sx0, 0.0),              # 남쪽 에스컬 서쪽 진입
        (sx0, sy0),              # 남서 (예: y=-1)
        (sx1, sy0),              # 남동
        (sx1, 0.0),              # 복귀
        (L, 0.0),
        (L, W),
        (nx1, W),                # 북쪽 에스컬 동쪽 진입
        (nx1, ny1),              # 북동 (예: y=26)
        (nx0, ny1),              # 북서
        (nx0, W),                # 복귀
        (nx, W),                 # notch 북쪽
        (nx, ny),                # notch 모서리
        (0.0, ny),                # notch 서쪽
    ]


# =============================================================================
# SPACE — 공간 객체 단일 진실 원천
# =============================================================================
# 모든 좌표는 simulation/seongsu_west_escalator.py 와
# simulation/run_west_simulation_cfsm_escalator.py 에서 추출.
# 값을 수정하면 시뮬과 시각화 모두에 반영됨.
SPACE = {
    "concourse": {
        "length": 50.0,            # x 방향 (m)
        "width": 25.0,             # y 방향 (m)
        "notch": {"x": 12.0, "y": 22.0},  # 좌상단 계단실 들여쓰기
    },

    # 외곽 boundary는 함수로 derive (escalator corridor 변경 시 자동 반영)
    # _outer_boundary() 참조. SPACE["outer_boundary"]로 접근.

    "gate_params": {
        "x": 12.0,                      # 배리어 시작 x
        "length": 1.5,                  # 배리어 두께 (게이트 통과 길이)
        "passage_width": 0.55,          # 게이트 통로 폭 (y)
        "housing_width": 0.30,          # 게이트 사이 칸막이 폭
        "barrier_y_bottom": 3.0,
        "barrier_y_top": 22.0,
        "n_gates": 7,
        # 7개 게이트 y 좌표 (calculate_gate_positions() 결과)
        "y_positions": [9.95, 10.80, 11.65, 12.50, 13.35, 14.20, 15.05],
    },

    # 게이트 7개 (y는 gate_params에서 산출됨; 여기는 표시용)
    "gates": [
        {"id": 0, "name": "G1", "x": 12.0, "y": 9.95},
        {"id": 1, "name": "G2", "x": 12.0, "y": 10.80},
        {"id": 2, "name": "G3", "x": 12.0, "y": 11.65},
        {"id": 3, "name": "G4", "x": 12.0, "y": 12.50},
        {"id": 4, "name": "G5", "x": 12.0, "y": 13.35},
        {"id": 5, "name": "G6", "x": 12.0, "y": 14.20},
        {"id": 6, "name": "G7", "x": 12.0, "y": 15.05},
    ],

    # 계단 (대합실=승강장 2D 겹침, 가로 통로)
    # 2026-04-24: 실측 도면 반영, 폭 3m → 4.5m (게이트 클러스터 9.95~15.05 와 비충돌)
    "stairs": [
        {"id": "upper", "x_start": 1.0, "x_end": 11.0,
         "y_start": 15.0, "y_end": 19.5,
         "spawn_x_offset_range": (0.5, 2.5)},
        {"id": "lower", "x_start": 1.0, "x_end": 11.0,
         "y_start": 5.5,  "y_end": 10.0,
         "spawn_x_offset_range": (0.5, 2.5)},
    ],

    # 에스컬레이터 (출구 1번/4번)
    # 2026-04-22: 대합실 → 에스컬 사이 공간을 5m 넓히기 위해 x 방향 +5 이동
    # + corridor 폭 1m → 1.2m (2인용 에스컬레이터 기준)
    "escalators": [
        {
            "id": "exit1", "direction": "뚝섬", "side": "lower",
            # 물리 통로 (대합실 외곽 돌출, 2인용 1.2m 폭)
            "corridor": {"x_range": (28.0, 40.0), "y_range": (-1.2, 0.0)},
            "entry_point": (32.0, 0.0),         # 외곽상 입구 좌표
            # 실제 sim에서 agent가 흡수되는 위치 (concourse 내부)
            "capture_zone": {"x_range": (31.5, 33.0), "y_range": (-1.2, 0.0)},
            "waypoint": (32.0, -1.2),            # 접근 wp
            "service_time": 1.7,                # pair 흡수 주기 (s) → 1.17 ped/s (Cheung & Lam)
            "sink_x": 40.0,
        },
        {
            "id": "exit4", "direction": "용답", "side": "upper",
            "corridor": {"x_range": (28.0, 40.0), "y_range": (25.0, 26.2)},
            "entry_point": (32.0, 25.0),
            "capture_zone": {"x_range": (31.5, 33.0), "y_range": (25.0, 26.2)},
            "waypoint": (32.0, 26.2),
            "service_time": 1.7,                # pair 흡수 주기 (s) → 1.17 ped/s
            "sink_x": 40.0,
        },
    ],

    # 비통행 구조물 (빗금 영역)
    # 2026-04-22: 에스컬 이동(+5m)에 맞춰 구조물도 +5m 이동
    "structures": [
        {"id": "upper_right", "x_range": (35.0, 48.0), "y_range": (16.0, 24.0)},
        {"id": "lower_right", "x_range": (35.0, 48.0), "y_range": (3.0, 11.0)},
    ],

    # 측정 Zone (2026-04-22: 에스컬 +5m 이동에 맞춰 재조정)
    "zones": [
        {"id": "Z1", "name": "대합실_전체", "purpose": "전체",
         "x_range": (0.0, 50.0), "y_range": (0.0, 25.0)},
        {"id": "Z2", "name": "게이트_앞", "purpose": "게이트 대기",
         "x_range": (8.0, 12.0), "y_range": (9.0, 16.0)},
        # exit1 (남쪽) — gate y=10~12.5에서 capture(y=-1~0)까지
        {"id": "Z3A", "name": "exit1_접근", "purpose": "approach",
         "x_range": (14.0, 28.0), "y_range": (0.0, 12.5)},
        {"id": "Z3B", "name": "exit1_대기", "purpose": "wait (capture 포함)",
         "x_range": (28.0, 33.0), "y_range": (-1.2, 3.0)},
        {"id": "Z3C", "name": "exit1_corridor_inside", "purpose": "service (참고용)",
         "x_range": (31.0, 40.0), "y_range": (-1.2, 0.0)},
        # exit4 (북쪽) — gate y=13~15에서 capture(y=25~26)까지
        {"id": "Z4A", "name": "exit4_접근", "purpose": "approach",
         "x_range": (14.0, 28.0), "y_range": (12.5, 25.0)},
        {"id": "Z4B", "name": "exit4_대기", "purpose": "wait (capture 포함)",
         "x_range": (28.0, 33.0), "y_range": (22.0, 26.2)},
        {"id": "Z4C", "name": "exit4_corridor_inside", "purpose": "service (참고용)",
         "x_range": (31.0, 40.0), "y_range": (25.0, 26.2)},
    ],

    # 에이전트 spawn 영역 (각 계단 동쪽 끝 부근)
    # 2026-04-24: 계단 폭 4.5m 반영
    "spawn_areas": [
        {"id": "from_stair_upper", "stair_id": "upper",
         "x_range": (1.5, 3.5), "y_range": (15.0, 19.5)},
        {"id": "from_stair_lower", "stair_id": "lower",
         "x_range": (1.5, 3.5), "y_range": (5.5, 10.0)},
    ],

    # Sink (지상 도달)
    "sink": {
        "type": "x_threshold",
        "x_line": 40.0,
        "description": "에스컬 통로 동쪽 끝 (sink_x). agent 도달 시 sink_time 기록",
    },
}

# corridor 좌표에서 outer_boundary 자동 계산하여 SPACE에 삽입
SPACE["outer_boundary"] = _compute_outer_boundary(SPACE)


# =============================================================================
# 시각화 함수
# =============================================================================
def visualize_space(save_path=None):
    """SPACE dict의 모든 객체를 matplotlib로 그림."""
    import matplotlib
    if save_path is not None:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    plt.rcParams["font.family"] = "Malgun Gothic"
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots(figsize=(14, 8))

    # 외곽 boundary
    poly = mpatches.Polygon(SPACE["outer_boundary"], closed=True,
                            facecolor="#FAFAFA", edgecolor="black",
                            linewidth=3, zorder=1)
    ax.add_patch(poly)

    # 비통행 구조물
    for s in SPACE["structures"]:
        x0, x1 = s["x_range"]; y0, y1 = s["y_range"]
        ax.add_patch(mpatches.Rectangle((x0, y0), x1 - x0, y1 - y0,
                     facecolor="#FFE0B2", edgecolor="#E65100",
                     hatch="///", alpha=0.5, linewidth=1.5, zorder=2))

    # 계단 (회색 반투명)
    for st in SPACE["stairs"]:
        x0, x1 = st["x_start"], st["x_end"]
        y0, y1 = st["y_start"], st["y_end"]
        ax.add_patch(mpatches.Rectangle((x0, y0), x1 - x0, y1 - y0,
                     facecolor="#FFCCBC", edgecolor="#D84315",
                     alpha=0.4, linewidth=1.5, zorder=2))
        ax.text((x0 + x1) / 2, (y0 + y1) / 2,
                f"계단 {st['id']}\nx={x0:.0f}~{x1:.0f}",
                ha="center", va="center", fontsize=9,
                color="#D84315", fontweight="bold")

    # 에스컬레이터
    for esc in SPACE["escalators"]:
        cx0, cx1 = esc["corridor"]["x_range"]
        cy0, cy1 = esc["corridor"]["y_range"]
        ax.add_patch(mpatches.Rectangle((cx0, cy0), cx1 - cx0, cy1 - cy0,
                     facecolor="#C8E6C9", edgecolor="#2E7D32",
                     alpha=0.7, linewidth=1.5, zorder=2))
        ax.text((cx0 + cx1) / 2, (cy0 + cy1) / 2,
                f"에스컬 {esc['id']}\n({esc['direction']})",
                ha="center", va="center", fontsize=8,
                color="#2E7D32", fontweight="bold")
        # capture zone (점선 테두리)
        cz = esc["capture_zone"]
        zx0, zx1 = cz["x_range"]; zy0, zy1 = cz["y_range"]
        ax.add_patch(mpatches.Rectangle((zx0, zy0), zx1 - zx0, zy1 - zy0,
                     facecolor="none", edgecolor="#1565C0",
                     linewidth=2, linestyle="--", zorder=4))
        # waypoint
        wx, wy = esc["waypoint"]
        ax.plot(wx, wy, "x", color="#0D47A1", markersize=12,
                markeredgewidth=2.5, zorder=5)
        ax.text(wx + 0.3, wy, f"wp {esc['id']}", fontsize=7,
                color="#0D47A1")
        # entry → 화살표 (corridor 방향)
        ex, ey = esc["entry_point"]
        ax.annotate("", xy=(esc["sink_x"], (cy0 + cy1) / 2),
                    xytext=(ex, ey),
                    arrowprops=dict(arrowstyle="->", color="#2E7D32",
                                    lw=2, alpha=0.6))

    # Zones (purpose별 색)
    zone_color = {"전체": "#90A4AE", "게이트 대기": "#7986CB",
                  "approach": "#FFF59D", "wait (capture 포함)": "#FFAB91",
                  "service (참고용)": "#EF9A9A"}
    zone_alpha = {"전체": 0.05, "게이트 대기": 0.15,
                  "approach": 0.25, "wait (capture 포함)": 0.30,
                  "service (참고용)": 0.20}
    for z in SPACE["zones"]:
        x0, x1 = z["x_range"]; y0, y1 = z["y_range"]
        col = zone_color.get(z["purpose"], "#CCCCCC")
        al = zone_alpha.get(z["purpose"], 0.2)
        ax.add_patch(mpatches.Rectangle((x0, y0), x1 - x0, y1 - y0,
                     facecolor=col, edgecolor=col, alpha=al,
                     linewidth=1, zorder=3))
        ax.text(x0 + 0.2, y1 - 0.5, z["id"], fontsize=7,
                color="#37474F", fontweight="bold", zorder=6)

    # 게이트 (빨강 막대 + 라벨)
    for g in SPACE["gates"]:
        ax.plot([g["x"], g["x"] + SPACE["gate_params"]["length"]],
                [g["y"], g["y"]],
                color="#C62828", linewidth=4, solid_capstyle="round",
                zorder=5)
        ax.text(g["x"] + SPACE["gate_params"]["length"] / 2, g["y"] + 0.3,
                g["name"], fontsize=8, color="#C62828",
                ha="center", fontweight="bold", zorder=6)

    # Spawn 영역
    for sp in SPACE["spawn_areas"]:
        x0, x1 = sp["x_range"]; y0, y1 = sp["y_range"]
        ax.add_patch(mpatches.Rectangle((x0, y0), x1 - x0, y1 - y0,
                     facecolor="#9E9E9E", edgecolor="#424242",
                     alpha=0.3, linewidth=1, hatch="..", zorder=4))

    # Sink line
    ax.axvline(SPACE["sink"]["x_line"], linestyle=":",
               color="#1565C0", linewidth=2, alpha=0.7, zorder=2)
    ax.text(SPACE["sink"]["x_line"] + 0.2, 12.5, "sink (x=35)",
            fontsize=9, color="#1565C0", rotation=90, va="center")

    # 격자
    ax.grid(True, alpha=0.25, linestyle=":")
    ax.set_xticks(range(-2, 52, 5))
    ax.set_yticks(range(-2, 28, 5))
    ax.minorticks_on()
    ax.grid(which="minor", alpha=0.1, linestyle=":")

    # 범례 (수동)
    legend_items = [
        mpatches.Patch(facecolor="#FFCCBC", edgecolor="#D84315", label="계단"),
        mpatches.Patch(facecolor="#C8E6C9", edgecolor="#2E7D32", label="에스컬레이터 통로"),
        mpatches.Patch(facecolor="none", edgecolor="#1565C0", linestyle="--",
                       label="capture zone (점선)"),
        mpatches.Patch(facecolor="#FFF59D", alpha=0.5, label="Zone A (접근)"),
        mpatches.Patch(facecolor="#FFAB91", alpha=0.5, label="Zone B (대기)"),
        mpatches.Patch(facecolor="#EF9A9A", alpha=0.5, label="Zone C (서비스)"),
        mpatches.Patch(facecolor="#FFE0B2", edgecolor="#E65100", hatch="///",
                       label="비통행 구조물"),
        mpatches.Patch(facecolor="#9E9E9E", alpha=0.5, hatch="..", label="spawn"),
    ]
    ax.legend(handles=legend_items, loc="upper right", fontsize=8,
              ncol=2, framealpha=0.9)

    ax.set_xlim(-2, 52)
    ax.set_ylim(-3, 28)
    ax.set_aspect("equal")
    ax.set_xlabel("x (m)", fontsize=11)
    ax.set_ylabel("y (m)", fontsize=11)
    ax.set_title("성수역 서쪽 대합실 — 공간 레이아웃 (단일 진실 원천)",
                 fontsize=13, fontweight="bold")

    import matplotlib.pyplot as plt2
    plt2.tight_layout()
    if save_path is not None:
        fig.savefig(str(save_path), dpi=100, bbox_inches="tight")
        print(f"Saved: {save_path}")
    return fig, ax


# =============================================================================
# 검증 함수
# =============================================================================
def _rect_contains(outer_x, outer_y, inner):
    """outer 사각형 (xmin, xmax, ymin, ymax) 가 inner를 완전 포함하는지."""
    ox0, ox1 = outer_x; oy0, oy1 = outer_y
    ix0, ix1 = inner["x_range"]; iy0, iy1 = inner["y_range"]
    return ox0 <= ix0 and ix1 <= ox1 and oy0 <= iy0 and iy1 <= oy1


def _rect_overlap(a, b):
    """두 사각형의 overlap 면적."""
    ax0, ax1 = a["x_range"]; ay0, ay1 = a["y_range"]
    bx0, bx1 = b["x_range"]; by0, by1 = b["y_range"]
    dx = max(0, min(ax1, bx1) - max(ax0, bx0))
    dy = max(0, min(ay1, by1) - max(ay0, by0))
    return dx * dy


def validate_layout():
    """공간 일관성 검증. 경고 리스트 반환 (빈 리스트 = 통과)."""
    warnings = []

    # 1. 모든 사각형 좌표 유효성 (xmax > xmin, ymax > ymin)
    objs_to_check = []
    for z in SPACE["zones"]:
        objs_to_check.append((f"Zone {z['id']}", z))
    for s in SPACE["structures"]:
        objs_to_check.append((f"Structure {s['id']}", s))
    for esc in SPACE["escalators"]:
        objs_to_check.append((f"Escalator {esc['id']} corridor", esc["corridor"]))
        objs_to_check.append((f"Escalator {esc['id']} capture", esc["capture_zone"]))
    for sp in SPACE["spawn_areas"]:
        objs_to_check.append((f"Spawn {sp['id']}", sp))
    for st in SPACE["stairs"]:
        st_rect = {"x_range": (st["x_start"], st["x_end"]),
                   "y_range": (st["y_start"], st["y_end"])}
        objs_to_check.append((f"Stair {st['id']}", st_rect))

    for name, obj in objs_to_check:
        x0, x1 = obj["x_range"]; y0, y1 = obj["y_range"]
        if x1 <= x0:
            warnings.append(f"[invalid x] {name}: x_range={obj['x_range']}")
        if y1 <= y0:
            warnings.append(f"[invalid y] {name}: y_range={obj['y_range']}")

    # 2. capture_zone이 sim의 실제 흡수 위치 안에 있는지 (Zone B 안)
    z_by_id = {z["id"]: z for z in SPACE["zones"]}
    for esc in SPACE["escalators"]:
        zb_id = "Z3B" if esc["id"] == "exit1" else "Z4B"
        zb = z_by_id[zb_id]
        if not _rect_contains(zb["x_range"], zb["y_range"], esc["capture_zone"]):
            warnings.append(
                f"[capture not in {zb_id}] {esc['id']} capture "
                f"{esc['capture_zone']} not subset of Zone {zb_id} "
                f"(x={zb['x_range']}, y={zb['y_range']})")

    # 3. 게이트 y 위치가 배리어 범위 안에 있는지
    gp = SPACE["gate_params"]
    for g in SPACE["gates"]:
        if not (gp["barrier_y_bottom"] <= g["y"] <= gp["barrier_y_top"]):
            warnings.append(
                f"[gate out of barrier] {g['name']} y={g['y']} "
                f"not in [{gp['barrier_y_bottom']}, {gp['barrier_y_top']}]")

    # 4. 에이전트 waypoint(에스컬)이 capture zone 안에 있는지
    for esc in SPACE["escalators"]:
        wx, wy = esc["waypoint"]
        cz = esc["capture_zone"]
        x0, x1 = cz["x_range"]; y0, y1 = cz["y_range"]
        if not (x0 <= wx <= x1 and y0 <= wy <= y1):
            warnings.append(
                f"[wp out of capture] {esc['id']} wp ({wx},{wy}) "
                f"not in capture {cz}")

    # 5. Zone A vs Zone B 의도된 인접 (overlap 0 권장)
    for prefix in ["3", "4"]:
        za = z_by_id.get(f"Z{prefix}A")
        zb = z_by_id.get(f"Z{prefix}B")
        if za and zb:
            ov = _rect_overlap(za, zb)
            if ov > 0.001:
                warnings.append(
                    f"[unexpected overlap] Z{prefix}A x Z{prefix}B = {ov:.2f} sqm")

    # 6b. outer_boundary가 corridor x_range와 일치하는지
    for esc in SPACE["escalators"]:
        cx0, cx1 = esc["corridor"]["x_range"]
        # outer에 해당 corridor corner 좌표 존재하는지 체크
        outer_xs = {round(p[0], 3) for p in SPACE["outer_boundary"]}
        if round(cx0, 3) not in outer_xs:
            warnings.append(
                f"[outer mismatch] escalator {esc['id']} corridor x0={cx0} "
                f"not in outer_boundary x values")
        if round(cx1, 3) not in outer_xs:
            warnings.append(
                f"[outer mismatch] escalator {esc['id']} corridor x1={cx1} "
                f"not in outer_boundary x values")

    # 6. Zone 3 그룹 vs Zone 4 그룹은 절대 겹치지 않아야 함
    z3 = [z_by_id[k] for k in ("Z3A", "Z3B", "Z3C") if k in z_by_id]
    z4 = [z_by_id[k] for k in ("Z4A", "Z4B", "Z4C") if k in z_by_id]
    for a in z3:
        for b in z4:
            if _rect_overlap(a, b) > 0:
                warnings.append(
                    f"[unexpected overlap] {a['id']} x {b['id']} > 0")

    return warnings


def summary_print():
    """모든 객체 요약 콘솔 출력."""
    print("=" * 70)
    print("SPACE 요약")
    print("=" * 70)
    print(f"\n[좌표계] {COORD_SYSTEM['origin']}")
    print(f"  +x: {COORD_SYSTEM['x_direction']}")
    print(f"  +y: {COORD_SYSTEM['y_direction']}")
    c = SPACE["concourse"]
    print(f"\n[대합실] {c['length']}m × {c['width']}m, "
          f"notch (x={c['notch']['x']}, y={c['notch']['y']})")
    gp = SPACE["gate_params"]
    print(f"\n[게이트] {gp['n_gates']}개, x={gp['x']}, "
          f"통로폭={gp['passage_width']}m, 두께={gp['length']}m")
    for g in SPACE["gates"]:
        print(f"  {g['name']}: y={g['y']}")
    print(f"\n[계단] {len(SPACE['stairs'])}개")
    for st in SPACE["stairs"]:
        print(f"  {st['id']}: x={st['x_start']}~{st['x_end']}, "
              f"y={st['y_start']}~{st['y_end']}")
    print(f"\n[에스컬레이터] {len(SPACE['escalators'])}개")
    for esc in SPACE["escalators"]:
        cz = esc["capture_zone"]
        print(f"  {esc['id']} ({esc['direction']}): "
              f"corridor x={esc['corridor']['x_range']} y={esc['corridor']['y_range']}, "
              f"capture x={cz['x_range']} y={cz['y_range']}, "
              f"wp={esc['waypoint']}, service={esc['service_time']}s")
    print(f"\n[Zone] {len(SPACE['zones'])}개")
    for z in SPACE["zones"]:
        x0, x1 = z["x_range"]; y0, y1 = z["y_range"]
        area = (x1 - x0) * (y1 - y0)
        print(f"  {z['id']:5s} ({z['name']:20s}): "
              f"x={x0}~{x1}, y={y0}~{y1}  ({area:.1f}㎡)  [{z['purpose']}]")
    print(f"\n[Sink] x_line = {SPACE['sink']['x_line']}")
    print()


# =============================================================================
# 메인
# =============================================================================
if __name__ == "__main__":
    import pathlib
    summary_print()
    print("[검증]")
    warnings = validate_layout()
    if warnings:
        for w in warnings:
            print(f"  WARN: {w}")
    else:
        print("  통과 (경고 0건)")
    print()
    out = pathlib.Path(__file__).parent / "figures" / "space_current.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    visualize_space(save_path=out)
