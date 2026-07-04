# WebBLE Playground

`playground.html` — drive the Halo / Frame HUD straight from a browser over
Bluetooth, no app store and no build. It speaks Lua to the glasses over the
**Nordic UART Service** (`6e400001-…`: RX `…0002` write, TX `…0003` notify),
the same transport the phone hub uses.

## Run it

It's a single self-contained file. Open it in a supported browser (locally or
served anywhere):

```
# any static server, e.g.
python3 -m http.server -d web 8080
# then visit http://localhost:8080/playground.html
```

Click **Connect glasses**, pick your device, then use the canned demos (show
text, clear, battery, dots) or type Lua into the REPL. Replies stream back on
TX into the log.

## Browser support — the hard caveat

Web Bluetooth works in **Chrome / Edge on Android, macOS, Windows, Linux**.

- **iPhone / iPad Safari does _not_ support Web Bluetooth** — Apple does not
  implement the API. On iOS, use the DreamLayer app. The page detects this and
  shows a clear message instead of a dead button.
- **Firefox** does not support it either.

This is a companion / dev-and-hacking surface, not a replacement for the phone
hub. It's the fastest way to poke the HUD from a laptop and to learn the Lua
API without installing anything.
