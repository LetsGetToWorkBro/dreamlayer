# mailbox.py — the $6 physical-events kit (INNOVATION 1.6 / O5)
#
# A reed switch on your mailbox door becomes an event on your face. Flash this
# to any ESP32 running MicroPython; when the door opens, it POSTs one line to
# your DreamLayer Brain, which forwards `ble:3` to whatever figment is on stage.
# Rehearse a figment first: "when I hear ble:3, show MAIL and pulse amber twice."
#
# Wiring: reed switch between GPIO 14 and GND (internal pull-up). Any normally-
# open contact sensor works — door, drawer, thermostat click, a plain button.
#
# Deps: MicroPython's built-in `urequests` and `network`. No libraries to pip.
#
# This is the OWNER half of 1.6 (your hardware, your LAN). The host half — the
# route this talks to — ships in the Brain and is covered by tests
# (host-python/.../tests/test_physical_events.py). Nothing here is secret: the
# only thing that ever crosses the wire is the event name.

import time

import machine
import network
import urequests

# ---- configure these three lines --------------------------------------------
WIFI_SSID = "your-network"
WIFI_PASS = "your-password"
BRAIN = "http://192.168.1.42:8765"   # your Mac's IP + the Brain port
EVENT = "ble/3"                       # → the figment hears "ble:3"; use ble/0..255
TOKEN = ""                            # the Brain's API token (Settings → pairing)
# -----------------------------------------------------------------------------

SWITCH = machine.Pin(14, machine.Pin.IN, machine.Pin.PULL_UP)
DEBOUNCE_MS = 400


def connect():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(WIFI_SSID, WIFI_PASS)
        while not wlan.isconnected():
            time.sleep(0.2)
    return wlan


def fire():
    """POST the event to the Brain. The Brain forwards it to the figment on
    stage; if nothing is armed it's a harmless no-op (returns ok:false)."""
    headers = {"Authorization": "Bearer " + TOKEN} if TOKEN else {}
    try:
        r = urequests.post(BRAIN + "/dreamlayer/event/" + EVENT, headers=headers)
        r.close()
    except Exception as e:            # never let a flaky POST wedge the loop
        print("post failed:", e)


def main():
    connect()
    last = SWITCH.value()
    fired_at = 0
    print("mailbox watcher up — waiting for the door")
    while True:
        v = SWITCH.value()
        now = time.ticks_ms()
        # falling edge = contact opened (door opened), with a debounce window
        if last == 1 and v == 0 and time.ticks_diff(now, fired_at) > DEBOUNCE_MS:
            print("door! ->", EVENT)
            fire()
            fired_at = now
        last = v
        time.sleep_ms(20)


if __name__ == "__main__":
    main()
