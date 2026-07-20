# Trek ThumbDrive drivers and dump tool

The original Trek ThumbDrive (VID `0A16` / PID `1111`, typically 32MB) predates USB Mass Storage Bulk-Only Transport. Modern OSes cannot mount it as a normal flash drive. This repo reverse-engineers the proprietary Trek protocol and provides a userspace tool that dumps a **raw disk image** (same idea as `dd` of a block device).

Historical OS drivers live under `Win98/`, `Win2000/`, and `WinXP/`. **These may be used directly** inside approriate virutal machines.

Protocol notes are in [findings.md](findings.md).


## 1. Set up USB access (libusb)

`trek_dump.py` talks to the stick through **libusb**. The OS must not own the device with an incompatible driver.

### Windows (Zadig)

1. Plug in the ThumbDrive.
2. Download [Zadig](https://zadig.akeo.ie/).
3. Options → **List All Devices**.
4. Select the Trek device (`VID_0A16` / `PID_1111`, often labeled “ThumbDrive”).
5. Replace the driver with **WinUSB** or **libusbK** (either works with `libusb-package`).
6. Click **Replace Driver** / **Install Driver**.

After that, Device Manager should show the stick under “Universal Serial Bus devices” (WinUSB) rather than as an unknown/storage device Windows cannot use.

### Linux

Usually no Zadig equivalent is needed. Unbind any mass-storage claim if present, then grant access:

```bash
# Optional: see the device
lsusb | grep -i 0a16

# Access via udev (example rule)
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="0a16", ATTR{idProduct}=="1111", MODE="0666"' \
  | sudo tee /etc/udev/rules.d/99-trek-thumbdrive.rules
sudo udevadm control --reload-rules
# Unplug/replug the stick
```

### macOS

Install libusb (Homebrew) and run the tool; claim the interface from userspace:

```bash
brew install libusb
pip install -r requirements.txt
```

If macOS attaches something to the device, unload it for the session or use a tool that detaches the kernel driver (pyusb will try `detach_kernel_driver` where supported).

---

## 2. Install python depdancies

```bash
pip install -r requirements.txt
```

## 3. Dump the data
```
# Smoke test (geometry + read LBA 0)
python test_read.py

# Full dump (~32 MiB)
python trek_dump.py out.img
```

Useful options:

```bash
python trek_dump.py --lba 0 --count 64 probe.img   # partial
python trek_dump.py --sectors 65536 out.img         # force 32MiB if geometry fails
python trek_dump.py --chunk 32 out.img              # sectors per USB READ
```

### What the output file is

`out.img` is a **raw sector dump** of the flash, starting at LBA 0:

- This is the same format you'd get by using `dd if=/dev/sdX of=out.img` with a modern device
- It is not a `.zip`, VHD, or ISO container — just concatenated 512-byte sectors
- A successful 32MB stick is **33 554 432 bytes** (`65536 × 512`)
- LBA 0 is typically a FAT boot sector (JMP + `0x55AA`); the image is usually a **superfloppy** (filesystem in the whole image, no MBR partition table)

**If a transfer times out:** physically unplug and replug, then retry. Do **not** USB-reset the device — that leaves it uninitialized.

At this point you have a backup of the data you just need to mount it as a filesystem to read the files out.

---

## 4. Mount/read the image

Prefer **read-only** mounts so you do not alter the dump.

### Windows 

#### via disk tools

There are tools that can mount raw disk images, for example OSFMount - https://www.osforensics.com/tools/mount-disk-images.html 

#### via WSL2

Copy or access the image from the Windows filesystem (e.g. `/mnt/c/Users/.../thumbdrive/out.img`), then:

```bash
sudo mkdir -p /mnt/trek
sudo mount -o loop,ro,uid=$(id -u),gid=$(id -g) /mnt/c/Users/<you>/Dev/thumbdrive/out.img /mnt/trek
ls /mnt/trek
# when done:
sudo umount /mnt/trek
```

If mount complains about the filesystem type, try:

```bash
sudo mount -t vfat -o loop,ro,uid=$(id -u),gid=$(id -g) out.img /mnt/trek
```

WSL2 note: loop mounts need a modern WSL2 kernel (they work on current releases). Run these commands **inside** the Linux distro, not in PowerShell.

### Linux (native)

```bash
sudo mkdir -p /mnt/trek
sudo mount -o loop,ro,uid=$(id -u),gid=$(id -g) out.img /mnt/trek
# or explicitly:
sudo mount -t vfat -o loop,ro out.img /mnt/trek

sudo umount /mnt/trek
```

If the image ever has an MBR with partitions (unusual for this device):

```bash
sudo losetup -fP --show out.img    # prints e.g. /dev/loop0
sudo mount -o ro /dev/loop0p1 /mnt/trek
# cleanup: sudo umount /mnt/trek; sudo losetup -d /dev/loop0
```

### macOS

Attach as a raw disk image, then mount the volume read-only:

```bash
# Attach (often creates /dev/diskN)
hdiutil attach -readonly -imagekey diskimage-class=CRawDiskImage out.img

# If it does not auto-mount, find the device and mount manually:
diskutil list
mkdir -p ~/trek-mnt
# Use the slice that holds the FAT volume, e.g. /dev/disk4s1 — check diskutil output
sudo mount -t msdos -o ro /dev/diskNsM ~/trek-mnt

# Detach when finished
hdiutil detach /dev/diskN
```

Alternatively, open the `.img` with a GUI tool that understands raw FAT images (e.g. [FUSE for macOS](https://osxfuse.github.io/) + `ext4fuse`/`fuse-t` variants, or a hex/disk utility). For a simple FAT superfloppy, `hdiutil attach -readonly` is usually enough and Finder will show the volume.

---

## 4. Repo layout

| Path | Purpose |
|------|---------|
| `trek_dump.py` | Full-image dump CLI |
| `test_read.py` | Geometry + LBA0 smoke test |
| `trek_protocol.py` | Shared USB protocol helpers |
| `requirements.txt` | `pyusb`, `libusb-package` |
| `findings.md` | Protocol reverse-engineering notes |
| `WinXP/` / `Win2000/` / `Win98/` | Original Trek drivers |

### Protocol (short)

| Request | Meaning |
|---------|---------|
| `0x10` | Geometry (Vendor IN) |
| `0x11` | READ (Vendor OUT + Bulk IN) |
| `0x16` | WRITE (Vendor OUT + Bulk OUT) |

Details: [findings.md](findings.md), [WinXP/protocol_analysis.md](WinXP/protocol_analysis.md).
