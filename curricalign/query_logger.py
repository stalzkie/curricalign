import csv
import os

LOG_FILE = "query_training_data.csv"

def log_query(query, is_cs_term, word_count, trend_value, jobs_returned, matched_skills_count, avg_subject_score=None):
    """
    Logs the result of a used query to the CSV dataset for ML training.
    """
    file_exists = os.path.isfile(LOG_FILE)

    with open(LOG_FILE, mode="a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=[
            "query", "is_cs_term", "word_count", "trend_value",
            "jobs_returned", "matched_skills_count", "query_score"
        ])
        if not file_exists:
            writer.writeheader()

        writer.writerow({
            "query": query,
            "is_cs_term": is_cs_term,
            "word_count": word_count,
            "trend_value": trend_value,
            "jobs_returned": jobs_returned,
            "matched_skills_count": matched_skills_count,
            "query_score": avg_subject_score if avg_subject_score is not None else 0
        })
