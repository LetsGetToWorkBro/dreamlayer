# Viral storyboards

Three first-person clips, each **9:16, 12–15s, one job-to-be-done, one jaw-drop**.
The HUD in every beat is the *real* rendered card (see `storyboards.py`) — export
with `python -m dreamlayer.demo <name> <out>` and composite over your POV footage
(Screen/Add blend; timing in `manifest.json`).

Shape of every clip: **trigger → card → human outcome.**

---

## 1. Veritas — "the number that didn't add up"  (~13.5s)

The most shareable: it shows *intelligence*, not an overlay.

| t (s) | Shot (POV) | Audio | On-screen (real card) |
|------|------------|-------|-----------------------|
| 0–1 | Two coffees, a table, a man (Marcus) mid-sentence | room tone | — |
| 1–4.2 | He gestures | his VO: "We settled at two million, remember?" | caption: *Marcus — "We settled at two million…"* |
| 4.6–7.6 | He leans in | his VO: "The deal closed at three million." | caption: *Marcus — "…closed at three million."* |
| 7.9–13.5 | Your gaze holds on him | **earcon: watchout1**; your VO (optional): "It remembered what he said last week." | **FactCheckCard** — THEY SAID DIFFERENT BEFORE · *earlier: "we settled at two million"* · footer *Marcus · elevated · seen before* |

Caption punch-in for posting: **"My glasses caught him lying in real time."**

---

## 2. Answer-ahead — "the answer before you speak"  (~9.5s)

| t (s) | Shot (POV) | Audio | On-screen |
|------|------------|-------|-----------|
| 0–1 | Across a desk, a colleague (Priya) looks up | room tone | — |
| 1–4.5 | She asks | her VO: "When did we last ship to Denver?" | caption: *Priya — "When did we last ship to Denver?"* |
| 3.4–9.5 | You open your mouth — but it's already there | *silence by design*; your VO: "I hadn't said a word yet." | **AnswerAheadCard** — ON THE TIP OF YOUR TONGUE · *March 14th — two pallets.* · *Priya · your files* |

Caption punch-in: **"It answered before I could."**

---

## 3. Owe-someone — "it remembered so you didn't have to"  (~13.6s)

| t (s) | Shot (POV) | Audio | On-screen |
|------|------------|-------|-----------|
| 0–1.2 | Walking a lobby, someone approaching | footsteps | — |
| 1.2–5.4 | You slow | **earcon: listen1** | **HarkCard** — LISTEN · *Marcus is 2 min away — you owe him the lease.* · *from your last chat* |
| 5.7–10.5 | He's here | handshake foley | **CommitmentRecallCard** — *Send the signed lease* · due *today* |
| 10.8–13.6 | You hand over an envelope, he smiles | your VO: "I never opened my phone." | **JunoReplyCard** — JUNO · *Handed off. One less thing.* |

Caption punch-in: **"It nudged me before I walked past the one guy I owed."**

---

### Production notes
- Shoot POV real (head-mount / phone at brow) — honesty reads, and a fact-checker demo that's *staged* is self-defeating.
- Earcons: `phone-app/assets/sounds/{watchout1,listen1}.mp3`. Answer-ahead stays silent.
- Grade the plate a touch cool/dark so the emissive HUD (teal/amber) separates.
- Keep each cut on the beat the card lands — the reveal is the product.
