"""
병렬 batch runner — multiprocessing 으로 시나리오 동시 실행.

기존 batch_runner.py 는 시리얼. 이건 ProcessPoolExecutor 사용.
- 각 시나리오를 별도 프로세스에서 실행 → 4~8배 빠름 (CPU 코어 수 의존)
- 결과 aggregation 만 메인 프로세스에서 수행

사용:
    python batch_runner_parallel.py --workers 6 --results-dir results
"""
from __future__ import annotations
import argparse
import csv
import importlib
import os
import pathlib
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
SIM_DIR = ROOT / "simulation"
SCEN_DIR = ROOT / "scenarios"
sys.path.insert(0, str(SIM_DIR))
sys.path.insert(0, str(SCEN_DIR))

from scenario_matrix import iter_scenarios  # noqa: E402


def _worker_init():
    """워커 프로세스 초기화. 각 프로세스에서 sim 모듈 사전 로드."""
    sys.path.insert(0, str(SIM_DIR))


def _run_scenario_worker(args):
    """단일 시나리오 워커. (sid, params, raw_dir, model, esc_service_time, save_traj) 받음.

    각 프로세스마다 jupedsim 새로 import (process pool은 isolated).
    """
    sid, params, raw_dir, model, esc_service_time, save_traj = args
    raw_dir = pathlib.Path(raw_dir)

    sys.path.insert(0, str(SIM_DIR))
    if model == "avm":
        import run_west_simulation_avm_demo as runner
    else:
        import run_west_simulation_cfsm_escalator as runner
    importlib.reload(runner)

    # 파라미터 적용
    for key, val in params.items():
        if key.startswith("_"):
            continue
        setattr(runner, key, val)

    runner.BATCH_METRICS_OUT = raw_dir / f"agents_{sid}.csv"
    runner.BATCH_ZONE_CSV_OUT = raw_dir / f"zones_{sid}.csv"
    runner.BATCH_OUTPUT_SUFFIX = f"_{sid}"
    runner.BATCH_SKIP_HEAVY_OUTPUTS = True
    if save_traj:
        runner.BATCH_SAVE_TRAJECTORY = True
        runner.BATCH_TRAJECTORY_OUT = raw_dir / f"trajectory_{sid}.csv"
        runner.BATCH_TRAJECTORY_INTERVAL = 0.5
    if esc_service_time is not None:
        runner.BATCH_ESC_SERVICE_TIME = esc_service_time

    t0 = time.time()
    try:
        stats, spawned = runner.run_simulation()
        wall = time.time() - t0
        passed = sum(stats["gate_counts"])
        return ("ok", sid, wall, spawned, passed, stats)
    except Exception as e:
        return ("fail", sid, time.time() - t0, str(e), traceback.format_exc(), None)


