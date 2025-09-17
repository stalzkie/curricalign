# apps/backend/services/scan_pdf.py
from __future__ import annotations

import os
import io
import re
import json
import logging
from typing import List, Dict, Any

from supabase import create_client, Client
from pydantic import BaseModel, Field, ValidationError

from PyPDF2 import PdfReader
import requests

# ---------- Logging ----------
logger = logging.getLogger(__name__)

# ---------- Config ----------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")

SB: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

LLM_PROVIDER = (os.getenv("LLM_PROVIDER") or "gemini").lower()  # gemini | openai
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")

COURSES_TABLE = os.getenv("COURSES_TABLE", "courses")
UPSERT_ON = os.getenv("COURSES_UPSERT_COLUMN", "course_code")  # unique key


# ---------- Models ----------
class CourseRow(BaseModel):
    course_code: str = Field(..., min_length=1)
    course_title: str = Field(..., min_length=1)
    course_description: str = Field(..., min_length=1)


class ScanResult(BaseModel):
    rows: List[CourseRow]
    raw_text_len: int


# ---------- PDF -> Text ----------
def extract_text_from_pdf(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes))
    parts: List[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            parts.append("")
    text = "\n".join(parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------- LLM Prompting ----------
_SYSTEM = (
    "You extract structured course data from curriculum PDFs. "
    "Return ONLY valid JSON with the schema: "
    "{ \"rows\": [ {\"course_code\": str, \"course_title\": str, \"course_description\": str}, ... ] }"
    "You can find the information under the header: MAJOR COURSE DESCRIPTIONS"
    "Scan through the PDF three times before finalizing the stored output."
    "Make sure there are no duplicates by checking existing course codes and double checking if there are differences in capitalization or spacing. For example, if you see both 'CS101' and 'CS 101', only keep one of them."
    "Also check for title duplications in terms of capitalization and spacing. For example, if you see both 'Introduction to Programming' and 'introduction to programming' and 'INTRODUCTION TO PROGRAMMING', only keep one of them."
)

_USER_TEMPLATE = """Extract all courses from the following curriculum text.

Return JSON with key "rows": a list of objects:
- course_code (short alphanumeric like IT 101 / CS101)
- course_title (short title)
- course_description (1-5 sentences)

Text:
{payload}
"""

def _strip_code_fences(s: str) -> str:
    s = s.strip()
    # Remove ```json ... ``` or ``` ... ```
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()


def call_gemini(text: str) -> Dict[str, Any]:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    prompt = _USER_TEMPLATE.format(payload=text[:20000])  # keep request bounded
    body = {
        "contents": [
            {"role": "user", "parts": [{"text": _SYSTEM}]},
            {"role": "user", "parts": [{"text": prompt}]},
        ],
        "generationConfig": {"temperature": 0.2},
    }
    r = requests.post(url, json=body, timeout=90)
    r.raise_for_status()
    data = r.json()

    try:
        cand = data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        raise RuntimeError(f"Gemini unexpected response: {json.dumps(data)[:400]}")

    cleaned = _strip_code_fences(cand)
    # Try JSON object first
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # If model returned a bare array, wrap it
        if cleaned.startswith("[") and cleaned.endswith("]"):
            return {"rows": json.loads(cleaned)}
        # Last resort: capture the first {...} block
        m = re.search(r"\{.*\}", cleaned, flags=re.S)
        if m:
            return json.loads(m.group(0))
        raise RuntimeError(f"Gemini returned non-JSON or malformed JSON: {cleaned[:400]}")


def call_openai(text: str) -> Dict[str, Any]:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set")

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    prompt = _USER_TEMPLATE.format(payload=text[:20000])
    body = {
        "model": OPENAI_MODEL,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    r = requests.post(url, json=body, headers=headers, timeout=90)
    r.raise_for_status()
    data = r.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except Exception:
        raise RuntimeError(f"OpenAI unexpected response: {json.dumps(data)[:400]}")
    return json.loads(content)


def _regex_fallback(text: str) -> List[CourseRow]:
    """
    Super-naive backup:
    - headers like 'CS101 – Introduction to Programming'
    - description = subsequent non-empty lines until blank
    """
    rows: List[CourseRow] = []
    header_re = re.compile(r"(?P<code>[A-Z]{2,}\s*\d{2,})\s*[–-]\s*(?P<title>[^\n]+)")
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = header_re.search(lines[i])
        if m:
            code = m.group("code").strip()
            title = m.group("title").strip()
            desc_lines: List[str] = []
            j = i + 1
            while j < len(lines) and lines[j].strip():
                desc_lines.append(lines[j].strip())
                j += 1
            desc = " ".join(desc_lines) or "No description provided."
            rows.append(CourseRow(course_code=code, course_title=title, course_description=desc))
            i = j
        else:
            i += 1
    return rows


def llm_parse_courses(pdf_text: str) -> List[CourseRow]:
    try:
        raw = call_gemini(pdf_text) if LLM_PROVIDER == "gemini" else call_openai(pdf_text)
    except Exception as e:
        logger.warning("LLM parse failed (%s). Falling back to regex.", e)
        coarse = _regex_fallback(pdf_text)
        if coarse:
            return coarse
        raise

    # Normalize to ScanResult -> rows[List[CourseRow]]
    try:
        parsed = ScanResult(
            rows=[CourseRow(**row) for row in raw.get("rows", [])],
            raw_text_len=len(pdf_text),
        )
    except (ValidationError, AttributeError, TypeError) as ve:
        # If the model returned a bare list
        if isinstance(raw, list):
            parsed = ScanResult(rows=[CourseRow(**x) for x in raw], raw_text_len=len(pdf_text))
        else:
            snippet = (json.dumps(raw) if not isinstance(raw, str) else raw)[:400]
            raise RuntimeError(f"LLM JSON shape invalid: {ve}; got: {snippet}") from ve

    return parsed.rows


# ---------- Supabase upsert ----------
def upsert_courses(rows: List[CourseRow]) -> List[Dict[str, Any]]:
    """
    Only writes 'course_code', 'course_title', 'course_description'.
    Does NOT send 'course_id' (int8 identity), and we don't assume 'updated_at'.
    NOTE: supabase-py v2 doesn't support chaining .select() after .upsert().
    """
    if not rows:
        return []

    payload = [r.model_dump() for r in rows]

    # 1) Upsert
    up = SB.table(COURSES_TABLE).upsert(payload, on_conflict=UPSERT_ON).execute()
    data = up.data or []

    # 2) If your PostgREST settings return the row representation, 'data' already
    #    contains the inserted/updated rows. If not, fetch them explicitly:
    if data and all("course_id" in d for d in data):
        return data

    # Fallback explicit fetch for a clean response shape
    try:
        codes = [r.course_code for r in rows]
        fetched = (
            SB.table(COURSES_TABLE)
            .select("course_id, course_code, course_title, course_description, created_at")
            .in_("course_code", codes)
            .execute()
        )
        return fetched.data or data
    except Exception as e:
        logger.warning("Post-upsert fetch failed, returning raw upsert data: %s", e)
        return data


# ---------- Orchestrator entry ----------
def scan_pdf_and_store(file_bytes: bytes) -> Dict[str, Any]:
    """
    Main entry: PDF bytes -> text -> LLM parse -> upsert courses
    Returns:
      {
        "inserted": [...rows],
        "parsed_rows": [ {course_code,title,description} ... ],
        "raw_text_len": int
      }
    """
    text = extract_text_from_pdf(file_bytes)
    rows = llm_parse_courses(text)

    inserted = upsert_courses(rows) if rows else []
    return {
        "inserted": inserted,
        "parsed_rows": [r.model_dump() for r in rows],
        "raw_text_len": len(text),
    }