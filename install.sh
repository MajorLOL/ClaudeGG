#!/bin/bash
# Installs gamebot (image recognition with LiteRT) on the Raspberry Pi.
# Run it from the folder of this repository:   bash install.sh
# Prerequisite packages (adb, tesseract, ffmpeg, OpenCV, ...): see the wiki page "Requirements".
set -e
REPO="$(cd "$(dirname "$0")" && pwd)"
cd ~

echo "== Python environment =="
[ -d ~/gbvenv ] || python3 -m venv --system-site-packages ~/gbvenv
~/gbvenv/bin/pip uninstall -y mediapipe opencv-contrib-python 2>/dev/null || true   # does not work on the Pi 4
~/gbvenv/bin/pip install ai-edge-litert

echo "== Models from RegiBot (MIT license) =="
mkdir -p ~/models
cd ~/models
for m in model_classifier_screen_v5 model_detector_clickable_v2 model_detector_encounter model_detector_map_v2; do
  [ -s "$m.tflite" ] || curl -fL -o "$m.tflite" \
    "https://media.githubusercontent.com/media/Juancavr6/RegiBot/main/app/app/src/main/assets/$m.tflite"
done
cp "$REPO"/models/*.npz ~/models/     # anchors + throw predictor weights (derived from RegiBot, see NOTICE.md)
cp "$REPO"/models/battle_data.json ~/models/     # battle data (from PvPoke, MIT, see NOTICE.md)
ls -la ~/models

echo "== Program files =="
if [ "$REPO" != "$HOME" ]; then
  cp "$REPO"/gamebot.py "$REPO"/spin_stop.py "$REPO"/web.py "$REPO"/device_check.py "$REPO"/battle_engine.py "$REPO"/battle_nav.py ~/
fi
ls -la ~/gamebot.py ~/spin_stop.py ~/web.py ~/device_check.py ~/battle_engine.py ~/battle_nav.py

echo "== Test =="
cd ~
~/gbvenv/bin/python -c "from ai_edge_litert.interpreter import Interpreter; import cv2, numpy; print('LiteRT ok, OpenCV', cv2.__version__)"
echo
echo "Done. Test with:  ~/gbvenv/bin/python gamebot.py test"
echo "Updating an existing installation? The running services still use the old files. Restart them:"
echo "    sudo systemctl restart gamebot-web spin-stop     (then reload the web page with Ctrl+F5)"
echo "Next: install the services, the sudoers rule and the web password (wiki page 'Installation')."
