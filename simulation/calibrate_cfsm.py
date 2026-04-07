# -*- coding: utf-8 -*-
"""
CFSM V2 파라미터 보정: FZJ Seyfried et al. (2005) 기본다이어그램 기반

Tordeux et al. (2016) CFSM V2 속도 함수:
  V(s) = min(v0, max(0, (s - l) / T))
  - s: 선행 보행자와의 간격 (m)
  - l: 보행자 지름 (2 * radius)
  - T: time_gap (s) ← 보정 대상
  - v0: 자유 보행속도 (m/s)

1D 밀도 → 2D 밀도 변환:
  rho_2D = rho_1D^2 (Seyfried et al., 2005)
  또는 rho_2D = rho_1D / w (복도 폭 w)

FZJ 실험 조건: 원형 복도, single-file → 1D 밀도 (ped/m)
  1D headway: s = 1 / rho_1D
"""

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.optimize import minimize_scalar, curve_fit
import pathlib

plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

OUTPUT_DIR = pathlib.Path(__file__).parent.parent / 'output'
DATA_DIR   = pathlib.Path(__file__).parent.parent / 'data' / 'fzj'


# =============================================================================
# 1. FZJ 데이터 로드
# =============================================================================
def load_seyfried2005(path=None):
    """Seyfried et al. (2005) single-file 데이터 로드
    Returns: list of (rho_1d, v) tuples
    """
    if path is None:
        path = DATA_DIR / 'seyfried2005_single_file.txt'

    data = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) == 2:
                try:
                    v = float(parts[0])
                    rho = float(parts[1])
                    data.append((rho, v))
                except ValueError:
                    continue
    return np.array(data)  # shape (N, 2): [rho_1d, v]


# =============================================================================
# 2. CFSM V2 속도 함수
# =============================================================================
def cfsm_speed(rho_1d, T, v0=1.34, l=0.3):
    """
    CFSM V2 이론 속도
    rho_1d: 1D 밀도 (ped/m)
    T: time_gap (s)
    v0: 자유 보행속도 (m/s)
    l: 보행자 지름 (m) = 2 * radius
    """
    s = 1.0 / np.maximum(rho_1d, 0.01)  # headway = 1/rho
    v = np.minimum(v0, np.maximum(0, (s - l) / T))
    return v


# =============================================================================
# 3. 보정: 최적 time_gap 탐색
# =============================================================================
def calibrate_time_gap(data, v0=1.34, l=0.3):
    """FZJ 데이터에 CFSM 속도 함수 피팅 → 최적 T 도출"""
    rho = data[:, 0]
    v_obs = data[:, 1]

    def rmse(T):
        v_pred = cfsm_speed(rho, T, v0, l)
        return np.sqrt(np.mean((v_pred - v_obs) ** 2))

    result = minimize_scalar(rmse, bounds=(0.3, 3.0), method='bounded')
    T_opt = result.x
    rmse_opt = result.fun

    return T_opt, rmse_opt


def calibrate_dynamic_time_gap(data, v0=1.34, l=0.3):
    """밀도 구간별 최적 T 도출 (동적 time_gap 보정)"""
    rho = data[:, 0]
    v_obs = data[:, 1]

    # 밀도 구간 정의 (1D 밀도 기준)
    # rho_1d < 1.0: 저밀도 → 2D로 ~0.5 ped/m² 이하
    # rho_1d 1.0~1.5: 중밀도
    # rho_1d > 1.5: 고밀도
    bins = [
        ('low',  rho < 1.0),
        ('mid',  (rho >= 1.0) & (rho < 1.5)),
        ('high', rho >= 1.5),
    ]

    results = {}
    for name, mask in bins:
        if mask.sum() < 3:
            continue
        rho_sub = rho[mask]
        v_sub = v_obs[mask]

        def rmse(T):
            v_pred = cfsm_speed(rho_sub, T, v0, l)
            return np.sqrt(np.mean((v_pred - v_sub) ** 2))

        res = minimize_scalar(rmse, bounds=(0.3, 3.0), method='bounded')
        results[name] = {
            'T': res.x,
            'rmse': res.fun,
            'n': mask.sum(),
            'rho_range': (rho_sub.min(), rho_sub.max()),
        }

    return results


