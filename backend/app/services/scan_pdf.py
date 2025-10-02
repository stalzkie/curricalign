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

# Try high-fidelity text extraction first
try:
    from pdfminer.high_level import extract_text as pdfminer_extract
    _PDFMINER_AVAILABLE = True
except Exception:
    _PDFMINER_AVAILABLE = False

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


# ---------- Helpers for parsing ----------
HEADER_MAJOR = re.compile(r"\bMAJOR COURSE DESCRIPTION(?:S)?\b", re.I)
ALLCAPS_HEADER = re.compile(r"\n[A-Z][A-Z0-9&/ ,\-]{8,}\n")  # generic next big header

def _norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _slice_major_only(text: str) -> str:
    """
    Return ONLY the text under 'MAJOR COURSE DESCRIPTION(S)' up to the next ALL-CAPS header or EOF.
    """
    m = HEADER_MAJOR.search(text)
    if not m:
        return ""
    start = m.end()
    n = ALLCAPS_HEADER.search(text, start)
    end = n.start() if n else len(text)
    return text[start:end].strip()


# ---------- PDF -> Text ----------
def extract_text_from_pdf(file_bytes: bytes) -> str:
    """
    Prefer pdfminer.six for higher-fidelity text extraction.
    Fallback to PyPDF2 when pdfminer isn't available.
    """
    text = ""
    if _PDFMINER_AVAILABLE:
        try:
            text = pdfminer_extract(io.BytesIO(file_bytes)) or ""
        except Exception as e:
            logger.warning("pdfminer extract failed (%s). Falling back to PyPDF2.", e)

    if not text:
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


# ---------- Deterministic parser for MAJOR COURSE DESCRIPTION(S) ----------
def parse_major_course_descriptions(text: str) -> List[CourseRow]:
    """
    Parse 'MAJOR COURSE DESCRIPTION(S)' blocks ONLY.

    Expected pattern per course:
      Line A: <CODE> <units> units [optional details]
              e.g., "CompF 3 units" / "Prog1 4 units (LEC 2, LAB 2)" / "PATHFit 1 2 units"
      Line B: <TITLE> (often uppercase)
      Line C+: description (until blank line or next course header)

    We:
      - keep the original course_code as-is,
      - uppercase course_title to normalize,
      - merge multi-line descriptions until the next header.
    """
    section = _slice_major_only(text)
    if not section:
        return []

    lines = [ln.rstrip() for ln in section.splitlines()]
    rows: List[CourseRow] = []

    # Header line matcher:
    #   - code: letters/digits with optional space+digit suffix (e.g., PATHFit 1)
    #   - units: a number before the word 'units'
    head_re = re.compile(
        r"^\s*(?P<code>[A-Za-z][A-Za-z0-9]*(?:\s?\d{1,2})?)\s+(?P<units>\d+)\s+units\b.*$",
        re.I,
    )

    i, L = 0, len(lines)
    while i < L:
        m = head_re.match(lines[i])
        if not m:
            i += 1
            continue

        code = m.group("code").strip()

        # Next non-empty line is the Title
        j = i + 1
        while j < L and not lines[j].strip():
            j += 1
        title = lines[j].strip() if j < L else ""
        title = title.upper()  # normalize to uppercase as requested

        # Accumulate description until next header or end
        desc_lines: List[str] = []
        k = j + 1
        while k < L:
            if head_re.match(lines[k]):  # next course header found
                break
            # Paranoia stop if a big ALLCAPS header leaks into the slice
            if ALLCAPS_HEADER.match("\n" + lines[k] + "\n"):
                break
            if lines[k].strip():
                desc_lines.append(lines[k].strip())
            k += 1

        desc = _norm_space(" ".join(desc_lines)) or "No description provided."

        rows.append(
            CourseRow(
                course_code=code,
                course_title=title,
                course_description=desc,
            )
        )

        i = k  # jump to next block

    return rows


# ---------- LLM Prompting ----------
_SYSTEM = (
    "You extract structured course data from curriculum PDFs. "
    "Return ONLY valid JSON with the schema: "
    "{ \"rows\": [ {\"course_code\": str, \"course_title\": str, \"course_description\": str}, ... ] } "
    "Only consider the content inside the section labeled 'MAJOR COURSE DESCRIPTION' or 'MAJOR COURSE DESCRIPTIONS'. "
    "Scan carefully and avoid duplicates (normalize spacing and capitalization for both course codes and titles)."
)

_USER_TEMPLATE = """Extract all courses ONLY from the 'MAJOR COURSE DESCRIPTION(S)' section in the following text.

Return JSON with key "rows": a list of objects:
- course_code (short alphanumeric like IT 101 / CS101 / PATHFit 1)
- course_title (short title; keep original or uppercase if unclear)
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
    Very naive backup for patterns like:
      'CS101 – Introduction to Programming'
    Description = subsequent non-empty lines until blank.
    Not specific to MAJOR section; only used if everything else fails.
    """
    rows: List[CourseRow] = []
    header_re = re.compile(r"(?P<code>[A-Z]{2,}\s*\d{1,})\s*[–-]\s*(?P<title>[^\n]+)")
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
            rows.append(CourseRow(course_code=code, course_title=title, course_description=_norm_space(desc)))
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

    cleaned_rows = []
    for row in raw.get("rows", []):
        # Normalize and auto-repair empty values
        code = (row.get("course_code") or "").strip()
        title = (row.get("course_title") or "").strip()
        desc = (row.get("course_description") or "").strip()

        if not code:
            code = "UNKNOWN_CODE"
        if not title:
            title = "Untitled Course"
        if not desc:
            desc = "No description provided."

        try:
            cleaned_rows.append(
                CourseRow(
                    course_code=code,
                    course_title=title,
                    course_description=desc,
                )
            )
        except Exception as ve:
            logger.warning("Skipping invalid row after normalization: %s", ve)

    parsed = ScanResult(rows=cleaned_rows, raw_text_len=len(pdf_text))
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
    STRICT: PDF bytes -> text -> parse ONLY MAJOR COURSE DESCRIPTION(S) -> upsert.
    If deterministic parsing yields nothing (unexpected layout), LLM fallback is applied
    on the MAJOR-only slice, not the entire document.
    Returns:
      {
        "inserted": [...rows],
        "parsed_rows": [ {course_code,title,description} ... ],
        "raw_text_len": int
      }
    """
    text = extract_text_from_pdf(file_bytes)

    # 1) Deterministic parse for the MAJOR COURSE DESCRIPTION(S) section
    rows = parse_major_course_descriptions(text)

    # 2) Optional fallback: try LLM on the major-only slice (strict scope)
    if not rows:
        major_only = _slice_major_only(text)
        if major_only:
            try:
                rows = llm_parse_courses(major_only)
            except Exception as e:
                logger.warning("LLM fallback also failed: %s", e)
                rows = []
        else:
            rows = []

    inserted = upsert_courses(rows) if rows else []
    return {
        "inserted": inserted,
        "parsed_rows": [r.model_dump() for r in rows],
        "raw_text_len": len(text),
    }
