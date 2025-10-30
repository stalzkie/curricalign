import os
import re
import ast
from google import genai
from google.genai import types
from dotenv import load_dotenv
from datetime import datetime, timezone
from ..core.supabase_client import supabase

load_dotenv()

# --- Gemini Client ---
client = genai.Client(http_options=types.HttpOptions(api_version='v1'))
MODEL_ID = "gemini-2.5-pro"

# ------------------------------
# 🧩 Helpers for skill cleaning
# ------------------------------
def normalize_skill(skill):
    """Remove parentheses and normalize spacing/case."""
    skill = re.sub(r"\s*\([^)]*\)", "", skill)
    return skill.lower().strip()

def clean_skills(raw):
    """Parse Gemini's output safely into a cleaned list of skills."""
    raw = raw.strip()
    match = re.search(r"```[a-zA-Z]*\n?([\s\S]*?)\n?```", raw)
    if match:
        raw = match.group(1).strip()

    try:
        if raw.startswith("[") and raw.endswith("]"):
            skills = ast.literal_eval(raw)
            if isinstance(skills, list):
                return [normalize_skill(s) for s in skills if isinstance(s, str) and s.strip()]
    except Exception as e:
        print(f"⚠️ Failed to parse Gemini output: {e}\nRaw:\n{raw}")
    return []


# ------------------------------
# 🧠 Gemini Skill Extraction
# ------------------------------
def extract_skills_with_gemini(text):
    """Extract concise technical skills for short course descriptions."""
    prompt = f"""
You are a curriculum skill extraction expert.

Read the following short course description and extract 5 to 8 specific **technical** skills students are likely to gain.
Respond **only** with a valid Python list. No explanations, no markdown.

Include:
- Programming languages (e.g., 'python', 'java')
- Frameworks/libraries (e.g., 'react', 'spring boot')
- Tools or environments (e.g., 'git', 'aws')
- Technical concepts (e.g., 'object-oriented programming', 'data analysis')

Do NOT include:
- Soft skills (communication, teamwork)
- Vague phrases or general verbs
- Non-technical skills

Course Description:
{text.strip()}
"""
    try:
        response = client.models.generate_content(model=MODEL_ID, contents=prompt)
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
    """Simpler fallback if the first extraction fails."""
    retry_prompt = f"""
Extract 5–8 technical skills from this short course description. Return only a Python list.

{text.strip()}
"""
    try:
        response = client.models.generate_content(model=MODEL_ID, contents=retry_prompt)
        raw = response.text.strip()
        print(f"🔁 Gemini retry output:\n{raw}\n")
        return clean_skills(raw)
    except Exception as e:
        print(f"❌ Retry also failed: {e}")
        return []


# ------------------------------
# 🧩 Main Workflow
# ------------------------------
def extract_dataset_skills_from_supabase():
    """
    Extract skills from `courses_dataset` table and sync them to a new table `course_skills_dataset`.
    """
    print("📦 Fetching dataset courses from Supabase...")
    try:
        rows = supabase.table("courses_dataset") \
            .select("course_id, course_code, course_title, course_description") \
            .execute().data or []
    except Exception as e:
        print(f"❌ Failed to fetch courses_dataset: {e}")
        return {}

    if not rows:
        print("⚠️ No courses found in Supabase (courses_dataset).")
        return {}

    # Fetch existing course_skills_dataset for comparison
    existing = supabase.table("course_skills_dataset") \
        .select("course_skills_dataset_id, course_id, course_code, course_description") \
        .execute().data or []
    existing_map = {str(r["course_id"]): r for r in existing if r.get("course_id")}

    for i, course in enumerate(rows, start=1):
        cid = str(course.get("course_id"))
        code = course.get("course_code")
        title = course.get("course_title")
        desc = (course.get("course_description") or "").strip()

        if not desc:
            print(f"⚠️ Skipping {code} ({title}) — empty description.")
            continue

        existing_row = existing_map.get(cid)
        needs_update = (
            not existing_row or
            (desc.strip() != (existing_row.get("course_description") or "").strip())
        )

        if not needs_update:
            print(f"⏩ Skipping {code}, already up-to-date.")
            continue

        print(f"🔍 [{i}/{len(rows)}] Processing {code} - {title}")
        skills = extract_skills_with_gemini(desc)
        if not skills:
            print("⚠️ No skills extracted.\n")
            continue

        payload = {
            "course_id": cid,
            "course_code": code,
            "course_title": title,
            "course_description": desc,
            "course_skills": ", ".join(sorted(set(skills))),
            "date_extracted": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            if existing_row:
                supabase.table("course_skills_dataset").update(payload) \
                    .eq("course_skills_dataset_id", existing_row["course_skills_dataset_id"]).execute()
                print(f"♻️ Updated course_skills_dataset for {code}")
            else:
                supabase.table("course_skills_dataset").insert(payload).execute()
                print(f"📤 Inserted course_skills_dataset for {code}")
        except Exception as e:
            print(f"❌ Supabase upsert failed for {code}: {e}")

    # Return dictionary for model training
    try:
        raw = supabase.table("course_skills_dataset").select("course_code, course_skills").execute().data
        result = {
            row["course_code"]: [s.strip() for s in row["course_skills"].split(",") if s.strip()]
            for row in (raw or []) if row.get("course_skills")
        }
        return result
    except Exception as e:
        print(f"❌ Failed to fetch course_skills_dataset: {e}")
        return {}


# ------------------------------
# 🔍 Read-only fetch helper
# ------------------------------
def fetch_dataset_skills_from_db():
    """Return {course_code: [skills]} from course_skills_dataset without calling Gemini."""
    try:
        rows = supabase.table("course_skills_dataset") \
            .select("course_code, course_skills") \
            .execute().data or []
    except Exception as e:
        print(f"❌ Failed to fetch course_skills_dataset: {e}")
        return {}

    out = {}
    for r in rows:
        code = r.get("course_code")
        field = r.get("course_skills") or ""
        if not code:
            continue
        skills = [s.strip() for s in field.split(",") if s.strip()]
        if skills:
            out[code] = skills
    return out


# ------------------------------
# 🚀 Entry Point
# ------------------------------
if __name__ == "__main__":
    extract_dataset_skills_from_supabase()
