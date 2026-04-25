# 태그리스 게이트 운영 방안 연구 — 프로젝트 가이드

## 연구 개요
지하철 태그리스 개찰구 과도기(태그/태그리스 혼재) 상황에서 최적 게이트 운영 방안 연구.
**교통공학과 졸업설계** / 지도교수: 이동민 교수님

## 논문 스토리 라인
> "태그리스 전용 게이트를 무조건 늘리면 좋을까?"

1. **RQ1 (현상 발견)**: 태그리스 이용자 혼입률 증가에 따라, 시스템 병목은 게이트에서 후속 시설(출구 계단)로 어떻게 전이되는가?
2. **RQ2 (역설 검증)**: 전용 게이트 분리는 항상 시스템 효율을 높이는가? 전용 게이트를 과도하게 늘리면 병목 전이로 인해 시스템 총 통행비용이 오히려 증가하는가?
3. **RQ3 (처방 제시)**: 혼입률별 최적 전용 게이트 수가 다르다면, 시간대별 가변 운영이 고정 운영 대비 유효한가?

논리 흐름:
```
RQ1: 병목이 전이된다 (현상)
  -> "그래서 뭐가 문제인데?"
RQ2: 전용 늘리면 오히려 전체 비용 증가 (역설)
  -> "그럼 어떻게 해야 되는데?"
RQ3: 혼입률에 맞춰 가변 운영 (처방)
```

핵심 시사점: 겸용 게이트는 "비효율적 타협"이 아니라 **게이트 처리속도를 조절하여 후속 시설 병목을 완충하는 전략적 선택**

## 시나리오 설계
| 독립변수 | 수준 |
|---|---|
| 태그리스 이용 비율 (p) | 0 / 20 / 40 / 60 / 80 / 100% |
| 전용 게이트 수 (k) | 0 / 1 / 2 / 3대 |
| 시간대 | 첨두 / 비첨두 |

총 40개 시나리오 + S0(p=0%, 현행), S1(p=100%, 전면 도입) 앵커 시나리오

분석 지표:
- 게이트 앞 대기시간 + 출구 계단 밀도 = **시스템 총 통행비용 (person-sec)**
- 전용 게이트 수에 따른 비용 곡선 -> 혼입률별 **최적점** 도출

## 파라미터 근거
| 파라미터 | 값 | 근거 |
|---|---|---|
| CFSM time_gap | 0.80s (기본) | Rzezonka et al. (2022): 일반 1.3s ~ 조스틀링 0.1s, 첨두 통근자 중간값 |
| 동적 time_gap | 0.7~1.5s | 밀도별 차등, 현장조사 후 보정 예정 |
| 태그 서비스시간 | 2.0s (lognormal) | Gao et al. (2019) 실측 |
| 태그리스 통과시간 | 1.2s (고정) | 게이트 물리적 통과 (1.5m / 1.3m/s) |
| v0 (자유보행) | 1.34 m/s | Weidmann (1993), Fruin (1971) |

## 현재 구현 상태
- [x] 보행 모델: CFSM V2 (JuPedSim) + 소프트웨어 큐
- [x] 게이트 선택: Gao et al. (2019) LRP + Y_WEIGHT + **예측 큐 (유한 시야 8m)**
- [x] 물리 기반 도착 모델 (성수역 구조 반영)
- [x] 동적 waypoint: 큐 깊이별 접근 목표 자동 조정 (매 스텝, 양방향)
- [x] 역행 방지: waypoint 앞 에이전트 즉시 흡수 + 흡수 시 visual 점프 방지
- [x] 큐 진입 ease-in 보간 (현재 위치에서 슬롯까지 자연스럽게)
- [x] V&V Phase 1-2 완료 (NIST TN 1822)
- [x] **2026-04-13 안정 버전 스냅샷 저장 (DO NOT REVERT)**
- [ ] 출구 계단 병목 (RQ1 핵심, 모델 확장 필요)
- [ ] 과도기 시나리오 (20~80% 혼입률 x 전용 게이트 수)
- [ ] Calibration/Validation (우이신설선 실측 데이터 확보 후)
- [ ] 양방향 보행류 (하차 + 승차) — 이전 실험, 현재 단방향 버전으로 회귀

