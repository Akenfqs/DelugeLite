# Deluge community firmware: performance and RAM analysis for a "lite" fork with more voices and samples

**Repo:** `<upstream>`, HEAD `2cd3091a` (2026-10-08).
**Method:**
- I ran `git fetch --deepen=3000 --tags`. History now goes back to the 2023-05-04 open-source import.
- I built HEAD **and** `release_1_2_1` out-of-tree in the scratchpad with the same toolchain (v22, gcc 14.2.1, Release config), so the size numbers below are measured, not guessed.
- I compiled a small probe file to get `sizeof()` of the key structs.
- The repo working tree is unmodified (`git status` is clean). The only change is the extra git objects from the fetch.
- Build outputs: `scratchpad/build/Release/deluge.elf|.map`, `scratchpad/build121/Release/deluge.elf`, `scratchpad/nm_sorted.txt`, `scratchpad/nm_lines.txt`.

Labels used: **[FACT]** means verified in code or in the built ELF. **[EST]** means my engineering estimate, not measured on hardware.

---

## 0. Summary

1. **The internal RAM you can use has shrunk about 23% since 1.2.1.** [FACT, measured]
   - The internal heap at boot fell from 1,330,904 B (1.2.1) to 1,141,740 B (HEAD).
   - HEAD also now places the voice pools (about 120 KB, padded) inside that heap. In 1.2.1 those lived in static `.bss`.
   - Net free internal heap for song data and voices: about 1.02 MB now versus 1.33 MB in 1.2.1.
   - The growth is almost entirely code (`.text` up 306 KB, +35.6%). About 440 KB of the internal code is GUI (views, menus, UI). Code runs from the same 3 MB internal SRAM as the fast heap.
2. **The allocator rounds every block up to a power of two**, including its 8-byte header (`memory_region.cpp:59-79`). [FACT]
   - A `Voice` is 1460 B but costs 2048 B.
   - `InstrumentClip` is 3056 B but costs 4096 B.
   - `VoiceSample` (144 B) and `TimeStretcher` (176 B) each cost 256 B.
3. **Polyphony is not limited by a hard voice count.** It is limited by:
   - CPU culling: the average audio task runtime is compared against 80 samples, about 1.81 ms (`audio_engine.cpp:123`).
   - A per-sound limit: default 8, menu maximum 16.
   - SD streaming: each voice only holds 2 clusters (about 124–186 ms of audio) ahead.
4. **A stagger / voice-start spreading mechanism already exists.** It landed in PR #3229 (`dde56230`, 2025-01-06) and was reworked in #4148, #4658 and #4922.
   - At most 4 voice starts per render window are allowed, or 1 when `cpuDireness > 12`. Extra notes stay PENDING and start in later windows.
   - Every new voice also skips its first render.
5. **There is always-on CPU work that does nothing useful in many songs:**
   - The reverb runs whenever the output is non-silent, even with zero reverb sends.
   - The master compressor (tanh saturation plus RMS on every sample) always runs.
   - Every sounding Sound (each kit row) runs a full stereo post-chain, plus an extra stereo pass per Output.

---

## 1. RAM

### 1.1 Physical memory map (linker script `linker_script_rz_a1l.ld`) [FACT]

| Region | Address range | Contents |
|---|---|---|
| "Frunk" (data-retention RAM, marked NOLOAD and non-executable) | `0x20000000–0x2001FFFF` (128 KB) | `.frunk_bss` (`PLACE_INTERNAL_FRUNK`), then the "small internal" allocator region |
| TTB / exception stacks | `0x20020000–0x2002FFFF` | MMU table 32 KB; IRQ/FIQ/SVC/ABT stacks 8 KB each (`.ld:91-96`) |
| Main internal | `0x20030000–0x202F7FFF` | `.bss` → `.reset`/`.text` → `.rodata` → `.data` → `.heap` (to `program_stack_start`) |
| Program stack | `0x202F8000–0x202FFFFF` | 32 KB (`PROGRAM_STACK_SIZE = 0x8000`) |
| SDRAM | `0x0C000000–0x0FFFFFFF` (64 MB) | `.sdram_data/.sdram_rodata` (strings), `.exceptions` (ARM.exidx/extab), `.sdram_bss`, then the allocator regions |

Notes on the linker script:
- `.text` is linked into internal RAM (`> RAM012L`, `.ld:156-165`). Code executes from the same 3 MB SRAM as the fast heap.
- `PLACE_SDRAM_TEXT` is commented out because of execution problems from SDRAM (`src/definitions.h:83`).

