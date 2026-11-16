#include "audio.h"
#include "pin_config.h"
#include <Arduino.h>
#include <Preferences.h>
#include <driver/i2s_std.h>
#include <esp32-hal-i2c.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <string.h>

// Only audioTask touches the codec, I2S channel and PA after audioBegin().
// Shared state is protected by a short spinlock; no I2C, I2S, NVS, delay or
// notification calls are made while that lock is held. Use the existing
// Wire / I2C0 bus through Arduino-ESP32's locked HAL, with private read buffers:
// Wire.requestFrom() releases its mutex before Wire.read(), so sharing that
// RX buffer with RTC/PMU reads on the other core would otherwise be unsafe.
// Do not reinitialize the bus or change its pins here.
#if defined(CONFIG_DISABLE_HAL_LOCKS) && CONFIG_DISABLE_HAL_LOCKS
#error "TamaPoke audio requires Arduino I2C HAL locks on the shared bus"
#endif
static constexpr uint8_t ES8311_ADDR = 0x18;
static constexpr uint8_t CODEC_I2C_BUS = 0; // Global Wire in this board's setup().
static constexpr uint32_t CODEC_I2C_TIMEOUT_MS = 50;
static constexpr uint32_t SAMPLE_RATE = 16000;
static constexpr uint8_t QUEUE_CAPACITY = 12;
static constexpr uint32_t IDLE_OFF_MS = 150;
static constexpr uint32_t RETRY_MS = 1000;
static constexpr size_t DMA_FRAMES = 128;
static constexpr size_t DMA_BUFFERS = 4;

static portMUX_TYPE gStateMux = portMUX_INITIALIZER_UNLOCKED;
static TaskHandle_t gTask = nullptr;
static bool gReady = false;
static bool gOn = true;
static uint8_t gVolumePct = 100;
static bool gAlarmActive = false;
static bool gInFlight = false;
static bool gHardwareOn = false;
static bool gInitialSuspend = true;
static bool gForceIdle = false;
static bool gSleepArmed = false;
static uint32_t gLastUsed = 0;
static uint8_t gQueue[QUEUE_CAPACITY];
static uint8_t gHead = 0, gCount = 0;

// These are private to audioTask. The explicit channel lifecycle also handles
// partial initialization failures which ESP_I2S::end() in core 3.1.0 cannot
// reliably unwind when a channel has not yet reached the enabled state.
static i2s_chan_handle_t gTx = nullptr;
static bool gTxEnabled = false;
static bool gCodecTouched = false;
static bool gIoFailed = false;

static void notifyAudio() {
  TaskHandle_t task;
  portENTER_CRITICAL(&gStateMux);
  task = gTask;
  portEXIT_CRITICAL(&gStateMux);
  if (task) xTaskNotifyGive(task);
}

static bool esW(uint8_t reg, uint8_t val) {
  const uint8_t data[] = {reg, val};
  return i2cWrite(CODEC_I2C_BUS, ES8311_ADDR, data, sizeof(data), CODEC_I2C_TIMEOUT_MS) == ESP_OK;
}

static bool esR(uint8_t reg, uint8_t &val) {
  size_t received = 0;
  esp_err_t err = i2cWriteReadNonStop(CODEC_I2C_BUS, ES8311_ADDR, &reg, 1,
                                   &val, 1, CODEC_I2C_TIMEOUT_MS, &received);
  return err == ESP_OK && received == 1;
}

static bool codecPresent() {
  const uint8_t unused = 0;
  return i2cWrite(CODEC_I2C_BUS, ES8311_ADDR, &unused, 0, CODEC_I2C_TIMEOUT_MS) == ESP_OK;
}

struct RegValue { uint8_t reg, value; };
static bool writeRegisters(const RegValue *items, size_t count) {
  bool ok = true;
  for (size_t i = 0; i < count; ++i) {
    // Continue the shutdown sequence even if one transaction fails.
    if (!esW(items[i].reg, items[i].value)) ok = false;
  }
  return ok;
}

