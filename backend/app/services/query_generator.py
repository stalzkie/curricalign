import os
import re
import json
import joblib
import hashlib
import warnings
from collections import deque
from datetime import datetime, timezone
from typing import Set, Tuple, List, Dict, Any, Optional

import torch
from sentence_transformers import SentenceTransformer, util

# 🔑 MODERN SDK IMPORTS
from google import genai
from google.genai import types 

from serpapi import GoogleSearch
from supabase import create_client, Client

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Initialize Supabase Client
try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception as e:
    print(f"❌ Failed to initialize Supabase client: {e}")
    # You might want to mock or fail hard here in a real application

# Suppress sklearn warning
warnings.filterwarnings("ignore", category=UserWarning)

# ML model path and history
MODEL_PATH = "query_quality_model.pkl"
USED_KEYWORDS_PATH = ".used_keywords.json"
MAX_SESSION_HISTORY = 3


# Defaults (safe base) and dynamic term loading from Supabase
DEFAULT_STRONG: Set[str] = {
    "python","java","javascript","typescript","c","c++","c#","go","golang","rust","php","ruby","sql",
    "developer","software engineer","backend","frontend","full stack","devops","sre",
    "data engineer","data scientist","machine learning","ai","nlp","computer vision","deep learning",
    "cloud","aws","gcp","azure","kubernetes","docker","linux","git","github","gitlab","ci","cd",
    "react","next.js","vue","angular","node.js","spring","django","flask","laravel",".net","asp.net",
    "database","postgres","mysql","mongodb","redis","elasticsearch",
    "cybersecurity","security engineer","network engineer","sysadmin",
    "api","microservices","distributed systems","computer science"
}
DEFAULT_MODERATE: Set[str] = {
    "engineering","engineer","architect","architecture","design","designer","systems","infrastructure","platform"
}
DEFAULT_NEGATIVE: Set[str] = {
    "interior","civil","mechanical","electrical","structural","architectural",
    "construction","furniture","landscape","quantity","surveyor","autocad","revit",
    "plumbing","masonry","estimator","site supervisor","drafter","cad technician"
}
CS_MODIFIERS: Set[str] = {
    "software","computer","computing","programming","code","coding","it","data","cloud","ai","ml",
    "cyber","security","systems","network","web","app","application","dev","backend","frontend","fullstack"
}

def _load_terms(table: str, defaults: Set[str]) -> Set[str]:
    """Merge DB-hosted terms with safe defaults so you can tweak without redeploys."""
    try:
        res = supabase.table(table).select("keyword").execute()
        db = {r["keyword"].lower() for r in (res.data or []) if r.get("keyword")}
        return defaults | db
    except Exception as e:
        print(f"❌ Failed to fetch {table}: {e}")
        return defaults

STRONG_CS_TERMS = _load_terms("cs_strong_terms", DEFAULT_STRONG)
MODERATE_TERMS  = _load_terms("cs_moderate_terms", DEFAULT_MODERATE)
NEGATIVE_TERMS  = _load_terms("cs_negative_terms", DEFAULT_NEGATIVE)


# Tokenizer with unigrams+bigrams (keeps c#, c++, .net intact)

def _tokens_and_ngrams(text: str) -> Set[str]:
    clean = re.sub(r"[^a-z0-9#+.\s]", " ", text.lower())
    toks = [t for t in clean.split() if t]
    bigrams = [" ".join(p) for p in zip(toks, toks[1:])]
    return set(toks) | set(bigrams)


# Fast Gate (cheap, deterministic)

def is_cs_query_fast(query: str) -> Optional[bool]:
    """
    Return True/False when clear; None when uncertain (defer to semantic/Gemini).
    """
    toks = _tokens_and_ngrams(query)

    # Strong term present = allow
    if any(t in toks for t in STRONG_CS_TERMS):
        return True

    # Negative term with no strong CS term = block
    if any(n in toks for n in NEGATIVE_TERMS) and not any(t in toks for t in STRONG_CS_TERMS):
        return False

    # Moderate + CS modifier = allow
    if any(m in toks for m in MODERATE_TERMS) and any(c in toks for c in CS_MODIFIERS):
        return True

    return None  # borderline

# Semantic Gate (centroids) — robust to new tech wording

_embedder = SentenceTransformer("all-MiniLM-L6-v2")

CS_EXTRAS    = [
    "software development","computer programming","cloud computing","api design",
    "distributed systems","data pipelines","kubernetes operations","frontend development",
    "backend services","machine learning engineering","database administration"
]
NONCS_EXTRAS = [
    "interior design","civil engineering","mechanical engineering","structural engineering",
    "home renovation","building construction","furniture layout","landscape design"
]

def _build_centroid(terms: Set[str], extras: List[str]):
    corpus = list(terms | set(extras))
    embs = _embedder.encode(corpus, convert_to_tensor=True)
    centroid = torch.nn.functional.normalize(embs.mean(dim=0, keepdim=True), p=2, dim=1)
    return centroid