### 1.2 Allocator regions (`src/deluge/memory/general_memory_allocator.cpp:42-78`, `.h:31-33`) [FACT]

| Region | Range | Used for |
|---|---|---|
| INTERNAL | `__heap_start` → `program_stack_start` | `allocMaxSpeed()` / `fast_allocator` (tried first) |
| INTERNAL_SMALL | `__frunk_bss_end` → `0x20020000` | internal allocations under 128 B (`kInternalSwitchSize`) |
| STEALABLE | `__sdram_bss_end` → `END − 2 MB − 128 KB` | `allocStealable()`: audio Clusters, Samples/AudioFiles, grain buffers |
| EXTERNAL | 2 MB (`RESERVED_EXTERNAL_ALLOCATOR = 0x200000`) | `allocLowSpeed`, `operator new` (`operators.cpp:7` always goes to external), `sdram_allocator` |
| EXTERNAL_SMALL | 128 KB at the top of SDRAM | external allocations under 128 B |

How allocation falls through:
- `alloc()` (`.cpp:169-215`) tries internal first when allowed, then external, then **the stealable region**. So song objects silently spill into SDRAM when internal fills.
- `RESERVED_INTERNAL_SMALL` is defined but unused (`.h:33`).
- `padSize()` (`memory_region.cpp:59-79`) adds 8 B and rounds up to the next power of two. For sizes above 4096 B it rounds in 4 KB multiples plus a power-of-two remainder. Minimum alignment is 64 B in the big regions and 16 B in the small regions. This scheme dates from `c8516f01` (PR #638, 2023-10-24).

### 1.3 Measured image sizes at HEAD (Release, gcc 14.2.1) [FACT]

| Section | Bytes | Location |
|---|---|---|
| `.frunk_bss` | 21,072 | internal (frunk) → small-internal region = **110,000 B** free |
| `.bss` | 180,904 | internal; `AudioEngine::reverb` alone is **131,272** |
| `.reset` + `.text` (incl. read-only tables) | 1,166,192 | internal |
| `.rodata` (non-string) | 418,460 | internal |
| `.data` | 9,984 | internal |
| **Internal heap at boot** | **1,141,740** (`0x201E1414`→`0x202F8000`) | |
| SDRAM image (data, rodata strings, exceptions, bss) | 57,472 + 38,724 + 48,888 + 60,944 = 206,028 | |
| Stealable region | about 64.67 MB minus 2.125 MB, about **61.7 MiB**, about 1,960 × 32 KB clusters | |
| `deluge.bin` | 1,738,768 | |

**Same compiler, `release_1_2_1`** [FACT]:
- `.text` 859,912
- `.rodata` 408,972
- `.bss` 308,412 (this included `staticVoices` 61,824, `timeStretchers` 7,680, `voiceSamples` 6,528, `connectedUSBMIDIDevices` 25,944, `ssiRxBuffer` 16,384)
- internal heap 1,330,904
- `.bin` 1,296,392

Change from 1.2.1 to HEAD:
- Code grew by **+306 KB (+35.6%)**.
- The heap shrank by **189 KB**.
- On top of that, the voice pools now come out of the heap. At boot (`AudioEngine::init()`, `audio_engine.cpp:229-231`) `ObjectPool::repopulate()` (`object_pool.h:30`, `kDefaultSize = 48`) allocates:
  - 48 × Voice @ 2048 B
  - 48 × VoiceSample @ 256 B
  - 48 × TimeStretcher @ 256 B
  - total = **122,880 B** of internal heap.
- Effective free internal heap: about **1.019 MB (HEAD) versus 1.331 MB (1.2.1), roughly −23%**.
- Source lines under `src/` excluding RZA1: 180k (1.0) → 216k (1.2.1) → 247k (HEAD).

**Where internal code goes** (from DWARF attribution, `nm -l`, HEAD) [FACT]:

| Bucket | Bytes |
|---|---|
| GUI (`gui/views` 148,008, `gui/menu_item` 128,914, `gui/ui` 128,274, `gui/context_menu` 10,150, `hid/display` + `hid/led` about 30.7K) | about **446 KB** |
| `processing/sound` | 62,830 |
| `dsp/*` (oscillators, filter, dx, reverb, delay, timestretch) | about 65 KB |
| `RZA1/usb` | 32,532 |
| Oscillator wavetables (`analogSquare_*`, `mysterySynthA/BSaw_*`, `squareWave*`, `sawWave*`) plus `tanH2d` (16,770) | about 300 KB |

The largest single function is `__static_initialization…` for `gui/ui/menus.cpp` (21.7 KB). Menu objects themselves were moved to SDRAM in `1f600623` (#4792).

### 1.4 Key struct sizes (probe compiled with production flags) [FACT]

Allocated cost follows from `padSize` (power-of-two rounding including the 8 B header).

| Type | sizeof | Allocated cost | Where it is allocated |
|---|---|---|---|
| `Voice` | **1,460** (1,288 in 1.2.1) | 2,048 | `VoicePool` → `fast_allocator` → `allocMaxSpeed` → internal (`audio_engine.h:139`, `sound.cpp:4910`) |
| `VoiceSample` | 144 | 256 | `VoiceSamplePool` (internal), `audio_engine.cpp:1437` |
| `TimeStretcher` | 176 | 256 | `TimeStretcherPool` (internal) |
| `SampleLowLevelReader` | 112 | (embedded) | inside VoiceSample |
| `Cluster` header | 112, plus `Cluster::size` data (32,768 B for a FAT32 32 KB allocation unit) | about 32,888 | `allocStealable` (SDRAM), `cluster.cpp:40-45` |
| `SampleCluster` (per 32 KB of every loaded file) | 12 | in a `ResizeableArray` → `allocMaxSpeed` → **internal** | `sample_cluster_array.cpp:23`, `resizeable_array.cpp:153` |
| `Sample` | 360 | stealable SDRAM | `audio_file_manager.cpp:782` |
| `Sound` / `SoundDrum` / `SoundInstrument` | 1,336 / 1,856 / 2,088 | 2,048 / 2,048 / 4,096 | `allocMaxSpeed` (internal), e.g. `instrument_clip_view.cpp:5485` |
| `Kit` | 1,732 | 2,048 | internal |
| `InstrumentClip` | 3,056 | 4,096 | internal |
| `NoteRow` / `Note` | 256 / 24 | arrays in internal | |
| `Delay` / `ModFXProcessor` / `RMSFeedbackCompressor` | 344 / 96 / 120 | embedded in every Sound | |
| `dsp::Reverb` (variant) | 131,272 (Freeverb 102,424; Mutable and Digital 131,216 because of `std::array<float,32768>` in `mutable.hpp:166`) | static `.bss`, **internal** | `audio_engine.cpp:132` |

Other buffer locations:
- **Internal (allocated on demand):**
  - The delay buffer (`delay_buffer.cpp:47`, `allocLowSpeed`, SDRAM first).
  - The ModFX buffer, 512 × 8 B = 4 KB per Sound when mod FX is on (`ModFXProcessor.cpp:283`, `delugeAlloc` = internal first).
  - `GranularProcessor` (internal); its 64K-sample grain buffer is stealable SDRAM (`GranularProcessor.cpp:307`).
- **Rendering scratch, all internal:**
  - `renderingMemory` / `reverbMemory`, 1 KB each (`audio_engine.cpp:186-187`).
  - `spareRenderingBuffer[4][128]` in frunk (`voice.cpp:64`).
  - Static `sound_memory` (`sound.cpp:2513`).
- **SDRAM:** `ssiRxBuffer`.

### 1.5 Why code growth costs voices

[FACT] `.text` and the internal heap share the same 3 MB, and every song object competes for that heap via `allocMaxSpeed`: Sounds, Kits, Clips, NoteRow arrays, param automation, `SampleCluster` arrays, voice vectors and pools.

[EST] When the heap is exhausted, new Voices beyond the 48 pooled ones (and song data) go to SDRAM. That is slower: L1 is 32 KB, and L2 data caching was enabled only recently (`a2f8bc51`, #4456, 2026-04-17; `L2CacheUnlockData()` at `deluge.cpp:907`). The comment at `resetprg.c:186` saying "instruction caching only" is now stale.

[EST] Each 64 KB of code costs about 32 pooled-size Voices' worth of fast RAM.

---

## 2. CPU

### 2.1 Render loop [FACT]

**Not interrupt driven.** The audio routine is scheduler task priority 0: min 8 samples, target 64 samples (1.45 ms), max 128 samples (2.9 ms) (`deluge.cpp:551-552`).

**`AudioEngine::routine()`** (`audio_engine.cpp:1046-1125`) calls `routine_()` at most twice per invocation (`numRoutines < 2`, l.1060).

**`routine_()`** (l.563-634):
1. Reads the DMA position from the 128-sample TX ring (`SSI_TX_BUFFER_NUM_SAMPLES 128`, `definitions.h:51`).
2. Calls `setDireness()`.
3. **Doubles the render window** above 6 samples, capped at 128 and rounded to a multiple of 4 for NEON (l.595-614).
4. Calls `tickSongFinalizeWindows()`. **This runs the sequencer ticks (all note-ons) inside the audio routine** and truncates the window at the next tick (l.737-827).
5. Calls `renderAudio()`.

**`renderAudio()`** (l.635-668):
1. `memset` of the buffers.
2. `Song::renderAudio` (`song.cpp:2488`). It loops over all Outputs, each inside `ENTER_CRITICAL_SECTION()` (`song.cpp:2511`). That macro does `CPSID i`, so IRQs are masked for each output render. It was added in #2111 (`dac64cec`).
3. `renderReverb`
4. `renderSamplePreview`
5. `renderSongFX` (master filter, SRR/bitcrush, stutter, pan, **master compressor**)
6. `metronome.render`
7. `envelopeFollower.calcApproxRMS`

**`doSomeOutputting()`** (l.1132-1272) does, for every sample: a 64-bit multiply, `getNoise()` dither ×2, saturation, input monitoring, and the recorder feeds.

### 2.2 Culling and "direness" [FACT]

Constants:
- `numSamplesLimit = 80` (l.123). It was 40 until #2111 (2024-06-16).
- `direnessThreshold = 50` (l.125).
- `MIN_VOICES = 7` (l.130).

**`setDireness()`** (l.503-547):
- Load measure: `getAverageRunTimeForTask(audio) × 44100`. This is an EMA of the form `(last + avg) / 2` (`task.h:32-40`).
- `cpuDireness` = 0..14. It rises immediately and decays by 1 every `kSampleRate >> 3` (125 ms) once the measure is below 47.

**`cullVoices()`** (l.427-499):
- Allowance: `limit = 80 + 20 × voices_started_this_render`.
- Over by ≥32 samples: cull `over >> 4` voices (half killed, half fast-released, plus one soft cull), but keep at least 7 voices.
- Over by ≥0 and rising: one soft cull (`forceReleaseOneVoice`).
- At or below 7 voices: one terminate if over by ≥40.
- If `FlashStorage::highCPUUsageIndicator` is set, the PLAY LED blinks.

What direness degrades:
- Linear instead of sinc interpolation for up-pitched samples (`sample_controls.cpp:37-45`).
- Lower wavetable mip levels (`oscillator.cpp:74,176,273,330`).
- Ladder filter oversampling turns off at 14 (`lpladder.cpp:69`).
- Voice-start throttle (see §3.4).

Voice limits:
- Per Sound, `maxVoiceCount` defaults to 8 (`sound.h:116`), menu maximum 16 (`polyphony.h:67`).
- When exceeded, `acquireVoice()` fast-releases one voice (`sound.cpp:4901-4922`). On out-of-memory it steals one.
- **There is no global voice cap.** The pool of 48 is a free-list size, not a limit.

**Bug** [FACT]: `killOneVoice()` dereferences `it` even when `it == end()` (`audio_engine.cpp:285-291`, no `return` after `cullAudioClipVoice()`). This is undefined behaviour, reachable when only AudioClips are sounding.

Related culling fixes: #4722 (`4bf178fe`), #4819 (`81bc59fe`), #3503, #3067.

### 2.3 What runs per sample vs per buffer [FACT]

**Per voice, per buffer:**
- Envelopes: env 0 always; envelopes 1–3 only if patched (`voice.cpp:735-751`).
- LFO2/LFO4 only if patched.
- MPE smoothing.
- `patcher.performPatching` when any source changed. This is every buffer during an envelope's active stages.
- Porta, the auto-release computation, and `filterSet.setConfig`.

**Per voice, per sample:**
- Oscillator or sample read.
- 16-tap windowed-sinc interpolation when pitch ≠ native (NEON via Argon, `dsp/interpolate/interpolate.cpp`). The buffer shift (`interpolate.h:16-38`) is scalar and done once per input sample. The interpolation buffers are int16, so 24-bit data is truncated for interpolation.
- Ladder or SVF filters (scalar loops, `lpladder.cpp`, `svf.cpp`).
- Amplitude ramp and pan.
- Unison multiplies the cost by `numUnison` (up to 8) × 2 sources.

**Per Sound (every kit row or synth that is not `skippingRendering`), per sample** (`sound.cpp:2383-2650`):
- `memset` and mono→stereo expansion.
- SRR/bitcrush (gated).
- `processFX`: mod FX (gated on type and on sound coming in), EQ (only if adjusted), delay (returns early if off, `delay.cpp:224`).
- Stutter.
- **`processReverbSendAndVolume`: always a full stereo multiply loop** (`mod_controllable_audio.cpp:214-267`).
- Compressor only if threshold > 0 (`sound.cpp:2616`).
- Add into the output.

**Per Output (Kit / AudioOutput, `global_effectable_for_clip.cpp:60-160`):**
- Another 128-sample stereo buffer, `memset`, filters / SRR (if rendered), FX, stutter, the reverb-send/volume loop (always), the compressor (gated), and the add.

**Per Kit, per buffer:** the "Tick ParamManagers" loop over all NoteRows (`kit.cpp:583+`).

**Always on at master level:**
- **Reverb**: `reverbOn = (time since last send < 12 s) || max(RMS) > 9` (`audio_engine.cpp:855-857`, the RMS clause from #1127). Reverb therefore processes whenever anything is audible, **even if no Sound sends to it**.
- **Master compressor** (`audio_engine.cpp:939` → `rms_feedback.cpp:59-127`): per sample, gain ramp plus `getTanHAntialiased` ×2 plus the HPF and RMS of the whole buffer. There is no threshold gating.
- Dither in `doSomeOutputting`.

**NEON use:**
- Oscillators: `basic_waves.cpp`, `sine_osc.h`, `oscillator.cpp`, `render_wave.h`, `vector_rendering_function.h`.
- Interpolation.
- Live pitch shifter.
- Reverb cosine oscillator.
- Not NEON: filters, the sample native-read loops, the per-Sound volume / reverb-send loops, the compressor, and delay.

**Build flags** (`CMakeLists.txt:156-197`):
- `-O2 -fno-inline-functions` globally, chosen for binary size in #487 (`43b8e7aa`).
- LTO with `-flto-partition=none`.
- Thumb-2.
- `ALPHA_OR_BETA_VERSION` is hard-coded to 1 (`definitions.h:6`), so extra checks (`checkStack` in every `Voice::render`, `FREEZE` checks in the kit loop) run in release builds.
- `D_PRINTLN` is compiled out in Release.

### 2.4 Per-voice and per-FX cost [EST, not measured on hardware]

Cycle budget: 400 MHz / 44.1 kHz ≈ 9,070 cycles per sample in total.

| Item | Estimated cycles per output sample | Approx. CPU |
|---|---|---|
| Sample voice, native pitch, no filter | ~25–40 | ~0.3–0.45% |
| Sample voice, pitched sinc + LPF ladder | ~80–130 | ~1–1.4% |
| Synth voice with unison 4, 2 osc, filter | multiples of the above | |
| Per-Sound post chain with no FX (volume/send loop, expand, add) | ~10–20 | ~0.15% per sounding row |
| Delay active | ~40–60 | |
| Mod FX chorus / flanger | ~30–60 | |
| Per-sound compressor | ~40–60 | |
| Reverb, Freeverb or Mutable (always on while audible) | ~60–150 | ~0.7–1.7% |
| Master compressor (always on) | ~30–50 | ~0.4% |

Per-buffer overhead (patching, envelopes, filter setup, per-Sound and per-Output setup, sequencer ticks) is amortised over only about 64 samples. [EST] It is 20–40% of DSP time in dense kits.

---

## 3. Concurrent sample streaming

### 3.1 Mechanics [FACT]

**Cluster size.** `Cluster::size` equals the SD card's FAT allocation unit (`audio_file_manager.cpp:82`, `fileSystem.csize*512`; default 32 KB, `cluster.cpp:30`). FAT32 only (`FF_FS_EXFAT 0`). Each cluster is a Stealable in SDRAM.

**Pinning at load time.** A sample assigned to a Sound pins its **first 2 clusters** (`clustersForStart`, `sample_holder.cpp:158-187`). That is why many kit hits start without SD reads.
- The loop-start clusters are also pinned.
- PR #4952 (`8d9d97dc`, 2026-09-30) tried to pin up to 8 extra clusters for short samples ("caching whole sample", `sample_holder_for_voice.cpp:91-100`). It is **effectively disabled** because `claimClusterReasonsForMarker` forces `numClustersToClaim = 2;` (`sample_holder.cpp:193`).
- The size test in that code also compares a duration in *samples* against a count of *clusters* (`duration >> Cluster::size_magnitude`), so the units are wrong.

**Lookahead per voice.** `kNumClustersLoadedAhead = 2` (`definitions_cxx.hpp:679`): the current cluster plus the next. On entering the next cluster, the reader enqueues N+2 (`sample_low_level_reader.cpp:323-392`). If the next cluster is not loaded in time, the voice is cut (`moveOnToNextCluster` returns false, l.353; "So just cut the sound", l.710).

**Loading.** `ClusterPriorityQueue` is a `std::priority_queue` (`cluster_priority_queue.h`). The "load clusters" task (priority 5, 0.1 ms interval, `deluge.cpp:562`) calls `loadAnyEnqueuedClusters(128)` (`audio_file_manager.cpp:1256-1360`).
- It loads **one cluster at a time** (`clusterBeingLoaded`).
- SD reads are DMA transfers with `yield()`, so audio keeps rendering during reads (since #2111, `deluge.cpp:928-970`).
- `routineForSD()` runs audio and some UI during busy waits.

**SD bus.** 4-bit, HS mode; `SD_CLK_50MHz` maps to 66.6/2 = **33.3 MHz** (`sd_dev_low.c:396`, `sd_cfg.h`). That gives a raw bus limit of about 16.6 MB/s.

### 3.2 Limits [EST]

- **Lead time per voice:** 32 KB lasts about 186 ms (16-bit stereo), 124 ms (24-bit stereo) or 372 ms (16-bit mono) at native pitch. Pitching up shortens it proportionally.
- **Cluster read time:** about 2 ms transfer plus 0.5–2 ms card latency, so roughly 250–400 clusters/s, or 8–13 MB/s.
- **Sustained streams:** about 30–70 concurrent stereo 24/16-bit streams from SD.
  - The binding constraint is usually burst latency, not throughput. When N voices cross into their second cluster at the same moment (all kit rows hit on one step, all 0.25 s in), N reads queue serially. With 2-cluster lookahead there is only about one cluster's play time to drain the queue.
  - The code itself notes 7 voices "can overwhelm SD bandwidth if we schedule the loads badly" (`audio_engine.cpp:127-130`).
- **Short one-shots** that fit inside the 2 pinned start clusters (64 KB, about 0.37 s at 16-bit stereo) never touch the SD card after load.

### 3.3 Many samples triggered on the same step [FACT]

All note-ons happen inside the audio routine via `tickSongFinalizeWindows()`. Each `Sound::noteOn()` → arpeggiator → `allowedToStartVoice()` (`sound.cpp:1550`). Then:
1. **Allowed:** voice allocation from the internal pool, `VoiceSample` setup, start-cluster attach. The new voice's **first `render()` returns immediately** (`voice.cpp:717-722`, `justCreated`), so allocation and first render land in different windows.
2. **Refused:** the note stays PENDING in the arpeggiator and is started from `Sound::render()` → `process_postarp_notes()` in later windows (`sound.cpp:2354-2376`). The Sound is kept out of render-skipping so the note is not lost (#4658).
3. Culling is relaxed by 20 samples per voice started in that window (l.432).

[FACT] Deferred notes are started with `ticksLate = 0, samplesLate = 0` (`sound.cpp:2370-2374`), so the delay is not compensated.

[EST] 16 simultaneous hits finish starting about 4 windows later (about 6–12 ms) at normal load. Above direness 12 they need 16 windows (about 25–45 ms), which is audible flamming. The `justCreated` skip adds 0.2–2.9 ms of variable latency to every note.

### 3.4 Stagger feature: yes, it exists [FACT]

| Commit | Date | PR | What |
|---|---|---|---|
| `dde56230` | 2025-01-06 | **#3229** "Spread out notes to improve perceived performance" (Mark Adams) | Adds `AudioEngine::allowedToStartVoice()` (4 per render), NoteRow deferral (`ignoredNoteOn` / `maybeStartLateNote`), and `Voice::justCreated` skip-first-render. Also cut `RESERVED_EXTERNAL_ALLOCATOR` from 8 MB to 2 MB |
| `edd666c4` | 2026-01-06 | **#4148** | Moves the deferral from NoteRow into `Sound::noteOn` and arpeggiator pending notes (`process_postarp_notes`) |
| `5c33ff73`, `d671f7b1`, `364f9cd1`, `f0b5dd21` | 2026-02-01 to 02-06 | direct commits, no PR number | Fix duplicate pending notes; `cpuDireness > 12 ? 1 : 4` threshold; cull leniency `+20 × voices started`; rename to `voices_started_this_render` |
| `85fed274` | 2026-07-11 | **#4658** | Don't lose notes refused under load (issue #2262) |
| `b76ed397` | 2026-09-24 | **#4922** (Sean Ditny) "Fix multiple delayed note ons starting simultaneously" | Per-note gating in `process_postarp_notes` |

Current code locations:
- `audio_engine.cpp:173` (counter), `615` (reset per `routine_`), `1428-1435` (`allowedToStartVoice`)
- `sound.cpp:1550`, `sound.cpp:2367`
- `voice.cpp:719`

The stagger applies to Sound voices only. AudioClips are not gated.

---

## 4. Scheduler and time stolen from audio [FACT]

**Scheduler type.** `src/OSLikeStuff/task_scheduler/task_scheduler.cpp` is a cooperative, non-preemptive scheduler with 25 task slots (`task_scheduler.h:18`).
- `chooseBestTask()` (l.35-103) picks the lowest-priority task that fits before a higher-priority task's deadline, using EMA durations.
- A task overdue past `maxInterval` is run unconditionally ("mandatory").

**Registered tasks** (`deluge.cpp:531-604`):

| Priority | Task | Interval |
|---|---|---|
| 0 | audio | |
| 1 | USB MIDI | 0.5 ms |
| 2 | encoders | 1 ms |
| 3 | playback routine | 1 ms |
| 4 | MIDI routine | |
| 5 | load clusters | 0.1 ms |
| 6 | audio slow | |
| 7 | buttons/pads | 5 ms |
| 11 | pending UI | 10 ms, max 30 ms |
| 12 | SysEx | |
| 21–23 | file / recorder / playback slow | |
| 31+ | PIC flush, OLED, UI timers | 0.7 ms |

**Audio is just another task.** Any long non-yielding task (UI render, file parsing, recorder `cardRoutine`) delays audio. The only protections are:
- About 93 manual `routineWithClusterLoading()` / `runRoutine()` calls sprinkled through UI, storage and model code.
- `routineForSD()` during SD waits.
- Yields in the SD driver.

**Sequencer ticks** and all note-on processing run inside the audio routine.

**IRQs are masked during each Output's render** (`song.cpp:2511-2516`), which defers USB, MIDI and SD interrupts.

**The OLED** is rendered in a deferred task and sent by DMA (#2032, #2040). The screensaver (#4755) costs about 2.2 KB of `.bss`.

---

## 5. Recommendations

### 5.1 Ranked optimisations for more voices and samples

| # | Change | Where | Impact [EST] | Difficulty |
|---|---|---|---|---|
| 1 | Raise SD lookahead from 2 to 3–4 clusters per voice (SDRAM is plentiful: +32 KB per voice per cluster), and/or prefetch cluster N+2 at voice start | `kNumClustersLoadedAhead`, `sample_low_level_reader.cpp`, `voice_sample.cpp:196+` (comments warn of 2-cluster assumptions) | High for concurrent streaming: removes most "late" cuts in bursts | Medium |
| 2 | Fix #4952: remove `numClustersToClaim = 2;` and fix the samples-vs-bytes unit, so short one-shots are fully pinned | `sample_holder.cpp:193`, `sample_holder_for_voice.cpp:91-100` | High for drum kits: zero SD traffic for samples up to about 10 clusters | Low |
| 3 | Gate reverb on actual sends only (drop the RMS clause, or check reverb tail energy) | `audio_engine.cpp:855-857` | about 1–2% CPU always | Low |
| 4 | Bypass the master compressor when threshold is 0 / neutral (keep a cheap clip stage) | `audio_engine.cpp:939`, `rms_feedback.cpp` | about 0.5% always | Low |
| 5 | Slab/array allocator for Voice, VoiceSample, TimeStretcher, SoundDrum, InstrumentClip (no power-of-two padding) | `object_pool.h` with a dedicated region; `memory_region.cpp:59` | Voice 2048 → 1468 B (−28%): 48 voices save about 28 KB; clips and kits save 10–25% | Low–Medium |
| 6 | Larger render windows: TX buffer 256 and audio target 128 samples, raise `numSamplesLimit` proportionally (more latency, about 5.8 ms) | `definitions.h:51`, `deluge.cpp:551`, `audio_engine.cpp:123` | 10–20% DSP time saved on per-buffer overhead in dense songs; more slack against UI stalls | Medium (many buffers are sized on `SSI_TX_BUFFER_NUM_SAMPLES`) |
| 7 | Compile hot DSP (`voice.cpp`, `voice_sample.cpp`, `sample_low_level_reader.cpp`, `sound.cpp`, `dsp/*`) with inlining allowed or -O3; keep GUI at -Os | per-file options in CMake (note `-fno-inline-functions` in `CMakeLists.txt:174`; LTO interaction needs testing) | 5–15% voice-render speed; GUI at -Os frees about 100+ KB internal | Medium |
| 8 | Fuse the per-Sound post chain (volume + reverb send + add-to-output in one NEON pass; skip the stereo expand for mono kit rows with pan applied at add) | `sound.cpp:2560-2630`, `mod_controllable_audio.cpp:214` | 2–5% with 16+ sounding rows | Medium |
| 9 | Remove `voice.cpp:717` `justCreated` skip and deferred-note lateness: pass `samplesLate` so deferred starts are sample-compensated, or allow more starts per window | `audio_engine.cpp:1428`, `sound.cpp:2370` | Timing/feel improvement; neutral CPU | Low |
| 10 | Move the reverb (128 KB) to SDRAM, now that L2 data cache is on, or keep only Freeverb and drop Mutable/Digital (saves about 28 KB internal) | `audio_engine.cpp:132`, `reverb.hpp:109` | +128 KB internal heap (about 60 more Voices' worth) at a small reverb-CPU cost | Low |
| 11 | Set `ALPHA_OR_BETA_VERSION 0` for release (removes `checkStack` per voice and extra FREEZE checks). Note `audio_file_manager.cpp:1400` uses `cluster->` on a reference in the non-alpha branch, so it will not compile without fixing | `definitions.h:6` | 1–3% | Low |
| 12 | NEON for native-rate sample reads and the scalar interpolation shift; int32 interpolation for 24-bit | `sample_low_level_reader.cpp`, `interpolate.h:16-38` | 5–10% per sample voice | Medium–High |
| 13 | Several cluster loads in flight (queue more than one SD command / multi-block per voice), or bigger reads when contiguous | `audio_file_manager.cpp:906-1360` | Better SD burst throughput | High |
| 14 | Do not mask IRQs for the whole output render; mask only around shared-state touches | `song.cpp:2511` | Lower MIDI/SD latency; indirect | Medium (correctness risk) |
| 15 | Fix the `killOneVoice` undefined behaviour | `audio_engine.cpp:285-291` | Stability | Trivial |

### 5.2 Features whose removal frees CPU or internal RAM, versus ones that only cost code

**Actually free runtime CPU or RAM** (ranked):
1. **Reverb engine variants / always-on reverb**: 128 KB `.bss` and about 1–2% CPU while audible. Keeping only Freeverb saves about 28 KB; moving it or making it optional saves 128 KB. The gating fix is §5.1 #3.
2. **Master compressor / saturation** (always on): about 0.5% CPU.
3. **4 envelopes, LFO3/LFO4** (#3279 `9b843d95`, #3332 `44d8e601`): they cost CPU only when patched, but they grew `Voice` from 1,288 to 1,460 B, which pushed it into the 2048-B padding class (×48 pooled = 98 KB) and enlarged per-voice patching arrays. Removing them gets `Voice` back to about 1.3 KB (still 2048 with power-of-two padding unless §5.1 #5 is also done).
4. **The pre-allocated pools** themselves (48 × 3 objects = 120 KB internal at boot). They could be sized to the target polyphony.
5. **Per-Sound FX** only cost when enabled or tailing: Granular (internal 356 B plus SDRAM buffer), ModFX (4 KB internal per enabled Sound), Delay (SDRAM buffer). The unconditional part is the always-on volume/send loop. Fix it in code rather than by removing features.
6. **DX7 engine**: lazy pool, so CPU and RAM cost arise only when used. About 12.9 KB code.

**Mostly code/flash, little runtime cost** (removing them only frees internal RAM via `.text`, which still helps the heap 1:1):
- GUI: performance view, automation view, keyboard layouts and chord library, arranger extras, menus (about 446 KB internal code in total).
- Screensaver (about 2.2 KB `.bss`).
- Sysex/firmware tools (`smSysex`, 5.4 KB fn).
- MIDI follow and USB host features (`connectedUSBMIDIDevices` is already in SDRAM).
- Stem export, slicer, sample browser previews (`renderSamplePreview` is a cheap UI check).
- DX7 cartridge loader, wavetable import.
- These have essentially zero per-buffer cost unless active, but each 1 KB of `.text` is 1 KB less internal heap.

**Wavetables** (about 300 KB internal): the oscillators need them in fast RAM. Do not move them unless you also drop the analog-square / mystery-synth oscillator types.
