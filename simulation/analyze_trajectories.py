"""
궤적 자동 분석 스크립트
- 역행(backtracking), 뭉침(clumping), 큐 미진입 정체 감지
- 파라미터 튜닝 루프에서 사용
"""
import csv, sys, json
from collections import defaultdict

sys.path.insert(0, 'simulation')
try:
    from seongsu_west import GATE_X
except:
    GATE_X = 12.0

TRAJ_FILE = "output/trajectories.csv"
QUEUE_HEAD_X = GATE_X - 0.3


def load_trajectories():
    agents = defaultdict(list)
    with open(TRAJ_FILE) as f:
        for r in csv.DictReader(f):
            agents[r['agent_id']].append((
                float(r['time']), float(r['x']), float(r['y']),
                r['state'], int(r['gate_idx'])
            ))
    for aid in agents:
        agents[aid].sort()
    return agents


def detect_backtracking(agents):
    """x 역행 감지. ID 재사용(큰 점프) 제외."""
    results = []
    for aid, traj in agents.items():
        for i in range(1, len(traj)):
            dx = traj[i][1] - traj[i-1][1]
            dt = traj[i][0] - traj[i-1][0]
            # ID 재사용: x가 5m 이상 순간 점프 → 제외
            if abs(dx) > 5.0 and dt < 1.0:
                continue
            if dx < -0.3 and traj[i][3] == 'moving':
                results.append({
                    'agent': aid,
                    'time': traj[i][0],
                    'x_from': traj[i-1][1],
                    'x_to': traj[i][1],
                    'dx': dx,
                    'y': traj[i][2],
                })
    return results


def detect_stalling(agents, zone_start=GATE_X-5.0, zone_end=GATE_X,
                    min_duration=5.0, state_filter='moving'):
    """게이트 접근 구역에서 moving 상태로 장기 정체 감지."""
    results = []
    for aid, traj in agents.items():
        i = 0
        while i < len(traj):
            t0, x0, y0, st0, gi0 = traj[i]
            if st0 == state_filter and zone_start < x0 < zone_end:
                j = i + 1
                while j < len(traj):
                    if traj[j][3] != state_filter:
                        break
                    if not (zone_start - 0.5 < traj[j][1] < zone_end):
                        break
                    j += 1
                duration = traj[min(j, len(traj)-1)][0] - t0
                if duration >= min_duration:
                    results.append({
                        'agent': aid,
                        't_start': t0,
                        'duration': duration,
                        'x': x0,
                        'y': y0,
                        'gate': gi0,
                    })
                i = j
            else:
                i += 1
    return results


def detect_clumping(agents, x_bin=0.5, t_bin=5.0, density_thresh=5):
    """특정 x 구간에 동시에 많은 에이전트가 'moving' 상태로 뭉치는 지점 감지."""
    # (t_bin, x_bin) 격자에 에이전트 수 카운트
    grid = defaultdict(set)
    for aid, traj in agents.items():
        for t, x, y, st, gi in traj:
            if st == 'moving' and 6.0 < x < GATE_X:
                tb = int(t / t_bin)
                xb = int(x / x_bin)
                grid[(tb, xb)].add(aid)
    hot = [(k, len(v)) for k, v in grid.items() if len(v) >= density_thresh]
    hot.sort(key=lambda z: -z[1])
    return [{'t_bin': k[0]*t_bin, 'x_center': k[1]*x_bin + x_bin/2,
             'count': n} for k, n in hot[:20]]



def score(backtrack, stall, clump):
    bt_score  = min(100, len(backtrack))          # 역행 건수
    st_score  = min(100, sum(s['duration'] for s in stall) / max(len(stall), 1))  # 평균 정체 시간
    cl_score  = clump[0]['count'] if clump else 0  # 최대 동시 밀집
    total = bt_score * 0.3 + st_score * 0.5 + cl_score * 0.2
    return {'backtrack_n': len(backtrack), 'stall_n': len(stall),
            'stall_avg_dur': round(st_score, 1),
            'clump_max': cl_score, 'total_penalty': round(total, 1)}


def main():
    agents = load_trajectories()
    bt = detect_backtracking(agents)
    st = detect_stalling(agents)
    cl = detect_clumping(agents)
    sc = score(bt, st, cl)

    print("=" * 50)
    print("궤적 품질 분석")
    print("=" * 50)
    print(f"역행(backtracking): {sc['backtrack_n']}건")
    if bt:
        worst = sorted(bt, key=lambda x: x['dx'])[:3]
        for w in worst:
            print(f"  agent {w['agent']}: {w['x_from']:.2f}→{w['x_to']:.2f}m "
                  f"({w['dx']:.2f}m) @ t={w['time']:.1f}s")

    print(f"\n접근구역 정체(moving, 5초+): {sc['stall_n']}건, 평균 {sc['stall_avg_dur']:.1f}초")
    if st:
        worst_st = sorted(st, key=lambda x: -x['duration'])[:3]
        for w in worst_st:
            print(f"  agent {w['agent']}: x={w['x']:.2f}, {w['duration']:.1f}초 @ t={w['t_start']:.1f}s")

    print(f"\n동시 밀집(clumping): 최대 {sc['clump_max']}명")
    if cl:
        for c in cl[:3]:
            print(f"  t~{c['t_bin']:.0f}s, x~{c['x_center']:.1f}m: {c['count']}agents")

    print(f"\n종합 페널티 점수: {sc['total_penalty']} (낮을수록 좋음)")
    return sc


if __name__ == '__main__':
    main()
