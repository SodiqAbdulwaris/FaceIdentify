# Recognition 02 Models, ONNX and execution providers

## 1. What this is and why it exists

The "intelligence" in the product is two ready-made **neural networks**. This lesson explains what a
network is in one page, what the project does and does not do with it (it **never trains**), how a model
file is run (**ONNX Runtime**) and on what hardware (**execution providers**: CPU or an NVIDIA GPU via
**CUDA**), and a rule you will see everywhere: the worker never silently falls back from one to the other.

## 2. Where it lives

| Idea | Where |
|---|---|
| Loading and running a model file | `load_session` in `backend/ml/worker/onnx_session.py` |
| Which providers to try | `providers_from` in `backend/api/real.py`, from `FACEIDENTIFY_PROVIDERS` |
| Making the GPU build visible | `backend/ml/worker/gpu_path.py` (`FACEIDENTIFY_ORT_GPU_DIR`) |
| The chosen models | `docs/research/reference-model-selection.md` (the `buffalo_l` pack) |
| Model files, hashes, variants | the runtime package manifest; [packages and the catalog](../../03-backend/runtime-and-worker/04-packages-and-catalog.md) |

## 3. How it works

### A network in one page

A **neural network** is a very large function: numbers in (a picture's pixels), numbers out (a vector, or
box coordinates and scores). It has millions of adjustable **weights**. **Training** means showing it many
examples with known answers and nudging the weights so its answers improve. **Inference** means using the
finished, frozen network on new input. **FaceIdentify never trains**: it only runs ready-made models, so there
is no training code, no GPU training and no face dataset to label. (Training appears in the specs only as
future ideas.)

A **convolutional neural network (CNN)** is the standard design for images: a *kernel* (a small grid of
weights) slides across the picture, marking where a pattern appears; stacked layers learn patterns of
growing complexity. Both models used here are CNNs. A *Vision Transformer* (cuts the image into patches
and lets them attend to each other) is a newer family: [researched], not used.

### ONNX and ONNX Runtime

**ONNX** ("Open Neural Network Exchange") is a standard file format for a trained model, so one trained in
PyTorch can be run by other software. **ONNX Runtime** loads an `.onnx` file and executes it fast through an
**execution provider**, a back end for particular hardware:

| Provider | Runs on | Status here |
|---|---|---|
| `CPUExecutionProvider` | your processor | always available; the default |
| `CUDAExecutionProvider` | an NVIDIA graphics card, via CUDA and cuDNN | verified on the owner's RTX 4070 (2026-10-07) |
| `TensorrtExecutionProvider`, OpenVINO, DirectML | NVIDIA optimiser, Intel, any Windows GPU | [researched]; not used |

**CUDA** is NVIDIA's platform for general computation on its GPUs; **cuDNN** its library of neural-network
building blocks; **cuBLAS** fast matrix maths. They are separate proprietary downloads, which is why the GPU
runtime is installed into a machine-local folder (never committed) that the worker is told about with
`FACEIDENTIFY_ORT_GPU_DIR`. A GPU has thousands of small cores and is far faster than a CPU for the matrix
arithmetic of a network: on the owner's machine, steady state, detecting one image took about 0.03 s on CUDA
against 0.22 to 0.38 s on CPU, and embedding one face about 0.01 to 0.02 s against 0.25 to 0.64 s (the first
CUDA call takes about 5 s to start up, once per worker). CPU and CUDA vectors for the same face agreed to
cosine 0.99995 or better.

### The worker never silently falls back

Ask ONNX Runtime for CUDA when CUDA cannot start and it quietly uses the CPU. The worker refuses that
(`load_session`): it reads the file **once**, checks its SHA-256 against the recorded digest, creates the
session **from those same bytes** (so a file swapped after the check cannot run), requires the requested
provider to be available, and checks that the session really runs on it. Otherwise it raises an error with a
code (`RUNTIME_VARIANT_NOT_AVAILABLE`, `RUNTIME_INITIALIZATION_FAILED`, `COMPONENT_LOAD_FAILED`). Why? Because
*the backend* decides what a fallback is allowed to be, and it must **record which hardware actually produced
each result** (provenance). A silent change of hardware would make that record a lie.

## 4. Try it

**Works with no models for steps 1 and 2; step 3 needs the local models. Verified 2026-10-12 (steps 1 and
2).**

