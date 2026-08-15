# Reverse-engineering findings — DJI RC Motion 3

**Status: trigger axis decoded and working. Gesture/IMU axes still not
located.**

## Setup
- VID:PID `2CA3:1021`, must be rebound from `libusb-win32` to **WinUSB** via
  Zadig ("List All Devices" → BULK Interface → WinUSB → Replace Driver)
  before `pyusb` (libusb1 backend) can open it. Windows sometimes reverts
  this on replug — if `dev.set_configuration()` raises
  `USBError: [Errno 2] Entity not found`, re-run Zadig and replace the
  driver again.
- Interface 0: `EP 0x01 OUT` (bulk, 64B) / `EP 0x81 IN` (bulk, 64B).
- Interface 1: class 255, no endpoints (control-transfer only, unexplored).

## Protocol — DUML (corrected header layout)

DUML-framed, same family as RC-N1. **The header has a `CMD_TYPE` byte at
offset 8 that an earlier revision of this document missed**, which shifted
`CMD_SET`/`CMD_ID` by one and made every command decode in this file wrong.
Corrected:

```
0      : 0x55 SOF
1-2    : u16 LE — low 10 bits = total packet length, top 6 bits = version (=1)
3      : header CRC8 (seed 0x77, computed over bytes 0-2)
4      : SENDER
5      : RECEIVER
6-7    : SEQ (u16 LE)
8      : CMD_TYPE   — 0x40 = request (ack wanted), 0x80 = reply
9      : CMD_SET    — 0x06 = RADIO
10     : CMD_ID
11..n-3: PAYLOAD    — byte 11 is a status/return code (0x00 = OK)
n-2..n : CRC16 (seed 0x3692, over everything preceding)
```

Three independent facts confirm this layout, all from our own captures:
1. Replies **echo the request's exact sequence number** (we sent seq
   `0x350c` with `CMD_ID=0x03`; the reply carried seq `0x350c`).
2. Byte 8 flips `0x40`→`0x80` between request and reply while byte 9 stays
   `0x06`. Under the old layout the *command set* would have changed
   between a request and its own response, which is nonsense.
3. `build()` in `duml.py` reproduces the known-good RC-N1 magic packet
   byte-for-byte from these field definitions.

Both CRC algorithms are implemented and verified byte-exact in `duml.py`
(CRC8 table/seed from mefistotelis/phantom-firmware-tools, CRC16 from
hdnes/pyduml). **We can now construct arbitrary valid DUML frames**, which
is what unblocked everything below.

### Parser correctness warning

Do **not** reconstruct frames by scanning for `0x55` and trusting the
length field, as `analyze.py` / `analyze_brute.py` do. Payload bytes
frequently contain `0x55`, so that approach false-syncs and manufactures
phantom "changing" values — this is exactly what produced several bogus
leads earlier in this investigation. `duml.extract_frames()` validates
CRC16 on every frame before accepting it; use that.

## CONFIRMED: trigger axis decoded

`CMD_SET=0x06` (RADIO) / `CMD_ID=0x01` is a **polled request/response**
channel query — not a push stream. Send the request, get current channel
values back immediately. Reply payload:

```
status(1=0x00) + N × [ value(u16 LE), channel_id(u8) ]
```

`CMD_ID=0x04` returns the same values without the channel-id bytes.

Values use **DJI's standard analog range: 364 min / 1024 center / 1684
max** — identical to the stick-based remotes.

| Channel | Source | Behavior |
|---|---|---|
| **1** | **Trigger** | **Proportional analog.** 1024 at rest → 1684 fully squeezed. Verified: a slow half-squeeze produced 35 distinct intermediate values ramping smoothly 1171→1366. Returns to exactly 1024 when released. |
| 2 | unknown | Static `128` (0x80) in every test |
| 3 | unknown | Static `128` (0x80) in every test |

Tested against this channel set and confirmed **not** present: pitch tilt,
roll tilt, yaw, violent shaking, and every button (record / lock / Fn).
Channels 2 and 3 never moved under any input. Their resting value of 128
is the midpoint of an 8-bit 0-255 range rather than the 364-1684 analog
band, so they are likely a different kind of field entirely (mode/status
byte?) rather than idle gesture axes.

Poll it with `poll_channels.py [seconds] [cmd_id_hex]`, which decodes
channels and reports per-channel min/max/span so brief changes can't be
missed.

## ⚠ HAZARD: do not blind-sweep the whole command space

A pipelined sweep of all 4352 `(CMD_SET 0x00-0x10, CMD_ID 0x00-0xFF)` pairs
(`sweep_cmdsets.py` as originally written) **wedged the controller**: it
stopped answering the known-good channel query, then would not power on at
all — no LEDs, unresponsive to the power button, including a 20-30s hard
press.

The device still enumerated on USB the whole time (`2CA3:1021` present in a
full `pyusb` device listing), so it was not electrically damaged — data
commands over the bulk endpoint cannot do that. The likely cause is that
the blind sweep hit a power-off / reboot / enter-bootloader command. DUML
has several in that space, e.g. `CMD_SET=0x00 CMD_ID=0x0b` is documented as
**Chip Reboot**, plus firmware-upgrade and encryption commands around
`0x30`.

**Rules going forward:**
- Never sweep `CMD_SET=0x00` (GENERAL) blindly — that is where reboot,
  upgrade-mode and encryption commands live.
