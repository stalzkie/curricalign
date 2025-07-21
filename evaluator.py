import joblib
import numpy as np
import os
from nltk.stem import PorterStemmer
from sentence_transformers import SentenceTransformer, util

ps = PorterStemmer()

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

# Load BERT model once
bert_model = SentenceTransformer('all-MiniLM-L6-v2')

def compute_subject_scores(subject_skills_map, job_skill_tree):
    model = load_subject_model()
    all_skills = load_feature_list() if model else sorted(job_skill_tree.keys())
    all_skills_norm = [normalize(skill) for skill in all_skills]

    scored = []

    for course, subject_skills in subject_skills_map.items():
        if model and all_skills:
            subj_skills_norm = [normalize(s) for s in subject_skills]

            vector = []
            for job_skill_norm in all_skills_norm:
                matched = any(
                    normalize(subj_skill) == job_skill_norm
                    for subj_skill in subj_skills_norm
                )
                vector.append(1 if matched else 0)

            vector_np = np.array(vector).reshape(1, -1)

            try:
                predicted_score = model.predict(vector_np)[0]
            except Exception as e:
                print(f"❌ Model prediction failed for {course}: {e}")
                predicted_score = 0

            scored.append({
                "course": course,
                "skills_taught": subject_skills,
                "skills_in_market": [],
                "score": int(predicted_score)
            })

        else:
            # 🔁 BERT-based fallback
            matched_skills = []
            subj_embeddings = bert_model.encode(subject_skills, convert_to_tensor=True)
            job_embeddings = bert_model.encode(list(job_skill_tree.keys()), convert_to_tensor=True)

            cosine_scores = util.cos_sim(subj_embeddings, job_embeddings)

            for i, row in enumerate(cosine_scores):
                if any(score >= 0.75 for score in row):
                    matched_skills.append(subject_skills[i])

            score = int((len(matched_skills) / len(subject_skills)) * 100) if subject_skills else 0

            scored.append({
                "course": course,
                "skills_taught": subject_skills,
                "skills_in_market": matched_skills,
                "score": score
            })

    return sorted(scored, key=lambda x: x["score"], reverse=True)
