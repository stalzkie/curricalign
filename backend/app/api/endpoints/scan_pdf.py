# apps/backend/services/scan_pdf.py
from __future__ import annotations

import os
import re
import json
import logging
from typing import List, Dict, Any, Iterable, Optional

from supabase import create_client, Client
from pydantic import BaseModel, Field, ValidationError
import fitz  # PyMuPDF
from dotenv import load_dotenv

# --- Gemini SDK (force public v1 API surface) ---
import google.generativeai as genai

# ---------- Logging ----------
logger = logging.getLogger(__name__)

# ---------- Env / Config ----------
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")

SB: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------- Gemini API (FORCE v1 endpoint) ----------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY must be set for Gemini parsing")

# 🚨 Clear any environment variables that might override the endpoint
for bad_var in [
    "GOOGLE_API_BASE_URL",
    "GEMINI_API_BASE_URL",
    "GEMINI_ENDPOINT",
    "GEMINI_VERSION",
]:
    if bad_var in os.environ:
        os.environ.pop(bad_var)

# 🔧 CRITICAL FIX: Monkey-patch the SDK to use v1 instead of v1beta
import google.ai.generativelanguage as glm

# Override the default service path in the client
original_service_path = glm.services.generative_service.GenerativeServiceClient.DEFAULT_ENDPOINT

# Replace v1beta with v1 in the endpoint
v1_endpoint = "generativelanguage.googleapis.com"
glm.services.generative_service.GenerativeServiceClient.DEFAULT_ENDPOINT = v1_endpoint

# Also patch any other references to v1beta
if hasattr(glm, 'GenerativeServiceClient'):
    glm.GenerativeServiceClient.DEFAULT_ENDPOINT = v1_endpoint

logger.info("🔧 Patched Gemini SDK to use v1 endpoint: %s", v1_endpoint)

# Configure the SDK
genai.configure(api_key=GEMINI_API_KEY)

# 🔧 Use the correct model name for v1 API
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")

# 🔧 Verify the model exists before creating it
try:
    available_models = [m.name for m in genai.list_models()]
    logger.info("Available Gemini models: %s", available_models)
    
    # The model name from list_models includes "models/" prefix
    full_model_name = f"models/{GEMINI_MODEL}"
    if full_model_name not in available_models:
        # Try without version suffix if the main model exists
        fallback_models = [
            "models/gemini-1.5-pro-latest",
            "models/gemini-1.5-pro-001",
            "models/gemini-pro",
            "models/gemini-1.5-flash",
        ]
        for fallback in fallback_models:
            if fallback in available_models:
                GEMINI_MODEL = fallback.replace("models/", "")
                logger.warning("Model not found, using fallback: %s", GEMINI_MODEL)
                break
        else:
            logger.error("Specified model %s not available. Available models: %s", 
                        GEMINI_MODEL, available_models)
except Exception as e:
    logger.warning("Could not verify model availability: %s", e)

MODEL = genai.GenerativeModel(GEMINI_MODEL)
logger.info("✅ Initialized Gemini model: %s", GEMINI_MODEL)

# ---------- Tunables ----------
COURSES_TABLE = os.getenv("COURSES_TABLE", "courses")
UPSERT_ON = os.getenv("COURSES_UPSERT_COLUMN", "course_code")
MIN_REASONABLE_ROWS = int(os.getenv("SCAN_MIN_ROWS", "6"))
CHUNK_SIZE = int(os.getenv("SCAN_CHUNK_SIZE", "4500"))
CHUNK_OVERLAP = int(os.getenv("SCAN_CHUNK_OVERLAP", "600"))
FAIL_ON_EMPTY = os.getenv("SCAN_FAIL_ON_EMPTY", "1") not in ("0", "false", "False", "")

# ---------- Models ----------
class CourseRow(BaseModel):
    course_code: str = Field(..., min_length=1)
    course_title: str = Field(..., min_length=1)
    course_description: str = Field(..., min_length=1)

# ---------- Text helpers ----------
def _norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _canonical_code(code: str) -> str:
    return re.sub(r"\s+", "", (code or "").upper())

def _merge_dedupe(primary: List[CourseRow], secondary: List[CourseRow]) -> List[CourseRow]:
    by_code: Dict[str, CourseRow] = {_canonical_code(r.course_code): r for r in primary}
    for r in secondary:
        key = _canonical_code(r.course_code)
        if key not in by_code:
            by_code[key] = r
        else:
            a = by_code[key]
            if len(r.course_description or "") > len(a.course_description or ""):
                by_code[key] = r
    return list(by_code.values())

def _sliding_windows(txt: str, size: int, overlap: int) -> Iterable[str]:
    n = len(txt)
    i = 0
    while i < n:
        yield txt[i : min(i + size, n)]
        if i + size >= n:
            break
        i = max(i + size - overlap, i + 1)

# ---------- 1️⃣ PyMuPDF Extraction ----------
def extract_full_text_pymupdf(file_bytes: bytes) -> str:
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        parts: List[str] = [page.get_text("text") or "" for page in doc]
        doc.close()
        joined = "\n".join(parts)
        joined = re.sub(r"(\w+)-\n(\w+)", r"\1\2", joined)
        joined = re.sub(r"[ \t]+\n", "\n", joined)
        joined = re.sub(r"\n{2,}", "\n\n", joined)
        return joined.strip()
    except Exception as e:
        logger.error("❌ PyMuPDF extraction failed: %s", e)
        return ""