// Preserve the board-proven BCLK-derived, 16 kHz stereo configuration.
// All bus failures are checked before enabling the external amplifier.
static bool es8311Init() {
  if (!codecPresent()) return false;
  gCodecTouched = true;
  bool ok = esW(0x0D, 0xFA);
  esW(0x44, 0x08); // Espressif workaround: the first noise-immunity write can fail.
  if (!esW(0x44, 0x08)) ok = false;
  static const RegValue setup[] = {
    {0x01,0x30}, {0x02,0x00}, {0x03,0x10}, {0x16,0x24},
    {0x04,0x10}, {0x05,0x00}, {0x0B,0x00}, {0x0C,0x00},
    {0x10,0x1F}, {0x11,0x7F}, {0x00,0x80}, {0x00,0x80},
    {0x01,0xBF}
  };
  if (!writeRegisters(setup, sizeof(setup) / sizeof(setup[0]))) ok = false;
  uint8_t r = 0;
  if (!esR(0x06, r) || !esW(0x06, r & ~0x20)) ok = false;
  static const RegValue sample[] = {
    {0x13,0x10}, {0x1B,0x0A}, {0x1C,0x6A}, {0x44,0x58},
    {0x02,0x18}, {0x05,0x00}, {0x03,0x10}, {0x04,0x20}
  };
  if (!writeRegisters(sample, sizeof(sample) / sizeof(sample[0]))) ok = false;
  if (!esR(0x07, r) || !esW(0x07, r & 0xC0)) ok = false;
  if (!esW(0x08, 0xFF)) ok = false;
  if (!esR(0x06, r) || !esW(0x06, (r & 0xE0) | 0x03)) ok = false;
  static const RegValue start[] = {
    {0x09,0x0C}, {0x0A,0x0C}, {0x00,0x80}, {0x01,0xBF},
    {0x09,0x0C}, {0x0A,0x0C}, {0x17,0xBF}, {0x0E,0x02},
    {0x12,0x00}, {0x14,0x1A}, {0x0D,0x01}, {0x15,0x40},
    {0x37,0x08}, {0x45,0x00}, {0x32,0xBF}
  };
  if (!writeRegisters(start, sizeof(start) / sizeof(start[0]))) ok = false;
  if (!esR(0x31, r) || !esW(0x31, r & 0x9F)) ok = false;
  return ok;
}

static bool es8311Suspend() {
  // Register order from Espressif esp_codec_dev es8311_suspend/power_down:
  // github.com/espressif/esp-adf/blob/master/components/esp_codec_dev/device/es8311/es8311.c
  // Keep PA low before muting/powering down, and keep I2S clocks until this ends.
  static const RegValue stop[] = {
    {0x32,0x00}, {0x17,0x00}, {0x0E,0xFF}, {0x12,0x02},
    {0x14,0x00}, {0x0D,0xFA}, {0x15,0x00}, {0x02,0x10},
    {0x00,0x00}, {0x00,0x1F}, {0x01,0x30}, {0x01,0x00},
    {0x45,0x00}, {0x0D,0xFC}, {0x02,0x00}
  };
  return writeRegisters(stop, sizeof(stop) / sizeof(stop[0]));
}

static void publishHardware() {
  portENTER_CRITICAL(&gStateMux);
  gHardwareOn = (gTx != nullptr);
  portEXIT_CRITICAL(&gStateMux);
}

static bool hardwareStop(bool probeCodec = false) {
  digitalWrite(PA, LOW);
  if (gCodecTouched || (probeCodec && codecPresent())) {
    if (!es8311Suspend()) Serial.println("AUDIO codec suspend I2C error");
    gCodecTouched = false; // A subsequent cue always restores the full configuration.
  }
  if (gTx && gTxEnabled) {
    esp_err_t err = i2s_channel_disable(gTx);
    if (err == ESP_OK || err == ESP_ERR_INVALID_STATE) gTxEnabled = false;
    else Serial.printf("AUDIO I2S disable error=%d\n", (int)err);
  }
  if (gTx && !gTxEnabled) {
    esp_err_t err = i2s_del_channel(gTx);
    if (err == ESP_OK) gTx = nullptr;
    else Serial.printf("AUDIO I2S delete error=%d\n", (int)err);
  }
  publishHardware();
  return gTx == nullptr;
}

