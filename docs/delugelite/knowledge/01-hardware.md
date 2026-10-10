# Synthstrom Deluge community firmware: hardware reference derived from the code

Repo root (called `UP` below): `<upstream>`, git HEAD `2cd3091a`. Every path below is relative to `UP`, written as `file:line`.

Everything here comes from source code, with one exception: the chip part numbers. The firmware never names the codec, CV DAC, PIC, SDRAM or CPU package. Those names come only from the repo's pin-map generator script, `contrib/doc/pinmap/generate.py` ("pinmap" below), and are marked as such. Anything I could not find in code is marked **UNKNOWN**.

---

## 0. Things that contradict each other or are unresolved

1. **SDRAM size:** the linker comment says "SDRAM 32MB", but `LENGTH = 0x04000000` is 64 MB (`linker_script_rz_a1l.ld:65`). The code uses 64 MB:
   - `resetprg.c:191` calls `userdef_bsc_cs2_init(0); // 64MB, hardcoded`.
   - `EXTERNAL_MEMORY_BEGIN/END` = 0x0C000000 to 0x10000000 (`src/RZA1/cpu_specific.h:122-123`).
   - The allocator comment says "3MB ram … external 64MB SDRAM" (`src/deluge/memory/general_memory_allocator.h:40`).
2. **XTAL / MTU timer rates:**
   - `definitions.h:60` tests `#if DELUGE_MODEL >= DELUGE_MODEL_144_G`, but `DELUGE_MODEL_144_G` is never defined anywhere. In the preprocessor it evaluates as 0, so `XTAL_SPEED_MHZ = 13007402` (the "1.65% lower, for SSCG" value; the alternative is 13225625). The value is in Hz despite the name.
   - The comments on timer rates disagree with each other: "32 ticks/ms" (`definitions.h:44`) vs "33 ticks per millisecond" (`main.c:94`, and `msToSlowTimerCount` = ms*33 in `cfunctions.c:232`). Superfast is described as "32.792 ticks/µs (33.792 MHz)" (`definitions.h:48`) and "33.792 ticks per microsecond" (`main.c:100`).
3. **CV DAC vendor:** the code comment says "As instructed by the AD DAC's datasheet" (`processing/engines/cv_engine.cpp:50`). The pinmap says **MAX5136** (`contrib/doc/pinmap/generate.py:422`).
4. **Undefined startup symbols:** `initsct.S:44-45` loads `address_start_data_RAM` and `address_end_data_RAM`. Neither is defined in the linker script or anywhere else in the repo, and no CMake `--defsym` adds them. **UNKNOWN** how these resolve at link time. Only `address_start_data_ROM` and `address_end_data_ROM` exist (`ld:210,219`).
5. **Allocator size comments are wrong:**
   - `RESERVED_EXTERNAL_SMALL_ALLOCATOR = 0x00020000 // 200k` is actually 128 KiB.
   - `RESERVED_INTERNAL_SMALL = 0x00010000 // 200k` is 64 KiB, and the constant is unused.
   - Both at `general_memory_allocator.h:32-33`.
6. **L2 cache comment vs behaviour:** `resetprg.c:185-187` says L2 is "currently instruction caching only". The L2 data ways are in fact locked at boot (`cache.c:245`) and then unlocked at the end of init by `L2CacheUnlockData()` (`deluge/deluge.cpp:907`).
7. **The linker script is inherited from the RZ/A1H Renesas example** (header comment `ld:42-46`, "10-Mbyte on-chip RAM"). The memory region actually used is `RAM012L` = 0x20000000, length 0x300000 (3 MB) (`ld:77`).

---

## 1. CPU

| Item | Value | Source |
|---|---|---|
| SoC | Renesas RZ/A1L. Package name "R7S721020VCFP (RZ/A1L)" comes from the pinmap only | `cpu_specific.h:21` ("RZ/A1"), `generate.py:1065` |
| Core | ARM Cortex-A9, NEON, hard-float, Thumb-2 with interwork, little-endian | `scripts/cmake/CMakeToolchainDeluge.cmake:56-63` (`-mcpu=cortex-a9 -mfpu=neon -mfloat-abi=hard -mthumb -mthumb-interwork -mlittle-endian`), plus `-funsafe-math-optimizations` "to use NEON instead of VFPv3" (`:68-70`) |
| Multicore guard | Reads MPIDR; any core other than 0 sits in WFI | `src/RZA1/compiler/asm/reset_handler.S:61-66` |
| Board model macro | `DELUGE_MODEL = DELUGE_MODEL_144_PAD` (1); the 40-pad model is 0 | `cpu_specific.h:23-26` |

### Clocks (CPG)

Set in `src/RZA1/peripheral_init_basic.c:84-113`, called from `reset_handler.S:218-219`:
- `FRQCR = 0x1035`, described as "PLL(x30), I:G:B:P1:P0 = 30:20:10:5:5/2".
- `FRQCR2 = 0x0001`.
- The comment gives: input 13.33 MHz, CKIO 66.67, I (CPU) 400.00, G 266.67, B 133.33, P1 66.67, P0 33.33 MHz.
- `SYSCR3 = 0x0F` enables writes to the on-chip data-retention RAM.
- The Power Control Register at `0x3fffff80` is set to 1 ("standby_mode_en").

How each clock is used:
- **P1:** the code assumes 66.67 MHz for RSPI (`rspi.c:98-99`) and SDHI (`sd_dev_low.c:397-415`). The UART computes P1 as `XTAL_SPEED_MHZ*5` (`sio_char.c:171`).
- **P0:** MTU2 clock, documented as "P0 (33.33MHz)" (`src/RZA1/mtu/mtu.h:71-74`). The OSTM-based scheduler clock uses `DELUGE_CLOCKS_PER 33330000` (`OSLikeStuff/timers_interrupts/clock_type.h:10`).
- The time-conversion helpers imply P0 = 2.5 × XTAL, e.g. `superfastTimerCountToNS = count*400000000/XTAL` (`deluge/util/cfunctions.c:216-230`).

### Module clocks (STB_Init)

`src/RZA1/stb/stb.c`, called from `resetprg.c:135`. In these registers a 0 bit means the clock is supplied.

| Register | Value | Clocked modules |
|---|---|---|
| STBCR2 | 0b01101010 | — |
| STBCR3 | 0b11110101 | MTU2 |
| STBCR4 | 0b00000111 | SCIF0-4 |
| STBCR5 | 0b11111100 | OSTM0/1 |
| STBCR6 | 0b01111111 | A/D |
| STBCR7 | 0b00111101 | DVDEC0/1, USB0 (USB1 off) |
| STBCR8 | 0xFF | all off |
| STBCR9 | 0b11110111 | SPIBSC0 |
| STBCR10 | 0b00011111 | RSPI0-2 |
| STBCR11 | 0b11011111 | SSIF0 |
| STBCR12 | 0b11111011 | — |

SDHI init later writes `STBCR12 = 0xF0`, enabling all four SDHI clocks (`sd_dev_low.c:172,215`).

### Caches and MMU

- **Reset path:**
  - Disables I-cache, D-cache and MMU (`reset_handler.S:72-76`).
  - Invalidates the TLBs and the I-cache, then the D/unified caches by set/way (`:123-179`).
  - Calls `init_TTB` (`:185`) and sets DACR = 0x55555555, all domains Client (`:190-192`).
  - Enables CP10/11 access (`:198-201`) and sets `FPEXC = 0x40000000` (`:206-207`).
  - Calls `enable_mmu` (`:212`).
