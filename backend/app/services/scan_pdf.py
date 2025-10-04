# apps/backend/services/scan_pdf.py
from __future__ import annotations

import os
import io
import re
import json
import logging
from typing import List, Dict, Any, Iterable, Tuple

from supabase import create_client, Client
from pydantic import BaseModel, Field, ValidationError

# Primary/backup PDF readers
from PyPDF2 import PdfReader
import requests

# Try high-fidelity text extraction first
try:
    from pdfminer.high_level import extract_text as pdfminer_extract
    _PDFMINER_AVAILABLE = True
except Exception:
    _PDFMINER_AVAILABLE = False

# Try PyMuPDF as second extractor
try:
    import fitz  # PyMuPDF
    _PYMUPDF_AVAILABLE = True
except Exception:
    _PYMUPDF_AVAILABLE = False

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
UPSERT_ON = os.getenv("COURSES_UPSERT_COLUMN", "course_code")  # unique key in DB

# Tunables
MIN_REASONABLE_ROWS = int(os.getenv("SCAN_MIN_ROWS", "6"))   # escalate if < this
CHUNK_SIZE = int(os.getenv("SCAN_CHUNK_SIZE", "4500"))       # characters per LLM chunk
CHUNK_OVERLAP = int(os.getenv("SCAN_CHUNK_OVERLAP", "600"))  # characters overlap

# ---------- Models ----------
class CourseRow(BaseModel):
    course_code: str = Field(..., min_length=1)
    course_title: str = Field(..., min_length=1)
    course_description: str = Field(..., min_length=1)

class ScanResult(BaseModel):
    rows: List[CourseRow]
    raw_text_len: int

# ---------- Helpers (normalize, chunking, dedupe) ----------
def _norm_space(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def _normalize_text(t: str) -> str:
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()

def _sliding_windows(txt: str, size: int, overlap: int) -> Iterable[str]:
    if size <= 0:
        yield txt
        return
    n = len(txt)
    i = 0
    while i < n:
        yield txt[i : min(i + size, n)]
        if i + size >= n:
            break
        i = max(i + size - overlap, i + 1)

def _canonical_code(code: str) -> str:
    # normalize for dedupe: collapse spaces like "CS 101" -> "CS101"
    return re.sub(r"\s+", "", (code or "").upper())

def _merge_dedupe(primary: List[CourseRow], secondary: List[CourseRow]) -> List[CourseRow]:
    by_code: Dict[str, CourseRow] = { _canonical_code(r.course_code): r for r in primary }
    for r in secondary:
        key = _canonical_code(r.course_code)
        if key not in by_code:
            by_code[key] = r
        else:
            # prefer row with longer description/title (more info)
            a = by_code[key]
            if len(r.course_description or "") > len(a.course_description or "") or \
               len(r.course_title or "") > len(a.course_title or ""):
                by_code[key] = r
    return list(by_code.values())

# ---------- Semantic section slicing (labels/cues) ----------
MAJOR_LABELS = [
    r"\bMAJOR COURSE DESCRIPTION(?:S)?\b",
    r"\bMAJOR COURSES\b",
    r"\bMAJOR SUBJECTS\b",
    r"\bMAJOR(?:\s+AND\s+PROFESSIONAL)?\s+COURSES\b"
]
END_CUES = [
    r"\bMINOR\b",
    r"\bELECTIVE(S)?\b",
    r"\bGENERAL EDUCATION\b",
    r"\bGEN(?:ERAL)? ED(?:UCATION)?\b",
    r"\bCOURSE (?:MAP|MATRIX)\b",
    r"\bPROGRAM OUTCOMES\b",
    r"\bSUMMARY\b",
]

def _slice_major_section(text: str) -> str:
    # find first start label
    starts = [re.search(p, text, re.I) for p in MAJOR_LABELS]
    starts = [m.end() for m in starts if m]
    if not starts:
        return ""
    start = min(starts)

    # earliest end cue after start
    ends = [re.search(p, text[start:], re.I) for p in END_CUES]
    ends = [start + m.start() for m in ends if m]
    end = min(ends) if ends else len(text)

    return text[start:end].strip()

# ---------- PDF -> Text (cascade) ----------
def extract_text_from_pdf(file_bytes: bytes) -> str:
    # 1) pdfminer
    if _PDFMINER_AVAILABLE:
        try:
            txt = pdfminer_extract(io.BytesIO(file_bytes)) or ""
            if txt.strip():
                return _normalize_text(txt)
        except Exception as e:
            logger.warning("pdfminer extract failed (%s)", e)

    # 2) PyMuPDF
    if _PYMUPDF_AVAILABLE:
        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            parts = []
            for p in doc:
                parts.append(p.get_text("text") or "")
            txt = "\n".join(parts)
            if txt.strip():
                return _normalize_text(txt)
        except Exception as e:
            logger.warning("PyMuPDF extract failed (%s)", e)

    # 3) PyPDF2 fallback
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        parts: List[str] = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        return _normalize_text("\n".join(parts))
    except Exception as e:
        logger.error("PyPDF2 extract failed: %s", e)
        return ""

# ---------- LLM prompting (contracts) ----------
_SYSTEM = (
    "Extract ONLY the courses under the 'Major Courses' portion of this curriculum. "
    "Ignore formatting, page headers/footers, and non-major sections. "
    "Return strict JSON with the schema: "
    "{ 'rows': [ {'course_code': str, 'course_title': str, 'course_description': str}, ... ] }. "
    "Do not guess; skip items you can't confidently parse. "
    "Normalize spacing; keep original course_code exactly as written; UPPERCASE course_title. "
    "Deduplicate by course_code (keep the first complete entry)."
)

_USER_TEMPLATE = """Text:
{payload}
"""

def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()

def _post_validate_rows(raw_rows: List[Dict[str, Any]]) -> List[CourseRow]:
    out: List[CourseRow] = []
    for row in raw_rows or []:
        code = _norm_space((row.get("course_code") or "")) or "UNKNOWN_CODE"
        title = _norm_space((row.get("course_title") or "")) or "UNTITLED COURSE"
        desc  = _norm_space((row.get("course_description") or "")) or "No description provided."
        try:
            out.append(CourseRow(course_code=code, course_title=title, course_description=desc))
        except ValidationError as e:
            logger.warning("Dropping invalid row after repair: %s | data=%s", e, row)
    return out

# --- OpenAI JSON-object (best-effort schema) ---
def call_openai_json(text: str) -> Dict[str, Any]:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY not set")

    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}"}
    body = {
        "model": OPENAI_MODEL,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _USER_TEMPLATE.format(payload=text[:20000])},
        ],
        "response_format": {"type": "json_object"},
    }
    r = requests.post(url, json=body, headers=headers, timeout=90)
    r.raise_for_status()
    data = r.json()
    try:
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception as e:
        raise RuntimeError(f"OpenAI unexpected response: {str(e)[:200]} | {json.dumps(data)[:400]}")

