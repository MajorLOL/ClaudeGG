#!/usr/bin/env python3
"""Developer tool: converts the RegiBot TFLite models to ONNX and proves the copies agree.

The C++ port of the Pokémon GO bot runs its models with ONNX Runtime, which this
program already ships (the machine learning module), instead of adding TFLite as
a second runtime. This script is the one place that says how the ONNX files are
made and how close they are to the TFLite originals the Raspberry Pi runs.

    python3 tools/convert_models_to_onnx.py <folder with the .tflite files> <output folder> [--no-check]

It needs: tflite2onnx, onnx, ai-edge-litert and numpy, and with the check also onnxruntime (without --no-check, which
only converts, ONNX Runtime is not needed; the build on Windows uses that).

Four models are converted as they are (predictor, screen classifier, map detector, clickable detector).  Next to them the
output folder gets the anchors of the detectors as plain floats (27,621 x 4 little-endian float32 for the map and the
clickable detector from models/anchors.npz, 51,150 x 4 for the encounter detector from the model itself), which the C++
port reads without a library for .npz files.

model_detector_encounter cannot be converted as it is: it ends in the custom operation TFLite_Detection_PostProcess,
which ONNX has no name for, and it makes its two-fold enlargements of the picture with PACK, which tflite2onnx does not
know.  cut_encounter() makes a copy of the TFLite file in which every enlargement (PACK, RESHAPE, PACK, RESHAPE: every
pixel twice along a row, then every row twice) is one RESIZE_NEAREST_NEIGHBOR, which is the same numbers, and in which the
network stops in front of the post-processing: it gives the 51,150 box encodings and the 51,150 x 4 certainties (the
background and three classes).  That copy is written as model_detector_encounter_cut.tflite and converted to
model_detector_encounter.onnx.  What the post-processing did (decode the boxes with the anchors, pick the best class of
every box, take the 10 best boxes that do not cover each other: the fast variant of non-maximum suppression) is done by the
C++ port; the parameters it needs are the ones in the model (checked here).

For each model the check feeds the same seeded random picture to LiteRT (the original; for the encounter detector the cut
copy) and to ONNX Runtime (the converted copy) and fails when an output differs by more than TOLERANCE.  tflite2onnx turns
the pictures into channels-first (NCHW); the check does the same turn on its input, and the C++ side has to as well.
"""
import struct
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
ENCOUNTER = "model_detector_encounter"
ENCOUNTER_SHAPE = (1, 640, 640, 3)
# what the post-processing of the encounter detector does, as the C++ port has it (checked against the model)
ENCOUNTER_OPTIONS = {
    "y_scale": 10.0, "x_scale": 10.0, "h_scale": 5.0, "w_scale": 5.0, "max_detections": 10,
    "max_classes_per_detection": 1, "num_classes": 3, "use_regular_nms": 0, "nms_score_threshold": 0.0,
}
ENCOUNTER_IOU = 0.6
TOLERANCE = 1e-4
SEED = 5


ANCHORS = ("model_detector_map_v2_anchors", "model_detector_clickable_v2_anchors")


def write_anchors(target: Path) -> None:
    npz = np.load(Path(__file__).resolve().parent.parent / "models" / "anchors.npz")
    for name in ANCHORS:
        anchors = np.ascontiguousarray(npz[name], dtype="<f4")
        assert anchors.shape == (27621, 4), anchors.shape
        (target / f"{name}.f32").write_bytes(anchors.tobytes())


