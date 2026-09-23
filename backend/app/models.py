"""Imports every feature's persistence models so `Base.metadata` is complete.

Import this module wherever the full schema is needed (test fixtures now, Alembic in M2).
"""

from backend.app.jobs import models as jobs
from backend.app.memory import models as memory
from backend.app.processing import models as processing
from backend.app.runtime import models as runtime
from backend.app.settings import models as settings
from backend.app.sources import models as sources
from backend.infrastructure.db.engine import Base

__all__ = ["Base", "jobs", "memory", "processing", "runtime", "settings", "sources"]
