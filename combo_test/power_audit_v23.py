from pathlib import Path
import re
import subprocess

root = Path('source_combo/TamaPoke')
patterns = re.compile(r'(screenOff|lastInteract|standby|brightness|bright|backlight|displayOff|displayOn|sleep|WiFi|Bluetooth|btStop|SD\.begin|SD\.open|setBrightness|setBacklight|gfx->flush|pwrShortPressed|touch)', re.I)
out=[]

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
    out.append(f'===== POWER AUDIT {p.name} =====')
    shown=set()
    for i in hits:
        for j in range(max(0,i-3), min(len(lines),i+4)):
            if j in shown: continue
            shown.add(j)
            out.append(f'{j+1:05d}: {lines[j]}')
        out.append('---')
out.append('===== END POWER AUDIT =====')
text='\n'.join(out)+'\n'
print(text)
site=Path('site')
site.mkdir(exist_ok=True)
(site/'power-audit.txt').write_text(text,encoding='utf-8')

# Apply the first safe Battery Edition pass only after auditing the exact final
# v2.2.4 generated source.
subprocess.run(['python3','combo_test/power_save_v23.py'],check=True)

# Battle 2.4 is generated after this script. Patch its generator against the
# final polished arcade menu so the battle entry is actually reachable while
# preserving Tetris, Snake, and Minesweeper.
subprocess.run(['python3','combo_test/battle_menu_fix_v241.py'],check=True)
