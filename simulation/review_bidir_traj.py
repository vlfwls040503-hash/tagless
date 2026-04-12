# -*- coding: utf-8 -*-
"""
양방향 시뮬레이션 궤적 개별 리뷰
- 각 kind별로 샘플 에이전트 선정
- 시간순 (x, y, state) 추적, 보행 패턴 검증
- 역행/jump/큐 합류 패턴 자동 체크
"""
import csv
import sys
import pathlib
from collections import defaultdict
import numpy as np

CSV = pathlib.Path(__file__).parent.parent / 'output' / 'trajectories_bidir.csv'

GATE_X = 12.0
GATE_LENGTH = 1.5

def load():
    agents = defaultdict(list)
    with open(CSV) as f:
        for r in csv.DictReader(f):
            agents[r['agent_id']].append({
                't': float(r['time']),
                'x': float(r['x']),
                'y': float(r['y']),
                'gate': int(r['gate_idx']),
                'state': r['state'],
                'kind': r['kind'],
            })
    for aid in agents:
        agents[aid].sort(key=lambda r: r['t'])
    return agents

def analyze_one(aid, traj):
    """한 에이전트의 궤적을 분석. 이상 패턴 리포트 반환."""
    issues = []
    if len(traj) < 2:
        return ['too short']

    kind = traj[0]['kind']
    states = [r['state'] for r in traj]
    xs = [r['x'] for r in traj]
    ys = [r['y'] for r in traj]
    ts = [r['t'] for r in traj]

    # 1. 진행방향 일관성
    if kind == 'out':
        # x 단조 증가가 정상 (좌 → 우)
        x_diffs = np.diff(xs)
        # 큐 진입(이전 moving → queue 전환)에서는 점프 가능
        backward_count = 0
        for i in range(1, len(traj)):
            if traj[i]['state'] == 'moving' and traj[i-1]['state'] == 'moving':
                if xs[i] < xs[i-1] - 0.2:
                    backward_count += 1
        if backward_count > 0:
            issues.append(f'역행 {backward_count}회 (out)')
    else:  # in
        backward_count = 0
        for i in range(1, len(traj)):
            if traj[i]['state'] == 'moving' and traj[i-1]['state'] == 'moving':
                if xs[i] > xs[i-1] + 0.2:
                    backward_count += 1
        if backward_count > 0:
            issues.append(f'역행 {backward_count}회 (in)')

    # 2. 큐 합류 검증: queue 상태에서 머문 동안 위치 거의 변화 없음 (visual_x만 변동)
    queue_recs = [(r['x'], r['y']) for r in traj if r['state'] == 'queue']
    if queue_recs:
        qxs = [q[0] for q in queue_recs]
        qys = [q[1] for q in queue_recs]
        # 큐 내 y 변화 (작아야 정상)
        if len(qys) > 1:
            y_var = max(qys) - min(qys)
            if y_var > 0.5:
                issues.append(f'큐 내 y변동 {y_var:.2f}m')

    # 3. moving → queue 전환 시 점프 거리
    transitions = []
    for i in range(1, len(traj)):
        if traj[i-1]['state'] == 'moving' and traj[i]['state'] == 'queue':
            jump = abs(traj[i]['x'] - traj[i-1]['x'])
            transitions.append(jump)
    if transitions:
        max_jump = max(transitions)
        if max_jump > 1.5:
            issues.append(f'큐 합류 점프 {max_jump:.2f}m')

    # 4. 큐 wp 도달 못 했는지
    if kind == 'out':
        # 정상이면 마지막 x가 GATE_X+ (통과) 또는 큐(GATE_X-)
        last_x = xs[-1]
        if last_x < GATE_X - 5:
            issues.append(f'미진입: 마지막 x={last_x:.1f}')
    else:
        last_x = xs[-1]
        if last_x > GATE_X + GATE_LENGTH + 5:
            issues.append(f'미진입: 마지막 x={last_x:.1f}')

    return issues

def print_traj(aid, traj, max_rows=20):
    """에이전트 궤적 시간순 출력 (상태 전환 포인트 위주)"""
    n = len(traj)
    # 상태 전환 지점 찾기
    transitions = [0]
    for i in range(1, n):
        if traj[i]['state'] != traj[i-1]['state'] or traj[i]['gate'] != traj[i-1]['gate']:
            transitions.append(i)
    transitions.append(n - 1)
    # 중복 제거
    transitions = sorted(set(transitions))[:max_rows]

    print(f"\n  agent {aid} ({traj[0]['kind']}, {n} 레코드)")
    print(f"  {'t':>7s} {'x':>6s} {'y':>6s} {'gate':>5s} {'state':>8s}")
    for i in transitions:
        r = traj[i]
        print(f"  {r['t']:7.1f} {r['x']:6.2f} {r['y']:6.2f} {r['gate']:5d} {r['state']:>8s}")

def main():
    agents = load()
    print(f"전체 에이전트: {len(agents)}")

    out_agents = [aid for aid, tr in agents.items() if tr[0]['kind'] == 'out']
    in_agents  = [aid for aid, tr in agents.items() if tr[0]['kind'] == 'in']
    print(f"  하차: {len(out_agents)}, 승차: {len(in_agents)}")

    # 전체 자동 검증
    all_issues = defaultdict(int)
    issue_examples = defaultdict(list)
    for aid, tr in agents.items():
        issues = analyze_one(aid, tr)
        for iss in issues:
            key = iss.split(' ')[0]
            all_issues[key] += 1
            if len(issue_examples[key]) < 3:
                issue_examples[key].append((aid, iss))

    print("\n[자동 검증 요약]")
    if not all_issues:
        print("  이상 없음")
    else:
        for k, n in sorted(all_issues.items(), key=lambda x: -x[1]):
            print(f"  {k}: {n}건")
            for aid, iss in issue_examples[k]:
                print(f"      예: agent {aid}: {iss}")

    # 샘플 개별 출력 (각 종류 5명씩)
    print("\n" + "=" * 60)
    print("샘플 궤적 (하차 5명)")
    print("=" * 60)
    for aid in out_agents[::max(1, len(out_agents)//5)][:5]:
        print_traj(aid, agents[aid], max_rows=15)

    print("\n" + "=" * 60)
    print("샘플 궤적 (승차 5명)")
    print("=" * 60)
    for aid in in_agents[::max(1, len(in_agents)//5)][:5]:
        print_traj(aid, agents[aid], max_rows=15)

if __name__ == '__main__':
    main()
