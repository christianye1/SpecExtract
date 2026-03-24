import json
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

import fitz  # PyMuPDF (PDF parsing)

from dotenv import load_dotenv

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


def _read_pdf_text(file_path: Path) -> str:
    # Extract text from a PDF using PyMuPDF.
    # We do it page-by-page so we can support large documents.
    # Extract text page-by-page to support large files.
    # For complex PDFs, extraction quality can vary; Gemini can still often infer fields from partial text.
    doc = fitz.open(str(file_path))
    chunks: list[str] = []
    for page in doc:
        chunks.append(page.get_text() or "")
    return "\n".join(chunks)


def _chunk_text(text: str, max_chars: int = 6000) -> list[str]:
    # Chunking exists to keep prompts within model limits.
    # Instead of tokenizing (harder), we approximate using character windows.
    # Simple chunking: split into contiguous character windows.
    # This avoids implementing tokenization up-front.
    text = text.strip()
    if not text:
        return []
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]


def _gemini_extract_project_fields(text_chunk: str, client: Client, model: str) -> dict[str, Any]:
    # Ask Gemini to extract just two fields from a chunk of PDF text.
    # We instruct the model to output a strict JSON object with the exact keys we need.
    # Ask Gemini to return strict JSON with the only fields we care about.
    prompt = (
        "You are extracting project metadata from construction specification PDFs.\n\n"
        "Given the following extracted text chunk, identify:\n"
        "- Project ID\n"
        "- Project Name\n\n"
        "Return ONLY valid JSON with exactly this shape:\n"
        "{\n"
        '  "project_id": string | null,\n'
        '  "project_name": string | null\n'
        "}\n\n"
        "If a field is not present in this chunk, set it to null.\n\n"
        f"TEXT CHUNK:\n{text_chunk}\n"
    )

    resp = client.models.generate_content(
        model=model,
        contents=prompt,
    )

    # The SDK returns a response object; its text is typically accessible via `resp.text`.
    # We keep parsing defensive because Gemini occasionally returns extra whitespace.
    raw = getattr(resp, "text", None) or str(resp)
    raw = raw.strip()
    try:
        # Most of the time Gemini returns exactly the JSON we requested.
        return json.loads(raw)
    except json.JSONDecodeError:
        # Sometimes Gemini may wrap JSON in code fences (```json ... ```).
        # We strip those and retry parsing.
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)


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
        model = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")

        # Create a Gemini client for this job.
        client = Client(api_key=api_key)

        # 1) Extract full text
        text = _read_pdf_text(file_path)
        # Text extraction is done; update progress to indicate the next phase.
        _set_job(job_id, progress=0.35)

        # 2) Chunk + extract per chunk
        chunks = _chunk_text(text)
        if not chunks:
            raise RuntimeError("No text could be extracted from PDF")

        extracted: list[dict[str, Any]] = []
        # Distribute remaining progress across chunk requests (roughly).
        per_chunk_weight = 0.6 / max(len(chunks), 1)
        progress = 0.35
        for i, chunk in enumerate(chunks, start=1):
            # Call Gemini for each chunk. Each call should return JSON for project_id/name.
            data = _gemini_extract_project_fields(chunk, client=client, model=model)
            extracted.append(data)
            progress += per_chunk_weight
            # Cap at < 1.0 so the "finalize" step can bring it to 100%.
            _set_job(job_id, progress=min(progress, 0.95))

        # 3) Merge: take first non-null for each field
        # We may extract partial info from different chunks. This merge tries to pick
        # the first non-null occurrence for each field as a simple heuristic.
        project_id = None
        project_name = None
        for item in extracted:
            if project_id is None and item.get("project_id"):
                project_id = item["project_id"]
            if project_name is None and item.get("project_name"):
                project_name = item["project_name"]
            if project_id is not None and project_name is not None:
                break

        result = {
            "project_id": project_id,
            "project_name": project_name,
            "source_filename": filename,
        }

        # All done: mark completion and store the final structured result.
        _set_job(job_id, status=JobStatus.completed, progress=1.0, result=result)

    except Exception as e:
        # Any exception means the job failed; we capture the error message for the UI.
        _set_job(job_id, status=JobStatus.failed, progress=1.0, error=str(e))


app = FastAPI(title="Mercura API")

app.add_middleware(
    # CORS allows a separate frontend dev server (different origin) to call our API.
    CORSMiddleware,
    # For local dev, default to Vite's default port.
    allow_origins=[os.getenv("CORS_ALLOW_ORIGIN", "http://localhost:5173")],
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

