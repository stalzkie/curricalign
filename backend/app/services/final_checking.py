# backend/app/services/final_checking.py
from __future__ import annotations

import os
import re
import logging
import asyncio
from typing import Any, Dict, List, Optional, Tuple, Iterable, Set

from rapidfuzz.fuzz import token_set_ratio as rf_token_set_ratio

from ..core.supabase_client import supabase
from .report_utils import fetch_report_data_from_supabase  # ✅ use shared fetcher

# ----------------------------------------------------------------------
# Logging setup
# ----------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [final_checking] %(message)s",
)

# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------
def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}

STRICT_GATE_DEFAULT = _env_flag("STRICT_REPORT_GATE", True)

REQUIRED_FIELDS = (
    "course_id",
    "course_code",
    "course_title",
    "coverage",
    "avg_similarity",
    "score",
)

MIN_ROWS = int(os.getenv("FINAL_CHECK_MIN_ROWS", "5"))
MIN_COVERAGE = float(os.getenv("FINAL_CHECK_MIN_COVERAGE", "0.0"))
MIN_AVG_SIMILARITY = float(os.getenv("FINAL_CHECK_MIN_AVG_SIM", "0.0"))
REQUIRE_SINGLE_BATCH = _env_flag("FINAL_CHECK_REQUIRE_SINGLE_BATCH", True)

# Fuzzy de-dupe threshold for skill phrases (0..1). 0.86 works well in practice.
FUZZY_DEDUPE_THRESHOLD = float(os.getenv("FINAL_CHECK_FUZZY_DEDUPE", "0.86"))

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
_STOPWORDS = {
    "a","an","and","the","of","to","in","on","for","with","using","by","from","into","via","as","at"
}

def _coerce_float(x: Any) -> Optional[float]:
    try:
        v = float(x)
        if v != v:  # NaN
            return None
        return v
    except Exception:
        return None

def _coerce_int(x: Any) -> Optional[int]:
    try:
        return int(x)
    except Exception:
        try:
            return int(float(x))
        except Exception:
            return None

def _unique_ordered(seq: Iterable[Any]) -> List[Any]:
    seen: Set[Any] = set()
    out: List[Any] = []
    for s in seq:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out

def _split_csv(s: str) -> List[str]:
    return [x.strip() for x in s.split(",") if str(x).strip()]

def _as_list(v: Any) -> List[str]:
    """
    Normalize a field that can be list, "a, b" string, or Postgres brace-string "{a,b}".
    """
    if v is None:
        return []
    if isinstance(v, list):
        return _unique_ordered([str(x).strip() for x in v if str(x).strip()])
    if isinstance(v, str):
        s = v.strip()
        if s.startswith("{") and s.endswith("}"):
            s = s[1:-1]
        return _unique_ordered(_split_csv(s))
    return []

def _get_code2id() -> Dict[str, Any]:
    """
    Build a course_code -> course_id lookup as a safety net.
    """
    try:
        rows = (
            supabase.table("courses")
            .select("course_id, course_code")
            .execute()
            .data
            or []
        )
        return {
            r["course_code"]: r["course_id"]
            for r in rows
            if r.get("course_id") and r.get("course_code")
        }
    except Exception as e:
        logging.warning(f"[final_checking] Could not build course_code map: {e}")
        return {}

# --- Fuzzy skill de-duplication ---------------------------------------

_norm_keep_chars_re = re.compile(r"[^0-9a-zA-Z#+.\s]+")
_multi_space_re = re.compile(r"\s+")

def _tokenize_no_stop(text: str) -> List[str]:
    """
    Lowercase, keep letters/digits and tech chars (# + .), strip punctuation,
    remove stopwords, keep order.
    """
    s = _norm_keep_chars_re.sub(" ", text.lower())
    s = _multi_space_re.sub(" ", s).strip()
    tokens = [t for t in s.split(" ") if t and t not in _STOPWORDS]
    return tokens

def _norm_phrase(text: str) -> str:
    """
    Canonical string for fuzzy matching (space-joined tokens without stopwords).
    """
    toks = _tokenize_no_stop(text)
    return " ".join(toks)

