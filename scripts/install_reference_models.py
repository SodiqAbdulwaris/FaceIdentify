"""Install the reference SCRFD and ArcFace models as a machine-local runtime package (issue 69).

    uv run python scripts/install_reference_models.py --models-dir local-models/buffalo_l \
        --detector det_10g.onnx --embedder w600k_r50.onnx --local-state-root <dir>

The weights are developer-supplied local files that are never committed. The package is built from
the files' measured size and hash and installed through the same store the application uses.
Registering it in a library's catalog (`register_package`) is not done here: the real host wiring
that does it on startup is a later M5 step (R2), so today the package is installed, not yet used.
"""

import argparse
import tempfile
import uuid
from pathlib import Path

from backend.app.runtime.package_store import RuntimePackageStore
from backend.app.runtime.reference_package import (
    Provenance,
    ReferenceModel,
    reference_manifest,
    write_reference_package,
)
from backend.infrastructure.storage.layout import StorageRoots

LICENSE = "InsightFace pretrained models: non-commercial research purposes only"
SOURCE = "https://github.com/deepinsight/insightface/releases/tag/v0.7"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models-dir", type=Path, required=True)
    parser.add_argument("--detector", required=True, help="the SCRFD ONNX file name")
    parser.add_argument("--embedder", required=True, help="the ArcFace ONNX file name")
    parser.add_argument("--local-state-root", type=Path, required=True)
    parser.add_argument("--key", default="insightface-buffalo-l")
    parser.add_argument("--version", default="1.0.0")
    parser.add_argument("--dimension", type=int, default=512)
    arguments = parser.parse_args()

    detector = ReferenceModel("scrfd-10g", arguments.models_dir / arguments.detector, "scrfd")
    embedder = ReferenceModel("arcface-r50", arguments.models_dir / arguments.embedder, "arcface")
    manifest = reference_manifest(
        arguments.key,
        arguments.version,
        detector,
        embedder,
        dimension=arguments.dimension,
        provenance=Provenance(LICENSE, SOURCE, redistributable=False),
    )
    roots = StorageRoots(Path(), arguments.local_state_root)
    with tempfile.TemporaryDirectory() as scratch:
        package = write_reference_package(
            manifest,
            {detector.file.name: detector.file, embedder.file.name: embedder.file},
            Path(scratch),
        )
        installed = RuntimePackageStore(roots, new_id=uuid.uuid4).install(package, facts={})
    print(f"installed {installed.key} {installed.version} at {installed.path}")


if __name__ == "__main__":
    main()
