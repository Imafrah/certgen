import io
import zipfile

import pytest

from app import models, service
from app.certificate import render_certificate
from app.database import SessionLocal
from app.schemas import JobCreate
from app.validation import validate_recipient
from tests.conftest import make_payload


# ---------- creating a job ----------

def test_create_job_returns_202_and_finishes(client):
    r = client.post("/jobs", json=make_payload())
    assert r.status_code == 202
    body = r.json()
    assert body["id"]
    assert body["counts"]["total"] == 2

    job = client.get(f"/jobs/{body['id']}").json()
    assert job["status"] == "completed"
    assert job["counts"]["success"] == 2
    assert job["counts"]["failed"] == 0


def test_issue_date_defaults_to_today(client):
    payload = make_payload()
    del payload["issue_date"]
    r = client.post("/jobs", json=payload)
    assert r.status_code == 202
    assert r.json()["issue_date"]


# ---------- input validation ----------

@pytest.mark.parametrize(
    "payload",
    [
        make_payload(recipients=[]),                      # empty list
        make_payload(recipients="not a list"),            # wrong type
        make_payload(event_name=""),                      # missing event name
        {"event_name": "x", "issuer": "y"},               # recipients missing
    ],
)
def test_invalid_request_rejected(client, payload):
    assert client.post("/jobs", json=payload).status_code == 422


def test_too_many_recipients_rejected(client):
    many = [{"name": f"P{i}", "email": f"p{i}@example.com"} for i in range(1001)]
    assert client.post("/jobs", json=make_payload(recipients=many)).status_code == 422


def test_invalid_recipient_fails_only_that_item(client):
    recipients = [
        {"name": "Good One", "email": "good@example.com"},
        {"name": "", "email": "bad"},                     # both invalid
        {"email": "noname@example.com"},                  # no name
        "just a string",                                  # not an object
        {"name": "Also Good", "email": "ok@example.com"},
    ]
    r = client.post("/jobs", json=make_payload(recipients=recipients))
    assert r.status_code == 202
    job = client.get(f"/jobs/{r.json()['id']}").json()

    assert job["status"] == "completed_with_errors"
    assert job["counts"] == {**job["counts"], "total": 5, "success": 2, "failed": 3}
    assert sorted(f["position"] for f in job["failures"]) == [1, 2, 3]
    assert all(f["error"].startswith("validation:") for f in job["failures"])


def test_all_invalid_job_is_failed(client):
    r = client.post("/jobs", json=make_payload(recipients=[{"name": "x"}, {}]))
    job = client.get(f"/jobs/{r.json()['id']}").json()
    assert job["status"] == "failed"
    assert job["counts"]["progress_percent"] == 100.0


def test_validate_recipient_cleans_input():
    clean, err = validate_recipient({"name": "  Asha   Rao ", "email": " ASHA@Example.com ", "course": " "})
    assert err is None
    assert clean == {"name": "Asha Rao", "email": "asha@example.com", "course": None}


# ---------- certificate generation ----------

def test_render_certificate_writes_pdf(tmp_path):
    from datetime import date
    out = tmp_path / "c.pdf"
    render_certificate(out, name="Asha Rao", event_name="Event", issuer="Org",
                       issue_date=date(2026, 10, 1), course="Course")
    assert out.read_bytes().startswith(b"%PDF")


def test_very_long_name_still_renders(tmp_path):
    from datetime import date
    out = tmp_path / "c.pdf"
    render_certificate(out, name="A" * 100, event_name="E" * 150, issuer="Org",
                       issue_date=date(2026, 10, 1))
    assert out.stat().st_size > 0


# ---------- status / progress ----------

