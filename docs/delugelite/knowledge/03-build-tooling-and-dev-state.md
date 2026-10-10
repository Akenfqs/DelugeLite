# Deluge Community Firmware: upstream investigation report

**Repo root:** `<upstream>` (written as `$U` below)

**What the clone is:** a shallow clone (`git rev-parse --is-shallow-repository` returns `true`) with one commit: `2cd3091 Infra/pr template (#4986)`, dated 2026-10-08. There are no git submodules (no `.gitmodules`). Third-party code is either vendored under `src/` or pulled at configure time with CMake `FetchContent`.

**Docs have moved:** most markdown under `docs/` (`docs/dev/*`, `docs/community_features.md`, `CHANGELOG.md`, `docs/features/`) is now a 4-line stub that says "Page has been moved" and links to delugecommunity.com. The real content is in `$U/website/src/content/docs/` (an Astro/Starlight site).

---

## 1. Build system

### 1.1 DBT (Deluge Build Tool)

**Entry points**
- `$U/dbt` is a bash wrapper ("blatantly borrowed from 'fbt'" in flipperzero-firmware, GPL). It does three things:
  - sources `scripts/toolchain/dbtenv.sh`, unless `DBT_NOENV` is set;
  - runs `git submodule update --init --depth 1`, unless `DBT_NO_SYNC` is set (it exits if `.git` is missing, so a source zip will not build);
  - runs `python3 dbt.py "$@"`.
- `$U/dbt.cmd` is the Windows equivalent. It downloads the toolchain with `scripts/toolchain/windows-toolchain-download.ps1`.
- `$U/dbt.py`:
  - discovers subcommands as `scripts/tasks/task-*.py`, each exposing `argparser()` and `main()`;
  - sets `DELUGE_FW_ROOT`, `DBT_TOOLCHAIN_PATH` and `DBT_DEBUG_DIR=scripts/debug`;
  - on first run, copies `IDE_Configs/vscode` to `.vscode` and `IDE_Configs/clion` to `.idea`.
- `$U/Makefile` is a thin shim: `make debug` runs `./dbt build debug`, `make release` runs `./dbt build release`, and `make clean` runs `./dbt clean`.

**Environment variables:** `DBT_NOENV`, `DBT_NO_SYNC`, `DBT_TOOLCHAIN_PATH`, `DBT_VERBOSE`, `DBT_NO_PYTHON_UPGRADE`, `DBT_TOOLCHAIN_VERSION`.

**Subcommands** (all in `$U/scripts/tasks/`)

| Group | Command | Purpose |
|---|---|---|
| Building | `build [debug\|release\|relwithdebinfo\|all] [-S] [-v] [-c] [-m [-t TYPE]]` | `cmake --build build --target deluge --config X`. Runs `configure` automatically if `build/` is missing. Extra args go straight to CMake, e.g. `-j 8`. |
| Building | `configure [-f] [-m] [-t dev\|nightly\|alpha\|beta\|rc\|release] [-DVAR=...]` | Generator is `Ninja Multi-Config`. Sets `-DCMAKE_CROSS_CONFIGS=all -DCMAKE_DEFAULT_CONFIGS=Debug;Release -DCMAKE_EXPORT_COMPILE_COMMANDS=TRUE`. With `-m` it adds `-DENABLE_VERSIONED_OUTPUT=TRUE -DRELEASE_TYPE=<type>`. `-f` nukes the build tree first. |
| Building | `clean`, `nuke`, `envclean` | Remove build artefacts; remove the whole build tree; remove stale toolchain envs. |
| Development | `test [-n]` | Host unit tests: configures `tests/` into `build/tests`, builds, then runs `ctest -C Debug`. |
| Development | `loadfw <build\|path.bin> [-p port] [-k hexkey] [-d ms] [-o file.syx]` | Sends firmware over MIDI SysEx. It goes to RAM only and is not persisted. |
| Development | `sysex-logging [outport [inport]]` | Shows the debug console over MIDI SysEx. |
| Development | `run [config] [-p port] [-f elf] [--no-strip]` | Builds, strips the ELF and uploads it over a USB CDC serial port with a `DLUP` frame (see 1.8). |
| Development | `midi-clock` | Measures the MIDI clock intervals the Deluge sends. |
| Debugging | `debug [-j] [-p swd\|jtag] [-i cmsis-dap] [-g 3333] [-d R7S721020]` | Starts a J-Link GDB server or OpenOCD. |
| Debugging | `openocd`, `gdb` | OpenOCD with DelugeProbe/esp-prog presets; a GDB remote session. |
| Misc | `format`, `license`, `docs`, `elfsize old.elf new.elf`, `sizediff`, `annotate_sdram`, `checkprdoc`, `exec`, `shell` | clang-format; add the GPL header; Doxygen; RAM/SDRAM section diff; size diff against the merge-base; and others. |

**Typical commands**
```bash
./dbt build release            # build/Release/deluge.{elf,bin,hex,map,nmdump}
./dbt build debug
./dbt build relwithdebinfo
./dbt build release -m -t nightly          # versioned file names
./dbt configure -DENABLE_SYSEX_LOAD=YES && ./dbt build release
./dbt configure -DENABLE_MATRIX_DEBUG=YES && ./dbt build debug
./dbt configure -f -DENABLE_RTT=OFF
./dbt test
./dbt elfsize old.elf new.elf
./dbt shell                    # shell with the toolchain on PATH
```

### 1.2 Toolchain (how it is fetched, and versions)

**Version pin:** `$U/toolchain/REQUIRED_VERSION` contains **`22`** (dbt-toolchain v22).

**Download, from `$U/scripts/toolchain/dbtenv.sh`**
- URL: `https://github.com/SynthstromAudible/dbt-toolchain/releases/download/v${VER}/dbt-toolchain-${VER}-${SYS}-${ARCH}.tar.gz`
  - `SYS` is `linux` or `darwin`.
  - `ARCH` is `x86_64` or `arm64`; `aarch64` is rewritten to `arm64`.
