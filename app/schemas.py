"""The request/response contract. Grows one model per capability as each
router lands (Phases 9-13); only the health check exists at Phase 1."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str = "ok"
