"""
100-시나리오 배치 러너.

용법:
  python simulation/batch_runner.py            # 전체 100회
  python simulation/batch_runner.py --pilot    # 파일럿 1회 (p=0.5, cfg=3, seed=42)
  python simulation/batch_runner.py --limit 10 # 앞 10개만

특성:
  - 이미 results/raw/ 에 있는 시나리오는 스킵 (중단 후 재개 지원)
  - 실패한 시나리오는 로그에 기록, 계속 진행
  - 연속 5회 실패 시 중단
  - 모든 실행을 results/execution_log.txt 에 timestamp와 함께 기록
"""
import argparse
import csv
import importlib
import os
import pathlib
import sys
import time
import traceback
from datetime import datetime

# Windows cp949 인코딩 회피 — 유니코드 출력 허용
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scenarios"))
sys.path.insert(0, str(ROOT / "simulation"))

from scenario_matrix import iter_scenarios  # noqa: E402

RESULTS_DIR = ROOT / "results"  # main()에서 --results-dir로 override
RAW_DIR = RESULTS_DIR / "raw"
LOG_PATH = RESULTS_DIR / "execution_log.txt"
FAIL_LOG = RESULTS_DIR / "failures.txt"


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run_one_scenario(sid, params):
    """단일 시나리오 실행. 성공 시 (wall_time, spawned, passed) 반환. 실패 시 예외 rethrow."""
    # runner 모듈을 매 실행마다 reload - 전역 상태(trajectory_data 누적 등) 초기화
    import run_west_simulation_cfsm_escalator as runner
    importlib.reload(runner)

    # 파라미터 적용 (module globals 덮어쓰기)
    for key, val in params.items():
        if key.startswith("_"):  # _p, _config, _seed - 내부 메타
            continue
        setattr(runner, key, val)

    # 배치 모드 출력 경로 설정
    runner.BATCH_METRICS_OUT = RAW_DIR / f"agents_{sid}.csv"
    runner.BATCH_ZONE_CSV_OUT = RAW_DIR / f"zones_{sid}.csv"
    runner.BATCH_OUTPUT_SUFFIX = f"_{sid}"
    runner.BATCH_SKIP_HEAVY_OUTPUTS = True  # mp4/snapshot 생략

    t0 = time.time()
    stats, spawned = runner.run_simulation()
    wall = time.time() - t0
    passed = sum(stats["gate_counts"])
    return wall, spawned, passed, stats


