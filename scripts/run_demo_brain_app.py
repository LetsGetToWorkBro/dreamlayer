#!/usr/bin/env python3
"""scripts/run_demo_brain_app.py — the DreamLayer Brain app, end to end.

Boots the real Brain server (the thing you run on a Mac mini), drops a couple
of files into a watched folder, then does what the phone and the control panel
do over real HTTP: add a folder, ask questions grounded in your files, and
read the query history back. Shows the config layer working with no model —
plug Ollama on the Mac mini for written answers + vision.

Run:  python scripts/run_demo_brain_app.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "host-python" / "src"))

from dreamlayer.ai_brain.server import Brain, BrainConfig, make_brain_server  # noqa: E402
from dreamlayer.ai_brain import BrainRouter, connect_brain                    # noqa: E402

TOKEN = "rune-birch"


def _op():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def main() -> int:
    d = Path(tempfile.mkdtemp())
    notes = d / "notes"; notes.mkdir()
    (notes / "lease.md").write_text(
        "Rent is 2400 per month, due on the first.\n\n"
        "The lease at 44 Birch St ends in June 2026.")
    (notes / "people.md").write_text(
        "Marcus owes me the signed contract.\n\nPriya prefers tea, not coffee.")
    cfg = d / "cfg"; cfg.mkdir()
    BrainConfig(token=TOKEN, folders=[str(notes)]).save(cfg)

    brain = Brain(cfg)
    server = make_brain_server(brain, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    print("\nDreamLayer Brain — the app you run on your Mac mini\n")
    print(f"  control panel would be at  {base}/")
    print(f"  watching 1 folder · {brain.index.stats()['files']} files indexed\n")

    try:
        # the phone connects with the same token and asks your files
        router = BrainRouter()
        connect_brain(router, base, token=TOKEN)
        print("  the phone asks (answers come from your own files):")
        for q in ["how much is the rent",
                  "when does the lease end",
                  "what does Marcus owe me"]:
            ans = router.ask(q)
            src = ans.sources[0] if ans and ans.sources else "—"
            print(f"    “{q}?”\n       → {ans.text}   [{ans.tier}: {src}]")

        # drop a new file in and it's instantly answerable
        def post(p, pl):
            r = urllib.request.Request(
                base + p, data=json.dumps(pl).encode(),
                headers={"Content-Type": "application/json",
                         "X-DreamLayer-Token": TOKEN})
            return json.loads(_op().open(r, timeout=5).read())
        (notes / "car.md").write_text("The car is a 2019 blue Subaru, plate 8XYZ123.")
        post("/dreamlayer/folders", {"action": "add", "path": str(notes)})  # reindex
        print("\n  you drop car.md into the folder, then ask:")
        ans = router.ask("what's my license plate")
        print(f"    → {ans.text}   [{ans.tier}: {ans.sources[0]}]")

        req = urllib.request.Request(base + "/dreamlayer/history",
                                     headers={"X-DreamLayer-Token": TOKEN})
        items = json.loads(_op().open(req, timeout=5).read())["items"]
        print(f"\n  query history: {len(items)} questions remembered "
              f"(newest: “{items[0]['query']}”)")
        print("\n  Add Ollama on the Mac mini and the same answers become "
              "written prose + vision.\n")
    finally:
        server.shutdown(); server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
