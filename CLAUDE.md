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
- [x] 게이트 선택: Gao et al. (2019) LRP 3단계
- [x] 물리 기반 도착 모델 (성수역 구조 반영)
- [x] 동적 waypoint: 큐 깊이별 접근 목표 자동 조정 (매 스텝)
- [x] 역행 방지: waypoint 앞 에이전트 즉시 흡수
- [x] **양방향 보행류 (하차 + 승차)**: 게이트 단방향 분리 운영
- [x] 큐 진입 ease-in 보간 (자연스러운 줄 형성)
- [x] V&V Phase 1-2 완료 (NIST TN 1822)
- [x] 개별 궤적 V&V 리뷰 스크립트 (review_bidir_traj.py)
- [ ] 출구 계단 병목 (RQ1 핵심, 모델 확장 필요)
- [ ] 과도기 시나리오 (20~80% 혼입률 x 전용 게이트 수)
- [ ] Calibration/Validation (우이신설선 실측 데이터 확보 후)

## 주요 파일

### simulation/ (시뮬레이션 코드)
```
run_west_simulation_cfsm.py
  [메인] 양방향 시뮬레이션 — 하차+승차 통합
  - 게이트별 방향 속성 (GATE_DIRECTIONS): G1/G2 입구, G3-G7 출구
  - 하차류: 계단 spawn -> 동적 wp -> 큐 흡수 -> 서비스 -> 출구 퇴장
  - 승차류: 출구(상/하) spawn -> 입구 게이트 큐 -> 서비스 -> 계단 퇴장
  - 큐: FIFO + ease-in 진입 + ease shift + jockeying + 동적 wp (매 스텝)
  - 도착: 하차(열차 펄스) + 승차(NHPP 균일 16명/분)
  - LRP 게이트 선택: 방향별 allowed_gates 분리
  - 출력: MP4, 궤적 CSV(7컬럼: kind 추가), 큐 히스토리, 서비스시간
  - 파라미터 여기서 수정 (TAGLESS_RATIO, GATE_DIRECTIONS 등)

run_demo.py
  [발표용] 단방향 데모 — run_west_simulation_cfsm_v1의 복사본
  - SIM_TIME, TRAIN_ALIGHTING 등 자유 수정
  - 코드 구조 수정 금지 (메인에서 수정 -> 여기로 동기화)

run_bidirectional.py
  [원본] 양방향 시뮬레이션 원본 (run_west_simulation_cfsm.py와 동일)
  - 양방향 개발 이력 보존용

run_west_simulation_cfsm_v1_unidirectional.py
  [백업] 양방향 적용 전 단방향 버전
  - 이전 S0/S1 결과와 호환 필요 시 사용

seongsu_west.py
  [기하구조] 성수역 2F 대합실 서쪽 50m x 25m
  - 게이트 7대, 계단 2개, 출구 2개 좌표 정의
  - build_geometry(): walkable area 생성 (Shapely)
  - 시뮬레이션과 시각화 모두 이 파일의 좌표 참조

verify_cfsm_basic.py
  [V&V] CFSM V2 기본 검증 (RiMEA 기반)
  - Test 1: 자유보행 속도
  - Test 2: 기본 다이어그램 (밀도-속도, Weidmann 1993)
  - Test 3: 병목 유량

calibrate_cfsm.py
  [보정] FZJ Seyfried (2005) 데이터로 time_gap 보정
  - 1D single-file -> 2D 직접 적용은 부적합 확인
  - 결과: T_opt=1.19s (1D), 현재 T=0.80s는 Rzezonka (2022) 근거
  - output/calibration_cfsm_fzj.png 생성

compare_scenarios.py
  [분석] 시나리오 비교 — 기본(0%) vs 태그리스(100%)
  - 계단 유량, 첨두/비첨두, 통행비용 비교
  - output/scenario_comparison.png 생성
  - 현재 단방향 버전 기준 (양방향 업데이트 필요)

analyze_trajectories.py
  [분석] 궤적 자동 품질 감지
  - 역행(backtracking), 정체(stalling), 밀집(clumping)
  - 파라미터 튜닝 시 자동 실행

review_bidir_traj.py
  [V&V] 양방향 궤적 개별 리뷰
  - 에이전트별 상태 전환 추적 (moving -> queue -> passed)
  - 역행, 큐 합류 점프, y변동 자동 검출
  - 하차/승차 각 5명 샘플 출력
```

