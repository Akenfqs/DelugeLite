# DelugeLite: findings and roadmap

**Baseline:** upstream `main` @ `2cd3091a` (2026-10-08), c1.3.0-dev, compared against tag `release_1_2_1`.
Both were built locally with the same toolchain (dbt v22, GCC 14.2.1, Release configuration).
Line references point into the upstream tree. The details and evidence are in `knowledge/*.md`.

## 1. What limits voices and samples

### 1.1 Internal RAM is the scarce resource, and code competes for it

The RZ/A1L has 3 MB of on-chip SRAM. The firmware **executes code from that same SRAM**, because
running code from SDRAM was tried and did not work (`src/definitions.h:83`). Whatever SRAM the code
and static data do not use becomes the "fast heap". That heap holds:

- voices, VoiceSamples and TimeStretchers;
- Sounds, Kits and Clips;
- NoteRow arrays and automation;
- the per-sample cluster index arrays.

Measured layout of the internal RAM at HEAD:

| Item | Bytes |
|---|---|
| `.text` (code + oscillator wavetables) | 1,166,192 |
| `.rodata` | 418,460 |
| `.bss` (of which `AudioEngine::reverb` alone is **131,272**) | 180,904 |
| **Fast heap at boot** | **1,141,740** |
| minus voice pools pre-allocated at boot (48 × Voice/VoiceSample/TimeStretcher) | −122,880 |
| **Free fast heap** | **≈ 1.02 MB** |

The same layout at 1.2.1 had a free fast heap of **≈ 1.33 MB**. That is a 23 % drop in about a
year, and almost all of it is code growth: `.text` went up 306 KB (+36 %).

About **446 KB** of the internal code is GUI: views, menus, UIs and display code. GUI code does
almost nothing at runtime, but every KB of it is a KB taken from the voice heap. When the fast heap
fills up, allocations silently spill into SDRAM, which is slower.

Two more facts make this worse:

- **The allocator rounds every block up to a power of two**, including its 8-byte header
  (`memory/memory_region.cpp:59`). A `Voice` is 1,460 B but costs 2,048 B. An `InstrumentClip` is
  3,056 B but costs 4,096 B.
- **`Voice` grew from 1,288 B to 1,460 B** when 4 envelopes and 4 LFOs were added.

### 1.2 CPU: culling, not a hard voice limit

- There is no global voice cap. Voices are culled when the averaged audio-task time exceeds
  **80 samples (≈ 1.8 ms) per render** (`audio_engine.cpp:123`). Sounds are also capped at 8 voices
  each by default, 16 at most.
- Some DSP runs all the time, even when it does nothing useful:
  - The **reverb** runs whenever *anything* is audible, even if no sound sends to it
    (`audio_engine.cpp:855-857`, the RMS clause).
  - The **master compressor** runs tanh saturation and an RMS calculation on every sample, with no
    bypass.
  - **Every sounding Sound**, including each kit row, runs a full stereo volume/reverb-send pass
    even when its send is 0. Each Kit or Output then adds another stereo pass on top.
- Per-buffer overhead (patching, envelopes, filter setup, sequencer ticks) is spread over only
  ~64 samples.
- Hot DSP code is built with `-O2 -fno-inline-functions`, a size optimisation.
- `ALPHA_OR_BETA_VERSION=1` is hard-coded, so debug checks still run in release builds.

### 1.3 SD streaming of many samples

- Each sample pins its **first 2 clusters** (2 × 32 KB on a typical card) in RAM. Each playing voice
  keeps only **2 clusters of look-ahead**, roughly 124–186 ms of stereo audio.
- Clusters are loaded **one at a time**. When many voices cross into their next cluster at the same
  moment, the reads queue up and voices can get cut.
- PR #4952 (2026-09-30) was meant to pin whole short samples. It is **effectively dead code**,
  because `numClustersToClaim = 2;` at `model/sample/sample_holder.cpp:193` overrides it. Its size
  test also compares a count of samples against a count of clusters.

### 1.4 The "samples don't start at exactly the same moment" fix

**This already exists and is in current firmware.** It was added by PR #3229 (2025-01-06,
"Spread out notes to improve perceived performance") and refined by #4148, #4658 and #4922
(2026-09-24). It works like this:

- At most **4 new voices may start per render window**, or only 1 when the CPU is "dire" (> 12).
  Any extra note-ons are held as pending and started in later windows
  (`AudioEngine::allowedToStartVoice`, `audio_engine.cpp:1428`).
- A new voice also **skips its first render** (`voice.cpp:719`).
- Culling is relaxed by 20 samples for each voice started in that window.

It reduces CPU spikes. The cost is that a held-back note is started with `samplesLate = 0`, so it
is not timing-compensated. Under load, 16 simultaneous hits can flam by ~25–45 ms. That is a
concrete thing DelugeLite can improve.

## 2. Plan

