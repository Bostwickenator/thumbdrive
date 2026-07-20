# Trek ThumbDrive (VID 0x0A16, PID 0x1111) — Protocol Findings

## Goal

Userspace dump of the raw 32MB image via Python/`pyusb`/`libusb`. The device is **not** USB Mass Storage BOT.

## Hardware

| Field | Value |
|-------|-------|
| VID | `0x0A16` (Trek Technology) |
| PID | `0x1111` (ThumbDrive) |
| Capacity | 32MB typical (`0x10000` × 512-byte sectors) |
| Write-protect | Physical switch |

Works under Windows XP with `TrekthXP.sys`. USBPcap cannot capture VirtualBox USB passthrough on a Windows host (filter-driver conflict) — protocol below is from **static analysis** of `TrekthXP.sys`, cross-checked with earlier live probes.

## Wire protocol (from TrekthXP.sys)

All vendor commands use **`URB_FUNCTION_VENDOR_ENDPOINT`** (`0x19`):

| Direction | `bmRequestType` | Notes |
|-----------|-----------------|-------|
| OUT | `0x42` | Vendor, Endpoint, Host→Device |
| IN | `0xC2` | Vendor, Endpoint, Device→Host |

`wValue` = 0, `wIndex` = 0.

### Command map

| `bRequest` | Direction | Payload / data | Role |
|------------|-----------|----------------|------|
| `0x10` | Control **IN** (`0xC2`), 31 bytes | Geometry / inquiry block | **Init** — required before useful reads |
| `0x11` | Control **OUT** (`0x42`), 8 bytes, then **Bulk IN** | `struct { uint32_le lba; uint32_le count; }` then `count * 512` bytes | **READ** |
| `0x16` | Control **OUT** (`0x42`), 8 bytes, then **Bulk OUT** | Same 8-byte header, then `count * 512` data | **WRITE** |
| `0x13` / `0x14` / `0x15` | Misc vendor | Used by proprietary IOCTLs | Not needed for dump |

**Important correction vs earlier notes:** `0x11` is **READ**, not “read capacity”. `0x16` is **WRITE**, not read. Capacity comes from command `0x10`.

### Geometry response (`bRequest=0x10`, 31 bytes)

Parsed by driver init at `PAGE!0x13955`:

| Offset | Type | Field |
|--------|------|-------|
| `+0x09` | `u16` | Geometry key (lookup table) |
| `+0x0B` | `u32` LE | Block/group count factor |
| `+0x0F` | `u32` LE | Group size (sectors); also erase/unit size |

```
total_sectors = u32(buf+0x0B) * u32(buf+0x0F)
group_size    = u32(buf+0x0F)
```

Driver then may shrink usable capacity while scanning a spare area for magic `0xAA55AA55` (bad-block / remap header). For a raw dump, dumping `total_sectors` (or a fixed 65536) is fine; usable FS size may be slightly smaller.

### Read sequence

1. `ctrl_transfer(0x42, 0x11, 0, 0, pack('<II', lba, count))`
2. `ep_in.read(count * 512)`

Writes are the same with `bRequest=0x16` and `ep_out.write(...)`.

Sector size is always **512**. The driver sometimes remaps LBAs through a spare-area table (`0x11e42`) before issuing USB; raw physical dump uses LBAs as sent on the wire without that table.

## Driver architecture notes

- `TrekthXP.sys` is a monolithic USB + storage class hybrid (based on MS `class.c` sample; pool tag `ScUn`).
- Vendor URB builder: `0x10e30` (sets URB Function `0x19`, Request, TransferBuffer, TransferFlags).
- Bulk URB: Function `0x09`, TransferFlags `3` = IN+short-OK, `0` = OUT.
- READ helper: `0x1227a` / cache path `0x11c78` → request `0x11`.
- WRITE helper: `0x123d0` → request `0x16`.
- Init / geometry: `PAGE!0x1386e` → get descriptors → vendor `0x10` → optional spare scan with `0x11`.
- Driver **synthesizes** FAT boot/MBR views for Windows (`FAT16`, `0xAA55` JMP stub in `.text`); that is host-side presentation, not necessarily on-flash layout.

## Live testing status

### Confirmed dead ends

- Standard BOT CBW/CSW — timeout
- Raw SCSI CDB on bulk — timeout
- Vendor Device (`0x40`/`0xC0`) for `0x11` — wrong recipient
- Payload `50 20 00 90...` — **false lead** (kernel/stack addresses from bad RE, not wire format)

### Partial success (reinterpreted)

- `0x42` / `0x11` once returned 8 bulk bytes with a bogus payload. That matches “control OUT then bulk IN” for READ, but the payload must be real `lba,count` (e.g. `0,1`), not IRP pointers.

### Device fragility

Failed sequences and `dev.reset()` leave the stick needing a **physical replug**. Prefer one careful probe per plug cycle.

## USB capture

**Not viable** on Windows host + VirtualBox USB passthrough: USBPcap and VBox USB filters conflict. Rely on static RE + careful pyusb probes (or a Linux host / hardware analyzer if needed later).

## Deliverables in this repo

| Path | Purpose |
|------|---------|
| [`trek_protocol.py`](trek_protocol.py) | Shared protocol helpers |
| [`trek_dump.py`](trek_dump.py) | Full-image dump CLI |
| [`test_read.py`](test_read.py) | Minimal init+LBA0 probe |
| [`WinXP/page_geometry.txt`](WinXP/page_geometry.txt) | Disasm of geometry init |
| [`WinXP/protocol_analysis.md`](WinXP/protocol_analysis.md) | URB/WDK layout notes |