def aggregate_summary_row(sid, params, stats, spawned, passed, raw_dir):
    """기존 batch_runner 의 aggregate_summary_row 와 동일."""
    raw_dir = pathlib.Path(raw_dir)
    agent_csv = raw_dir / f"agents_{sid}.csv"
    travel_times, gate_waits, post_gates, esc_precise = [], [], [], []
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
                ewp = row.get("esc_wait_precise")
                if ewp and ewp != "None":
                    esc_precise.append(float(ewp))
                side = row.get("sink_side", "")
                if side == "lower": n_exit1 += 1
                elif side == "upper": n_exit4 += 1
    travel_times = np.array(travel_times) if travel_times else np.array([])
    gate_waits = np.array(gate_waits) if gate_waits else np.array([])
    post_gates = np.array(post_gates) if post_gates else np.array([])
    esc_precise = np.array(esc_precise) if esc_precise else np.array([])

    zone_csv = raw_dir / f"zones_{sid}.csv"
    AREAS = {
        "z1": 50 * 25, "z2": 4 * 7,
        "z3a": 8 * 3, "z3b": 2 * 3, "z3c": 10 * 3,
        "z4a": 8 * 3, "z4b": 2 * 3, "z4c": 10 * 3,
    }
    zone_series = {k: [] for k in AREAS}
    if zone_csv.exists():
        with open(zone_csv, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            is_v3 = "zone3a_count" in header
            for row in reader:
                if is_v3:
                    t, z1, z2, z3a, z3b, z3c, z4a, z4b, z4c = row
                    vals = {"z1": z1, "z2": z2, "z3a": z3a, "z3b": z3b,
                            "z3c": z3c, "z4a": z4a, "z4b": z4b, "z4c": z4c}
                else:
                    t, z1, z2, z3, z4 = row
                    vals = {"z1": z1, "z2": z2, "z3b": z3, "z4b": z4,
                            "z3a": 0, "z3c": 0, "z4a": 0, "z4c": 0}
                for k, v in vals.items():
                    zone_series[k].append(int(v))

    def _agg(arr, fn=np.mean):
        return float(fn(arr)) if len(arr) > 0 else 0.0

    row = {
        "scenario_id": sid,
        "p": params["_p"],
        "config": params["_config"],
        "seed": params["_seed"],
        "spawned": spawned,
        "passed": passed,
        "avg_travel_time": _agg(travel_times),
        "p95_travel_time": _agg(travel_times, lambda a: np.percentile(a, 95)),
        "n_completed": len(travel_times),
        "avg_gate_wait": _agg(gate_waits),
        "p95_gate_wait": _agg(gate_waits, lambda a: np.percentile(a, 95)),
        "avg_post_gate": _agg(post_gates),
        "p95_post_gate": _agg(post_gates, lambda a: np.percentile(a, 95)),
        "avg_esc_wait_precise": _agg(esc_precise),
        "p95_esc_wait_precise": _agg(esc_precise, lambda a: np.percentile(a, 95)),
        "n_esc_precise": len(esc_precise),
        "n_exit1": n_exit1,
        "n_exit4": n_exit4,
        "exit1_share": n_exit1 / max(n_exit1 + n_exit4, 1),
    }
    for z, area in AREAS.items():
        s = zone_series[z]
        if s:
            avg_count = np.mean(s)
            max_count = np.max(s)
        else:
            avg_count = max_count = 0
        row[f"zone1_avg_density" if z == "z1" else f"{'zone'+z[1:]}_avg_density"] = avg_count / area
        row[f"zone1_max_density" if z == "z1" else f"{'zone'+z[1:]}_max_density"] = max_count / area
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=max(1, os.cpu_count() - 1),
                    help="병렬 워커 수 (기본: CPU 수 - 1)")
    ap.add_argument("--results-dir", default="results")
    ap.add_argument("--save-traj", action="store_true")
    ap.add_argument("--model", choices=["cfsm", "avm"], default="cfsm")
    ap.add_argument("--esc-service-time", type=float, default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--cfg", type=str, default=None,
                    help="cfg 필터 콤마구분 (예: 1,2,3,4)")
    args = ap.parse_args()
    cfg_filter = None
    if args.cfg:
        cfg_filter = {int(c) for c in args.cfg.split(",")}

    results_dir = ROOT / args.results_dir
    raw_dir = results_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    log_path = results_dir / "execution_log.txt"

    def log(msg):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    log(f"병렬 모드: workers={args.workers}, model={args.model}")

    scenarios = list(iter_scenarios())
    if cfg_filter is not None:
        scenarios = [(sid, p) for sid, p in scenarios if p["_config"] in cfg_filter]
    if args.limit:
        scenarios = scenarios[:args.limit]

    # 이미 존재하는 시나리오 SKIP (--save-traj 면 trajectory도 있어야 SKIP)
    todo = []
    skipped = 0
    for sid, params in scenarios:
        agent_csv = raw_dir / f"agents_{sid}.csv"
        zone_csv = raw_dir / f"zones_{sid}.csv"
        traj_csv = raw_dir / f"trajectory_{sid}.csv"
        base_done = agent_csv.exists() and zone_csv.exists()
        if base_done and (not args.save_traj or traj_csv.exists()):
            skipped += 1
            continue
        todo.append((sid, params))
    log(f"전체 {len(scenarios)}개 중 SKIP {skipped}, 실행 {len(todo)}")

    rows = []
    ok = failed = 0
    t_start = time.time()

    # 워커 인자 준비
    worker_args = [
        (sid, params, str(raw_dir), args.model, args.esc_service_time, args.save_traj)
        for sid, params in todo
    ]

    # 진행 상황 출력 주기
    last_log_t = time.time()

    with ProcessPoolExecutor(max_workers=args.workers, initializer=_worker_init) as ex:
        futures = {ex.submit(_run_scenario_worker, wa): (sid, params)
                   for wa, (sid, params) in zip(worker_args, todo)}
        completed = 0
        for fut in as_completed(futures):
            sid, params = futures[fut]
            completed += 1
            try:
                result = fut.result()
                if result[0] == "ok":
                    _, sid_r, wall, spawned, passed, stats = result
                    log(f"[{completed}/{len(todo)}] {sid_r}: OK ({wall:.1f}s, spawn={spawned}, pass={passed})")
                    row = aggregate_summary_row(sid_r, params, stats, spawned, passed, raw_dir)
                    rows.append(row)
                    ok += 1
                else:
                    _, sid_r, wall, err, tb, _ = result
                    log(f"[{completed}/{len(todo)}] {sid_r}: FAIL - {err}")
                    failed += 1
            except Exception as e:
                log(f"[{completed}/{len(todo)}] {sid}: WORKER EXCEPTION - {e}")
                failed += 1

            # 진행 상황 5초마다 요약
            if time.time() - last_log_t > 10:
                elapsed = time.time() - t_start
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (len(todo) - completed) / rate if rate > 0 else 0
                log(f"  진행: {completed}/{len(todo)}, 경과 {elapsed:.0f}s, ETA {eta:.0f}s")
                last_log_t = time.time()

    # SKIP 된 것도 summary 재집계
    for sid, params in scenarios:
        if (raw_dir / f"agents_{sid}.csv").exists() and not any(r["scenario_id"] == sid for r in rows):
            try:
                row = aggregate_summary_row(sid, params, {"gate_counts": [0]}, 0, 0, raw_dir)
                rows.append(row)
            except Exception:
                pass

    summary_csv = results_dir / "summary.csv"
    if rows:
        with open(summary_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        log(f"summary.csv 생성: {len(rows)} 행 -> {summary_csv}")

    elapsed = time.time() - t_start
    log(f"종료: 성공 {ok}, 스킵 {skipped}, 실패 {failed}, 총 {elapsed:.1f}s")


if __name__ == "__main__":
    main()
