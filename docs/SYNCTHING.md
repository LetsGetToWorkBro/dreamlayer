# Your memory follows you — without the cloud (Syncthing)

The Cloud card's biggest promise — *your memory on every device* — ships today
with [Syncthing](https://syncthing.net): battle-tested, encrypted, peer-to-peer
folder sync. No server, no account, no third party ever holding your bytes.
Device-to-device TLS, the exact posture DreamLayer already promises.

## The recipe (five minutes)

1. Install Syncthing on the Brain machine and on the device you want your
   memory to follow you to (Mac, Linux, Windows, Android all supported):
   `brew install syncthing` / your package manager / syncthing.net/downloads.
2. On the Brain machine, open the Syncthing UI at `http://127.0.0.1:8384`
   and **Add Folder** pointing at the Brain's config directory
   (`~/.dreamlayer` by default — it holds `people.json`, `meetings.json`,
   the activity ledger, the memory DB).
3. **Share** the folder with your other device (scan the device QR once).
4. On the other device, accept the share. Done — every memory write now
   replicates peer-to-peer, encrypted in transit, versioned by Syncthing.

DreamLayer's dashboard shows this as the **folder_sync** capability: it probes
`http://127.0.0.1:8384` and lights up when Syncthing is running locally.

## Cautions (honest ones)

* **One writer at a time.** The Brain assumes it owns its config dir. Sync a
  *second Brain* against the same folder only if one of them is idle — two
  live Brains writing the same `people.json` will race (Syncthing keeps
  conflict copies; nothing is lost, but resolution is manual).
* **The receipt key stays put.** `receipt.key` (the Ed25519 seed that signs
  your activity ledger) syncing to your own devices is fine — they're yours —
  but add it to Syncthing's ignore patterns if you'd rather each device keep
  its own signing identity: `.stignore` → `receipt.key`.
* **Encrypt at rest where it matters.** Syncthing encrypts *in transit*. For
  an untrusted intermediate device, use Syncthing's "untrusted device"
  (encrypted-at-rest) mode for the share.
