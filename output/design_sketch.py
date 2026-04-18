"""
성수역 서쪽 공간 확장 설계 v4 — 승강장 겹침 반영.
"""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import pathlib

plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

fig, ax = plt.subplots(1, 1, figsize=(18, 12))

# 대합실 (2F) — 승강장 3F와 같은 영역에 겹침
ax.add_patch(mpatches.Rectangle(
    (0, 0), 50, 25, facecolor='#FFF3E0', edgecolor='#E65100',
    linewidth=2, alpha=0.6))
ax.text(38, 20, '대합실 (2F) 50×25\n+ 승강장 (3F) 겹침',
        ha='center', va='center', fontsize=11, fontweight='bold', color='#E65100')

# 게이트 7개
for i in range(7):
    g_y = 9.95 + i * 0.85
    ax.add_patch(mpatches.Rectangle(
        (12, g_y - 0.28), 1.5, 0.55, facecolor='#4CAF50', alpha=0.7))
ax.text(13, 18.5, '게이트 7 (x=12, 기존)', fontsize=9, color='#1B5E20')

# 계단 a (upper, 뚝섬 방향): x=1~11, y=15~18 (가로 통로)
ax.add_patch(mpatches.Rectangle(
    (1, 15), 10, 3, facecolor='#FFCCBC', edgecolor='#D84315',
    linewidth=2, alpha=0.8))
ax.text(6, 16.5, '계단 a (upper, 뚝섬 방향)\nx=1~11, y=15~18',
        ha='center', va='center', fontsize=9, color='#D84315', fontweight='bold')

# 계단 b (lower, 반대 방향): x=1~11, y=8~11
ax.add_patch(mpatches.Rectangle(
    (1, 8), 10, 3, facecolor='#FFCCBC', edgecolor='#D84315',
    linewidth=2, alpha=0.8))
ax.text(6, 9.5, '계단 b (lower, 반대 방향)\nx=1~11, y=8~11',
        ha='center', va='center', fontsize=9, color='#D84315', fontweight='bold')

# 기존 STAIRS = 계단 대합실 쪽 연결부 (x=1 빨간 세로선)
for y_range, lbl in [((15, 18), 'a'), ((8, 11), 'b')]:
    ax.plot([1, 1], y_range, color='red', linewidth=6, solid_capstyle='round')
    ax.text(0.5, (y_range[0] + y_range[1]) / 2, f'연결부\n({lbl})',
            ha='right', va='center', fontsize=7, color='red', fontweight='bold')

# spawn 위치: 계단 x=11 끝 (승강장 쪽)
ax.plot(11, 16.5, 'o', color='#0288D1', markersize=14)
ax.text(11.5, 16.5, 'spawn a\n(x=11, y=15~18)',
        fontsize=8, color='#0288D1', fontweight='bold')
ax.plot(11, 9.5, 'o', color='#0288D1', markersize=14)
ax.text(11.5, 9.5, 'spawn b\n(x=11, y=8~11)',
        fontsize=8, color='#0288D1', fontweight='bold')

# 대합실 우측 구조물
ax.add_patch(mpatches.Rectangle(
    (30, 16), 18, 8, facecolor='#FFE0B2', hatch='///', alpha=0.4))
ax.add_patch(mpatches.Rectangle(
    (30, 3), 18, 8, facecolor='#FFE0B2', hatch='///', alpha=0.4))

# 에스컬 4 (북쪽): x=25~35, y=25~26, 입구 (25,25)
ax.add_patch(mpatches.Rectangle(
    (25, 25), 10, 1, facecolor='#C8E6C9', edgecolor='#2E7D32',
    linewidth=2, alpha=0.8))
ax.text(30, 25.5, '에스컬 4번 (용답) x=25~35, y=25~26',
        ha='center', va='center', fontsize=8, color='#2E7D32', fontweight='bold')
ax.plot(25, 25, 'o', color='blue', markersize=10)
ax.text(23.5, 24, '입구 (25, 25)', fontsize=7, color='blue', ha='right')
ax.plot([35, 35], [25, 26], 'b-', linewidth=4)
ax.text(36, 25.5, 'sink_4', fontsize=9, color='blue', fontweight='bold')

# 에스컬 1 (남쪽): x=25~35, y=-1~0, 입구 (25,0)
ax.add_patch(mpatches.Rectangle(
    (25, -1), 10, 1, facecolor='#C8E6C9', edgecolor='#2E7D32',
    linewidth=2, alpha=0.8))