def aggregate_summary_row(sid, params, stats, spawned, passed):
    """시나리오 1개의 집계값 dict 반환."""
    import numpy as np

    # per-agent CSV 읽어서 travel time 집계
    agent_csv = RAW_DIR / f"agents_{sid}.csv"
    travel_times, gate_waits, post_gates = [], [], []
    n_exit1 = n_exit4 = 0
    if agent_csv.exists():
        with open(agent_csv, "r", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                tt = row.get("travel_time")
                if tt and tt != "None":
                    travel_times.append(float(tt))
                gw = row.get("gate_wait_time")
                if gw and gw != "None":
                    gate_waits.append(float(gw))
                pg = row.get("post_gate_time")
                if pg and pg != "None":
                    post_gates.append(float(pg))
                side = row.get("sink_side", "")
                if side == "lower": n_exit1 += 1
                elif side == "upper": n_exit4 += 1
    travel_times = np.array(travel_times) if travel_times else np.array([])
    gate_waits = np.array(gate_waits) if gate_waits else np.array([])
    post_gates = np.array(post_gates) if post_gates else np.array([])

    # zone density
    zone_csv = RAW_DIR / f"zones_{sid}.csv"
    # zone 면적 (배치 설정과 일치)
    AREAS = {"z1": 50 * 25, "z2": 4 * 7, "z3": 2 * 3, "z4": 2 * 3}
    zone_series = {"z1": [], "z2": [], "z3": [], "z4": []}
    if zone_csv.exists():
        with open(zone_csv, "r", encoding="utf-8") as f:
            r = csv.DictReader(f)
            for row in r:
                for i, zk in enumerate(["z1", "z2", "z3", "z4"], 1):
                    c = int(row[f"zone{i}_count"])
                    zone_series[zk].append(c / AREAS[zk])

    def _stat(series, fn, default=0.0):
        return float(fn(series)) if series else default

    total_side = n_exit1 + n_exit4
    exit1_share = n_exit1 / total_side if total_side > 0 else 0.0

    return {
        "scenario_id": sid,
        "p": params["_p"],
        "config": params["_config"],
        "seed": params["_seed"],
        "spawned": spawned,
        "passed": passed,
        "avg_travel_time": float(travel_times.mean()) if len(travel_times) else 0.0,
        "p95_travel_time": float(np.percentile(travel_times, 95)) if len(travel_times) else 0.0,
        "n_completed": len(travel_times),
        "avg_gate_wait": float(gate_waits.mean()) if len(gate_waits) else 0.0,
        "p95_gate_wait": float(np.percentile(gate_waits, 95)) if len(gate_waits) else 0.0,
        "avg_post_gate": float(post_gates.mean()) if len(post_gates) else 0.0,
        "p95_post_gate": float(np.percentile(post_gates, 95)) if len(post_gates) else 0.0,
        "n_exit1": n_exit1,
        "n_exit4": n_exit4,
        "exit1_share": exit1_share,
        "zone1_avg_density": _stat(zone_series["z1"], np.mean),
        "zone1_max_density": _stat(zone_series["z1"], np.max),
        "zone2_avg_density": _stat(zone_series["z2"], np.mean),
        "zone2_max_density": _stat(zone_series["z2"], np.max),
        "zone3_avg_density": _stat(zone_series["z3"], np.mean),
        "zone3_max_density": _stat(zone_series["z3"], np.max),
        "zone4_avg_density": _stat(zone_series["z4"], np.mean),
        "zone4_max_density": _stat(zone_series["z4"], np.max),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pilot", action="store_true", help="파일럿 1회만 실행")
    ap.add_argument("--limit", type=int, default=None, help="앞 N개 시나리오만")
    ap.add_argument("--timeout-minutes", type=float, default=15.0,
                    help="시뮬 1회 최대 허용 시간 (분) - 초과 시 중단")
    ap.add_argument("--results-dir", default="results",
                    help="출력 디렉토리 (ROOT 기준 상대, 기본 results)")
    args = ap.parse_args()

    global RESULTS_DIR, RAW_DIR, LOG_PATH, FAIL_LOG
    RESULTS_DIR = ROOT / args.results_dir
    RAW_DIR = RESULTS_DIR / "raw"
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    LOG_PATH = RESULTS_DIR / "execution_log.txt"
    FAIL_LOG = RESULTS_DIR / "failures.txt"

    scenarios = list(iter_scenarios())

    if args.pilot:
        # 파일럿: p=0.5, cfg=3, seed=42
        scenarios = [s for s in scenarios
                     if s[1]["_p"] == 0.5 and s[1]["_config"] == 3
                     and s[1]["_seed"] == 42]
        log(f"파일럿 모드: {len(scenarios)} 시나리오")
    elif args.limit:
        scenarios = scenarios[:args.limit]
        log(f"Limit 모드: {len(scenarios)} 시나리오")
    else:
        log(f"전체 모드: {len(scenarios)} 시나리오")

    timeout_sec = args.timeout_minutes * 60
    rows = []
    consecutive_failures = 0
    ok = skipped = failed = 0

    for i, (sid, params) in enumerate(scenarios, 1):
        agent_csv = RAW_DIR / f"agents_{sid}.csv"
        zone_csv = RAW_DIR / f"zones_{sid}.csv"
        if agent_csv.exists() and zone_csv.exists():
            log(f"[{i}/{len(scenarios)}] {sid}: SKIP (이미 존재)")
            skipped += 1
            # 기존 파일로 summary 재집계
            try:
                row = aggregate_summary_row(sid, params,
                                            {"gate_counts": [0]}, 0, 0)
                rows.append(row)
            except Exception:
                pass
            continue

        log(f"[{i}/{len(scenarios)}] {sid}: 시작 (p={params['_p']}, "
            f"cfg={params['_config']}, seed={params['_seed']})")
        try:
            wall, spawned, passed, stats = run_one_scenario(sid, params)
            log(f"[{i}/{len(scenarios)}] {sid}: OK "
                f"({wall:.1f}s, spawn={spawned}, pass={passed})")
            if wall > timeout_sec:
                log(f"!!! {sid}: 시뮬 1회 {wall:.1f}s > 임계 {timeout_sec:.0f}s "
                    f"→ 이후 시나리오 중단")
                row = aggregate_summary_row(sid, params, stats, spawned, passed)
                rows.append(row)
                break
            row = aggregate_summary_row(sid, params, stats, spawned, passed)
            rows.append(row)
            ok += 1
            consecutive_failures = 0
        except Exception as e:
            tb = traceback.format_exc()
            log(f"[{i}/{len(scenarios)}] {sid}: FAIL - {e}")
            with open(FAIL_LOG, "a", encoding="utf-8") as f:
                f.write(f"\n=== {sid} ===\n{tb}\n")
            failed += 1
            consecutive_failures += 1
            if consecutive_failures >= 5:
                log(f"!!! 연속 5회 실패 → 중단")
                break

    # summary CSV (v2는 summary_v2.csv 파일명)
    _suffix = "_v2" if "v2" in args.results_dir else ""
    summary_csv = RESULTS_DIR / f"summary{_suffix}.csv"
    if rows:
        with open(summary_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        log(f"summary.csv 생성: {len(rows)} 행 -> {summary_csv}")
    log(f"종료: 성공 {ok}, 스킵 {skipped}, 실패 {failed}")


if __name__ == "__main__":
    main()
