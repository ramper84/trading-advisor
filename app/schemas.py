"""The request/response contract. Grows one model per capability as each
router lands (Phases 9-13); only the health check exists at Phase 1."""

from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"


class Citation(BaseModel):
    """One claim in the rationale, grounded to a real retrieved chunk.
    `chunk_id` is validated post-generation against the actual retrieved
    set (`s11-03`'s citation integrity check) — Phase 13, not here; this
    schema only shapes what the model must produce."""

    chunk_id: int
    claim: str = Field(description="A short paraphrase of the specific fact this citation supports.")


class AnalysisSynthesis(BaseModel):
    """Phase 12's Instructor-validated generation output (`s11-02`/`s11-03`).
    `confidence` here is the model's own self-reported estimate — Phase
    13's `analysis_guard.py` computes the real, code-derived confidence
    and quality_status separately; the two are never conflated."""

    stance: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    citations: list[Citation]