# =============================================================================
# 4. 시각화
# =============================================================================
def plot_calibration(data, T_opt, dynamic_results, v0=1.34, l=0.3):
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    rho = data[:, 0]
    v_obs = data[:, 1]

    # ── (a) 단일 T 보정 결과 ──
    ax = axes[0]
    ax.scatter(rho, v_obs, c='gray', s=15, alpha=0.5, label='FZJ 실측 (2005)')

    rho_fit = np.linspace(0.4, 2.2, 200)
    v_fit = cfsm_speed(rho_fit, T_opt, v0, l)
    ax.plot(rho_fit, v_fit, 'r-', lw=2.5,
            label=f'CFSM V2 (T={T_opt:.3f}s)')

    # 현재 설정값
    v_current = cfsm_speed(rho_fit, 0.80, v0, l)
    ax.plot(rho_fit, v_current, 'b--', lw=1.5, alpha=0.7,
            label='현재 설정 (T=0.80s)')

    ax.set_xlabel('1D 밀도 (ped/m)')
    ax.set_ylabel('속도 (m/s)')
    ax.set_title('(a) 단일 T 보정')
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.set_xlim(0.3, 2.2)
    ax.set_ylim(0, 1.2)

    # ── (b) 밀도 구간별 동적 T ──
    ax = axes[1]
    ax.scatter(rho, v_obs, c='gray', s=15, alpha=0.5, label='FZJ 실측')

    colors = {'low': '#4CAF50', 'mid': '#FF9800', 'high': '#F44336'}
    labels = {'low': '저밀도', 'mid': '중밀도', 'high': '고밀도'}

    for name, res in dynamic_results.items():
        r_lo, r_hi = res['rho_range']
        rho_seg = np.linspace(r_lo, r_hi, 100)
        v_seg = cfsm_speed(rho_seg, res['T'], v0, l)
        ax.plot(rho_seg, v_seg, color=colors[name], lw=2.5,
                label=f"{labels[name]}: T={res['T']:.3f}s (n={res['n']})")

    ax.set_xlabel('1D 밀도 (ped/m)')
    ax.set_ylabel('속도 (m/s)')
    ax.set_title('(b) 밀도 구간별 동적 T 보정')
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.set_xlim(0.3, 2.2)
    ax.set_ylim(0, 1.2)

    plt.suptitle('CFSM V2 time_gap 보정: Seyfried et al. (2005) FZJ 데이터',
                 fontsize=13, fontweight='bold')
    plt.tight_layout()
    out = OUTPUT_DIR / 'calibration_cfsm_fzj.png'
    fig.savefig(out, dpi=150, bbox_inches='tight')
    plt.close(fig)
    print(f'  저장: {out}')
    return fig


# =============================================================================
# 5. 현재 설정과 비교
# =============================================================================
def compare_with_current():
    print("\n[현재 설정 vs FZJ 보정 비교]")
    print(f"{'구간':<12} {'현재':>10} {'FZJ 보정':>10} {'비고'}")
    print("-" * 50)

    current = {
        'low':  1.5,   # TIME_GAP_LOW
        'mid':  1.0,   # TIME_GAP_MID
        'high': 0.7,   # TIME_GAP_HIGH
    }

    return current


# =============================================================================
# 메인
# =============================================================================
def main():
    print("=" * 55)
    print("CFSM V2 보정: Seyfried et al. (2005) FZJ 데이터")
    print("=" * 55)

    data = load_seyfried2005()
    print(f"데이터: {len(data)}개 관측점")
    print(f"밀도 범위: {data[:,0].min():.3f} ~ {data[:,0].max():.3f} ped/m")
    print(f"속도 범위: {data[:,1].min():.3f} ~ {data[:,1].max():.3f} m/s")

    # 단일 T 보정
    T_opt, rmse_opt = calibrate_time_gap(data)
    print(f"\n[단일 T 보정]")
    print(f"  최적 T = {T_opt:.4f}s  (RMSE = {rmse_opt:.4f} m/s)")
    print(f"  현재 T = 0.80s")

    # 동적 T 보정
    dynamic = calibrate_dynamic_time_gap(data)
    print(f"\n[밀도 구간별 동적 T 보정]")
    for name, res in dynamic.items():
        print(f"  {name:>5}: T={res['T']:.4f}s  "
              f"RMSE={res['rmse']:.4f}  "
              f"rho={res['rho_range'][0]:.2f}~{res['rho_range'][1]:.2f}  "
              f"(n={res['n']})")

    # 현재 설정 비교
    current = compare_with_current()
    for name in ['low', 'mid', 'high']:
        if name in dynamic:
            cur = current[name]
            cal = dynamic[name]['T']
            diff = (cal - cur) / cur * 100
            print(f"  {name:<12} {cur:>10.3f} {cal:>10.3f}   {diff:>+6.1f}%")

    # 시각화
    plot_calibration(data, T_opt, dynamic)

    # 2D 밀도 변환 참고
    print("\n[참고: 1D → 2D 밀도 변환]")
    print("  복도 폭 w에서: rho_2D = rho_1D / w")
    print("  w=2m 가정: rho_1D=1.0 → rho_2D=0.5 ped/m^2")
    print("  w=2m 가정: rho_1D=1.5 → rho_2D=0.75 ped/m^2")
    print("  w=2m 가정: rho_1D=2.0 → rho_2D=1.0 ped/m^2")

    return T_opt, dynamic


if __name__ == '__main__':
    main()
