# backend/app/services/evaluator.py
from __future__ import annotations

import os
import re
import joblib
import numpy as np
from uuid import uuid4
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from collections import Counter
from pathlib import Path

from sentence_transformers import SentenceTransformer
from rapidfuzz.fuzz import token_set_ratio

from ..core.supabase_client import supabase

# ---------------- Config / thresholds ----------------
SIM_THRESHOLD = float(os.getenv("SIM_THRESHOLD", 0.75))             # final gate after BOTH semantic+fuzzy
SEMANTIC_THRESHOLD = float(os.getenv("SEMANTIC_THRESHOLD", 0.75))   # cosine (0..1)
FUZZY_THRESHOLD   = float(os.getenv("FUZZY_THRESHOLD", 0.75))       # token_set_ratio (0..1)

# Default to app/ml/subject_success_model.pkl, override via env MODEL_BUNDLE_FILE
_DEFAULT_BUNDLE = (
    Path(__file__).resolve().parents[1]  # backend/app
    / "ml"
    / "subject_success_model.pkl"
)
MODEL_BUNDLE_FILE = os.getenv("MODEL_BUNDLE_FILE", str(_DEFAULT_BUNDLE))

# Turn ML scoring on/off (heuristic is always available)
USE_TRAINED_MODEL_SCORE = os.getenv("USE_TRAINED_MODEL_SCORE", "0").lower() in {"1", "true", "yes"}

# ---------------- Bundle / encoder selection ----------------
_bundle: Dict[str, Any] | None = None
_bundle_loaded = False
_embed_model_name: str | None = None

def _try_load_bundle():
    """Lazy-load the model bundle once; capture encoder name for parity."""
    global _bundle, _bundle_loaded, _embed_model_name
    if _bundle_loaded:
        return
    try:
        if os.path.exists(MODEL_BUNDLE_FILE):
            _bundle = joblib.load(MODEL_BUNDLE_FILE)
            # expected keys saved by train_model.py
            assert "embed_model_name" in _bundle and "cluster_centroids" in _bundle
            _embed_model_name = _bundle.get("embed_model_name")
            print(f"🧠 Loaded model bundle: {MODEL_BUNDLE_FILE} (embed_model={_embed_model_name})")
        else:
            print(f"ℹ️ Model bundle not found at {MODEL_BUNDLE_FILE} (using env/default encoder).")
    except Exception as e:
        print(f"⚠️ Failed to load model bundle {MODEL_BUNDLE_FILE}: {e}")
        _bundle = None
        _embed_model_name = None
    finally:
        _bundle_loaded = True

def _get_encoder() -> SentenceTransformer:
    """
    Encoder selection order:
    1) If bundle loaded, use bundle['embed_model_name']
    2) Else SKILL_ENCODER_MODEL env
    3) Else safe default: intfloat/e5-base-v2
    """
    _try_load_bundle()
    name = _embed_model_name or os.getenv("SKILL_ENCODER_MODEL") or "intfloat/e5-base-v2"
    print(f"🔤 Using sentence encoder: {name}")
    return SentenceTransformer(name)

