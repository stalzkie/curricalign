import pandas as pd
from datetime import datetime

# Load your raw CSV
df = pd.read_csv("/Users/stal/Documents/Projects/curricalign/backend/app/ml/all_courses.csv")

# ---- Inspect the file to understand column names ----
print("Original columns:", df.columns.tolist())
print(df.head(3))

# ---- Normalize column names ----
df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]

# ---- Try to detect your existing fields ----
# Modify these depending on your CSV’s actual headers
possible_id_cols = [c for c in df.columns if "id" in c or "code" in c]
possible_title_cols = [c for c in df.columns if "title" in c or "name" in c]
possible_desc_cols = [c for c in df.columns if "desc" in c or "summary" in c]

print("Detected:", possible_id_cols, possible_title_cols, possible_desc_cols)

# ---- Map to your desired structure ----
df_clean = pd.DataFrame({
    "course_id": df[possible_id_cols[0]] if possible_id_cols else range(1, len(df)+1),
    "course_code": df[possible_id_cols[0]] if possible_id_cols else None,
    "course_title": df[possible_title_cols[0]] if possible_title_cols else None,
    "course_description": df[possible_desc_cols[0]] if possible_desc_cols else "",
    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
})

# ---- Drop duplicates and rows with no title ----
df_clean.drop_duplicates(subset=["course_code", "course_title"], inplace=True)
df_clean.dropna(subset=["course_title"], inplace=True)

# ---- Save cleaned CSV ----
df_clean.to_csv("cleaned_courses.csv", index=False)
print("✅ Cleaned file saved as cleaned_courses.csv")
