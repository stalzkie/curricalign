import os
import re
# 🔑 Import necessary components from the modern SDK structure
from google import genai
from google.genai import types 
import ast
from dotenv import load_dotenv
from datetime import datetime, timezone
# Assuming this path is correct for your project structure
from ..core.supabase_client import supabase 


load_dotenv()

# --- 🚀 MODERN GEMINI CLIENT INITIALIZATION ---
# 1. Initialize the client using the stable 'v1' API endpoint.
# The client automatically picks up the API key from the GEMINI_API_KEY environment variable.
client = genai.Client(
    # Explicitly sets the API version to 'v1' for production stability
    http_options=types.HttpOptions(api_version='v1')
)

# 2. Define the model ID as a string
MODEL_ID = "gemini-2.5-pro" # Using a current, stable model ID


# Helpers for skill normalization
# -----------------------------

def normalize_skill(skill):
    """Removes text in parentheses and normalizes case/whitespace."""
    skill = re.sub(r"\s*\([^)]*\)", "", skill)
    return skill.lower().strip()


def clean_skills(raw):
    """
    Safely parses the string output from Gemini into a cleaned list of skills.
    
    This function has been revised to strip markdown code fences which often cause 
    SyntaxErrors with ast.literal_eval().
    """
    raw = raw.strip()
    
    # 🎯 FIX: Use regex to strip the markdown code fences (e.g., ```python\n...\n```)
    # This non-greedy regex looks for three backticks, optional language tag, 
    # and extracts the content in between.
    match = re.search(r"```[a-zA-Z]*\n?([\s\S]*?)\n?```", raw)
    
    # If a markdown block is found, use the content inside it.
    if match:
        raw = match.group(1).strip()
    
    try:
        # Check if the stripped content looks like a list before attempting to parse
        if raw.startswith("[") and raw.endswith("]"):
            # Using ast.literal_eval() to safely parse the Python list string
            skills = ast.literal_eval(raw)
            
            if not isinstance(skills, list):
                print("⚠️ Gemini output is not a list after stripping. Raw:\n", raw)
                return []
            
            # Normalize and filter out empty strings
            return [normalize_skill(s) for s in skills if isinstance(s, str) and s.strip()]
        else:
            print("⚠️ Raw output does not look like a Python list (missing brackets). Raw:\n", raw)
            return []
            
    except Exception as e:
        print(f"❌ Failed to parse Gemini output: {e}")
        print("Raw output (after stripping):\n", raw)
        return []


# Core Gemini extraction functions
# ------------------------------

def extract_skills_with_gemini(text):
    """
    Primary function to extract technical skills from a course description using Gemini.
    """
    prompt = f"""
You are a curriculum analysis expert.

Your task is to read a course description and extract a Python list of 10 specific technical skills that a student is likely to learn from the course.
Do NOT include soft skills or vague terms. Respond ONLY with the Python list. FOCUS ON TECHNICAL SKILLS.

NOTE: FOCUS ONLY ON TECHNICAL SKILLS.

These should include:
- Programming languages (e.g., 'python', 'java')
- Frameworks (e.g., 'react', 'spring boot')
- Tools or software (e.g., 'git', 'tableau')
- Concepts (e.g., 'object-oriented programming', 'data structures', 'agile development')
- Platforms or environments (e.g., 'unity', 'aws')
- FOCUS ON SKILLS TO BE ACHIEVED BY STUDENTS IN THE SAID COURSE
- THEY SHOULD BE IN VERB FORMAT AS MUCH AS POSSIBLE
- EXAMPLES OF TO INCLUDE: python, sql, java, c++, c#, tableu, posgtresql, mysql, unity

⚠️ Do NOT include:
- Soft skills (e.g., communication, teamwork)
- Generic verbs (e.g., develop, build)
- Duplicate or redundant entries
- Any commentary or markdown
- DO NOT BE VAGUE and use terms such as debugging mobile applications
- EXAMPLES OF VAGUE TERMS: developing with a web application framework, software development methodologies, software engineering principles, and more.

Output only a Python list. For example: ['python', 'sql', 'data visualization', 'machine learning'].
Course Description:
{text.strip()}
"""
    try:
        # 🎯 UPDATED: Use the client.models service to call generate_content
        response = client.models.generate_content(
            model=MODEL_ID, 
            contents=prompt
        )
        raw = response.text.strip()
        print(f"🧠 Gemini raw output:\n{raw}\n")
        skills = clean_skills(raw)
        if not skills:
            # Re-raise the ValueError using the specific failure type for logging clarity
            raise ValueError(f"Empty or invalid skill list after parsing. Raw was: {raw}")
        return skills
    except Exception as e:
        print(f"⚠️ Primary extraction failed: {e}")
        return retry_extract_skills(text)


def retry_extract_skills(text):
    """
    Fallback skill extraction if the first Gemini call fails.
    """
    retry_prompt = f"""
Extract 5–10 technical skills from this course. Return only a valid Python list.

{text.strip()}
"""
    try:
        # 🎯 UPDATED: Use the client.models service for the retry call
        response = client.models.generate_content(
            model=MODEL_ID, 
            contents=retry_prompt
        )
        raw = response.text.strip()
        print(f"🔁 Gemini retry output:\n{raw}\n")
        return clean_skills(raw)
    except Exception as e:
        print(f"❌ Retry also failed: {e}")
        return []


# Main extraction workflow
# ------------------------

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
            # Joins the list into a comma-space separated string for your DB schema
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

# ---------------------------
# NEW: Read-only fetch helper
# ---------------------------
def fetch_subject_skills_from_db():
    """
    Return {course_code: [skill, ...]} from the course_skills table
    WITHOUT calling Gemini or mutating the DB.
    """
    try:
        rows = supabase.table("course_skills") \
            .select("course_code, course_skills") \
            .execute().data or []
    except Exception as e:
        print(f"❌ Failed to fetch course_skills: {e}")
        return {}

    out = {}
    for r in rows:
        code = r.get("course_code")
        skills_field = r.get("course_skills") or ""
        if not code:
            continue
        skills = [s.strip() for s in skills_field.split(",") if s.strip()]
        if skills:
            out[code] = skills
    return out

if __name__ == "__main__":
    extract_subject_skills_from_supabase()