- Download uses curl, falling back to wget.
- The archive is unpacked to `toolchain/v22/<sys>-<arch>/`, and a `toolchain/current` symlink is created.
- It re-downloads if the `VERSION` file inside that directory is lower than the pin.
- On a fresh unpack it pip-installs `scripts/toolchain/requirements.txt` and runs `pre-commit install`.
- PATH gets: `python/bin`, `arm-none-eabi-gcc/bin`, `openocd/bin`, `clang-format`, `cmake/bin`, `ninja-build/bin`.

**Windows:** `https://github.com/SynthstromAudible/dbt-toolchain/releases/download/v$VER/dbt-toolchain-$VER-win32-x86_64.zip`, fetched by `scripts/toolchain/windows-toolchain-download.ps1`. `toolchain/win32-x64/openocd/` (OpenOCD 0.12.0 exe and DLLs) is checked in.

**Python packages** (`requirements.txt`): certifi 2026.7.22, setuptools 84.0.0, pyserial 3.5, python-rtmidi 1.5.8, ansi 0.3.7, pre-commit 4.6.2.

**Contents** (as documented in `website/src/content/docs/development/deluge/getting_started.md`; this text cites "DBT-Toolchain v10" for disk sizes, so it may be out of date for v22):
- xPack GNU Arm Embedded GCC **v13.2.1**
- OpenOCD v0.12.0
- Clang v17.0.6 (clang-format and clang-tidy only)
- CMake v3.26.5
- Ninja v1.11.1
- standalone Python v3.12.1

The exact GCC version inside v22 is **not recorded anywhere in the repo**. Check with `toolchain/current/arm-none-eabi-gcc/bin/arm-none-eabi-gcc --version`. Disk: about 1.3 GB toolchain, 1.5 GB total.

**CI image:** `ghcr.io/synthstromaudible/dbt-toolchain:v$(cat toolchain/REQUIRED_VERSION)`. Its entrypoint is dbt (`.github/workflows/build.yml`).

**CMake toolchain file:** `$U/scripts/cmake/CMakeToolchainDeluge.cmake`
- Compiler path is `${DBT_TOOLCHAIN_PATH}/toolchain/v${VER}/${host}-${arch}/arm-none-eabi-gcc/bin/arm-none-eabi-{gcc,g++,objcopy,size,nm,...}`.
- Sets `CMAKE_SYSTEM_NAME Generic` and `CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY`.

### 1.3 CMake structure

**Top level:** `$U/CMakeLists.txt` declares `project(Deluge VERSION 1.3.0)` and requires CMake ≥ 3.23.
- `add_subdirectory(lib)` fetches argon and etl.
- `add_executable(deluge)` links `argon` and `etl::etl`.
- `add_subdirectory(src)`.

**`src/CMakeLists.txt`**
- Sources: `main.c resetprg.c c_lib_alternatives.S malloc.c terminate.cpp memmove.c`.
- Subdirectories: `OSLikeStuff`, `deluge`, `RZA1`, `RTT`, `fatfs`, `NE10`, `lib` (eyalroz printf).

**`src/deluge/CMakeLists.txt`**
- `GLOB_RECURSE` over `*.S *.c *.cpp`, excluding `dsp/`, which is built as the static library `deluge_dsp` with `UNITY_BUILD true`.
- Generated code:
  - `gui/l10n` produces `deluge_strings` (`g_english.cpp`, `g_seven_segment.cpp`) from `english.json` and `seven_segment.json`;
  - `gui/menu_item/generate` produces `deluge_menus`;
  - `version` produces `deluge_version`.
- Links: `fatfs NE10 RZA1 eyalroz_printf deluge_dsp`.

**Language standards:** C23 and C++23 with GNU extensions (`DELUGE_C_STANDARD`/`DELUGE_CXX_STANDARD 23`).

**CMake options**

| Option | Default | Effect |
|---|---|---|
| `RELEASE_TYPE` | `dev` | One of `dev`/`nightly`/`alpha`/`beta`/`rc`/`release`; controls the version string. |
| `ENABLE_VERSIONED_OUTPUT` | `OFF` | Adds a semver suffix to output file names. |
| `ENABLE_RTT` | **`ON`** | SEGGER RTT, only in Debug/RelWithDebInfo. |
| `ENABLE_SYSEX_LOAD` | `OFF` | Defines `ENABLE_SYSEX_LOAD=1`. |
| `ENABLE_MATRIX_DEBUG` | `OFF` | Defines `ENABLE_MATRIX_DEBUG=1`. |
| `MAINTAINER_MODE` | `OFF` | Adds `-Wall -Wextra -Wabi -Wpedantic -fanalyzer`. |

Doxygen is optional (`dbt docs`, which pulls doxygen-awesome-css v2.2.1).

### 1.4 Configurations

| Config | Defines | Optimisation |
|---|---|---|
| Debug | `IN_HARDWARE_DEBUG=1`, `ENABLE_TEXT_OUTPUT=1`, `HAVE_RTT=1` (if `ENABLE_RTT`) | `-Og -ggdb3`, `-Wstack-usage=2000`, `-Werror=write-strings` |
| RelWithDebInfo | same defines as Debug (debug printing, RTT) | `-O2` with LTO, the same as Release |
| Release | `-DNDEBUG` (forced in the toolchain file); no text output | `-O2 -fsplit-loops -funswitch-loops -flto=auto -fuse-linker-plugin -flto-partition=none -fdevirtualize-at-ltrans` |

- `ENABLE_SEQUENTIALITY_TESTS` is on whenever `NDEBUG` is not defined (`src/definitions.h`).
- `ALPHA_OR_BETA_VERSION` is hard-coded to 1 in `src/definitions.h`. It is the most common preprocessor switch (146 uses) and adds extra error checking.

