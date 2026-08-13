# DJI RC Motion Controller → PC Bridge (WIP)

**Status: reverse-engineering in progress. Not working yet.**

No existing open-source tool turns a DJI RC Motion Controller into a PC game
controller. This repo is an attempt to build one, from scratch, since the
device's protocol isn't documented anywhere publicly.

## Why this is harder than the RC-N1 bridge

DJI's stick-based remotes (RC-N1, RC 2, RM330, etc.) all speak the same
DUML-over-serial-VCOM protocol, and multiple existing tools already read it
(see [DJI_RCN1_for_drone_simulators](https://github.com/pverhaert/DJI_RCN1_for_drone_simulators),
[DJI-RC-Emulator](https://github.com/deviverr/DJI-RC-Emulator)). The Motion
Controller is a different beast:

- No analog sticks — pitch/roll come from an internal IMU (gesture control),
  plus a trigger, a record button, and a few auxiliary buttons.
- It does **not** enumerate as a `DJI USB VCOM For Protocol` serial port.
  Windows Device Manager shows it under `libusb-win32 devices`
  (`USB\VID_2CA3&PID_1021`) — raw USB, not a virtual COM port.
- No existing GitHub project documents its packet format.

## What's confirmed so far

| Property | Value |
|---|---|
| USB VID:PID | `2CA3:1021` |
| Windows driver class | `libusb-win32 devices` (not Ports/VCOM) |
| Known working similar tools | None found for this exact device |

## Plan

1. **`probe.py`** — opens the device via `pyusb`/libusb, enumerates its USB
   descriptor (interfaces, endpoints), and dumps raw bytes from every
   readable endpoint while the controller is manipulated (tilt, trigger,
   buttons) — to reverse-engineer the packet structure by observation.
2. Correlate byte changes with physical actions to map out the packet
   layout (likely still DUML-framed, `0x55` header like RC-N1's protocol,
   since DJI reuses DUML across the product line).
3. Once the packet format is known, write a proper bridge: parse → push to
   a virtual Xbox controller via `vgamepad`/ViGEm (same approach as the
   RC-N1 bridge).
4. Publish for others once it reliably works.

## Setup for probing

```bash
py -3.10 -m pip install pyusb libusb
py -3.10 probe.py
```

Requires: [ViGEmBus](https://github.com/ViGEm/ViGEmBus/releases) (for later,
once we build the actual bridge) and the device connected via its bottom
USB-C port, powered on.

## References used

- [DUML protocol partial docs (samuelsadok/dji_protocol)](https://github.com/samuelsadok/dji_protocol)
- [dji_rev — DJI reverse engineering notes](https://github.com/fvantienen/dji_rev)
- [DJI RC2 Reverse Engineering Research Notes](https://docs.f1y.ing/pen-testing/drones/github-dji-rc2-research)
- [pyduml](https://github.com/hdnes/pyduml)

## Contributing

If you have a DJI RC Motion Controller and some USB reverse-engineering
patience, PRs and packet captures welcome once this is public.

## License

MIT
