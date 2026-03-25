"""
Minimal FastAPI app: upload one PDF, extract structured metadata via Gemini.

Flow: PDF bytes → one Gemini call with the PDF attached → normalized JSON.
"""
import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from google.genai import Client

from metadata_extract import extract_fields_from_pdf_bytes

load_dotenv()

app = FastAPI(title="SpecExtract API (MVP)")

_cors_origins = [
    o.strip()
    for o in os.getenv(
        "CORS_ALLOW_ORIGIN",
        "http://localhost:5173,http://localhost:5174",
    ).split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, bool]:
    """Liveness check for deploys and local debugging."""
    return {"ok": True}


@app.post("/api/upload")
def upload_pdf(file: UploadFile = File(...)) -> dict[str, Any]:
    """
    Accept one PDF, send it to Gemini for extraction, return normalized metadata and filename.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="File must have a filename")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Missing GEMINI_API_KEY env var")
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    pdf_bytes = file.file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    client = Client(api_key=api_key)
    result = extract_fields_from_pdf_bytes(pdf_bytes, client=client, model=model)
    result["source_filename"] = file.filename
    return result
