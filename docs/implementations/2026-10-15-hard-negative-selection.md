# Hard-negative evaluation cohorts — Issue #177

This is an **opt-in challenge-cohort sampling mode**, not a replacement for the default stable-hash import and **not an unbiased estimate of population false-accept rate**.

## Inputs and workflow

1. Start with a separately authorised, **Git-ignored** copy of LFW/CelebA. Use the project's existing detector/embedding runtime to obtain *one genuine face vector per usable image*, and export a local UTF-8 JSON map of vectors, keyed by paths relative to the source folder. E.g.:

```json
{
  "model_digest": "actual sha256 of installed embedding weights",
  "vectors": {
    "George_Walker/George_Walker_0001.jpg": [0.12, -0.43, 0.78],
    "Some_Other_Person/Some_Other_Person_0001.jpg": [0.33, -0.23, 0.19]
  }
}
```

The vectors shown here are **illustrative, not real model output**. Vectors must have consistent dimensions. Input remains local and must be kept Git-ignored. The importer **does not compute embeddings** or fabricate vectors. If there is no prepared embedding map, do not use this mode.

2. Example selection, with 12 enrolled identities and 8 similarity-selected strangers:

```bash
uv run python evaluation/import_labelled_dataset.py lfw \
  --source evaluation/datasets/lfw-source \
  --out evaluation/datasets/lfw-hard-negatives \
  --selection hard-negatives --embeddings evaluation/datasets/local-vectors.json \
  --known-people 12 --people 20 --minimum 5 --maximum 12
```

3. The `PROVENANCE.json` includes chosen `known_names`, `unknown_names`, local embedding-map digest, model digest and per-selected-stranger maximum cosine similarities. Imported photographs and derived embeddings must not enter Git or a release.
4. Run `assisted_recognition_gate.py` with `--people 12 --unknown 8` and normal other required arguments. The gate honours explicit roles instead of re-partitioning by hash. It rejects role/count mismatches.
5. Run separate **random/baseline** and **held-out** evaluations. Do not tune a decision threshold on the same selected strangers used to claim unbiased performance. Report challenge-cohort false accepts/abstentions separately from random-cohort estimates.

## Limitations and follow-up verification

Vectors must be extracted with the same intended evaluation representation model and preprocessing contract and independently checked for correct human labels. A vector map from another model is not interchangeable merely because dimensions match. The minimum is defined by distinct source photographs, and identities without embeddings cannot be selected as hard-negative strangers. The importer selects a stable known cohort before similarity ranking, and ranks strangers by the *maximum* normalized cosine similarity to a known photograph. The selected cohort is deliberately biased toward confusing negatives.

**Before closing #177**, validate against a real local model-derived embedding map, run the gate end-to-end, compare to random sampling, and confirm no datasets or derived biometrics have been committed. This implementation includes pure algorithm/unit tests but cannot attest to local model-weight tests.
