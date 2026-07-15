#!/usr/bin/env bash
# install-macos.sh — set up the DreamLayer Brain on a Mac mini.
#
# Installs Ollama + models, prepares the config dir, and installs a
# launch-at-login agent so the Brain (control panel + API) is always running.
#
#   ./install-macos.sh --token rune-birch            # loopback only (default)
#   ./install-macos.sh --lan --token rune-birch      # reachable from the phone
#
# Re-runnable. Requires Homebrew and Python 3.10+.
set -euo pipefail

TOKEN=""
LAN=0                       # bind loopback by default; --lan opts into the LAN
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CFG_DIR="${DREAMLAYER_DIR:-$HOME/.dreamlayer}"
PY="$(command -v python3)"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --token) TOKEN="$2"; shift 2;;
    --dir)   CFG_DIR="$2"; shift 2;;
    --lan)   LAN=1; shift;;   # expose the Brain to the LAN so the phone can pair
    *) echo "unknown arg: $1"; exit 1;;
  esac
done

# Loopback by default, LAN as an explicit opt-in (audit 2026-07-14): a bare
# install must not silently expose the control panel + API (and your indexed
# files/mail) to every device on the network. --lan turns that on and mandates
# a token below, mirroring the server's own guard and the companion's refusal.
if [[ "$LAN" == "1" ]]; then
  BIND_HOST="0.0.0.0"
else
  BIND_HOST="127.0.0.1"
fi

echo "→ DreamLayer Brain setup"
echo "  repo:   $REPO_ROOT"
echo "  config: $CFG_DIR"
echo "  bind:   $BIND_HOST$([[ "$LAN" == "1" ]] && echo '  (LAN — phone can pair)' || echo '  (loopback only — pass --lan to let the phone pair)')"

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
chmod 700 "$CFG_DIR" 2>/dev/null || true       # the config holds a secret
DEFAULT_FOLDER="$HOME/Documents/DreamLayer"
mkdir -p "$DEFAULT_FOLDER"

# A LAN bind MUST be authenticated — never serve the control panel + API (and
# your indexed files / mail) token-less on the network. On the --lan path, if no
# --token was given, mint a strong one now (mirrors the server's own guard and
# the companion's LAN refusal). A loopback-only bind may stay tokenless (only
# this machine can reach it), so we don't force a token the user doesn't need.
if [[ "$LAN" == "1" && -z "$TOKEN" ]]; then
  TOKEN="$("$PY" -c 'import secrets; print(secrets.token_hex(16))')"
  echo "  ⚠ --lan with no --token — generated one (needed to pair the phone):"
  echo "      $TOKEN"
fi

CFG_FILE="$CFG_DIR/brain_config.json"
if [[ ! -f "$CFG_FILE" ]]; then
  cat > "$CFG_FILE" <<JSON
{ "folders": ["$DEFAULT_FOLDER"], "model": "ollama",
  "ollama_url": "http://127.0.0.1:11434",
  "ollama_chat_model": "llama3.2",
  "ollama_vision_model": "llama3.2-vision",
  "token": "${TOKEN}" }
JSON
  echo "  wrote $CFG_FILE (watching $DEFAULT_FOLDER)"
fi
if [[ "$LAN" == "1" ]]; then
  # Persist the token into the (possibly pre-existing) config so a LAN bind is
  # never tokenless and the pairing token shown above is the one actually used.
  # Only fills an empty/missing token — never overwrites one you set.
  "$PY" - "$CFG_FILE" "$TOKEN" <<'PYEOF'
import json, pathlib, sys
p, tok = pathlib.Path(sys.argv[1]), sys.argv[2]
cfg = json.loads(p.read_text()) if p.exists() else {}
if not cfg.get("token"):
    cfg["token"] = tok
    p.write_text(json.dumps(cfg, indent=2) + "\n")
PYEOF
fi
# the token lives here — make it readable only by this user, not world/group
chmod 600 "$CFG_FILE"
echo "  $CFG_FILE (0600)"

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
    <!-- Bind loopback by default; only 0.0.0.0 when the installer was run with
         --lan. On the LAN path the config above carries a token (minted if none
         was given), and the token is read from --dir, never passed on the
         command line (no \`ps\` exposure). -->
    <string>--host</string><string>$BIND_HOST</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>DREAMLAYER_DIR</key><string>$CFG_DIR</string></dict>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
</dict></plist>
PL
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

if [[ "$LAN" == "1" ]]; then
  IP="$(ipconfig getifaddr en0 2>/dev/null || echo 127.0.0.1)"
else
  IP="127.0.0.1"
fi
echo
echo "✓ Brain installed and running."
echo "  control panel:  http://$IP:7777/"
if [[ "$LAN" == "1" ]]; then
  echo "  pair the phone with your token, drop files into $DEFAULT_FOLDER, and ask."
else
  echo "  loopback only — re-run with --lan (and a token) to pair the phone."
  echo "  drop files into $DEFAULT_FOLDER and ask from this Mac."
fi
echo "  (see docs/OLLAMA_SETUP.md to tune the models)"
