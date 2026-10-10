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

Research phase. The code has not been imported yet. The knowledge base is under
[`docs/knowledge/`](docs/knowledge/):

| Doc | Content |
|---|---|
| [ROADMAP.md](docs/ROADMAP.md) | Executive summary, measured numbers, prioritised plan, open decisions |
| [01-hardware.md](docs/knowledge/01-hardware.md) | CPU, clocks, MMU/caches, memory map, GIC, DMA, codec/SSI, SD, USB, UARTs, PIC protocol, displays, CV/gate, encoders, pin-out |
| [02-software-architecture.md](docs/knowledge/02-software-architecture.md) | Boot, scheduler, audio engine, DSP, synth/sampler, model, playback, GUI, IO, storage; coupling and how hard each part is to remove |
| [03-build-tooling-and-dev-state.md](docs/knowledge/03-build-tooling-and-dev-state.md) | dbt/CMake/toolchain, flags, flashing, tests/CI, runtime feature flags, community feature list, licences, debugging |
| [04-performance-ram-cpu.md](docs/knowledge/04-performance-ram-cpu.md) | RAM accounting (measured), culling, streaming, voice-start staggering history, ranked optimisations |

The analysis is based on upstream `main` @ `2cd3091a` (2026-10-08, version c1.3.0-dev). Paths
written `<upstream>/...` refer to that tree. Sizes come from a real Release build made with
dbt-toolchain v22 (arm-none-eabi-gcc 14.2.1).

## License

GPLv3, inherited from upstream. See the licensing section of
[03-build-tooling-and-dev-state.md](docs/knowledge/03-build-tooling-and-dev-state.md).