## 주요 파일

### simulation/ (시뮬레이션 코드)
```
run_west_simulation_cfsm.py
  [메인] 성수역 서쪽 단방향 시뮬레이션 (하차 전용)
  - CFSM V2 (JuPedSim) + 소프트웨어 큐
  - LRP 게이트 선택 (Gao 2019) + Y_WEIGHT 2.5 + 예측 큐 (FOV 8m)
  - 큐: FIFO + ease-in 진입 + 동적 wp (매 스텝, 양방향 갱신)
  - jockeying 금지, 자유보행 중 재선택 금지 (spawn 시 1회만)
  - 파라미터 여기서 수정 (TAGLESS_RATIO, SIM_TIME 등)

run_west_simulation_cfsm_20260413.py
  [스냅샷, DO NOT DELETE] 2026-04-13 안정 버전 — 복원용 원본
  - #1~#13 모든 수정 사항 반영

seongsu_west.py
  [기하구조] 성수역 2F 대합실 서쪽 50m x 25m
  - 게이트 7대, 계단 2개, 출구 2개 좌표 정의
  - build_geometry(): walkable area 생성 (Shapely)

seongsu_west_20260413.py
  [스냅샷, DO NOT DELETE] 2026-04-13 기하구조 스냅샷

verify_cfsm_basic.py
  [V&V] CFSM V2 기본 검증 (RiMEA 기반)
  - 자유보행 속도 / 기본다이어그램 / 병목 유량

calibrate_cfsm.py
  [보정] FZJ Seyfried (2005) 데이터로 time_gap 검토
  - 1D single-file → 2D 직접 적용 부적합 확인
  - 현재 T=0.80s (Rzezonka 2022 근거)

compare_scenarios.py
  [분석] 시나리오 비교 스크립트 (S0 vs S1)
  - 계단 유량, 첨두/비첨두, 통행비용 비교

analyze_trajectories.py
  [분석] 궤적 자동 품질 감지
  - 역행, 정체, 밀집, y가로지름 자동 검출
  - 파라미터 튜닝 시 자동 실행

run_west_simulation_cfsm_escalator.py
  [실험] 에스컬레이터 하류 병목 추가 버전 (2026-04-17)
  - run_west_simulation_cfsm.py 기반 복사본, 원본 비손상
  - EXITS 폭 3m → 1m (실제 에스컬레이터 폭)
  - exit_stage 제거 → escalator_wp (waypoint) + dummy_exit
  - 에스컬레이터 소프트웨어 큐: CFSM off-on 재활용, 서비스 시간 0.85s (1.17 ped/s 목표)
  - 시야 기반 대기 로직: busy 측 wp 반경 1.2m 이내 + 전방 60° 콘 + wp 거리 FIFO
  - front-most 에이전트 면제 (멈춤 탈출), 반응 주기 매 2스텝

seongsu_west_escalator.py
  [실험] 에스컬레이터 버전 기하 (EXITS 폭 1m, STRUCTURES는 원본과 동일)
  - plot_station/build_geometry 에 visible 플래그 지원 (숨겨진 장애물용)
```

### output/ (시뮬레이션 결과)
```
simulation_cfsm.mp4             <- 최신 시뮬레이션 영상
simulation_cfsm_view.mp4        <- Windows 재생 호환 (H.264 재인코딩)
trajectories.csv                <- 최신 궤적 데이터
snapshots_cfsm.png              <- 시점별 스냅샷
queue_history_cfsm.png          <- 게이트별 큐 길이 시계열
service_time_cfsm.png           <- 서비스 시간 분포
scenario_comparison.png         <- S0 vs S1 비교 그래프
calibration_cfsm_fzj.png        <- FZJ 보정 결과 그래프
3장_방법론_v3.docx              <- 논문 방법론 초고
verification/                   <- V&V 검증 결과
```

### data/ (원시 데이터)
```
서울교통공사_역별 시간대별 승하차인원(24.1~24.12).csv
서울교통공사_1_8호선 개집표기 시설물 현황_20250311.csv
fzj/seyfried2005_single_file.txt   <- FZJ 기본다이어그램 실측
```

