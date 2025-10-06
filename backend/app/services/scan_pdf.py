# apps/backend/services/scan_pdf.py
from __future__ import annotations

import os
import re
import json
import logging
from typing import List, Dict, Any, Iterable

from supabase import create_client, Client
from pydantic import BaseModel, Field, ValidationError
import fitz  # PyMuPDF
from dotenv import load_dotenv

# --- Gemini SDK (same style as skill_extractor) ---
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

# Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY must be set for Gemini parsing")

genai.configure(api_key=GEMINI_API_KEY)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")
MODEL = genai.GenerativeModel(GEMINI_MODEL)

COURSES_TABLE = os.getenv("COURSES_TABLE", "courses")
UPSERT_ON = os.getenv("COURSES_UPSERT_COLUMN", "course_code")  # unique key

# Tunables
MIN_REASONABLE_ROWS = int(os.getenv("SCAN_MIN_ROWS", "6"))
CHUNK_SIZE = int(os.getenv("SCAN_CHUNK_SIZE", "4500"))
CHUNK_OVERLAP = int(os.getenv("SCAN_CHUNK_OVERLAP", "600"))

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
            # prefer the row with the longer description (more info)
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
        parts: List[str] = []
        for page in doc:
            text = page.get_text("text") or ""
            if text:
                parts.append(text)
        doc.close()
        joined = "\n".join(parts)
        # de-hyphenate line-break hyphenation and normalize spacing
        joined = re.sub(r"(\w+)-\n(\w+)", r"\1\2", joined)
        joined = re.sub(r"\n{2,}", "\n\n", joined)
        return joined.strip()
    except Exception as e:
        logger.error("❌ PyMuPDF extraction failed: %s", e)
        return ""

# ---------- 2️⃣ Gemini Parsing (SDK) ----------
_SYSTEM = (
    "You are a precise curriculum parser. Extract ONLY the courses under the "
    "'Major Courses' or 'Major Course Description' section. Ignore General Education, "
    "Minor, and Electives. Return valid JSON with this exact schema:\n"
    "{ \"rows\": [ { \"course_code\": str, \"course_title\": str, \"course_description\": str } ] }\n"
    "Rules:\n"
    "- Keep the exact course_code as written in the PDF (e.g., 'CompF', 'Prog1').\n"
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
    """
    Use the official Gemini SDK (same pattern as skill_extractor).
    Enforce JSON object; salvage the first {...} block if needed.
    """
    prompt = _USER_TEMPLATE.format(payload=prompt_text[:20000])
    resp = MODEL.generate_content(
        [
            {"role": "user", "parts": [{"text": _SYSTEM}]},
            {"role": "user", "parts": [{"text": prompt}]},
        ]
    )
    raw = (resp.text or "").strip()
    raw = _strip_code_fences(raw)

    # Expect a JSON object; try parse directly
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    # salvage the first {...} if model adds extra prose
    m = re.search(r"\{[\s\S]*\}", raw)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass

    raise RuntimeError(f"Gemini returned non-JSON or malformed JSON: {raw[:400]}")

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
    up = SB.table(COURSES_TABLE).upsert(payload, on_conflict=UPSERT_ON).execute()
    return up.data or []

# ---------- 4️⃣ Main Pipeline ----------
def scan_pdf_and_store(file_bytes: bytes) -> Dict[str, Any]:
    """
    Step 1: Extract all visible text with PyMuPDF.
    Step 2: Use Gemini (SDK) to locate 'Major Courses' and format structured JSON.
    Step 3: If recall is low, run chunked passes and merge.
    Step 4: Upsert into Supabase.
    """
    logger.info("🚀 Starting hybrid scan pipeline (PyMuPDF + Gemini SDK)…")

    # Step 1 — Extract text
    full_text = extract_full_text_pymupdf(file_bytes)
    if not full_text:
        raise RuntimeError("No text extracted from PDF.")

    # Step 2 — Ask Gemini to parse structured JSON
    rows: List[CourseRow] = []
    try:
        raw_obj = _call_gemini_json(full_text)
        rows = _parse_gemini_rows(raw_obj)
    except Exception as e:
        logger.warning("Gemini main parse failed: %s", e)

    # Step 3 — If too few rows, chunk + merge
    if len(rows) < MIN_REASONABLE_ROWS:
        logger.info("Low recall (%d); retrying with chunked text", len(rows))
        chunk_rows: List[CourseRow] = []
        for chunk in _sliding_windows(full_text, CHUNK_SIZE, CHUNK_OVERLAP):
            try:
                r = _call_gemini_json(chunk)
                chunk_rows = _merge_dedupe(chunk_rows, _parse_gemini_rows(r))
            except Exception as ce:
                logger.warning("Chunk parse failed: %s", ce)
        rows = _merge_dedupe(rows, chunk_rows)

    # Step 4 — Save results
    inserted = upsert_courses(rows) if rows else []
    logger.info("✅ Parsed %d rows and inserted %d", len(rows), len(inserted))

    return {
        "inserted": inserted,
        "parsed_rows": [r.model_dump() for r in rows],
        "raw_text_len": len(full_text),
    }
