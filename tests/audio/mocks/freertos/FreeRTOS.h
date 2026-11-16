#pragma once
#include <cstdint>
#include <mutex>
using TickType_t = uint32_t;
using BaseType_t = int;
struct portMUX_TYPE { std::mutex mutex; };
#define portMUX_INITIALIZER_UNLOCKED {}
#define portENTER_CRITICAL(p) (p)->mutex.lock()
#define portEXIT_CRITICAL(p) (p)->mutex.unlock()
#define pdMS_TO_TICKS(ms) (ms)
static constexpr TickType_t portMAX_DELAY = UINT32_MAX;
static constexpr BaseType_t pdTRUE = 1;
static constexpr BaseType_t pdPASS = 1;