- **`enable_mmu`:** sets SCTLR.M and clears the I, C, Z and A bits (`access.S:129-138`).
- **`VbarInit`:** VBAR = `start` (`access.S:165-172`). `SetLowVectors` clears SCTLR.V (`access.S:180-185`).
- **TTB** (`src/RZA1/compiler/asm/ttb_init.S`):
  - TTBCR = 0 (`:79-80`).
  - TTBR0 = `ttb_mmu1_base` with flags 0x08 | 0x40 (`:84-96`).
  - 4096 entries of 1 MB sections, written from the top down (`:120-231`).
  - Attributes (`:38,42,47`): STRGLY 0x0DE2 (strongly ordered), NORMAL_NOT_CACHE 0x1DE2, NORMAL_CACHE 0x1DEE (write-back, write-allocate).
  - Area sizes in MB (`:50-61`); the address ranges below are derived by cumulative sum.

| Area | Range | Content | Attribute |
|---|---|---|---|
| 0 | 0x00000000-0x07FFFFFF | CS0/1 (NOR) | cached |
| 1 | 0x08000000-0x0FFFFFFF | CS2/3 (SDRAM) | cached |
| 2 | 0x10000000-0x17FFFFFF | CS4/5 | strongly ordered |
| 3 | 0x18000000-0x1FFFFFFF | SPI flash | cached |
| 4 | 0x20000000-0x209FFFFF (10 MB) | internal RAM | cached |
| 5 | 0x20A00000-0x3FFFFFFF (502 MB) | I/O | strongly ordered |
| 6-10 | 0x40000000+ | uncached mirrors of NOR, SDRAM, CS45 (strongly ordered), SPI, RAM; RAM mirror is 0x60000000-0x609FFFFF | uncached |
| 11 | 0x60A00000-0xFFFFFFFF (2550 MB) | I/O | strongly ordered |

- **Uncached mirror:** `UNCACHED_MIRROR_OFFSET 0x40000000` (`cpu_specific.h:128`). DMA buffers are accessed through it, e.g. `ssi.c:51-79` and `pic.h:312`.
- **L1** (`R_CACHE_L1Init`, `l1_cache_init.S:44-74`): I-cache, D-cache and branch prediction (SCTLR bits 12, 2, 11) on; D-side prefetch on (ACTLR bit 2).
- **L2 (PL310 "L2C")** (`L2CacheInit`, `src/RZA1/cache/cache.c:268-273`):
  - Enable sequence (`:244-248`): `REG9_D_LOCKDOWN0 = 0xFFFFFFFF` (data ways locked), `I_LOCKDOWN0 = 0`, `AUX_CONTROL |= 0x30000000`, `CONTROL = 1`.
  - 8 ways (`:58`).
  - Data unlock happens via `L2CacheUnlockData` (`:251-255`), called at `deluge.cpp:907`.
  - Range maintenance uses 32-byte lines (`:282-316`). `CACHE_LINE_SIZE 32` (`definitions.h:58`).

### Vector table, startup and bootloader handoff

- **Vector table** (`src/RZA1/compiler/asm/start.S:51-67`): eight `LDR pc,=` entries (reset, undef, svc, prefetch, abort, reserved, irq, fiq), followed by the image header:

| Offset | Field | Value |
|---|---|---|
| 0x20 | `code_start` | `.word start` |
| 0x24 | `code_end` | `.word end` |
| 0x28 | `code_execute` | `.word execute` |
| 0x2C | signature | `.string ".BootLoad_ValidProgramTest."` |

  The offsets are confirmed by `OFF_USER_CODE_START 0x20 / END 0x24 / EXECUTE 0x28 / SIGNATURE 0x2c` (`src/deluge/util/chainload.h:3-6`).
- **Entry point:** `ENTRY(start)` (`ld:57`) and `--entry=start` (`CMakeLists.txt:270`). The comment says it "corresponds with code_start … referenced in bootloader with DEF_USER_CODE_START" (`ld:56`).
- **Load address:**
  - The code start is **not a fixed constant**. It is `program_code_start`, the start of `.reset` (ALIGN 0x20), which comes after `.bss` in RAM012L (`ld:152-178`).
  - The flash image location is `PLACEMENT_FLASH_START 0x18080000` ("Copied from bootloader") (`resetprg.c:80`).
  - The bootloader itself is **not in this repo**, so **UNKNOWN** beyond that.
- **Boot sequence:**
  1. `reset_handler`: stacks for SVC, IRQ, FIQ and ABT, then SYS mode with `program_stack_end` (`reset_handler.S:99-118`).
  2. Caches/TTB/MMU set-up as above.
  3. `Peripheral_Basic_Init` (CPG).
  4. `initsct` (`.data` copy and `.bss` zero).
  5. `resetprg` (`resetprg.c:131-209`):
     - zeroes `.frunk_bss` and `.sdram_bss`;
     - `STB_Init`;
     - SDRAM pin mux: P3_0-14 address, P5_0-15 data, P2_0-6 CS3/RAS/CAS/CKE/WE0/WE1/RD;
     - `R_INTC_Init`, `R_CACHE_L1Init`, `L2CacheInit`, enable IRQ and FIQ;
     - `userdef_bsc_cs2_init(0)`, then memset all 64 MB of SDRAM to 0;
     - relocates `.exceptions`, `.sdram_text`, `.sdram_data` and `.sdram_rodata` from their load address (`__heap_start + offset`) into SDRAM;
     - `__libc_init_array()`, then `main()`.
  6. `main()` (`main.c:70-140`) sets up pins, timers and UARTs, then calls `deluge_main()` (`deluge.cpp:643`).
- **Fault vectors:** adjust LR, pass a fault type in r5 (0 = undef, 0xF = svc, 1 = prefetch, 2 = abort, 3 = reserved), and call `handle_cpu_fault` in SYS mode (`reset_handler.S:246-280`). The handler is `OSLikeStuff/fault_handler/fault_handler.c`, which writes to the PIC, i.e. shows the fault on the pads.
- **Firmware chainload over SysEx:** `deluge/io/midi/sysex.cpp:212` calls `chainload_from_buf` (`deluge/util/chainload.cpp:31-75`). It disables timers 0, 1, 2 and 4, cleans the caches, and jumps to the two-stage `deluge_chainload` (`chainload.S`), which copies the new image over the old one with the MMU and caches off.

---

## 2. Memory map

### Linker MEMORY regions (`linker_script_rz_a1l.ld:61-83`)

- `SDRAM`: 0x0C000000, length 0x04000000 (64 MB, CS3).
- `RAM012L`: 0x20000000, length 0x00300000 (3 MB internal RAM, pages 0-2).
- `ROM`: 0x18000000, length 0x02000000 (SPI flash window, 32 MB).
- Constants: `INTERNAL_RAM_START = 0x20020000`, `INTERNAL_RAM_END = 0x20300000` (`ld:92-93`).
- The comment at `ld:63-64` says 0x20000000-0x2001FFFF is data-retention RAM, write-enabled via SYSCR. `SYSCR3=0x0F` is set at `peripheral_init_basic.c:111`.

