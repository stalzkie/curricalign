# backend/app/services/evaluator.py
from __future__ import annotations

import re
import numpy as np
from uuid import uuid4
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from sentence_transformers import SentenceTransformer
from rapidfuzz.fuzz import token_set_ratio

from ..core.supabase_client import supabase

# ---------------- Config / thresholds ----------------
SIM_THRESHOLD = 0.75         # gate after BOTH semantic+fuzzy pass
SEMANTIC_THRESHOLD = 0.75    # cosine (0..1)
FUZZY_THRESHOLD   = 0.75     # token_set_ratio (0..1)

# Use a model different from train_model.py to reduce label leakage
_label_encoder = SentenceTransformer("intfloat/e5-base-v2")

# ---------------- Helpers ----------------
def _split_comma_skills(val: Any) -> List[str]:
    """Accept list or comma-separated string; return list of stripped strings."""
    if val is None:
        return []
    if isinstance(val, list):
        return [s for s in (x.strip() for x in val) if s]
    if isinstance(val, str):
        return [s for s in (x.strip() for x in val.split(",")) if s]
    return []

def normalize_skills(skills: Any) -> List[str]:
    """
    Normalize skills into consistent lowercased tokens; keep phrases (no token explosion).
    Preserve characters that matter to tech names (#, +, .).
    """
    skills = _split_comma_skills(skills)
    normalized: List[str] = []
    for skill in skills:
        clean = skill.strip().lower()
        clean = re.sub(r"[^\w\s#.+]", "", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        if clean:
            normalized.append(clean)
    # de-dupe, preserve order
    seen = set()
    out: List[str] = []
    for s in normalized:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out

def _encode_norm(texts: List[str]) -> np.ndarray:
    """Encode with unit-length normalization for stable cosine."""
    if not texts:
        return np.zeros((0, _label_encoder.get_sentence_embedding_dimension()), dtype=np.float32)
    return _label_encoder.encode(texts, convert_to_numpy=True, normalize_embeddings=True)

# ---------------- Data assembly ----------------
def _fetch_courses_map() -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    """
    Build lookups from the courses table (PK is course_id).

    Returns:
      id2course: {course_id: {"course_code":..., "course_title":...}}
      code2id:   {course_code: course_id}
    """
    rows = (
        supabase.table("courses")
        .select("course_id, course_code, course_title")
        .execute()
        .data
        or []
    )
    id2course: Dict[str, Dict[str, Any]] = {}
    code2id: Dict[str, str] = {}
    for r in rows:
        cid = r.get("course_id")
        code = r.get("course_code")
        title = r.get("course_title")
        if cid and code:
            id2course[cid] = {"course_code": code, "course_title": title}
            code2id[code] = cid
    return id2course, code2id

def get_combined_job_skills() -> List[Dict[str, Any]]:
    """
    Fetch ALL job_skills rows, group by job_id, combine & dedupe skills.
    Choose the latest row per job_id as representative to carry job_skill_id.
    """
    print("📦 Fetching ALL job_skills rows...")
    rows = supabase.table("job_skills").select("*").execute().data or []

    by_job: Dict[Any, List[Dict[str, Any]]] = {}
    for r in rows:
        jid = r.get("job_id")
        if jid is None:
            continue
        by_job.setdefault(jid, []).append(r)

    combined: List[Dict[str, Any]] = []
    for jid, items in by_job.items():
        items_sorted = sorted(items, key=lambda x: x.get("date_extracted_jobs") or "", reverse=True)
        rep = items_sorted[0]
        all_sk: List[str] = []
        for it in items:
            all_sk.extend(_split_comma_skills(it.get("job_skills")))
        merged = normalize_skills(all_sk)
        combined.append({
            "job_id": jid,
            "skills": merged,
            "rep_job_skill_id": rep.get("job_skill_id"),
        })

    print(f"🧮 Combined job_ids: {len(combined)}")
    return combined

def get_combined_course_skills() -> List[Dict[str, Any]]:
    """
    Fetch ALL course_skills rows and produce one combined record per course_id.
    We resolve course_id robustly:
      - Prefer course_skills.course_id
      - Else infer via course_code → courses.course_id
    We also prefer canonical course_code/title from courses, falling back to the row if missing.

    Returns list of:
      { course_id, course_code, course_title, skills }
    """
    print("📦 Fetching ALL course_skills rows...")
    rows = supabase.table("course_skills").select("*").execute().data or []

    id2course, code2id = _fetch_courses_map()

    by_course: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        # resolve course_id
        cid = r.get("course_id")
        if not cid:
            code = (r.get("course_code") or "").strip()
            if code:
                cid = code2id.get(code)
        if not cid:
            # cannot resolve this record; skip to avoid failing final checks
            continue
        by_course.setdefault(cid, []).append(r)

    combined: List[Dict[str, Any]] = []
    for cid, items in by_course.items():
        # latest row in course_skills for fallback metadata
        items_sorted = sorted(items, key=lambda x: x.get("date_extracted_course") or "", reverse=True)
        rep = items_sorted[0]

        # prefer canonical metadata from courses; fallback to rep row
        meta = id2course.get(cid, {})
        course_code = meta.get("course_code") or rep.get("course_code") or ""
        course_title = meta.get("course_title") or rep.get("course_title") or ""

        # merge + normalize skills across all rows of this course_id
        all_sk: List[str] = []
        for it in items:
            all_sk.extend(_split_comma_skills(it.get("course_skills")))
        merged = normalize_skills(all_sk)

        combined.append({
            "course_id": cid,
            "course_code": course_code,
            "course_title": course_title,
            "skills": merged,
        })

    print(f"🧮 Combined courses (with resolved course_id): {len(combined)}")
    return combined

# ---------------- Scoring (DB -> DB) ----------------
def compute_subject_scores_and_save() -> None:
    """
    1) Build combined job + course skill sets.
    2) Encode and score with semantic + fuzzy gates.
    3) Insert rows into course_alignment_scores with REQUIRED fields:
       course_id, course_code, course_title, coverage, avg_similarity, score (+ extras).
    """
    job_groups = get_combined_job_skills()
    course_groups = get_combined_course_skills()

    # Flatten job skill space (distinct skills per job, but keep a rep id per job_id)
    job_skill_pairs: List[str] = []
    job_skill_rep_id_lookup: List[Any] = []
    for g in job_groups:
        rep_id = g.get("rep_job_skill_id")
        for s in g["skills"]:
            job_skill_pairs.append(s)
            job_skill_rep_id_lookup.append(rep_id)

    if not job_skill_pairs:
        print("❌ No job market skills found.")
        return

    print(f"📦 Encoding {len(job_skill_pairs)} job market skills (combined across job_ids)...")
    job_embeddings = _encode_norm(job_skill_pairs)

    batch_id = str(uuid4())
    now_utc = datetime.now(timezone.utc).isoformat()

    for course in course_groups:
        course_id = course["course_id"]
        course_code = course.get("course_code", "")
        course_title = course.get("course_title", "")
        course_skills = course.get("skills", [])

        if not course_skills:
            print(f"⚠️ No course skills for {course_code or course_id}. Skipping.")
            continue

        # Encode course skills
        course_embeddings = _encode_norm(course_skills)
        cosine_matrix = course_embeddings @ job_embeddings.T  # [S, J]

        matched_market_skills: List[str] = []
        matched_job_skill_ids: set[str] = set()
        match_scores: List[float] = []

        for i, course_skill in enumerate(course_skills):
            similarities = cosine_matrix[i]
            max_index = int(np.argmax(similarities))
            max_score = float(similarities[max_index])  # semantic cosine in [0,1]
            job_skill = job_skill_pairs[max_index]
            rep_job_skill_id = job_skill_rep_id_lookup[max_index]

            fuzzy_score = token_set_ratio(course_skill, job_skill) / 100.0
            if max_score >= SEMANTIC_THRESHOLD and fuzzy_score >= FUZZY_THRESHOLD:
                final_score = (0.7 * max_score + 0.3 * fuzzy_score)
                if final_score >= SIM_THRESHOLD:
                    matched_market_skills.append(job_skill)
                    if rep_job_skill_id:
                        matched_job_skill_ids.add(str(rep_job_skill_id))
                    match_scores.append(final_score)

        matched = len(match_scores)
        total_skills = len(course_skills)
        coverage = matched / total_skills if total_skills else 0.0
        avg_similarity = float(np.mean(match_scores)) if match_scores else 0.0
        raw_score = avg_similarity * coverage * 100.0
        score = int(np.clip(raw_score, 0.0, 100.0))

        if score == 0:
            print(f"📉 {course_code or course_id}: matched {matched}/{total_skills} (coverage={coverage:.2f}) → score=0")
        else:
            print(f"📊 {course_code or course_id}: matched {matched}/{total_skills} → coverage={coverage:.2f}, sim={avg_similarity:.2f}, score={score}")

        # Prepare values for insert
        # NOTE: If your Postgres column 'matched_job_skill_ids' is text[],
        # the safest cross-client way is to send it as a Postgres array literal string.
        # UUID-like strings are quoted to be safe in array literal.
        matched_ids_literal = "{" + ", ".join(f'"{v}"' for v in sorted(matched_job_skill_ids)) + "}"

        payload = {
            "batch_id": batch_id,
            "course_id": course_id,                      # ✅ REQUIRED by final_checking
            "course_code": course_code,
            "course_title": course_title,
            "skills_taught": ", ".join(course_skills),   # keep as text; change to list if your column is text[]
            "skills_in_market": ", ".join(matched_market_skills),
            "matched_job_skill_ids": matched_ids_literal,
            "coverage": round(coverage, 3),
            "avg_similarity": round(avg_similarity, 3),
            "score": score,
            "calculated_at": now_utc,
        }

        try:
            supabase.table("course_alignment_scores").insert(payload).execute()
            print(f"✅ Saved: {course_code or course_id} - {score}")
        except Exception as e:
            print(f"❌ Insert failed for {course_code or course_id}: {e}")

# ---------------- Pure function (for ML/tests) ----------------
def compute_subject_scores(subject_skills_map: Dict[str, Any], job_skill_tree: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Pure scoring variant used for ML/testing; returns a list of dicts (not DB writes).
    """
    job_skill_list = list(job_skill_tree.keys())
    job_skill_cleaned = normalize_skills(job_skill_list)

    if not job_skill_cleaned:
        print("❌ No cleaned job skills available.")
        return []

    job_embeddings = _encode_norm(job_skill_cleaned)

    scored_subjects: List[Dict[str, Any]] = []
    for course_code, raw_skills in subject_skills_map.items():
        course_skills = normalize_skills(raw_skills)
        if not course_skills:
            continue

        try:
            course_embeddings = _encode_norm(course_skills)
            cosine_matrix = course_embeddings @ job_embeddings.T  # [S, J]

            matched_market_skills: List[str] = []
            match_scores: List[float] = []

            for i, course_skill in enumerate(course_skills):
                similarities = cosine_matrix[i]
                max_index = int(np.argmax(similarities))
                max_score = float(similarities[max_index])
                job_skill = job_skill_cleaned[max_index]

                fuzzy_score = token_set_ratio(course_skill, job_skill) / 100.0
                if max_score >= SEMANTIC_THRESHOLD and fuzzy_score >= FUZZY_THRESHOLD:
                    final_score = (0.7 * max_score + 0.3 * fuzzy_score)
                    if final_score >= SIM_THRESHOLD:
                        matched_market_skills.append(job_skill)
                        match_scores.append(final_score)

            matched = len(match_scores)
            total = len(course_skills)
            coverage = matched / total if total else 0.0
            avg_sim = float(np.mean(match_scores)) if match_scores else 0.0
            raw_score = avg_sim * coverage * 100.0

            scored_subjects.append({
                "course": course_code,
                "skills_taught": course_skills,
                "skills_in_market": matched_market_skills,
                "coverage": round(coverage, 3),
                "avg_similarity": round(avg_sim, 3),
                "score": int(np.clip(raw_score, 0.0, 100.0)),
            })

        except Exception as e:
            print(f"❌ Failed to score {course_code}: {e}")

    return scored_subjects

if __name__ == "__main__":
    compute_subject_scores_and_save()
