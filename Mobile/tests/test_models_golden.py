"""The file that the C++ port of the models is tested against is what the models say now.  If this fails, a model,
gamebot.py (Brain._ssd, Brain.screen, Brain.throw_params) or the pictures changed: run
python3 tools/make_models_golden.py --models DIR  and port the change to
SerialPrograms/Source/ClaudeGG/ClaudeGG_PokemonGoModels.cpp (its test then says what differs).

The models are not in the repository, so this test needs them: the folder with the .tflite files is the one in the
environment variable CLAUDEGG_TFLITE (the workflow Mobile Python tests fetches them and checks their hashes), or
~/models on the Raspberry Pi.  Without them, or without LiteRT, the test is skipped."""
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "..", "tools", "make_models_golden.py")
NEEDED = ("model_classifier_screen_v5.tflite", "model_detector_map_v2.tflite", "model_detector_clickable_v2.tflite",
          "model_detector_encounter.tflite")


def models_folder():
    folder = os.environ.get("CLAUDEGG_TFLITE") or os.path.expanduser("~/models")
    return folder if all(os.path.isfile(os.path.join(folder, name)) for name in NEEDED) else None


class ModelsGolden(unittest.TestCase):
    def test_the_golden_file_is_current(self):
        folder = models_folder()
        if folder is None:
            self.skipTest("the .tflite models are not here (CLAUDEGG_TFLITE)")
        try:
            import ai_edge_litert  # noqa: F401
        except ImportError:
            self.skipTest("LiteRT (ai-edge-litert) is not installed")
        done = subprocess.run([sys.executable, TOOL, "--models", folder, "--check"], capture_output=True)
        self.assertEqual(done.returncode, 0, done.stdout.decode() + done.stderr.decode())


if __name__ == "__main__":
    unittest.main()