_CS_CENTROID    = _build_centroid(STRONG_CS_TERMS | CS_MODIFIERS, CS_EXTRAS)
_NONCS_CENTROID = _build_centroid(NEGATIVE_TERMS | {"interior design","civil engineering"}, NONCS_EXTRAS)

SEMANTIC_MIN    = 0.45  # must be at least this similar to CS centroid
SEMANTIC_MARGIN = 0.07  # must beat Non‑CS by this margin

def _semantic_gate(query: str) -> Optional[bool]:
    q = _embedder.encode([query], convert_to_tensor=True)
    q = torch.nn.functional.normalize(q, p=2, dim=1)
    s_cs = float(util.cos_sim(q, _CS_CENTROID)[0][0])
    s_nc = float(util.cos_sim(q, _NONCS_CENTROID)[0][0])

    if (s_cs >= SEMANTIC_MIN) and (s_cs - s_nc >= SEMANTIC_MARGIN):
        return True
    if (s_nc >= SEMANTIC_MIN) and (s_nc - s_cs >= SEMANTIC_MARGIN):
        return False
    return None  # still borderline


# Gemini Cross‑Reference (only for borderline)
# 🎯 REVISED: Initialize the modern client
client = genai.Client(
    api_key=GEMINI_API_KEY, 
    http_options=types.HttpOptions(api_version='v1')
) 
_GEMINI_MODEL = "gemini-1.5-flash" # Use a fast, stable model for classification
_GCACHE: Dict[str, Dict[str, Any]] = {}

GEMINI_SYSTEM = """You are a classifier that decides if a query is about computer science / software / IT.
Output ONLY strict JSON: {"is_cs": bool, "confidence": float, "reason": "short", "tags": ["keywords..."]}

CS-related: software engineering, programming, data/AI/ML, cloud/devops, web/mobile, databases, networking, cybersecurity, systems.
Product/design counts only if clearly about digital/software (e.g., "UX for mobile app", "API design patterns").
NOT CS-related: civil/mechanical/electrical/structural engineering unless explicitly about computing/software;
interior/furniture/landscape design, construction, building, architecture unless explicitly software/IT.
"""

GEMINI_FEWSHOTS = [
    ("interior design portfolio ideas", {"is_cs": False, "confidence": 0.98, "reason": "Interior design domain", "tags": ["interior design"]}),
    ("data engineering pipelines with airflow", {"is_cs": True, "confidence": 0.96, "reason": "Data engineering tooling", "tags": ["data engineering","airflow"]}),
    ("civil engineering estimation software", {"is_cs": False, "confidence": 0.8, "reason": "Civil domain; software incidental", "tags": ["civil engineering"]}),
    ("ux design patterns for react apps", {"is_cs": True, "confidence": 0.9, "reason": "Frontend software design", "tags": ["ux","react"]}),
]

def _ck(q: str) -> str:
    return hashlib.sha1(q.strip().lower().encode()).hexdigest()

def gemini_cs_check(query: str) -> Dict[str, Any]:
    """
    Returns: {"is_cs": bool, "confidence": float, "reason": str, "tags": [..]}
    Falls back safely on parse errors.
    """
    k = _ck(query)
    if k in _GCACHE:
        return _GCACHE[k]

    fewshots = "\n\n".join([
        f"Example {i} Query: {q}\nExample {i} JSON: {json.dumps(ans, ensure_ascii=False)}"
        for i, (q, ans) in enumerate(GEMINI_FEWSHOTS, 1)
    ])
    prompt = f"""{GEMINI_SYSTEM}

{fewshots}

Classify this query now. Return ONLY JSON, no extra text.
Query: {query}
"""
    try:
        # 🎯 UPDATED: Use client.models.generate_content()
        resp = client.models.generate_content(
            model=_GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0, 
                max_output_tokens=120,
                response_mime_type="application/json"
            )
        )
        raw = (resp.text or "").strip().strip("`").lstrip("json").strip()
        data = json.loads(raw)
        out = {
            "is_cs": bool(data.get("is_cs", False)),
            "confidence": float(data.get("confidence", 0.0)),
            "reason": str(data.get("reason", ""))[:200],
            "tags": [t for t in data.get("tags", []) if isinstance(t, str)],
        }
    except Exception as e:
        print(f"❌ Gemini call failed for '{query}': {e}")
        out = {"is_cs": False, "confidence": 0.0, "reason": f"parse_error: {e}", "tags": []}

    _GCACHE[k] = out
    return out

# Final “three‑fallback” CS gate

def is_cs_query(query: str) -> bool:
    # 1) Fast gate
    fast = is_cs_query_fast(query)
    if fast is True:
        return True
    if fast is False:
        return False

    # 2) Semantic gate
    sem = _semantic_gate(query)
    if sem is True:
        return True
    if sem is False:
        return False

    # 3) Gemini cross‑reference
    g = gemini_cs_check(query)
    return bool(g["is_cs"] and g["confidence"] >= 0.70)