1. Ask ONNX Runtime what it can use on this machine:

   ```bash
   uv run python -c "import onnxruntime as ort; print(ort.__version__, ort.get_available_providers())"
   ```

   Expected on the writing machine: `1.30.0 ['AzureExecutionProvider', 'CPUExecutionProvider']`. Yours has
   `CPUExecutionProvider`; it lists CUDA only if a GPU build is active.
2. How the application reads your provider choice:

   ```python
   >>> from backend.api.real import providers_from
   >>> providers_from({})
   ('CPUExecutionProvider',)
   >>> providers_from({"FACEIDENTIFY_PROVIDERS": "CUDAExecutionProvider, CPUExecutionProvider"})
   ('CUDAExecutionProvider', 'CPUExecutionProvider')
   >>> providers_from({"FACEIDENTIFY_PROVIDERS": "CPU"})
   ValueError: FACEIDENTIFY_PROVIDERS must list distinct known providers, not 'CPU'
   ```

   A typo is an error, never silently "CPU".
3. *(Needs the local models; unverified here: the model files are not in the writing environment.)* With the
   `buffalo_l` package installed as the project's scripts describe, the smoke script runs both models for
   real and prints the provider that executed each stage:

   ```bash
   PYTHONPATH=. uv run python scripts/smoke_real_models.py --local-state-root local-models/state \
     --providers CPUExecutionProvider path/to/one.jpg path/to/two.jpg
   ```

   (The pictures are your own local files; `--local-state-root` is where the model package was installed;
   see `scripts/smoke_real_models.py` and [a real-model run](../../06-evaluation-and-operations/05-real-model-run.md).)
   The documented behaviour (read from the script): for each picture it prints a line such as
   `one.jpg: 1 face(s); detect 0.30s, embed 0.40s on CPUExecutionProvider; scores [0.9]`, then the cosine
   of every pair of faces; it asserts every vector is 512 numbers, finite and unit length, and that the
   provider that ran is the one you asked for (unless you pass `--allow-fallback`).

## 5. Change it

The safe change is to the *test* of the rule, not to the rule. Run the worker-handler tests, which use small
generated ONNX models (no real weights):

```bash
uv run pytest tests/integration/test_ml_perception_handlers.py tests/unit/test_gpu_path.py -q
```

Expected on Windows: pass. They prove the "exact provider, no silent fallback" behaviour. (On the Linux
sandbox some worker-process tests fail for platform reasons; read the failure before deciding it is yours.)
If you changed `load_session` to accept `session.get_providers()[0] != provider` silently, the test that
requests an unavailable accelerator would fail.

## 6. Break it on purpose

In `FACEIDENTIFY_PROVIDERS` ask for CUDA with only the CPU build installed. The real profile asks the worker
for `CUDAExecutionProvider`; the worker answers `RUNTIME_VARIANT_NOT_AVAILABLE`; the perception client then
tries the next provider in your list (the CPU) and records that a fallback happened and which variant ran.
Only an actual backend-approved fallback closes one execution segment and starts another (owner decision
2026-10-05). Verified by reading `perception_client.py` and `tests/integration/test_runtime_perception_client.py`
(a real worker process that skips a variant whose provider does not exist and runs the next).

## 7. Exercises

1. What is the difference between training and inference, and which does this project do?
2. Why does `load_session` create the session from the bytes it hashed instead of from the path?
3. What would be wrong with letting ONNX Runtime fall back to the CPU silently?
4. Name the environment variable that lists providers and the one that points at the GPU build.

**Answers**

1. Training adjusts weights from examples; inference runs a frozen model. Only inference.
2. So a file swapped between the check and the load cannot run (the digest verified is the digest executed).
3. The backend could no longer record truthfully which hardware produced a result, and a "fallback" must be
   a recorded decision, not an accident.
4. `FACEIDENTIFY_PROVIDERS` and `FACEIDENTIFY_ORT_GPU_DIR`.

## 8. Related files

- Previous: [01 Vectors and NumPy](01-vectors-and-numpy.md) · Next: [03 The face pipeline](03-the-face-pipeline.md)
- [`backend/ml/worker/onnx_session.py`](../../../../../backend/ml/worker/onnx_session.py), [`docs/research/reference-model-selection.md`](../../../../research/reference-model-selection.md)
- [Perception client and providers](../../03-backend/runtime-and-worker/03-perception-client-and-providers.md)