**OLED vs 7SEG:** there is no separate build target. A single binary detects the display at runtime with `display->haveOLED()` (used throughout `src/deluge`). A 7SEG display can be emulated on OLED hardware through the `EmulatedDisplay` community setting. Display strings come from `src/deluge/gui/l10n/english.json` and `seven_segment.json`.

**Hardware model:** `src/RZA1/cpu_specific.h` contains `#define DELUGE_MODEL DELUGE_MODEL_144_PAD // Change this as needed`; the alternative is `DELUGE_MODEL_40_PAD`.

### 1.5 Compiler and linker flags (all configs)

- **Architecture:** `-mcpu=cortex-a9 -mfpu=neon -mfloat-abi=hard -mthumb -mthumb-interwork -mlittle-endian`
- **Math:** `-funsafe-math-optimizations` ("required to use NEON instead of VFPv3") and `-ffast-math`
- **Code generation:** `-fsigned-char -D_GNU_SOURCE -ffunction-sections -fdata-sections -fno-inline-functions -DUSE_TASK_MANAGER -fmessage-length=0`
- **C++:** `-fno-rtti -fno-use-cxa-atexit -fno-threadsafe-statics`. Exceptions are not disabled; the linker script keeps `.ARM.extab`/`.ARM.exidx`.
- **Warnings:** `-Warray-bounds=1 -Wnull-dereference -Wparentheses -Wsequence-point -Werror=switch`
- **Link:** `-T linker_script_rz_a1l.ld -Map=... --cref --gc-sections --entry=start -nostartfiles --warn-common --stats`, plus LTO flags in Release/RelWithDebInfo.
- The linker script `/DISCARD/`s `libc.a libm.a libgcc.a libstdc++.a`. Replacements live in `src/c_lib_alternatives.S`, `src/malloc.c`, `src/memmove.c` and eyalroz printf.

### 1.6 Outputs (in `build/<Config>/`)

- `deluge.elf`: the full ELF, `-ggdb3` even in Release.
- `deluge.bin`: `objcopy -O binary -S`. **This is the file you flash.**
- `deluge.hex`: Intel hex.
- `deluge.map` and `deluge.nmdump` (`nm -S -C --size-sort`).
- `arm-none-eabi-size` output is printed after each build.

With `-m`, file names become e.g. `deluge-c1_3_0.bin` for a release, or `deluge-v1_3_0-nightly_2026_10_10-<sha>.bin`; dots are replaced with underscores (top-level CMakeLists lines 47–62).

### 1.7 Memory layout and size limits (`$U/linker_script_rz_a1l.ld`)

- **Target:** Renesas RZ/A1L, R7S721020, Cortex-A9 at 400 MHz.
- **Internal RAM:** region `RAM012L` is 0x20000000 + 0x300000. Usable space is `INTERNAL_RAM_START=0x20020000` to `INTERNAL_RAM_END=0x20300000`, about 2.875 MB.
  - Holds the TTB (32 KB), IRQ/FIQ/SVC/ABT stacks (8 KB each), `.bss`, `.reset`/`.text`/`.rodata`/`.data`, an internal heap, and a 32 KB program stack at the top.
  - `.frunk_bss` is placed below `.ttb_mmu1`.
- **SDRAM:** 0x0C000000, LENGTH 0x04000000 (64 MB; the comment says 32 MB).
  - Holds `.sdram_text`/`.sdram_data`/`.sdram_rodata` (string constants are moved here), `.exceptions`, `.sdram_bss`, and the external heap.
  - These sections are loaded `AT` the end of the image and relocated at boot.
- **SPI ROM:** 0x18000000 (32 MB). The bootloader copies the image from SPI flash to RAM.
- **Image header** (`src/RZA1/compiler/asm/start.S`): the vector table is followed by `code_start`, `code_end` (`end`) and `code_execute` words, then the signature string `".BootLoad_ValidProgramTest."`. The bootloader uses these (`DEF_USER_CODE_START`/`END`).
  - Load address is 0x20030000 (see `after_gdb_write` in the OpenOCD cfg).
- **Practical limit:** code plus data plus bss must fit in internal RAM below the 32 KB stack. Check headroom with `./dbt elfsize old.elf new.elf`, which reports internal and external heap sizes.
- `dbt run` limits uploads to 12 MiB (`MAX_UPLOAD_BYTES`).

### 1.8 Flashing and loading

1. **SD card (permanent).** Put a single `*.bin` (any name, e.g. `deluge.bin`) in the SD card root and remove any other `.bin` files. Hold SHIFT while powering on. The display shows "UPDA", a spinner, then "DONE". Interrupting it is safe. Sources: `website/src/content/docs/manual/device_overview/sd_card.mdx` and the README in `.github/workflows/publish.yml`, which also warns to update the **bootloader** first on never-updated units and links the wiki Update-guide.
2. **`dbt loadfw` over MIDI SysEx (RAM only).** You must first flash, via SD, a build made with `-DENABLE_SYSEX_LOAD=YES`. Then enable `COMMUNITY FEATURES > ALLOW INSECURE DEVELOP SYSEX MESSAGES (SYSX)`, which shows an 8-hex-digit key; the key is cached in `.deluge_hex_key`.
   - Protocol (`scripts/tasks/task-loadfw.py`): header `F0 00 21 7B 01 03 01`, then a 7-bit-packed handshake, a segment number and a 512-byte chunk. A final `03 02` message carries handshake, length and CRC32.
   - Firmware side: `src/deluge/io/midi/sysex.cpp`, functions `loadPacketReceived` and `loadCheckAndRun`.
   - A power cycle returns to the firmware flashed from SD.