### docs/ (연구 설계·선행연구 — 2026-04-17 재정립)
```
연구설계_v2.md             <- RQ 재정립, 공간 범위, 통행비용 함수 3후보
선행연구_축A.md            <- 다구간 역사 보행 시뮬
선행연구_축B.md            <- 병목 전이 / 다운스트림 혼잡
선행연구_축C.md            <- 통행비용 함수 / LOS 가중
선행연구_축D.md            <- 기존 7절 선행연구 검증
선행연구_암묵적병목.md      <- CFSM/AVM 계보, 암묵적 혼잡 14편
시뮬_확장성_검토.md        <- 현 코드 분석 + JuPedSim/PedPy/transp-or 재평가
vv_framework.md            <- V&V (유지)
```

### experiments/escalator_convergence_test/ (에스컬레이터 병목 실험)
```
scenario_setup.py          <- 10m×10m + 3m 통로 최소 재현
metrics.py                 <- 진동/역행/밀도 4개 지표
run_experiments.py         <- 13 전략 × 3 rate × 3 seed 일괄 러너
results/summary.json       <- 전략별 지표 수치
baseline_metrics.md, strategy_comparison.md, recommendation.md
```

## 절대 되돌리면 안 되는 수정 (DO NOT REVERT)

> 최종 안정 버전 — **2026-04-13**
> 스냅샷: `simulation/run_west_simulation_cfsm_20260413.py` / `simulation/seongsu_west_20260413.py`
> 이 수정 사항은 **절대 변경/제거 금지**. 리팩토링이나 기능 추가 시에도 반드시 유지할 것.
> 유실 시 **보행 행태가 비현실적**으로 됨 (큐 이동 혼란, 횡단 가로지름, 게이트 쏠림 등)

### 1. QUEUE_RESELECT_ENABLED = False (0040b53, 2026-04-03)
**위치**: `simulation/run_west_simulation_cfsm.py` 큐 파라미터
```python
QUEUE_RESELECT_ENABLED = False  # 대기열 진입 후 게이트 확정
```
**이유**: 큐 내 jockeying(게이트 간 이동)이 시각적/행태적으로 부자연스러움. 실제 사람은 한번 줄 서면 잘 안 바꿈.
**증상 (되돌릴 경우)**: 큐→큐 순간이동 또는 큐→자유보행→다른 큐로 이동. 에이전트가 대기열 사이를 가로지르는 현상.

### 2. Y_WEIGHT = 2.5 (0040b53, 2026-04-03)
**위치**: `choose_gate_lrp()` 함수 내 l1_actual 계산
```python
Y_WEIGHT = 2.5
l1_actual = np.array([
    np.hypot(agent_pos[0] - g["x"], (agent_pos[1] - g["y"]) * Y_WEIGHT)
    for g in gates
])
```
**이유**: 횡단(y방향 이동)은 직진(x방향)보다 심리적 비용이 큼. 이 가중치 없으면 에이전트가 가까운 게이트 두고 대각선으로 옆 게이트 선택.
**증상 (되돌릴 경우)**: 에이전트들이 y를 크게 가로질러 이동하며 큐 옆을 통과.

### 3. 역행 방지 (0248e6d, 2026-04-10)
**위치**: 동적 waypoint 갱신 로직
- 동적 wp depth는 **줄어들기만 허용** (늘어나면 후퇴하므로)
- tail 안쪽 에이전트는 즉시 흡수

**이유**: 큐가 급증할 때 에이전트가 뒤로 밀려나는 현상 방지.

### 4. 큐 시프트 ease-in-out (0248e6d, 2026-04-10)
**위치**: 큐 head pop 및 진입 시 `queue_shift_from / queue_target_x / queue_shift_start` 처리
**이유**: 큐 전진 시 텔레포트 대신 0.5초 보간으로 자연스럽게 이동.

### 5. 스텝당 큐 흡수 1명 제한 (50e50f5, 2026-04-12)
**위치**: 큐 흡수 루프 내 `absorbed_this_step` 카운터
**이유**: 첨두 시 큐가 폭발적으로 성장하는 것 방지.