### Stack and table sizes (`ld:85-90`)

| Name | Size |
|---|---|
| `PROGRAM_STACK_SIZE` (SYS/user) | 0x8000 (32 KB) |
| `IRQ_STACK_SIZE` | 0x2000 |
| `FIQ_STACK_SIZE` | 0x2000 |
| `SVC_STACK_SIZE` | 0x2000 |
| `ABT_STACK_SIZE` | 0x2000 |
| `TTB_SIZE` | 0x8000 |

### Section order inside RAM012L

| Address / order | Section | Notes | Source |
|---|---|---|---|
| 0x20000000 | `.frunk_bss` (NOLOAD) | `PLACE_INTERNAL_FRUNK` objects. Comment: "this area is not executable" (`definitions.h:76-77`). Users: allocator empty-space tables, `spareRenderingBuffer[4][128]`, `reverbSidechain`, `oscSyncRenderingBuffer` | `ld:97-105` |
| 0x20020000 (ALIGN 0x4000) | `.ttb_mmu1` (32 KB) | `__frunk_slack_end` = start of this section | `ld:110-117` |
| next | `.irq_stack` | IRQ, FIQ, SVC, ABT, 8 KB each (32 KB) | `ld:119-137` |
| next | `.bss` | — | `ld:139-149` |
| next (ALIGN 0x20) | `.reset` | start.S, access.S, initsct.S, reset_handler.S, ttb_init.S; `program_code_start`, `execute` | `ld:152-178` |
| next | `.text`, `.rodata` (non-string), `.data`, `.preinit/.init/.fini_array`, `.tors` | — | `ld:180-261` |
| next | `.heap` (NOLOAD, empty) | `__heap_start` | `ld:263-274` |
| VMA in SDRAM, LMA at `.heap` | `.sdram_text`, `.sdram_data`, `.sdram_rodata` (all SHF_STRINGS rodata), `.exceptions` (ARM.extab/exidx) | copied at boot | `ld:277-317` |
| — | `end` / `_end` | ALIGN(0xFFFF) after the LMA blob; "EVERYTHING PLACED AFTER END SECTION WILL NOT BE COPIED" | `ld:320-330` |
| SDRAM | `.sdram_bss` (NOLOAD) | `PLACE_SDRAM_BSS` | `ld:332-340` |
| 0x202F8000-0x20300000 | `.program_stack` | `INTERNAL_RAM_END - 0x8000` | `ld:342-348` |

The libc, libm, libgcc and libstdc++ archives are discarded (`ld:353-359`).

Exact section sizes need a `.map` file. None is in the repo; CMake produces `deluge*.map` (`CMakeLists.txt:257,267`). Sizes are therefore **UNKNOWN** without a build.

### Allocator regions (`src/deluge/memory/general_memory_allocator.cpp:42-78`)

| Region (index) | Start | End | Notes |
|---|---|---|---|
| STEALABLE (0) | `__sdram_bss_end` | 0x0FDE0000 | audio cluster cache etc.; managed by CacheManager |
| EXTERNAL (2) | 0x0FDE0000 | 0x0FFE0000 | 2 MB (`RESERVED_EXTERNAL_ALLOCATOR`) |
| EXTERNAL_SMALL (3) | 0x0FFE0000 | 0x10000000 | 0x20000 = 128 KB; minAlign 16, pivot 64 |
| INTERNAL (1) | `__heap_start` | `program_stack_start` (0x202F8000) | — |
| INTERNAL_SMALL (4) | `__frunk_bss_end` | `__frunk_slack_end` (0x20020000) | minAlign 16, pivot 64 |

- Empty-space record tables (`:28-32`): 512, 1024, 256, 256 and 256 entries, all in frunk.
- **Selection logic** (`:106-215`):
  - With `mayUseOnChipRam`: INTERNAL_SMALL for requests under 128 B, otherwise INTERNAL.
  - Then EXTERNAL_SMALL for under 128 B, otherwise EXTERNAL.
  - Then STEALABLE as the last resort. Stealable objects go only in STEALABLE.
- `malloc` maps to `delugeAlloc(size, true)` (`src/malloc.c:7-8`). `operator new` is overridden in `memory/operators.cpp`.
- `fast_allocator` uses `allocMaxSpeed` (internal first). `sdram_allocator` and `external_allocator` use `allocLowSpeed`.
- Stack guard: `checkStack` freezes with "E338" when less than 200 B of stack is left (`:83-99`).

### Other address constants

- `UNUSED_MEMORY_SPACE_ADDRESS 0x08000000`, `INTERNAL_MEMORY_BEGIN 0x20000000` (`cpu_specific.h:124-126`).
- Placement constants: `PLACEMENT_SDRAM_START 0x0C000000`, `PLACEMENT_INTRAM_START 0x20020000`, `PLACEMENT_FLASH_START 0x18080000` (`resetprg.c:78-80`).
- **Settings in SPI flash** are at offset `0x80000 - 0x1000` = 0x7F000:
  - read 256 B at `storage/flash_storage.cpp:394`;
  - erase and program 256 B at `:1054-1055`;
  - offset 0 holds the firmware version (0xFF = blank) (`:73`).

---

## 3. SDRAM / BSC

- **Chip:** AS4C32M16SB per the pinmap only (`generate.py:368`). The code just says 64 MB.
- **Configuration** (`src/RZA1/bsc/bsc_userdef.c:157-222`):
  - `CS2BCR = CS3BCR = 0x00004C00`: SDRAM, 16-bit, 0 idle cycles.
  - `CS3WCR = 0x00000088`: comment says CAS latency 2, plus the WTRCD/AC3L notes.
  - `SDCR`: 0x00110912 when ramSize==0 ("CS3 cols 10-bit. For 64MB chip"), otherwise 0x00110911 (32 MB). The firmware passes 0.
  - `RTCOR = 0xA55A0080` (128 cycles per refresh).
  - `RTCSR = 0xA55A0008` (B-phy/4).
  - Mode registers are written via `0x3FFFD040` / `0x3FFFE040`.
- **Pins** (`resetprg.c:137-178`), all mux 1: A1-A15 on P3_0-14, D0-15 on P5_0-15, CS3 P2_0, RAS P2_1, CAS P2_2, CKE P2_3, WE0 P2_4, WE1 P2_5, RD/!WR P2_6.

---

## 4. Interrupt controller (GIC / INTC)

- **Init** (`src/RZA1/intc/intc.c:141-199`):
  - all sources secure; ICDICFR set from a table;
  - all priorities 31 (0xF8F8F8F8);
  - targets CPU0 from ICDIPTR8 on;
  - all sources disabled;
  - PMR = 31; `ICCBPR = 2` (group priority bits [7:3]); `ICCICR = 3`; `ICDDCR = 1`.
- `INTC_ID_TOTAL 587` (`devdrv_intc.h:45`). Priorities run 0-31, shifted left by 3 (`intc.c:288-317`).
- **IRQ entry** (`irqfiq_handler.S:134-185`): reads ICCIAR with workarounds for ARM errata 801120 and 733075 (`:46-98`); ICCIAR is at 0xE820200C and ICCEOIR at 0xE8202010 (`:40-41`).
- **Nesting:** `INTC_Handler_Interrupt` re-enables IRQs before dispatching (`intc_handler.c:118`), so interrupts nest by priority. ID 1023 / out-of-range IDs print "i029" and return (`:108-114`).
- **FIQ:** `fiq_handler` calls `Userdef_FIQ_HandlerExe` (`:146-149`). No FIQ users were found.
- **External IRQ edge mode:** `INTC.ICR1 = 0b0101010101010101`, falling edge for IRQ0-7 (`main.c:131`). Encoder IRQs are then switched to both edges via `setIRQInterruptBothEdges` (`timers_interrupts.c:79-87`).

