#!/bin/bash
# Installs the Claude GG agent on a Raspberry Pi: the hands and eyes of an Android phone.
# Run it from this folder on the Pi:   bash install-agent.sh
# The phone is on the Pi's USB cable with USB debugging on (see README.md in this folder).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
TARGET="$HOME/claudegg-agent"

echo "== Packages =="
sudo apt-get install -y adb python3 ffmpeg

echo "== The agent =="
mkdir -p "$TARGET"
cp "$HERE/claudegg_agent.py" "$TARGET/"
chmod 755 "$TARGET/claudegg_agent.py"

echo "== Permission to start and stop the bot (for these three commands only) =="
#  Claude GG starts the Pokemon GO bot (the service spin-stop) through this agent. The agent runs as
#  you, so it needs sudo for exactly these three commands, without a password; nothing else.
RULE="$USER ALL=(root) NOPASSWD: /usr/bin/systemctl start spin-stop, /usr/bin/systemctl stop spin-stop, /usr/bin/systemctl restart spin-stop"
RULE_FILE="$(mktemp)"
echo "$RULE" > "$RULE_FILE"
if sudo visudo -cf "$RULE_FILE" >/dev/null; then
  sudo install -m 0440 -o root -g root "$RULE_FILE" /etc/sudoers.d/claudegg-agent
  echo "Written: /etc/sudoers.d/claudegg-agent"
else
  echo "visudo did not accept the rule, so nothing was written: add the rule of the Installation page of the bot yourself."
fi
rm -f "$RULE_FILE"

echo "== The service (starts by itself, restarts when it stops) =="
sudo tee /etc/systemd/system/claudegg-agent.service >/dev/null <<UNIT
[Unit]
Description=Claude GG agent (the hands and eyes of an Android phone)
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$TARGET
ExecStart=/usr/bin/python3 $TARGET/claudegg_agent.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now claudegg-agent
sleep 2

echo
echo "== The phone =="
adb start-server >/dev/null 2>&1 || true
adb devices
echo "(A line with 'device' is a phone that works; 'unauthorized': accept the question on the phone.)"

echo
echo "== What to enter in Claude GG =="
echo "Address: $(hostname -I | awk '{print $1}')   Port: 8765"
echo "Token:   $(python3 "$TARGET/claudegg_agent.py" --print-token)"
echo "Anyone who has the token can use the phone: keep it to yourself."
