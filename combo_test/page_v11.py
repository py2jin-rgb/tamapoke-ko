from pathlib import Path

p = Path('site/index.html')
s = p.read_text(encoding='utf-8')

repls = [
    ('🧪 NEW TEST · COMBO v1.0', '🧪 NEW TEST · COMBO v1.1'),
    ('③ 안정판 + 알람 + 한글 천지인</h2>', '③ 안정판 + 알람 + 한글 천지인 + 낮/밤 대기</h2>'),
    ('manifest-combo.json?v=combo10', 'manifest-combo.json?v=combo11'),
]
for old, new in repls:
    if old not in s:
        raise SystemExit(f'page marker not found: {old}')
    s = s.replace(old, new, 1)

marker = '<p class="ok">✓ 전체 현대 한글 음절 표시용 폴백 글꼴 포함</p>'
add = marker + '<p class="ok">✓ 대기 시계 06:00~19:59: 해 표시 + 포켓몬 깨어서 좌우 걷기</p><p class="ok">✓ 대기 시계 20:00~05:59: 달 + 수면 + Zzz...</p>'
if marker not in s:
    raise SystemExit('combo feature marker not found')
s = s.replace(marker, add, 1)

p.write_text(s, encoding='utf-8')
print('installer page updated for combo v1.1 day/night standby')
