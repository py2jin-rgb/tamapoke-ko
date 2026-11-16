#pragma once
#include "FreeRTOS.h"
#include <condition_variable>
#include <thread>
#include <chrono>
struct MockTask { std::mutex mutex; std::condition_variable cv; uint32_t notices = 0; };
using TaskHandle_t = MockTask *;
inline thread_local TaskHandle_t mockCurrentTask = nullptr;
inline BaseType_t xTaskCreatePinnedToCore(void (*fn)(void *), const char *, uint32_t, void *arg, int, TaskHandle_t *out, int) {
  auto *t = new MockTask;
  *out = t;
  std::thread([t, fn, arg] { mockCurrentTask = t; fn(arg); }).detach();
  return pdPASS;
}
inline void xTaskNotifyGive(TaskHandle_t t) {
  std::lock_guard<std::mutex> lock(t->mutex);
  ++t->notices;
  t->cv.notify_one();
}
inline uint32_t ulTaskNotifyTake(BaseType_t clear, TickType_t ticks) {
  auto *t = mockCurrentTask;
  std::unique_lock<std::mutex> lock(t->mutex);
  if (ticks == portMAX_DELAY) t->cv.wait(lock, [t] { return t->notices != 0; });
  else t->cv.wait_for(lock, std::chrono::milliseconds(ticks), [t] { return t->notices != 0; });
  uint32_t result = t->notices;
  if (clear) t->notices = 0;
  else if (t->notices) --t->notices;
  return result;
}
