# The ideas behind recognition

You do not need advanced mathematics to follow this project. You need five ideas: a **vector**, a
**dot product**, a **neural network as a function**, a **threshold**, and the difference between
"usually right" and "safe to act on". These six lessons build them one at a time, each with
something to compute in this repository.

| # | Lesson | The idea |
|---|---|---|
| 01 | [Vectors and NumPy](01-vectors-and-numpy.md) | a list of numbers is a point; cosine similarity; arrays; an image is an array |
| 02 | [Models, ONNX and providers](02-models-onnx-and-providers.md) | a trained network is a file; ONNX Runtime runs it; CPU versus CUDA; why the worker never falls back silently |
| 03 | [The face pipeline](03-the-face-pipeline.md) | detect, align, embed, compare, with the real contracts and a runnable alignment |
| 04 | [Kinds of recognition](04-kinds-of-recognition.md) | verification, identification, closed-set versus open-set, templates |
| 05 | [Thresholds and errors](05-thresholds-and-errors.md) | false accepts, false rejects, the decision policy, how it was measured |
| 06 | [Nearest-neighbour search and the video vocabulary](06-nearest-neighbour-and-video-vocabulary.md) | why an index exists, and the words for what is not built yet |

Related: [the topic map](../topic-map/README.md) answers "what did the project do about X?" for every
topic on the old research checklist. Back to [01 Basics](../README.md).
