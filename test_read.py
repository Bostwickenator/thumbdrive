#!/usr/bin/env python3
"""Minimal probe: geometry (0x10) then READ LBA 0 (0x11).

Usage:
  python test_read.py

Replug the ThumbDrive before running if a previous probe timed out.
Do not call USB reset between attempts.
"""

from __future__ import annotations

from trek_protocol import TrekError, open_device, read_geometry, read_sectors


def main() -> int:
    print("Opening ThumbDrive (do not reset; replug if previous attempt failed)...")
    try:
        dev, ep_in, ep_out = open_device()
    except TrekError as e:
        print(e)
        return 1

    print(f"Endpoints: IN={ep_in.bEndpointAddress:#04x} OUT={ep_out.bEndpointAddress:#04x}")

    try:
        total, group, fields = read_geometry(dev)
    except TrekError as e:
        print(e)
        print("Hint: physical unplug/replug, then run this script once.")
        return 1

    print("Geometry (bRequest 0x10):")
    print(f"  key={fields['key']} factor={fields['factor']} group={group}")
    print(f"  total_sectors={total} ({total * 512 / (1024 * 1024):.2f} MiB)")
    print(f"  raw={fields['raw_hex']}")

    try:
        sector0 = read_sectors(dev, ep_in, lba=0, count=1)
    except TrekError as e:
        print(e)
        print("Hint: replug, then retry. Geometry may have succeeded but READ failed.")
        return 1

    print(f"LBA 0 ({len(sector0)} bytes): {sector0[:32].hex()}...")
    if sector0[510:512] == b"\x55\xaa":
        print("Looks like a boot/MBR sector (0x55AA signature).")
    elif sector0[0] == 0xEB:
        print("Looks like a BIOS Parameter Block (JMP at offset 0).")
    else:
        print("No FAT/MBR signature at LBA0 - may be raw flash / remapped layout.")

    print("OK - protocol probe succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
