"""Per-run observability: one RunRecorder per request or per ingest run,
one StageRecord per named stage inside it — timing, cost, success/failure,
logged as structured JSON when each stage completes. Mirrors fantasy's
pipeline/RunRecorder shape (PLAYBOOK.md Phase 1). Not persisted to Postgres
in v1 — stdout/log aggregation is enough for a single-operator tool;
revisit only if cross-run analysis over recorded stages is ever needed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StageRecord:
    stage: str
    started_at: datetime
    finished_at: datetime | None = None
    success: bool | None = None
    cost_usd: float = 0.0
    error: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float | None:
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds() * 1000


class RunRecorder:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.stages: list[StageRecord] = []

    def stage(self, name: str, **extra: Any) -> "_StageContext":
        return _StageContext(self, name, extra)

    def total_cost_usd(self) -> float:
        return sum(s.cost_usd for s in self.stages)

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "total_cost_usd": self.total_cost_usd(),
            "stages": [
                {
                    "stage": s.stage,
                    "duration_ms": s.duration_ms,
                    "success": s.success,
                    "cost_usd": s.cost_usd,
                    "error": s.error,
                    **s.extra,
                }
                for s in self.stages
            ],
        }


class _StageContext:
    def __init__(self, recorder: RunRecorder, name: str, extra: dict[str, Any]):
        self._recorder = recorder
        self._record = StageRecord(stage=name, started_at=datetime.now(timezone.utc), extra=extra)

    def __enter__(self) -> StageRecord:
        return self._record

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._record.finished_at = datetime.now(timezone.utc)
        self._record.success = exc is None
        if exc is not None:
            self._record.error = str(exc)
        self._recorder.stages.append(self._record)
        logger.info(
            "stage complete",
            extra={
                "run_id": self._recorder.run_id,
                "stage": self._record.stage,
                "duration_ms": self._record.duration_ms,
                "success": self._record.success,
            },
        )
        return False  # never suppress the exception
