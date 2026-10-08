"""Business logic: create a job, then process it (generate the PDFs)."""
import logging
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import database, models
from app.certificate import render_certificate
from app.config import STORAGE_DIR
from app.schemas import JobCreate
from app.validation import validate_recipient

log = logging.getLogger(__name__)


def create_job(db: Session, payload: JobCreate) -> models.Job:
    """Persist the job and one row per recipient.

    Invalid recipients are stored immediately as 'failed' with the reason.
    Valid ones are 'pending' and picked up by process_job().
    """
    job = models.Job(
        event_name=payload.event_name,
        issuer=payload.issuer,
        issue_date=payload.issue_date or date.today(),
        total=len(payload.recipients),
    )
    for i, raw in enumerate(payload.recipients):
        clean, err = validate_recipient(raw)
        if err:
            raw_d = raw if isinstance(raw, dict) else {}
            name = raw_d.get("name")
            email = raw_d.get("email")
            cert = models.Certificate(
                position=i,
                recipient_name=name[:200] if isinstance(name, str) else None,
                recipient_email=email[:320] if isinstance(email, str) else None,
                status=models.ERROR,
                error=f"validation: {err}",
            )
        else:
            cert = models.Certificate(position=i, status=models.PENDING, **{
                "recipient_name": clean["name"],
                "recipient_email": clean["email"],
                "course": clean["course"],
            })
        job.certificates.append(cert)
    db.add(job)
    db.commit()

    if not any(c.status == models.PENDING for c in job.certificates):
        _finalize(db, job)  # nothing to generate
    return job


def process_job(job_id: str) -> None:
    """Generate all pending certificates of a job.

    Runs in a background task, so it opens its own DB session.
    A failure on one certificate is recorded and the loop continues.
    """
    db = database.SessionLocal()
    try:
        job = db.get(models.Job, job_id)
        if job is None:
            return
        job.status = models.PROCESSING
        db.commit()

        out_dir = STORAGE_DIR / job.id
        out_dir.mkdir(parents=True, exist_ok=True)

        pending = db.scalars(
            select(models.Certificate)
            .where(models.Certificate.job_id == job_id, models.Certificate.status == models.PENDING)
            .order_by(models.Certificate.position)
        ).all()

        for cert in pending:
            path = out_dir / f"{cert.id}.pdf"
            try:
                render_certificate(
                    path,
                    name=cert.recipient_name,
                    event_name=job.event_name,
                    issuer=job.issuer,
                    issue_date=job.issue_date,
                    course=cert.course,
                )
                cert.status = models.SUCCESS
                cert.file_path = str(path)
            except Exception as exc:  # noqa: BLE001 - isolate per-item failures
                log.exception("certificate %s failed", cert.id)
                path.unlink(missing_ok=True)
                cert.status = models.ERROR
                cert.error = f"generation: {type(exc).__name__}: {exc}"[:500]
            db.commit()  # commit per item so progress is visible while running

        _finalize(db, job)
    except Exception:  # unexpected: don't leave the job stuck in 'processing'
        log.exception("job %s crashed", job_id)
        db.rollback()
        job = db.get(models.Job, job_id)
        if job is not None:
            job.status = models.FAILED
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()


def _finalize(db: Session, job: models.Job) -> None:
    counts = get_counts(db, job)
    if counts["failed"] == 0:
        job.status = models.COMPLETED
    elif counts["success"] == 0:
        job.status = models.FAILED
    else:
        job.status = models.COMPLETED_WITH_ERRORS
    job.completed_at = datetime.now(timezone.utc)
    db.commit()


def get_counts(db: Session, job: models.Job) -> dict:
    rows = db.execute(
        select(models.Certificate.status, func.count())
        .where(models.Certificate.job_id == job.id)
        .group_by(models.Certificate.status)
    ).all()
    by_status = dict(rows)
    success = by_status.get(models.SUCCESS, 0)
    failed = by_status.get(models.ERROR, 0)
    pending = by_status.get(models.PENDING, 0)
    total = job.total
    return {
        "total": total,
        "pending": pending,
        "success": success,
        "failed": failed,
        "progress_percent": round(100 * (success + failed) / total, 1) if total else 100.0,
    }
