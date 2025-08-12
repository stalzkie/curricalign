import os
import re
import numpy as np
from uuid import uuid4
from datetime import datetime, timezone
from sentence_transformers import SentenceTransformer, util
from rapidfuzz.fuzz import token_set_ratio
from ..core.supabase_client import supabase

# ---- thresholds ----
SIM_THRESHOLD = 0.75         # used only for reporting/averaging after BOTH gates pass
SEMANTIC_THRESHOLD = 0.75     # new: cosine gate (0..1)
FUZZY_THRESHOLD = 0.75        # new: token_set_ratio gate (0..1)

# Use a DIFFERENT model than train_model.py to reduce label leakage
# (trainer uses all-MiniLM-L6-v2). Keep this local to evaluator.
_label_encoder = SentenceTransformer("intfloat/e5-base-v2")

# ----------------------------
# Helpers for normalization
# ----------------------------

def _split_comma_skills(val):
    """Accept list or comma-separated string; return list of stripped strings."""
    if val is None:
        return []
    if isinstance(val, list):
        return [s for s in (x.strip() for x in val) if s]
    if isinstance(val, str):
        return [s for s in (x.strip() for x in val.split(",")) if s]
    return []

def normalize_skills(skills):
    """
    Normalize skills into consistent lowercased tokens.
    Input can be list or comma-separated string.
    """
    skills = _split_comma_skills(skills)
    normalized = []
    for skill in skills:
        clean = skill.strip().lower()
        # Keep #, +, . (e.g., c#, c++, asp.net) and remove other punctuation
        clean = re.sub(r"[^\w\s#.+]", "", clean)
        clean = re.sub(r"\s+", " ", clean).strip()
        # Keep the phrase intact (do not explode into single tokens)
        if clean:
            normalized.append(clean)
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for s in normalized:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique

def hybrid_similarity(bert_score, course_skill, job_skill):
    fuzzy_score = token_set_ratio(course_skill, job_skill) / 100
    return (0.7 * bert_score + 0.3 * fuzzy_score)

def _encode_norm(texts):
    """Encode with unit-length normalization for stable cosine."""
    if not texts:
        return np.zeros((0, _label_encoder.get_sentence_embedding_dimension()), dtype=np.float32)
    return _label_encoder.encode(texts, convert_to_numpy=True, normalize_embeddings=True)

# ----------------------------
# Combine ALL rows by id
# ----------------------------

def get_combined_job_skills():
    """
    Fetch ALL job_skills rows, group by job_id, combine & dedupe skills.
    Also pick the latest row per job_id as the representative to carry job_skill_id.
    Returns a list of dicts:
      { job_id, skills: [..combined..], rep_job_skill_id }
    """
    print("📦 Fetching ALL job_skills rows...")
    rows = supabase.table("job_skills").select("*").execute().data or []

    # Group rows by job_id
    by_job = {}
    for r in rows:
        jid = r.get("job_id")
        if jid is None:
            continue
        by_job.setdefault(jid, []).append(r)

    combined = []
    for jid, items in by_job.items():
        # Sort desc by date to pick a representative row (latest)
        items_sorted = sorted(
            items,
            key=lambda x: x.get("date_extracted_jobs") or "",
            reverse=True
        )
        rep = items_sorted[0]  # latest row for representative job_skill_id
        # Combine all skills across rows with dedupe+normalize
        all_sk = []
        for it in items:
            all_sk.extend(_split_comma_skills(it.get("job_skills")))
        merged_skills = normalize_skills(all_sk)
        combined.append({
            "job_id": jid,
            "skills": merged_skills,
            "rep_job_skill_id": rep.get("job_skill_id")
        })

    print(f"🧮 Combined job_ids: {len(combined)}")
    return combined

def get_combined_course_skills():
    """
    Fetch ALL course_skills rows, group by course_id, combine & dedupe skills.
    Returns a list of dicts:
      { course_id, course_code, course_title, skills: [..combined..] }
    Metadata (code/title/description) is taken from the latest row.
    """
    print("📦 Fetching ALL course_skills rows...")
    rows = supabase.table("course_skills").select("*").execute().data or []

    by_course = {}
    for r in rows:
        cid = r.get("course_id")
        if cid is None:
            continue
        by_course.setdefault(cid, []).append(r)

    combined = []
    for cid, items in by_course.items():
        items_sorted = sorted(
            items,
            key=lambda x: x.get("date_extracted_course") or "",
            reverse=True
        )
        rep = items_sorted[0]  # latest to carry code/title/desc
        all_sk = []
        for it in items:
            all_sk.extend(_split_comma_skills(it.get("course_skills")))
        merged_skills = normalize_skills(all_sk)
        combined.append({
            "course_id": cid,
            "course_code": rep.get("course_code", ""),
            "course_title": rep.get("course_title", ""),
            "skills": merged_skills
        })

    print(f"🧮 Combined course_ids: {len(combined)}")
    return combined

# ----------------------------
# Main scoring (DB → DB)
# ----------------------------

