# Audio lifecycle tests

Run `python3 tests/audio/run.py` from any working directory (requires g++ and
Python 3). The test builds the production `firmware/TamaPoke/audio.cpp`, runs
its actual audio worker on a host thread, and mocks only the platform edges.

Checks cover TX-only allocation, release after idle, codec suspend writes,
queued effects and alarms arriving after a successful sleep reservation,
cancelled sleep, game-mute versus alarm behavior, volume 0, and recovery from
injected I2S init/enable/write and codec-transaction failures. The mock rejects
an RX channel, concurrent/leaked TX channels, deleting enabled channels, and
writes to a stopped channel.

These tests do not measure real power, verify analog audio/pop behavior, or
replace an ESP32 build and touch/alarm/sleep wake tests on the target board.
The hardware code targets Arduino-ESP32 3.1.0 (ESP-IDF 5.3.x), whose I2C HAL
serializes transactions on the existing Wire0 bus. Codec reads use private
buffers so another core's RTC/PMU reads cannot overwrite the audio result.
