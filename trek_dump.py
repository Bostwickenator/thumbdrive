#!/usr/bin/env python3
"""Dump Trek ThumbDrive (VID 0x0A16 / PID 0x1111) to a raw image.

Protocol is proprietary vendor-endpoint + bulk (not USB Mass Storage BOT).
See findings.md.

Examples:
  python trek_dump.py thumbdrive.img
  python trek_dump.py --lba 0 --count 64 probe.img
  python trek_dump.py --sectors 65536 out.img   # skip geometry, force size

Windows: install libusb via Zadig (WinUSB or libusbK) on the ThumbDrive interface.
If a transfer times out, physically unplug/replug before retrying - do not USB-reset.
"""

from __future__ import annotations

import argparse
import sys
import time

from trek_protocol import (
    DEFAULT_SECTORS,
    SECTOR_SIZE,
    TrekError,
    open_device,
    read_geometry,
    read_sectors,
)


def dump(
    path: str,
    *,
    start_lba: int = 0,
    count: int | None = None,
    sectors_override: int | None = None,
    chunk: int = 32,
    timeout: int = 5000,
) -> int:
    print("Opening device...")
    try:
        dev, ep_in, _ep_out = open_device()
    except TrekError as e:
        print(e, file=sys.stderr)
        return 1

    total = sectors_override
    group = chunk
    if total is None:
        print("Reading geometry (vendor 0x10)...")
        try:
            total, group, fields = read_geometry(dev, timeout=timeout)
            print(
                f"  total_sectors={total} ({total * SECTOR_SIZE / (1024 * 1024):.2f} MiB), "
                f"group={group}, key={fields['key']}"
            )
        except TrekError as e:
            print(e, file=sys.stderr)
            print(
                f"Falling back to default {DEFAULT_SECTORS} sectors (32 MiB).",
                file=sys.stderr,
            )
            total = DEFAULT_SECTORS
            group = chunk

    if count is None:
        count = max(0, total - start_lba)
    end = start_lba + count
    if end > total and sectors_override is None:
        print(f"Clamping end LBA {end} to capacity {total}")
        end = total
        count = end - start_lba

    # Prefer group size from geometry when chunking; keep within a sane range
    step = max(1, min(chunk, group if group > 0 else chunk, 128))

    print(f"Dumping LBA {start_lba}..{end - 1} ({count} sectors) → {path}")
    print(f"Chunk size: {step} sectors ({step * SECTOR_SIZE} bytes)")

    t0 = time.time()
    written = 0
    try:
        with open(path, "wb") as out:
            lba = start_lba
            while lba < end:
                n = min(step, end - lba)
                try:
                    data = read_sectors(dev, ep_in, lba, n, timeout=timeout)
                except TrekError as e:
                    print(f"\nError: {e}", file=sys.stderr)
                    print(
                        "Replug the device and re-run. "
                        "Partial image may be incomplete.",
                        file=sys.stderr,
                    )
                    return 1
                out.write(data)
                written += len(data)
                lba += n
                done = lba - start_lba
                pct = 100.0 * done / count if count else 100.0
                sys.stdout.write(
                    f"\rProgress: {done}/{count} sectors ({pct:.1f}%) "
                    f"{written / (1024 * 1024):.2f} MiB"
                )
                sys.stdout.flush()
    except OSError as e:
        print(f"\nFile error: {e}", file=sys.stderr)
        return 1

    elapsed = time.time() - t0
    print(f"\nDone: {written} bytes in {elapsed:.1f}s → {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("output", help="Output raw image path")
    p.add_argument("--lba", type=int, default=0, help="Starting LBA (default 0)")
    p.add_argument("--count", type=int, default=None, help="Sector count (default: full device)")
    p.add_argument(
        "--sectors",
        type=int,
        default=None,
        help=f"Force total sector count instead of geometry (default probe, else {DEFAULT_SECTORS})",
    )
    p.add_argument("--chunk", type=int, default=32, help="Sectors per READ (default 32)")
    p.add_argument("--timeout", type=int, default=5000, help="USB timeout ms")
    args = p.parse_args(argv)
    return dump(
        args.output,
        start_lba=args.lba,
        count=args.count,
        sectors_override=args.sectors,
        chunk=args.chunk,
        timeout=args.timeout,
    )


if __name__ == "__main__":
    raise SystemExit(main())
