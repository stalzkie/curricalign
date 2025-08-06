import os
import json
import pandas as pd
import google.generativeai as genai
from dotenv import load_dotenv
from course_descriptions import COURSE_DESCRIPTIONS
import re

# Load .env and configure Gemini
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-pro")
<<<<<<< HEAD

def normalize_skill(skill):
    """
    Normalize a skill: lowercase, strip, remove parentheses, and fix spacing.
    """
    skill = re.sub(r"\s*\([^)]*\)", "", skill)  # Remove parenthetical content
    return skill.lower().strip()

def clean_skills(raw):
    """
    Convert Gemini's output into a cleaned skill list.
    """
    try:
        skills = eval(raw) if raw.startswith("[") else []
        return [normalize_skill(s) for s in skills if isinstance(s, str) and s.strip()]
    except:
        return []
=======
>>>>>>> f982469be23ee3d4f0d449f21a972ed4d29819d7

def extract_skills_with_gemini(text):
    """
    Extracts a list of relevant technical skills from a course description using Gemini.
    """
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
    """
    Retry with a simplified prompt if Gemini returns nothing or invalid list.
    """
    retry_prompt = f"""
Extract 5–10 technical skills from this course. Return only a valid Python list.

{text.strip()}
"""
    try:
        response = model.generate_content(retry_prompt)
        raw = response.text.strip()
        print(f"🔁 Gemini retry output:\n{raw}\n")

        skills = clean_skills(raw)
        return skills if skills else []
    except Exception as e:
        print(f"❌ Retry also failed: {e}")
        return []

def extract_subject_skills_from_static():
    """
    Extracts technical skills using the static COURSE_DESCRIPTIONS dictionary.
    Returns a mapping of course title → list of extracted skills.
    """
    course_map = {}
    csv_rows = []

    print(f"\n📚 Extracting from {len(COURSE_DESCRIPTIONS)} hardcoded course descriptions...\n")

    for code, description in COURSE_DESCRIPTIONS.items():
        title_line = description.strip().splitlines()[0] if description.strip() else ""
        full_title = f"{code} - {title_line[:40]}".strip()

        print(f"🔍 Analyzing: {full_title}")
        matched_skills = extract_skills_with_gemini(description)

        if matched_skills:
            print(f"✅ Skills: {matched_skills}\n")
        else:
            print("⚠️ No skills extracted.\n")

        course_map[full_title] = sorted(set(matched_skills))
        csv_rows.append({
            "course": full_title,
            "skills": ", ".join(sorted(set(matched_skills)))
        })

    print(f"\n✅ Finished extracting skills for {len(course_map)} courses.\n")

    # Save to JSON
    with open("course_skills_output.json", "w") as f:
        json.dump(course_map, f, indent=2)
        print("📝 Saved output to course_skills_output.json")

    # Save to CSV in curricalign
    os.makedirs("curricalign", exist_ok=True)
    df = pd.DataFrame(csv_rows)
    df.to_csv("curricalign/course_skills_output.csv", index=False)
    print("📁 Saved CSV to curricalign/course_skills_output.csv")

    return course_map

if __name__ == "__main__":
    extract_subject_skills_from_static()
