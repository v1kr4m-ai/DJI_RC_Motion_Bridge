"""
Pipelined sweep of the DUML (CMD_SET, CMD_ID) space, to find where the
gesture/IMU data lives.

*** WARNING -- READ FINDINGS.md "HAZARD" SECTION BEFORE RUNNING THIS. ***

Running this across the full default range WEDGED the controller: it went
dark, stopped answering, and would not power on afterwards (recovered only
via DJI Assistant 2). CMD_SET 0x00 (GENERAL) contains reboot
(CMD_ID 0x0b), firmware-upgrade and encryption commands -- blind-sweeping it
will eventually send one. Narrow CMD_SETS/CMD_IDS to a small, understood
range before using this, and never include CMD_SET 0x00.

Replies echo the request's sequence number, so we don't have to wait for
each reply before sending the next request -- we fire the whole sweep with
a unique seq per probe, drain the IN endpoint continuously, and match
replies back to probes by seq afterwards. That turns a ~7 minute
request/wait/request slog into ~30 seconds.

Workflow:
    py -3.10 sweep_cmdsets.py rest.json       # device untouched
    py -3.10 sweep_cmdsets.py active.json     # trigger HELD + tilting
    py -3.10 sweep_cmdsets.py --diff rest.json active.json

Anything that appears only in the active pass, or whose payload differs
between passes, is a candidate gesture channel.
"""
import json
import sys
import time

import usb.core
import usb.util
import usb.backend.libusb1
import libusb

import duml

VID, PID = 0x2CA3, 0x1021
OUT_EP, IN_EP = 0x01, 0x81

CMD_SETS = list(range(0x00, 0x11))
CMD_IDS = list(range(0x00, 0x100))
SEND_INTERVAL = 0.004
DRAIN_TAIL = 2.0

# Sanity target: we know cmd_set 0x06 / cmd_id 0x01 always answers. If a
# sweep finishes without it, the sweep is broken -- not the device.
KNOWN_RESPONDER = (0x06, 0x01)


def collect(dev, buf, replies, seq_map, reads, timeout):
    """Read `reads` times with a generous timeout, matching replies by seq.

    Short read timeouts do not work here: pipelining requests at a few ms
    with 1-2ms reads silently drops every reply, including ones we know the
    device always answers. The device needs tens of ms to turn a request
    around, so mirror the timing that poll_channels.py proved reliable.
    """
    for _ in range(reads):
        try:
            buf.extend(dev.read(IN_EP, 64, timeout=timeout))
        except usb.core.USBError:
            pass
        for f in duml.extract_frames(buf):
            if f["cmd_type"] != 0x80:
                continue
            probe = seq_map.get(f["seq"])
            if probe is not None:
                replies.setdefault(probe, f["payload"].hex(" "))


def sweep(path):
    backend = usb.backend.libusb1.get_backend(find_library=lambda x: libusb.dll._name)
    dev = usb.core.find(idVendor=VID, idProduct=PID, backend=backend)
    if dev is None:
        raise SystemExit("Device not found")
    dev.set_configuration()

    probes = [(s, i) for s in CMD_SETS for i in CMD_IDS]
    total = len(probes)
    print(f"Sweeping {total} (cmd_set, cmd_id) pairs (~{total * SEND_INTERVAL:.0f}s)...")

    buf = bytearray()
    replies = {}
    seq_map = {}
    seq = 0x1000

    t0 = time.time()
    for n, (cs, ci) in enumerate(probes):
        seq_map[seq] = (cs, ci)
        try:
            dev.write(OUT_EP, duml.build(0x0A, 0x06, seq, 0x40, cs, ci), timeout=50)
        except usb.core.USBError:
            pass
        seq = (seq + 1) & 0xFFFF

        collect(dev, buf, replies, seq_map, reads=2, timeout=25)

        if n % 128 == 127:
            print(f"  {n + 1}/{total}  ({len(replies)} replies so far)")

    t_end = time.time() + DRAIN_TAIL
    while time.time() < t_end:
        collect(dev, buf, replies, seq_map, reads=1, timeout=50)

    print(f"Done in {time.time() - t0:.0f}s -- {len(replies)} distinct responders.")
    if KNOWN_RESPONDER in [p for p in probes] and KNOWN_RESPONDER not in replies:
        print(f"WARNING: known-good probe cmd_set=0x{KNOWN_RESPONDER[0]:02x} "
              f"cmd_id=0x{KNOWN_RESPONDER[1]:02x} did not answer -- results are "
              f"NOT trustworthy (sweep dropping replies).")
    print()

    out = {f"{cs:02x}:{ci:02x}": pl for (cs, ci), pl in sorted(replies.items())}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print(f"Wrote {path}")

    for key, pl in sorted(out.items()):
        print(f"  cmd_set=0x{key[:2]} cmd_id=0x{key[3:]}  {pl}")


def diff(pa, pb):
    a = json.load(open(pa, encoding="utf-8"))
    b = json.load(open(pb, encoding="utf-8"))

    only_b = [k for k in b if k not in a]
    changed = [k for k in b if k in a and a[k] != b[k]]
    only_a = [k for k in a if k not in b]

    if only_b:
        print(f"--- responded ONLY in {pb} ---")
        for k in sorted(only_b):
            print(f"  cmd_set=0x{k[:2]} cmd_id=0x{k[3:]}  {b[k]}")
    if changed:
        print(f"\n--- payload CHANGED between passes ---")
        for k in sorted(changed):
            print(f"  cmd_set=0x{k[:2]} cmd_id=0x{k[3:]}")
            print(f"      {pa}: {a[k]}")
            print(f"      {pb}: {b[k]}")
    if only_a:
        print(f"\n--- responded ONLY in {pa} ---")
        for k in sorted(only_a):
            print(f"  cmd_set=0x{k[:2]} cmd_id=0x{k[3:]}  {a[k]}")

    if not (only_b or changed or only_a):
        print("No differences between the two passes.")


if __name__ == "__main__":
    try:
        if len(sys.argv) > 1 and sys.argv[1] == "--diff":
            diff(sys.argv[2], sys.argv[3])
        else:
            sweep(sys.argv[1] if len(sys.argv) > 1 else "sweep.json")
    except KeyboardInterrupt:
        print("\nStopped.")