_encoder = _get_encoder()

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
    NOTE: This normalization is used consistently for both job and course skills.
    """
    skills = _split_comma_skills(skills)
    normalized: List[str] = []
    for skill in skills:
        clean = skill.strip().lower()
        clean = re.sub(r"[^\w\s#.+]", "", clean)  # keep [A-Za-z0-9_], spaces, # . +
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
        return np.zeros((0, _encoder.get_sentence_embedding_dimension()), dtype=np.float32)
    return _encoder.encode(texts, convert_to_numpy=True, normalize_embeddings=True)

# ---------------- Data assembly ----------------
def _fetch_courses_map() -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
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
    print("📦 Fetching ALL course_skills rows...")
    rows = supabase.table("course_skills").select("*").execute().data or []

    id2course, code2id = _fetch_courses_map()

    by_course: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        cid = r.get("course_id")
        if not cid:
            code = (r.get("course_code") or "").strip()
            if code:
                cid = code2id.get(code)
        if not cid:
            continue
        by_course.setdefault(cid, []).append(r)

    combined: List[Dict[str, Any]] = []
    for cid, items in by_course.items():
        items_sorted = sorted(items, key=lambda x: x.get("date_extracted_course") or "", reverse=True)
        rep = items_sorted[0]

        meta = id2course.get(cid, {})
        course_code = meta.get("course_code") or rep.get("course_code") or ""
        course_title = meta.get("course_title") or rep.get("course_title") or ""

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

# ---------------- Persistence: unmatched job skills ----------------
def _upsert_skill_gap_counts(
    unmatched_job_skill_norms: List[str],
    batch_id: str,
    calculated_at_iso: str,
) -> None:
    counts = Counter([s for s in unmatched_job_skill_norms if s and s.strip()])
    if not counts:
        print("ℹ️ No unmatched job skills in this batch.")
        return

    rows = [
        {
            "batch_id": batch_id,
            "skill_norm": skill,
            "count": int(cnt),
            "calculated_at": calculated_at_iso,
        }
        for skill, cnt in counts.items()
    ]
    try:
        supabase.table("skill_gap_counts").upsert(
            rows,
            on_conflict="batch_id,skill_norm",
            ignore_duplicates=False,
        ).execute()
        print(f"✅ Upserted {len(rows)} skill_gap_counts rows for batch {batch_id}")
    except Exception as e:
        print(f"❌ Failed to upsert skill_gap_counts for batch {batch_id}: {e}")

# ---------------- (Optional) ML score helpers ----------------
def _topk_mean(a: np.ndarray, k=3, axis=-1) -> np.ndarray:
    if a.size == 0:
        return np.array([], dtype=np.float32)
    k = max(1, min(k, a.shape[axis]))
    idx = np.argpartition(a, kth=-k, axis=axis)
    topk_idx = np.take(idx, indices=range(a.shape[axis]-k, a.shape[axis]), axis=axis)
    topk_vals = np.take_along_axis(a, topk_idx, axis=axis)
    return topk_vals.mean(axis=axis)

def _summarize_course_vs_centroids(course_skills: List[str], centroids: np.ndarray) -> np.ndarray:
    if not course_skills or centroids.size == 0:
        return np.array([0, 0, 0, 0], dtype=np.float32)
    cs_emb = _encode_norm(course_skills)
    sims = cs_emb @ centroids.T
    max_per_skill = sims.max(axis=1)
    max_per_cluster = sims.max(axis=0)
    return np.array([
        float(max_per_skill.mean()),
        float((max_per_skill > 0.60).mean()),
        float(max_per_cluster.mean()),
        float(max_per_cluster.std()),
    ], dtype=np.float32)

def _predict_ml_score_if_enabled(course_skills: List[str], job_skill_pairs: List[str]) -> float | None:
    """
    Use the trained model bundle to predict a score if enabled and bundle present.
    Demand-weighted pooling is applied via bundle['cluster_freq'] for perfect train/infer parity.
    """
    if not (USE_TRAINED_MODEL_SCORE and _bundle):
        return None
    try:
        centroids: np.ndarray = _bundle["cluster_centroids"]          # [C, D]
        topk = int(_bundle.get("topk", 3))
        cluster_freq: np.ndarray | None = _bundle.get("cluster_freq") # [C] or None

        cs_emb = _encode_norm(course_skills)
        if cs_emb.size == 0 or centroids.size == 0:
            return 0.0

        sims = cs_emb @ centroids.T                        # [S, C]
        pooled = _topk_mean(sims, k=topk, axis=0)          # [C]

        # Apply demand weighting as used during training
        if isinstance(cluster_freq, np.ndarray) and cluster_freq.shape[0] == centroids.shape[0]:
            pooled = pooled * (0.5 + 0.5 * cluster_freq)

        summary = _summarize_course_vs_centroids(course_skills, centroids)  # [4]
        feat = np.concatenate([pooled, summary], axis=0)[None, :]  # [1, C+4]

        raw = _bundle["model"].predict(feat)
        pred = _bundle["calibrator"].predict(raw)
        return float(pred[0])
    except Exception as e:
        print(f"⚠️ ML score prediction failed, falling back to heuristic: {e}")
        return None

# ---------------- Scoring (DB -> DB) ----------------
def compute_subject_scores_and_save() -> None:
    """
    Bidirectional, non-greedy coverage with fuzzy+semantic gates.
    - For scoring:
        * Heuristic score = avg(best final per course skill) × coverage × 100
        * If USE_TRAINED_MODEL_SCORE=1 and bundle present → use ML score instead.
    - For gaps:
        * Every JOB-SKILL OCCURRENCE is marked covered if ANY course skill passes the final threshold.
        * Uncovered occurrences are aggregated to skill_gap_counts.
    """
    job_groups = get_combined_job_skills()
    course_groups = get_combined_course_skills()

    # Flatten job skill occurrences
    job_skill_pairs: List[str] = []
    job_skill_rep_id_lookup: List[Any] = []
    for g in job_groups:
        rep_id = g.get("rep_job_skill_id")
        for s in g["skills"]:
            job_skill_pairs.append(s)          # normalized job skill token
            job_skill_rep_id_lookup.append(rep_id)

    if not job_skill_pairs:
        print("❌ No job market skills found.")
        return

    print(f"📦 Encoding {len(job_skill_pairs)} job market skills (combined across job_ids)...")
    job_embeddings = _encode_norm(job_skill_pairs)

    batch_id = str(uuid4())
    now_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    matched_job_occurrence = np.zeros(len(job_skill_pairs), dtype=bool)  # ← for gap

    for course in course_groups:
        course_id = course["course_id"]
        course_code = course.get("course_code", "")
        course_title = course.get("course_title", "")
        course_skills = course.get("skills", [])

        if not course_skills:
            print(f"⚠️ No course skills for {course_code or course_id}. Skipping.")
            continue

        # Encode course skills and compute cosine similarities [S, J]
        course_embeddings = _encode_norm(course_skills)
        cosine_matrix = course_embeddings @ job_embeddings.T

        matched_market_skills: List[str] = []
        matched_job_skill_ids: set[str] = set()

        best_finals_per_course_skill: List[float] = []
        course_skill_matched = np.zeros(len(course_skills), dtype=bool)

        for i, course_skill in enumerate(course_skills):
            sims = cosine_matrix[i]
            cand_idx = np.where(sims >= SEMANTIC_THRESHOLD)[0]
            if cand_idx.size == 0:
                continue

            best_final_for_i = 0.0
            matched_any_for_i = False

            for j in cand_idx:
                sem = float(sims[j])
                job_skill = job_skill_pairs[j]
                fuzzy = token_set_ratio(course_skill, job_skill) / 100.0
                if fuzzy < FUZZY_THRESHOLD:
                    continue

                final = 0.7 * sem + 0.3 * fuzzy
                if final >= SIM_THRESHOLD:
                    matched_any_for_i = True
                    matched_job_occurrence[j] = True      # mark job occurrence covered
                    matched_market_skills.append(job_skill)

                    rep_job_skill_id = job_skill_rep_id_lookup[j]
                    if rep_job_skill_id:
                        matched_job_skill_ids.add(str(rep_job_skill_id))

                    if final > best_final_for_i:
                        best_final_for_i = final

            if matched_any_for_i:
                course_skill_matched[i] = True
                best_finals_per_course_skill.append(best_final_for_i)

        matched_course_skills = int(course_skill_matched.sum())
        total_course_skills = len(course_skills)
        coverage = (matched_course_skills / total_course_skills) if total_course_skills else 0.0
        avg_similarity = float(np.mean(best_finals_per_course_skill)) if best_finals_per_course_skill else 0.0
        heuristic_score = int(np.clip(avg_similarity * coverage * 100.0, 0.0, 100.0))

        # Optionally replace with ML score from your trained bundle (uses demand-weighted pooling)
        final_score = heuristic_score
        if USE_TRAINED_MODEL_SCORE and _bundle:
            ml_score = _predict_ml_score_if_enabled(course_skills, job_skill_pairs)
            if ml_score is not None:
                final_score = int(np.clip(ml_score, 0.0, 100.0))

        # Prepare values for insert
        matched_ids_literal = "{" + ", ".join(f'"{v}"' for v in sorted(matched_job_skill_ids)) + "}"

        payload = {
            "batch_id": batch_id,
            "course_id": course_id,
            "course_code": course_code,
            "course_title": course_title,
            "skills_taught": ", ".join(course_skills),
            "skills_in_market": ", ".join(sorted(set(matched_market_skills))),
            "matched_job_skill_ids": matched_ids_literal,
            "coverage": round(coverage, 3),
            "avg_similarity": round(avg_similarity, 3),
            "score": final_score,  # heuristic or ML depending on flag/bundle
            "calculated_at": now_utc,
        }

        try:
            supabase.table("course_alignment_scores").insert(payload).execute()
            print(f"✅ Saved: {course_code or course_id} - score={final_score} (heuristic={heuristic_score})")
        except Exception as e:
            print(f"❌ Insert failed for {course_code or course_id}: {e}")

    # --------- Aggregate unmatched job skills across the ENTIRE batch ----------
    unmatched_occ_indices = np.where(~matched_job_occurrence)[0]
    unmatched_job_skill_norms = [job_skill_pairs[i] for i in unmatched_occ_indices]

    print(f"🧩 Unmatched job-skill occurrences: {len(unmatched_occ_indices)} "
          f"(unique skills: {len(set(unmatched_job_skill_norms))})")

    _upsert_skill_gap_counts(
        unmatched_job_skill_norms=unmatched_job_skill_norms,
        batch_id=batch_id,
        calculated_at_iso=now_utc,
    )

# ---------------- Pure function (for ML/tests) ----------------
def compute_subject_scores(subject_skills_map: Dict[str, Any], job_skill_tree: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Pure scoring variant used for ML/testing; returns a list of dicts (not DB writes).
    Uses the same encoder chosen above to avoid train/infer drift.
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

            best_finals_per_course_skill: List[float] = []
            for i, course_skill in enumerate(course_skills):
                sims = cosine_matrix[i]
                cand_idx = np.where(sims >= SEMANTIC_THRESHOLD)[0]
                if cand_idx.size == 0:
                    continue
                best_final = 0.0
                for j in cand_idx:
                    sem = float(sims[j])
                    job_skill = job_skill_cleaned[j]
                    fuzzy = token_set_ratio(course_skill, job_skill) / 100.0
                    if fuzzy < FUZZY_THRESHOLD:
                        continue
                    final = 0.7 * sem + 0.3 * fuzzy
                    if final >= SIM_THRESHOLD and final > best_final:
                        best_final = final
                if best_final > 0:
                    best_finals_per_course_skill.append(best_final)

            matched = len(best_finals_per_course_skill)
            total = len(course_skills)
            coverage = matched / total if total else 0.0
            avg_sim = float(np.mean(best_finals_per_course_skill)) if best_finals_per_course_skill else 0.0
            raw_score = avg_sim * coverage * 100.0

            scored_subjects.append({
                "course": course_code,
                "skills_taught": course_skills,
                "coverage": round(coverage, 3),
                "avg_similarity": round(avg_sim, 3),
                "score": int(np.clip(raw_score, 0.0, 100.0)),
            })
        except Exception as e:
            print(f"❌ Failed to score {course_code}: {e}")

    return scored_subjects


if __name__ == "__main__":
    compute_subject_scores_and_save()