### 6. 큐 진입 시간 간격 제한 (29fa8d0, 2026-04-06)
**위치**: 큐 흡수 루프
```python
QUEUE_ENTRY_MIN_GAP = 0.7  # 게이트당 0.7초에 1명만 흡수
if len(sw_queue[gi]) > 0 and current_time - last_queue_entry_time[gi] < QUEUE_ENTRY_MIN_GAP:
    break
```
**이유**: 큐가 한 스텝에 여러 명 동시 흡수되어 폭발적으로 커지는 현상 방지.
**증상 (되돌릴 경우)**: 첨두 시 큐가 1초에 +5~10명씩 튐.

### 7. tail snapshot 연쇄 진입 방지 (29fa8d0, 2026-04-06)
**위치**: 큐 흡수 루프 시작 시
```python
queue_tail_snap = []  # 스텝 시작 시 스냅샷 — 루프 중 실시간 tail 변동 무시
for gi in range(N_GATES):
    ...
```
**이유**: 흡수 중 큐가 길어지면 tail이 이동 → 다음 후보가 tail 안쪽 판정됨 → 연쇄 흡수.
**증상 (되돌릴 경우)**: 한 스텝에 여러 명이 이어서 흡수되며 큐 길이 점프.

### 8. 자유보행 중 1차/2차 재선택 제거 (2026-04-13)
**위치**: 메인 루프의 `choose_gate_lrp(stage="1st"/stage="2nd")` 호출 **모두 제거**
**이유**: 자유보행 중 게이트 재배정 → 에이전트가 경로 중간에 방향 전환 → 다른 게이트 큐 가로지름.
- spawn 시 1회 LRP 선택만 사용 (강제)
- 큐 진입 후 jockeying도 금지 (위 #1)
**증상 (되돌릴 경우)**: 에이전트가 y를 크게 가로지르며 다른 게이트의 큐를 통과.

### 9. 예측 큐 기반 LRP (2026-04-13)
**위치**: spawn 시 `gate_queue` 계산
```python
gate_queue = [len(q) for q in sw_queue]
# 다른 에이전트가 어느 게이트로 가는지 관찰 → 예측 큐에 반영
for _ad in agent_data.values():
    if _ad.get("serviced") or _ad.get("queued"):
        continue
    _gi = _ad.get("gate_idx", -1)
    if _gi >= 0:
        gate_queue[_gi] += 1
```
**이유**: 현실에서 사람은 "지금 이 순간의 큐" 만 보는 게 아니라 "다른 사람이 어디로 가는지" 도 관찰함.
기존: 같은 시점 spawn한 에이전트 여럿이 동일한 "빈 게이트"를 선택 → 한 게이트에 쏠림.
수정: 앞선 에이전트가 향하는 게이트는 "곧 큐가 생길 게이트" 로 판단.
**효과**: G7 쏠림 26명 → 모든 게이트 5~7명으로 균등화 (편차 22 → 2)
**증상 (되돌릴 경우)**: 특정 게이트에 큐 쏠림 (예: G7 only).

### 10. 흡수 시 역행 점프 방지 (2026-04-13)
**위치**: 큐 흡수 로직 (2곳 모두)
```python
ad["queue_visual_x"] = px_c  # 현재 위치에서 시작
ad["queue_target_x"] = _qx   # 슬롯까지 ease 보간
ad["queue_shift_start"] = current_time
```
**이유**: 흡수 시 visual_x를 곧바로 슬롯 위치(QH - slot*0.5)로 두면 현재 위치보다 뒤라서 텔레포트.
**증상 (되돌릴 경우)**: 흡수 시 평균 -1.5m 뒤로 점프 (58건 발생).

### 11. 동적 waypoint 양방향 갱신 (2026-04-13)
**위치**: 동적 waypoint 업데이트 루프
```python
cur_depth = ad.get("target_depth", new_depth)
if new_depth != cur_depth:  # < 가 아니라 !=
    ad["target_depth"] = new_depth
    ...switch...
```
**이유**: 기존은 `new_depth < cur_depth` (줄어들 때만). 큐 늘어나면 wp가 옛 위치 그대로 → 에이전트가 큐 안쪽으로 계속 전진.
**증상 (되돌릴 경우)**: 에이전트가 큐 있는데 개찰구 입구로 직행.

### 12. SIM_TIME 영상 길이와 동일 (2026-04-13)
**값**: `SIM_TIME = 120.0` (열차 1편 처리 분량)
**이유**: MP4는 120초까지만 렌더링 → 그 이후 시뮬은 불필요.

### 13. 유한 시야 기반 예측 큐 (2026-04-13)
**위치**: spawn 시 `gate_queue` 계산
```python
VISION_RANGE = 8.0  # 앞쪽 8m만 관찰 가능 (Moussaïd 2011 기반 유한 시야)
_my_x = stair["x"]
for _other in sim.agents():
    _oad = agent_data.get(_other.id, {})
    if _oad.get("serviced") or _oad.get("queued"):
        continue
    _ogi = _oad.get("gate_idx", -1)
    if _ogi < 0:
        continue
    _ox = _other.position[0]
    if _my_x < _ox < _my_x + VISION_RANGE:
        gate_queue[_ogi] += 1
```
**이유**: #9 예측 큐는 무한 시야(전체 에이전트 관찰)였음. 현실은 시야 제한.
- 내 **앞쪽(+x)** 8m 이내만 관찰
- 뒤에 있거나 멀리 있는 에이전트는 모름
**근거**: Moussaïd et al. (2011) "How simple rules determine pedestrian behavior"
**효과**: #9와 유사한 분산 효과 유지하면서 현실성 ↑ (게이트별 편차 2로 동일)
**증상 (되돌릴 경우)**: 비현실적으로 완벽한 예측 → 논문 공격 포인트.

### 14. 에스컬레이터 하류 병목 최종본 (2026-04-20, simulation_escalator_v12_win.mp4)
**위치**: `simulation/run_west_simulation_cfsm_escalator.py`
**최종 영상**: `output/simulation_escalator_v12_win.mp4`

**절대 변경 금지 항목:**

**(a) 에스컬레이터 위치 (x+2 이동)**
- `docs/space_layout.py`: capture_zone x_range `(26.5, 28.0)`, waypoint `(27.0, ...)`
- `create_simulation()`: `escalator_wp_upper=(28.0, 25.5)`, `escalator_wp_lower=(28.0, -0.5)`
- approach_wp: `(25.5, 23.5)` / `(25.5, 1.5)`
- ESC_QUEUE_SLOTS: upper x=25.2/25.7/26.2, lower x=25.2/25.7/26.2
- ESC_APPROACH_UPPER/LOWER: `(25.5, 23.5)` / `(25.5, 1.5)`
**이유**: 이 위치에서 stop-and-go + 시야 기반 대기가 가장 자연스럽게 작동.

**(b) Funnel 벽 원래 위치**
```python
_Poly([(30.0, 25.0), (35.0, 25.0), (35.0, 26.0), (30.0, 26.0)]),  # 동측 캡
_Poly([(30.0, -1.0), (35.0, -1.0), (35.0,  0.0), (30.0,  0.0)]),
_Poly([(19.8, 21.8), (20.2, 22.2), (22.9, 24.9), (22.5, 24.5)]),  # 대각 upper
_Poly([(19.8,  3.2), (20.2,  2.8), (22.7,  0.3), (22.3,  0.7)]),  # 대각 lower
```
**이유**: 대각 벽이 x+2 이동하면 corridor 입구를 막아 병목 발생. 원래 위치(x=19.8~22.9)가 올바름.
**증상 (되돌릴 경우)**: 에이전트들이 corridor로 진입 못하고 병목 형성.

**(c) 시야 기반 대기 로직 (VISION_R=2.5, VISION_DOT_TH=0.3)**
**위치**: 메인 루프 내 `if step % 2 == 0:` 블록
**이유**: 이 로직 없으면 에이전트들이 에스컬레이터 앞에서 stop-and-go 없이 밀고 들어감.
파라미터(VISION_R, VISION_DOT_TH 등)만 존재하고 적용 코드 없으면 완전 동일 — 반드시 코드도 유지.
**증상 (제거 시)**: stop-and-go 전혀 없음, 시야 적용 안 됨.

**(d) Slot-based stop-and-go (`model.v0` 사용)**
**위치**: `# ── 에스컬 큐 에이전트 stop-and-go` 블록
`sim.agent(_aid).model.v0 = _new_v0` — **`desired_speed`로 바꾸면 안 됨**
**이유**: `model.v0`는 deprecated setter지만 경고 모드에서 정상 작동. `desired_speed`와 동일하나 v7 검증된 버전 유지.

**(e) capture zone 강제 흡수 로직**
**위치**: `# 강제 진입` 블록 (큐 비어있을 때 capture zone 내 에이전트 직접 흡수)
**이유**: 큐 없는 상황에서 에스컬레이터 앞 에이전트가 대기만 하다 막히는 현상 방지.
**증상 (제거 시)**: 큐 비어도 에이전트가 에스컬레이터 앞에서 멈춤.

---

## 핵심 파라미터 (run_west_simulation_cfsm.py)
```python
# 시뮬레이션
TAGLESS_RATIO        = 1.0    # 태그리스 이용자 비율 (시나리오별 변경)
TAGLESS_SERVICE_TIME = 1.2    # 태그리스 통과시간 (s)
SERVICE_TIME_MEAN    = 2.0    # 태그 통과시간 평균 (s, lognormal)
SIM_TIME             = 120.0  # 시뮬레이션 시간 (s, 영상 길이와 동일)
TRAIN_INTERVAL       = 180.0  # 열차 간격 (s)
TRAIN_ALIGHTING      = 234    # 편당 하차인원 (성수역 08-09시 실측)
N_GATES              = 7      # 게이트 수

# CFSM V2 파라미터 (Rzezonka 2022 근거)
CFSM_TIME_GAP = 0.80          # 기본 time_gap (동적 조정)
CFSM_RADIUS = 0.15            # 보행자 반경

# 큐 제어
QUEUE_ENTRY_MIN_GAP  = 0.7    # 큐 진입 최소 간격 (s)
QUEUE_SHIFT_DURATION = 0.5    # 큐 시프트/진입 ease 시간 (s)
MAX_QUEUE_DEPTH_WP   = 25     # 동적 waypoint 최대 큐 깊이

# LRP 게이트 선택 (Gao 2019 + 확장)
QUEUE_RESELECT_ENABLED = False  # 큐 내 jockeying 금지
# choose_gate_lrp() 내부: Y_WEIGHT = 2.5
# spawn 시 예측 큐: VISION_RANGE = 8.0 (앞쪽 시야)
```

## 시뮬레이션 실행
```bash
cd ~/tagless
python simulation/run_west_simulation_cfsm.py             # 메인 (단방향)
python simulation/run_west_simulation_cfsm_escalator.py   # 하류 병목 실험용 (2026-04-17)
python simulation/verify_cfsm_basic.py                    # V&V 검증
python simulation/analyze_trajectories.py                 # 궤적 자동 분석
python simulation/compare_scenarios.py                    # 시나리오 비교
python simulation/calibrate_cfsm.py                       # FZJ 보정
```

## 에스컬레이터 병목 구현 메모 (2026-04-20 최종 확정)

- **최종 영상**: `output/simulation_escalator_v12_win.mp4`
- **채택된 접근**: 시야 기반 대기 (전방 72° 콘, VISION_R=2.5) + 소프트웨어 슬롯 큐 + front-most 면제 + capture zone 강제 흡수.
- **에스컬레이터 위치**: x+2 이동 (capture_zone x=26.5~28.0).
- **Funnel**: 대각 벽 원래 위치(x=19.8~22.9) 유지 — x+2 이동 시 corridor 병목 발생 확인.
- **시야 로직 주의**: 파라미터(VISION_R 등) 정의만으로는 적용 안 됨 — 루프 내 `step % 2 == 0` 블록 필수.
- **AVM 교체 보류**: 전체 시뮬 V&V 재수행 부담. 후속 과제.
- **현 실효 처리율**: upper 0.68 / lower 0.65 ped/s (목표 1.17 ped/s)
- **참고 문헌**: `docs/선행연구_암묵적병목.md` (Xu 2021 AVM, Rzezonka 2022 등 14편)

## Git 설정
- GitHub: https://github.com/vlfwls040503-hash/tagless
- user.name: 박필진
- user.email: vlfwls040503@gmail.com

## 의존 패키지
```
jupedsim (Python 3.10+), numpy, matplotlib, shapely, pandas, imageio-ffmpeg, scipy
```
