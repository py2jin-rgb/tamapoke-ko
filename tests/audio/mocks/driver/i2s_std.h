#pragma once
#include <atomic>
#include <cassert>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <thread>
using esp_err_t = int;
using gpio_num_t = int;
static constexpr esp_err_t ESP_OK = 0, ESP_FAIL = -1, ESP_ERR_INVALID_STATE = 3;
static constexpr int I2S_NUM_AUTO = -1, I2S_ROLE_MASTER = 1;
static constexpr int I2S_DATA_BIT_WIDTH_16BIT = 16, I2S_SLOT_MODE_STEREO = 2, I2S_STD_SLOT_BOTH = 3, I2S_GPIO_UNUSED = -1;
struct i2s_chan_config_t { int dma_desc_num = 6, dma_frame_num = 240; bool auto_clear = false; };
struct i2s_std_clk_config_t { uint32_t sample_rate_hz; };
struct i2s_std_slot_config_t { int data_bit_width, slot_mode, slot_mask; };
struct i2s_std_config_t {
  i2s_std_clk_config_t clk_cfg;
  i2s_std_slot_config_t slot_cfg;
  struct { gpio_num_t mclk, bclk, ws, dout, din; } gpio_cfg;
};
#define I2S_CHANNEL_DEFAULT_CONFIG(port, role) {}
#define I2S_STD_CLK_DEFAULT_CONFIG(rate) {rate}
#define I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(bits, channels) {bits, channels, I2S_STD_SLOT_BOTH}
struct MockChannel { bool initialized = false, enabled = false; };
using i2s_chan_handle_t = MockChannel *;
namespace Mock {
inline std::atomic<int> liveChannels{0}, enabledChannels{0};
inline std::atomic<unsigned> allocations{0}, deletes{0}, writes{0};
inline std::atomic<bool> failInit{false}, failEnable{false}, failWrite{false};
}
inline esp_err_t i2s_new_channel(const i2s_chan_config_t *cfg, i2s_chan_handle_t *tx, i2s_chan_handle_t *rx) {
  assert(rx == nullptr); assert(cfg->auto_clear);
  *tx = new MockChannel; ++Mock::allocations;
  assert(++Mock::liveChannels == 1);
  return ESP_OK;
}
inline esp_err_t i2s_channel_init_std_mode(i2s_chan_handle_t tx, const i2s_std_config_t *cfg) {
  assert(cfg->gpio_cfg.din == I2S_GPIO_UNUSED);
  assert(cfg->clk_cfg.sample_rate_hz == 16000);
  if (Mock::failInit.exchange(false)) return ESP_FAIL;
  tx->initialized = true; return ESP_OK;
}
inline esp_err_t i2s_channel_enable(i2s_chan_handle_t tx) {
  assert(tx->initialized);
  if (Mock::failEnable.exchange(false)) return ESP_FAIL;
  tx->enabled = true; ++Mock::enabledChannels; return ESP_OK;
}
inline esp_err_t i2s_channel_disable(i2s_chan_handle_t tx) {
  if (!tx->enabled) return ESP_ERR_INVALID_STATE;
  tx->enabled = false; --Mock::enabledChannels; return ESP_OK;
}
inline esp_err_t i2s_del_channel(i2s_chan_handle_t tx) {
  assert(!tx->enabled); delete tx;
  --Mock::liveChannels; ++Mock::deletes; return ESP_OK;
}
inline esp_err_t i2s_channel_write(i2s_chan_handle_t tx, const void *, size_t bytes, size_t *written, uint32_t) {
  assert(tx && tx->enabled);
  if (Mock::failWrite.exchange(false)) { *written = 0; return ESP_FAIL; }
  ++Mock::writes;
  std::this_thread::sleep_for(std::chrono::milliseconds(2));
  *written = bytes; return ESP_OK;
}
