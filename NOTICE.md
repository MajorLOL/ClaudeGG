# Third-party notices

## RegiBot

This project uses models and data from **RegiBot** (https://github.com/Juancavr6/RegiBot), which is released under the MIT License:

- `model_classifier_screen_v5.tflite`, `model_detector_map_v2.tflite`, `model_detector_clickable_v2.tflite` and `model_detector_encounter.tflite` are **not** part of this repository. `install.sh` downloads them from the RegiBot repository.
- `models/anchors.npz` (detector anchors) and `models/predictor_weights.npz` (the weights of the throw predictor) are derived from RegiBot's model files and are included here under the same MIT License.

```
MIT License

Copyright (c) 2025 Juancavr6

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## PvPoke

The battle engine (`battle_engine.py`) uses game data from **PvPoke** (https://github.com/pvpoke/pvpoke), which is released under the MIT License: species base stats, moves, the CP multiplier table and the type effectiveness chart. `tools/build_battle_data.py` boils these down to `models/battle_data.json`, which is included here under the same MIT License. The damage formula follows PvPoke's `DamageCalculator.js`, and the rule that shields an attack after which the Pokémon could not survive the opponent's next round of fast attacks follows PvPoke's `ActionLogic.js`.

```
MIT License

Copyright (c) 2019 pvpoke

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Trademarks

Pokémon, Pokémon GO and related names are trademarks of their respective owners. This project is unofficial and is not affiliated with or endorsed by Niantic, Nintendo, The Pokémon Company or Google.