3. **`dbt run` over USB CDC "Dev Upload" (`scripts/tasks/task-run.py`).** Frame format: `"DLUP"`, version 1, flags, len u32, crc32 u32, stripped ELF. The device must be USB VID 0x16D0, PID 0x0EDA and sitting on an "app-loader boot menu with DEV MODE: ON".
   - The comments reference an external "deluge-sdk cargo-deluge" loader.
   - **None of the device-side code exists in this repo** (grep for DLUP/devupload in `src` finds nothing), so it needs a separate, newer bootloader or app-loader. VSCode tasks "Run (USB, dev mode)" exist.
4. **JTAG/SWD** through GDB `load` (J-Link or OpenOCD). See section 6.

### 1.9 Version files

- The version comes from `project(Deluge VERSION 1.3.0)` in `$U/CMakeLists.txt`.
- `src/deluge/version/CMakeLists.txt` generates `version.cpp.gen` from `version.cpp.in` at build time, using git `rev-parse --short` and `status --porcelain`:
  - release builds get `kFirmwareVersionString = "c1.3.0"`;
  - other builds get `"1.3.0-<type>-<sha>[-dirty]"`;
  - `kFirmwareVersionStringShort = "c1.3.0"` and `kCommitShort` are also generated.
- `version.h.in` produces `FIRMWARE_VERSION_MAJOR/MINOR/PATCH`.
- `src/deluge/util/firmware_version.h.in` defines `FirmwareVersion` with `Type::OFFICIAL=0` and `COMMUNITY=254`. Any community version compares as newer than any official one. Strings are parsed as "4.1.4-beta" (official) or "c1.1.0-alpha" (community, leading `c`).

---

## 2. Tests and CI

### 2.1 Host tests (`$U/tests/`)

**Top level:** `tests/CMakeLists.txt` is a separate CMake project, `DelugeTests`.

**`unit/`: CppUTest** (pinned at commit `eccbc21`; etl 20.39.4)
- One executable, `UnitTests`.
- Test files: scheduler, lfo, scale, value_scaling, clip_iterator, function, sync, chord, time, clock_output_scheduler, name_compare, default_name, encoder_acceleration, rgb, notes_state, iterance_migration.
- Built with `IN_UNIT_TESTS=1` against selected real sources (`modulation/lfo.cpp`, `model/scale/*`, `model/sync.cpp`, `gui/ui/keyboard/chords.cpp`, `playback/clock_output_scheduler.cpp`, and others) plus mocks in `unit/mocks/`.

**`32bit_unit_tests/`: CppUTest, Linux only**, compiled with `-m32` because the memory tests assume 32-bit pointers.
- `MemoryManagerTests` covers `src/deluge/memory/*`.
- `SmallPointerTests` covers containers such as the open-addressing hash table and the lazy param node vector.

**`spec/`: CppSpec** (toroidal-code/cppspec main tarball)
- Specs: object_pool, semver, string, tracking_allocator, starfield, rainfall.
- `StarfieldPreview` and `RainfallPreview` are visual previews and are not registered as tests.

**`qemu/`:** a separate project for ARMv7 hard-float (`-mcpu=cortex-a9 -mfpu=neon`), run under qemu-user. Specs: `fixedpoint_spec`, `fixedpoint_vfp_spec`.

**Other test directories**
- `fuzz/`: a libFuzzer harness, `memmove_fuzz.c`, for the custom memmove.
- `integration/usbmidi/`: manual Python tests on real hardware (`test_usb_config.py`, `test_midi_config.py`, `handraulic_test_midi_io.py`).

**Commands**
```bash
./dbt test                       # configure, build, ctest -C Debug (build/tests)
# or, without dbt (as CI does):
CC=gcc-14 CXX=g++-14 cmake -B build -S tests -G Ninja && cmake --build build
ctest --test-dir build --output-on-failure
build/unit/UnitTests -ojunit; build/32bit_unit_tests/MemoryManagerTests; build/32bit_unit_tests/SmallPointerTests
# ARM via QEMU (needs gcc-14-arm-linux-gnueabihf and qemu-user):
CC=arm-linux-gnueabihf-gcc-14 CXX=arm-linux-gnueabihf-g++-14 cmake -B build -S tests/qemu -G Ninja && cmake --build build && ctest --test-dir build
```

### 2.2 CI workflows (`$U/.github/workflows/`, all present)

| Workflow | What it does |
|---|---|
| `build.yml` (reusable) | `docker run ghcr.io/synthstromaudible/dbt-toolchain:v22 build --verbose --tag-metadata --type <tag> <Release\|Debug\|RelWithDebInfo>`. Then `git diff --exit-code` (generated files must be committed) and uploads `build/<type>/*`. |
| `pr-build.yml` | On PRs to `next`, `release/**` or `main`, and on pushes to `synthstrom-official`: Release and Debug build checks. |
| `tests.yml` | On PRs to `main` or `release/**`. x86 job: gcc-14 multilib, ctest, 32-bit and unit CppUTest with JUnit output. QEMU job: arm-linux-gnueabihf-gcc-14. |
| `test-results.yml` | Publishes JUnit results (EnricoMi action). |
| `format-check.yml` | clang-format 19 on `./src` (c, cpp, h, hpp); Ruff 0.16.0 format and lint on scripts, contrib, tests and src. |
| `clang-tidy.yml` | clang-tidy 19 annotations on PRs, using `./dbt configure` to get a compile database. |
| `beta-build.yml` | Daily at 00:14 from `main` if there were new commits; publishes a "beta" pre-release. |
| `nightly-build.yml` | Builds from `next`; the schedule is commented out. |
| `publish.yml` | Pre-release publishing for tags `nightly`/`beta`; branches include `release/1.1`, `1.2`, `1.3` and `community`. |
| Others | Website (Astro/pnpm): `deploy-website.yml` (also deploys Doxygen to GitHub Pages), `pr-build-website.yml`, `format-website.yml`. Labelling: `label-issues.yml`, `label-prs.yml`, `sync-labels.yml`. |

**Pre-commit** (`$U/.pre-commit-config.yaml`): actionlint v1.7.7, ruff v0.16.0, clang-format v19.1.7. Style files: `.clang-format`, `.clang-tidy`, `.editorconfig`.

