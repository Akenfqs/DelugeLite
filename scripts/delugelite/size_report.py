#!/usr/bin/env python3
"""DelugeLite memory budget report.

Prints how the 3 MB internal SRAM is used by a built firmware ELF, and how much is left for the
"fast heap" (voices, sounds, clips...). Optionally compares against a baseline ELF.

Usage:
    scripts/delugelite/size_report.py build/Release/deluge.elf [--baseline other.elf] [--top N]
"""

import argparse
import os
import shutil
import subprocess
import sys

INTERNAL = (0x20000000, 0x20300000)
SDRAM = (0x0C000000, 0x10000000)


def tool(name):
    root = os.environ.get("DBT_TOOLCHAIN_PATH", os.path.join(os.path.dirname(__file__), "..", ".."))
    cand = os.path.join(root, "toolchain", "current", "arm-none-eabi-gcc", "bin", name)
    if os.path.exists(cand):
        return cand
    found = shutil.which(name)
    if not found:
        sys.exit(f"cannot find {name}; run inside './dbt shell' or set DBT_TOOLCHAIN_PATH")
    return found


def nm(elf):
    out = subprocess.run([tool("arm-none-eabi-nm"), "-S", "-C", elf], capture_output=True, text=True, check=True)
    syms = {}
    sized = []
    for line in out.stdout.splitlines():
        parts = line.split(" ", 3)
        try:
            if len(parts) == 4:
                addr, size, kind, name = int(parts[0], 16), int(parts[1], 16), parts[2], parts[3]
                sized.append((size, addr, kind, name))
            elif len(parts) == 3:
                addr, kind, name = int(parts[0], 16), parts[1], parts[2]
            else:
                continue
        except ValueError:
            continue
        syms[name] = addr
    return syms, sized


def sections(elf):
    out = subprocess.run([tool("arm-none-eabi-size"), "-A", elf], capture_output=True, text=True, check=True)
    res = {}
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0].startswith("."):
            res[parts[0]] = (int(parts[1]), int(parts[2]))
    return res


def report(elf):
    syms, sized = nm(elf)
    secs = sections(elf)

    def sec(name):
        return secs.get(name, (0, 0))[0]

    r = {
        ".text (code + wavetables)": sec(".text") + sec(".reset"),
        ".rodata (internal)": sec(".rodata"),
        ".data": sec(".data"),
        ".bss (internal)": sec(".bss"),
        ".frunk_bss": sec(".frunk_bss"),
        "fast heap at boot": syms["program_stack_start"] - syms["__heap_start"],
        "small internal heap (frunk)": syms["__frunk_slack_end"] - syms["__frunk_bss_end"],
        "SDRAM image (data+rodata+exceptions+bss)": sec(".sdram_data")
        + sec(".sdram_rodata")
        + sec(".exceptions")
        + sec(".sdram_bss"),
    }
    return r, sized


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("elf")
    ap.add_argument("--baseline")
    ap.add_argument("--top", type=int, default=0, help="also list the N biggest internal-RAM symbols")
    a = ap.parse_args()

    cur, sized = report(a.elf)
    base = report(a.baseline)[0] if a.baseline else None

    print(f"{'item':45} {'bytes':>10}" + (f" {'baseline':>10} {'delta':>9}" if base else ""))
    for k, v in cur.items():
        line = f"{k:45} {v:10,}"
        if base:
            line += f" {base[k]:10,} {v - base[k]:+9,}"
        print(line)
    print("\nNote: at boot ~120 KB of the fast heap is taken by the voice/voicesample/timestretcher pools.")

    if a.top:
        print(f"\nTop {a.top} internal-RAM symbols:")
        internal = [s for s in sized if INTERNAL[0] <= s[1] < INTERNAL[1]]
        for size, _addr, kind, name in sorted(internal, reverse=True)[: a.top]:
            print(f"{size:9,} {kind} {name[:110]}")


if __name__ == "__main__":
    main()
