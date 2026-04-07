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
- 전용 게이트 수에 따른 비용 곡선 → 혼입률별 **최적점** 도출

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
- [x] 동적 waypoint: 큐 깊이별 접근 목표 자동 조정
- [x] 역행 방지: waypoint 앞 에이전트 즉시 흡수
- [x] S0 기본 시나리오 (TAGLESS_RATIO=0.0)
- [x] S1 전면 태그리스 (TAGLESS_RATIO=1.0)
- [x] V&V Phase 1-2 완료 (NIST TN 1822)
- [ ] 출구 계단 혼잡도 측정 (병목 전이 분석용 모델 확장 필요)
- [ ] 과도기 시나리오 (20~80% 혼입률 × 전용 게이트 수)
- [ ] Calibration/Validation (우이신설선 실측 데이터 확보 후)

## 주요 파일
```
simulation/
  run_west_simulation_cfsm.py   <- 메인 시뮬레이션 (파라미터 여기서 수정)
  run_demo.py                   <- 데모 버전 (발표용, 파라미터 자유 수정)
  seongsu_west.py               <- 성수역 기하구조 (게이트, 계단, 출구 좌표)
  compare_scenarios.py          <- 시나리오 비교 분석 (병목, 첨두/비첨두)
  verify_cfsm_basic.py          <- V&V 검증 스크립트
  analyze_trajectories.py       <- 궤적 품질 자동 감지 (역행, 정체, 밀집)

output/
  simulation_cfsm.mp4           <- 최신 시뮬레이션 영상
  demo_baseline.mp4             <- 발표용 데모 영상 (p=0%, 열차 2편, 150명/편)

docs/
  vv_framework.md               <- V&V 프레임워크 문서
  졸작6주차_박필진.pdf           <- 6주차 발표자료
  필요 데이터 연구 계획서.pdf    <- 데이터 협조 요청 계획서
```

## 데모 파일 운용 방법
1. `run_demo.py`는 `run_west_simulation_cfsm.py`의 복사본으로, 파라미터를 자유롭게 수정하여 발표/테스트용 영상 생성
2. 코드 수정은 `run_west_simulation_cfsm.py`에서 진행
3. 최종 커밋 확정 시 `cp run_west_simulation_cfsm.py run_demo.py`로 데모 파일 동기화
4. 데모 파일의 파라미터(SIM_TIME, TRAIN_ALIGHTING, TAGLESS_RATIO 등)만 변경하여 사용

## 핵심 파라미터 (run_west_simulation_cfsm.py)
```python
TAGLESS_RATIO        = 1.0    # 태그리스 이용자 비율 (0.0=기본, 1.0=전면)
TAGLESS_SERVICE_TIME = 1.2    # 태그리스 통과시간 (s)
SERVICE_TIME_MEAN    = 2.0    # 태그 통과시간 평균 (s, lognormal)
SIM_TIME             = 720.0  # 시뮬레이션 시간 (s, 열차 4편)
TRAIN_INTERVAL       = 180.0  # 열차 간격 (s)
TRAIN_ALIGHTING      = 234    # 편당 하차인원 (성수역 08-09시 기준)
N_GATES              = 7      # 게이트 수
MAX_QUEUE_DEPTH_WP   = 25     # 동적 waypoint 최대 큐 깊이
```

## 시뮬레이션 실행
```bash
cd ~/tagless
python simulation/run_west_simulation_cfsm.py   # 메인 시뮬레이션
python simulation/run_demo.py                    # 데모 시뮬레이션
python simulation/verify_cfsm_basic.py           # V&V 검증
python simulation/compare_scenarios.py           # 시나리오 비교 분석
```

## 결과 요약 (현재)
| 지표 | 기본 (T=2.0s) | 태그리스 (T=1.2s) | 변화 |
|---|---|---|---|
| 평균 대기시간 | 19.1s | 5.5s | -71.4% |
| 추정 총 통행시간 | 41.4s | 32.9s | -20.6% |
| 총 통행비용 | 11.17 인시 | 8.86 인시 | -20.6% |

**병목 분석**: 기본 -> 게이트 병목(3.5 ped/s < 계단 4.6 ped/s), 태그리스 -> 계단 병목(5.8 > 4.6)

## 의존 패키지
```
jupedsim, numpy, matplotlib, shapely, pandas, imageio-ffmpeg
```

## Git 설정
- GitHub: https://github.com/vlfwls040503-hash/tagless
- user.name: 박필진
- user.email: vlfwls040503@gmail.com
