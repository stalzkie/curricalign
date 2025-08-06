# backend/app/services/orchestrator.py
from .scraper import scrape_jobs_from_google_jobs
from .skill_extractor import extract_skills_from_jobs
from .syllabus_matcher import extract_subject_skills_from_supabase
from .evaluator import compute_subject_scores_and_save
from .pdf_report import generate_pdf_report
from ..ml.train_model import train_subject_score_model
from ..ml.train_query_model import train_query_model
from .query_generator import CS_TERMS
from ..core.supabase_client import insert_job

import os
from dotenv import load_dotenv
load_dotenv()

def run_pipeline():
    print("🌐 Scraping job listings from Google Jobs via SerpApi...")
    all_jobs = scrape_jobs_from_google_jobs()

    if not all_jobs:
        print("⚠️ No new jobs scraped. Continuing with existing job data.")
    else:
        for job in all_jobs:
            insert_job(job)

    print("🧠 Extracting skills from job descriptions...")
    extract_skills_from_jobs()

    print("📘 Extracting course skills from Supabase...")
    extract_subject_skills_from_supabase()

    if os.getenv("RETRAIN_MODELS", "false").lower() == "true":
        print("🤖 Retraining ML models...")
        train_subject_score_model()
        train_query_model()

    print("📊 Computing subject success scores...")
    report = compute_subject_scores_and_save()

    print("📝 Generating PDF report...")
    generate_pdf_report(report)
