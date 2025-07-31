import os
import re
import google.generativeai as genai
from dotenv import load_dotenv
from datetime import datetime, timezone
from supabase_client import supabase

# Load environment and configure Gemini
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-pro")


def normalize_skill(skill):
    skill = re.sub(r"\s*\([^)]*\)", "", skill)
    return skill.lower().strip()


def clean_skills(raw):
    try:
        skills = eval(raw) if raw.startswith("[") else []
        return [normalize_skill(s) for s in skills if isinstance(s, str) and s.strip()]
    except:
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


def extract_subject_skills_from_supabase():
    print("📦 Fetching courses from Supabase...")
    try:
        courses = supabase.table("courses") \
            .select("course_id, course_code, course_title, course_description") \
            .execute().data
    except Exception as e:
        print(f"❌ Failed to fetch courses: {e}")
        return

    if not courses:
        print("⚠️ No courses found in Supabase.")
        return

    for course in courses:
        code = course.get("course_code")
        title = course.get("course_title")
        description = course.get("course_description") or ""

        print(f"🔍 Analyzing: {code} - {title}")
        matched_skills = extract_skills_with_gemini(description)

        if not matched_skills:
            print("⚠️ No skills extracted.\n")
            continue

        print(f"✅ Skills: {matched_skills}\n")

        try:
            result = supabase.table("course_skills").insert({
                "course_id": course["course_id"],
                "course_code": code,
                "course_title": title,
                "course_description": description,
                "course_skills": ", ".join(sorted(set(matched_skills))),
                "date_extracted_course": datetime.now(timezone.utc).isoformat()
            }).execute()

            if not result or not hasattr(result, "data") or result.data is None:
                print(f"❌ Insert returned None for {code}")
            else:
                print("📤 Inserted into course_skills table.\n")
        except Exception as e:
            print(f"❌ Supabase insert failed for {code}: {e}\n")


if __name__ == "__main__":
    extract_subject_skills_from_supabase()
