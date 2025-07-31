from collections import Counter
import os
import re
import pandas as pd
import google.generativeai as genai
from dotenv import load_dotenv
from supabase_client import supabase  # Pull from jobs table

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-1.5-pro")

def extract_skills_with_gemini(text):
    """
    Uses Gemini to extract a list of technical skills from job text.
    """
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
    """
    Retry with a simpler prompt if Gemini returns nothing or fails.
    """
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

def extract_skills_from_jobs(jobs=None):
    """
    Extracts a frequency map of skills from job descriptions using Gemini
    and saves the results to curricalign/extracted_skills.csv.
    """
    if jobs is None:
        print("📦 Fetching all jobs from Supabase...")
        try:
            jobs = supabase.table("jobs").select("*").execute().data
        except Exception as e:
            print(f"❌ Failed to fetch jobs: {e}")
            return {}

    if not jobs:
        print("❌ No jobs available to process.")
        return {}

    skills_found = Counter()
    all_extracted = []

    for i, job in enumerate(jobs):
        content = " ".join([
            job.get("title", ""),
            job.get("description", ""),
            job.get("requirements", ""),
            job.get("matched_keyword", "")
        ]).lower()

        content = re.sub(r'\s+', ' ', content).strip()[:2000]

        print(f"🔍 [{i+1}/{len(jobs)}] Extracting skills from job...")
        extracted_skills = extract_skills_with_gemini(content)

        if extracted_skills:
            print(f"✅ Extracted: {extracted_skills}\n")
            all_extracted.append({
                "job_id": job.get("id", f"job_{i+1}"),
                "skills": ", ".join(extracted_skills)
            })
        else:
            print("⚠️ No skills extracted.\n")

        for skill in set(extracted_skills):
            skills_found[skill] += 1

    csv_path = os.path.join("curricalign", "extracted_skills.csv")
    df = pd.DataFrame(all_extracted)
    df.to_csv(csv_path, index=False)
    print(f"📁 Extracted skills saved to: {csv_path}")

    return dict(skills_found)
