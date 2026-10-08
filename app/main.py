import io
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models, service
from app.config import STORAGE_DIR
from app.database import Base, engine, get_db
from app.schemas import CertificateList, CertificateOut, JobCreate, JobOut

@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Bulk Certificate Generator", version="1.0.0", lifespan=lifespan)


# ---------- helpers ----------

def _get_job(db: Session, job_id: str) -> models.Job:
    job = db.get(models.Job, job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job


def _cert_out(cert: models.Certificate) -> CertificateOut:
    out = CertificateOut.model_validate(cert)
    if cert.status == models.SUCCESS:
        out.download_url = f"/jobs/{cert.job_id}/certificates/{cert.id}/download"
    return out


def _job_out(db: Session, job: models.Job) -> JobOut:
    failures = db.scalars(
        select(models.Certificate)
        .where(models.Certificate.job_id == job.id, models.Certificate.status == models.ERROR)
        .order_by(models.Certificate.position)
    ).all()
    return JobOut(
        id=job.id,
        event_name=job.event_name,
        issuer=job.issuer,
        issue_date=job.issue_date,
        status=job.status,
        created_at=job.created_at,
        completed_at=job.completed_at,
        counts=service.get_counts(db, job),
        download_all_url=f"/jobs/{job.id}/download",
        failures=[_cert_out(c) for c in failures],
    )


# ---------- endpoints ----------

@app.post("/jobs", response_model=JobOut, status_code=202)
def create_job(payload: JobCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Submit many recipients in one request. Returns immediately (202);
    generation continues in the background. Poll GET /jobs/{id}."""
    job = service.create_job(db, payload)
    if job.status == models.QUEUED:
        background_tasks.add_task(service.process_job, job.id)
    return _job_out(db, job)


@app.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)):
    """Status, progress counts, and the list of failed items with reasons."""
    return _job_out(db, _get_job(db, job_id))


@app.get("/jobs/{job_id}/certificates", response_model=CertificateList)
def list_certificates(
    job_id: str,
    status: str | None = Query(None, pattern="^(pending|success|failed)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Paginated list of certificates in a job, optionally filtered by status."""
    _get_job(db, job_id)
    q = select(models.Certificate).where(models.Certificate.job_id == job_id)
    if status:
        q = q.where(models.Certificate.status == status)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    items = db.scalars(q.order_by(models.Certificate.position).limit(limit).offset(offset)).all()
    return CertificateList(total=total, limit=limit, offset=offset, items=[_cert_out(c) for c in items])


@app.get("/jobs/{job_id}/certificates/{cert_id}/download")
def download_certificate(job_id: str, cert_id: str, db: Session = Depends(get_db)):
    cert = db.get(models.Certificate, cert_id)
    if cert is None or cert.job_id != job_id:
        raise HTTPException(404, "Certificate not found")
    if cert.status != models.SUCCESS or not cert.file_path or not Path(cert.file_path).exists():
        raise HTTPException(409, f"Certificate is not available (status: {cert.status})")
    return FileResponse(cert.file_path, media_type="application/pdf", filename=f"certificate_{cert.position + 1}.pdf")


@app.get("/jobs/{job_id}/download")
def download_all(job_id: str, db: Session = Depends(get_db)):
    """ZIP of every successfully generated certificate in the job."""
    job = _get_job(db, job_id)
    if job.status in (models.QUEUED, models.PROCESSING):
        raise HTTPException(409, "Job is still running")
    certs = db.scalars(
        select(models.Certificate)
        .where(models.Certificate.job_id == job_id, models.Certificate.status == models.SUCCESS)
        .order_by(models.Certificate.position)
    ).all()
    if not certs:
        raise HTTPException(404, "No certificates were generated for this job")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for c in certs:
            safe = "".join(ch if ch.isalnum() else "_" for ch in c.recipient_name)[:50]
            zf.write(c.file_path, arcname=f"{c.position + 1:04d}_{safe}.pdf")
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="certificates_{job_id}.zip"'},
    )
