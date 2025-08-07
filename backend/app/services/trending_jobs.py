import os
import re
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from ..core.supabase_client import supabase
from sentence_transformers import SentenceTransformer, util
from fuzzywuzzy import fuzz
from collections import Counter

# Config
DAYS_RECENT = 14
DAYS_PREV = 14
TREND_WEIGHT = 0.5
GROWTH_WEIGHT = 0.35
DIVERSITY_WEIGHT = 0.15
SIMILARITY_THRESHOLD = 0.6
FUZZY_THRESHOLD = 70

model = SentenceTransformer("all-MiniLM-L6-v2")

def fetch_cs_keywords():
    res = supabase.table("cs_keywords").select("keyword").execute()
    return [kw["keyword"].lower() for kw in res.data]

def normalize(series):
    min_val = series.min()
    max_val = series.max()
    return (series - min_val) / (max_val - min_val + 1e-5)

def clean_title(title: str) -> str:
    title = title.lower()
    title = re.sub(r"\([^)]*\)", "", title)
    title = re.sub(r"\d+\+?\s*(years|yrs)?", "", title)
    title = re.sub(r"(remote|onsite|homebased|wfh|qc|pasay|makati|hybrid|urgent|asap|start|office|permanent|morning|shift|night|work|pasig|location|earn)", "", title)
    title = re.sub(r"[^a-z0-9\s]", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title

def is_cs_related(title: str, cs_keywords: list) -> bool:
    for kw in cs_keywords:
        if kw in title:
            return True
    return False

def fetch_all_jobs():
    res = supabase.table("jobs").select("job_id, title, company, scraped_at").execute()
    df = pd.DataFrame(res.data)
    df["scraped_at"] = pd.to_datetime(df["scraped_at"]).dt.date
    return df

def cluster_similar_titles(titles, job_ids):
    cleaned_titles = [clean_title(t) for t in titles]
    embeddings = model.encode(cleaned_titles, convert_to_tensor=True)

    groups = []
    used = set()

    for i, title in enumerate(titles):
        if i in used:
            continue

        group = {
            "original_titles": [titles[i]],
            "cleaned_titles": [cleaned_titles[i]],
            "matched_job_ids": [job_ids[i]],
        }

        for j in range(i + 1, len(titles)):
            if j in used:
                continue
            cosine_sim = util.cos_sim(embeddings[i], embeddings[j]).item()
            fuzz_score = fuzz.token_sort_ratio(cleaned_titles[i], cleaned_titles[j]) / 100

            if cosine_sim > SIMILARITY_THRESHOLD or fuzz_score > (FUZZY_THRESHOLD / 100):
                used.add(j)
                group["original_titles"].append(titles[j])
                group["cleaned_titles"].append(cleaned_titles[j])
                group["matched_job_ids"].append(job_ids[j])

        most_common_clean = Counter(group["cleaned_titles"]).most_common(1)[0][0]
        group["canonical_title"] = most_common_clean.title()

        used.add(i)
        groups.append(group)

    return groups

def compute_trending_jobs():
    print("📊 Computing trending job scores...")

    df = fetch_all_jobs()

    existing_res = supabase.table("trending_jobs").select("matched_job_ids").execute()
    existing_ids = set()
    for row in existing_res.data:
        existing_ids.update(row.get("matched_job_ids", []))

    df = df[~df["job_id"].isin(existing_ids)].dropna(subset=["title", "job_id"])

    if df.empty:
        print("✅ No new job titles to process.")
        return

    titles = df["title"].tolist()
    job_ids = df["job_id"].tolist()
    clusters = cluster_similar_titles(titles, job_ids)

    batch_id = datetime.now().strftime("%Y%m%d")
    today = datetime.utcnow().date()

    cs_keywords = fetch_cs_keywords()

    for group in clusters:
        if not is_cs_related(group["canonical_title"].lower(), cs_keywords):
            continue

        matched_ids = group["matched_job_ids"]
        canonical_title = group["canonical_title"]
        group_df = df[df["job_id"].isin(matched_ids)]

        recent_cutoff = today - timedelta(days=DAYS_RECENT)
        prev_cutoff = recent_cutoff - timedelta(days=DAYS_PREV)

        recent_mentions = group_df[group_df["scraped_at"] >= recent_cutoff].shape[0]
        prev_mentions = group_df[(group_df["scraped_at"] < recent_cutoff) & (group_df["scraped_at"] >= prev_cutoff)].shape[0]

        growth = (recent_mentions - prev_mentions) / max(prev_mentions, 1)
        diversity = group_df["company"].nunique()

        trending_score = (
            TREND_WEIGHT * recent_mentions +
            GROWTH_WEIGHT * growth +
            DIVERSITY_WEIGHT * diversity
        )

        supabase.table("trending_jobs").insert({
            "title": canonical_title,
            "trending_score": round(trending_score, 2),
            "growth_rate": round(growth, 3),
            "mentions": recent_mentions,
            "company_diversity": diversity,
            "batch_id": batch_id,
            "date_computed": datetime.utcnow().isoformat(),
            "matched_job_ids": matched_ids
        }).execute()

        print(f"✅ {canonical_title}: {round(trending_score, 2)}")

if __name__ == "__main__":
    compute_trending_jobs()
