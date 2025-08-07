import re
from ..core.supabase_client import supabase
from nltk.corpus import stopwords
import nltk

nltk.download('stopwords')
nltk.download('punkt')

nltk_stopwords = set(stopwords.words('english'))

MIN_LENGTH = 3

CUSTOM_BLACKLIST = {
    "hiring", "urgent", "from", "with", "day", "night", "shift", "manager", "lead",
    "junior", "senior", "based", "home", "onsite", "hybrid", "office", "associate",
    "developer", "engineer", "staff", "location", "permanent", "certified", "experience",
    "support", "time", "expert", "solution", "project", "delivery", "grads", "start", "earn",
    "and", "only", "for", "own", "any", "role", "full", "back", "front", "work", "team",
    "new", "career", "within", "apply", "looking", "opportunity", "must", "will", "salary",
    "benefits", "skills", "required", "required", "available", "join", "apply", "now", "today",
    "vacancy", "vacancies", "vacant", "vacant", "vacancies", "vacant", "vacant", "vacant", "wfh", 
    "work from home", "remote", "flexible", "flexi", "flexible working", "flexible hours", "flexible schedule"
    "nighshift", "computer", "pasay", "makati", "qc", "manila", "taguig", "bpo", "call center",
    "pre",'desk', 'morning', 'service', 'boot', 'cebu', 'asap', 'help', 'nightshift', 'test', 'years', 
    'services', 'fresh', 'hours', 'high', 'online', 'pasig', 'level', 'bgc'
}

STOPWORDS = nltk_stopwords.union(CUSTOM_BLACKLIST)

def extract_terms(title):
    words = re.findall(r'\b[a-zA-Z]{%d,}\b' % MIN_LENGTH, title.lower())
    return set([
        w for w in words
        if w.lower() not in STOPWORDS and not w.isdigit()
    ])


def fetch_existing_keywords():
    res = supabase.table("cs_keywords").select("keyword").execute()
    return set(kw["keyword"].lower() for kw in res.data)

def update_cs_keywords():
    print("🔍 Updating CS keywords dynamically from job titles...")

    # Fetch all job titles
    res = supabase.table("jobs").select("title").execute()
    titles = [r["title"] for r in res.data if r.get("title")]

    # Extract terms and compare
    existing = fetch_existing_keywords()
    new_terms = set()

    for title in titles:
        for term in extract_terms(title):
            if term not in existing:
                new_terms.add(term)

    # Insert new keywords into Supabase
    if new_terms:
        print(f"➕ New keywords found: {new_terms}")
        insert_data = [{"keyword": kw} for kw in new_terms]
        supabase.table("cs_keywords").insert(insert_data).execute()
        print("✅ Supabase cs_keywords table updated.")
    else:
        print("📭 No new keywords found.")

if __name__ == "__main__":
    update_cs_keywords()
