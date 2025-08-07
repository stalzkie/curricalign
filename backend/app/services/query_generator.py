import os
import json
import joblib
import warnings
from collections import deque
from datetime import datetime, timezone
from dotenv import load_dotenv
from serpapi import GoogleSearch
from supabase import create_client, Client

# Load environment variables
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Suppress sklearn warning
warnings.filterwarnings("ignore", category=UserWarning)

# ML model path and history
MODEL_PATH = "query_quality_model.pkl"
USED_KEYWORDS_PATH = ".used_keywords.json"
MAX_SESSION_HISTORY = 3

def load_cs_terms_from_supabase():
    print("🔍 Fetching CS keywords from Supabase...")
    try:
        res = supabase.table("cs_keywords").select("keyword").execute()
        if not res.data:
            print("⚠️ Supabase returned an empty result for cs_keywords.")
            return set()
        terms = set(row["keyword"].lower() for row in res.data)
        print(f"✅ Loaded {len(terms)} CS keywords: {list(terms)[:10]}")
        return terms
    except Exception as e:
        print(f"❌ Failed to fetch CS terms from Supabase: {e}")
        return set()

CS_TERMS = load_cs_terms_from_supabase()

def contains_cs_term(query: str) -> bool:
    tokens = set(query.lower().split())
    return any(term in tokens for term in CS_TERMS)

# Try to load ML model
try:
    model = joblib.load(MODEL_PATH)
    USE_ML = True
    print("🤖 ML model loaded for query ranking.")
except Exception as e:
    print(f"⚠️ Failed to load ML model, using fallback scoring: {e}")
    USE_ML = False

def load_used_keywords():
    if not os.path.exists(USED_KEYWORDS_PATH):
        return deque(maxlen=MAX_SESSION_HISTORY)
    with open(USED_KEYWORDS_PATH, "r") as f:
        return deque(json.load(f), maxlen=MAX_SESSION_HISTORY)

def save_used_keywords(history: deque):
    with open(USED_KEYWORDS_PATH, "w") as f:
        json.dump(list(history), f)

def fallback_trend_score(query: str, value: float) -> float:
    score = float(value)
    if contains_cs_term(query):
        score += 10
    if len(query.split()) > 3:
        score -= 5
    return score

def ml_trend_score(query: str, value: float) -> float:
    is_cs = int(contains_cs_term(query))
    word_count = len(query.split())
    try:
        return model.predict([[is_cs, word_count, value]])[0]
    except Exception as e:
        print(f"❌ Prediction failed for '{query}': {e}")
        return fallback_trend_score(query, value)

def store_trending_keywords(keywords, scores, region="PH", source="google_trends"):
    print(f"📝 Storing {len(keywords)} trending keywords in Supabase from {source}...")
    now = datetime.now(timezone.utc).isoformat()
    try:
        entries = [
            {
                "query": q,
                "score": float(round(scores[q], 2)),
                "region": region,
                "source": source,
                "collected_at": now
            } for q in keywords
        ]
        supabase.table("trending_keywords").insert(entries).execute()
        print(f"✅ Stored {len(entries)} keywords to Supabase.")
    except Exception as e:
        print(f"❌ Failed to insert trending keywords: {e}")

def fallback_from_jobs(n=10):
    print("⚙️ Fallback 3: Extracting keywords from job titles...")
    try:
        job_rows = supabase.table("jobs") \
            .select("title") \
            .order("scraped_at", desc=True) \
            .limit(200) \
            .execute().data
        titles = [r["title"].lower() for r in job_rows if "title" in r]

        counter = {}
        for title in titles:
            for word in title.split():
                if word in CS_TERMS:
                    counter[word] = counter.get(word, 0) + 1

        fallback_sorted = sorted(counter.items(), key=lambda x: x[1], reverse=True)
        keywords = [w for w, _ in fallback_sorted][:n]
        print(f"✅ Extracted {len(keywords)} keywords from job titles: {keywords}")
        return keywords
    except Exception as e:
        print(f"❌ Fallback failed: {e}")
        return list(CS_TERMS)[:n]

