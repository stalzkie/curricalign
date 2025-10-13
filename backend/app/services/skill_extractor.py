from collections import Counter
import os
import re
from datetime import datetime, timezone
import json # <-- NEW: Import the JSON library
from pydantic import BaseModel, Field # <-- NEW: Import Pydantic for schema definition
from ast import literal_eval # <-- NEW: Use safe literal_eval instead of eval

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


# 🎯 FIX 1: Define a Pydantic schema for structured output
class SkillList(BaseModel):
    """Schema to enforce the model returns a clean list of skills."""
    skills: list[str] = Field(description="A concise list of 5-10 technical skills.")

# Skill Extraction Logic
# ---------------------

def extract_skills_with_gemini(text):
    """
    Primary function to extract technical skills from job descriptions using Gemini.
    - Sends a carefully crafted prompt to Gemini
    - **Uses JSON schema to force a clean, parsable list of skills**
    - Cleans and normalizes the skills before returning
    """
    # NOTE: The prompt can be simplified since the schema enforces the format.
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
        # 🎯 FIX 2: Use response_mime_type and response_schema for JSON output
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SkillList,
        )

        response = client.models.generate_content(
            model=MODEL_ID, 
            contents=prompt,
            config=config # <-- Pass the structured configuration
        )
        
        # 🎯 FIX 3: Parse the response JSON and extract the list
        try:
            # The response.text will be a JSON string like '{"skills": ["python", "sql"]}'
            # Safely load the JSON string.
            json_data = json.loads(response.text.strip())
            extracted_list = json_data.get("skills", [])
            
            raw_text_for_logging = response.text.strip()
            print(f"🧠 Gemini raw output (JSON): {raw_text_for_logging}\n")
            
            if extracted_list and isinstance(extracted_list, list):
                # Normalize and clean the skills
                skills = [s.lower().strip() for s in extracted_list if isinstance(s, str) and s.strip()]
                if skills:
                    return skills
                
        except json.JSONDecodeError:
            # If the model still returns messy markdown/code fences, the JSON load fails.
            print(f"⚠️ JSON decoding failed. Raw output: {response.text.strip()[:100]}...")
            
        # If invalid response, trigger fallback
        raise ValueError("No valid skills extracted from structured response.")

    except Exception as e:
        print(f"⚠️ Primary extraction failed: {e}")
        # Fallback attempt with simpler prompt
        return retry_extract_skills(text)


def retry_extract_skills(text):
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
            contents=retry_prompt
        )
        raw = response.text.strip()
        print(f"🔁 Gemini retry output:\n{raw}\n")

        # 🎯 FIX 4: Use literal_eval() for safer parsing after stripping markdown
        
        # 1. Strip markdown code fences if they exist
        if raw.startswith("```"):
            raw = re.sub(r'^\s*```[a-z]*\s*', '', raw, flags=re.MULTILINE)
            raw = re.sub(r'```\s*$', '', raw, flags=re.MULTILINE)
            raw = raw.strip()

        # 2. Check if the result is a Python list string
        if raw.startswith("[") and raw.endswith("]"):
            # literal_eval is safer than eval for parsing list/dict literals
            skills_list = literal_eval(raw)
            if skills_list and isinstance(skills_list, list):
                return [s.lower().strip() for s in skills_list if isinstance(s, str)]
            
    except Exception as e:
        print(f"❌ Retry also failed: {e}")

    # Return empty list if both attempts fail
    return []


# --- Remainder of the code (fetch_skills_from_supabase, get_existing_job_skill_ids, extract_skills_from_jobs, if __name__ == "__main__":) remains the same ---

# Supabase Helpers
# ----------------

def fetch_skills_from_supabase():
    # ... (code unchanged)
    response = supabase.table("job_skills").select("job_skills").execute()
    all_skills = []
    for row in response.data:
        raw = row.get("job_skills")
        if isinstance(raw, str):
            # This logic assumes job_skills is a comma-separated string
            skills = [s.strip() for s in raw.split(",") if s.strip()]
            all_skills.extend(skills)
    return {skill: 1 for skill in all_skills}


def get_existing_job_skill_ids():
    # ... (code unchanged)
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
# --------------------------
def extract_skills_from_jobs(jobs=None):
    # ... (code unchanged)
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
                    # Joins the list into a comma-space separated string for your DB schema
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