import os
import numpy as np
import pandas as pd
from datetime import datetime
from sentence_transformers import SentenceTransformer, util
from supabase_client import supabase

model = SentenceTransformer("all-MiniLM-L6-v2")
SIMILARITY_THRESHOLD = 0.8

def compute_trending_jobs():
    # Fetch today's jobs
    today = datetime.utcnow().date()
    jobs_response = supabase.table("jobs").select("*").execute()
    jobs = jobs_response.data
    df = pd.DataFrame(jobs)

    if df.empty or "title" not in df.columns or "scraped_at" not in df.columns:
        print("⚠️ No valid job data found.")
        return

    df["scraped_at"] = pd.to_datetime(df["scraped_at"])
    df = df[df["scraped_at"].dt.date == today]

    if df.empty:
        print("📭 No new jobs found for today. Skipping trending job computation.")
        return

    titles = df["title"].fillna("").str.strip().tolist()
    matched_keywords = df.get("matched_keyword", [""] * len(titles)).fillna("").tolist()
    embeddings = model.encode(titles, convert_to_tensor=True)

    # Load existing trending jobs
    existing_response = supabase.table("trending_jobs").select("*").execute()
    existing_data = existing_response.data or []
    existing_titles = [row["title"] for row in existing_data]
    existing_embeddings = model.encode(existing_titles, convert_to_tensor=True) if existing_titles else None

    for i, title in enumerate(titles):
        matched_kw = matched_keywords[i]
        title_embedding = embeddings[i]

        updated = False
        if existing_embeddings is not None:
            sims = util.cos_sim(title_embedding, existing_embeddings)[0].cpu().numpy()
            best_sim_idx = int(np.argmax(sims))
            best_sim_val = float(sims[best_sim_idx])  # Cast to native float

            if best_sim_val >= SIMILARITY_THRESHOLD:
                # Update existing record
                existing = existing_data[best_sim_idx]
                new_freq = existing["frequency"] + 1
                new_avg_sim = float((existing["average_similarity"] * existing["frequency"] + best_sim_val) / new_freq)

                supabase.table("trending_jobs").update({
                    "frequency": new_freq,
                    "average_similarity": new_avg_sim,
                    "date_generated": datetime.utcnow().isoformat()
                }).eq("trending_job_id", existing["trending_job_id"]).execute()

                print(f"🔁 Updated trending: {existing['title']} (+1 freq)")
                updated = True

        if not updated:
            # Insert as new trending entry
            supabase.table("trending_jobs").insert({
                "title": title,
                "matched_keyword": matched_kw,
                "frequency": 1,
                "average_similarity": 1.0,
                "date_generated": datetime.utcnow().isoformat()
            }).execute()
            print(f"➕ New trending: {title}")

if __name__ == "__main__":
    compute_trending_jobs()
