# Audio block size and latency

This file is the ledger for the one DelugeLite change that **adds latency on purpose**. It covers
what changed, how much latency it adds, why, and how to get the latency back later.

**Switch:** the CMake cache variable `DELUGELITE_AUDIO_BLOCK_SAMPLES`. It accepts `128` (the
upstream value) or `256` (the DelugeLite default).

```bash
./dbt configure -DDELUGELITE_AUDIO_BLOCK_SAMPLES=128   # upstream behaviour
./dbt configure -DDELUGELITE_AUDIO_BLOCK_SAMPLES=256   # DelugeLite default
./dbt build release
```

## 1. How audio gets out of the Deluge

The text below follows `processing/engines/audio_engine.{h,cpp}` and `drivers/ssi/ssi.c`.

```
 sequencer ticks + note-ons            renderingMemory[]                ssiTxBuffer[] (ring)          codec
 (tickSongFinalizeWindows) ──► render ──►  (one "window",   ──► doSomeOutputting ──► N samples  ──► DMA ──► DAC
                                            ≤ N samples)        (volume, dither,       circular,     44.1 kHz
                                                                 monitoring, rec)      N = 128|256
```

1. **The TX ring.** `ssiTxBuffer` is a circular buffer of `SSI_TX_BUFFER_NUM_SAMPLES` stereo
   frames. A DMA channel streams it to the codec without stopping. When the code wants to know how
   much room there is to write, it reads the DMA's current position (`CRSA`).
2. **The audio routine.** This is scheduler task priority 0, not an interrupt. Each time it runs it
   measures the free space in the ring, then renders a *window* of samples into
   `renderingMemory`.
   - The window is about **twice** the free space, capped at N. Half is written into the ring
     straight away; the rest waits in `renderingMemory` and is written on the next call.
   - The window is also cut short so that it ends exactly on the next sequencer tick. This keeps
     sequencer timing sample-accurate regardless of window size.
3. **Scheduling.** The task asks to run every `64·S` samples, at least every `8` and at most every
   `128·S`. S is `AUDIO_BLOCK_SCALE`: 1 for upstream, 2 for DelugeLite.

## 2. How much latency

The latency from a note-on to the moment its first sample reaches the DAC is the sum of:

