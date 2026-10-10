# DelugeLite

A performance-focused fork of the [Synthstrom Deluge community firmware](https://github.com/SynthstromAudible/DelugeFirmware).
Its goals, in priority order:

1. **More voices and more concurrent samples.** Recover the internal RAM and CPU headroom that
   the firmware has gradually lost as features were added.
2. **Remove features only where that pays.** Cut first the ones that cost the most runtime CPU or
   internal RAM.
3. **Add features cheaply.** New features should have negligible runtime cost.

Target hardware for testing: **7-segment Deluge** (144 pads, RZ/A1L).

## Status

The upstream code is imported with its full history (remote `upstream`, `main` @ `2cd3091a`).
Work in progress: Phase 0/1 of the roadmap. Every deviation from upstream is logged in
[CHANGES.md](docs/delugelite/CHANGES.md).

## Build

```bash
./dbt build release                      # DelugeLite defaults: 256-sample audio block, 7-segment only
./dbt configure -DDELUGELITE_AUDIO_BLOCK_SAMPLES=128 -DDELUGELITE_7SEG_ONLY=OFF   # upstream-equivalent
scripts/delugelite/size_report.py build/Release/deluge.elf --top 20               # memory budget
```

Flash `build/Release/deluge.bin` the usual way: copy it as the only `.bin` file in the SD card
root, then hold SHIFT while powering on.

## Docs

| Doc | Content |
|---|---|
| [CHANGES.md](docs/delugelite/CHANGES.md) | Ledger of every change vs upstream |
| [LATENCY.md](docs/delugelite/LATENCY.md) | Audio block size, latency budget, how to win it back |
| [ROADMAP.md](docs/delugelite/ROADMAP.md) | Executive summary, measured numbers, prioritised plan, open decisions |
| [01-hardware.md](docs/delugelite/knowledge/01-hardware.md) | CPU, clocks, MMU/caches, memory map, GIC, DMA, codec/SSI, SD, USB, UARTs, PIC protocol, displays, CV/gate, encoders, pin-out |
| [02-software-architecture.md](docs/delugelite/knowledge/02-software-architecture.md) | Boot, scheduler, audio engine, DSP, synth/sampler, model, playback, GUI, IO, storage; coupling and how hard each part is to remove |
| [03-build-tooling-and-dev-state.md](docs/delugelite/knowledge/03-build-tooling-and-dev-state.md) | dbt/CMake/toolchain, flags, flashing, tests/CI, runtime feature flags, community feature list, licences, debugging |
| [04-performance-ram-cpu.md](docs/delugelite/knowledge/04-performance-ram-cpu.md) | RAM accounting (measured), culling, streaming, voice-start staggering history, ranked optimisations |

The analysis is based on upstream `main` @ `2cd3091a` (2026-10-08, version c1.3.0-dev). Paths
written `<upstream>/...` refer to that tree. Sizes come from a real Release build made with
dbt-toolchain v22 (arm-none-eabi-gcc 14.2.1).

## License

GPLv3, inherited from upstream. See the licensing section of
[03-build-tooling-and-dev-state.md](docs/delugelite/knowledge/03-build-tooling-and-dev-state.md).
