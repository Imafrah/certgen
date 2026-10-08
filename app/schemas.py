from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.config import MAX_RECIPIENTS_PER_JOB


class JobCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    event_name: str = Field(min_length=1, max_length=200)
    issuer: str = Field(min_length=1, max_length=200)
    issue_date: date | None = None  # defaults to today
    # Items are validated individually later, so one bad recipient
    # does not reject the whole request.
    recipients: list[Any] = Field(min_length=1, max_length=MAX_RECIPIENTS_PER_JOB)


class CertificateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    position: int
    recipient_name: str | None
    recipient_email: str | None
    course: str | None
    status: str
    error: str | None
    download_url: str | None = None


class JobCounts(BaseModel):
    total: int
    pending: int
    success: int
    failed: int
    progress_percent: float


class JobOut(BaseModel):
    id: str
    event_name: str
    issuer: str
    issue_date: date
    status: str
    created_at: datetime
    completed_at: datetime | None
    counts: JobCounts
    download_all_url: str
    failures: list[CertificateOut] = []


class CertificateList(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[CertificateOut]
