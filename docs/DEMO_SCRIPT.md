# DreamLayer — Demo Script

All demos run headless against the emulator + deterministic fixtures.

## Demo 1 — Object Recall
```bash
python scripts/run_demo_object_recall.py
```
Seeds `object_keys_scene.json`, asks "where are my keys", renders **ObjectRecallCard**.
Expected HUD:
- Keys
- Kitchen table
- Beside blue notebook
- Last seen 7:42 PM
Exports `assets/hud/samples/object_recall.png`.

## Demo 2 — Commitment Recall
```bash
python scripts/run_demo_conversation.py
```
Seeds `conversation_invoice.json`, asks "what did I promise Jordan", renders
**CommitmentRecallCard**.
Expected HUD:
- You promised Jordan
- Send the invoice
- Tomorrow before noon

## Demo 3 — Proactive Place Memory
```bash
python scripts/run_demo_proactive.py
```
Seeds `place_invoice_memory.json`, triggers place recognition, renders
**ProactiveMemoryCard**.
Expected HUD:
- Last time here
- You discussed the invoice
- With Jordan

## Demo 4 — Privacy Veil
Triggered via `privacy_pause` event in the emulator; renders **PrivacyVeilCard**.
Expected HUD:
- Privacy Veil engaged
- Nothing is being captured
