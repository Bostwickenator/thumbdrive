"""Trek ThumbDrive proprietary USB protocol helpers.

VID 0x0A16 / PID 0x1111 — vendor-endpoint control + bulk, not BOT.
See findings.md and WinXP/protocol_analysis.md.
"""

from __future__ import annotations

import struct
from typing import Optional, Tuple

import usb.core
import usb.util

try:
    import libusb_package
except ImportError:  # pragma: no cover
    libusb_package = None

VID = 0x0A16
PID = 0x1111
SECTOR_SIZE = 512

# bmRequestType: Vendor | Endpoint
RT_VENDOR_ENDPOINT_OUT = 0x42
RT_VENDOR_ENDPOINT_IN = 0xC2

REQ_GEOMETRY = 0x10
REQ_READ = 0x11
REQ_WRITE = 0x16

GEOMETRY_LEN = 31
DEFAULT_SECTORS = 0x10000  # 32 MiB


class TrekError(RuntimeError):
    pass


def get_backend():
    if libusb_package is not None:
        return libusb_package.get_libusb1_backend()
    return None


def find_device(backend=None):
    kwargs = {"idVendor": VID, "idProduct": PID}
    if backend is not None:
        kwargs["backend"] = backend
    elif libusb_package is not None:
        kwargs["backend"] = get_backend()
    return usb.core.find(**kwargs)


def open_device(dev: Optional[usb.core.Device] = None):
    """Find device, set configuration, claim interface 0, return (dev, ep_in, ep_out)."""
    if dev is None:
        dev = find_device()
    if dev is None:
        raise TrekError(
            f"ThumbDrive not found (VID={VID:#06x} PID={PID:#06x}). "
            "On Windows, use Zadig to bind WinUSB/libusbK to the interface."
        )

    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except (NotImplementedError, usb.core.USBError):
        pass

    try:
        dev.set_configuration()
    except usb.core.USBError:
        # Already configured is fine
        pass

    cfg = dev.get_active_configuration()
    intf = cfg[(0, 0)]
    try:
        usb.util.claim_interface(dev, intf.bInterfaceNumber)
    except usb.core.USBError:
        pass

    ep_in = usb.util.find_descriptor(
        intf,
        custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
        == usb.util.ENDPOINT_IN,
    )
    ep_out = usb.util.find_descriptor(
        intf,
        custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress)
        == usb.util.ENDPOINT_OUT,
    )
    if ep_in is None or ep_out is None:
        raise TrekError("Could not find bulk IN/OUT endpoints")

    for ep in (ep_in, ep_out):
        try:
            dev.clear_halt(ep.bEndpointAddress)
        except usb.core.USBError:
            pass

    return dev, ep_in, ep_out


def parse_geometry(buf: bytes) -> Tuple[int, int, dict]:
    """Parse 31-byte response from bRequest 0x10.

    Returns (total_sectors, group_size, raw_fields).
    """
    if len(buf) < 0x13:
        raise TrekError(f"Geometry response too short: {len(buf)} bytes")
    key = struct.unpack_from("<H", buf, 0x09)[0]
    factor = struct.unpack_from("<I", buf, 0x0B)[0]
    group = struct.unpack_from("<I", buf, 0x0F)[0]
    if group == 0:
        raise TrekError(f"Geometry group size is 0 (raw={buf.hex()})")
    total = factor * group
    fields = {
        "key": key,
        "factor": factor,
        "group_size": group,
        "total_sectors": total,
        "raw_hex": buf.hex(),
    }
    return total, group, fields


def read_geometry(dev: usb.core.Device, timeout: int = 2000) -> Tuple[int, int, dict]:
    """Vendor IN 0x10 — device geometry (control data stage, 31 bytes)."""
    try:
        data = bytes(dev.ctrl_transfer(RT_VENDOR_ENDPOINT_IN, REQ_GEOMETRY, 0, 0, GEOMETRY_LEN, timeout=timeout))
    except usb.core.USBError as e:
        raise TrekError(
            f"Geometry (0x10) failed: {e}. "
            "Replug the device and retry; avoid reset() between probes."
        ) from e
    return parse_geometry(data)


def _cmd_payload(lba: int, count: int) -> bytes:
    return struct.pack("<II", lba, count)


def read_sectors(
    dev: usb.core.Device,
    ep_in,
    lba: int,
    count: int = 1,
    timeout: int = 5000,
) -> bytes:
    """READ: vendor OUT 0x11 with (lba, count), then bulk IN count*512."""
    if count < 1:
        raise ValueError("count must be >= 1")
    payload = _cmd_payload(lba, count)
    try:
        dev.ctrl_transfer(RT_VENDOR_ENDPOINT_OUT, REQ_READ, 0, 0, payload, timeout=timeout)
    except usb.core.USBError as e:
        raise TrekError(f"READ command (0x11) LBA={lba} count={count} failed: {e}") from e

    need = count * SECTOR_SIZE
    data = bytearray()
    while len(data) < need:
        try:
            chunk = ep_in.read(need - len(data), timeout=timeout)
        except usb.core.USBError as e:
            raise TrekError(
                f"Bulk IN failed at LBA={lba} after {len(data)}/{need} bytes: {e}"
            ) from e
        if not chunk:
            raise TrekError(f"Bulk IN returned empty at LBA={lba}")
        data.extend(chunk)
    return bytes(data)


def write_sectors(
    dev: usb.core.Device,
    ep_out,
    lba: int,
    data: bytes,
    timeout: int = 5000,
) -> None:
    """WRITE: vendor OUT 0x16 with (lba, count), then bulk OUT. Not used by dump."""
    if len(data) % SECTOR_SIZE:
        raise ValueError("data length must be a multiple of 512")
    count = len(data) // SECTOR_SIZE
    payload = _cmd_payload(lba, count)
    dev.ctrl_transfer(RT_VENDOR_ENDPOINT_OUT, REQ_WRITE, 0, 0, payload, timeout=timeout)
    ep_out.write(data, timeout=timeout)
