from pathlib import Path

p = Path('site/index.html')
s = p.read_text(encoding='utf-8')

repls = [
    ('✅ ALARM · STABILITY 2', '⏰ ALARM · CLOCK UI 1.2'),
    ('✨ COMBO · QUALITY GAMES 2.0 FINAL', '✨ COMBO · QUALITY GAMES 2.0 FINAL + CLOCK'),
]
for old, new in repls:
    if old not in s:
        raise SystemExit(f'clock page marker not found: {old}')
    s = s.replace(old, new, 1)

alarm_marker = '<p class="ok">✓ 30초 무조작 시 시계 · 수면 상태와 시계 화면 완전 분리</p>'
alarm_add = alarm_marker + (
    '<p class="ok">✓ 시계 배터리 표시 중앙 정렬 · 충전 중 CHG / USB 전원 표시</p>'
    '<p class="ok">✓ 낮/밤 투톤 시계 디자인 · 날짜/요일/알람 표시 재배치</p>'
)
if alarm_marker not in s:
    raise SystemExit('alarm clock feature marker not found')
s = s.replace(alarm_marker, alarm_add, 1)

combo_marker = '<p class="ok">✓ PWR 짧게 게임↔시계 · 30초 자동 시계 · 수면 상태 유지</p>'
combo_add = combo_marker + (
    '<p class="ok">✓ 시계 배터리 표시 중앙 정렬 · 충전 중 CHG / USB 전원 표시</p>'
    '<p class="ok">✓ 새 대기 시계 UI: 낮/밤 투톤 · 큰 시간 · 중앙 날짜/요일 · 알람 표시</p>'
)
if combo_marker not in s:
    raise SystemExit('combo clock feature marker not found')
s = s.replace(combo_marker, combo_add, 1)

p.write_text(s, encoding='utf-8')
print('installer page updated for clock UI 1.2')
