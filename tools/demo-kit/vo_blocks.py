"""Locate the 14 VO blocks in a transcribed take (word timestamps) by matching
each block's opening words. Outputs /tmp/blocks_<take>.json with start/end/dur.
Usage: vo_blocks.py <tag> [openers.json]   (reads /tmp/words_<tag>.json)"""
from __future__ import annotations
import json, sys

OPENERS = [
    ("intro",       ["dreamlayer"]),
    ("dmg",         ["one", "dmg"]),
    ("drag",        ["drag"]),
    ("applications",["applications", "there"]),
    ("home",        ["this", "is", "the", "brain"]),
    ("day",         ["your", "day"]),
    ("mind",        ["intelligence"]),
    ("reach",       ["connections"]),
    ("privacy",     ["privacy"]),
    ("plugins",     ["plugins"]),
    ("caps",        ["capabilities"]),
    ("learn",       ["learn"]),
    ("advanced",    ["advanced"]),
    ("outro",       ["zero", "point", "one"]),
]

def norm(w): return w.lower().strip(".,!?'’\"")

def find(words, seq, from_i):
    n = len(seq)
    for i in range(from_i, len(words)-n+1):
        if all(norm(words[i+k]["w"]) == seq[k] for k in range(n)):
            return i
    return -1

def main(tag, openers_path=None):
    global OPENERS
    if openers_path:
        OPENERS=[(o["name"], o["seq"]) for o in json.load(open(openers_path))]
    words = json.load(open(f"/tmp/words_{tag}.json"))
    idxs = []
    cur = 0
    for name, seq in OPENERS:
        i = find(words, seq, cur)
        if i < 0:
            print(f"MISS {name} (searching from word {cur})"); idxs.append(None); continue
        idxs.append(i); cur = i + len(seq)
    blocks = []
    for k, (name, _) in enumerate(OPENERS):
        i = idxs[k]
        if i is None: continue
        start = words[i]["s"]
        if k+1 < len(idxs) and idxs[k+1] is not None:
            end = words[idxs[k+1]-1]["e"]
        else:
            end = words[-1]["e"]
        blocks.append({"name": name, "s": round(start,2), "e": round(end,2), "dur": round(end-start,2)})
    json.dump(blocks, open(f"/tmp/blocks_{tag}.json","w"), indent=1)
    for b in blocks: print(f"{b['name']:>13}: {b['s']:7.2f} → {b['e']:7.2f}  ({b['dur']:.2f}s)")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv)>2 else None)
