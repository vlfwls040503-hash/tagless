"""
유효 (p, cfg) 시나리오들의 wait footprint 합집합으로 zone 정의.

1. results_cfsm_latest/raw/trajectory_*.csv 전체 로드 (cfg 1~4)
2. summary.csv 의 pass_rate >= 0.9 case 만 채택
3. 매 trajectory 에서 wait frames 추출:
     state == "queue"  OR  (state == "passed" AND speed < 0.5 m/s)
4. 모든 case 합쳐 2D heatmap (0.5m bin)
5. threshold + dilation 2 → connected component → bbox + 0.25 buffer
6. 도출된 zone JSON 저장 + heatmap PNG
"""
from __future__ import annotations
from pathlib import Path
import json
import sys
import numpy as np
import pandas as pd
from scipy import ndimage

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mp

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "results_cfsm_latest" / "raw"
SUMMARY = ROOT / "results_cfsm_latest" / "summary.csv"
OUT_JSON = ROOT / "docs" / "union_zones.json"
OUT_FIG = ROOT / "figures" / "molit" / "union_zones_heatmap.png"
OUT_FIG.parent.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(ROOT / "docs"))
from space_layout import SPACE  # noqa: E402

BIN = 0.5
WAIT_SPEED = 0.5  # m/s, post-gate 체증 임계 (자유보행 1.3 m/s 의 38%)
PASS_RATE_MIN = 0.9
DILATE_ITERS = 2
BUFFER = 0.25
THRESHOLD_FRAC = 0.08  # heatmap max × 8% 또는 MIN_DENSITY 중 큰 값
MIN_DENSITY = 0.02
BBOX_DOMAIN = (-2.0, 36.0, -2.0, 27.0)  # heatmap 범위


def load_valid_scenarios():
    """pass_rate >= 0.9 + cfg 1~4 + trajectory 존재하는 시나리오 list."""
    df = pd.read_csv(SUMMARY)
    df["pass_rate"] = df["passed"] / df["spawned"]
    keep = df[(df["config"].isin([1, 2, 3, 4, 5, 6])) & (df["pass_rate"] >= PASS_RATE_MIN)]
    valid = []
    for _, r in keep.iterrows():
        sid = r["scenario_id"]
        tp = RAW / f"trajectory_{sid}.csv"
        if tp.exists():
            valid.append((sid, r["p"], r["config"], r["seed"], r["pass_rate"]))
    return valid


def compute_speeds_inplace(df):
    df = df.sort_values(["agent_id", "time"]).reset_index(drop=True)
    grp = df.groupby("agent_id", sort=False)
    df["dx"] = grp["x"].diff()
    df["dy"] = grp["y"].diff()
    df["dt"] = grp["time"].diff()
    with np.errstate(invalid="ignore", divide="ignore"):
        df["speed"] = np.hypot(df["dx"], df["dy"]) / df["dt"]
    return df