def _info_len(text: str) -> int:
    """How 'atomic' a phrase is: fewer non-stopword tokens preferred."""
    return len(_tokenize_no_stop(text))

def _dedupe_skill_phrases(items: List[str], threshold: float = FUZZY_DEDUPE_THRESHOLD) -> List[str]:
    """
    Keep one representative per fuzzy-equivalent group of skill phrases.
    - Uses RapidFuzz token_set_ratio on normalized phrases.
    - Prefers the *shorter* representative (e.g., 'python' over 'using python').
    - Preserves relative order of first appearance of each group.
    """
    survivors: List[str] = []        # display strings we keep (original form)
    survivors_norm: List[str] = []   # normalized canonical for matching

    for raw in items:
        s = str(raw).strip()
        if not s:
            continue
        norm = _norm_phrase(s)
        if not norm:
            continue

        dup_idx = -1
        for i, prev_norm in enumerate(survivors_norm):
            # High when same bag-of-words or near-morphs (visualizing ~ visualization)
            score = rf_token_set_ratio(norm, prev_norm) / 100.0
            if score >= threshold or norm in prev_norm or prev_norm in norm:
                dup_idx = i
                break

        if dup_idx >= 0:
            # Prefer the more atomic (fewer info tokens) representative
            if _info_len(s) < _info_len(survivors[dup_idx]):
                survivors[dup_idx] = s
                survivors_norm[dup_idx] = norm
        else:
            survivors.append(s)
            survivors_norm.append(norm)

    # Optional: log how many we collapsed
    collapsed = len(items) - len(survivors)
    if collapsed > 0:
        logging.info("[final_checking] Fuzzy de-duped %d skill phrase(s) (threshold=%.2f)", collapsed, threshold)

    return survivors

# ----------------------------------------------------------------------
# Core Cleaning
# ----------------------------------------------------------------------
def _select_latest_batch(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Optional[str], int]:
    by_batch: Dict[Optional[str], List[Dict[str, Any]]] = {}
    for r in rows:
        by_batch.setdefault(r.get("batch_id"), []).append(r)

    non_null = [b for b in by_batch.keys() if b]
    if not non_null:
        return rows, None, len(by_batch)

    latest = sorted(non_null)[-1]
    return by_batch[latest], latest, len(by_batch)

