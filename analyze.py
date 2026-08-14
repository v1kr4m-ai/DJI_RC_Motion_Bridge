"""
Parses probe.py's log output, reconstructs the DUML frame stream (frames
span multiple 64-byte USB reads), and prints Type-A (len=19) frame payloads
in order so we can see which bytes change over time / correlate with
physical actions performed during capture.
"""
import re
import struct
import sys

LOG = sys.argv[1] if len(sys.argv) > 1 else "probe_log.txt"

# reconstruct the raw byte stream from all "[EP 0x81] <hex...>" lines
stream = bytearray()
with open(LOG, "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        m = re.match(r"\[EP 0x81\]\s*(.*)", line)
        if not m:
            continue
        hexpart = m.group(1).strip()
        if not hexpart:
            continue
        try:
            stream.extend(bytes.fromhex(hexpart.replace(" ", "")))
        except ValueError:
            continue

print(f"Total bytes reconstructed: {len(stream)}")

# walk the stream looking for 0x55 frame headers, parse DUML length field
i = 0
frames = []
while i < len(stream) - 3:
    if stream[i] == 0x55:
        ph = struct.unpack("<H", stream[i+1:i+3])[0]
        pl = ph & 0b0000001111111111
        if pl >= 3 and i + pl <= len(stream):
            frame = bytes(stream[i:i+pl])
            frames.append((i, frame))
            i += pl
            continue
    i += 1

typeA = [f for off, f in frames if len(f) == 19]
typeB = [f for off, f in frames if len(f) == 77]
other = [f for off, f in frames if len(f) not in (19, 77)]

print(f"Type A (len 19) frames: {len(typeA)}")
print(f"Type B (len 77) frames: {len(typeB)}")
print(f"Other length frames: {len(other)}")
if other:
    lens = sorted(set(len(f) for f in other))
    print(f"  other lengths seen: {lens}")

print("\n--- Type A payload evolution (bytes 6:13, hex) ---")
prev = None
for f in typeA:
    payload = f[6:13]
    hexstr = payload.hex(' ')
    if payload != prev:
        print(hexstr)
        prev = payload

print(f"\n(printed only when payload changed; {len(typeA)} total Type A frames)")