### Registered interrupts (lower number = higher priority)

| Source | INTC ID | Priority | Handler | Location |
|---|---|---|---|---|
| MTU2 TGI2A (MIDI/gate timer) | `INTC_ID_TGI0A`+2 (139+2) | 5 | `midiAndGateOutputTimerInterrupt` | `main.c:85` |
| IRQ6 (trigger clock in, P1_14) | 32+6 | 5 | `triggerClockInputHandler` | `main.c:133` |
| DMA ch10 end (PIC TX) | DMAINT0(41)+10 | 5 | `PIC_TX_INT_TrnEnd` | `sio_char.c:190-193`, `uart.c:341` |
| DMA ch11 end (MIDI TX) | 41+11 | 13 | `MIDI_TX_INT_TrnEnd` | same |
| DMA ch4 end (OLED SPI) | 41+4 | 13 | `oledTransferComplete` | `deluge/drivers/oled/oled.c:165` |
| RSPI0 SPRI (CV word complete) | `INTC_ID_SPRI0` (271) + 3×ch | 5 | `cvSPITransferComplete` | `RZA1/oled/oled_low_level.c:35` |
| USBI0 | 73 | 9 | `usb_hstd_usb_handler` / `usb_pstd_usb_handler` | `r_usb_usbif_api.c:249,286` |
| SDHI1 (3 sources: 305, 306, 307) | — | 10 (`INT_LEVEL_SDHI`) | `sddev_sd_int_handler_1` | `sd_dev_low.c:67,224-226` |
| Encoders IRQ0, 1, 2, 3, 4, 7 | 32+n | 14 | `encoderIrqHandler<i>` | `hid/encoders.cpp:127,148` |

- USB DMA interrupts (DMAINT0-3, priority 0) exist only under `USB_CFG_DMA == ENABLE`. It is disabled (`r_usb_basic_config.h:67`, `r_usb_rz_mcu.c:199-214`).
- **Critical sections:** a nest-counted `CPSID i` + DSB/ISB (`OSLikeStuff/timers_interrupts/timers_interrupts.c:30-70`).

---

## 5. Timers

### MTU2

Five 16-bit channels. `TCNT`/`TGRA` are `uint16_t` (`src/RZA1/mtu/mtu.h:110-112`). `mtuEnableAccess` sets `TRWER=1` (`mtu.c:20-23`). Prescalers available per channel: 1/4/16/64 on all, 256 on ch 1/3/4, 1024 on ch 2/3/4 (`mtu.h:71-108`).

| Name | Channel | Prescaler | Mode | Source |
|---|---|---|---|---|
| `TIMER_SYSTEM_FAST` | 0 | 64 | free-running | `definitions.h:41`, `main.c:98` |
| `TIMER_SYSTEM_SUPERFAST` | 1 | 1 | free-running | `definitions.h:49`, `main.c:101` |
| `TIMER_MIDI_GATE_OUTPUT` | 2 | 64 | cleared on TGRA, interrupt | `definitions.h:37`, `main.c:85` |
| `TIMER_SYSTEM_SLOW` | 4 | 1024 | free-running | `definitions.h:45`, `main.c:95` |

- **Gate timer delay:** `TGRA = samplesTilMIDIOrGate*766245 >> 16`, commented as "×515616/kSampleRate" (`processing/engines/audio_engine.cpp:1028-1030`).
- **Tick rates, derived** (P0 = 2.5×XTAL = 32.52 MHz at XTAL 13.007402 MHz):
  - superfast: about 32.5 MHz (30.75 ns/tick);
  - fast: about 508 kHz;
  - slow: about 31.8 kHz.
  - These are derived numbers and disagree with the comments listed in section 0.

### OSTM0

Used by the task scheduler: free-running, 32-bit, no interrupt (`OSLikeStuff/task_scheduler/task_scheduler.cpp:374-382`). It is converted to seconds assuming 33.33 MHz (`clock_type.h:10-18`), and rollover is handled in software (`task_scheduler.cpp:454-466`). `ostm.c` drives OSTM0/1 through `OSTMnTS/TT/CTL/CMP/CNT`.

---

## 6. DMA channel allocation

The table is in `cpu_specific.h:89-120`. SD's channel is in `sdhi/inc/sd_cfg.h:63-64`.

| Ch | Use | DMARS | Notes |
|---|---|---|---|
| 0, 1, 3, 5, 15 | unused (ch 0-3 are reserved for USB DMA, which is disabled) | — | `r_usb_basic_config.h:67-99` |
| 2 | SD host (SDHI1), `SD1_DMA_CHANNEL 2` | — | `sd_cfg.h:64`; ch 3 is "SD0, Not actually used" |
| 4 | OLED + CV SPI TX (RSPI0) | `DMARS_FOR_RSPI_TX 0b100100001` + (ch<<2) | `cpu_specific.h:39,110`, `oled.c:141-166` |
| 6 | SSI0 TX (audio out) | `0x00E1` | `cpu_specific.h:32,112` |
| 7 | SSI0 RX (audio in) | `0x00E2` | `cpu_specific.h:33,113` |
| 8, 9 | "SD SPI TX/RX for 40-pad Deluge (mmc.c)" | — | `mmc.c` is not in the repo |
| 10 | PIC UART TX (SCIF1) | `DMARS_FOR_SCIF0_TX 0b001100001` + (sci<<2) | `uart.c:329` |
| 11 | MIDI UART TX (SCIF0) | same formula | — |
| 12 | PIC UART RX | `DMARS_FOR_SCIF0_RX 0b001100010` + (sci<<2) | `uart.c:345` |
| 13 | MIDI UART RX | same formula | — |
| 14 | MIDI RX timing capture: on each MIDI RX request, copies SSI TX DMA `CRSA` (current audio-out read address) into `midiRxTimingBuffer[32]` | same RX DMARS | `sio_char.c:217-228`, `uart.c:353-362` |

- Bootloader DMA config is reused for **OLED presence detection**: `have_oled = (DMACn(4).CHCFG_n & (0b1101000|4)) == that value` (`deluge.cpp:645-646`).
- **Helpers** (`deluge/drivers/dmac/dmac.c:20-44`): `setDMARS` (16-bit halves per channel pair), `initDMAWithLinkDescriptor` (`CHCFG` from `desc[4]`, `NXLA`), and `dmaChannelStart` (SWRST, then SETEN).

---

## 7. Audio codec and SSI

