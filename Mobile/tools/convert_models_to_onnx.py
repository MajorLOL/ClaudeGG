#!/usr/bin/env python3
"""Developer tool: converts the RegiBot TFLite models to ONNX and proves the copies agree.

The C++ port of the Pokémon GO bot runs its models with ONNX Runtime, which this
program already ships (the machine learning module), instead of adding TFLite as
a second runtime. This script is the one place that says how the ONNX files are
made and how close they are to the TFLite originals the Raspberry Pi runs.

    python3 tools/convert_models_to_onnx.py <folder with the .tflite files> <output folder> [--no-check]

It needs: tflite2onnx, onnx, onnxruntime, ai-edge-litert and numpy (without --no-check, which only converts: LiteRT
and ONNX Runtime are then not needed; the build on Windows uses it).

Next to the .onnx files it writes the anchors of the two detectors (from models/anchors.npz) as plain floats,
model_detector_map_v2_anchors.f32 and model_detector_clickable_v2_anchors.f32 (27,621 x 4 little-endian float32 each),
which the C++ port reads without a library for .npz files.

For each model it feeds the same seeded random picture to LiteRT (the original)
and to ONNX Runtime (the copy) and fails when an output differs by more than
TOLERANCE. tflite2onnx turns the pictures into channels-first (NCHW); the
check does the same turn on its input, and the C++ side has to as well.

model_detector_encounter is left out on purpose: it ends in the custom
operation TFLite_Detection_PostProcess, which ONNX has no name for. To run it
in C++ the network is cut in front of that operation and the box decoding and
the non-maximum suppression are done in the program's own code.
"""
import sys
from pathlib import Path

import numpy as np

MODELS = {
    # name: input shape of the TFLite model (NHWC, or flat for the predictor)
    "predictor": (1, 4),
    "model_classifier_screen_v5": (1, 224, 224, 3),
    "model_detector_map_v2": (1, 384, 384, 3),
    "model_detector_clickable_v2": (1, 384, 384, 3),
}
TOLERANCE = 1e-4
SEED = 5


ANCHORS = ("model_detector_map_v2_anchors", "model_detector_clickable_v2_anchors")


def write_anchors(target: Path) -> None:
    npz = np.load(Path(__file__).resolve().parent.parent / "models" / "anchors.npz")
    for name in ANCHORS:
        anchors = np.ascontiguousarray(npz[name], dtype="<f4")
        assert anchors.shape == (27621, 4), anchors.shape
        (target / f"{name}.f32").write_bytes(anchors.tobytes())


def convert(tflite_path: Path, onnx_path: Path) -> None:
    import tflite2onnx
    tflite2onnx.convert(str(tflite_path), str(onnx_path))


def outputs_tflite(path: Path, x: np.ndarray) -> list:
    from ai_edge_litert.interpreter import Interpreter
    it = Interpreter(model_path=str(path))
    it.allocate_tensors()
    it.set_tensor(it.get_input_details()[0]["index"], x)
    it.invoke()
    return [it.get_tensor(d["index"]) for d in it.get_output_details()]


def outputs_onnx(path: Path, x: np.ndarray) -> list:
    import onnxruntime
    session = onnxruntime.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    first = session.get_inputs()[0]
    if x.ndim == 4 and list(first.shape)[1] == 3:
        x = np.ascontiguousarray(x.transpose(0, 3, 1, 2))
    return session.run(None, {first.name: x})


def main(argv: list) -> int:
    check = "--no-check" not in argv
    argv = [a for a in argv if a != "--no-check"]
    if len(argv) != 3:
        print(__doc__)
        return 2
    source, target = Path(argv[1]), Path(argv[2])
    target.mkdir(parents=True, exist_ok=True)
    write_anchors(target)
    rng = np.random.default_rng(SEED)
    worst = 0.0
    for name, shape in MODELS.items():
        tflite_path, onnx_path = source / f"{name}.tflite", target / f"{name}.onnx"
        convert(tflite_path, onnx_path)
        if not check:
            print(f"{name}: converted")
            continue
        x = rng.random(shape, dtype=np.float32)
        original, copy = outputs_tflite(tflite_path, x), outputs_onnx(onnx_path, x)
        if len(original) != len(copy):
            print(f"{name}: {len(original)} outputs in TFLite, {len(copy)} in ONNX")
            return 1
        for i, (a, b) in enumerate(zip(original, copy)):
            if a.shape != b.shape:
                print(f"{name}: output {i} has shape {a.shape} in TFLite and {b.shape} in ONNX")
                return 1
            diff = float(np.abs(a - b).max())
            worst = max(worst, diff)
            print(f"{name}: output {i} {a.shape} largest difference {diff:.3g}")
    if not check:
        return 0
    if worst > TOLERANCE:
        print(f"The largest difference {worst:.3g} is above {TOLERANCE}.")
        return 1
    print(f"All outputs agree to {worst:.3g} (limit {TOLERANCE}).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