- Probe narrow, targeted ranges and read the public command tables
  (o-gs/dji-firmware-tools `comm_dissector/`) before sending anything new.
- Prefer known-safe query commands; treat any unrecognised `CMD_ID` in
  GENERAL as potentially destructive to device state.

**Recovery:** DJI Assistant 2 is the standard path for a device stuck in
bootloader/upgrade mode. Note that Assistant 2 needs DJI's own USB driver —
if the device has been rebound to WinUSB via Zadig for `pyusb` work, uninstall
that driver first (Device Manager → Uninstall device → tick "attempt to
remove the driver", then replug) so Windows restores the DJI driver.

## Ruled out

- **`CMD_ID` sweep 0x00-0x10 within `CMD_SET=0x06`** (`brute_subscribe.py`).
  Only `CMD_ID` 0x01, 0x03, 0x04, 0x07 return distinct replies; 0x03/0x07
  return short constant acks, 0x01/0x04 are the channel query documented
  above. No IMU/gesture data anywhere in this range. (Note: this sweep was
  originally written believing it varied a "DATA byte" — under the
  corrected layout it was varying `CMD_ID`, which is why it was still a
  useful thing to have run.)
- **Goggles-as-relay.** Paired the Motion Controller to the Goggles by
  normal RF pairing, connected the **Goggles** to the PC by USB-C, relaunched
  DJI Virtual Flight. Its "Goggles" button opens a "Select Control Method"
  dialog hardcoded to "DJI FPV RC 2" text — not a real device picker — and
  Confirm proceeds to the simulator screen with no connection gating at
  all. Goggles stayed disconnected, controller unresponsive, no input
  reached the sim. This path does not expose Motion Controller data.

## Other frames seen (device→host, unsolicited)

| Length | CMD_TYPE/SET/ID | Content |
|---|---|---|
| 19 | `0x00`/`0x06`/`0x1e` | Periodic heartbeat. Payload `28 0a 00 00 64 XX`. |
| 77 | `0x40`/`0x00`/`0x81` and `0x82` | Periodic identity beacon, alternating between two IDs. Contains ASCII `"rc221"` (device model string) + mostly zero padding. |

## Device identity

Physical hardware: **DJI RC Motion 3**, model string `rc221`. Windows
records it as a composite device with (at least) 3 interfaces, though only
one is currently active:

| Interface | Class | Status |
|---|---|---|
| MI_00 | `libusb-win32 devices` (bulk) | **Active** — everything above talks to this |
| MI_01 | WPD (media transfer / file access) | Phantom — seen in a past session, not currently enumerating |
| MI_02 | **ADB Interface** (Android Debug Bridge!) | Phantom — same |

The phantom MI_01/MI_02 records carry a real device serial
(`6UZTP15001UDX1`), while the currently-active MI_00 connection reports a
placeholder-looking serial (`123456789FEDCBA`) — hints the controller may
expose ADB only in a different connection mode/state than whatever plain
USB-C plug-in triggers. Not yet reproduced.

**If ADB access can be reproduced**, `adb shell` / `logcat` on the device's
internal Android system could expose IMU/trigger/button state directly
(DJI RC hardware commonly runs Android internally), sidestepping the
remaining protocol work entirely.

## Next steps

The trigger is solved; the gesture/IMU axes are the remaining unknown. The
Motion Controller very likely only produces IMU data when it believes it is
in an active flight context, which would explain why the channel query
exposes the trigger (a raw hardware control) but leaves the gesture axes
absent rather than idling at center.

1. **Sweep `CMD_SET` broadly**, now that frames can be built correctly.
   Known DUML sets: 0x00 GENERAL, 0x01 SPECIAL, 0x02 CAMERA,
   0x03 FLYCONTROLLER, 0x04 ZENMUSE (gimbal — IMU-adjacent),
   0x05 CENTER_BOARD, 0x06 RADIO, 0x07 WIFI, 0x09 OFDM, 0x0B SIM,
   0x0F RTK, 0x10 AUTOTEST. Look for a set/id pair whose reply changes
   under tilt.
2. **Look for a mode/arm command.** Something has to put the controller
   into gesture-streaming mode. Channels 2/3 sitting at a constant 128 may
   be a mode indicator worth watching while other commands are tried.
3. **Interface 1** (control transfers via EP0, class 255) — unexplored, may
   carry a handshake that is a prerequisite for gesture streaming.
4. **ADB lead** above.

## Tools in this repo

- `duml.py` — shared protocol module: CRC8/CRC16, `build()`, `parse()`,
  and CRC-validating `extract_frames()`. **Use this**, not the older
  ad-hoc parsers.
- `poll_channels.py` — polls the RADIO channel query, decodes named
  channels, reports min/max/span per channel. The main working tool.
- `probe.py` — original passive listener, dumps raw bytes from IN endpoints.
- `probe2_subscribe.py` — writes the RC-N1 magic packet while reading.
- `brute_subscribe.py` — sweeps `CMD_ID` 0x00-0x10 on `CMD_SET=0x06`.
- `analyze.py`, `analyze_brute.py` — early log analyzers. **Both use the
  naive 0x55 scan and the pre-correction header layout; treat their output
  as unreliable.** Kept only for reference.
