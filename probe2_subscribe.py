"""
Probe v2: actively writes the RC-N1 "subscribe to position push" magic
packet to the OUT endpoint every cycle (same as pverhaert/DJI_RCN1's
dji.py does), then reads the IN endpoint. If the Motion Controller
responds to the same subscribe command, we should see a NEW frame type
(not the len=19 heartbeat or len=77 identity beacon) start appearing.
"""
import time
import usb.core
import usb.util
import usb.backend.libusb1
import libusb

VID = 0x2CA3
PID = 0x1021

_backend = usb.backend.libusb1.get_backend(find_library=lambda x: libusb.dll._name)

MAGIC = bytes.fromhex('55 0d 04 33 0a 06 eb 34 40 06 01 74 24'.replace(' ', ''))

dev = usb.core.find(idVendor=VID, idProduct=PID, backend=_backend)
if dev is None:
    raise SystemExit("Device not found")

dev.set_configuration()

OUT_EP = 0x01
IN_EP = 0x81

print("Writing subscribe packet + reading, Ctrl+C to stop")
print(f"Magic OUT: {MAGIC.hex(' ')}")

last = None
seen_types = set()
while True:
    try:
        dev.write(OUT_EP, MAGIC, timeout=200)
    except usb.core.USBError as e:
        print(f"write error: {e}")

    try:
        data = bytes(dev.read(IN_EP, 64, timeout=200))
        if data != last:
            print(f"[IN] len={len(data)} {data.hex(' ')}")
            last = data
    except usb.core.USBError:
        pass

    time.sleep(0.02)
