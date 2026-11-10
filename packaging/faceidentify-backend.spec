# PyInstaller spec of the backend (M8 step 2, decision R3: onedir). Build from the repository root:
#   uv run --group build pyinstaller packaging/faceidentify-backend.spec --noconfirm \
#       --distpath build/dist --workpath build/work
# The weights are never bundled: they are installed by the user (decision R6).
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # SPECPATH is this file's folder


def backend_modules():
    """Every module under backend/ except the migration scripts (those are data, see below)."""
    for path in sorted(Path(ROOT, "backend").rglob("*.py")):
        relative = path.relative_to(ROOT).with_suffix("")
        if relative.parts[:2] != ("backend", "alembic"):
            yield ".".join(relative.parts[:-1] if relative.name == "__init__" else relative.parts)


hiddenimports = (
    list(backend_modules())  # the worker factory, the use cases and what the migrations import
    + collect_submodules("alembic", filter=lambda name: "testing" not in name)  # the SQLite dialect and the runtime are loaded by name
    + collect_submodules("uvicorn")
    + collect_submodules("websockets")
    + collect_submodules("sqlalchemy.dialects.sqlite")
)
binaries = collect_dynamic_libs("onnxruntime") + collect_dynamic_libs("usearch") + collect_dynamic_libs("PIL")
datas = (
    # Alembic reads the migration scripts as files: lifecycle.py looks for them at backend/alembic.
    [(os.path.join(ROOT, "backend", "alembic"), "backend/alembic")]
    + collect_data_files("alembic")
    + collect_data_files("onnxruntime")
)

a = Analysis(
    [os.path.join(SPECPATH, "frozen_entry.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["setuptools", "pkg_resources", "tkinter", "pytest", "hypothesis", "onnx", "mypy", "ruff"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="faceidentify-backend", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="faceidentify-backend")
