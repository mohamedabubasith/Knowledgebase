from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.schemas.common import Identified


class JobLogRead(Identified):
    job_id: str
    job_type: str
    document_id: UUID
    document_name: str | None = None
    knowledge_base_name: str | None = None
    status: str
    attempt: int
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    error_message: str | None
    metadata: dict = Field(validation_alias="metadata_")
    stage_timings: dict
    attempt_history: list
