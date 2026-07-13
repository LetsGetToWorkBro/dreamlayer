# DreamLayer — Demo Script

All demos run headless against the emulator + deterministic fixtures.

## Demo 1 — Object Recall
```bash
python -c "from dreamlayer.simulator import scenarios; print(scenarios.object_recall()[1])"
```
Seeds `object_keys_scene.json`, asks "where did I leave my keys", renders **ObjectRecallCard**.
Expected HUD:
- Keys
- Kitchen table
- Beside blue notebook
- Last seen 7:42 PM
`python -m dreamlayer.hud.export` regenerates `assets/hud/samples/object_recall.png`.

## Demo 2 — Commitment Recall
```bash
python -c "from dreamlayer.simulator import scenarios; print(scenarios.commitment_recall()[1])"
```
Seeds `conversation_invoice.json`, asks "what did I promise Jordan", renders
**CommitmentRecallCard**.
Expected HUD:
- You promised Jordan
- Send the invoice
- Tomorrow before noon

## Demo 3 — Proactive Place Memory
```bash
python -c "from dreamlayer.simulator import scenarios; print(scenarios.proactive_recall()[1])"
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
- Privacy Veil
- Nothing is being captured