def compute_subject_scores_and_save():
    # Build combined sets
    job_groups = get_combined_job_skills()
    course_groups = get_combined_course_skills()

    # Flatten job skill space for encoding (one row per job_id, distinct skills per job)
    job_skill_pairs = []
    job_skill_rep_id_lookup = []  # use representative job_skill_id per job_id
    rep_id_per_job = {}  # job_id -> rep_job_skill_id
    for g in job_groups:
        rep_id_per_job[g["job_id"]] = g.get("rep_job_skill_id")
        for s in g["skills"]:
            job_skill_pairs.append(s)
            # store the representative job_skill_id for this job_id
            job_skill_rep_id_lookup.append(g.get("rep_job_skill_id"))

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
            print(f"⚠️ No course skills for {course_code}. Skipping.")
            continue

        course_embeddings = _encode_norm(course_skills)
        # cosine sim on normalized embeddings -> dot product
        cosine_matrix = course_embeddings @ job_embeddings.T  # shape [S, J]

        matched_market_skills = []
        matched_job_skill_ids = set()
        match_scores = []

        for i, course_skill in enumerate(course_skills):
            similarities = cosine_matrix[i]
            max_index = np.argmax(similarities)
            max_score = float(similarities[max_index])  # semantic cosine in [0,1]
            job_skill = job_skill_pairs[max_index]
            rep_job_skill_id = job_skill_rep_id_lookup[max_index]

            # Gate by BOTH thresholds
            fuzzy_score = token_set_ratio(course_skill, job_skill) / 100.0
            if max_score >= SEMANTIC_THRESHOLD and fuzzy_score >= FUZZY_THRESHOLD:
                final_score = (0.7 * max_score + 0.3 * fuzzy_score)
                # Optionally also check SIM_THRESHOLD on the hybrid score
                if final_score >= SIM_THRESHOLD:
                    matched_market_skills.append(job_skill)
                    if rep_job_skill_id:
                        matched_job_skill_ids.add(str(rep_job_skill_id))
                    match_scores.append(final_score)
            # else: no match for this course_skill

        matched = len(match_scores)
        total_skills = len(course_skills)
        coverage = matched / total_skills if total_skills else 0.0
        avg_similarity = float(np.mean(match_scores)) if match_scores else 0.0
        raw_score = avg_similarity * coverage * 100.0
        score = int(np.clip(raw_score, 0.0, 100.0))

        if score == 0:
            print(f"📉 {course_code}: matched {matched}/{total_skills} "
                  f"(coverage={coverage:.2f}) → score=0")
        else:
            print(f"📊 {course_code}: matched {matched}/{total_skills} "
                  f"→ coverage={coverage:.2f}, sim={avg_similarity:.2f}, score={score}")

        try:
            supabase.table("course_alignment_scores").insert({
                "batch_id": batch_id,
                "course_id": course_id,
                "course_code": course_code,
                "course_title": course_title,
                "skills_taught": ", ".join(course_skills),
                "skills_in_market": ", ".join(matched_market_skills),
                # Keep your existing column but store the representative job_skill_id per job match
                "matched_job_skill_ids": "{" + ", ".join(sorted(matched_job_skill_ids)) + "}",
                "coverage": round(coverage, 3),
                "avg_similarity": round(avg_similarity, 3),
                "score": score,
                "calculated_at": now_utc
            }).execute()
            print(f"✅ Saved: {course_code} - {score}")
        except Exception as e:
            print(f"❌ Insert failed for {course_code}: {e}")

# ----------------------------
# Pure function variant (for ML)
# ----------------------------

def compute_subject_scores(subject_skills_map, job_skill_tree):
    # job_skill_tree is expected as {skill: freq} or similar; use its keys
    job_skill_list = list(job_skill_tree.keys())
    job_skill_cleaned = normalize_skills(job_skill_list)

    if not job_skill_cleaned:
        print("❌ No cleaned job skills available.")
        return []

    job_embeddings = _encode_norm(job_skill_cleaned)

    scored_subjects = []
    for course_code, raw_skills in subject_skills_map.items():
        course_skills = normalize_skills(raw_skills)
        if not course_skills:
            continue

        try:
            course_embeddings = _encode_norm(course_skills)
            cosine_matrix = course_embeddings @ job_embeddings.T  # [S, J]

            matched_market_skills = []
            match_scores = []

            for i, course_skill in enumerate(course_skills):
                similarities = cosine_matrix[i]
                max_index = np.argmax(similarities)
                max_score = float(similarities[max_index])  # semantic cosine
                job_skill = job_skill_cleaned[max_index]

                # BOTH gates first
                fuzzy_score = token_set_ratio(course_skill, job_skill) / 100.0
                if max_score >= SEMANTIC_THRESHOLD and fuzzy_score >= FUZZY_THRESHOLD:
                    final_score = (0.7 * max_score + 0.3 * fuzzy_score)
                    if final_score >= SIM_THRESHOLD:
                        matched_market_skills.append(job_skill)
                        match_scores.append(final_score)
                # else: not matched

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
                "score": int(np.clip(raw_score, 0.0, 100.0))
            })

        except Exception as e:
            print(f"❌ Failed to score {course_code}: {e}")

    return scored_subjects

if __name__ == "__main__":
    compute_subject_scores_and_save()
