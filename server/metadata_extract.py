"""
Shared Gemini extraction: send the PDF to the model, return fixed fields + additional_metadata.

Used by main.py (async jobs) and main2.py (sync single-file MVP).

Tradeoff vs local text extraction: simpler pipeline and works for scans; very large PDFs may
hit API size/context limits—then you would split the file or use the Files API.
"""
import json
from typing import Any

from google.genai import Client, types

FIXED_METADATA_KEYS: tuple[str, ...] = (
    "project_id",
    "project_name",
    "cost",
    "date",
    "client",
    "building_owner",
    "site_location",
)


def parse_gemini_json(raw: str) -> dict[str, Any]:
    """Parse model output; strip markdown code fences if present."""
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)


def normalize_extraction(parsed: dict[str, Any]) -> dict[str, Any]:
    """
    Turn one Gemini JSON object into a stable API payload: all fixed keys present,
    strings trimmed, additional_metadata only string values (numbers coerced).
    """
    out_fixed: dict[str, Any] = {}
    for key in FIXED_METADATA_KEYS:
        val = parsed.get(key)
        if val is None or (isinstance(val, str) and not val.strip()):
            out_fixed[key] = None
        elif isinstance(val, str):
            out_fixed[key] = val.strip()
        else:
            out_fixed[key] = val

    merged_extra: dict[str, str] = {}
    raw_extra = parsed.get("additional_metadata")
    if isinstance(raw_extra, dict):
        for k, v in raw_extra.items():
            if not isinstance(k, str) or not k.strip():
                continue
            if v is None:
                continue
            if isinstance(v, (int, float)):
                merged_extra[k.strip()] = str(v)
            elif isinstance(v, str) and v.strip():
                merged_extra[k.strip()] = v.strip()

    return {**out_fixed, "additional_metadata": merged_extra}


def extract_fields_from_pdf_bytes(pdf_bytes: bytes, client: Client, model: str) -> dict[str, Any]:
    """
    Attach the PDF, ask Gemini for JSON, return a normalized dict (fixed keys + additional_metadata).
    """
    fixed_lines = "\n".join(f"- {k.replace('_', ' ').title()}" for k in FIXED_METADATA_KEYS)
    fixed_json = ",\n".join(f'  "{k}": string | null' for k in FIXED_METADATA_KEYS)
    prompt = (
        "You are extracting project metadata from construction specification PDFs (often German).\n"
        "Use the exact JSON keys below (English). From German text, map e.g. Auftraggeber→client, "
        "Bauherr→building_owner, Leistungsort / Ort der Leistung→site_location.\n\n"
        "The PDF is attached. It may be mostly text, scanned, or mixed. "
        "Use everything you can infer (including visual text).\n\n"
        "Fill these fields when supported by the document:\n"
        f"{fixed_lines}\n\n"
        "- additional_metadata: an object whose keys are short snake_case labels in English "
        "and values are short strings. Put any other noteworthy facts here "
        "(e.g. contacts, norms, phases, partial services, tender IDs, deadlines not covered above). "
        "Omit keys you cannot support; use {} if nothing extra applies.\n\n"
        "Return ONLY valid JSON with exactly this shape:\n"
        "{\n"
        f"{fixed_json},\n"
        '  "additional_metadata": { "<key>": string, ... }\n'
        "}\n\n"
        "If a fixed field is not present in the document, set it to null.\n"
    )

    resp = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_text(text=prompt),
            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
        ],
    )
    raw = (getattr(resp, "text", None) or str(resp)).strip()
    parsed = parse_gemini_json(raw)
    return normalize_extraction(parsed)