- **Codec:** Cirrus Logic CS4270 per the pinmap only (`generate.py:467`). The code never names it; it only says "the annoying codec chip freaks out if it sees the same 0s" (`audio_engine.cpp:1159`). No I²C/SPI control-port code exists (no RIIC users). The only control is the **CODEC enable pin P6_12**: off at boot (`deluge.cpp:673-674`), then on after `PIC::setupForPads()` (`:743`).
- **Interface:** SSI0 (`SSI_CHANNEL 0`, `cpu_specific.h:80`); 1 stereo input and 1 stereo output (`:81-84`).
- **Pins** (`main.c:73-77`):
  - AUDIO_XOUT on P7_11 (mux 6); the pinmap calls this "MCLK" (`generate.py:633`);
  - SSI0 SCK P6_8, WS P6_9, TX P6_10 (codec Data In), RX P6_11 (codec Data Out), all mux 3.
- **SSICR** (`src/RZA1/ssi/drv_ssif_user.h:48-85`):
  - CKS=0 (AUDIO_X1 input), CHNL=0;
  - DWL=0x00280000 (24-bit data word);
  - SWL=0x00030000 (32-bit system word);
  - SCKD=1 and SWSD=1 (master);
  - CKDV=0x20, commented "/4" (the original was /8);
  - DEL=0.
- **SSIFCR:** base value has TTRG=0xA0 with FIFOs held in reset (`drv_ssif.h:60-66`). `ssiStart` releases the FIFO resets, sets TIE/RIE (DMA requests), then TEN|REN (`src/RZA1/ssi/ssi.c:95-113`). The init path is `ssiInit2` (reset via `CPG.SWRSTCR1`), then the DMA link descriptors, then start (`ssi.c:59-93`). `ssiInit(0,1)` is called from `deluge.cpp:721`.
- **Sample format:** `kSampleRate = 44100`, "fixed in hardware … SSI bit clock … generated by a crystal" (`definitions_cxx.hpp:1040-1044`); `kBitDepth = 24` (`:1047`).
  - **Derived, not stated in code:** with SWL 32 bits × 2 channels = 64fs and CKDV /4, AUDIO_X1 = 11.2896 MHz.
- **Buffers** (`definitions.h:51-52`, `deluge/drivers/ssi/ssi.c:23-48`):
  - TX: `ssiTxBuffer[128*2]` int32 (1 KB, internal RAM, 32-byte aligned).
  - RX: `ssiRxBuffer[2048*2]` int32 (16 KB, `PLACE_SDRAM_DATA`).
  - Each uses a self-looping link descriptor (header 0b1101), so the ring runs continuously. Config words: TX `0b10000001001000100010001000101000|DMA_LVL_FOR_SSI|6`, RX `0b10000001000100100010001000100000|LVL|7`. `DMA_LVL_FOR_SSI = 1<<6` (`cpu_specific.h:31`).
  - The current position is read from `CRSA`/`CRDA` (`ssi.c:50-56`).
- **Render window:** `numSamplesLimit = 80`, `direnessThreshold = 50` (`audio_engine.cpp:123-125`). The RX read position starts `(2048-128-16)` frames behind (`:224-226`).

---

## 8. SD card (SDHI) and FatFs

- **Port:** `SD_PORT 1` (`cpu_specific.h:87`), `SDCFG_IP1_BASE 0xE804E800` (IP0 is 0xE804E000) (`sd_cfg.h:44-45`).
- **Pins** (`main.c:120-127`), all mux 3: CD P7_0, WP P7_1, D1 P7_2, D0 P7_3, CLK P7_4, CMD P7_5, D3 P7_6, D2 P7_7. `sddev_set_port_0` returns early: "pin mux stuff is for the wrong pins anyway!" (`sd_dev_low.c:459`).
- **Mode** (`sd_cfg.h:50-98, 360`):
  - hardware interrupts, DMA transfer with `SD_MODE_DMA_64`, SDIO enabled (`SDCFG_IO`), high-speed, SD version 2.x;
  - card-detect interrupt on;
  - **4-bit bus**, because `SDCFG_SDMODE_1BIT` is commented out at `:98`.
- **Clock dividers** from a 66.6 MHz base (`sd_dev_low.c:390-422`):

| Requested | Divider | Actual |
|---|---|---|
| 50 MHz | /2 | 33.3 MHz |
| 25 / 20 MHz | /4 | 16.6 MHz |
| 10 MHz | /8 | — |
| 5 MHz | /16 | — |
| 1 MHz | /128 | — |
| 400 kHz | /256 | 260 kHz |

- **Mount** (`src/RZA1/diskio.c:136-177`): `sd_init(SD_PORT, SDCFG_IP1_BASE, …, SD_CD_SOCKET)`, then `sd_cd_int(…, sdIntCallback)`, then `sd_mount(…, SDCFG_DRIVER_MODE, SD_VOLT_3_3)`; write-protect check via `sd_iswp`.
- **Waiting:** `deluge/drivers/sd/sd.c` yields into `routineForSD` / the task manager while waiting.
- **FatFs version R0.14b**, revision ID 86631 (`fatfs/ff.h:2,23`; `ffconf.h:5`). Key config (`ffconf.h`): LFN=1, MAX_LFN 255, code page 437, 1 volume, sector size 512, exFAT 0, LBA64 0, TINY 0, REENTRANT 0, CHMOD 1.

---

## 9. USB

- **Controller:** RZ/A1 USB 2.0 IP0 (`WHICH_USB_MODULE USB_IP0`, `src/RZA1/usb/USBConnection.c:38`). Uses the Renesas `r_usb_basic` stack, which includes hub support (`r_usb_hhubsys.c`).
- **Config** (`src/RZA1/usb/userdef/r_usb_basic_config.h`):
  - `USB_CFG_MODE HOST|PERI` (`:39`); classes PMIDI and HMIDI (`:57-58`);
  - DMA disabled (`:67`); 48 MHz clock select (`:110`);
  - `BUSWAIT 5`; VBUS high (`:140`); `USB_CFG_USE_USBIP IP0` (`:187`);
  - double buffering on (`:202`).
- **Speed:** full speed (`cfg.usb_speed = USB_FS`) for both host and peripheral (`USBConnection.c:67,92`). The `ctrl.type` values are `USB_HHID`/`USB_PMSC`, apparently reused as placeholders for MIDI (`:66,91`).
- **Boot behaviour:** opens as host; if nothing is attached, closes and opens as peripheral (`deluge.cpp:815-828`).
- **Host MIDI pipes:** bulk send PIPE1, interrupt send PIPE6, bulk receive PIPE2-5, interrupt receive PIPE7-8 (`r_usb_hmidi_config.h:40-47`). `MAX_NUM_USB_MIDI_DEVICES 6` (`definitions.h:74`).
- **Device MIDI:** bulk IN PIPE2, OUT PIPE3 (`deluge/drivers/usb/userdef/r_usb_pmidi_config.h:21-22`).
- **Device descriptor** (`deluge/io/midi/r_usb_pmidi_descriptor.c`):
  - bcdUSB 0x0200, VID 0x16D0, PID 0x0CE2 (`:34-42`);
  - `NCABLES 3` (`:51`);
  - bulk endpoints with wMaxPacketSize 0x40 (`:209,227`);
  - EP0 max packet size 64 (`:37`);
  - strings "Synthstrom Audible", "Deluge", "OUT", "IN" (`:248-336`).
- Interrupt priority 9 (section 4).

---

## 10. UARTs: DIN MIDI and PIC

