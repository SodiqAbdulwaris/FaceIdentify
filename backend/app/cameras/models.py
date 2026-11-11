"""Camera persistence (M7 step 1; PERSISTENCE_IMPLEMENTATION.md section 4.3).

A configured camera is a `CAMERA` Source (it has no original artifact) plus one row here naming the
device on this computer. Nothing else about a camera is stored: an encounter is an `Occurrence` of
kind `TRACK` on the camera's Source (M7 plan C3), so there are no encounter, appearance or track
tables.
"""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.infrastructure.db.engine import Base


class CameraSourceMetadata(Base):
    """The device a `CAMERA` Source captures from. Its display name is the Source's."""

    __tablename__ = "camera_source_metadata"
    __table_args__ = (
        CheckConstraint("length(trim(device_name)) > 0", name="device_name_not_empty"),
        CheckConstraint(
            "device_path IS NULL OR length(trim(device_path)) > 0", name="device_path_not_empty"
        ),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True
    )
    # The name the capture system shows ("Integrated Camera"), and its stable device path (the
    # DirectShow alternative name) when it has one: names are not unique across drivers, paths are.
    device_name: Mapped[str] = mapped_column(String)
    device_path: Mapped[str | None] = mapped_column(String)