Phase 0 is a prerequisite. Phases 1 and 2 are mostly independent and can be measured one by one.

### Phase 0: set up the base and measurement (no behaviour change)

1. Import upstream with its full history, so we can keep merging upstream fixes.
2. Add a size budget: a report of `.text`, `.bss` and fast heap per build (`dbt elfsize` already
   exists).
3. Add an on-device stress test: one song with N kit rows and long samples. Record which voice
   count first triggers culling, and when samples get cut. Show the voice count and direness on the
   7-segment display. **This needs your hardware.**

### Phase 1: low-risk wins without removing any features

| # | Change | Gain (estimated) | Effort |
|---|---|---|---|
| 1 | Fix the dead whole-sample pinning from #4952 | no SD traffic for short one-shots | low |
| 2 | Run the reverb only when something is actually sent to it (or its tail is still decaying) | ~1–2 % CPU | low |
| 3 | Bypass the master compressor when it is neutral | ~0.5 % CPU | low |
| 4 | Move the 128 KB reverb buffer to SDRAM (L2 data cache is now enabled), or keep only Freeverb | +28 to +128 KB fast heap | low |
| 5 | Exact-size slab pools for Voice, VoiceSample, TimeStretcher and SoundDrum | ~−28 % per voice | low–med |
| 6 | Size the boot pools to the target polyphony instead of a fixed 48 | tunable | low |
| 7 | `ALPHA_OR_BETA_VERSION 0` in release builds (one compile fix is needed) | 1–3 % CPU | low |
| 8 | Look-ahead of 3–4 clusters per voice (SDRAM is plentiful) | far fewer streaming cuts | medium |
| 9 | Compile hot DSP at `-O2/-O3` with inlining; compile GUI at `-Os` | 5–15 % voice CPU, and ~100 KB+ more fast heap | medium |
| 10 | Fused NEON post-chain per Sound (volume + send + mix in one pass) | 2–5 % with dense kits | medium |
| 11 | Timing-compensate the held-back voice starts | tighter timing | low |
| 12 | Fix a crash bug in `killOneVoice()`: `*it` is used when `it == end()` (`audio_engine.cpp:285`) | stability | trivial |

### Phase 2: remove features, cheapest per KB freed first

These features are self-contained and cost only code. Each KB of code removed gives back a KB of
fast heap.

| Candidate | Internal code (approx.) | Effort to remove |
|---|---|---|
| Keyboard view layouts + chord library | ~25 KB | moderate |
| Performance view | ~10 KB | moderate |
| Automation view (automation itself stays) | ~19 KB + editors | moderate–hard |
| MIDI Follow | ~5.5 KB + hooks | moderate |
| Stem export, sysex file protocol, screensavers | several KB | easy |
| Randomizer, DX7 engine + browser + menus | ~13 KB + menus | moderate |
| OLED-only code paths (keep 7-segment) | OLED + canvas ≈ 12 KB + `renderOLED` in every UI | hard; probably not worth it |

These features also cost runtime RAM or CPU:

- Reverb model variants: 128 KB of `.bss`.
- 4 envelopes / 4 LFOs: +172 B per Voice.
- ModFX: 4 KB of internal RAM for each Sound that uses it.

### Phase 3: cheap additions

Decide these after Phases 1 and 2, using the size budget from Phase 0.

## 3. Decisions (answered 2026-10-10)

1. **Repository base:** upstream `main`, imported with full history. Done.
2. **Branch to track:** upstream `main`, i.e. the c1.3 line.
3. **Latency:** a doubled audio block is accepted, on condition that every detail is logged and
   there is a plan to win the latency back. See [LATENCY.md](LATENCY.md) (DL-002).
4. **File compatibility:** keep loading existing files where possible, but this is not a hard
   requirement.
5. **Feature list:** still open. The user is thinking about it.
6. **Displays:** the target is 7-segment only, so OLED support may be removed (DL-003).
7. **Testing:** the user tests on the 7-segment unit, following [TESTING.md](TESTING.md).

## 4. Things I could not determine from code

- The **bootloader source**: it is not in the repo. Only the image header format and the flash
  address `0x18080000` are known.
- The OLED controller and SPI-flash part numbers. The codec (CS4270), CV DAC (MAX5136), PIC
  (PIC24FJ256) and SDRAM (AS4C32M16SB) are named only in `contrib/doc/pinmap/generate.py`.
- Real cycle costs. All CPU percentages here are estimates until they are measured on the device.

## 5. Notes

- Upstream's `docs/CONTRIBUTING.md` forbids agent-opened PRs and LLM-written PR descriptions **to
  the upstream repo**. That is not a problem for this fork. If you later send fixes upstream (for
  example the `killOneVoice` bug or the #4952 pinning fix), you will have to submit them yourself.
- GPLv3: if you distribute binaries, you must publish the corresponding source. Do not brand the
  fork as official Synthstrom firmware.