def _dedupe_courses(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    best: Dict[Tuple[Any, Any], Dict[str, Any]] = {}
    for r in rows:
        key = (r.get("course_id"), r.get("course_code"))
        cur = best.get(key)
        if cur is None:
            best[key] = r
            continue

        def rank(x: Dict[str, Any]) -> Tuple[int, float, float]:
            return (
                _coerce_int(x.get("score")) or -1,
                _coerce_float(x.get("coverage")) or -1.0,
                _coerce_float(x.get("avg_similarity")) or -1.0,
            )

        if rank(r) > rank(cur):
            best[key] = r
    return list(best.values())

def _normalize_row_types(
    rows: List[Dict[str, Any]],
    *,
    code2id: Optional[Dict[str, Any]] = None
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    - Backfill course_id from course_code if missing (using code2id).
    - Normalize list-like fields (skills + matched_job_skill_ids).
    - Fuzzy de-duplicate skills (handles 'python' vs 'using python',
      'data visualization' vs 'visualizing data', etc.).
    - Coerce numeric fields and validate ranges.
    - Ensure course_id is non-empty.
    """
    problems: List[str] = []
    cleaned: List[Dict[str, Any]] = []

    for i, r in enumerate(rows):
        # Backfill course_id if possible
        if (r.get("course_id") in (None, "", 0)) and r.get("course_code") and code2id:
            cid = code2id.get(r["course_code"])
            if cid:
                r["course_id"] = cid

        # Normalize list-ish fields first
        for k in ("skills_taught", "skills_in_market", "matched_job_skill_ids"):
            r[k] = _as_list(r.get(k))

        # Fuzzy de-dupe skills lists (leave matched_job_skill_ids exact-deduped)
        r["skills_taught"] = _dedupe_skill_phrases(r["skills_taught"], FUZZY_DEDUPE_THRESHOLD)
        r["skills_in_market"] = _dedupe_skill_phrases(r["skills_in_market"], FUZZY_DEDUPE_THRESHOLD)

        # Required presence after backfill/normalization
        missing = [f for f in REQUIRED_FIELDS if f not in r]
        if missing:
            problems.append(f"row {i}: missing {missing}")
            continue

        if r.get("course_id") in (None, "", 0):
            problems.append(f"row {i}: empty course_id")
            continue

        cov = _coerce_float(r.get("coverage"))
        sim = _coerce_float(r.get("avg_similarity"))
        sc = _coerce_int(r.get("score"))

        if cov is None or not (0.0 <= cov <= 1.0):
            problems.append(f"row {i}: invalid coverage={r.get('coverage')}")
        if sim is None or not (0.0 <= sim <= 1.0):
            problems.append(f"row {i}: invalid avg_similarity={r.get('avg_similarity')}")
        if sc is None or not (0 <= sc <= 100):
            problems.append(f"row {i}: invalid score={r.get('score')}")

        if cov is not None and cov < MIN_COVERAGE:
            problems.append(f"row {i}: coverage below min ({cov:.3f} < {MIN_COVERAGE})")
        if sim is not None and sim < MIN_AVG_SIMILARITY:
            problems.append(f"row {i}: avg_similarity below min ({sim:.3f} < {MIN_AVG_SIMILARITY})")

        r["coverage"] = cov if cov is not None else 0.0
        r["avg_similarity"] = sim if sim is not None else 0.0
        r["score"] = sc if sc is not None else 0
        cleaned.append(r)

    return cleaned, problems

# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------
async def run_final_checks(
    report_data: Optional[List[Dict[str, Any]]] = None,
    *,
    strict: Optional[bool] = None,
    require_single_batch: bool = REQUIRE_SINGLE_BATCH,
    min_rows: int = MIN_ROWS,
    save_to_supabase: bool = True,
) -> Dict[str, Any]:
    strict = STRICT_GATE_DEFAULT if strict is None else strict

    # 1) Acquire rows
    data = report_data or await asyncio.to_thread(fetch_report_data_from_supabase)
    if not data:
        msg = "No report data available after evaluation."
        if strict:
            raise ValueError(msg)
        logging.warning(msg)
        return {"rows": []}

    rows = data if isinstance(data, list) else data.get("rows", [])
    if not isinstance(rows, list):
        msg = "Report data has no list of rows to validate."
        if strict:
            raise ValueError(msg)
        return {"rows": []}

    # 2) Select latest batch
    original_count = len(rows)
    rows, latest_batch, total_batches = _select_latest_batch(rows)

    if require_single_batch and total_batches > 1:
        logging.info("[final_checking] Multiple batches detected; using latest batch_id=%s", latest_batch)

    # 3) Deduplicate + normalize (with safety net for course_id)
    code2id = _get_code2id()
    deduped = _dedupe_courses(rows)
    cleaned, problems = _normalize_row_types(deduped, code2id=code2id)

    if len(cleaned) < min_rows:
        problems.append(f"Only {len(cleaned)} row(s) after cleaning; need at least {min_rows}.")

    if problems:
        msg = f"Final checks found {len(problems)} issue(s): {problems[:5]}..."
        if strict:
            raise ValueError(msg)
        logging.warning(msg)

    logging.info(
        "Final check summary: original=%d, cleaned=%d, batch_id=%s",
        original_count, len(cleaned), latest_batch,
    )

    # 4) Save cleaned rows into course_alignment_scores_clean
    if save_to_supabase and cleaned:
        try:
            if latest_batch:
                supabase.table("course_alignment_scores_clean").delete().eq("batch_id", latest_batch).execute()
            supabase.table("course_alignment_scores_clean").insert(cleaned).execute()
            logging.info("✅ Saved %d cleaned rows to course_alignment_scores_clean (batch_id=%s)", len(cleaned), latest_batch)
        except Exception as e:
            logging.error("❌ Failed to save cleaned rows to Supabase: %s", e)

    return {"rows": cleaned}

def run_final_checks_sync(report_data: Optional[List[Dict[str, Any]]] = None, **kwargs: Any) -> Dict[str, Any]:
    return asyncio.run(run_final_checks(report_data, **kwargs))
