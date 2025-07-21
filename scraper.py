import os
from dotenv import load_dotenv
from serpapi import GoogleSearch

from course_descriptions import COURSE_DESCRIPTIONS
from query_generator import get_top_keywords, CS_TERMS
from query_logger import log_query

load_dotenv()
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")


def scrape_jobs_from_google_jobs(
    location: str = "Philippines",
    top_n_keywords: int = 10,
    jobs_per_query: int = 3
):
    syllabus_text = "\n".join(COURSE_DESCRIPTIONS.values())
    keyword_list = get_top_keywords(syllabus_text, n=top_n_keywords)

    print("📈 Top keywords from Google Trends:", keyword_list)

    all_jobs = []

    for keyword in keyword_list:
        base_query = f"{keyword} developer computer science jobs"
        print(f"🔍 Searching for: {base_query}")

        variations = [
            base_query,
            f"{keyword} developer jobs",
            f"{keyword} engineer jobs",
            f"remote {keyword} jobs"
        ]

        collected = []

        for variation in variations:
            if len(collected) >= jobs_per_query:
                break

            params = {
                "engine": "google_jobs",
                "q": variation,
                "hl": "en",
                "gl": "ph",
                "api_key": SERPAPI_API_KEY
            }

            try:
                search = GoogleSearch(params)
                results = search.get_dict()
                jobs = results.get("jobs_results", [])

                for job in jobs:
                    job_data = {
                        "source": "Google Jobs via SerpApi",
                        "title": job.get("title", "N/A"),
                        "company": job.get("company_name", "N/A"),
                        "location": job.get("location", location),
                        "via": job.get("via", "N/A"),
                        "description": job.get("description", "N/A"),
                        "requirements": extract_requirements(job.get("job_highlights", [])),
                        "job_id": job.get("job_id", "N/A"),
                        "url": job.get("related_links", [{}])[0].get("link", "N/A"),
                        "matched_keyword": keyword
                    }

                    if job_data["job_id"] not in [j["job_id"] for j in collected]:
                        collected.append(job_data)

                    if len(collected) >= jobs_per_query:
                        break

                # Log query performance to CSV
                log_query(
                    query=variation,
                    is_cs_term=int(any(term in variation.lower() for term in CS_TERMS)),
                    word_count=len(variation.split()),
                    trend_value=0,  # 
                    jobs_returned=len(jobs),
                    matched_skills_count=estimate_matched_skills(jobs),
                    avg_subject_score=None 
                )

            except Exception as e:
                print(f"❌ Error fetching jobs for '{variation}': {e}")
                continue

        if not collected:
            print(f"⚠️ No jobs found for: {keyword}")
        else:
            all_jobs.extend(collected)

    return all_jobs


def extract_requirements(highlights):
    for section in highlights:
        title = section.get("title", "")
        if "Qualifications" in title or "Requirements" in title:
            return " ".join(section.get("items", []))
    return "Not specified"


def estimate_matched_skills(jobs):
    """
    Estimates how many CS_TERMS appear in a list of jobs (deduplicated).
    """
    skills = set()
    for job in jobs:
        text = (job.get("description", "") + " " + job.get("requirements", "")).lower()
        for term in CS_TERMS:
            if term in text:
                skills.add(term)
    return len(skills)
