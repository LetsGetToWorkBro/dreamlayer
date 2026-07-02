# Ollama on the Mac mini — making the Brain smart

The DreamLayer Brain works out of the box with keyword retrieval (no model).
Adding **Ollama** gives it two things: written answers from your files (a
chat model turns retrieved passages into prose) and **vision** (explain what
you look at). Everything stays on the Mac mini — Ollama is a local server.

## 1. Install Ollama

```bash
brew install ollama          # or download from https://ollama.com
ollama serve                 # runs the local API on http://127.0.0.1:11434
```

## 2. Pull the models

Good defaults for an Apple-Silicon Mac mini:

```bash
ollama pull llama3.2              # chat — writes answers from your notes
ollama pull llama3.2-vision       # vision — explains what you look at
ollama pull nomic-embed-text      # embeddings — for semantic file search
```

Smaller Mac mini? `llama3.2:1b` and `moondream` (vision) are lighter. Bigger?
`qwen2.5` / `qwen2-vl` are stronger. The Brain doesn't care which — set the
names in the control panel.

## 3. Point the Brain at it

In the control panel (`http://<mac-mini>:7777/`) → **Model**:

- choose **Ollama**
- URL `http://127.0.0.1:11434`
- chat model `llama3.2`, vision model `llama3.2-vision`
- **Save**

Or in `~/.dreamlayer/brain_config.json`:

```json
{ "model": "ollama",
  "ollama_url": "http://127.0.0.1:11434",
  "ollama_chat_model": "llama3.2",
  "ollama_vision_model": "llama3.2-vision" }
```

## 4. Verify

Ask a question in the panel — the answer is now written prose citing your
files, not just the raw passage. Look at an object through the glasses and
the AI Object Lens explains it. If Ollama is down, the Brain silently falls
back to keyword answers, so it never breaks.

## Notes

- Ollama and the Brain both run on the Mac mini; the phone only ever talks to
  the Brain (token-paired), never to Ollama directly.
- First model load is slow (cold start); after that it's warm.
- Nothing leaves the machine. The opt-in **cloud** tier (for the hardest
  asks) is separate and off until you enable it.
