#!/usr/bin/env python3
"""Compile the actual audio.cpp against a threaded FreeRTOS/I2S test backend."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix="tamapoke-audio-test-") as work:
    exe = Path(work) / "test_audio"
    subprocess.run([
        "g++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-pthread",
        "-I", str(root / "tests/audio/mocks"),
        "-I", str(root / "firmware/TamaPoke"),
        str(root / "tests/audio/test_audio.cpp"),
        str(root / "firmware/TamaPoke/audio.cpp"),
        "-o", str(exe),
    ], check=True)
    subprocess.run([str(exe)], check=True, timeout=30)
