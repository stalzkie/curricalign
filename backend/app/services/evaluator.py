import os
import numpy as np
from uuid import uuid4
from datetime import datetime, timezone
from sentence_transformers import SentenceTransformer, util
from rapidfuzz.fuzz import token_set_ratio
from ..core.supabase_client import supabase

SIM_THRESHOLD = 0.65
bert_model = SentenceTransformer("all-MiniLM-L6-v2")

def normalize_skills(skills_str):
    if not isinstance(skills_str, str):
        return []
    return [s.strip().lower() for s in skills_str.split(",") if s.strip()]

def hybrid_similarity(bert_score, course_skill, job_skill):
    fuzzy_score = token_set_ratio(course_skill, job_skill) / 100
    return (0.7 * bert_score + 0.3 * fuzzy_score)

def get_latest_supabase_skills():
    print("📦 Fetching latest course and job skills...")

    job_rows = supabase.table("job_skills") \
        .select("*") \
        .order("date_extracted_jobs", desc=True) \
        .execute().data

    latest_job_skills = {}
    for row in job_rows:
        job_id = row.get("job_id")
        if job_id not in latest_job_skills:
            latest_job_skills[job_id] = row

    course_rows = supabase.table("course_skills") \
        .select("*") \
        .order("date_extracted_course", desc=True) \
        .execute().data

    latest_course_skills = {}
    for row in course_rows:
        course_id = row.get("course_id")
        if course_id not in latest_course_skills:
            latest_course_skills[course_id] = row

    return list(latest_job_skills.values()), list(latest_course_skills.values())

def compute_subject_scores_and_save():
    job_rows, course_rows = get_latest_supabase_skills()

    job_skill_pairs = []
    job_skill_id_lookup = []

    for row in job_rows:
        skills = normalize_skills(row["job_skills"])
        for skill in skills:
            job_skill_pairs.append(skill)
            job_skill_id_lookup.append(row["job_skill_id"])

    if not job_skill_pairs:
        print("❌ No job market skills found.")
        return

    print(f"📦 Encoding {len(job_skill_pairs)} job market skills...")
    job_embeddings = bert_model.encode(job_skill_pairs, convert_to_tensor=True)

    # ✅ Generate a single batch_id for this run
    batch_id = str(uuid4())
    now_utc = datetime.now(timezone.utc).isoformat()

    for course in course_rows:
        course_id = course["course_id"]
        course_code = course.get("course_code", "")
        course_title = course.get("course_title", "")
        course_skills = normalize_skills(course.get("course_skills", ""))

        if not course_skills:
            print(f"⚠️ No course skills for {course_code}. Skipping.")
            continue

        course_embeddings = bert_model.encode(course_skills, convert_to_tensor=True)
        cosine_matrix = util.cos_sim(course_embeddings, job_embeddings).cpu().numpy()

        matched_skills = []
        matched_market_skills = []
        matched_job_ids = set()
        match_scores = []

        for i, course_skill in enumerate(course_skills):
            similarities = cosine_matrix[i]
            max_index = np.argmax(similarities)
            max_score = similarities[max_index]
            job_skill = job_skill_pairs[max_index]
            job_skill_id = job_skill_id_lookup[max_index]

            final_score = hybrid_similarity(max_score, course_skill, job_skill)

            if final_score >= SIM_THRESHOLD:
                matched_skills.append(course_skill)
                matched_market_skills.append(job_skill)
                matched_job_ids.add(str(job_skill_id))
                match_scores.append(final_score)

        matched = len(matched_skills)
        total_skills = len(course_skills)
        coverage = matched / total_skills if total_skills > 0 else 0
        avg_similarity = np.mean(match_scores) if match_scores else 0
        score = int(float(avg_similarity) * float(coverage) * 100)

        if score == 0:
            print(f"📉 {course_code}: No sufficient match (matched {matched}/{total_skills}) → score=0")
        else:
            print(f"📊 {course_code}: matched {matched}/{total_skills} → coverage={float(coverage):.2f}, sim={float(avg_similarity):.2f}, score={score}")

        try:
            supabase.table("course_alignment_scores").insert({
                "batch_id": batch_id,  # ✅ Included here
                "course_id": course_id,
                "course_code": course_code,
                "course_title": course_title,
                "skills_taught": ", ".join(course_skills),
                "skills_in_market": ", ".join(matched_market_skills),
                "matched_job_skill_ids": "{" + ", ".join(matched_job_ids) + "}",
                "coverage": float(round(coverage, 3)),
                "avg_similarity": float(round(avg_similarity, 3)),
                "score": score,
                "calculated_at": now_utc
            }).execute()
            print(f"✅ Saved: {course_code} - {score}")
        except Exception as e:
            print(f"❌ Insert failed for {course_code}: {e}")

if __name__ == "__main__":
    compute_subject_scores_and_save()
