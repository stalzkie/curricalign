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
import google.generativeai as genai  # ← Using SDK like skill_extractor!

# ---------- Logging ----------
logger = logging.getLogger(__name__)

# ---------- Env / Config ----------
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")

SB: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------- Gemini API (using SDK like skill_extractor) ----------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY must be set for Gemini parsing")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-pro")  # ← Simple like skill_extractor!

logger.info("✅ Using Gemini SDK with model: gemini-1.5-pro")

# ---------- Tunables ----------
COURSES_TABLE = os.getenv("COURSES_TABLE", "courses")
UPSERT_ON = os.getenv("COURSES_UPSERT_COLUMN", "course_code")
MIN_REASONABLE_ROWS = int(os.getenv("SCAN_MIN_ROWS", "15"))
CHUNK_SIZE = int(os.getenv("SCAN_CHUNK_SIZE", "6000"))
CHUNK_OVERLAP = int(os.getenv("SCAN_CHUNK_OVERLAP", "800"))
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
        parts: List[str] = []
        
        # Extract ALL pages from page 11 onwards (where course descriptions start)
        for page_num in range(len(doc)):
            if page_num >= 10:  # Page 11 is index 10
                page = doc[page_num]
                text = page.get_text("text") or ""
                parts.append(text)
        
        doc.close()
        joined = "\n".join(parts)
        
        # Clean up hyphenation and extra whitespace
        joined = re.sub(r"(\w+)-\n(\w+)", r"\1\2", joined)
        joined = re.sub(r"[ \t]+\n", "\n", joined)
        joined = re.sub(r"\n{2,}", "\n\n", joined)
        
        result = joined.strip()
        logger.info("📄 Extracted %d characters from pages 11+", len(result))
        logger.info("📄 First 300 chars of extracted text:\n%s\n", result[:300])
        
        return result
    except Exception as e:
        logger.error("❌ PyMuPDF extraction failed: %s", e)
        return ""

# ---------- 2️⃣ Gemini Parsing (using SDK) ----------
_SYSTEM_PROMPT = """Extract all computer science courses from this curriculum text.

For each course, find:
- Course code (like "CompF", "Prog1", "DatSci")  
- Course title (like "COMPUTING FUNDAMENTALS")
- Course description (the full paragraph explaining the course)

ONLY extract courses that have ALL THREE: code, title, AND a description paragraph.

Return a valid JSON array like this:
[
  {{"course_code": "CompF", "course_title": "COMPUTING FUNDAMENTALS", "course_description": "This course provides..."}},
  {{"course_code": "Prog1", "course_title": "PROGRAMMING ESSENTIALS", "course_description": "This course emphasizes..."}}
]

Curriculum text:
{text}

Return ONLY the JSON array, no other text."""

def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()

def _call_gemini_json(prompt_text: str) -> Dict[str, Any]:
    """Call Gemini using SDK (like skill_extractor)"""
    prompt = _SYSTEM_PROMPT.format(text=prompt_text[:30000])
    
    try:
        # Simple SDK call like skill_extractor
        response = model.generate_content(prompt)
        raw = response.text.strip()
        
        logger.info("📥 Gemini response (first 500 chars):\n%s\n", raw[:500])
        
    except Exception as e:
        raise RuntimeError(f"Gemini call failed: {e}")
    
    # Strip markdown code fences if present
    raw = _strip_code_fences(raw)
    
    # Try direct JSON parse first (as array or object)
    try:
        parsed = json.loads(raw)
        
        # Handle both array and object responses
        if isinstance(parsed, list):
            logger.info("✅ Parsed as JSON array with %d items", len(parsed))
            return {"rows": parsed}
        elif isinstance(parsed, dict):
            logger.info("✅ Parsed as JSON object")
            return parsed
            
    except json.JSONDecodeError as e:
        logger.warning("⚠️ Direct JSON parse failed: %s", e)

    # Try to find JSON in the response (array or object)
    # Look for arrays first
    array_match = re.search(r'\[.*\]', raw, re.DOTALL)
    if array_match:
        try:
            parsed = json.loads(array_match.group(0))
            if isinstance(parsed, list):
                logger.info("✅ Extracted and parsed JSON array with %d items", len(parsed))
                return {"rows": parsed}
        except json.JSONDecodeError as e:
            logger.warning("⚠️ Array extraction failed: %s", e)
    
    # Look for objects
    obj_match = re.search(r'\{.*\}', raw, re.DOTALL)
    if obj_match:
        try:
            parsed = json.loads(obj_match.group(0))
            if isinstance(parsed, dict):
                logger.info("✅ Extracted and parsed JSON object")
                return parsed
        except json.JSONDecodeError as e:
            logger.warning("⚠️ Object extraction failed: %s", e)

    # If all else fails, log the full response for debugging
    logger.error("❌ Could not parse JSON. Full response:\n%s\n", raw)
    raise RuntimeError(f"Gemini returned unparseable response. First 400 chars: {raw[:400]}")