def get_top_keywords(region="PH", n=10):
    print(f"\n🌐 Fetching Google Trends for job queries in region: {region}")

    seed_clusters = [
        "developer, software engineer, ai, data, cloud",
        "machine learning, devops, python, backend, frontend",
        "data analytics, computer science, cyber security, mobile dev",
        "web development, javascript, react, angular, vue",
        "full stack, data science, big data, blockchain, ar/vr",
        "it support, network engineer, database admin, system admin",
        "project management, scrum master, agile, product owner",
        "ui/ux design, product designer, digital marketing, seo",
        "cloud architect, solutions architect, enterprise architect"
    ]

    trend_pairs = []
    seen_queries = set()

    for cluster in seed_clusters:
        for seed in cluster.split(","):
            seed = seed.strip()
            print(f"🔍 Searching Google Trends for seed: '{seed}'")

            params = {
                "engine": "google_trends",
                "q": seed,
                "geo": region,
                "hl": "en",
                "date": "today 3-m",
                "api_key": SERPAPI_API_KEY,
                "data_type": "RELATED_QUERIES"
            }

            try:
                search = GoogleSearch(params)
                results = search.get_dict()
                if "related_queries" not in results:
                    print(f"⚠️ No related_queries returned for '{seed}': {results}")
                related = results.get("related_queries", {})
                trends = related.get("rising", []) + related.get("top", [])
                print(f"✅ Found {len(trends)} trends for '{seed}'")
            except Exception as e:
                print(f"❌ Google Trends error for seed '{seed}': {e}")
                trends = []

            for entry in trends:
                query = entry["query"].lower()
                raw_value = entry.get("value", 0)

                # ✅ Validate value before any processing
                try:
                    value = float(raw_value)
                except (ValueError, TypeError):
                    print(f"⚠️ Skipping invalid trend value '{raw_value}' for query '{query}'")
                    continue

                # ✅ Now safe to filter by seen queries
                if query in seen_queries:
                    continue
                seen_queries.add(query)

                score = ml_trend_score(query, value) if USE_ML else fallback_trend_score(query, value)
                trend_pairs.append((query, score))

            if len(trend_pairs) >= 3 * n:
                break

    sorted_trends = sorted(trend_pairs, key=lambda x: x[1], reverse=True)
    history = load_used_keywords()
    recently_used = set(kw for session in list(history)[:2] for kw in session)
    score_map = {q: s for q, s in trend_pairs}

    fresh_trends = [q for q, _ in sorted_trends if q not in recently_used][:n]

    if fresh_trends:
        print("\n📈 Trending Queries (Google Trends):")
        for q in fresh_trends:
            print(f"🔼 {q} — score: {round(score_map[q], 2)}")
        history.append(fresh_trends)
        save_used_keywords(history)
        store_trending_keywords(fresh_trends, score_map, region, source="google_trends")
        return fresh_trends

    elif sorted_trends:
        fallback = [q for q, _ in sorted_trends if q not in recently_used][:n]
        print("⚠️ Using Google Trends fallback due to history filter...")
        history.append(fallback)
        save_used_keywords(history)
        store_trending_keywords(fallback, score_map, region, source="google_trends_fallback")
        return fallback

    elif CS_TERMS:
        print("⚠️ Fallback 2: No Google Trends results. Using CS keywords from Supabase.")
        fallback_keywords = list(CS_TERMS)[:n]
        score_map = {q: fallback_trend_score(q, 5) for q in fallback_keywords}
        store_trending_keywords(fallback_keywords, score_map, region, source="cs_keywords")
        return fallback_keywords

    print("⚠️ Fallback 3: No CS keywords available. Using job title terms.")
    return fallback_from_jobs(n)

if __name__ == "__main__":
    keywords = get_top_keywords()
    print(f"\n🎯 Final keywords returned: {keywords}")
