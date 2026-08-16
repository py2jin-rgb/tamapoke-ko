from pathlib import Path
import sys


def extract_window(text, keyword, before=18, after=45):
    lines = text.splitlines()
    hits = [i for i, line in enumerate(lines) if keyword in line]
    out = []
    for i in hits[:8]:
        lo = max(0, i - before)
        hi = min(len(lines), i + after + 1)
        out.append(f"--- {keyword} @ line {i+1} ---")
        out.extend(f"{n+1:05d}: {lines[n]}" for n in range(lo, hi))
    return "\n".join(out) if out else f"--- {keyword}: NOT FOUND ---"


def scan(root: Path):
    ino = (root / "TamaPoke.ino").read_text(encoding="utf-8", errors="replace")
    pet = (root / "pet.cpp").read_text(encoding="utf-8", errors="replace")
    keys = [
        "drawCelebration",
        "standby",
        "Standby",
        "lastInteract",
        "sleeping",
        "toggleLight",
        "handleTouch",
        "renderStandby",
        "drawAlarmPet",
    ]
    chunks = [f"========== {root} =========="]
    for k in keys:
        chunks.append(extract_window(ino, k))
    chunks.append("===== pet.cpp toggle/sleep =====")
    for k in ("toggleLight", "sleeping"):
        chunks.append(extract_window(pet, k, 15, 35))
    return "\n\n".join(chunks)


if len(sys.argv) != 5:
    raise SystemExit("usage: debug_stability.py stable alarm combo output")

stable, alarm, combo, out = map(Path, sys.argv[1:])
Path(out).write_text("\n\n".join(scan(p) for p in (stable, alarm, combo)), encoding="utf-8")
print(f"wrote {out}")
