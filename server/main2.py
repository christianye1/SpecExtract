import json
import os
from typing import Any

import fitz  # PyMuPDF
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from google.genai import Client

# Load env vars from server/.env if present.
load_dotenv()


def _read_pdf_text_from_bytes(pdf_bytes: bytes) -> str:
    """Extract text from an in-memory PDF."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    parts: list[str] = []
    for page in doc:
        parts.append(page.get_text() or "")
    return "\n".join(parts).strip()


def _chunk_text(text: str, max_chars: int = 6000) -> list[str]:
    """Split text into chunks so each Gemini call stays reasonably small."""
    if not text:
        return []
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]


def _extract_fields_from_chunk(text_chunk: str, client: Client, model: str) -> dict[str, Any]:
    """Ask Gemini for project fields in strict JSON."""
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

    resp = client.models.generate_content(model=model, contents=prompt)
    raw = (getattr(resp, "text", None) or str(resp)).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)


app = FastAPI(title="Mercura API (MVP)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ALLOW_ORIGIN", "http://localhost:5173")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/api/upload")
def upload_pdf(file: UploadFile = File(...)) -> dict[str, Any]:
    """
    MVP endpoint:
    - Accept exactly one PDF file
    - Extract project_id and project_name with Gemini
    - Return result directly
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="File must have a filename")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Missing GEMINI_API_KEY env var")
    model = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")

    pdf_bytes = file.file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    text = _read_pdf_text_from_bytes(pdf_bytes)
    chunks = _chunk_text(text)
    if not chunks:
        raise HTTPException(status_code=400, detail="No extractable text found in PDF")

    client = Client(api_key=api_key)
    extracted: list[dict[str, Any]] = []
    for chunk in chunks:
        extracted.append(_extract_fields_from_chunk(chunk, client=client, model=model))

    project_id = None
    project_name = None
    for item in extracted:
        if project_id is None and item.get("project_id"):
            project_id = item["project_id"]
        if project_name is None and item.get("project_name"):
            project_name = item["project_name"]
        if project_id is not None and project_name is not None:
            break

    return {
        "project_id": project_id,
        "project_name": project_name,
        "source_filename": file.filename,
    }