ax.text(30, -0.5, '에스컬 1번 (뚝섬) x=25~35, y=-1~0',
        ha='center', va='center', fontsize=8, color='#2E7D32', fontweight='bold')
ax.plot(25, 0, 'o', color='blue', markersize=10)
ax.text(23.5, 1, '입구 (25, 0)', fontsize=7, color='blue', ha='right')
ax.plot([35, 35], [-1, 0], 'b-', linewidth=4)
ax.text(36, -0.5, 'sink_1', fontsize=9, color='blue', fontweight='bold')

# 흐름 화살표
# spawn → 계단 → 연결부 (x-)
ax.annotate('', xy=(1.8, 16.5), xytext=(10.5, 16.5),
            arrowprops=dict(arrowstyle='->', color='#D84315', lw=2))
ax.annotate('', xy=(1.8, 9.5), xytext=(10.5, 9.5),
            arrowprops=dict(arrowstyle='->', color='#D84315', lw=2))
# 연결부 → 게이트 (기존 로직)
ax.annotate('', xy=(11.5, 13), xytext=(3, 15),
            arrowprops=dict(arrowstyle='->', color='#E65100', lw=1.5, alpha=0.6))
# 게이트 후 → 에스컬 입구
ax.annotate('', xy=(25, 24.5), xytext=(16, 14),
            arrowprops=dict(arrowstyle='->', color='#2E7D32', lw=1.5, alpha=0.7))
ax.annotate('', xy=(25, 0.5), xytext=(16, 11),
            arrowprops=dict(arrowstyle='->', color='#2E7D32', lw=1.5, alpha=0.7))
# 에스컬 내부 x+
ax.annotate('', xy=(34, 25.5), xytext=(26, 25.5),
            arrowprops=dict(arrowstyle='->', color='#2E7D32', lw=2.5))
ax.annotate('', xy=(34, -0.5), xytext=(26, -0.5),
            arrowprops=dict(arrowstyle='->', color='#2E7D32', lw=2.5))

# 주석
ax.text(55, 23, '설계 v4', fontsize=13, fontweight='bold')
ax.text(55, 21, '• 대합실 = 승강장 (2D 겹침)', fontsize=10, color='#E65100')
ax.text(55, 19, '• 계단 a: x=1~11, y=15~18', fontsize=10, color='#D84315')
ax.text(55, 17.5, '• 계단 b: x=1~11, y=8~11', fontsize=10, color='#D84315')
ax.text(55, 16, '  (모두 승강장 ↔ 대합실)', fontsize=8, color='#D84315')
ax.text(55, 14, '• 에스컬 1: x=25~35, y=-1~0', fontsize=10, color='#2E7D32')
ax.text(55, 12.5, '• 에스컬 4: x=25~35, y=25~26', fontsize=10, color='#2E7D32')
ax.text(55, 11, '  (둘 다 밖으로 나가는 출구)', fontsize=8, color='#2E7D32')

ax.text(55, 8, '에이전트 동선:', fontsize=11, fontweight='bold')
ax.text(55, 6.5, '1. spawn at 계단 a 또는 b\n   (x=11 승강장쪽 끝)', fontsize=9)
ax.text(55, 4, '2. 계단 내부 x↓ 이동 → STAIRS(x=1)', fontsize=9)
ax.text(55, 2.5, '3. [기존] 게이트 선택·통과', fontsize=9)
ax.text(55, 1, '4. 출구 1/4 선택 (50:50)', fontsize=9)
ax.text(55, -0.5, '5. 에스컬 입구로 y 이동 후 x+ → sink', fontsize=9)

ax.text(55, -3, '파라미터:', fontsize=11, fontweight='bold')
ax.text(55, -4.5, '• 계단 속도 0.6 m/s', fontsize=9)
ax.text(55, -6, '• 에스컬 속도 0.5 m/s', fontsize=9)

ax.set_xlim(-3, 88)
ax.set_ylim(-10, 28)
ax.set_aspect('equal')
ax.grid(True, alpha=0.3, linestyle=':')
ax.set_xlabel('x (m)')
ax.set_ylabel('y (m)')
ax.set_title('성수역 서쪽 공간 확장 설계 v4 (승강장 겹침)',
             fontsize=14, fontweight='bold')

plt.tight_layout()
out_path = pathlib.Path(__file__).parent / "design_sketch_v4.png"
fig.savefig(str(out_path), dpi=120, bbox_inches='tight')
print(f"Saved: {out_path}")