---

## 3. Feature flags

### 3.1 Runtime "Community Features"

**Code:** `$U/src/deluge/model/settings/runtime_feature_settings.{h,cpp}`; the menu is in `src/deluge/gui/menu_item/runtime_feature/`.
- Settings are stored in **`SETTINGS/CommunityFeatures.XML`** on the SD card. A legacy root `CommunityFeatures.XML` is migrated with `f_rename`.
- Unknown keys are preserved (`unknownSettings`).
- Access: `runtimeFeatureSettings.get(RuntimeFeatureSettingType::X)` or `.isOn(X)`.
- Menu path: SHIFT + SELECT, then `COMMUNITY FEATURES` (OLED) or `FEAT` (7SEG).

**Adding a setting:** add a value to the `RuntimeFeatureSettingType` enum (before `MaxElement`), call `SetupOnOffSetting(...)` in `init()`, and add an l10n string.

| Enum | xmlName | Default | 7SEG |
|---|---|---|---|
| DrumRandomizer | drumRandomizer | On | DRUM |
| Quantize | quantize | On | QUAN |
| FineTempoKnob | fineTempoKnob | On | TEMP |
| CatchNotes | catchNotes | On | CATC |
| DeleteUnusedKitRows | deleteUnusedKitRows | On | UNUS |
| AltGoldenKnobDelayParams | altGoldenKnobDelayParams | Off | DELA |
| DevSysexAllowed | devSysexAllowed | Off | SYSX |
| SyncScalingAction | syncScalingAction | SyncScaling (or Fill) | SCAL |
| HighlightIncomingNotes | highlightIncomingNotes | On | HIGH |
| DisplayNornsLayout | displayNornsLayout | Off | NORN |
| ShiftIsSticky | stickyShift | Off | STIC |
| LightShiftLed | lightShift | Off | LIGH |
| EnableDX7Engine | EnableDX7Engine | Off | DX7 |
| EmulatedDisplay | emulatedDisplay | Hardware (or Toggle / OnBoot) | EMUL |
| EnableKeyboardViewSidebarMenuExit | enableKeyboardViewSidebarMenuExit | Off | EXIT |
| EnableLaunchEventPlayhead | enableLaunchEventPlayhead | On | PLAY |
| DisplayChordKeyboard | displayChordKeyboard | Off | CHRD |
| AlternativePlaybackStartBehaviour | alternativePlaybackStartBehaviour | Off | STAR |
| EnableGridViewLoopPads | enableGridViewLoopPads | Off | LOOP |
| AlternativeTapTempoBehaviour | alternativeTapTempoBehaviour | Off | TAPT |
| HorizontalMenus | enableHorizontalMenus | On | – |
| TrimFromStartOfAudioClip | trimFromStartOfAudioClip | On | TRIM |
| ShowBatteryLevel | showBatteryLevel | On | BATT |
| RoundedCorners | roundedCorners | On | – |
| ShortcutOverlay | shortcutOverlay | On | – |

The 7SEG codes and descriptions are in `website/src/content/docs/features/community_features.mdx` §5 (lines 1324–1393). `ShortcutOverlay` is in the code but is not documented there.

### 3.2 Compile-time switches

- **Documented in §7 of `community_features.mdx`:** `ENABLE_SYSEX_LOAD` and `ENABLE_MATRIX_DEBUG`, plus a placeholder "FEATURE_...". There is no `FEATURE_*` scheme in use.
- **Build-system defines:** `ENABLE_RTT` (CMake), giving `HAVE_RTT`; `ENABLE_TEXT_OUTPUT`, `IN_HARDWARE_DEBUG`, `NDEBUG`, `USE_TASK_MANAGER`, `IN_UNIT_TESTS`.
  - `ENABLE_TEXT_OUTPUT` defaults to 0 in `src/deluge/drivers/uart/uart.h` and is set to 1 in Debug/RelWithDebInfo. It gates the `D_PRINTLN`/`D_PRINT`/`D_PRINT_RAW` macros in `src/deluge/io/debug/log.h`.
- **Source-level switches** (count of uses in `src/deluge`):

| Switch | Uses | Defined in |
|---|---|---|
| `ALPHA_OR_BETA_VERSION` | 146 | `src/definitions.h`, hard-coded to 1 |
| `ENABLE_SEQUENTIALITY_TESTS` | 15 | follows `NDEBUG` |
| `TEST_VECTOR*` | – | `definitions_cxx.hpp`, commented out |
| `INPUT_ENABLE_REPITCHED_BUFFER` | 16 | |
| `TIME_STRETCH_ENABLE_BUFFER` | 15 | |
| `MEASURE_HOP_END_PERFORMANCE` | 12 | |
| `TEST_GENERAL_MEMORY_ALLOCATION` | 10 | |
| `PITCH_DETECT_DEBUG_LEVEL` | 9 | |
| `DO_AUDIO_LOG` | 8 | |
| `SCHEDULER_DETAILED_STATS` | – | |
| `REPORT_CPU_USAGE` | – | |
| `REPORT_LOAD_TIME` | – | |
| `OLED_LOG_TIMING` | – | |
| `SD_TEST_MODE_ENABLED` | – | |
| `RECORD_TEST_MODE` | – | |
| `DELUGE_MODEL` | – | `src/RZA1/cpu_specific.h` |
| `HAVE_NEON` | – | `src/deluge/dsp/dx/fm_op_kernel.cpp` |

There is no compile-time switch that removes whole user features. Features are compiled in and gated at runtime.

### 3.3 Features added on top of the official Synthstrom 4.x firmware