def main():
    valid = load_valid_scenarios()
    print(f"유효 시나리오 (pass_rate>={PASS_RATE_MIN}): {len(valid)}")

    x0, x1, y0, y1 = BBOX_DOMAIN
    x_edges = np.arange(x0, x1 + BIN, BIN)
    y_edges = np.arange(y0, y1 + BIN, BIN)
    H_total = np.zeros((len(x_edges) - 1, len(y_edges) - 1), dtype=np.float64)

    n_used = 0
    for sid, p, cfg, seed, pr in valid:
        tp = RAW / f"trajectory_{sid}.csv"
        df = pd.read_csv(tp)
        df = compute_speeds_inplace(df)
        # warm-up 제외 (첫 90s) — 정상상태 도달 후만
        df = df[df["time"] >= 90.0]
        mask_q = df["state"] == "queue"
        mask_s = ((df["state"] == "passed") &
                  df["speed"].notna() & (df["speed"] < WAIT_SPEED))
        wait = df[mask_q | mask_s]
        if len(wait) == 0:
            continue
        H, _, _ = np.histogram2d(wait["x"], wait["y"], bins=(x_edges, y_edges))
        H_total += H
        n_used += 1
        if n_used % 20 == 0:
            print(f"  처리 {n_used}/{len(valid)}: {sid} pr={pr:.2f} wait_frames={len(wait)}")

    print(f"\n총 {n_used} trajectory 합산 완료")
    cell_area = BIN * BIN
    # 각 frame = 0.5s 점유, 합산 시나리오 수로 normalize
    H_density = H_total * 0.5 / cell_area / max(n_used, 1)
    print(f"heatmap max density: {H_density.max():.4f} wait-frames/s/m^2")

    thr = max(MIN_DENSITY, H_density.max() * THRESHOLD_FRAC)
    print(f"threshold: {thr:.4f}")

    mask = H_density > thr
    mask_d = ndimage.binary_dilation(mask, iterations=DILATE_ITERS)
    labels, n_lab = ndimage.label(mask_d, structure=np.ones((3, 3)))
    print(f"clusters: {n_lab}")

    clusters = []
    for lid in range(1, n_lab + 1):
        idx = np.where((labels == lid) & mask)
        if len(idx[0]) < 4:
            continue
        xi_min, xi_max = idx[0].min(), idx[0].max()
        yi_min, yi_max = idx[1].min(), idx[1].max()
        xmin = float(x_edges[xi_min]) - BUFFER
        xmax = float(x_edges[xi_max + 1]) + BUFFER
        ymin = float(y_edges[yi_min]) - BUFFER
        ymax = float(y_edges[yi_max + 1]) + BUFFER
        area = (xmax - xmin) * (ymax - ymin)
        peak = float(H_density[xi_min:xi_max + 1, yi_min:yi_max + 1].max())
        total = float(H_density[xi_min:xi_max + 1, yi_min:yi_max + 1].sum() * cell_area)
        clusters.append({
            "x_range": [round(xmin, 2), round(xmax, 2)],
            "y_range": [round(ymin, 2), round(ymax, 2)],
            "area_m2": round(area, 2),
            "peak_density": round(peak, 4),
            "total_intensity": round(total, 4),
            "n_cells": int(len(idx[0])),
        })

    clusters.sort(key=lambda c: c["total_intensity"], reverse=True)

    # 휴리스틱 이름 부여
    def name(c):
        x_mid = 0.5 * (c["x_range"][0] + c["x_range"][1])
        y_mid = 0.5 * (c["y_range"][0] + c["y_range"][1])
        if x_mid < 13 and 8 <= y_mid <= 17:
            return "W_gate"
        if x_mid > 20 and y_mid > 18:
            return "W_esc_upper"
        if x_mid > 20 and y_mid < 8:
            return "W_esc_lower"
        return f"W_other({x_mid:.1f},{y_mid:.1f})"

    for i, c in enumerate(clusters):
        c["id"] = f"W{i+1}"
        c["name"] = name(c)

    output = {
        "metadata": {
            "method": f"wait = (state==queue) OR (state==passed AND speed<{WAIT_SPEED} m/s)",
            "source": f"results_cfsm_latest/raw (cfg 1~4, pass_rate>={PASS_RATE_MIN})",
            "n_scenarios_used": n_used,
            "warmup_excluded_s": 90.0,
            "bin_m": BIN,
            "threshold": round(thr, 4),
            "dilation": DILATE_ITERS,
            "buffer_m": BUFFER,
        },
        "zones": clusters,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n저장: {OUT_JSON}")
    print("\n도출된 zone:")
    for c in clusters:
        print(f"  {c['id']} {c['name']:>15s}: x={c['x_range']}, y={c['y_range']}, "
              f"area={c['area_m2']:.1f}m^2, peak={c['peak_density']:.3f}")

    # 시각화
    fig, ax = plt.subplots(figsize=(10, 5), dpi=100)
    im = ax.imshow(H_density.T, origin="lower",
                   extent=[x_edges[0], x_edges[-1], y_edges[0], y_edges[-1]],
                   aspect="equal", cmap="hot",
                   vmax=np.percentile(H_density[H_density > 0], 95)
                        if (H_density > 0).any() else 1)
    for c in clusters:
        x0_, x1_ = c["x_range"]; y0_, y1_ = c["y_range"]
        r = mp.Rectangle((x0_, y0_), x1_ - x0_, y1_ - y0_,
                         fill=False, edgecolor="cyan", linewidth=2)
        ax.add_patch(r)
        ax.text(0.5 * (x0_ + x1_), 0.5 * (y0_ + y1_),
                f"{c['id']}\n{c['name']}\n{c['area_m2']:.1f}m^2",
                color="cyan", ha="center", va="center", fontsize=9, fontweight="bold")
    cc = SPACE["concourse"]
    ax.plot([0, cc["length"], cc["length"], 0, 0],
            [0, 0, cc["width"], cc["width"], 0], "w-", lw=1)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.set_title(f"합집합 wait footprint (n={n_used} 시나리오, cfg1~4, pass_rate>={PASS_RATE_MIN})")
    plt.colorbar(im, ax=ax, shrink=0.7, label="wait-frames/s/m^2")
    plt.tight_layout()
    plt.savefig(OUT_FIG, dpi=100, bbox_inches="tight")
    plt.close()
    print(f"그림: {OUT_FIG}")


if __name__ == "__main__":
    main()