# ---------- 2️⃣ Gemini Parsing ----------
_SYSTEM = (
    "You are a precise curriculum parser. Extract ONLY the courses under the "
    "'Major Courses' or 'Major Course Description' section. Ignore General Education, "
    "Minor, and Electives. Return valid JSON with this exact schema:\n"
    "{ \"rows\": [ { \"course_code\": str, \"course_title\": str, \"course_description\": str } ] }\n"
    "Rules:\n"
    "- Keep the exact course_code as written in the PDF.\n"
    "- Uppercase the course_title.\n"
    "- Merge multiline descriptions into one paragraph.\n"
    "- Do not invent items. If no major courses are present, return {\"rows\": []}."
)

_USER_TEMPLATE = """PDF text:

{payload}

Return ONLY the JSON object (no backticks, no commentary).
"""

def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()

def _call_gemini_json(prompt_text: str) -> Dict[str, Any]:
    prompt = _USER_TEMPLATE.format(payload=prompt_text[:20000])
    try:
        response = MODEL.generate_content(
            [{"text": _SYSTEM + "\n\n" + prompt}],
            generation_config={
                "temperature": 0.2,
                "max_output_tokens": 4096,
            },
        )
        raw = (response.text or "").strip()
    except Exception as e:
        raise RuntimeError(f"Gemini call failed: {e}")

    if not raw:
        raise RuntimeError("Gemini returned empty response.")
    raw = _strip_code_fences(raw)

    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        try:
            obj = json.loads(match.group(0))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

    raise RuntimeError(f"Gemini returned malformed JSON: {raw[:400]}")

def _parse_gemini_rows(raw_obj: Dict[str, Any]) -> List[CourseRow]:
    cleaned: List[CourseRow] = []
    for row in (raw_obj.get("rows") or []):
        code = _norm_space(str(row.get("course_code", ""))) or "UNKNOWN_CODE"
        title = _norm_space(str(row.get("course_title", ""))) or "UNTITLED COURSE"
        desc = _norm_space(str(row.get("course_description", ""))) or "No description provided."
        try:
            cleaned.append(CourseRow(course_code=code, course_title=title, course_description=desc))
        except ValidationError as e:
            logger.warning("Skipping invalid row: %s | %s", e, row)
    return cleaned

# ---------- 3️⃣ Supabase Upsert ----------
def upsert_courses(rows: List[CourseRow]) -> List[Dict[str, Any]]:
    if not rows:
        return []
    payload = [r.model_dump() for r in rows]
    try:
        up = SB.table(COURSES_TABLE).upsert(payload, on_conflict=UPSERT_ON).execute()
        return up.data or []
    except Exception as e:
        logger.error("❌ Supabase upsert failed: %s", e)
        return []

# ---------- 4️⃣ Main Pipeline ----------
def scan_pdf_and_store(file_bytes: bytes) -> Dict[str, Any]:
    logger.info("🚀 Starting hybrid scan pipeline (PyMuPDF + Gemini v1 SDK)… [model=%s]", GEMINI_MODEL)

    # Step 1 — Extract text
    full_text = extract_full_text_pymupdf(file_bytes)
    if not full_text:
        raise RuntimeError("No text extracted from PDF.")

    # Step 2 — Parse with Gemini
    rows: List[CourseRow] = []
    last_err: Optional[str] = None
    try:
        raw_obj = _call_gemini_json(full_text)
        rows = _parse_gemini_rows(raw_obj)
    except Exception as e:
        last_err = str(e)
        logger.warning("Gemini main parse failed: %s", last_err)

    # Step 3 — Retry with chunks if recall is low
    if len(rows) < MIN_REASONABLE_ROWS:
        logger.info("Low recall (%d); retrying with chunked text", len(rows))
        chunk_rows: List[CourseRow] = []
        for chunk in _sliding_windows(full_text, CHUNK_SIZE, CHUNK_OVERLAP):
            try:
                r = _call_gemini_json(chunk)
                chunk_rows = _merge_dedupe(chunk_rows, _parse_gemini_rows(r))
            except Exception as ce:
                last_err = str(ce)
                if "not found" in last_err or "404" in last_err:
                    logger.warning("Chunk parse aborted due to model error: %s", last_err)
                    break
                logger.warning("Chunk parse failed: %s", last_err)
        rows = _merge_dedupe(rows, chunk_rows)

    # Step 4 — Optional fail if still empty
    if FAIL_ON_EMPTY and len(rows) == 0:
        raise RuntimeError(
            f"Gemini parse produced 0 rows. "
            f"{'Last error: ' + last_err if last_err else 'No additional error details.'}"
        )

    # Step 5 — Save to Supabase
    inserted = upsert_courses(rows) if rows else []
    logger.info("✅ Parsed %d rows and inserted %d", len(rows), len(inserted))

    return {
        "inserted": inserted,
        "parsed_rows": [r.model_dump() for r in rows],
        "raw_text_len": len(full_text),
    }