# --- Gemini freeform → repaired JSON ---
def call_gemini_jsonish(text: str) -> Dict[str, Any]:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not set")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    body = {
        "contents": [
            {"role": "user", "parts": [{"text": _SYSTEM}]},
            {"role": "user", "parts": [{"text": _USER_TEMPLATE.format(payload=text[:20000])}]},
        ],
        "generationConfig": {"temperature": 0.1},
    }
    r = requests.post(url, json=body, timeout=90)
    r.raise_for_status()
    data = r.json()
    try:
        cand = data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        raise RuntimeError(f"Gemini unexpected response: {json.dumps(data)[:400]}")

    cleaned = _strip_code_fences(cand)
    # Try object, then array wrapped, then first {...}
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        if cleaned.startswith("[") and cleaned.endswith("]"):
            return {"rows": json.loads(cleaned)}
        m = re.search(r"\{.*\}", cleaned, flags=re.S)
        if m:
            return json.loads(m.group(0))
        raise RuntimeError(f"Gemini returned non-JSON or malformed JSON: {cleaned[:400]}")

# ---------- Heuristic candidates (regex) ----------
def heuristic_blocks(major_text: str) -> List[CourseRow]:
    rows: List[CourseRow] = []

    patterns = [
        # CODE — TITLE (same line)
        r"(?P<code>[A-Z][A-Z0-9/._\- ]{1,20})\s*[–\-:]\s*(?P<title>[^\n]+)",
        # CODE <units unit(s)> \n TITLE
        r"(?P<code>[A-Z]{2,}[A-Z0-9/._\- ]{0,10})\s+(?P<units>\d+(?:\.\d+)?)\s*unit(?:s)?\b[^\n]*\n(?P<title>[^\n]+)",
    ]

    for pat in patterns:
        rx = re.compile(pat, re.I)
        for m in rx.finditer(major_text):
            code = _norm_space(m.groupdict().get("code", ""))
            title = _norm_space(m.groupdict().get("title", ""))
            if not code or not title:
                continue
            try:
                rows.append(CourseRow(
                    course_code=code,
                    course_title=title.upper(),
                    course_description="No description provided."
                ))
            except ValidationError:
                # ignore malformed hits
                pass
    return rows

