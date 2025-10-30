import pandas as pd
import re
from datetime import datetime
from pathlib import Path

# === Paths ===
INPUT_PATH  = Path(__file__).resolve().parent / "cleaned_courses.csv"
OUTPUT_PATH = Path(__file__).resolve().parent / "final_courses.csv"

# === Load data ===
df = pd.read_csv(INPUT_PATH)
print(f"📄 Loaded {len(df)} rows from {INPUT_PATH.name}")

# === Normalize column names ===
df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

# === Ensure required columns exist ===
expected_cols = ["course_id", "course_code", "course_title", "course_description"]
for col in expected_cols:
    if col not in df.columns:
        df[col] = None

# === Drop duplicates (by title + description) ===
before = len(df)
df = df.drop_duplicates(subset=["course_title", "course_description"], keep="first")
print(f"🧹 Removed {before - len(df)} duplicates")

# === Remove rows missing critical info ===
df = df.dropna(subset=["course_title", "course_description"])
df = df[df["course_title"].astype(str).str.strip() != ""]
df = df[df["course_description"].astype(str).str.strip() != ""]

# === Remove extremely short or useless descriptions ===
df = df[df["course_description"].apply(lambda x: len(str(x)) >= 30)]

# === Remove HTML tags, excess spaces, and weird symbols ===
def clean_text(text: str) -> str:
    text = re.sub(r"<.*?>", " ", str(text))      # remove HTML
    text = re.sub(r"\s+", " ", text)             # collapse spaces
    text = re.sub(r"[^\w\s.,;:!?()\-'/&]", "", text)  # remove non-text noise
    return text.strip()

df["course_title"] = df["course_title"].apply(clean_text)
df["course_description"] = df["course_description"].apply(clean_text)

# === Optional: Keep only CS/IT-related courses ===
cs_keywords = [
    "computer", "software", "data", "information", "programming",
    "network", "algorithm", "database", "system", "security",
    "web", "ai", "artificial", "machine", "cyber", "it", "technology"
]
pattern = "|".join(cs_keywords)
df = df[df["course_title"].str.lower().str.contains(pattern) |
        df["course_description"].str.lower().str.contains(pattern)]

print(f"💻 Filtered to {len(df)} CS/IT-related courses")

# === Add or refresh created_at ===
df["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# === Reorder columns and save ===
df = df[["course_id", "course_code", "course_title", "course_description", "created_at"]]
df.to_csv(OUTPUT_PATH, index=False)
print(f"✅ Cleaned dataset saved → {OUTPUT_PATH.name} ({len(df)} rows)")