static bool hardwareStart() {
  if (gTx && gTxEnabled && gCodecTouched) return true;
  if (gTx && !hardwareStop()) return false;
  digitalWrite(PA, LOW);
  i2s_chan_config_t channel = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_AUTO, I2S_ROLE_MASTER);
  channel.dma_desc_num = DMA_BUFFERS;
  channel.dma_frame_num = DMA_FRAMES;
  channel.auto_clear = true;
  esp_err_t err = i2s_new_channel(&channel, &gTx, nullptr); // TX only; no microphone RX.
  if (err == ESP_OK) {
    i2s_std_config_t cfg = {};
    cfg.clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(SAMPLE_RATE);
    cfg.slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO);
    cfg.slot_cfg.slot_mask = I2S_STD_SLOT_BOTH;
    cfg.gpio_cfg.mclk = (gpio_num_t)I2S_MCK_IO;
    cfg.gpio_cfg.bclk = (gpio_num_t)I2S_BCK_IO;
    cfg.gpio_cfg.ws = (gpio_num_t)I2S_WS_IO;
    cfg.gpio_cfg.dout = (gpio_num_t)I2S_DO_IO;
    cfg.gpio_cfg.din = I2S_GPIO_UNUSED;
    err = i2s_channel_init_std_mode(gTx, &cfg);
  }
  if (err == ESP_OK) {
    err = i2s_channel_enable(gTx);
    gTxEnabled = (err == ESP_OK);
  }
  publishHardware();
  if (err != ESP_OK || !es8311Init()) {
    Serial.printf("AUDIO start failed (I2S=%d); output off\n", (int)err);
    hardwareStop(); // Includes a codec that was only partly initialized.
    return false;
  }
  return true;
}

// ---- sintetizador de tono cuadrado ----
struct Note { uint16_t f, ms; };

static const Note N_TAP[]    = {{880, 35}};
static const Note N_EAT[]    = {{660, 45}, {0, 12}, {660, 45}};
static const Note N_PLAY[]   = {{784, 45}, {988, 60}};
static const Note N_HEART[]  = {{1047, 55}, {1319, 90}};
static const Note N_HATCH[]  = {{523, 80}, {659, 80}, {784, 110}, {1047, 170}};
static const Note N_EVOLVE[] = {{523, 80}, {659, 80}, {784, 80}, {1047, 90}, {1319, 230}};
static const Note N_MEDAL[]  = {{784, 70}, {0, 25}, {784, 70}, {0, 25}, {1047, 200}};
static const Note N_DENY[]   = {{300, 110}, {200, 170}};
static const Note N_BYE[]    = {{784, 150}, {659, 150}, {523, 280}};
static const Note N_LEVEL[]  = {{784, 70}, {1047, 130}};
static const Note N_ALARM[]  = {{880, 180}, {0, 80}, {1175, 180}, {0, 80}, {880, 180}, {0, 320}};

// Minigame sound pack: short original square-wave cues. Kept intentionally
// compact so rapid touch games stay responsive and do not fill the audio queue.
static const Note N_GAME_OPEN[]  = {{523, 35}, {659, 35}, {784, 55}};
static const Note N_GAME_START[] = {{523, 55}, {659, 55}, {784, 55}, {1047, 90}};
static const Note N_MOLE_H1[]    = {{190, 18}, {720, 28}, {1040, 42}};
static const Note N_MOLE_H2[]    = {{220, 18}, {830, 28}, {1240, 42}};
static const Note N_MOLE_H3[]    = {{260, 18}, {930, 28}, {1480, 44}};
static const Note N_MOLE_MISS[]  = {{220, 55}, {165, 65}};
static const Note N_GAME_TICK[]  = {{1320, 32}};
static const Note N_RPS_SELECT[] = {{620, 28}};
static const Note N_RPS_WIN[]    = {{659, 45}, {831, 45}, {1047, 85}};
static const Note N_RPS_LOSE[]   = {{392, 55}, {330, 55}, {262, 90}};
static const Note N_RPS_DRAW[]   = {{523, 45}, {0, 18}, {523, 60}};
static const Note N_GAME_OVER[]  = {{784, 45}, {659, 45}, {523, 100}};

