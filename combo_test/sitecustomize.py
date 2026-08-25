"""Narrow CI source hotfix for Battle 2.4.

Python imports sitecustomize before executing scripts from this directory.  Only
battle_v24.py is touched: the ESP-NOW packet payload itself does not need to be
volatile; the volatile pending flag remains the cross-callback signal.  This
keeps the generated C++ copyable under Arduino-ESP32 3.1.0.
"""
from pathlib import Path
import sys

if sys.argv and Path(sys.argv[0]).name == "battle_v24.py":
    p = Path(sys.argv[0])
    try:
        s = p.read_text(encoding="utf-8")
        old = "static volatile BattlePacket battleRx;"
        new = "static BattlePacket battleRx;"
        if old in s:
            p.write_text(s.replace(old, new, 1), encoding="utf-8")
    except OSError:
        pass