def cut_encounter(path: Path):
    """(the TFLite file of the encounter detector cut in front of its post-processing, as bytes; its anchors [51150, 4])."""
    import flatbuffers
    from ai_edge_litert import schema_py_generated as schema
    from flatbuffers import flexbuffers

    ops_of = schema.BuiltinOperator
    model = schema.ModelT.InitFromObj(schema.Model.GetRootAsModel(path.read_bytes(), 0))
    graph = model.subgraphs[0]

    def kind(op):
        return model.operatorCodes[op.opcodeIndex].builtinCode

    resize_code = next((i for i, code in enumerate(model.operatorCodes) if code.builtinCode == ops_of.RESIZE_NEAREST_NEIGHBOR), None)
    if resize_code is None:
        code = schema.OperatorCodeT()
        code.builtinCode = code.deprecatedBuiltinCode = ops_of.RESIZE_NEAREST_NEIGHBOR
        code.version = 1
        model.operatorCodes.append(code)
        resize_code = len(model.operatorCodes) - 1

    operators, new_operators, at = list(graph.operators), [], 0
    while at < len(operators):
        op = operators[at]
        if kind(op) != ops_of.PACK:
            new_operators.append(op)
            at += 1
            continue
        four = operators[at:at + 4]
        assert [kind(o) for o in four] == [ops_of.PACK, ops_of.RESHAPE, ops_of.PACK, ops_of.RESHAPE], "an enlargement that is not the usual one"
        source, target = int(four[0].inputs[0]), int(four[3].outputs[0])
        height, width = (int(v) for v in graph.tensors[target].shape[1:3])
        assert [height, width] == [2 * int(v) for v in graph.tensors[source].shape[1:3]]
        data = schema.BufferT()
        data.data = np.frombuffer(struct.pack("<ii", height, width), dtype=np.uint8)
        model.buffers.append(data)
        size = schema.TensorT()
        size.shape = np.array([2], dtype=np.int32)
        size.type = schema.TensorType.INT32
        size.buffer = len(model.buffers) - 1
        size.name = b"resize_size_%d" % at
        graph.tensors.append(size)
        resize = schema.OperatorT()
        resize.opcodeIndex = resize_code
        resize.inputs = np.array([source, len(graph.tensors) - 1], dtype=np.int32)
        resize.outputs = np.array([target], dtype=np.int32)
        resize.builtinOptionsType = schema.BuiltinOptions.ResizeNearestNeighborOptions
        options = schema.ResizeNearestNeighborOptionsT()
        options.alignCorners = False
        options.halfPixelCenters = True       # for a two-fold enlargement the same as every pixel twice (and the one that ONNX has a path for)
        resize.builtinOptions = options
        new_operators.append(resize)
        at += 4

    last = new_operators[-1]
    assert kind(last) == ops_of.CUSTOM and model.operatorCodes[last.opcodeIndex].customCode == b"TFLite_Detection_PostProcess"
    options = flexbuffers.Loads(bytes(last.customOptions))
    for key, value in ENCOUNTER_OPTIONS.items():
        assert float(options[key]) == value, f"the post-processing of the model has {key} = {options[key]}, not {value}"
    assert abs(float(options["nms_iou_threshold"]) - ENCOUNTER_IOU) < 1e-6
    boxes, certainties, anchors = (int(v) for v in last.inputs)
    anchors = np.frombuffer(bytes(model.buffers[graph.tensors[anchors].buffer].data), dtype="<f4").reshape(-1, 4).copy()
    graph.operators = new_operators[:-1]
    graph.outputs = np.array([boxes, certainties], dtype=np.int32)
    builder = flatbuffers.Builder(1024)
    builder.Finish(model.Pack(builder), b"TFL3")
    return bytes(builder.Output()), anchors


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

    cut, anchors = cut_encounter(source / f"{ENCOUNTER}.tflite")
    assert anchors.shape == (51150, 4), anchors.shape
    (target / f"{ENCOUNTER}_anchors.f32").write_bytes(np.ascontiguousarray(anchors, dtype="<f4").tobytes())
    (target / f"{ENCOUNTER}_cut.tflite").write_bytes(cut)

    rng = np.random.default_rng(SEED)
    worst = 0.0
    jobs = [(name, source / f"{name}.tflite", shape) for name, shape in MODELS.items()]
    jobs.append((ENCOUNTER, target / f"{ENCOUNTER}_cut.tflite", ENCOUNTER_SHAPE))
    for name, tflite_path, shape in jobs:
        onnx_path = target / f"{name}.onnx"
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