struct SfxDef { const Note *n; uint8_t len; };
static const SfxDef SFX[SFX_COUNT] = {
  {N_TAP, 1}, {N_EAT, 3}, {N_PLAY, 2}, {N_HEART, 2}, {N_HATCH, 4},
  {N_EVOLVE, 5}, {N_MEDAL, 5}, {N_DENY, 2}, {N_BYE, 3}, {N_LEVEL, 2},
  {N_ALARM, 6},
  {N_GAME_OPEN, 3}, {N_GAME_START, 4},
  {N_MOLE_H1, 3}, {N_MOLE_H2, 3}, {N_MOLE_H3, 3}, {N_MOLE_MISS, 2},
  {N_GAME_TICK, 1}, {N_RPS_SELECT, 1}, {N_RPS_WIN, 3}, {N_RPS_LOSE, 3},
  {N_RPS_DRAW, 3}, {N_GAME_OVER, 3},
};

static int16_t buf[256 * 2]; // Stereo interleaved, L=R; audioTask owns it.

static bool playbackAllowed(bool alarm, uint8_t &volume) {
  portENTER_CRITICAL(&gStateMux);
  volume = gVolumePct;
  bool allowed = alarm ? gAlarmActive : (gOn && !gAlarmActive);
  portEXIT_CRITICAL(&gStateMux);
  return allowed && volume > 0;
}

static bool writePcm(const int16_t *data, size_t frames) {
  size_t written = 0;
  const size_t bytes = frames * 2 * sizeof(int16_t);
  esp_err_t err = i2s_channel_write(gTx, data, bytes, &written, 150);
  if (err != ESP_OK || written != bytes) {
    gIoFailed = true;
    return false;
  }
  return true;
}

static bool silenceDrain() {
  // At least one complete DMA ring of zero frames ensures earlier samples
  // have left the ring before PA is disabled, without clipping short cues.
  memset(buf, 0, sizeof(buf));
  for (size_t left = DMA_BUFFERS * DMA_FRAMES; left; ) {
    size_t n = left > 256 ? 256 : left;
    if (!writePcm(buf, n)) return false;
    left -= n;
  }
  return true;
}

static bool playTone(uint16_t f, uint16_t ms, bool alarm) {
  int total = SAMPLE_RATE * ms / 1000;
  int half = f ? SAMPLE_RATE / (2 * f) : 0;
  int phase = 0, done = 0;
  bool high = true;
  while (done < total) {
    uint8_t volume;
    if (!playbackAllowed(alarm, volume)) return false;
    int16_t amp = (int16_t)(5000L * volume / 100L);
    int n = total - done;
    if (n > 256) n = 256;
    for (int i = 0; i < n; ++i) {
      int16_t sample = 0;
      if (f) {
        sample = high ? amp : -amp;
        int idx = done + i;
        if (idx < 64) sample = (int16_t)(sample * idx / 64);
        else if (idx > total - 96) sample = (int16_t)(sample * (total - idx) / 96);
        if (++phase >= half) { phase = 0; high = !high; }
      }
      buf[i * 2] = sample;
      buf[i * 2 + 1] = sample;
    }
    if (!writePcm(buf, n)) return false;
    done += n;
  }
  return true;
}

static TickType_t waitTicks(uint32_t ms) {
  TickType_t ticks = pdMS_TO_TICKS(ms);
  return ticks ? ticks : 1;
}

