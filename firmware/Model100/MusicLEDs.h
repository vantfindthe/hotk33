// -*- mode: c++ -*-
// MusicLEDs: lets a host program stream full-keyboard LED frames over Focus.
//
// Focus commands:
//   music.frame <hex>   384 hex chars: 64 keys x RRGGBB, matrix order
//                       (row 0 col 0..15, row 1 col 0..15, ...).
//                       Takes over the LEDs from the active LED mode.
//   music.stop          Hands the LEDs back to the active LED mode.
//   music.info          Prints "<rows> <cols> <timeout_ms>".
//
// If no frame arrives for `timeout_ms_`, the LEDs are handed back
// automatically, so the keyboard recovers if the host app quits or crashes.
// This plugin uses no EEPROM, so it doesn't disturb Chrysalis settings.

#pragma once

#include "kaleidoscope/Runtime.h"
#include "kaleidoscope/KeyAddr.h"
#include "kaleidoscope/plugin.h"
#include "Kaleidoscope-FocusSerial.h"
#include "Kaleidoscope-LEDControl.h"

namespace kaleidoscope {
namespace plugin {

class MusicLEDs : public kaleidoscope::Plugin {
 public:
  EventHandlerResult onFocusEvent(const char *input) {
    const char *cmd_frame = PSTR("music.frame");
    const char *cmd_stop  = PSTR("music.stop");
    const char *cmd_info  = PSTR("music.info");

    if (::Focus.inputMatchesHelp(input))
      return ::Focus.printHelp(cmd_frame, cmd_stop, cmd_info);

    if (::Focus.inputMatchesCommand(input, cmd_info)) {
      ::Focus.send(KeyAddr::rows, KeyAddr::cols, timeout_ms_);
      return EventHandlerResult::EVENT_CONSUMED;
    }

    if (::Focus.inputMatchesCommand(input, cmd_stop)) {
      release();
      return EventHandlerResult::EVENT_CONSUMED;
    }

    if (::Focus.inputMatchesCommand(input, cmd_frame)) {
      // A malformed or truncated frame is dropped; the next one will fix it.
      if (!readFrame())
        return EventHandlerResult::EVENT_CONSUMED;

      // Stop the active LED mode from drawing over us. Re-checked every frame
      // because IdleLEDs / power management may re-enable LEDControl.
      if (!active_ || ::LEDControl.isEnabled()) {
        ::LEDControl.disable();
        active_ = true;
      }

      uint8_t i = 0;
      for (uint8_t r = 0; r < KeyAddr::rows; r++) {
        for (uint8_t c = 0; c < KeyAddr::cols; c++, i++) {
          Runtime.device().setCrgbAt(KeyAddr(r, c), frame_[i]);
        }
      }
      Runtime.device().syncLeds();
      last_frame_ms_ = Runtime.millisAtCycleStart();
      return EventHandlerResult::EVENT_CONSUMED;
    }

    return EventHandlerResult::OK;
  }

  EventHandlerResult afterEachCycle() {
    if (active_ && Runtime.hasTimeExpired(last_frame_ms_, timeout_ms_))
      release();
    return EventHandlerResult::OK;
  }

 private:
  static constexpr uint8_t num_keys_ = KeyAddr::upper_limit;
  cRGB frame_[num_keys_];
  bool active_             = false;
  uint32_t last_frame_ms_  = 0;
  uint16_t timeout_ms_     = 1500;

  void release() {
    if (!active_)
      return;
    active_ = false;
    ::LEDControl.enable();
  }

  // Returns the next hex digit's value, or -1 on newline / non-hex / timeout.
  static int8_t readNibble() {
    auto &serial   = Runtime.serialPort();
    uint32_t start = millis();
    while (serial.available() == 0) {
      if (millis() - start > 100)
        return -1;
    }
    int c = serial.peek();
    if (c == '\n')
      return -1;  // leave the newline for FocusSerial
    serial.read();
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
  }

  static bool readByte(uint8_t &out) {
    int8_t hi = readNibble();
    if (hi < 0) return false;
    int8_t lo = readNibble();
    if (lo < 0) return false;
    out = (hi << 4) | lo;
    return true;
  }

  bool readFrame() {
    for (uint8_t i = 0; i < num_keys_; i++) {
      if (!readByte(frame_[i].r) || !readByte(frame_[i].g) || !readByte(frame_[i].b))
        return false;
    }
    return true;
  }
};

}  // namespace plugin
}  // namespace kaleidoscope

kaleidoscope::plugin::MusicLEDs MusicLEDs;
