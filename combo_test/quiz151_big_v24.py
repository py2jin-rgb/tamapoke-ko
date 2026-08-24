from pathlib import Path
import re, sys

root=Path(sys.argv[1])
p=root/'TamaPoke.ino'
s=p.read_text(encoding='utf-8')
old='if (miniOpponentPmd.loaded) drawPmdActM(miniOpponentPmd, PMD_IDLE, CX, 276, now, true, false, 3);'
new='if (miniOpponentPmd.loaded) drawPmdActM(miniOpponentPmd, PMD_IDLE, CX, 302, now, true, false, 5);'
if old not in s:
    raise SystemExit('quiz151 big sprite marker missing')
s=s.replace(old,new,1)
# Master/clear screen can also show a larger celebration sprite, but keep it inside the circle.
old2='if (miniOpponentPmd.loaded) drawPmdActM(miniOpponentPmd, PMD_IDLE, CX, 348, now, true, false, 3);'
new2='if (miniOpponentPmd.loaded) drawPmdActM(miniOpponentPmd, PMD_IDLE, CX, 360, now, true, false, 4);'
if old2 in s:
    s=s.replace(old2,new2,1)
p.write_text(s,encoding='utf-8')
print('151 quiz Pokemon artwork enlarged: question 3x -> 5x, master 3x -> 4x')
