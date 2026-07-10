# The $6 Physical-Events Kit

Turn any cheap sensor into an event on your retina. A reed switch, a thermostat
click, a plain push-button — wire it to an ESP32, and when it fires, a figment
on your glasses transitions. GPIO for your face.

> "The kettle clicks off in the kitchen, and the word TEA fades onto the ring
> 40 feet away — and every hop was in your house."

## The path

```
 sensor → ESP32 (MicroPython) → POST → your Brain → BLE → figment on stage
   reed        mailbox.py       LAN     rc_event()   event    scene exit
```

The **only** thing that crosses the wire is the event *name* (`ble:3`). No
media, no telemetry, no account. The Brain forwards it to whichever figment is
armed; if none is, it's a no-op (an event grants no authority — it can only
*advance* a machine you already installed and proved).

## Try it

1. **Rehearse a figment that listens for the event.** In the phone app's
   rehearsal flow, build one whose scene exits on `ble:3` — e.g. "show WAIT;
   when I hear ble:3, show MAIL and pulse amber twice." Deploy it (it's now on
   stage).
2. **Flash the sketch.** Copy `mailbox.py` to your ESP32 with `mpremote` or
   Thonny. Edit the three config lines at the top: your Wi-Fi, your Mac's IP +
   Brain port, and the Brain API token (phone → Settings → pairing).
3. **Open the door.** The reed switch opens, the ESP32 POSTs
   `/dreamlayer/event/ble/3`, and MAIL fades onto the ring.

## The route

```
POST /dreamlayer/event/ble/<n>     → the figment hears "ble:<n>"  (n = 0..255)
POST /dreamlayer/event/<name>      → the figment hears "<name>"   (e.g. "mail")
```

Returns `{ok, name, active, mode}`; `ok:false` with an explanation when no
figment is on stage or the name is empty. The route is authenticated with the
Brain token like every other endpoint.

## Why this is only possible here

The event grammar of the behaviors on your display is **open**. Closed glasses
integrate with three blessed smart-home brands, eventually, through their
cloud. This is a local wire from a reed switch to your retina — and because the
figment's own emit/scene budgets bound what any event can do, a chatty (or
hostile) sensor *cannot* flood your eyes. The display is an interrupt target
with provable rate limits.

## Beyond the mailbox

The sketch is 60 lines and the sensor is the only thing that changes:

- **Kettle** — a thermistor on the base; fire when it crosses a threshold.
- **Drawer / cabinet** — the same reed switch, different door.
- **Doorbell** — tap the existing button's contacts.
- **Workshop** — and if you bond with a partner (Confluence), *their* sensor's
  event can cross the bond onto your Horizon ring, still rate-limited. Two
  homes' sensors, one shared surface.