# ML scoring & history helpers

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
    try:
        with open(USED_KEYWORDS_PATH, "r") as f:
            return deque(json.load(f), maxlen=MAX_SESSION_HISTORY)
    except Exception:
        return deque(maxlen=MAX_SESSION_HISTORY)

def save_used_keywords(history: deque):
    with open(USED_KEYWORDS_PATH, "w") as f:
        json.dump(list(history), f)

def fallback_trend_score(query: str, value: float) -> float:
    score = float(value)
    score += 10 if is_cs_query(query) else -15  # prefer CS, penalize non‑CS
    if len(query.split()) > 3:
        score -= 5
    return score

def ml_trend_score(query: str, value: float) -> float:
    is_cs = int(is_cs_query(query))
    word_count = len(query.split())
    try:
        return float(model.predict([[is_cs, word_count, value]])[0])
    except Exception as e:
        print(f"❌ Prediction failed for '{query}': {e}")
        return fallback_trend_score(query, value)


# Storage helpers

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

# Fallback extraction from jobs (filtered by CS gate)

def fallback_from_jobs(n=10):
    print("⚙️ Fallback 3: Extracting keywords from job titles...")
    try:
        job_rows = supabase.table("jobs") \
            .select("title") \
            .order("scraped_at", desc=True) \
            .limit(200) \
            .execute().data
        titles = [r["title"].lower() for r in (job_rows or []) if "title" in r]

        counter: Dict[str, int] = {}
        for title in titles:
            if not is_cs_query(title):
                continue
            for word in title.split():
                lw = word.lower()
                if (lw in STRONG_CS_TERMS) or (lw in CS_MODIFIERS):
                    counter[lw] = counter.get(lw, 0) + 1

        fallback_sorted = sorted(counter.items(), key=lambda x: x[1], reverse=True)
        keywords = [w for w, _ in fallback_sorted][:n]
        print(f"✅ Extracted {len(keywords)} keywords from job titles: {keywords}")
        return keywords
    except Exception as e:
        print(f"❌ Fallback failed: {e}")
        # last resort: use strong terms list
        return list(STRONG_CS_TERMS)[:n]

# Main: fetch top keywords from Google Trends (with CS filter)

def get_top_keywords(region="PH", n=10):
    print(f"\n🌐 Fetching Google Trends for job queries in region: {region}")

    seed_clusters = [
        "developer, software engineer, ai, data, cloud",
        "machine learning, devops, python, backend, frontend",
        "data analytics, computer science, cyber security, mobile development",
        "web development, javascript, react, angular, vue",
        "full stack, data science, big data, blockchain, ar/vr",
        "it support, network engineer, database admin, system admin",
        "software project management, scrum master, agile, software product owner",
        "ui/ux design, software product designer, digital marketing, seo",
        "cloud architect, solutions architect, enterprise architect"
    ]

    trend_pairs: List[Tuple[str, float]] = []
    seen_queries: Set[str] = set()

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
                query = str(entry.get("query", "")).lower()
                raw_value = entry.get("value", 0)

                # Validate value before any processing
                try:
                    value = float(raw_value)
                except (ValueError, TypeError):
                    print(f"⚠️ Skipping invalid trend value '{raw_value}' for query '{query}'")
                    continue

                # Hard CS filter before scoring/storing
                if not is_cs_query(query):
                    continue

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

    # No trends = fall back to CS terms or jobs
    print("⚠️ Fallback 2: No Google Trends results. Using CS keywords from Supabase/strong terms.")
    fallback_keywords = list(STRONG_CS_TERMS)[:n]
    if not fallback_keywords:
        print("⚠️ Fallback 3: No CS strong terms available. Using job title terms.")
        return fallback_from_jobs(n)

    score_map = {q: fallback_trend_score(q, 5) for q in fallback_keywords}
    store_trending_keywords(fallback_keywords, score_map, region, source="cs_keywords/strong_terms")
    return fallback_keywords

# surface candidate new terms for promotion

def audit_candidates(accepted_queries: List[str]):
    candidates = set()
    for q in accepted_queries:
        toks = _tokens_and_ngrams(q)
        # if query passed but didn't include any strong term and no negatives,
        # suggest tokens for promotion
        if not any(t in toks for t in STRONG_CS_TERMS) and not any(n in toks for n in NEGATIVE_TERMS):
            for t in toks:
                if len(t) >= 3 and t not in (STRONG_CS_TERMS | NEGATIVE_TERMS | MODERATE_TERMS | CS_MODIFIERS):
                    candidates.add(t)
    if candidates:
        print("💡 Candidate CS terms to consider:", list(sorted(candidates))[:20])
        try:
            supabase.table("cs_candidate_terms").insert([{"keyword": k} for k in candidates]).execute()
        except Exception as e:
            print(f"❌ Failed to insert candidate terms: {e}")

# Entry point

if __name__ == "__main__":
    kw = get_top_keywords()
    print(f"\n🎯 Final keywords returned: {kw}")
    audit_candidates(kw)