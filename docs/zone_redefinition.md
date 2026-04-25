# 통행비용 측정 Zone 재정의 (궤적 기반, 2026-04-20)

## 1. 배경
기존 `docs/space_layout.py`의 Zone 정의(Z1~Z4C)는 **공간 기하 기반**으로 임의 분할된 것. 통행비용(travel cost) 산정에는 부적합.

**문제점**:
- **Z1 (대합실 전체, 1,250m²)**: 너무 광범위 — 평균 밀도 희석되어 의미 없음.
- **Z3B/Z4B (6m² 소면적)**: 소면적 나눗셈으로 peak density가 과도하게 부풀려짐 (z4b=4.77 ped/m²).
- **핵심**: Z4B의 "LOS F"는 실제 대기가 아니라 **순간 통과 밀도**. 실측 평균속도 **0.85 m/s**로 자유보행에 가깝고, 평균 체류 **4.8s**에 불과.

통행비용의 본질은 **"delay 발생 공간"** 식별. 따라서 **궤적 기반 대기 footprint**로 zone을 재정의해야 함.

## 2. 방법론
### 대기(waiting) 판정 기준
두 조건의 합집합:
1. `state == "queue"`: 소프트웨어 큐 내부 (게이트 대기 확정)
2. `state == "passed"` AND `speed < 0.5 m/s`: post-gate 체증 (자유보행 1.3 m/s 대비 2.6× 지연)

### 데이터
- 입력: `results_baseline/raw/trajectory_p0_s{42..46}.csv` (5 seeds, p=0, 300s)
- 총 182,808 frames (0.5s 샘플링)
- 대기 frames: 82,553 (45.2%)

### 처리
1. 0.5m × 0.5m 격자에 대기 frames 집계 → 단위 `wait-frames/s/m²`
2. threshold=0.181로 mask → connected component labeling
3. **Binary dilation (2 cells)** 으로 인접 큐 strip 병합 (게이트 7개 큐 → 1개 zone)
4. 각 cluster의 tight bounding rect + 0.25m buffer
5. 임의 이름(게이트/에스컬 랜드마크 기반) 부여

## 3. 도출된 대기 Zone

| ID | 이름 | x 범위 | y 범위 | 면적 | intensity (5 seeds 합) |
|---|---|---|---|---|---|
| **W1** | 게이트_대기 | 6.25 ~ 12.25 | 9.25 ~ 15.75 | **33.0 m²** | 17.82 |
| **W2** | upper_에스컬_대기 | 21.75 ~ 26.75 | 21.75 ~ 26.00 | **18.0 m²** | 8.73 |

### Per-waiter 통계 (p=0, 5 seeds)

| Zone | 대기경험 agent 수 | 평균 대기시간 | 중앙값 | p95 |
|---|---|---|---|---|
| W1 | 1,891 | **14.2 s** | 13.0 s | 29.0 s |
| W2 | 1,054 | **12.6 s** | 12.0 s | 27.0 s |

총 spawn ~2,070 (5 seeds), W1 경험률 91%, W2 경험률 51%. W2는 upper 선호 agent만 경유하므로 절반이 합리적.

## 4. 제외된 공간: Lower 에스컬 (기존 Z4B)

### 왜 제외되었나
기존 Z4B는 LOS F 판정되었으나, 실제 궤적 분석에서는 대기 아닌 **transit**으로 판명:

| 지표 | Lower 에스컬 (exit1) | Upper 에스컬 (exit4) |
|---|---|---|
| 평균 속도 | **0.85 m/s** | 0.32 m/s |
| 저속(<0.15) 비율 | 3.2% | 35.3% |
| 평균 체류 | 4.8 s | 13.5 s (**약 3배**) |
| 실효 처리율 | 0.60 ped/s | 0.78 ped/s |

→ Lower 에스컬은 **순간 밀도는 높으나 개인별 지연은 작음**. 통행비용 산정에서 제외 타당.

