# Hardware test protocol (7-segment Deluge)

This protocol is for testing DelugeLite builds until dedicated measurement tooling exists
(ROADMAP Phase 0). Keep a copy of a known-good upstream `.bin` on your computer so you can always
flash back.

## Flashing

1. Copy **one** `.bin` file into the SD card root, and remove any other `.bin` files.
2. Hold **SHIFT** while switching the Deluge on. The display shows `UPDA`, then `DONE`.
3. Remove the `.bin` from the card. It is safe to leave it there, but it is confusing.

## 1. Smoke test (every build)

| # | Check | Pass if |
|---|---|---|
| 1 | Boot | 7-segment shows normally; pads light up |
| 2 | Load an existing song | loads and plays as before |
| 3 | Synth: play pads; long attack and release; fast attack (0) | sounds identical, no clicks or crackle |
| 4 | Kit: 8+ rows on the same step | no flams beyond what upstream does |
| 5 | Audio clip with time-stretch (tempo ≠ sample tempo) | no glitch at clip start |
| 6 | Record a sample from line in or mic; resample | recording has no gaps and lines up with the beat |
| 7 | Monitoring (input to output) | works; latency is a little higher at 256 |
| 8 | MIDI clock **in** from an external device, 120 and 180 BPM | stays in sync, no drift or stutter |
| 9 | MIDI clock **out** and CV/gate out | external gear stays in time |
| 10 | Menus (SHIFT+SELECT, sound editor) | all text shows on the 7-segment |
| 11 | Save a song, power-cycle, load it again | identical |

## 2. A/B voice capacity (128 vs 256 block)

You get two builds that differ **only** in the audio block size. Both are 7-segment only.

- `DelugeLite-256.bin` is the DelugeLite default.
- `DelugeLite-128.bin` has the upstream block size.

**Setup, once:**
1. Enable the CPU warning: SHIFT+SELECT → Defaults → `CPU` → ON. The PLAY LED then blinks
   whenever voices are culled.
2. Build a stress song. This one song is reused for every future build, so keep it.
   - **Synth test:** one synth track with a saw-pad patch (2 oscillators, unison 4, low-pass
     filter, long release). Set polyphony to 16.
   - **Kit test:** one kit with 16 rows of long samples (> 1 s, stereo 24-bit if you have
     them), all triggered on every 16th step.

**Measurement, on each build:**
1. **Synth test:** with the sequencer stopped, hold down more and more pads until the PLAY LED
   blinks. Note how many notes you were holding.
2. **Kit test:** play the kit pattern, then raise the tempo until you hear cut-offs or see the PLAY
   LED blink. Note the BPM.
3. **Feel:** play pads live on both builds and note whether 256 feels any less responsive.

**Record the results here, or in a GitHub issue:**

| build | synth notes before culling | kit BPM before cut-offs | feel notes |
|---|---|---|---|
| upstream c1.3 | | | |
| DelugeLite-128 | | | |
| DelugeLite-256 | | | |

## 3. What a failure looks like and what to send back

- **Crash:** the pads show a pattern, which is the crash code. Take a photo of the pads.
- **Crackle or dropouts:** describe which song and action triggered it, and which build.
- **Timing drift with external clock:** note the BPM and the device.
