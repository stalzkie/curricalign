from collections import Counter
import os
import re
from datetime import datetime, timezone
import google.generativeai as genai
from dotenv import load_dotenv
from ..core.supabase_client import supabase  # Supabase wrapper for DB access

# Load .env variables (Gemini API key, Supabase credentials, etc.)
load_dotenv()

# Configure Gemini (Google Generative AI SDK)
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Initialize Gemini model (using latest 1.5 Pro)
model = genai.GenerativeModel("gemini-1.5-pro")


# Skill Extraction Logic

def extract_skills_with_gemini(text):
    """
    Primary function to extract technical skills from job descriptions using Gemini.
    - Sends a carefully crafted prompt to Gemini
    - Ensures response is a Python list of skills
    - Cleans and normalizes the skills before returning
    """
    prompt = f"""
You're an AI assistant extracting technical skills from job postings.

Given the job description below, return a concise Python list of 5–10 technical skills the candidate should know. 
Do NOT include soft skills or vague terms. Respond ONLY with the Python list.

These should include:
- Programming languages (e.g., 'python', 'java')
- Frameworks (e.g., 'react', 'spring boot')
- Tools or software (e.g., 'git', 'tableau')
- Concepts (e.g., 'object-oriented programming', 'data structures', 'agile development')
- Platforms or environments (e.g., 'unity', 'aws')

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
        # Call Gemini with the extraction prompt
        response = model.generate_content(prompt)
        raw = response.text.strip()
        print(f"🧠 Gemini raw output:\n{raw}\n")

        # Ensure response is a Python list
        if raw.startswith("["):
            skills = [s.lower().strip() for s in eval(raw) if isinstance(s, str)]
            if skills:
                return skills

        # If invalid response, trigger fallback
        raise ValueError("No valid skills extracted")

    except Exception as e:
        print(f"⚠️ Primary extraction failed: {e}")
        # Fallback attempt with simpler prompt
        return retry_extract_skills(text)


def retry_extract_skills(text):
    """
    Fallback skill extraction if the first Gemini call fails.
    Uses a simpler, more direct prompt.
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

    # Return empty list if both attempts fail
    return []


# Supabase Helpers

def fetch_skills_from_supabase():
    """
    Fetch all existing skills stored in job_skills table.
    Returns a dictionary simulating frequency {skill: 1, ...}
    """
    response = supabase.table("job_skills").select("job_skills").execute()
    all_skills = []
    for row in response.data:
        raw = row.get("job_skills")
        if isinstance(raw, str):
            skills = [s.strip() for s in raw.split(",") if s.strip()]
            all_skills.extend(skills)
    return {skill: 1 for skill in all_skills}


def get_existing_job_skill_ids():
    """
    Fetch job_ids that already have extracted skills in `job_skills`.
    Prevents duplicate processing.
    """
    try:
        res = supabase.table("job_skills").select("job_id").execute()
        existing = set()
        for row in res.data or []:
            jid = row.get("job_id")
            if jid is not None:
                existing.add(str(jid))  # Normalize to string
        print(f"📚 Found {len(existing)} existing job_ids in job_skills.")
        return existing
    except Exception as e:
        print(f"❌ Failed to fetch existing job_skills IDs: {e}")
        return set()

# Main Skill Extraction Flow
def extract_skills_from_jobs(jobs=None):
    """
    Main pipeline for extracting skills from jobs.
    - Fetch jobs from Supabase (if not provided)
    - Skip jobs that already have extracted skills
    - Extract skills using Gemini
    - Insert extracted skills into Supabase
    - Return frequency count of skills found
    """
    # Avoid re-processing jobs that already have skills
    existing_ids = get_existing_job_skill_ids()

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

    # Filter jobs that need new skill extraction
    pending_jobs = [j for j in jobs if str(j.get("job_id")) not in existing_ids]

    print(
        f"🧮 Jobs total: {len(jobs)} | To process (new only): {len(pending_jobs)} | "
        f"Skipped (already have skills): {len(jobs) - len(pending_jobs)}"
    )

    skills_found = Counter()

    # Iterate over jobs and extract skills
    for i, job in enumerate(pending_jobs):
        job_id = job.get("job_id")
        title = job.get("title", "")
        company = job.get("company", "")
        description = job.get("description", "")
        requirements = job.get("requirements", "")
        keywords = job.get("matched_keyword", "")

        # Prepare job content (clean & limit length to avoid token overflow)
        content = " ".join(str(x or "") for x in [title, description, requirements, keywords]).lower()
        content = re.sub(r'\s+', ' ', content).strip()[:2000]

        print(f"🔍 [{i+1}/{len(pending_jobs)}] Extracting skills for job ID {job_id}...")

        # Extract skills using Gemini
        extracted_skills = extract_skills_with_gemini(content)

        if extracted_skills:
            print(f"✅ Extracted: {extracted_skills}\n")
            try:
                # Insert into Supabase job_skills table
                supabase.table("job_skills").insert({
                    "job_id": job_id,
                    "title": title,
                    "company": company,
                    "description": description,
                    "job_skills": ", ".join(sorted(set(extracted_skills))),
                    "date_extracted_jobs": datetime.now(timezone.utc).isoformat()
                }).execute()
                print("📤 Inserted into job_skills table.\n")
            except Exception as e:
                print(f"❌ Supabase insert failed: {e}\n")
        else:
            print("⚠️ No skills extracted.\n")

        # Count frequency of extracted skills
        for skill in set(extracted_skills):
            skills_found[skill] += 1

    if not pending_jobs:
        print("👌 Nothing to do. All jobs already have skills in job_skills.")

    return dict(skills_found)

if __name__ == "__main__":
    extract_skills_from_jobs()