### output/ (시뮬레이션 결과)
```
simulation_bidir.mp4           <- 양방향 시뮬레이션 최신 영상
simulation_bidir_view.mp4      <- Windows 재생 호환 (H.264 재인코딩)
trajectories_bidir.csv         <- 양방향 궤적 (7컬럼: time,agent_id,x,y,gate_idx,state,kind)
snapshots_bidir.png            <- 시점별 스냅샷
queue_history_bidir.png        <- 게이트별 큐 길이 시계열
service_time_bidir.png         <- 서비스 시간 분포

demo_baseline.mp4              <- 발표용 데모 (단방향, p=0%)
scenario_comparison.png        <- S0 vs S1 비교 그래프 (단방향 기준)
calibration_cfsm_fzj.png       <- FZJ 보정 결과 그래프

baseline/                      <- S0 결과 보관 (단방향 기준)
tagless/                       <- S1 결과 보관 (단방향 기준)
```

### data/ (원시 데이터)
```
서울교통공사_역별 시간대별 승하차인원(24.1~24.12).csv
서울교통공사_1_8호선 개집표기 시설물 현황_20250311.csv
fzj/seyfried2005_single_file.txt   <- FZJ 기본다이어그램 실측
```

## 절대 되돌리면 안 되는 수정 (DO NOT REVERT)

> 과거 이미 검증된 수정 사항. 리팩토링이나 기능 추가 시에도 반드시 유지할 것.
> 유실 시 **보행 행태가 비현실적**으로 됨 (큐 이동 혼란, 횡단 가로지름 등)

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

---

## 핵심 파라미터 (run_west_simulation_cfsm.py)
```python
# 양방향 설정
GATE_DIRECTIONS = ['in','in','out','out','out','out','out']  # G1/G2 입구, G3-G7 출구
INBOUND_RATE    = 16.2 / 60.0   # 승차 도착률 (ped/s)

# 시뮬레이션
TAGLESS_RATIO        = 0.0    # 태그리스 이용자 비율 (시나리오별 변경)
TAGLESS_SERVICE_TIME = 1.2    # 태그리스 통과시간 (s)
SERVICE_TIME_MEAN    = 2.0    # 태그 통과시간 평균 (s, lognormal)
SIM_TIME             = 360.0  # 시뮬레이션 시간 (s)
TRAIN_INTERVAL       = 180.0  # 열차 간격 (s)
TRAIN_ALIGHTING      = 150    # 편당 하차인원 (데모)
N_GATES              = 7      # 게이트 수

# 큐 제어
QUEUE_ENTRY_MIN_GAP  = 0.7    # 큐 진입 최소 간격 (s)
QUEUE_SHIFT_DURATION = 0.5    # 큐 시프트/진입 ease 시간 (s)
MAX_QUEUE_DEPTH_WP   = 25     # 동적 waypoint 최대 큐 깊이
```

## 시뮬레이션 실행
```bash
cd ~/tagless
python simulation/run_west_simulation_cfsm.py   # 메인 (양방향)
python simulation/run_demo.py                    # 데모 (단방향, 발표용)
python simulation/verify_cfsm_basic.py           # V&V 검증
python simulation/review_bidir_traj.py           # 궤적 개별 리뷰
python simulation/compare_scenarios.py           # 시나리오 비교 (단방향)
python simulation/calibrate_cfsm.py              # FZJ 보정
```

## Git 설정
- GitHub: https://github.com/vlfwls040503-hash/tagless
- user.name: 박필진
- user.email: vlfwls040503@gmail.com

## 의존 패키지
```
jupedsim (Python 3.10+), numpy, matplotlib, shapely, pandas, imageio-ffmpeg, scipy
```
