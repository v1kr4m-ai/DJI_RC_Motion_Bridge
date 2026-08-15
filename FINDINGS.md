# Reverse-engineering findings — DJI RC Motion Controller

## Setup
- VID:PID `2CA3:1021`, must be rebound from `libusb-win32` to **WinUSB** via
  Zadig ("List All Devices" → BULK Interface → WinUSB → Replace Driver)
  before `pyusb` (libusb1 backend) can open it.
- Interface 0: `EP 0x01 OUT` (bulk, 64B) / `EP 0x81 IN` (bulk, 64B).
- Interface 1: class 255, no endpoints (control-transfer only, unexplored).

## Protocol
DUML-framed, same family as RC-N1 (`0x55` sync byte, 10-bit length in
bytes 1-2). Header layout (offset : field):
```
0: 0x55 SOF
1-2: length (little-endian u16, low 10 bits) | version (top 6 bits)
3: header CRC8
4: SENDER
5: RECEIVER
6-7: SEQ (little-endian u16, increments ~11/packet at idle)
8: CMDSET
9: CMDID
10..n-2: DATA
n-2..n: CRC16
```

## Frame types observed

| Type | Length | CMDSET/CMDID | Behavior |
|---|---|---|---|
| A | 19 | `0x00`/`0x06` | Periodic heartbeat, device→host. Payload `1e 28 0a 00 00 64 XX` where XX flips 0→1 once a subscribe write is sent (see below). Otherwise **static regardless of physical input** — not telemetry. |
| B | 77 | `0x40`/`0x00` | Periodic identity beacon, device→host. Contains ASCII `"rc221"` (device model string). Static padding, not telemetry. |
| C | 23 | `0x80`/`0x06` | Only appears **after** writing the subscribe command below. Data `01 00 00 04 01 80 00 02 80 00 03`. Looks like a capability/ack reply. Also static — not telemetry either. |

## Confirmed: write channel is live

Writing the RC-N1 bridge's exact magic packet to `EP 0x01 OUT`:
```
55 0d 04 33 0a 06 eb 34 40 06 01 74 24
```
(decodes to SENDER=0x0a RECEIVER=0x06 CMDSET=0x40 CMDID=0x06 DATA=[0x01] —
i.e. "enable channel" with a generic RC-N1-style command reused verbatim)
produces two observable effects:
1. Type A's last payload byte flips `00`→`01` (state acknowledged).
2. A new Type C frame starts appearing.

**Neither carries changing data when the controller is tilted / trigger
pulled / buttons pressed.** So this specific subscribe command enables
*something* (possibly just a heartbeat-ack channel), but not the actual
IMU/trigger telemetry stream.

## Device identity confirmed

Physical hardware: **DJI RC Motion 3**. Windows records it as a composite
device with (at least) 3 interfaces, though only one is currently active:

| Interface | Class | Status |
|---|---|---|
| MI_00 | `libusb-win32 devices` (bulk) | **Active** — this is what `probe.py` talks to |
| MI_01 | WPD (media transfer / file access) | Phantom — seen in a past session, not currently enumerating |
| MI_02 | **ADB Interface** (Android Debug Bridge!) | Phantom — same |

The phantom MI_01/MI_02 records carry a real device serial
(`6UZTP15001UDX1`), while the currently-active MI_00 connection reports a
placeholder-looking serial (`123456789FEDCBA`) — hints the controller may
expose ADB only in a different connection mode/state than whatever we're
currently triggering by plain USB-C plug-in. Not yet reproduced.

**If ADB access can be reproduced**, it changes the whole approach: `adb
shell` / `logcat` on the device's internal Android system could expose
IMU/trigger/button state directly (DJI RC hardware commonly runs Android
internally), sidestepping the raw-USB-protocol reverse-engineering entirely.
Worth chasing before going deeper on the DUML brute-force route.

## Next steps (not yet done)

The real gesture-data channel almost certainly needs a **different**
CMDSET/CMDID/DATA combination than the one borrowed from RC-N1 — the
Motion Controller has entirely different data sources (IMU, trigger,
record button) than a stick controller, so it's unlikely to share the
exact same channel number.

To find it:
1. Try varying the DATA byte (channel/subscribe-item ID) in the same
   frame shape (`CMDSET=0x40 CMDID=0x06 DATA=[N]` for N = 0x00 through
   ~0x10) and watch for a new frame type with content that changes when
   the controller is moved.
2. Try known-generic DUML subscription CMDSETs from public docs
   (`samuelsadok/dji_protocol`, `fvantienen/dji_rev`) — DUML's generic
   data-subscription mechanism (distinct from this per-device shortcut)
   is usually CMDSET `0x00`, various CMDIDs for "subscribe to push".
3. Try Interface 1 (control transfers via EP0) — unexplored, may carry a
   config/handshake step that's a prerequisite for streaming to start on
   Interface 0.
4. If available: capture real DJI software (DJI Assistant 2 / Virtual
   Flight) talking to the device via Wireshark + USBPcap, to see the
   actual command sequence it sends — much faster than blind brute force.

## Tools in this repo
- `probe.py` — passive listener, dumps raw bytes from all IN endpoints.
- `analyze.py` — reconstructs DUML frames from a probe.py log, groups by
  length, shows payload changes over time.
- `probe2_subscribe.py` — active probe, writes the RC-N1 magic subscribe
  packet every cycle while reading. Confirmed the write channel works;
  starting point for trying other subscribe payloads.