static void audioTask(void *) {
  uint32_t retryAt = 0;
  for (;;) {
    uint8_t id = SFX_COUNT;
    bool suspend = false, initialSuspend = false;
    TickType_t wait = portMAX_DELAY;
    const uint32_t now = millis();

    portENTER_CRITICAL(&gStateMux);
    if (!gSleepArmed) {
      if (gInitialSuspend) {
        suspend = initialSuspend = true;
        gInFlight = true;
      } else if (gAlarmActive && gVolumePct > 0) {
        id = SFX_ALARM;
        gInFlight = true;
      } else if (gCount) {
        id = gQueue[gHead];
        gHead = (gHead + 1) % QUEUE_CAPACITY;
        --gCount;
        if (!gOn || !gVolumePct) id = SFX_COUNT;
        else gInFlight = true;
        if (id == SFX_COUNT) wait = 0; // Drop a now-muted queued cue, then recheck.
      } else if (gHardwareOn) {
        uint32_t idle = now - gLastUsed;
        if (gForceIdle || !gVolumePct || (!gOn && !gAlarmActive) || idle >= IDLE_OFF_MS) {
          suspend = true;
          gInFlight = true;
        } else {
          wait = waitTicks(IDLE_OFF_MS - idle);
        }
      }
    }
    portEXIT_CRITICAL(&gStateMux);

    if (suspend) {
      bool stopped = hardwareStop(initialSuspend);
      portENTER_CRITICAL(&gStateMux);
      gInitialSuspend = false;
      gForceIdle = false;
      gInFlight = false;
      gLastUsed = millis();
      portEXIT_CRITICAL(&gStateMux);
      if (!stopped) ulTaskNotifyTake(pdTRUE, waitTicks(250));
      continue;
    }
    if (id == SFX_COUNT) {
      if (wait) ulTaskNotifyTake(pdTRUE, wait);
      continue;
    }

    gIoFailed = false;
    bool failed = retryAt != 0 && (int32_t)(millis() - retryAt) < 0;
    bool completed = false;
    if (!failed && hardwareStart()) {
      retryAt = 0;
      uint8_t volume;
      // PA stays low until old DMA samples are replaced and codec is stable.
      if (playbackAllowed(id == SFX_ALARM, volume) && silenceDrain()) {
        digitalWrite(PA, HIGH);
        delay(8);
        const SfxDef &d = SFX[id];
        completed = true;
        do {
          for (uint8_t i = 0; i < d.len; ++i) {
            if (!playTone(d.n[i].f, d.n[i].ms, id == SFX_ALARM)) {
              completed = false;
              break;
            }
          }
        } while (id == SFX_ALARM && completed);
        if (completed) silenceDrain();
      }
      digitalWrite(PA, LOW); // Also immediate on alarm stop/mute/preemption.
      if (gIoFailed) {
        Serial.println("AUDIO write failed; output off");
        hardwareStop();
        retryAt = millis() + RETRY_MS;
        failed = true;
      }
    } else if (!failed) {
      retryAt = millis() + RETRY_MS;
      failed = true;
    }

    portENTER_CRITICAL(&gStateMux);
    gInFlight = false;
    gLastUsed = millis();
    bool retryAlarm = gAlarmActive && gVolumePct > 0;
    portEXIT_CRITICAL(&gStateMux);
    // A missing/faulty codec must never turn the repeating alarm into a busy
    // retry loop. Stop/volume changes notify this wait immediately.
    if (failed && retryAlarm) {
      int32_t remaining = (int32_t)(retryAt - millis());
      if (remaining > 0) ulTaskNotifyTake(pdTRUE, waitTicks((uint32_t)remaining));
    }
  }
}

void audioBegin() {
  portENTER_CRITICAL(&gStateMux);
  bool ready = gReady;
  portEXIT_CRITICAL(&gStateMux);
  if (ready) return;
  pinMode(PA, OUTPUT);
  digitalWrite(PA, LOW);
  Preferences p;
  p.begin("tamapoke", true);
  bool on = p.getBool("snd", true);
  uint8_t volume = p.getUChar("vol", 100);
  p.end();
  if (volume != 0 && volume != 25 && volume != 50 && volume != 75 && volume != 100) volume = 100;
  portENTER_CRITICAL(&gStateMux);
  gOn = on;
  gVolumePct = volume;
  gInitialSuspend = true;
  gSleepArmed = false;
  portEXIT_CRITICAL(&gStateMux);
  TaskHandle_t task = nullptr;
  if (xTaskCreatePinnedToCore(audioTask, "audio", 4096, nullptr, 1, &task, 0) != pdPASS) {
    Serial.println("AUDIO task allocation failed; output off");
    return;
  }
  portENTER_CRITICAL(&gStateMux);
  gTask = task;
  gReady = true;
  portEXIT_CRITICAL(&gStateMux);
  sfxPlay(SFX_HATCH); // Existing boot cue, subject to saved sound/volume settings.
}

