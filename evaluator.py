import os
import joblib
import numpy as np
from nltk.stem import PorterStemmer
from sentence_transformers import SentenceTransformer, util
from rapidfuzz import fuzz

ps = PorterStemmer()
bert_model = SentenceTransformer('all-MiniLM-L6-v2')


def normalize(skill):
    return ps.stem(skill.strip().lower())


def load_subject_model():
    model_path = "subject_success_model.pkl"
    if os.path.exists(model_path):
        print("🤖 ML model loaded for subject scoring.")
        return joblib.load(model_path)
    else:
        print("⚠️ ML model not found. Using fallback BERT logic.")
        return None


def load_feature_list():
    feature_path = "subject_model_features.pkl"
    if os.path.exists(feature_path):
        return joblib.load(feature_path)
    else:
        print("⚠️ Feature list not found. Using current job skills (may break ML prediction).")
        return None


def compute_subject_scores(subject_skills_map, job_skill_tree):
    model = load_subject_model()
    all_skills = load_feature_list() if model else sorted(job_skill_tree.keys())

    if not all_skills:
        print("❌ No job skills available for scoring.")
        return []

    all_skills_norm = [normalize(skill) for skill in all_skills]
    scored = []

    for course, subject_skills in subject_skills_map.items():
        if not subject_skills:
            print(f"⚠️ Skipping course with no skills: {course}")
            continue

        subject_skills_clean = [s.strip() for s in subject_skills if s.strip()]
        job_skills_clean = [k.strip() for k in job_skill_tree.keys() if k.strip()]

        if model:
            subj_skills_norm = [normalize(s) for s in subject_skills_clean]
            vector = []
            for job_skill_norm in all_skills_norm:
                matched = any(normalize(subj_skill) == job_skill_norm for subj_skill in subj_skills_norm)
                vector.append(1 if matched else 0)

            vector_np = np.array(vector).reshape(1, -1)
            try:
                predicted_score = model.predict(vector_np)[0]
            except Exception as e:
                print(f"❌ Model prediction failed for {course}: {e}")
                predicted_score = 0

            scored.append({
                "course": course,
                "skills_taught": subject_skills_clean,
                "skills_in_market": [],  # Not needed in ML mode
                "score": int(predicted_score)
            })

        else:
            if not job_skills_clean:
                print(f"❌ No job skills found. Cannot score: {course}")
                continue

            try:
                subj_embeddings = bert_model.encode(subject_skills_clean, convert_to_tensor=True)
                job_embeddings = bert_model.encode(job_skills_clean, convert_to_tensor=True)
                cosine_scores = util.cos_sim(subj_embeddings, job_embeddings)

                # Max similarity for each subject skill across all job skills
                max_similarities = [max(row).item() for row in cosine_scores]
                score = int(np.mean(max_similarities) * 100)

                # Also collect matched skills using a 0.6 threshold
                matched_skills = [
                    subject_skills_clean[i]
                    for i, sim in enumerate(max_similarities)
                    if sim >= 0.6
                ]

                # Fuzzy fallback (if nothing matched)
                if not matched_skills:
                    for subj in subject_skills_clean:
                        for job in job_skills_clean:
                            if fuzz.token_set_ratio(subj, job) > 85:
                                matched_skills.append(subj)
                                break

                    if matched_skills:
                        score = int((len(matched_skills) / len(subject_skills_clean)) * 100)

            except Exception as e:
                print(f"❌ BERT scoring failed for {course}: {e}")
                matched_skills = []
                score = 0

            scored.append({
                "course": course,
                "skills_taught": subject_skills_clean,
                "skills_in_market": matched_skills,
                "score": score
            })

    return sorted(scored, key=lambda x: x["score"], reverse=True)
