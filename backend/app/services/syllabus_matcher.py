import os
import re
import google.generativeai as genai
from dotenv import load_dotenv
from datetime import datetime, timezone
from ..core.supabase_client import supabase

# Load environment and configure Gemini
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-pro")


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


def extract_skills_with_gemini(text):
    prompt = f"""
You are a curriculum analysis expert.

Your task is to read a course description and extract a Python list of **5 to 10 specific technical skills** that a student is likely to learn from the course.

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

---

### Format:
Output a single Python list using valid syntax.

Example:
['python', 'pandas', 'sql', 'data visualization', 'machine learning']
['html', 'css', 'react', 'javascript', 'firebase']

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

Example:
['python', 'pandas', 'sql', 'data visualization', 'machine learning']
['html', 'css', 'react', 'javascript', 'firebase']

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


def fetch_subject_skills_from_db():
    response = supabase.table("course_skills").select("course_code", "course_skills").execute()
    return {
        row["course_code"]: row["course_skills"]
        for row in (response.data or [])
        if row.get("course_skills")
    }


def get_existing_course_skill_ids():
    """Return a set of course_ids that already exist in course_skills."""
    try:
        res = supabase.table("course_skills").select("course_id").execute()
        existing = set()
        for row in (res.data or []):
            cid = row.get("course_id")
            if cid is not None:
                existing.add(str(cid))
        print(f"📚 Found {len(existing)} existing course_ids in course_skills.")
        return existing
    except Exception as e:
        print(f"❌ Failed to fetch existing course_skills IDs: {e}")
        return set()


def extract_subject_skills_from_supabase():
    print("📦 Fetching courses from Supabase...")
    try:
        courses = supabase.table("courses") \
            .select("course_id, course_code, course_title, course_description") \
            .execute().data
    except Exception as e:
        print(f"❌ Failed to fetch courses: {e}")
        return {}

    if not courses:
        print("⚠️ No courses found in Supabase.")
        return {}

    # ✅ Skip courses that already have entries in course_skills
    existing_ids = get_existing_course_skill_ids()
    pending_courses = [c for c in courses if str(c.get("course_id")) not in existing_ids]

    print(
        f"🧮 Courses total: {len(courses)} | "
        f"To process (new only): {len(pending_courses)} | "
        f"Skipped (already in course_skills): {len(courses) - len(pending_courses)}"
    )

    for i, course in enumerate(pending_courses, start=1):
        code = course.get("course_code")
        title = course.get("course_title")
        description = course.get("course_description") or ""
        course_id = course.get("course_id")

        print(f"🔍 [{i}/{len(pending_courses)}] Analyzing: {code} - {title}")
        matched_skills = extract_skills_with_gemini(description)

        if not matched_skills:
            print("⚠️ No skills extracted.\n")
            continue

        print(f"✅ Skills: {matched_skills}\n")

        try:
            result = supabase.table("course_skills").insert({
                "course_id": course_id,
                "course_code": code,
                "course_title": title,
                "course_description": description,
                "course_skills": ", ".join(sorted(set(matched_skills))),
                "date_extracted_course": datetime.now(timezone.utc).isoformat()
            }).execute()

            if not result or not hasattr(result, "data") or result.data is None:
                print(f"❌ Insert returned None for {code}")
            else:
                print("📤 Inserted into course_skills.\n")
        except Exception as e:
            print(f"❌ Supabase insert failed for {code}: {e}\n")

    if not pending_courses:
        print("👌 Nothing to do. All courses already have skills in course_skills.")

    # ✅ Final return: Map course_code -> list of skills for model training
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
