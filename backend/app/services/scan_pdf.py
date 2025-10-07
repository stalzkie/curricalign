from __future__ import annotations

import os
import re
import json
import logging
import requests
from typing import List, Dict, Any, Iterable, Optional

from supabase import create_client, Client
from pydantic import BaseModel, Field, ValidationError
import fitz  # PyMuPDF
from dotenv import load_dotenv

# ---------- Logging ----------
logger = logging.getLogger(__name__)

# ---------- Env / Config ----------
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")

SB: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------- Gemini API (using REST directly to force v1) ----------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY must be set for Gemini parsing")

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")
GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1"

logger.info("✅ Using Gemini v1 REST API directly with model: %s", GEMINI_MODEL)

# ---------- Tunables ----------
COURSES_TABLE = os.getenv("COURSES_TABLE", "courses")
UPSERT_ON = os.getenv("COURSES_UPSERT_COLUMN", "course_code")
MIN_REASONABLE_ROWS = int(os.getenv("SCAN_MIN_ROWS", "15"))  # Increased threshold
CHUNK_SIZE = int(os.getenv("SCAN_CHUNK_SIZE", "6000"))  # Larger chunks
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
        
        # Focus on pages 11+ where major course descriptions are
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text") or ""
            
            # Only include pages that have course description content
            if page_num >= 10:  # Page 11 is index 10
                parts.append(text)
        
        doc.close()
        joined = "\n".join(parts)
        
        # Clean up hyphenation and extra whitespace
        joined = re.sub(r"(\w+)-\n(\w+)", r"\1\2", joined)
        joined = re.sub(r"[ \t]+\n", "\n", joined)
        joined = re.sub(r"\n{2,}", "\n\n", joined)
        return joined.strip()
    except Exception as e:
        logger.error("❌ PyMuPDF extraction failed: %s", e)
        return ""

# ---------- 2️⃣ Gemini Parsing (using REST API directly) ----------
_SYSTEM = """You are a precise curriculum parser extracting course information from the "MAJOR COURSE DESCRIPTION" section of a Computer Science curriculum document.

CRITICAL INSTRUCTIONS:
1. Extract ONLY courses from the "MAJOR COURSE DESCRIPTION" section (pages 11-16 in the document)
2. Each course entry follows this format:
   - Course code (e.g., "CompF", "Prog1", "DatSci") - appears on the left with unit count
   - Course title in UPPERCASE (e.g., "COMPUTING FUNDAMENTALS (LECTURE)")
   - Course description - the paragraph explaining what the course covers

3. DO NOT extract from:
   - Course curriculum tables (pages 3-10)
   - Summary tables
   - General Education courses
   - Professional Electives (unless specifically under "Professional Electives: Analytics Intelligence Specialization" section on page 7)

4. Return ONLY valid JSON with this exact schema:
{
  "rows": [
    {
      "course_code": "CompF",
      "course_title": "COMPUTING FUNDAMENTALS",
      "course_description": "Full description here..."
    }
  ]
}

5. Rules:
   - Keep course_code exactly as written (e.g., "CompF", "Prog2", "DatSci")
   - Keep course_title in UPPERCASE, remove anything in parentheses like "(LECTURE)" or "(LABORATORY)"
   - Merge multiline descriptions into one complete paragraph
   - Only extract courses with full descriptions (at least 50 words)
   - If no valid major course descriptions found, return {"rows": []}
"""

_USER_TEMPLATE = """Extract all major course descriptions from this text:

{payload}

Return ONLY the JSON object (no markdown, no backticks, no commentary).
"""

def _strip_code_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    return s.strip()

def _call_gemini_json(prompt_text: str) -> Dict[str, Any]:
    """Call Gemini API directly via REST (v1) to avoid SDK's v1beta hardcoding"""
    prompt = _USER_TEMPLATE.format(payload=prompt_text[:30000])  # Increased limit
    
    url = f"{GEMINI_API_BASE}/models/{GEMINI_MODEL}:generateContent"
    
    headers = {
        "Content-Type": "application/json",
    }
    
    payload = {
        "contents": [{
            "parts": [{
                "text": _SYSTEM + "\n\n" + prompt
            }]
        }],
        "generationConfig": {
            "temperature": 0.1,  # Lower temperature for more consistent extraction
            "maxOutputTokens": 8192,  # Increased for more courses
        }
    }
    
    params = {
        "key": GEMINI_API_KEY
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, params=params, timeout=60)
        response.raise_for_status()
        result = response.json()
        
        # Extract text from response
        candidates = result.get("candidates", [])
        if not candidates:
            raise RuntimeError("Gemini returned no candidates")
        
        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        if not parts:
            raise RuntimeError("Gemini returned empty parts")
            
        raw = parts[0].get("text", "")
        if not raw:
            raise RuntimeError("Gemini returned empty response.")
            
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Gemini call failed: {e}")
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"Gemini response parsing failed: {e}")
    
    raw = _strip_code_fences(raw.strip())

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
    logger.info("🚀 Starting hybrid scan pipeline (PyMuPDF + Gemini v1 REST API)… [model=%s]", GEMINI_MODEL)

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
                if "not found" in last_err or "404" in last_err:
                    logger.warning("⚠️ Chunk parse aborted due to model error: %s", last_err)
                    break
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