void sfxPlay(uint8_t id) {
  bool queued = false;
  portENTER_CRITICAL(&gStateMux);
  if (gReady && gOn && gVolumePct > 0 && !gAlarmActive &&
      id < SFX_COUNT && id != SFX_ALARM && gCount < QUEUE_CAPACITY) {
    gQueue[(gHead + gCount) % QUEUE_CAPACITY] = id;
    ++gCount;
    queued = true;
  }
  portEXIT_CRITICAL(&gStateMux);
  if (queued) notifyAudio();
}

void audioSetEnabled(bool on) {
  portENTER_CRITICAL(&gStateMux);
  gOn = on;
  if (!on) { gHead = 0; gCount = 0; gForceIdle = true; }
  portEXIT_CRITICAL(&gStateMux);
  notifyAudio();
  Preferences p;
  p.begin("tamapoke", false);
  p.putBool("snd", on);
  p.end();
}

bool audioEnabled() {
  portENTER_CRITICAL(&gStateMux);
  bool on = gOn;
  portEXIT_CRITICAL(&gStateMux);
  return on;
}

void audioSetVolume(uint8_t pct) {
  if (pct != 0 && pct != 25 && pct != 50 && pct != 75 && pct != 100) pct = 100;
  portENTER_CRITICAL(&gStateMux);
  gVolumePct = pct;
  if (!pct) { gHead = 0; gCount = 0; gForceIdle = true; }
  portEXIT_CRITICAL(&gStateMux);
  notifyAudio();
  Preferences p;
  p.begin("tamapoke", false);
  p.putUChar("vol", pct);
  p.end();
}

uint8_t audioVolume() {
  portENTER_CRITICAL(&gStateMux);
  uint8_t pct = gVolumePct;
  portEXIT_CRITICAL(&gStateMux);
  return pct;
}

void audioAlarmStart() {
  portENTER_CRITICAL(&gStateMux);
  if (gReady) {
    gAlarmActive = true;
    gHead = 0;
    gCount = 0;
  }
  portEXIT_CRITICAL(&gStateMux);
  notifyAudio();
}

void audioAlarmStop() {
  portENTER_CRITICAL(&gStateMux);
  gAlarmActive = false;
  gHead = 0;
  gCount = 0;
  gForceIdle = true;
  portEXIT_CRITICAL(&gStateMux);
  notifyAudio();
}

bool audioAlarmActive() {
  portENTER_CRITICAL(&gStateMux);
  bool active = gAlarmActive;
  portEXIT_CRITICAL(&gStateMux);
  return active;
}

bool audioBusy() {
  portENTER_CRITICAL(&gStateMux);
  bool busy = gCount || gInFlight || gAlarmActive;
  portEXIT_CRITICAL(&gStateMux);
  return busy;
}

bool audioPrepareSleep() {
  bool ready = false, requestStop = false;
  portENTER_CRITICAL(&gStateMux);
  if (!gCount && !gInFlight && !gAlarmActive) {
    if (gReady && (gHardwareOn || gInitialSuspend)) {
      gForceIdle = true;
      requestStop = true;
    } else {
      // Same lock as task dispatch: it cannot start I2S after this succeeds.
      gSleepArmed = true;
      ready = true;
    }
  }
  portEXIT_CRITICAL(&gStateMux);
  if (requestStop) notifyAudio();
  return ready;
}

void audioAfterWake() {
  portENTER_CRITICAL(&gStateMux);
  gSleepArmed = false;
  portEXIT_CRITICAL(&gStateMux);
  // Do not power up here. Only a queued cue or alarm resumes the hardware.
  notifyAudio();
}

void audioService() {
  bool requestStop = false;
  portENTER_CRITICAL(&gStateMux);
  if (gReady && !gSleepArmed && !gInFlight && !gCount && !gAlarmActive &&
      gHardwareOn && millis() - gLastUsed >= IDLE_OFF_MS) {
    gForceIdle = true;
    requestStop = true;
  }
  portEXIT_CRITICAL(&gStateMux);
  if (requestStop) notifyAudio();
}
