import os
import re
import google.generativeai as genai
from dotenv import load_dotenv
from datetime import datetime, timezone
from ..core.supabase_client import supabase

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-pro-latest")


# Helpers for skill normalization
def normalize_skill(skill):
    skill = re.sub(r"\s*\([^)]*\)", "", skill)
    return skill.lower().strip()


def clean_skills(raw):
    import ast
    try:
        raw = raw.strip()
        skills = ast.literal_eval(raw)
        if not isinstance(skills, list):
            print("⚠️ Gemini output is not a list. Raw:\n", raw)
            return []
        return [normalize_skill(s) for s in skills if isinstance(s, str) and s.strip()]
    except Exception as e:
        print(f"❌ Failed to parse Gemini output: {e}")
        print("Raw output:\n", raw)
        return []


# Core Gemini extraction functions
def extract_skills_with_gemini(text):
    prompt = f"""
You are a curriculum analysis expert.

Your task is to read a course description and extract a Python list of **5 to 10 specific technical skills** that a student is likely to learn from the course.
Do NOT include soft skills or vague terms. Respond ONLY with the Python list.

NOTE: FOCUS ONLY ON TECHNICAL SKILLS.

These should include:
- Programming languages (e.g., 'python', 'java')
- Frameworks (e.g., 'react', 'spring boot')
- Tools or software (e.g., 'git', 'tableau')
- Concepts (e.g., 'object-oriented programming', 'data structures', 'agile development')
- Platforms or environments (e.g., 'unity', 'aws')
- THEY SHOULD BE IN VERB FORMAT AS MUCH AS POSSIBLE

⚠️ Do NOT include:
- Soft skills (e.g., communication, teamwork)
- Generic verbs (e.g., develop, build)
- Duplicate or redundant entries
- Any commentary or markdown

Output only a Python list.
Course Description:
{text.strip()}
"""
    try:
        response = model.generate_content(prompt)
        raw = response.text.strip()
        print(f"🧠 Gemini raw output:\n{raw}\n")
        skills = clean_skills(raw)
        if not skills:
            raise ValueError("Empty or invalid skill list")
        return skills
    except Exception as e:
        print(f"⚠️ Primary extraction failed: {e}")
        return retry_extract_skills(text)


def retry_extract_skills(text):
    retry_prompt = f"""
Extract 5–10 technical skills from this course. Return only a valid Python list.

{text.strip()}
"""
    try:
        response = model.generate_content(retry_prompt)
        raw = response.text.strip()
        print(f"🔁 Gemini retry output:\n{raw}\n")
        return clean_skills(raw)
    except Exception as e:
        print(f"❌ Retry also failed: {e}")
        return []


# Main extraction workflow
def extract_subject_skills_from_supabase():
    """
    Sync `course_skills` with `courses`:
    - Insert new courses not yet in course_skills
    - Update courses if description changed
    - Delete stale rows not tied to any course
    """
    print("📦 Fetching courses from Supabase...")
    try:
        courses = supabase.table("courses") \
            .select("course_id, course_code, course_title, course_description") \
            .execute().data or []
    except Exception as e:
        print(f"❌ Failed to fetch courses: {e}")
        return {}

    if not courses:
        print("⚠️ No courses found in Supabase.")
        return {}

    # Fetch existing course_skills
    existing = supabase.table("course_skills") \
        .select("course_skill_id, course_id, course_code, course_description") \
        .execute().data or []
    existing_map = {str(r["course_id"]): r for r in existing if r.get("course_id")}

    # Detect stale entries (course_skills with no corresponding course_id in courses)
    current_ids = {str(c["course_id"]) for c in courses if c.get("course_id")}
    stale = [r for r in existing if str(r.get("course_id")) not in current_ids]
    for r in stale:
        try:
            supabase.table("course_skills").delete().eq("course_skill_id", r["course_skill_id"]).execute()
            print(f"🗑️ Deleted stale course_skills row id={r['course_skill_id']} (course_id={r.get('course_id')})")
        except Exception as e:
            print(f"❌ Failed to delete stale row id={r['course_skill_id']}: {e}")

    # Process insert/update
    for i, course in enumerate(courses, start=1):
        cid = str(course.get("course_id"))
        code = course.get("course_code")
        title = course.get("course_title")
        desc = course.get("course_description") or ""

        existing_row = existing_map.get(cid)
        needs_update = (
            not existing_row or
            (desc.strip() != (existing_row.get("course_description") or "").strip())
        )

        if not needs_update:
            print(f"⏩ Skipping {code}, already up-to-date.")
            continue

        print(f"🔍 [{i}/{len(courses)}] Processing {code} - {title}")
        matched_skills = extract_skills_with_gemini(desc)
        if not matched_skills:
            print("⚠️ No skills extracted.\n")
            continue

        payload = {
            "course_id": cid,
            "course_code": code,
            "course_title": title,
            "course_description": desc,
            "course_skills": ", ".join(sorted(set(matched_skills))),
            "date_extracted_course": datetime.now(timezone.utc).isoformat()
        }

        try:
            if existing_row:
                supabase.table("course_skills").update(payload).eq("course_skill_id", existing_row["course_skill_id"]).execute()
                print(f"♻️ Updated course_skills for {code}")
            else:
                supabase.table("course_skills").insert(payload).execute()
                print(f"📤 Inserted course_skills for {code}")
        except Exception as e:
            print(f"❌ Supabase upsert failed for {code}: {e}\n")

    # Final return: mapping for training
    try:
        raw = supabase.table("course_skills").select("course_code, course_skills").execute().data
        subject_skills_map = {
            row["course_code"]: [s.strip() for s in row["course_skills"].split(",") if s.strip()]
            for row in (raw or []) if row.get("course_skills")
        }
        return subject_skills_map
    except Exception as e:
        print(f"❌ Failed to fetch course_skills: {e}")
        return {}

if __name__ == "__main__":
    extract_subject_skills_from_supabase()