- **Channel assignment:** `UART_CHANNEL_MIDI 0`, `UART_CHANNEL_PIC 1` (`cpu_specific.h:66-67`), both on SCIFA.
- **Pins:** MIDI TX P6_15 and RX P6_14 (mux 5) (`main.c:108-109`). PIC TX P3_15 (mux 5) and RX P1_9 (mux 3) (`:114-115`).
- **Init** (`src/RZA1/uart/sio_char.c:85-166`):
  - 8N1 asynchronous, internal clock;
  - `SCEMR = 0x80` (BGDM double-speed);
  - `SCFCR` ends at 0;
  - break output high.
- **Baud formula:** `SCBRR = round(XTAL*5/(16*baud) - 1)` (`:168-175`).
- **Rates:**
  - MIDI: 31250 (`main.c:106`).
  - PIC: starts at 31250 (`UART_INITIAL_SPEED_PIC_PADS_HZ`, `cpu_specific.h:68`). `PIC::setUARTSpeed` sends byte `4000000/200000 - 0.5` (19), because the PIC side runs at "4MHz/(x+1)" (`pic.h:145-148`). `setupForPads()` then switches the RZ side to `kUartFullSpeedPadsHz = 200000`, with the comment "400000 glitches sometimes" (`pic.h:26,97`).
- **Buffers** (`sio_char.c:51-58`, `cpu_specific.h:53-56`, `definitions.h:69-72`):

| Buffer | Size |
|---|---|
| PIC TX | 1024 |
| PIC RX | 64 |
| MIDI TX | 1024 |
| MIDI RX | 512 |
| MIDI RX timing | 32 × uint32 |

- **TX path:** circular buffer drained by DMA, using N0/N1 register-set switching to handle wrap-around (`deluge/drivers/uart/uart.c:124-189`). The TX-end interrupt re-flushes (`:266-291`).
- **RX path:** a self-looping link-descriptor DMA into the ring; the write position comes from `CRDA` (`uart.c:220-262`).
- `SCSCR = 0x00F0` enables the DMA request "interrupts" (`uart.c:350`).
- **Debug text:** when `ENABLE_TEXT_OUTPUT` is on, it goes to the MIDI UART, or to SEGGER RTT if `HAVE_RTT` (`uart.c:32-94`).

---

## 11. PIC microcontroller (pads, buttons, LEDs, 7-segment, OLED CS/DC)

- **Chip:** PIC24FJ256 per the pinmap only (`generate.py:482`).
- **Transport:** UART on SCIF1 (section 10).
- **Host to PIC** (`src/deluge/drivers/pic/pic.h:28-72`):

| Code | Message | Payload |
|---|---|---|
| 1-9 | `SET_COLOUR_FOR_TWO_COLUMNS` + idx (8 main pairs + 1 sidebar pair) | 16 × RGB (48 B); 49 B total = `kNumBytesInColUpdateMessage` (`definitions_cxx.hpp:94`) |
| 10+n | `SET_FLASH_COLOR` + colour idx | — |
| 18 | `SET_DEBOUNCE_TIME` | ms; 20 at boot (`deluge.cpp:653`) |
| 19 | `SET_REFRESH_TIME` | ms; 23 at boot (`deluge.cpp:655`) |
| 20 / 21 | `SET_GOLD_KNOB_0/1_INDICATORS` | 4 brightness bytes |
| 22 | `RESEND_BUTTON_STATES` | — |
| 23 | `SET_FLASH_LENGTH` | 6 at boot |
| 24+idx | `SET_PAD_FLASHING` | — |
| 152+idx | `SET_LED_OFF` | idx 0-35 |
| 188+idx | `SET_LED_ON` | idx 0-35 |
| 224 | `UPDATE_SEVEN_SEGMENT_DISPLAY` | 4 bytes |
| 225 | `SET_UART_SPEED` | divider byte |
| 228+idx | `SET_SCROLL_ROW` | RGB |
| 236-239 | `SET_SCROLL_LEFT/RIGHT/RIGHT_FULL/LEFT_FULL` (236+bitflags) | — |
| 240 | `DONE_SENDING_ROWS` | — |
| 241 / 242 | `SET_SCROLL_UP/DOWN` | 18 × RGB |
| 243 | `SET_DIMMER_INTERVAL` | — |
| 244 | `SET_MIN_INTERRUPT_INTERVAL` | 8 at boot |
| 245 | `REQUEST_FIRMWARE_VERSION` | — |
| 247 | `ENABLE_OLED` | — |
| 248 | `SELECT_OLED` | — |
| 249 | `DESELECT_OLED` | — |
| 250 | `SET_DC_LOW` | — |
| 251 | `SET_DC_HIGH` | — |

- **PIC to host** (`pic.h:78-92`):
  - 0-179: pad/button event (`kPadAndButtonMessagesEnd = 180`);
  - 129: `UNKNOWN_BOOT_RESPONSE`, every boot;
  - 175: `RESET_SETTINGS`, sent if the select knob is held at boot (factory reset, `deluge.cpp:782-786`);
  - 245: `FIRMWARE_VERSION_NEXT`; the next byte has bits 0-6 = version and bit 7 = OLED present (`deluge.cpp:767-773`);
  - 246-251: OLED-related acks; 248/249 complete the select/deselect handshake;
  - 252: `NEXT_PAD_OFF` (the next event is a release);
  - 253: `UNKNOWN_BREAK`;
  - 254: `NO_PRESSES_HAPPENING`.
- **Decoding** (`deluge.cpp:270-325`):
  - **Pads:** values 0..143 (`Pad::isPad`, `hid/matrix/pad.cpp:29-31`). `y = v/9`, `x = (v%9)*2`; if `y >= 8`, then `y -= 8` and `x++` (`pad.cpp:7-15`). That gives 18 columns × 8 rows (16 main + 2 sidebar).
  - **Buttons:** `9*(y+16)+x` with x 0-8 and y 0-3, so values 144..179 (`hid/button.h:9-15`). `NUM_BUTTON_ROWS 4`, `NUM_BUTTON_COLS 9` (`cpu_specific.h:61-62`).
  - Button coordinates are listed in `definitions_cxx.hpp:57-82`, e.g. shift {8,0}, play {8,3}, record {8,2}. The mod buttons are x 1-2, y 0-3 (`button.h:20-21`).
- **Indicator LEDs:** index = x + 9y over 9 × 4 = 36 (`hid/led/indicator_leds.h:27-66`; `NUM_LED_COLS 9`, `NUM_LED_ROWS 4` in `cpu_specific.h:63,74`).
- **Gold-knob rings:** 4 LEDs per knob (`kNumGoldKnobIndicatorLEDs`, `definitions_cxx.hpp:447`).
- **Pad brightness:** 1-25 (`definitions_cxx.hpp:104-105`).
- **TX writes** go into `picTxBuffer` through the uncached mirror (`pic.h:310-316`).

---

## 12. Displays

