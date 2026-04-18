# 태그리스 개찰구 과도기 게이트 운영 전략 연구

서울시립대 교통공학과 졸업설계 | 박필진 | 지도교수: 이동민

## 연구 개요

지하철 태그리스 개찰구 과도기(태그/태그리스 혼재)에서 최적 게이트 배합
(전용/공용 구성)을 도출. 성수역 2F 대합실 서쪽 반(50m×25m, 게이트 7대)을
대상 공간으로 JuPedSim 기반 보행 시뮬레이션 수행.

## 2026-04-18 작업 요약

### 주요 성과 (R² 추이)

| 단계 | 조건 | avg_travel_time R² | 비고 |
|---|---|---|---|
| 초기 | 비대칭 배합, 120s, 잭키잉 ON | 0.017 | 필터 무력화 상태 |
| 잭키잉 수정 | 비대칭 배합, 120s, 잭키잉 OFF (배치 모드) | 0.309 | 18배 ↑ |
| **v2 재실험** | **대칭 배합, 300s, 구간별 측정** | **0.696** | 2.25배 ↑ |

### 핵심 발견

1. **최적 전용 게이트 수는 p에 따라 단조 증가**
   - p=0.1 → cfg 1 (전용 1개) | p=0.8 → cfg 4
   - ANOVA 교호 효과 η² = 0.62 (very large)

2. **역설 (RQ2) 확인**
   - p와 어긋나는 배합 선택 시 통과율 최저 55.9%
   - 가변 운영의 정량적 근거 확보

3. **병목 전이 (RQ3) 정성 관측**
   - 실측 게이트 처리율 vs 에스컬 대기: r=+0.48, R²=0.23
   - 최적 배합에서 post_gate가 총 시간의 50~62% 차지
   - 단, 현재 조건에서 에스컬 용량이 최적 배합 선택을 바꿀 만큼 부족하진 않음

## 파일 구조

```
tagless/
├── simulation/
│   ├── seongsu_west_escalator.py          # 기하구조 v4 (계단 가로통로 + 에스컬)
│   ├── run_west_simulation_cfsm_escalator.py  # 메인 sim runner
│   ├── batch_runner.py                     # 100 시나리오 순차 배치
│   └── ...
├── scenarios/
│   └── scenario_matrix.py                  # 100 시나리오 정의 (5×4×5)
├── analysis/
│   ├── aggregate_results.py
│   ├── plot_figures.py
│   ├── statistical_analysis.py
│   ├── generate_report.py
│   ├── analyze_v2.py                       # v1 vs v2 비교
│   ├── phase3_analysis.py                  # 게이트-only vs total
│   └── stats_rigor.py                      # Part A 통계 보강
├── results/                                # v1 (비대칭, 120s)
│   ├── summary.csv
│   ├── raw/ (200 CSV)
│   ├── figures/
│   └── analysis_report.md
├── results_v2/                             # v2 (대칭, 300s, 구간별 측정)
│   ├── summary_v2.csv
│   ├── raw/ (200 CSV)
│   ├── figures_phase3/                     # 병목 전이 그래프 3종
│   ├── figures_stats/                      # 통계 보강 그래프 5종
│   ├── presentation_slides/                # 발표 슬라이드 5장 (md)
│   ├── analysis_v2.md
│   ├── phase3_report.md
│   └── execution_log.txt
└── docs/
    ├── pitch_1sentence.md / pitch_1paragraph.md / pitch_3min.md
    ├── qa_prep.md                           # 예상 질문 10개
    ├── glossary.md
    ├── executive_summary.md
    ├── statistical_rigor.md
    └── phase1~3_*.md
```

## 재현 방법

### 파일럿 (1회, 약 30초)

```bash
cd tagless
py -3 simulation/batch_runner.py --pilot --results-dir results_v2
```

### 전체 배치 (100회, 약 45분)

```bash
py -3 simulation/batch_runner.py --results-dir results_v2
```

### 분석 파이프라인

```bash
# v1 분석
py -3 analysis/plot_figures.py
py -3 analysis/statistical_analysis.py
py -3 analysis/generate_report.py

# v2 + Phase 1-3
py -3 analysis/analyze_v2.py
py -3 analysis/phase3_analysis.py

# Part A 통계 보강
py -3 analysis/stats_rigor.py
```

### 의존 패키지

- Python 3.10+ (테스트: 3.12)
- jupedsim, numpy, pandas, matplotlib, shapely, scipy, statsmodels

## 논문 스토리

> "태그리스 전용 게이트를 무조건 늘리면 좋을까?"

- **RQ1 (현상)**: 혼입률 증가 시 병목이 게이트→에스컬로 전이되는가?
- **RQ2 (역설)**: 전용 게이트 확대가 항상 효율을 높이는가?
- **RQ3 (처방)**: 시간대별 가변 운영이 고정보다 유효한가?

## 주요 문서

- [docs/executive_summary.md](docs/executive_summary.md) — 1페이지 요약
- [docs/pitch_3min.md](docs/pitch_3min.md) — 3분 발표 인트로
- [results_v2/phase3_report.md](results_v2/phase3_report.md) — 병목 전이 종합 보고서
- [docs/statistical_rigor.md](docs/statistical_rigor.md) — 통계 보강

## 참고 문헌

- Gao et al. 2019 — LRP 게이트 선택 모델
- Tordeux et al. 2016 — CFSM V2 보행 모델
- Weidmann 1993 — Fundamental Diagram
- Moussaïd et al. 2011 — 유한 시야 보행자 행태
- Rzezonka et al. 2022 — 통근자 time_gap
- Cheung & Lam 2002 — 에스컬레이터 처리율

---

**생성일**: 2026-04-18
