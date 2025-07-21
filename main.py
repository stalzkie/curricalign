import os
from dotenv import load_dotenv

from scraper import scrape_jobs_from_google_jobs
from syllabus_matcher import extract_subject_skills_from_static
from skill_extractor import extract_skills_from_jobs
from evaluator import compute_subject_scores
from pdf_report import generate_pdf_report
from query_generator import CS_TERMS
from supabase_client import insert_job

# Load training functions
from train_model import train_subject_score_model
from train_query_model import train_query_model

# Load environment variables
load_dotenv()

def main():
    # Step 1: Scrape job listings using ML-enhanced keyword generator
    print("🌐 Scraping job listings from Google Jobs via SerpApi...")
    all_jobs = scrape_jobs_from_google_jobs()

    if not all_jobs:
        print("⚠️ No new jobs scraped. Continuing with existing job data in Supabase.")
    else:
        print(f"📤 Inserting {len(all_jobs)} job(s) into Supabase...")
        for job in all_jobs:
            insert_job(job)


    # Step 2: Save to Supabase
    print(f"📤 Inserting {len(all_jobs)} job(s) into Supabase...")
    for job in all_jobs:
        insert_job(job)

    # Step 3: Extract job market skill tree
    print("🧠 Extracting skills from job descriptions...")
    job_skill_tree = extract_skills_from_jobs()

    # Step 4: Extract subject-to-skill mapping
    print("📘 Mapping skills taught per subject from static descriptions...")
    subject_skills_map = extract_subject_skills_from_static()

    # Step 5: Conditionally retrain ML models
    if os.getenv("RETRAIN_MODELS", "false").lower() == "true":
        print("🤖 Retraining ML models...")
        train_subject_score_model()
        print("✅ ML models updated!")
    else:
        print("⏭️ Skipping ML model retraining (RETRAIN_MODELS=false)")

    # Step 6: Score subjects vs job market
    print("📊 Computing subject success scores...")
    report = compute_subject_scores(subject_skills_map, job_skill_tree)

    # Step 7: Generate PDF report
    print("📝 Generating curriculum-job alignment report...")
    generate_pdf_report(report)
    print("✅ PDF saved as: syllabus_job_alignment.pdf")

if __name__ == "__main__":
    main()