- **Type selection:** the OLED is detected from bootloader DMA state (section 6). With an OLED, `display = new OLED`; otherwise `new SevenSegment` (`deluge.cpp:703-718`).
- **7-segment:** 4 digits (`kNumericDisplayLength`, `definitions_cxx.hpp:446`), sent through PIC message 224 (`hid/display/seven_segment.cpp:667,693`).
- **OLED:**
  - **Controller: UNKNOWN part.** The init sequence is "copied from the OLED manufacturer's datasheet": 0xFD 0x12 command lock, horizontal addressing, `0x22` page range `(64-48)>>3=2..7`, multiplex 0x3F (64), COM pins 0x12, clock 0xF0, precharge 0xA2, VCOM 0x34 (`deluge/drivers/oled/oled.c:31-96`).
  - **Size:** 128 × 48 pixels used (`OLED_MAIN_WIDTH_PIXELS 128`, `HEIGHT 48`, `TOPMOST_PIXEL 5`, `OLED_HEIGHT_CHARS 4`; a 64-pixel option is commented out) (`cpu_specific.h:136-149`). `kOLEDWidthChars 16` (`definitions_cxx.hpp:982`).
  - **Frame:** (48/8) × 128 = 768 bytes per DMA transfer (`oled_low_level.c:159`).
  - **Bus:** RSPI0, shared with the CV DAC, using SPI_CLK P6_0 and MOSI P6_2 (mux 3) (`definitions_cxx.hpp:126-128`, `deluge.cpp:700-701`).
  - **CS and D/C go through the PIC** (messages 247-251; the pinmap shows OLED CS as a PIC output).
  - **SPI rate:** `R_RSPI_Create(0, have_oled ? 10 MHz : 30 MHz, phase 0, 32-bit)` (`deluge.cpp:694-699`). SPBR = ceil(66666666/(2·rate) − 1) (`rspi.c:99`). Derived actual rates: 3, giving about 8.33 MHz, for the OLED case; 1, giving 16.7 MHz, otherwise.
  - **Transfers:** OLED transfers are 8-bit (`SPDCR 0x20`), DMA channel 4, with a frame queue of 32 (`deluge/drivers/oled/oled.h:22`).
  - **Recovery:** a 50 ms DMA watchdog (`oled_low_level.c:74-143`). The select/deselect retry also times out at 50 ms (`:81-104`).

---

## 13. CV / gate outputs

- **DAC:** MAX5136 per the pinmap (`generate.py:422`); the code comment says "AD DAC".
- **Connection:** RSPI0 (`SPI_CHANNEL_CV 0`, `cpu_specific.h:64`), 32-bit frames, CS on **P6_1** (`SPI_SSL`):
  - with an OLED: driven as GPIO, low = selected (`oled_low_level.c:176,263`);
  - without an OLED: hardware SSL, mux 3 (`deluge.cpp:714`).
- **Word format:** `((0b00110000 | (1<<ch)) << 24) | (voltage16 << 8)`, voltage clamped to 0-65535 (`processing/engines/cv_engine.cpp:212-223`).
- **Init:** sends `0x05020000` (LIN=1), waits 10 ms, then sends `0x05000000` (LIN=0) (`cv_engine.cpp:49-77`).
- **Scaling:** volts/octave is in units of 0.01 V; the formula is `(note-24)*5.46*voltsPerOctave` (`:267-276`).
- **Counts:** `NUM_PHYSICAL_CV_CHANNELS 2`, `NUM_GATE_CHANNELS 4` (`cpu_specific.h:28-29`).
- **Gate pins:** P2_7, P2_8, P2_9, P4_0 as GPIO outputs; the output is inverted, so "true turns the gate off" (`cv_engine.h:26-27`, `cv_engine.cpp:225-229`). Gate 2 = RUN and gate 3 = CLOCK (`cv_engine.h:23-24`).
- **CV priority:** CV words pre-empt queued OLED frames on the shared bus (`oled_low_level.c:38-61,218-291`).
- **Trigger clock in:** P1_14 (mux 2) to IRQ6, falling edge "due to the presence of a transistor" (`main.c:129-133`, `deluge.cpp:687`). Each edge is timestamped with SSI TX DMA `CRSA` (`main.c:45-59`). The ring holds 4 entries (`definitions.h:56`).
- **Synced LED:** P6_7 output (`definitions_cxx.hpp:119`).

---

## 14. Encoders and gold knobs

All on port 1 (`hid/encoders.cpp:73-80,154-163`). The A pin is muxed (alt 2) to IRQn with both-edge interrupts; B is read as GPIO; quadrature is decoded in the ISR.

| Encoder | A pin / IRQ | B pin | Inverted |
|---|---|---|---|
| scrollY | P1_8 / IRQ0 | P1_10 | no |
| scrollX | P1_11 / IRQ3 | P1_12 | no |
| tempo | P1_6 / IRQ2 | P1_7 | yes |
| select | P1_3 / IRQ7 | P1_2 | yes |
| mod1 (gold) | P1_5 / IRQ1 | P1_4 | no |
| mod0 (gold) | P1_0 / IRQ4 | P1_15 | no |

- The four black encoders are detented: 4 edges per click (`hid/encoders.h:28-64`). The two gold ones are continuous (`:66-80`).
- `kNumPhysicalModKnobs 2` (`definitions_cxx.hpp:452`); `kMaxKnobPos 128` (`:349`).
- Encoder push-buttons arrive through the PIC as buttons (`definitions_cxx.hpp:59-64`).

---

## 15. Analog inputs, jack detects, power

All GPIO except the voltage sense (`definitions_cxx.hpp:112-124`; set-up at `deluge.cpp:666-691`; polled every 100 ms in `inputRoutine`, `deluge.cpp:122-205`).

| Signal | Pin | Logic |
|---|---|---|
| LINE_OUT_DETECT_L / R | P6_3 / P6_4 | input, 1 = plugged |
| HEADPHONE_DETECT | P6_5 | input, 1 = plugged |
| LINE_IN_DETECT | P6_6 | input, 1 = plugged |
| MIC_DETECT | P7_9 | input, **0** = plugged (`:135`) |
| SPEAKER_ENABLE | P4_1 | output; on only when no headphones and no line-out L/R (`:142-143`) |
| CODEC enable | P6_12 | output |
| BATTERY_LED | P1_1 | open-drain, 1 = off (`:666`) |
| VOLT_SENSE | P1_13 = AN5 (`SYS_VOLT_SENSE_PIN 5`), mux 1 | ADC input |

- Stereo rendering is chosen when headphones, line-out R, or internal recording is active (`deluge.cpp:145-146`).
- **Battery ADC:**
  - start with `ADC.ADCSR = (1<<13)|(0b011<<6)|5`;
  - when bit 15 is set, read `ADDRF`;
  - `mV = LPF(reading*3300) >> 15`; the reading is doubled because of a /2 resistor divider (`:158-201`).
  - LED thresholds: below 2900 mV blink (period (mV−2630)×3, clamped 60-500 ms); above 2950 solid; above 3300 off; back below 3200 solid.
- **Line in / mic:** both enter the single SSI0 RX stereo stream. **UNKNOWN** in code how the analog mic/line switch happens; the pinmap shows only "Mic Detect" and "Line In Detect".

---

## 16. SPI flash (SPIBSC)

- **Channel:** `SPIBSC_CH 0` (`cpu_specific.h:77`); pins P4_2-P4_7 mux 2 (`deluge.cpp:751-756`).
- **`initSPIBSC`** (`src/RZA1/spibsc/spibsc_Deluge_setup.c:50-…`):
  - `SSLDR = 0`;
  - SPBCR BRDV=0, SPBR=2, commented "33.33[MHz]";
  - read cache enabled;
  - external read mode with `SPIBSC_CMNCR_BSZ_SINGLE` and "just 1-bit" (`:53`).