| Component | Upstream (N=128) | DelugeLite (N=256) |
|---|---|---|
| Ring occupancy: samples already queued ahead of the new ones (the ring runs close to full in steady state) | ≤ 128 samples = **≤ 2.9 ms** | ≤ 256 samples = **≤ 5.8 ms** |
| Rendered but not yet written ("doubling" backlog) | ≤ window/2 | ≤ window/2 |
| `Voice::justCreated`: a new voice skips its first window (#3229) | ≤ 1 window ≈ 0.2–2.9 ms | ≤ 1 window ≈ 0.4–5.8 ms |
| Voice-start throttle: at most 4 starts per window, 1 when the CPU is dire; deferred starts are not compensated for lateness | 0 to several windows | same count of windows, but each is up to 2× longer |
| Codec converter delay (CS4270, a fixed hardware constant) | unchanged | unchanged |

**In practice:** worst-case added latency is about **+2.9 ms for the ring**, plus up to
**+2.9 ms** from the larger `justCreated` window. Typical added latency is about **+3 ms**.

What does **not** change:
- **Sequencer timing and jitter.** Windows always end exactly on tick boundaries.
- **MIDI clock out and gate timing.** These are scheduled sample-accurately by a hardware timer
  (`scheduleMidiGateOutISR`, MTU2 channel 2).

Every output event (audio, CV, gates, MIDI) moves later by the same constant. This matters for
**live playing** (pads, MIDI keyboard into the Deluge) and for **live input monitoring**. It does
not matter for sequenced material.

### Other side effects of larger windows

- **Envelope stage changes and LFO positions** are only recalculated at the start of each window
  (see the long comment in `audio_engine.h`). An attack or release shorter than one window can
  stretch to the window length. That means up to ~5.8 ms instead of ~2.9 ms, but only under heavy
  load. Under light load the windows stay short.
- **Modulation update rate** under load drops from about 340–800 Hz to 170–400 Hz. Levels,
  wavetable position and FM amounts are still interpolated linearly within a window, so this is
  rarely audible.
- **Time-stretch first hop** (`TimeStretch::kDefaultFirstHopLength`) must be at least one window.
  It goes from 200 to 256 samples, a slightly longer first crossfade when a time-stretched sample
  starts (`voice_sample.cpp` static_assert).
- **Internal RAM** grows by about 7 KB: render buffers, filter scratch, compressor dry buffer, the
  ring itself. `spareRenderingBuffer` and `oscSyncRenderingBuffer` grow by about 2 KB in the frunk.
  One render-scratch buffer per Kit or audio track, `global_effectable_memory`, lives on the stack
  and grows from 1 KB to 2 KB. The stack is 32 KB and is checked by `checkStack`.

## 3. What we get for it

- **Per-window overhead is amortised over twice as many samples.** That overhead includes patching
  (`Patcher::performPatching`), envelopes, LFOs, filter coefficients, per-Sound and per-Output
  setup, the Kit ParamManager tick loop, and render-skipping checks. **Estimate:** 5–10 % less
  audio CPU in dense songs.
- **More tolerance for scheduling hiccups.** UI redraws, SD waits and file parsing have twice as
  much time before a dropout. Culling also triggers less often from short spikes.

The culling and "direness" thresholds measure *render time per audio call*. They are scaled by
`AUDIO_BLOCK_SCALE`, so a given CPU load is judged the same way at either block size:

| Constant | Upstream | DelugeLite (×2) | Where |
|---|---|---|---|
| `numSamplesLimit` | 80 | 160 | `audio_engine.cpp` |
| `direnessThreshold` | limit − 30 | limit − 60 | same |
| hard-cull trigger / voices per step | 32 / ÷16 | 64 / ÷32 | `cullVoices` |
| cull below MIN_VOICES | 40 | 80 | same |
| direness hysteresis | 3 | 6 | `setDireness` |
| direness value | 0–14 | 0–14 (divided by the scale) | same |
| per-voice-start leniency | +20 | +20 (unscaled: a voice start costs a fixed time) | same |

**Status: these figures are estimates.** They must be measured on hardware by A/B testing the 128
and 256 builds with the stress test (Phase 0 in [ROADMAP.md](ROADMAP.md)). If 256 does not
measurably help, we go back to 128.

## 4. How to get the latency back later

These are options, roughly cheapest first:

1. **Remove the `justCreated` skip** (`voice.cpp:719`). A new voice would then start in the window
   where it was triggered. Saves up to one window of latency at any block size, so up to 5.8 ms.
   The cost is spikier CPU at note-on bursts.
2. **Compensate deferred voice starts.** Pass the real `samplesLate` to the deferred start
   (`sound.cpp:2370`) so that throttled notes keep their timing.
3. **Adaptive block size.** Run at 128 while the CPU is light and allow 256 only when direness is
   above zero. The ring stays 256 (the DMA descriptor is fixed). The audio routine would keep the
   ring filled to only 128 samples while the load is light. Most of the time this gives upstream
   latency, with the large block reserved for when it is needed.
4. **Menu setting.** Expose 3 above as "Low latency / More voices" in the settings menu.
5. **Revert:** rebuild with `-DDELUGELITE_AUDIO_BLOCK_SAMPLES=128`.

## 5. Everything this switch touches

| File | Change |
|---|---|
| `CMakeLists.txt` | `DELUGELITE_AUDIO_BLOCK_SAMPLES` cache variable, passed as a global compile definition |
| `src/definitions.h` | `SSI_TX_BUFFER_NUM_SAMPLES` comes from it; `AUDIO_BLOCK_SCALE` defined |
| `src/definitions_cxx.hpp` | `TimeStretch::kDefaultFirstHopLength = max(200, N)` |
| `src/deluge/deluge.cpp` | Audio task target and max interval × scale |
| `src/deluge/processing/engines/audio_engine.cpp` | Culling and direness thresholds × scale; `outputBufferForResampling` size derived from N instead of a hard-coded `128*2` |

All other users of `SSI_TX_BUFFER_NUM_SAMPLES` (57 uses) were checked. They size buffers from the
macro or use it as a ring mask, so they follow automatically. That includes the DMA descriptor
(`sizeof(ssiTxBuffer)`), the RX-latency alignment (RX ring 2048 ≥ 2·256), the sample recorder
offsets, time-stretch `maxSamplesBehind`, and the MIDI-clock-in timestamp mask
(`playback_handler.cpp:1862`).

The MTU2 gate timer's 16-bit compare value stays within range: 256 × 766245 >> 16 = 2993.

The one remaining hand-tuned value is the `+ 40` in `playback_handler.cpp:1862`, which upstream
tuned for 128 ("28 to 98 seemed to work"). A larger ring only gives it more room. Still, external
MIDI clock sync must be checked on hardware.