def test_progress_before_and_after_processing():
    """Create without processing -> queued/0%; then process -> completed/100%."""
    db = SessionLocal()
    payload = JobCreate(**make_payload())
    job = service.create_job(db, payload)
    assert job.status == models.QUEUED
    counts = service.get_counts(db, job)
    assert counts["pending"] == 2 and counts["progress_percent"] == 0.0

    service.process_job(job.id)
    db.refresh(job)
    counts = service.get_counts(db, job)
    assert job.status == models.COMPLETED
    assert counts["success"] == 2 and counts["progress_percent"] == 100.0
    assert job.completed_at is not None
    db.close()


def test_unknown_job_404(client):
    assert client.get("/jobs/doesnotexist").status_code == 404


# ---------- individual failure handling ----------

def test_one_certificate_failure_does_not_stop_others(client, monkeypatch):
    real = service.render_certificate

    def flaky(path, **kw):
        if kw["name"] == "Boom":
            raise RuntimeError("render exploded")
        return real(path, **kw)

    monkeypatch.setattr(service, "render_certificate", flaky)

    recipients = [
        {"name": "First", "email": "a@example.com"},
        {"name": "Boom", "email": "b@example.com"},
        {"name": "Third", "email": "c@example.com"},
    ]
    r = client.post("/jobs", json=make_payload(recipients=recipients))
    job = client.get(f"/jobs/{r.json()['id']}").json()

    assert job["status"] == "completed_with_errors"
    assert job["counts"]["success"] == 2
    assert job["counts"]["failed"] == 1
    failure = job["failures"][0]
    assert failure["recipient_name"] == "Boom"
    assert "render exploded" in failure["error"]
    assert failure["download_url"] is None


# ---------- retrieving certificates ----------

def test_list_filter_and_download_single(client):
    recipients = [
        {"name": "Asha Rao", "email": "asha@example.com"},
        {"name": "", "email": "bad"},
    ]
    job_id = client.post("/jobs", json=make_payload(recipients=recipients)).json()["id"]

    ok = client.get(f"/jobs/{job_id}/certificates", params={"status": "success"}).json()
    assert ok["total"] == 1
    item = ok["items"][0]

    pdf = client.get(item["download_url"])
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")

    failed = client.get(f"/jobs/{job_id}/certificates", params={"status": "failed"}).json()
    assert failed["total"] == 1
    bad_id = failed["items"][0]["id"]
    assert client.get(f"/jobs/{job_id}/certificates/{bad_id}/download").status_code == 409


def test_pagination(client):
    many = [{"name": f"P{i}", "email": f"p{i}@example.com"} for i in range(5)]
    job_id = client.post("/jobs", json=make_payload(recipients=many)).json()["id"]
    page = client.get(f"/jobs/{job_id}/certificates", params={"limit": 2, "offset": 2}).json()
    assert page["total"] == 5
    assert [i["position"] for i in page["items"]] == [2, 3]


def test_bad_status_filter_rejected(client):
    job_id = client.post("/jobs", json=make_payload()).json()["id"]
    assert client.get(f"/jobs/{job_id}/certificates", params={"status": "nope"}).status_code == 422


def test_download_zip(client):
    recipients = [
        {"name": "Asha Rao", "email": "asha@example.com"},
        {"name": "Ben Carter", "email": "ben@example.com"},
        {"name": "", "email": "bad"},
    ]
    job_id = client.post("/jobs", json=make_payload(recipients=recipients)).json()["id"]
    r = client.get(f"/jobs/{job_id}/download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert len(zf.namelist()) == 2  # failed item excluded
        assert all(zf.read(n).startswith(b"%PDF") for n in zf.namelist())


def test_zip_404_when_nothing_generated(client):
    job_id = client.post("/jobs", json=make_payload(recipients=[{}])).json()["id"]
    assert client.get(f"/jobs/{job_id}/download").status_code == 404


def test_certificate_must_belong_to_job(client):
    j1 = client.post("/jobs", json=make_payload()).json()["id"]
    j2 = client.post("/jobs", json=make_payload()).json()["id"]
    cert = client.get(f"/jobs/{j1}/certificates").json()["items"][0]
    assert client.get(f"/jobs/{j2}/certificates/{cert['id']}/download").status_code == 404
