# 태그리스 게이트 운영 방안 연구 — 프로젝트 가이드

## 연구 개요
지하철 태그리스 개찰구 과도기(태그/태그리스 혼재) 상황에서 최적 게이트 운영 방안 연구.
**교통공학과 졸업설계** / 지도교수: 이동민 교수님

## 핵심 연구 질문
- **RQ1 (현상)**: 태그리스 이용자 혼입률 증가에 따라, 시스템 병목은 게이트에서 후속 시설로 어떻게 전이되는가?
- **RQ2 (역설)**: 전용 게이트 분리는 항상 시스템 효율을 높이는가? 아니면 과도한 분리가 오히려 전체 통행비용을 증가시키는가?
- **RQ3 (처방)**: 시간대별 태그리스 수요를 고려한 겸용/전용 가변 운영이 고정 운영 대비 유효한가?

## 시나리오 설계
| 독립변수 | 수준 |
|---|---|
| 태그리스 이용 비율 | 20 / 40 / 60 / 80% |
| 전용 게이트 수 | 0(겸용) / 1 / 2 / 3대 |
| 시간대 | 첨두 / 비첨두 |

총 40개 시나리오 + S0(0% 기본), S1(100% 태그리스) 앵커 시나리오

## 현재 구현 상태
- [x] 보행 모델: CFSM V2 (JuPedSim) + 소프트웨어 큐
- [x] 게이트 선택: Gao et al. (2019) LRP 3단계
- [x] 물리 기반 도착 모델 (성수역 구조 반영)
- [x] S0 기본 시나리오 (TAGLESS_RATIO=0.0)
- [x] S1 전면 태그리스 (TAGLESS_RATIO=1.0)
- [x] 시나리오 비교 분석 (compare_scenarios.py)
- [ ] 출구 계단 혼잡도 측정 (병목 전이 분석용 모델 확장 필요)
- [ ] 과도기 시나리오 (20~80% 혼입률 x 전용 게이트 수)

## 주요 파일
```
simulation/
  run_west_simulation_cfsm.py   <- 메인 시뮬레이션 (파라미터 여기서 수정)
  seongsu_west.py               <- 성수역 기하구조 (게이트, 계단, 출구 좌표)
  compare_scenarios.py          <- 시나리오 비교 분석 (병목, 첨두/비첨두)
  analyze_trajectories.py       <- 궤적 품질 자동 감지 (역행, 정체, 밀집)

output/
  baseline/                     <- S0 결과 (TAGLESS_RATIO=0.0)
  tagless/                      <- S1 결과 (TAGLESS_RATIO=1.0)
  scenario_comparison.png       <- 두 시나리오 비교 그래프
```

## 핵심 파라미터 (run_west_simulation_cfsm.py)
```python
TAGLESS_RATIO        = 1.0    # 태그리스 이용자 비율 (0.0=기본, 1.0=전면)
TAGLESS_SERVICE_TIME = 1.2    # 태그리스 통과시간 (s)
SERVICE_TIME_MEAN    = 2.0    # 태그 통과시간 평균 (s, lognormal)
SIM_TIME             = 720.0  # 시뮬레이션 시간 (s, 열차 4편)
TRAIN_INTERVAL       = 180.0  # 열차 간격 (s)
TRAIN_ALIGHTING      = 234    # 편당 하차인원 (성수역 08-09시 기준)
N_GATES              = 7      # 게이트 수
```

## 시뮬레이션 실행
```bash
cd ~/tagless
python simulation/run_west_simulation_cfsm.py   # 시뮬레이션 실행
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
