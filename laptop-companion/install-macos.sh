#!/usr/bin/env bash
# install-macos.sh — set up the DreamLayer Brain on a Mac mini.
#
# Installs Ollama + models, prepares the config dir, and installs a
# launch-at-login agent so the Brain (control panel + API) is always running.
#
#   ./install-macos.sh --token rune-birch
#
# Re-runnable. Requires Homebrew and Python 3.10+.
set -euo pipefail

TOKEN=""
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CFG_DIR="${DREAMLAYER_DIR:-$HOME/.dreamlayer}"
PY="$(command -v python3)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --token) TOKEN="$2"; shift 2;;
    --dir)   CFG_DIR="$2"; shift 2;;
    *) echo "unknown arg: $1"; exit 1;;
  esac
done

echo "→ DreamLayer Brain setup"
echo "  repo:   $REPO_ROOT"
echo "  config: $CFG_DIR"

# 1. Ollama + models (the local AI). Skip if you only want keyword search.
if ! command -v ollama >/dev/null 2>&1; then
  echo "→ installing Ollama"; brew install ollama
fi
echo "→ pulling models (this can take a while the first time)"
ollama pull llama3.2          || true
ollama pull llama3.2-vision   || true
ollama pull nomic-embed-text  || true

# 2. Python deps for the Brain (stdlib-only server, but install the package)
echo "→ installing the dreamlayer package"
"$PY" -m pip install -e "$REPO_ROOT/host-python" >/dev/null

# 3. Config dir + a first folder to index
mkdir -p "$CFG_DIR"
DEFAULT_FOLDER="$HOME/Documents/DreamLayer"
mkdir -p "$DEFAULT_FOLDER"
if [[ ! -f "$CFG_DIR/brain_config.json" ]]; then
  cat > "$CFG_DIR/brain_config.json" <<JSON
{ "folders": ["$DEFAULT_FOLDER"], "model": "ollama",
  "ollama_url": "http://127.0.0.1:11434",
  "ollama_chat_model": "llama3.2",
  "ollama_vision_model": "llama3.2-vision",
  "token": "${TOKEN}" }
JSON
  echo "  wrote $CFG_DIR/brain_config.json (watching $DEFAULT_FOLDER)"
fi

# 4. Launch-at-login agent
PLIST="$HOME/Library/LaunchAgents/vision.dreamlayer.brain.plist"
mkdir -p "$(dirname "$PLIST")"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>vision.dreamlayer.brain</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string><string>-m</string>
    <string>dreamlayer.ai_brain.server</string>
    <string>--dir</string><string>$CFG_DIR</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>DREAMLAYER_DIR</key><string>$CFG_DIR</string></dict>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
</dict></plist>
PL
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

IP="$(ipconfig getifaddr en0 2>/dev/null || echo 127.0.0.1)"
echo
echo "✓ Brain installed and running."
echo "  control panel:  http://$IP:7777/"
echo "  pair the phone with your token, drop files into $DEFAULT_FOLDER, and ask."
echo "  (see docs/OLLAMA_SETUP.md to tune the models)"
