"""
국토부 고시 제2025-241호 '도시철도정거장 및 환승·편의시설 설계지침' LOS 기준.
표 2.2 (대기공간), 표 2.3 (보행로), 표 2.4 (계단).

측정 단위: 첨두 1분 단위 밀도 (인/㎡).
시뮬 데이터에서는 zone별 시간 평균 밀도를 1분 moving average 로 근사.
"""
from __future__ import annotations

# 표 2.3 보행로 서비스수준 (인/㎡ 상한) — 국토부 고시 제2025-241호 정본 기준
WALKWAY_LOS = [
    ("A", 0.3,  "보행속도의 자유선택 가능"),
    ("B", 0.4,  "정상속도로 같은 방향 추월 가능"),
    ("C", 0.6,  "보행속도 추월의 자유도 제한"),
    ("D", 0.8,  "보행속도 제한"),
    ("E", 1.0,  "자신의 보통 보행속도 불가"),
    ("F", float("inf"), "떠밀리는 걸음, 정지 상태"),
]

# 표 2.2 대기공간 서비스수준 (인/㎡ 상한)
WAITING_LOS = [
    ("A", 0.8,  "자유흐름"),
    ("B", 1.0,  "무리 없이 통과"),
    ("C", 1.4,  "통과 시 불편"),
    ("D", 3.3,  "타인과의 접촉 없이 대기"),
    ("E", 5.0,  "타인과의 접촉 없이 대기 불가"),
    ("F", float("inf"), "밀착, 심리적 불쾌"),
]

# 표 2.4 계단 서비스수준 (인/㎡ 상한)
STAIR_LOS = [
    ("A", 0.5,  "자유선택"),
    ("B", 0.7,  "정상속도"),
    ("C", 1.0,  "타인추월 곤란"),
    ("D", 1.4,  "속도 제한"),
    ("E", 2.5,  "보행 최저치"),
    ("F", float("inf"), "교통마비"),
]


def grade(density: float, table: list) -> str:
    """밀도 값을 LOS 등급으로 매핑."""
    for los, upper, _desc in table:
        if density <= upper:
            return los
    return "F"


# Zone 유형 분류 — 사용자 지시:
# "대합실은 '대기공간'이 아니라 '보행공간'임을 먼저 확인하고 그에 맞는 기준 적용"
#
# 단, 개찰구 전방 큐(Zone 2) 는 실제로 정지 대기하므로 대기공간 기준 유지.
# 나머지 대합실/접근/통로는 모두 보행공간(표 2.3) 기준.
ZONE_CATEGORY = {
    "zone1":  ("walkway", "대합실 전체"),        # 보행공간
    "zone2":  ("waiting", "개찰구 앞 큐"),       # 대기공간
    "zone3a": ("walkway", "exit1 접근"),         # 보행공간 (이동 동선)
    "zone3b": ("walkway", "exit1 에스컬 대기"),  # 보행공간 (대합실 일부 - 사용자 지시)
    "zone3c": ("walkway", "exit1 corridor"),     # 보행공간
    "zone4a": ("walkway", "exit4 접근"),
    "zone4b": ("walkway", "exit4 에스컬 대기"),
    "zone4c": ("walkway", "exit4 corridor"),
}


def zone_grade(zone_id: str, density: float) -> str:
    cat, _ = ZONE_CATEGORY[zone_id]
    table = WALKWAY_LOS if cat == "walkway" else WAITING_LOS
    return grade(density, table)


def los_threshold(zone_id: str, los: str) -> float:
    """특정 LOS 등급 상한값 (해당 zone 유형 기준)."""
    cat, _ = ZONE_CATEGORY[zone_id]
    table = WALKWAY_LOS if cat == "walkway" else WAITING_LOS
    for g, upper, _ in table:
        if g == los:
            return upper
    raise ValueError(los)


if __name__ == "__main__":
    # sanity check
    print("보행로:")
    for g, u, d in WALKWAY_LOS:
        print(f"  {g}: ≤{u} ped/m²  ({d})")
    print("대기공간:")
    for g, u, d in WAITING_LOS:
        print(f"  {g}: ≤{u} ped/m²  ({d})")
    # 예: 밀도 1.5 → 보행로 E, 대기공간 D
    assert grade(1.5, WALKWAY_LOS) == "E"
    assert grade(1.5, WAITING_LOS) == "D"
    assert grade(2.1, WALKWAY_LOS) == "F"
    print("\n검증 통과.")