### 공학적 해석
- Lower 에스컬: 적은 agent 수가 빠르게 통과 (평균 0.85 m/s ≈ 자유보행의 65%)
- Upper 에스컬: 많은 agent가 병목 때문에 체증 (0.32 m/s ≈ 자유보행의 25%)
- **비대칭의 원인**: spawn 분포 + LRP 게이트 선택이 upper 편향 → upper 에스컬 과부하
- 시사점: 과도기 배합 설계 시 **upper 에스컬 하류 병목**이 핵심 제약. lower는 여유.

## 5. 통행비용 산정 공식 제안

```
total_cost_i = free_travel_time_i + sum_j (wait_time_j * weight_j)
```
- `free_travel_time_i` = 총 통행시간 − sum(대기시간)
- `wait_time_j` = agent i가 zone W_j 내에서 (state=queue 또는 speed<0.5) 시간
- `weight_j` = Fruin LOS 기반 disutility (예: D=1.0, E=1.5, F=2.5)

**시스템 통행비용** = sum over all agents of total_cost_i.

## 6. 기존 Zone 정의와의 차이

| 기존 (space_layout.py) | 신규 (v5) | 비고 |
|---|---|---|
| Z1 대합실 전체 (1250 m²) | **삭제** | 의미 없는 평균 희석 |
| Z2 게이트 앞 (28 m²) | **W1로 흡수 확장 (33 m²)** | 큐 꼬리까지 포괄 |
| Z3A/Z3B/Z3C (exit1 subzones) | **제거** | transit — 대기 없음 |
| Z4A (exit4 접근) | **W2에 흡수** | |
| Z4B exit4 대기 | **W2와 일치** | 좌표 미세조정 |
| Z4C corridor | **제거** | transit |

→ **8 zone → 2 zone 축약**. 통행비용 관련 본질적 공간만 보존.

## 7. 구현 경로
### 새 zone으로 batch_runner 업데이트 (선택적)
현재 `batch_runner.py` AREAS dict는 6m² 소면적 기준 z4b 등을 계산. 신 정의에선:
```python
AREAS_V5 = {
    "W1": (6.25, 12.25, 9.25, 15.75),   # 게이트_대기
    "W2": (21.75, 26.75, 21.75, 26.0),  # upper_에스컬_대기
}
```
면적: W1 = 39 m², W2 = 21.25 m² (0.25m buffer 포함).

### trajectory 기반 통행비용 집계 스크립트
`simulation/compute_travel_cost.py` 신규 작성 권장 (이번 작업에선 미수행):
- agent별 wait_time_j (per zone) 계산
- free_travel_time 분리
- LOS weight 적용
- 시나리오별 system cost 비교

## 8. 한계
1. **p=0 단일 조건 기반**: 태그리스 도입(p>0)에서 새로운 대기 공간 출현 가능. 예컨대 p=0.5 cfg3에서 Z3B(upper 에스컬 인근)가 F로 전이됨 → p>0 trajectory로도 검증 필요.
2. **static 정의**: 시간대별 변동(첨두 vs 비첨두) 반영 안 됨. 현 정의는 **첨두 조건 기반**.
3. **0.5 m/s 임계값의 근거**: Weidmann(1993) v0=1.34 m/s 대비 0.5/1.34=37% 속도 = 체증 가능 속도. 실증 검증 없음.
4. **Dilation 2 cells**: 게이트 간 1m 간격을 병합. 개별 게이트별 대기 분리 분석은 별도 수행 필요.

## 9. 생성 파일
- `simulation/define_waiting_zones.py` — 재정의 스크립트
- `docs/waiting_zones_v5.json` — 신 zone 정의 (좌표 + empirical stats)
- `figures/waiting_zone_analysis.png` — 히트맵 + 신규/기존 zone 대비
- `docs/zone_redefinition.md` — 본 문서

## 10. 후속 작업 (권장)
1. **compute_travel_cost.py 작성**: 신규 zone으로 agent별 통행비용 재계산
2. **p=0.3/0.5/0.8로 검증**: 다른 혼입률에서도 zone 위치가 일정한지 확인
3. **LOS weight 실증 보정**: 현장 관찰이나 선행연구 기반 가중치 설정
4. **첨두/비첨두 분리**: TRAIN_ALIGHTING 차이로 zone 이동 여부 검증