**Source:** `website/src/content/docs/features/community_features.mdx`, 1424 lines, with badges c1.0 to c1.3.
- §2, UI changes in c1.3: velocity rendering, horizontal menus, layered shortcuts, favourites, 7SEG folder indicator.
- §3, general improvements (3.1–3.37): patch-cable resolution, MPE, MIDI (extra USB MIDI ports, CC learn of global commands, takeover modes, MIDI follow, and more), tempo and swing, alternative gold-knob delay params, kits, mod wheel, value pop-ups, stutter rate automation, metronome volume, startup song/template, pad brightness persistence, bipolar knob LEDs, audio clip source and monitoring, sample slice default, hold-press time, eased zoom, exit menus by holding back, automated audio export, launch-event playhead and countdown, new clip creation UI, clip settings menu, accessibility defaults, arranger playback from a clip, threshold recording, voice count, clip names, selectable accidental, battery level.
- §4.1, Session: compressors, row colour, fill/once clips, catch notes, **Grid View**, **Performance View**, master chromatic transpose, VU meter, song macros.
- §4.2, Clip FX: filters, stereo chorus, dimension, warbler, **Grain FX**, warble LFO, wavefolding, per-clip stutter, reverb improvements (Freeverb and Mutable models), launch exclusively.
- §4.3, Instrument clips: new LFO shapes and sync, quantize/humanize, fill modes, **Automation View**, row probability, nudge, **advanced arpeggiator**, randomizer, velocity view, iterance/probability/fill, note and row editor, sample auto-load, save/load patterns.
- §4.4, Synth/MIDI/CV: keyboard view (row step, keyboard API, highlight incoming notes, norns layout, sidebar controls, chord, chord library and piano layouts) and scales.
- §4.5, Synth/Kit: mod matrix, unison stereo spread, waveform loop lock, copy rows, paste gently, row play direction, **DX7 synth**, more envelopes and LFOs, send MIDI.
- §4.6, Kits: keyboard view, drum randomizer, manual slicing (lazy chop), batch delete rows.
- §4.7, MIDI: save/load MIDI presets, CC labels, MIDI device definition files.
- §4.8, CV: expression.
- §4.9, Audio clips: shift clip, trim from start.
- §4.10: Lumi Keys Studio Edition integration.
- §6, SysEx: screen mirroring (#174/#192), debug log forwarding (#215), firmware load (#295). The file-system SysEx protocol is in `development/deluge/SysExProtocolNotes.md`.

**Per-feature pages:** `website/src/content/docs/features/` contains `arpeggiator`, `audio_export`, `automation_view`, `automation_view_velocity_editor`, `chord_keyboard`, `dx_synth`, `looping_in_grid_view`, `midi_device_definition_files`, `midi_follow_mode`, `note_noterow_editor`, `performance_view`, `save_load_patterns`.

---

## 4. Current development state

**Version:** c1.3.0 "Derbyshire", marked "Upcoming" (`CMakeLists.txt` line 8; `website/src/content/docs/changelogs/CHANGELOG.mdx` line 33).
- Latest release: **c1.2.1 Chopin**. Earlier: c1.2.0 Chopin, c1.1.x Beethoven, c1.0.x Amadeus.
- Release branches referenced: `release/1.1`, `release/1.2`, `release/1.3`; integration branches `next` and `main`.
- The root `CHANGELOG.md` points to `https://delugecommunity.com/changelogs/changelog/22`.

**c1.3 changelog themes:** audio output modes, Edit Name menu, new clip-creation flow, MIDI Follow moved from flash to `SETTINGS/MIDIFollow.XML` (delete old files), velocity-shaded notes, independent probability/iterance/fill, note and row editor menus with custom iterance, layered shortcuts. Further sections cover sound engine, UI, sequencer, MIDI and SD card.

**`docs/dev`:** the stubs point to `website/src/content/docs/development/deluge/`:
- `getting_started.md`: clone, DBT, toolchain contents, build configs.
- `tools.md`: IDE configs, loadfw, sysex-logging, `ENABLE_MATRIX_DEBUG`, elfsize, and the Crash Reader Discord bot. On a crash, pad LEDs encode the LR and stack pointers; decode with `arm-none-eabi-addr2line -Capife build/Release/deluge.elf 0x...`. The bot repo is github.com/0beron/delugeqr.
- `guidelines.md`: contribution and code guidelines.
- `ux_principles.md`.
- `SysExProtocolNotes.md`: JSON-over-SysEx file-system protocol (open, close, read and write block, directory listing, mkdir, delete, rename, copy, move, timestamp, ping, error codes).
- `additional_info.md`: links to the wiki (uploading/debugging/RAM-flash explanation, codebase intro, hardware-mod guide, FAQ) and to Doxygen at delugecommunity.com/doxygen.

**`docs/CONTRIBUTING.md`:** includes an explicit **LLM policy**. Do not use agents to open PRs or comment on them, do not use an LLM to write PR descriptions, and do not open PRs with test plans you have not followed. Related repos: DelugeProbe (litui/delugeprobe) and dbt-toolchain.

**Other contrib material:** `contrib/midi_follow` templates, `contrib/sd_card/MIDI_DEVICES`, `contrib/midi2deluge` (MIT, busa-projects), `contrib/dx7/sysex-format.txt`, `contrib/rza1.svd`, `contrib/doc/pinmap`.

### Third-party libraries

`$U/lib/` only contains a `CMakeLists.txt` that FetchContents two libraries. The rest are vendored in `src/`.

| Library | Location | Purpose | License (from headers unless noted) |
|---|---|---|---|
| **argon** (github.com/stellar-aria/argon @ `cae5738`) | `lib/CMakeLists.txt`, fetched | C++ NEON SIMD wrapper, used by the DSP code | Not in repo; likely MIT, **verify upstream** |
| **ETL** (ETLCPP/etl 20.40.0; 20.39.4 in tests) | `lib/CMakeLists.txt`, fetched | Embedded Template Library: fixed-capacity containers | MIT (per the upstream project) |
| **NE10** | `src/NE10/` | ARM NEON DSP library (FFT and others) | BSD 3-clause, "Copyright 2011-16 ARM Limited" |
| **SEGGER RTT** | `src/RTT/` | Real Time Transfer debug channel | SEGGER BSD-style ("All rights reserved", redistribution permitted) |
| **FatFs R0.14b** (ChaN) | `src/fatfs/` | FAT32 SD card file system | ChaN 1-clause BSD-style |
| **eyalroz printf** | `src/lib/printf.{c,h}` (target `eyalroz_printf`) | Non-allocating printf | MIT |
| **gsl** | `src/gsl/gsl` | Single header with `gsl::owner<T>` for clang-tidy; not the full Microsoft GSL | N/A |
| **Renesas RZ/A1 BSP and USB stack** | `src/RZA1/` (and the linker script base) | Drivers: bsc, cache, gpio, intc, mtu, ostm, rspi, sdhi, spibsc, ssi, uart, usb (basic and hmidi) | Renesas proprietary disclaimer ("only intended for use with Renesas products") **inside a GPL project** |
| **MSFA / Dexed FM engine** | `src/deluge/dsp/dx/` | DX7 engine | `fm_core`, `env` and others: Apache-2.0 (Copyright 2012 Google). `EngineMkI.*`: GPLv3 (Pascal Gauthier, Dexed) |
| **Mutable Instruments reverb** | `src/deluge/dsp/reverb/mutable.hpp` | Reverb model | Copyright 2014 Emilie Gillet and 2023 Katherine Whitlock (Gillet's code is MIT) |
| **Freeverb** | `src/deluge/dsp/reverb/freeverb/` | Reverb model | Public domain (Jezar, 2000) |
| **Test only** | CppUTest (BSD-3), CppSpec (toroidal-code), doxygen-awesome-css (MIT) | | |

---

## 5. Licensing (GPLv3) and what it means for a fork

- `$U/LICENSE` is the **GNU GPL v3** (29 June 2007). File headers say "Copyright © 2014/2015-2023 Synthstrom Audible Limited … either version 3 of the License, or (at your option) any later version". `./dbt license -r` adds this header to new files.
- **Distributing binaries** (a `.bin` from a fork) requires offering the Corresponding Source under GPLv3 (§6). That source includes the build scripts needed to produce the binary: dbt, the CMake files, the linker script, and the toolchain version pin. Keep the LICENSE file, the copyright notices and the GPL headers, and mark modified files with a notice and date (§5a).
- The whole combined firmware is GPLv3. Any code you add and link in must be GPLv3-compatible:
  - Compatible with GPLv3: MIT, BSD, Apache-2.0, public domain and ETL MIT.
  - GPLv2-only code is **not** compatible.
- **Renesas BSP caveat:** the Renesas files have a restrictive disclaimer. Upstream ships them anyway; a fork inherits the same unclear status.
- **SEGGER RTT** is redistributable but carries a "strongly recommends to not make any changes" note.
- **Anti-tivoization (§6, Installation Information):** this matters only for consumer devices with locked boot. The Deluge accepts unsigned SD images, so it is not a practical issue.
- **Patents:** §11 gives a patent licence from contributors.
- **Names and branding:** GPL does not grant trademark rights. Avoid presenting a fork as official "Synthstrom" or "Deluge" firmware. `FirmwareVersion::Type` reserves `OFFICIAL` and `COMMUNITY=254`; a fork could pick its own type value or version prefix so it is not confused with community builds.
- The README links Synthstrom's open-source statement (synthstrom.com/open). No trademark policy file exists in the repo.

---

## 6. Debugging

### 6.1 RTT (SEGGER Real Time Transfer)
- Sources: `src/RTT/` (`SEGGER_RTT.c`, `SEGGER_RTT_printf.c`, `SEGGER_RTT_ASM_ARMv7M.S`, `SEGGER_RTT_Conf.h`), built as the static library `RTT`.
- Linked only when `ENABLE_RTT=ON` (the default) **and** the config is Debug or RelWithDebInfo. This defines `HAVE_RTT=1`.
- `src/deluge/drivers/uart/uart.c`: `uartPrintln` and friends call `SEGGER_RTT_WriteString(0, …)` when `HAVE_RTT` is set, and otherwise go to the MIDI UART buffer. All of it is gated by `ENABLE_TEXT_OUTPUT`.
- In code: `#include "io/debug/log.h"` then `D_PRINTLN("x=%d", x);`. `logDebug` in `src/deluge/io/debug/log.cpp` prefixes system time and `file:line`, then calls `Debug::println`.
- Viewing: VSCode Cortex-Debug `rttConfig` (port 0 console, `IDE_Configs/vscode/launch.json`), J-Link RTT Viewer, or SEGGER Ozone.

### 6.2 SysEx debug (no probe needed)
- `./dbt sysex-logging [port]` sends `F0 00 21 7B 01 03 00 01 F7` to enable logging, then prints messages with the header `F0 00 21 7B 01 03 40 00`.
- Release builds send no debug text, so use Debug or RelWithDebInfo.
- Firmware side: `Debug::sysexDebugPrint` in `src/deluge/io/midi/sysex.cpp`; namespace 3 is "debug". Commands: 0 = logging config, 1 = firmware segment, 2 = load and run.
- Also available: SysEx screen mirroring, and `./dbt loadfw` (section 1.8).
- Pad logging: `./dbt configure -DENABLE_MATRIX_DEBUG=YES`, which prints lines like `@matrix_driver.cpp:71: UI=…,PAD_X=..,PAD_Y=..,VEL=..`.

### 6.3 SEGGER J-Link
- `./dbt debug -j [-p swd]` runs `JLinkGDBServerCL -device R7S721020 -endian little -if SWD … -port 3333`; the Windows fallback path is `C:\Program Files\SEGGER\JLink\`.
- **VSCode** (`IDE_Configs/vscode/launch.json`):
  - "Cortex-Debug Load/Run Debug" and "Cortex-Debug Load/Run RelWithDebInfo": servertype jlink, device R7S721020, SWD, `svdFile contrib/rza1.svd`; launch, reset and restart all run `monitor reset` then `load`; RTT is enabled.
  - "CppDBG Attach/Load/Run": JLinkGDBServerCL args `-select USB -device R7S721020 -endian little -if SWD -speed auto -noir -LocalhostOnly -port 3333 -SWOPort 2332 -TelnetPort 2333`.
  - Also "Debug Tests", "LLDB Attach Debug" and "Cortex-Debug OpenOCD".
- **VSCode tasks** (`tasks.json`): Build Debug/Release/RelWithDebInfo, "Run (USB, dev mode)", "Run Release (USB, dev mode)", "Run JLink GDB Server", "Run OpenOCD GDB Server".
- **SEGGER Ozone projects:** `contrib/debug/Debug.jdebug`, `RelWithDebInfo.jdebug`, `Release.jdebug`. They set device R7S721020, SWD at 4 MHz, `Cortex-A9.svd`, open `../../build/Debug/deluge.elf`, and set the trace core clock to 400 MHz.
- **CLion:** `IDE_Configs/clion/` (`debug-profiles.xml`, `runConfigurations`).

### 6.4 OpenOCD

Configs are in `$U/scripts/debug/openocd/`:
- `deluge-swj-swd.cfg` and `deluge-swj-jtag.cfg` (DelugeProbe or CMSIS-DAP), `deluge-swd.cfg`, `deluge-jtag.cfg` (esp-prog);
- `interface/delugeprobe.cfg` (sources `interface/cmsis-dap.cfg`) and `interface/esp-prog.cfg`.

Settings in `deluge-swj-swd.cfg`:
- `DAP_TAPID 0x3ba02477`, chip name `r7s721020`, `adapter speed 10000`.
- Target: `cortex_a … -dbgbase 0x80030000` (RAM is mapped differently from the debugger's view).
- The `after_gdb_write` hook sets `pc 0x20030000, sp 0x10`.
- `reset_config srst_only srst_nogate`, `gdb_breakpoint_override hard`, semihosting enabled, `cortex_a maskisr on`, `dacrfixup on`.

Commands:
```bash
./dbt openocd                     # DelugeProbe, SWD (map in task-openocd.py: delugeprobe {swd,jtag}, esp-prog {jtag})
./dbt debug -p swd -i cmsis-dap   # openocd -f interface/cmsis-dap.cfg -f scripts/debug/openocd/deluge-swj-swd.cfg -c "gdb_port 3333"
./dbt gdb                          # arm-none-eabi-gdb remote (gdbinit: scripts/debug/gdbinit)
arm-none-eabi-gdb build/Debug/deluge.elf -ex "target extended-remote :3333" -ex "monitor reset" -ex load
```

Other tools:
- `contrib/debug/heap_state.py`: a GDB Python script that dumps the GMA heap. Use with `source ./contrib/debug/heap_state.py`.
- The RZ/A1 register SVD is `contrib/rza1.svd`.
- The DelugeProbe hardware lives at github.com/litui/delugeprobe.

---

## Main file paths (all under `$U`)

- **Build:** `dbt`, `dbt.py`, `dbt.cmd`, `Makefile`, `CMakeLists.txt`, `lib/CMakeLists.txt`, `src/CMakeLists.txt`, `src/deluge/CMakeLists.txt`, `src/deluge/dsp/CMakeLists.txt`, `scripts/cmake/CMakeToolchainDeluge.cmake`, `linker_script_rz_a1l.ld`, `src/RZA1/compiler/asm/start.S`
- **Toolchain:** `toolchain/REQUIRED_VERSION`, `scripts/toolchain/dbtenv.sh`, `scripts/toolchain/windows-toolchain-download.ps1`, `scripts/toolchain/requirements.txt`
- **Tasks:** `scripts/tasks/task-{build,configure,test,loadfw,run,sysex-logging,debug,openocd,gdb,elfsize,license}.py`
- **Version:** `src/deluge/version/{CMakeLists.txt,version.cpp.in,version.h.in}`, `src/deluge/util/firmware_version.h.in`
- **Feature flags:** `src/deluge/model/settings/runtime_feature_settings.{h,cpp}`, `src/definitions.h`, `src/RZA1/cpu_specific.h`, `src/deluge/drivers/uart/uart.{c,h}`, `src/deluge/io/debug/log.{h,cpp}`, `src/deluge/io/midi/sysex.cpp`
- **Tests and CI:** `tests/CMakeLists.txt`, `tests/unit/CMakeLists.txt`, `tests/32bit_unit_tests/CMakeLists.txt`, `tests/spec/CMakeLists.txt`, `tests/qemu/CMakeLists.txt`, `.github/workflows/{build,pr-build,tests,format-check,clang-tidy,beta-build,nightly-build,publish}.yml`, `.pre-commit-config.yaml`
- **Docs:** `website/src/content/docs/features/community_features.mdx`, `website/src/content/docs/changelogs/CHANGELOG.mdx`, `website/src/content/docs/development/deluge/*.md`, `website/src/content/docs/manual/device_overview/sd_card.mdx`, `docs/CONTRIBUTING.md`, `LICENSE`
- **Debug:** `scripts/debug/openocd/*.cfg`, `scripts/debug/gdbinit`, `IDE_Configs/vscode/{launch,tasks}.json`, `IDE_Configs/clion/`, `contrib/debug/*.jdebug`, `contrib/debug/heap_state.py`, `contrib/rza1.svd`, `src/RTT/`

## Open questions (not answerable from the repo)

- The exact GCC version in toolchain v22. The docs say 13.2.1, but that text dates from toolchain v10.
- The license of argon.
- Where the device-side dev-upload loader that `dbt run` and its "DLUP" frame depend on lives (the comments mention "deluge-sdk cargo-deluge").
- The bootloader's own source; it is not in this repo.