- **Chip: UNKNOWN.** `sflash.h:89-91` says page 512, sector 256 KB × 256, but that is a generic Renesas header.
- **Timing caveat:** this runs late in boot because "graphics and audio routines [are injected] into the SPIBSC wait routines" (`deluge.cpp:749-757`).

---

## 17. Other constants

- Pads: `kDisplayWidth 16`, `kDisplayHeight 8`, `kSideBarWidth 2` (`definitions_cxx.hpp:89-91,130`).
- `UI_MS_PER_REFRESH 50`, `UI_MS_PER_REFRESH_SCROLLING 7`; the latter is limited by the UART (`cpu_specific.h:69-72`).
- `NUM_LEVEL_INDICATORS 2` (`cpu_specific.h:130`).
- Boot-time pin mux for the MD_BOOT/MD_CLK pins (P0_0-3) appears only in the pinmap (`generate.py:517-522`).
- Unconnected pins per the pinmap: P6_13, P7_8, P7_10 (`generate.py:615,630,632`). `cv_engine.cpp:52-56` has commented-out code that used P6_13.

---

## 18. `src/` directory tree

- `src/main.c`: C `main()`; SSI/UART/SD pin mux, MTU timers, trigger-clock IRQ, then `deluge_main`.
- `src/resetprg.c`: post-reset C init (STB, SDRAM pins and BSC, INTC, L1/L2, SDRAM relocation, libc init).
- `src/definitions.h`, `src/definitions_cxx.hpp`: global hardware/timer/buffer constants, pin definitions, UI constants.
- `src/malloc.c`, `memmove.c`, `mem_functions.h`, `c_lib_alternatives.S/.h`, `sys_stubs.c` (`_sbrk`, `_write`, …), `cpp_handler.cpp`, `terminate.cpp`, `arm_neon_shim.h`: bare-metal libc/C++ runtime replacements.
- `src/RZA1/`: Renesas RZ/A1 BSP.
  - `compiler/asm/`: `start.S` (vectors and header), `reset_handler.S`, `access.S` (MMU/VBAR/NEON), `ttb_init.S`, `initsct.S`, `l1_cache_init.S`, `l1_cache_operation.s`, `irqfiq_handler.S`, `isr.S`.
  - `system/`: `iodefine.h` and `iodefines/*` (register structs for every RZ/A1 peripheral), `iobitmasks/*`, `rza_io_regrw.c`.
  - `cpu_specific.h`: board-level channel/DMA/memory/OLED constants.
  - `peripheral_init_basic.c`: CPG clocks.
  - `stb/`: module standby (clock gating).
  - `bsc/`: bus state controller (SDRAM).
  - `cache/`: L1/L2 cache maintenance.
  - `intc/`: GIC driver and handler table.
  - `gpio/`: pin mux and GPIO helpers.
  - `mtu/`: MTU2 timers.
  - `ostm/`: OS timer.
  - `rspi/`: RSPI SPI driver.
  - `ssi/`: SSI audio serial interface.
  - `uart/sio_char.c`: SCIF init, UART buffers, DMA descriptors.
  - `oled/oled_low_level.c`: OLED/CV shared-SPI arbitration.
  - `sdhi/`: Renesas SD host driver (`inc/`, `src/sd/access`, `src/sd/sdio`, `userdef/`).
  - `spibsc/`: SPI multi-I/O bus controller and serial-flash API.
  - `usb/`: Renesas USB basic stack (`r_usb_basic`), host MIDI class (`r_usb_hmidi`), `USBConnection.c` (host/peripheral open/close), `userdef/` configs.
  - `diskio.c`: FatFs disk I/O glue to SDHI.
- `src/fatfs/`: ChaN FatFs R0.14b (`ff.c/h`, `ffconf.h`, `ffunicode.c`, `ffsystem.c`) plus the `fatfs.cpp/hpp` C++ wrapper.
- `src/NE10/`: ARM Ne10 NEON DSP library subset (FFT: `modules/dsp/NE10_fft*`).
- `src/OSLikeStuff/`: `task_scheduler/` (cooperative task manager on OSTM0), `timers_interrupts/` (critical sections, IRQ/timer set-up helpers, `clock_type.h`), `fault_handler/` (CPU fault reporting), `scheduler_api.h`.
- `src/RTT/`: SEGGER RTT debug-output library.
- `src/gsl/`: Guidelines Support Library headers.
- `src/lib/printf.c/h`: embedded printf.
- `src/deluge/`: application.
  - `deluge.cpp/h`: hardware init (`deluge_main`), PIC input parsing, battery/jack polling, main loop/tasks.
  - `drivers/`: Deluge-level drivers. `cache/invalidate.S` (DMA cache maintenance), `dmac/`, `mtu/mtu.h`, `oled/` (init sequence and frame DMA queue), `pic/pic.h` (PIC protocol), `rspi/`, `sd/sd.c` (SD wait hooks), `ssi/` (audio DMA buffers), `uart/` (UART DMA engine), `usb/userdef/` (peripheral MIDI pipes).
  - `hid/`: buttons, pad matrix, encoders (IRQ quadrature), LEDs (`indicator_leds`, `pad_leds`), `display/` (OLED, seven-segment, canvas, numeric layers, screensaver), `hid_sysex`.
  - `io/midi/`: MIDI engine, DIN/USB cable types, device manager, USB device descriptor, sysex (including firmware chainload). `io/debug/`: logging.
  - `memory/`: `GeneralMemoryAllocator`, `MemoryRegion`, `Stealable`/`CacheManager`, STL allocators, `operator new`.
  - `processing/`: `engines/audio_engine.cpp` (render loop vs SSI DMA), `cv_engine` (DAC/gates), sound, live input, metronome, stem export.
  - `dsp/`: filters, reverb, delay, oscillators, FFT, timestretch, granular, DX7, compressor, convolution.
  - `model/`, `modulation/`, `playback/`, `gui/`: sequencer data model, modulation, transport, UI.
  - `storage/`: file I/O, audio files, clusters (SD streaming), `flash_storage.cpp` (settings in SPI flash at 0x7F000), wavetables, multisample ranges.
  - `util/`: helpers, `cfunctions.c` (timer conversions), `chainload.S/.cpp`, fixed-point maths.
  - `version/`: build version.
- `lib/CMakeLists.txt` (outside `src`): fetches `argon` (pinned commit cae5738c…) and `etl` 20.40.0.
- `contrib/doc/pinmap/generate.py` (outside `src`): the only in-repo source naming the chips (CS4270, MAX5136, PIC24FJ256, AS4C32M16SB, R7S721020VCFP), with a full CPU-pin-to-signal table (`:516-635`).
- `tests/qemu/`: Cortex-A9 build for emulation; not hardware.

---

## 19. Unknowns

- The bootloader source and its exact load behaviour (only the header layout and the 0x18080000 flash image address are known).
- Section sizes (need a `.map` from a build).
- OLED controller part number.
- Whether the codec is in stand-alone mode or has another control path (no control-port code exists).
- The SPI flash part.
- How the mic/line-in analog selection is done in hardware.
- How `address_start_data_RAM` / `address_end_data_RAM` resolve at link time.
- The exact AUDIO_X1 crystal frequency (only derivable as 11.2896 MHz from 44.1 kHz × 64 × 4).
