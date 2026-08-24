from pathlib import Path
import re

root = Path('source_combo/TamaPoke')
patterns = re.compile(r'(screenOff|lastInteract|standby|brightness|bright|backlight|displayOff|displayOn|sleep|WiFi|Bluetooth|btStop|SD\.begin|SD\.open|setBrightness|setBacklight|gfx->flush|pwrShortPressed|touch)', re.I)

for p in sorted(root.glob('*')):
    if p.suffix.lower() not in {'.ino','.cpp','.h'}:
        continue
    try:
        lines = p.read_text(encoding='utf-8', errors='replace').splitlines()
    except Exception:
        continue
    hits = [i for i, line in enumerate(lines) if patterns.search(line)]
    if not hits:
        continue
    print(f'===== POWER AUDIT {p.name} =====')
    shown=set()
    for i in hits:
        for j in range(max(0,i-3), min(len(lines),i+4)):
            if j in shown: continue
            shown.add(j)
            print(f'{j+1:05d}: {lines[j]}')
        print('---')
print('===== END POWER AUDIT =====')
