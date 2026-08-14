"""
Raw USB probe for DJI RC Motion Controller (VID 2CA3, PID 1021).
No known protocol docs exist for this device -- this script just opens it
via libusb and dumps whatever comes out of every readable endpoint, so we
can reverse-engineer the packet format by watching bytes change as you
move the controller / press buttons.

Usage: py -3.10 probe.py
Then physically: tilt the controller, pull the trigger, press record,
press C1/C2/Fn buttons -- one at a time, pausing between each -- and watch
for byte changes in the output.
"""
import sys
import time

import usb.core
import usb.util
import usb.backend.libusb1
import libusb

VID = 0x2CA3
PID = 0x1021

_backend = usb.backend.libusb1.get_backend(find_library=lambda x: libusb.dll._name)

def find_device():
    dev = usb.core.find(idVendor=VID, idProduct=PID, backend=_backend)
    if dev is None:
        print(f"Device {VID:04x}:{PID:04x} not found. Is it plugged in (bottom USB-C port) and powered on?")
        sys.exit(1)
    return dev

def describe(dev):
    print(f"Device found: {dev.idVendor:04x}:{dev.idProduct:04x}")
    print(f"  Manufacturer: {usb.util.get_string(dev, dev.iManufacturer) if dev.iManufacturer else '?'}")
    print(f"  Product: {usb.util.get_string(dev, dev.iProduct) if dev.iProduct else '?'}")
    for cfg in dev:
        print(f"Config {cfg.bConfigurationValue}:")
        for intf in cfg:
            print(f"  Interface {intf.bInterfaceNumber} alt {intf.bAlternateSetting}, class {intf.bInterfaceClass}")
            for ep in intf:
                direction = "IN" if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN else "OUT"
                ep_type = usb.util.endpoint_type(ep.bmAttributes)
                type_names = {0: "CONTROL", 1: "ISOCHRONOUS", 2: "BULK", 3: "INTERRUPT"}
                print(f"    EP 0x{ep.bEndpointAddress:02x} {direction} {type_names.get(ep_type, ep_type)} "
                      f"wMaxPacketSize={ep.wMaxPacketSize}")
    return cfg

def main():
    dev = find_device()

    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except (NotImplementedError, usb.core.USBError):
        pass  # Windows: no kernel driver concept the same way, ignore

    cfg = describe(dev)

    try:
        dev.set_configuration()
    except usb.core.USBError as e:
        print(f"set_configuration failed (may be harmless on Windows): {e}")

    # collect all IN endpoints across all interfaces
    in_endpoints = []
    for intf in cfg:
        for ep in intf:
            if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN:
                in_endpoints.append((intf.bInterfaceNumber, ep))

    if not in_endpoints:
        print("No IN endpoints found -- nothing to read.")
        return

    print(f"\nFound {len(in_endpoints)} IN endpoint(s). Reading in a loop.")
    print("Move sticks/trigger/buttons on the controller now. Ctrl+C to stop.\n")

    last_data = {}
    while True:
        for intf_num, ep in in_endpoints:
            try:
                data = dev.read(ep.bEndpointAddress, ep.wMaxPacketSize, timeout=200)
                data = bytes(data)
                key = ep.bEndpointAddress
                if data != last_data.get(key):
                    hexstr = ' '.join(f'{b:02x}' for b in data)
                    print(f"[EP 0x{key:02x}] {hexstr}")
                    last_data[key] = data
            except usb.core.USBError as e:
                if e.errno not in (110, None):  # 110 = timeout, expected when idle
                    pass  # stay quiet on routine timeouts
        time.sleep(0.01)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
