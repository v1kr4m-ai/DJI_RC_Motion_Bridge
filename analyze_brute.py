"""
Proper DUML frame reconstruction over brute_subscribe.py's log (same
approach as analyze.py, but pulls hex out of "[DATA=0xNN] [IN] len=.. <hex>"
lines instead of probe.py's "[EP 0x81] <hex>" lines, and keeps the DATA=
tag that was active when each byte arrived so we can tell which subscribe
channel produced which frame).
"""
import re
import struct
import sys

LOG = sys.argv[1] if len(sys.argv) > 1 else "brute_log.txt"

# reconstruct stream + a parallel array of "which DATA=0xNN section" each byte
# arrived under, from the tagged IN lines.
stream = bytearray()
tags = []
current_tag = None

line_re = re.compile(r"^\[DATA=(0x[0-9a-f]+)\]\s*\[IN\]\s*len=\d+\s+([0-9a-f ]+?)(\s+\*\*\*.*)?$")
section_re = re.compile(r"^--- DATA=(0x[0-9a-f]+)\s")

with open(LOG, "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        line = line.rstrip("\n")
        m = section_re.match(line)
        if m:
            current_tag = m.group(1)
            continue
        m = line_re.match(line)
        if not m:
            continue
        tag = m.group(1)
        hexpart = m.group(2).strip()
        try:
            b = bytes.fromhex(hexpart.replace(" ", ""))
        except ValueError:
            continue
        stream.extend(b)
        tags.extend([tag] * len(b))

print(f"Total bytes reconstructed: {len(stream)}")

i = 0
frames = []  # (offset, frame_bytes, tag_at_start)
while i < len(stream) - 3:
    if stream[i] == 0x55:
        ph = struct.unpack("<H", bytes(stream[i+1:i+3]))[0]
        pl = ph & 0b0000001111111111
        if pl >= 10 and i + pl <= len(stream):
            frame = bytes(stream[i:i+pl])
            frames.append((i, frame, tags[i]))
            i += pl
            continue
    i += 1

by_shape = {}
for off, f, tag in frames:
    cmdset, cmdid = f[8], f[9]
    key = (len(f), cmdset, cmdid)
    by_shape.setdefault(key, []).append((off, f, tag))

print(f"\nTotal frames reconstructed: {len(frames)}")
print(f"Distinct (len, cmdset, cmdid) shapes: {len(by_shape)}\n")

for key in sorted(by_shape):
    length, cmdset, cmdid = key
    occs = by_shape[key]
    print(f"--- len={length} cmdset={cmdset:#04x} cmdid={cmdid:#04x}  ({len(occs)} occurrences) ---")
    prev_data = None
    for off, f, tag in occs:
        data = f[10:-2]
        if data != prev_data:
            print(f"  [{tag}] {data.hex(' ')}")
            prev_data = data
    print()
