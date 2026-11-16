#pragma once
#include <stdint.h>

// Efectos de sonido del juego (cola, no bloqueante). El orden coincide con la
// tabla SFX de audio.cpp.
enum Sfx : uint8_t {
  SFX_TAP = 0,  // tocar / boton
  SFX_EAT,      // comer
  SFX_PLAY,     // punto del minijuego / golpe
  SFX_HEART,    // le gusta / mimo
  SFX_HATCH,    // eclosion
  SFX_EVOLVE,   // evolucion
  SFX_MEDAL,    // medalla / hito
  SFX_DENY,     // accion no permitida
  SFX_BYE,      // despedida
  SFX_LEVEL,    // sube de nivel
  SFX_ALARM,    // alarma diaria (se repite hasta detener/snooze)
  // Minigames: original synthesized 8-bit cues (no sampled game audio).
  SFX_GAME_OPEN,
  SFX_GAME_START,
  SFX_MOLE_HIT1,
  SFX_MOLE_HIT2,
  SFX_MOLE_HIT3,
  SFX_MOLE_MISS,
  SFX_GAME_TICK,
  SFX_RPS_SELECT,
  SFX_RPS_WIN,
  SFX_RPS_LOSE,
  SFX_RPS_DRAW,
  SFX_GAME_OVER,
  SFX_COUNT
};

void audioBegin();          // create audio task; TX/codec power up only for playback
void sfxPlay(uint8_t id);   // encola un efecto (no bloquea el loop)
void audioSetEnabled(bool on);
bool audioEnabled();

// Alarm audio ignores the game sound toggle and repeats until stopped.
void audioAlarmStart();
void audioAlarmStop();
bool audioAlarmActive();

void audioSetVolume(uint8_t pct);
uint8_t audioVolume();

// Main-loop power manager API. Calls are task-context only (not ISR-safe).
// Busy includes pending cues, in-flight hardware work, and a logical alarm
// even at volume 0. An idle powered codec is quiesced by the audio task.
bool audioBusy();
void audioService();

// Nonblocking: false means the task is still busy or powering down; retry on
// a later loop. True reserves a quiescent output and prevents the audio task
// from starting playback until audioAfterWake(). Pair every successful call
// with audioAfterWake(), INCLUDING if the caller aborts the actual sleep.
// Requests arriving during the reservation remain queued; audioBusy() can be
// checked once more immediately before sleep to notice newly queued work.
bool audioPrepareSleep();
void audioAfterWake();
