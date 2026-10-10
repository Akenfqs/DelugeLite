# DelugeLite change ledger

This ledger lists every way DelugeLite differs from upstream. Each entry records what changed, why,
its measured or estimated effect, and how to revert it. Newest entries are at the top.

The upstream base is `SynthstromAudible/DelugeFirmware` `main` @ `2cd3091a` (c1.3.0-dev). It is
merged with full history, and the git remote is named `upstream`.

Memory numbers come from `scripts/delugelite/size_report.py` on Release builds. "Fast heap" is the
internal SRAM left over for voices, sounds and clips; the upstream baseline is **1,141,740 B**.

| ID | Change | Type | Effect | Verified on HW? | Revert |
|---|---|---|---|---|---|
| DL-003 | 7-segment-only build (`DELUGELITE_7SEG_ONLY`, default ON) | removal | see entry | no | `-DDELUGELITE_7SEG_ONLY=OFF` |
| DL-002 | Audio block 256 samples (`DELUGELITE_AUDIO_BLOCK_SAMPLES`, default 256) | perf / latency | +~3 ms output latency; est. 5–10 % less audio CPU in dense songs | no | `-DDELUGELITE_AUDIO_BLOCK_SAMPLES=128` |
| DL-001 | Fix out-of-range dereference in `AudioEngine::killOneVoice()` | bug fix | removes a crash/UB when a hard cull happens with only audio clips sounding | no | revert commit |

---

## DL-003: 7-segment-only build

The target hardware has the 7-segment display, so OLED support is compiled out:

- `Display::haveOLED()` becomes a compile-time `false` (`hid/display/display.h`). The ~300
  `display->haveOLED()` branches therefore fold away.
- Boot never selects the OLED (`deluge.cpp`).
- The emulated-display swap (`swapDisplayType`) is disabled.

**Effect:** see the measurement table in the commit and in [ROADMAP.md](ROADMAP.md).

**Caveat:** a 7SEG_ONLY build shows nothing on an OLED unit. Everything else still works there.

**Not done yet:** the `renderOLED()` implementations of each UI and menu are still compiled in,
because the vtables keep them alive. Removing them is the next, bigger step.

## DL-002: audio block 256

Full description, latency numbers and the plan for winning the latency back are in
[LATENCY.md](LATENCY.md).

## DL-001: `killOneVoice()` end-iterator dereference

`processing/engines/audio_engine.cpp`: when no Sound had an active voice, the function culled an
audio clip voice and then fell through to `*it` with `it == end()`. It now returns after the
audio-clip cull. This should also go upstream; per upstream's contribution policy, a human has to
submit it.
