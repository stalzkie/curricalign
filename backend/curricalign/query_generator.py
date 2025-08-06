import os
import json
import joblib
from collections import deque
from dotenv import load_dotenv
from serpapi import GoogleSearch

# Load environment variables
load_dotenv()
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")

# ML model path
MODEL_PATH = "query_quality_model.pkl"

# Past keyword history tracking
USED_KEYWORDS_PATH = ".used_keywords.json"
MAX_SESSION_HISTORY = 3

# CS-focused keywords whitelist
CS_TERMS = {
    "python", "java", "developer", "data analytics", "cloud engineer", "software", "software engineering",
    "fullstack", "backend", "frontend", "machine learning", "product design", "analyst", "business intelligence", "devops",
    "cybersecurity", "react", "artificial intelligence", "android", "ios",
    "flutter", "unity", "web", "front end security", "project management", "it support", "aws"
}

# Try to load ML model for query ranking
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


def fallback_trend_score(query: str, value: int) -> int:
    score = value
    if any(term in query for term in CS_TERMS):
        score += 10
    if len(query.split()) > 3:
        score -= 5
    return score


def ml_trend_score(query: str, value: int) -> float:
    """Use trained model to predict query quality."""
    is_cs = int(any(term in query for term in CS_TERMS))
    word_count = len(query.split())
    try:
        return model.predict([[is_cs, word_count, value]])[0]
    except Exception as e:
        print(f"❌ Prediction failed for '{query}': {e}")
        return fallback_trend_score(query, value)


def get_top_keywords(region="PH", n=10):
    print(f"🌐 Fetching Google Trends for job queries in region: {region}")

    params = {
        "engine": "google_trends",
        "q": "developer computer science jobs",
        "geo": region,
        "hl": "en",
        "api_key": SERPAPI_API_KEY
    }

    try:
        search = GoogleSearch(params)
        results = search.get_dict()
        related = results.get("related_queries", {})
        rising = related.get("rising", [])
        top = related.get("top", [])
        all_trends = rising + top
    except Exception as e:
        print(f"❌ SerpAPI Google Trends Error: {e}")
        all_trends = []

    trend_pairs = []
    for entry in all_trends:
        query = entry["query"].lower()
        value = entry.get("value", 0)

        if any(term in query for term in CS_TERMS):
            score = ml_trend_score(query, value) if USE_ML else fallback_trend_score(query, value)
            trend_pairs.append((query, score))

    sorted_trends = sorted(trend_pairs, key=lambda x: x[1], reverse=True)

    # Remove recently used keywords
    history = load_used_keywords()
    recently_used = set(kw for session in list(history)[:2] for kw in session)

    fresh_trends = [query for query, _ in sorted_trends if query not in recently_used][:n]

    if not fresh_trends:
        print("⚠️ No fresh or trending CS keywords found. Falling back to static CS_TERMS.")
        fresh_trends = list(CS_TERMS)[:n]

    history.append(fresh_trends)
    save_used_keywords(history)

    print(f"✅ Trending job queries: {fresh_trends}")
    return fresh_trends