def _parse_gemini_rows(raw_obj: Dict[str, Any]) -> List[CourseRow]:
    cleaned: List[CourseRow] = []
    for row in (raw_obj.get("rows") or []):
        code = _norm_space(str(row.get("course_code", ""))) or "UNKNOWN_CODE"
        title = _norm_space(str(row.get("course_title", ""))) or "UNTITLED COURSE"
        desc = _norm_space(str(row.get("course_description", ""))) or "No description provided."
        
        # Clean up title - remove (LECTURE), (LABORATORY), etc.
        title = re.sub(r"\s*\([^)]*\)\s*", " ", title).strip()
        title = title.upper()
        
        # Skip if description is too short (likely not a real course description)
        if len(desc.split()) < 20:
            logger.warning("Skipping course with short description: %s", code)
            continue
            
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
    logger.info("🚀 Starting hybrid scan pipeline (PyMuPDF + Gemini SDK)...")

    # Step 1 — Extract text from major course description pages
    full_text = extract_full_text_pymupdf(file_bytes)
    if not full_text:
        raise RuntimeError("No text extracted from PDF.")

    logger.info("📄 Extracted %d characters from PDF", len(full_text))

    # Step 2 — Parse with Gemini (try full text first)
    rows: List[CourseRow] = []
    last_err: Optional[str] = None
    
    try:
        logger.info("🔍 Parsing full document with Gemini...")
        raw_obj = _call_gemini_json(full_text)
        rows = _parse_gemini_rows(raw_obj)
        logger.info("✅ Extracted %d courses from full parse", len(rows))
    except Exception as e:
        last_err = str(e)
        logger.warning("⚠️ Gemini main parse failed: %s", last_err)

    # Step 3 — Retry with chunks if recall is low
    if len(rows) < MIN_REASONABLE_ROWS:
        logger.info("🔄 Low recall (%d courses); retrying with chunked text", len(rows))
        chunk_rows: List[CourseRow] = []
        chunk_count = 0
        
        for chunk in _sliding_windows(full_text, CHUNK_SIZE, CHUNK_OVERLAP):
            chunk_count += 1
            logger.info("📦 Processing chunk %d...", chunk_count)
            
            try:
                r = _call_gemini_json(chunk)
                new_courses = _parse_gemini_rows(r)
                chunk_rows = _merge_dedupe(chunk_rows, new_courses)
                logger.info("   Found %d courses in chunk %d (total: %d unique)", 
                          len(new_courses), chunk_count, len(chunk_rows))
            except Exception as ce:
                last_err = str(ce)
                logger.warning("⚠️ Chunk %d parse failed: %s", chunk_count, last_err)
                
        rows = _merge_dedupe(rows, chunk_rows)
        logger.info("✅ After chunked parsing: %d total courses", len(rows))

    # Step 4 — Optional fail if still empty
    if FAIL_ON_EMPTY and len(rows) == 0:
        raise RuntimeError(
            f"Gemini parse produced 0 rows. "
            f"{'Last error: ' + last_err if last_err else 'No additional error details.'}"
        )

    # Log what we found
    logger.info("📚 Courses extracted:")
    for r in rows:
        logger.info("   - %s: %s", r.course_code, r.course_title)

    # Step 5 — Save to Supabase
    inserted = upsert_courses(rows) if rows else []
    logger.info("✅ Parsed %d rows and inserted %d", len(rows), len(inserted))

    return {
        "inserted": inserted,
        "parsed_rows": [r.model_dump() for r in rows],
        "raw_text_len": len(full_text),
    }