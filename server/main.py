import os
import threading
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

# ---- External services / libraries ----
# Gemini SDK (installed via `google-genai`)
from google.genai import Client

from dotenv import load_dotenv

from metadata_extract import extract_fields_from_pdf_bytes

# Load environment variables from `server/.env` (if present).
# This allows secrets/configuration (API keys, data dir) to be set without hardcoding.
load_dotenv()


class JobStatus(str, Enum):
    # Using an Enum gives us a closed set of valid states for a job.
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


# ---- Local file storage paths ----
# We store uploaded PDFs under a configurable data directory.
DATA_DIR = Path(os.getenv("MERCURA_DATA_DIR", "data")).resolve()
# Folder where raw uploaded PDFs are saved.
UPLOADS_DIR = DATA_DIR / "uploads"
# Ensure the directory exists so later file writes won't crash.
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class JobRecord:
    # A lightweight "job" model stored in memory.
    # The frontend polls /api/jobs/{job_id} for this job's status/progress/result.
    job_id: str
    status: JobStatus
    progress: float = 0.0
    created_at: float = time.time()
    updated_at: float = time.time()
    filename: str = ""
    error: Optional[str] = None
    result: Optional[dict[str, Any]] = None

    def touch(self) -> None:
        # Update the 'updated_at' timestamp whenever the job state changes.
        self.updated_at = time.time()


# In-memory job store: job_id -> JobRecord
# Note: this is NOT persisted to disk/DB, so jobs are lost on server restart.
JOBS: dict[str, JobRecord] = {}
# A lock to avoid race conditions while background tasks update JOBS.
JOBS_LOCK = threading.Lock()


def _get_job(job_id: str) -> JobRecord:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job


def _set_job(job_id: str, **fields: Any) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        for k, v in fields.items():
            # Update only the passed-in fields (status/progress/result/error, etc.)
            setattr(job, k, v)
        # Any update bumps updated_at so callers can reason about "freshness".
        job.touch()


def _process_job(job_id: str, file_path: Path, filename: str) -> None:
    # This function runs in the "background" after /api/upload returns.
    # It updates the job record as it goes so the frontend can display progress.
    try:
        # Mark the job as running and set an initial progress value.
        _set_job(job_id, status=JobStatus.processing, progress=0.05, error=None, result=None)

        # Read Gemini configuration from environment variables.
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("Missing GEMINI_API_KEY env var")
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

        client = Client(api_key=api_key)

        _set_job(job_id, progress=0.2)
        pdf_bytes = file_path.read_bytes()
        _set_job(job_id, progress=0.35)

        result = extract_fields_from_pdf_bytes(pdf_bytes, client=client, model=model)
        _set_job(job_id, progress=0.95)

        result["source_filename"] = filename

        # All done: mark completion and store the final structured result.
        _set_job(job_id, status=JobStatus.completed, progress=1.0, result=result)

    except Exception as e:
        # Any exception means the job failed; we capture the error message for the UI.
        _set_job(job_id, status=JobStatus.failed, progress=1.0, error=str(e))


app = FastAPI(title="SpecExtract API")

_cors_origins = [
    o.strip()
    for o in os.getenv(
        "CORS_ALLOW_ORIGIN",
        "http://localhost:5173,http://localhost:5174",
    ).split(",")
    if o.strip()
]

app.add_middleware(
    # CORS allows a separate frontend dev server (different origin) to call our API.
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, Any]:
    # Simple endpoint to verify the server is up.
    return {"ok": True}


@app.post("/api/upload")
def upload_pdfs(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
) -> dict[str, Any]:
    # Accept one or more uploaded PDFs.
    # We return job_ids immediately (so the request doesn't wait for Gemini processing).
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    job_ids: list[str] = []

    for upload in files:
        # Create a unique id per uploaded file so the frontend can poll progress per PDF.
        job_id = str(uuid.uuid4())
        job_ids.append(job_id)

        with JOBS_LOCK:
            # Create a JobRecord in memory and mark it as queued.
            JOBS[job_id] = JobRecord(job_id=job_id, status=JobStatus.queued, filename=upload.filename or "")

        suffix = Path(upload.filename or "").suffix or ".pdf"
        # Save the raw upload to disk so the background task can safely read it.
        dest_path = UPLOADS_DIR / f"{job_id}{suffix}"

        # Save upload to disk so the background worker can read it safely.
        # UploadFile.read() can be large; if you hit memory pressure, switch to streaming writes.
        data = upload.file.read()
        dest_path.write_bytes(data)

        # Start background processing after we return the response.
        background_tasks.add_task(_process_job, job_id, dest_path, upload.filename or "")

    # Client receives job ids immediately and can poll /api/jobs/{job_id}.
    return {"job_ids": job_ids}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    # Frontend polling endpoint: returns the latest snapshot of job state.
    job = _get_job(job_id)
    return {
        "job_id": job.job_id,
        "status": job.status.value,
        "progress": job.progress,
        "result": job.result,
        "error": job.error,
    }