# ---------- Deterministic (supplement) ----------
# Keep a relaxed variant of your earlier deterministic parser
_RELAXED_HEAD = re.compile(
    r"^\s*(?P<code>[A-Za-z][A-Za-z0-9/._\- ]{1,20})\s+(?P<units>\d+(?:\.\d+)?)\s*unit(?:s)?\b.*$",
    re.I,
)
def deterministic_parse_major(text: str) -> List[CourseRow]:
    section = _slice_major_section(text)
    if not section:
        return []
    lines = [ln.rstrip() for ln in section.splitlines()]
    rows: List[CourseRow] = []

    i, L = 0, len(lines)
    while i < L:
        m = _RELAXED_HEAD.match(lines[i])
        if not m:
            i += 1
            continue
        code = _norm_space(m.group("code"))

        # next non-empty line as title; guard against premature headers
        j = i + 1
        while j < L and not lines[j].strip():
            j += 1
        title = lines[j].strip() if j < L else ""
        if not title or _RELAXED_HEAD.match(title):
            title = "UNTITLED COURSE"
        title = title.upper()

        # accumulate description
        desc_lines: List[str] = []
        k = j + 1
        while k < L:
            if _RELAXED_HEAD.match(lines[k]):
                break
            if lines[k].strip():
                desc_lines.append(lines[k].strip())
            k += 1
        desc = _norm_space(" ".join(desc_lines)) or "No description provided."

        try:
            rows.append(CourseRow(course_code=code, course_title=title, course_description=desc))
        except ValidationError as e:
            logger.warning("Skipping invalid deterministic block (code=%r): %s", code, e)

        i = k
    return rows

# ---------- LLM-first parse with escalation ----------
def llm_first_parse_major(major_text: str) -> List[CourseRow]:
    rows: List[CourseRow] = []

    # 1) Single-pass LLM
    try:
        raw = call_openai_json(major_text) if (LLM_PROVIDER == "openai") else call_gemini_jsonish(major_text)
        rows = _post_validate_rows(raw.get("rows", []))
    except Exception as e:
        logger.warning("Primary LLM parse failed (%s). Falling back to chunked + heuristics.", e)
        rows = []

    # 2) If low recall, chunk with overlap and merge
    if len(rows) < MIN_REASONABLE_ROWS:
        logger.info("LLM rows %d < %d; running chunked passes", len(rows), MIN_REASONABLE_ROWS)
        chunk_rows: List[CourseRow] = []
        for chunk in _sliding_windows(major_text, CHUNK_SIZE, CHUNK_OVERLAP):
            try:
                raw = call_openai_json(chunk) if (LLM_PROVIDER == "openai") else call_gemini_jsonish(chunk)
                chunk_rows = _merge_dedupe(chunk_rows, _post_validate_rows(raw.get("rows", [])))
            except Exception as ce:
                logger.warning("Chunk parse failed: %s", ce)
        rows = _merge_dedupe(rows, chunk_rows)

    # 3) Heuristic supplement
    if len(rows) < MIN_REASONABLE_ROWS:
        logger.info("Rows still low after chunking; merging heuristic candidates")
        rows = _merge_dedupe(rows, heuristic_blocks(major_text))

    return rows

# ---------- Supabase upsert ----------
def upsert_courses(rows: List[CourseRow]) -> List[Dict[str, Any]]:
    if not rows:
        return []

    payload = [r.model_dump() for r in rows]

    up = SB.table(COURSES_TABLE).upsert(payload, on_conflict=UPSERT_ON).execute()
    data = up.data or []

    # If PostgREST returns rows with ids, great; otherwise fetch explicitly
    if data and all("course_id" in d for d in data):
        return data

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
    Layout-agnostic pipeline:
      PDF bytes → robust text → semantic 'Major' slice →
      LLM-first (schema) + chunked retries + heuristics →
      deterministic supplement (last) → upsert.
    """
    text = extract_text_from_pdf(file_bytes)
    major_text = _slice_major_section(text)

    if not major_text:
        logger.warning("No 'Major Courses' section detected.")
        inserted: List[Dict[str, Any]] = []
        return {
            "inserted": inserted,
            "parsed_rows": [],
            "raw_text_len": len(text),
        }

    # LLM-first with escalation
    rows = llm_first_parse_major(major_text)

    # Final deterministic supplement if results still seem small
    if len(rows) < MIN_REASONABLE_ROWS:
        logger.info("Final supplement via deterministic parser")
        rows = _merge_dedupe(rows, deterministic_parse_major(text))

    logger.info("Final parsed rows: %d", len(rows))
    inserted = upsert_courses(rows) if rows else []

    return {
        "inserted": inserted,
        "parsed_rows": [r.model_dump() for r in rows],
        "raw_text_len": len(text),
    }
