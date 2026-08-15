"""
Polls the Motion Controller's RADIO channel-value query and decodes the
reply into named analog channels.

cmd_set 0x06 (RADIO) / cmd_id 0x01 replies with:
    status(1) + N * [ value(u16 LE), channel_id(1) ]
cmd_id 0x04 replies with the same values, without the channel ids.

Values sit in DJI's standard analog range (364 min / 1024 center / 1684
max), the same one the stick-based remotes use.

Unlike the earlier probes, every frame here is CRC16-validated before being
decoded, so a 0x55 byte occurring inside a payload can't false-sync the
parser and manufacture phantom "changing" values.

Usage: py -3.10 poll_channels.py [duration_seconds] [cmd_id_hex]
"""
import sys
import time
import usb.core
import usb.util
import usb.backend.libusb1
import libusb

import duml

VID, PID = 0x2CA3, 0x1021
OUT_EP, IN_EP = 0x01, 0x81


def decode(cmd_id, payload):
    """-> dict {channel_id: value}, or None if it doesn't fit the shape."""
    if not payload or payload[0] != 0x00:
        return None
    body = payload[1:]
    chans = {}
    if cmd_id == 0x01:
        if len(body) % 3:
            return None
        for i in range(0, len(body), 3):
            val = body[i] | (body[i + 1] << 8)
            chans[body[i + 2]] = val
    else:
        if len(body) % 2:
            return None
        for i in range(0, len(body), 2):
            chans[i // 2 + 1] = body[i] | (body[i + 1] << 8)
    return chans


def main():
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 10.0
    cmd_id = int(sys.argv[2], 16) if len(sys.argv) > 2 else 0x01

    backend = usb.backend.libusb1.get_backend(find_library=lambda x: libusb.dll._name)
    dev = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
    if dev is None:
        raise SystemExit("Device not found")
    dev.set_configuration()

    buf = bytearray()
    seq = 0x3000
    samples = []       # (elapsed, {ch: val})
    t0 = time.time()
    last_poll = 0.0

    print(f"Polling cmd_set=0x06 cmd_id=0x{cmd_id:02x} for {duration:.0f}s "
          f"(range {duml.CH_MIN}/{duml.CH_CENTER}/{duml.CH_MAX})\n")

    while time.time() - t0 < duration:
        now = time.time()
        if now - last_poll >= 0.02:
            pkt = duml.build(0x0A, 0x06, seq, 0x40, 0x06, cmd_id)
            seq = (seq + 1) & 0xFFFF
            try:
                dev.write(OUT_EP, pkt, timeout=100)
            except usb.core.USBError:
                pass
            last_poll = now

        try:
            buf.extend(dev.read(IN_EP, 64, timeout=100))
        except usb.core.USBError:
            pass

        for f in duml.extract_frames(buf):
            if f["cmd_set"] != 0x06 or f["cmd_id"] != cmd_id or f["cmd_type"] != 0x80:
                continue
            chans = decode(cmd_id, f["payload"])
            if chans:
                samples.append((time.time() - t0, chans))

    if not samples:
        print("No valid replies decoded.")
        return

    ids = sorted({c for _, ch in samples for c in ch})
    print(f"{len(samples)} samples, channels seen: {ids}\n")

    print("channel   min   max  span  distinct  verdict")
    for cid in ids:
        vals = [ch[cid] for _, ch in samples if cid in ch]
        lo, hi = min(vals), max(vals)
        span = hi - lo
        verdict = "MOVED" if span > 20 else "static"
        print(f"  {cid:>5} {lo:>5} {hi:>5} {span:>5} {len(set(vals)):>9}  {verdict}")

    print("\nvalue changes over time:")
    prev = None
    shown = 0
    for t, ch in samples:
        cur = tuple(ch.get(c) for c in ids)
        if cur != prev:
            print(f"  [{t:6.2f}s] " + "  ".join(f"ch{c}={ch.get(c)}" for c in ids))
            prev = cur
            shown += 1
            if shown > 60:
                print("  ... (truncated)")
                break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
