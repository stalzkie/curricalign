from collections import Counter
import os
import re
from datetime import datetime, timezone
import google.generativeai as genai
from dotenv import load_dotenv
from ..core.supabase_client import supabase  # Supabase wrapper

# Load environment and configure Gemini
load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-pro")


def extract_skills_with_gemini(text):
    prompt = f"""
You're an AI assistant extracting technical skills from job postings.

Given the job description below, return a concise Python list of 5–10 technical skills the candidate should know. Do NOT include soft skills or vague terms. Respond ONLY with the Python list.

These should include:
- Programming languages (e.g., 'python', 'java')
- Frameworks (e.g., 'react', 'spring boot')
- Tools or software (e.g., 'git', 'tableau')
- Concepts (e.g., 'object-oriented programming', 'data structures', 'agile development')
- Platforms or environments (e.g., 'unity', 'aws')
- They should be in verb form where possible.

Do NOT include:
- Soft skills (e.g., communication, teamwork)
- Generic verbs (e.g., develop, build)
- Duplicate or redundant entries
- Any commentary or markdown

---

Example:
['python', 'pandas', 'sql', 'data visualization', 'machine learning']
['html', 'css', 'react', 'javascript', 'firebase']

Job Posting:
{text.strip()}
"""
    try:
        response = model.generate_content(prompt)
        raw = response.text.strip()
        print(f"🧠 Gemini raw output:\n{raw}\n")

        if raw.startswith("["):
            skills = [s.lower().strip() for s in eval(raw) if isinstance(s, str)]
            if skills:
                return skills
        raise ValueError("No valid skills extracted")
    except Exception as e:
        print(f"⚠️ Primary extraction failed: {e}")
        return retry_extract_skills(text)


def retry_extract_skills(text):
    retry_prompt = f"""
Extract 5–10 technical skills from this job. Return only a valid Python list.

{text.strip()}
"""
    try:
        response = model.generate_content(retry_prompt)
        raw = response.text.strip()
        print(f"🔁 Gemini retry output:\n{raw}\n")

        if raw.startswith("["):
            return [s.lower().strip() for s in eval(raw) if isinstance(s, str)]
    except Exception as e:
        print(f"❌ Retry also failed: {e}")
    return []

def fetch_skills_from_supabase():
    response = supabase.table("job_skills").select("job_skills").execute()
    all_skills = []
    for row in response.data:
        raw = row["job_skills"]
        if isinstance(raw, str):
            skills = [s.strip() for s in raw.split(",") if s.strip()]
            all_skills.extend(skills)
    return {skill: 1 for skill in all_skills}  # simulate frequency

def extract_skills_from_jobs(jobs=None):
    if jobs is None:
        print("📦 Fetching all jobs from Supabase...")
        try:
            jobs = supabase.table("jobs").select("*").execute().data
        except Exception as e:
            print(f"❌ Failed to fetch jobs: {e}")
            return {}

    if not jobs:
        print("⚠️ No jobs available to process.")
        return {}

    skills_found = Counter()

    for i, job in enumerate(jobs):
        job_id = job.get("job_id")
        title = job.get("title", "")
        company = job.get("company", "")
        description = job.get("description", "")
        requirements = job.get("requirements", "")
        keywords = job.get("matched_keyword", "")

        content = " ".join(str(x or "") for x in [title, description, requirements, keywords]).lower()
        content = re.sub(r'\s+', ' ', content).strip()[:2000]

        print(f"🔍 [{i+1}/{len(jobs)}] Extracting skills for job ID {job_id}...")
        extracted_skills = extract_skills_with_gemini(content)

        if extracted_skills:
            print(f"✅ Extracted: {extracted_skills}\n")
            try:
                supabase.table("job_skills").insert({
                    "job_id": job_id,
                    "title": title,
                    "company": company,
                    "description": description,
                    "job_skills": ", ".join(sorted(set(extracted_skills))),
                    "date_extracted_jobs": datetime.now(timezone.utc).isoformat()
                }).execute()
                print("📤 New version inserted into job_skills table.\n")
            except Exception as e:
                print(f"❌ Supabase insert failed: {e}\n")
        else:
            print("⚠️ No skills extracted.\n")

        for skill in set(extracted_skills):
            skills_found[skill] += 1

    return dict(skills_found)


if __name__ == "__main__":
    extract_skills_from_jobs()
