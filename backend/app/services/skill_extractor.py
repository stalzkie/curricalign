from collections import Counter
import os
import re
from datetime import datetime, timezone
import json
from pydantic import BaseModel, Field
from ast import literal_eval

# 🔑 MODERN SDK IMPORTS
from google import genai
from google.genai import types

from dotenv import load_dotenv
from ..core.supabase_client import supabase  # Supabase wrapper for DB access

# Load .env variables (Gemini API key, Supabase credentials, etc.)
load_dotenv()

# --- 🚀 MODERN GEMINI CLIENT INITIALIZATION ---
client = genai.Client(
    http_options=types.HttpOptions(api_version='v1')
)
MODEL_ID = "gemini-2.5-pro"

# How many newly scraped jobs to process per run
DEFAULT_BATCH_LIMIT = 10


# 🎯 FIX 1: Define a Pydantic schema for structured output
class SkillList(BaseModel):
    """Schema to enforce the model returns a clean list of skills."""
    skills: list[str] = Field(description="A concise list of 5-10 technical skills.")


# Skill Extraction Logic
# ---------------------

def extract_skills_with_gemini(text: str) -> list[str]:
    """
    Primary function to extract technical skills from job descriptions using Gemini.
    - Sends a carefully crafted prompt to Gemini
    - Uses JSON schema to force a clean, parsable list of skills
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

NOTE: FOCUS ONLY ON TECHNICAL SKILLS.

---
Example:
['python', 'pandas', 'sql', 'data visualization', 'machine learning']
['html', 'css', 'react', 'javascript', 'firebase']

Job Posting:
{text.strip()}
"""
    try:
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SkillList,
        )

        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt,
            config=config,
        )

        try:
            json_data = json.loads(response.text.strip())
            extracted_list = json_data.get("skills", [])

            raw_text_for_logging = response.text.strip()
            print(f"🧠 Gemini raw output (JSON): {raw_text_for_logging}\n")

            if extracted_list and isinstance(extracted_list, list):
                skills = [s.lower().strip() for s in extracted_list if isinstance(s, str) and s.strip()]
                if skills:
                    return skills

        except json.JSONDecodeError:
            print(f"⚠️ JSON decoding failed. Raw output: {response.text.strip()[:100]}...")

        raise ValueError("No valid skills extracted from structured response.")

    except Exception as e:
        print(f"⚠️ Primary extraction failed: {e}")
        return retry_extract_skills(text)


def retry_extract_skills(text: str) -> list[str]:
    """
    Fallback skill extraction if the first Gemini call fails.
    Uses a simpler, more direct prompt, and implements safer parsing.
    """
    retry_prompt = f"""
Extract 5–10 technical skills from this job. Return only a valid Python list like ['skill1', 'skill2'].

{text.strip()}
"""
    try:
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=retry_prompt,
        )
        raw = response.text.strip()
        print(f"🔁 Gemini retry output:\n{raw}\n")

        if raw.startswith("```"):
            raw = re.sub(r'^\s*```[a-z]*\s*', '', raw, flags=re.MULTILINE)
            raw = re.sub(r'```\s*$', '', raw, flags=re.MULTILINE)
            raw = raw.strip()

        if raw.startswith("[") and raw.endswith("]"):
            skills_list = literal_eval(raw)
            if skills_list and isinstance(skills_list, list):
                return [s.lower().strip() for s in skills_list if isinstance(s, str)]

    except Exception as e:
        print(f"❌ Retry also failed: {e}")

    return []


# Supabase Helpers
# ----------------

def fetch_skills_from_supabase():
    response = supabase.table("job_skills").select("job_skills").execute()
    all_skills = []
    for row in response.data:
        raw = row.get("job_skills")
        if isinstance(raw, str):
            skills = [s.strip() for s in raw.split(",") if s.strip()]
            all_skills.extend(skills)
    return {skill: 1 for skill in all_skills}


def get_existing_job_skill_ids() -> set[str]:
    try:
        res = supabase.table("job_skills").select("job_id").execute()
        existing = set()
        for row in res.data or []:
            jid = row.get("job_id")
            if jid is not None:
                existing.add(str(jid))
        print(f"📚 Found {len(existing)} existing job_ids in job_skills.")
        return existing
    except Exception as e:
        print(f"❌ Failed to fetch existing job_skills IDs: {e}")
        return set()


# Main Skill Extraction Flow
# --------------------------

def extract_skills_from_jobs(jobs=None, batch_limit: int = DEFAULT_BATCH_LIMIT):
    """
    Extract skills only for the **recently scraped jobs**, not the entire jobs table.

    Behaviour:
    - If `jobs` is provided: process only that list.
    - If `jobs` is None: fetch the most recent `batch_limit` jobs from Supabase,
      ordered by `scraped_at` DESC (i.e., last scraped first).
    - Within that batch, skip jobs that already have entries in `job_skills`.
    """
    existing_ids = get_existing_job_skill_ids()

    if jobs is None:
        print(f"📦 Fetching up to {batch_limit} most recently scraped jobs from Supabase...")
        try:
            resp = (
                supabase.table("jobs")
                .select("*")
                .order("scraped_at", desc=True)
                .limit(batch_limit)
                .execute()
            )
            jobs = resp.data or []
        except Exception as e:
            print(f"❌ Failed to fetch jobs: {e}")
            return {}

    if not jobs:
        print("⚠️ No jobs available to process in this batch.")
        return {}

    # Only consider jobs in this batch that don't have skills yet
    pending_jobs = [j for j in jobs if str(j.get("job_id")) not in existing_ids]

    print(
        f"🧮 Jobs fetched this batch: {len(jobs)} | To process (new only in batch): {len(pending_jobs)} | "
        f"Skipped (already have skills): {len(jobs) - len(pending_jobs)}"
    )

    skills_found = Counter()

    for i, job in enumerate(pending_jobs):
        job_id = job.get("job_id")
        title = job.get("title", "")
        company = job.get("company", "")
        description = job.get("description", "")
        requirements = job.get("requirements", "")
        keywords = job.get("matched_keyword", "")

        content = " ".join(str(x or "") for x in [title, description, requirements, keywords]).lower()
        content = re.sub(r'\s+', ' ', content).strip()[:2000]

        print(f"🔍 [{i+1}/{len(pending_jobs)}] Extracting skills for job ID {job_id}...")

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
                    "date_extracted_jobs": datetime.now(timezone.utc).isoformat(),
                }).execute()
                print("📤 Inserted into job_skills table.\n")
            except Exception as e:
                print(f"❌ Supabase insert failed: {e}\n")
        else:
            print("⚠️ No skills extracted.\n")

        for skill in set(extracted_skills):
            skills_found[skill] += 1

    if not pending_jobs:
        print("👌 Nothing to do for this batch. All fetched jobs already have skills in job_skills.")

    return dict(skills_found)


if __name__ == "__main__":
    extract_skills_from_jobs(batch_limit=DEFAULT_BATCH_LIMIT)
