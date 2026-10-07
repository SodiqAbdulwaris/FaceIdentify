"""The API's OpenAPI document, the source of the frontend's generated types (M4 W5; TST-046).

The document is built from the real application (`create_backend_app`), so it cannot drift from
the routes; it is committed at `frontend/src/api/openapi.json` and a test fails when the committed
file is stale. `python -m backend.api.openapi` rewrites it (`npm run generate:api` does that, then
generates the TypeScript types). The settings here are placeholders: building the application
opens nothing, so no path is touched.
"""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from backend.api.host import (
    PROVISIONAL_INDEX_BATCH,
    PROVISIONAL_INDEX_PASSES,
    PROVISIONAL_INDEX_RETRY,
    PROVISIONAL_TRANSACTION_RETRY,
)
from backend.api.startup import LibrarySettings, create_backend_app

# Any canonical token will do: the document never contains it.
_PLACEHOLDER_TOKEN: Final = "A" * 43
OPENAPI_PATH: Final = Path("frontend/src/api/openapi.json")


def openapi_document() -> dict[str, Any]:
    app = create_backend_app(
        _PLACEHOLDER_TOKEN,
        LibrarySettings(
            library_root=Path("unused"),
            local_state_root=Path("unused"),
            clock=lambda: datetime.now(UTC),
            new_id=uuid.uuid4,
            retry=PROVISIONAL_INDEX_RETRY,
            transaction_retry=PROVISIONAL_TRANSACTION_RETRY,
            index_batch=PROVISIONAL_INDEX_BATCH,
            max_index_passes=PROVISIONAL_INDEX_PASSES,
        ),
    )
    document: dict[str, Any] = app.openapi()
    return document


def render(document: dict[str, Any]) -> str:
    """Stable text: sorted keys, two-space indent, one trailing newline (LF)."""
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(path: Path = OPENAPI_PATH) -> int:
    path.write_text(render(openapi_document()), encoding="utf-8", newline="\n")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
