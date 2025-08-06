import os
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.model_selection import train_test_split, cross_val_score, KFold
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import mean_absolute_error, r2_score
from sentence_transformers import SentenceTransformer, util
from backend.app.services.syllabus_matcher import extract_subject_skills_from_supabase
from backend.app.services.skill_extractor import extract_skills_from_jobs
from backend.app.services.evaluator import normalize_skills

bert_model = SentenceTransformer("all-MiniLM-L6-v2")


def compute_semantic_vector(course_skills, market_skills):
    """
    For each market skill, compute its max similarity to any course skill.
    Returns a real-valued vector of shape (len(market_skills),)
    """
    if not course_skills or not market_skills:
        return np.zeros(len(market_skills))

    try:
        subj_embeddings = bert_model.encode(course_skills, convert_to_tensor=True)
        market_embeddings = bert_model.encode(market_skills, convert_to_tensor=True)
        cosine_scores = util.cos_sim(market_embeddings, subj_embeddings)  # market x subject
        vector = np.max(cosine_scores.cpu().numpy(), axis=1)  # max sim per market skill
        return vector
    except Exception as e:
        print(f"❌ BERT vectorization failed: {e}")
        return np.zeros(len(market_skills))


def train_subject_score_model():
    print("📄 Loading syllabus from course_descriptions.py ...")
    subject_skills_map = extract_subject_skills_from_supabase()
    if not subject_skills_map:
        print("❌ No subjects parsed. Exiting.")
        return

    print("🌐 Extracting job skill frequency from jobs...")
    job_skill_tree = extract_skills_from_jobs()
    if not job_skill_tree:
        print("❌ No skills extracted from jobs. Exiting.")
        return

    all_market_skills = sorted(set([normalize_skills([skill])[0] for skill in job_skill_tree.keys() if skill.strip()]))
    if not all_market_skills:
        print("❌ No usable job skills found after cleaning.")
        return

    joblib.dump(all_market_skills, "subject_model_features.pkl")
    print(f"📦 Saved normalized feature list ({len(all_market_skills)} skills) to subject_model_features.pkl")

    print("🧠 Generating simulated labels using BERT similarity scoring...")
    from backend.app.services.evaluator import compute_subject_scores  # Avoid circular import
    scored_subjects = compute_subject_scores(subject_skills_map, job_skill_tree)
    if len(scored_subjects) < 2:
        print(f"❌ Not enough training samples ({len(scored_subjects)}). Need at least 2.")
        return

    X, y, records = [], [], []

    print("🧮 Encoding training vectors using BERT similarity...")
    for item in scored_subjects:
        taught_skills = item["skills_taught"]
        if not taught_skills:
            continue

        try:
            taught_clean = [s.lower().strip() for s in taught_skills if s.strip()]
            vector = compute_semantic_vector(taught_clean, all_market_skills)
            X.append(vector)
            y.append(item["score"])
            records.append({
                "course": item["course"],
                "skills_taught": ", ".join(taught_clean),
                "skills_in_market": ", ".join(item["skills_in_market"]),
                "score": item["score"]
            })
        except Exception as e:
            print(f"❌ Feature generation failed for {item['course']}: {e}")

    if len(X) < 2:
        print("❌ Not enough feature samples to train. Exiting.")
        return

    X, y = np.array(X), np.array(y)
    pd.DataFrame(records).to_csv("bert_course_scores.csv", index=False)
    print("📄 Saved raw matches to bert_course_scores.csv")

    models = {
        "RandomForest": RandomForestRegressor(n_estimators=150, max_depth=12, random_state=42),
        "GradientBoosting": GradientBoostingRegressor(n_estimators=200, learning_rate=0.08, max_depth=5, random_state=42),
        "RidgeRegression": Ridge(alpha=1.0)
    }

    print("\n🔍 Cross-validating models...")
    best_model, best_score = None, -np.inf
    cv_splits = min(5, len(X))
    kf = KFold(n_splits=cv_splits, shuffle=True, random_state=42)

    for name, model in models.items():
        pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("regressor", model)
        ])
        try:
            scores = cross_val_score(pipeline, X, y, cv=kf, scoring="r2")
            avg_score = np.mean(scores)
            print(f"✅ {name}: Avg R² = {avg_score:.3f}")
            if avg_score > best_score:
                best_model = pipeline
                best_score = avg_score
        except Exception as e:
            print(f"❌ {name} failed: {e}")

    if not best_model:
        print("❌ No model was successfully trained.")
        return

    print("\n🏋️ Training best model on full dataset...")
    best_model.fit(X, y)
    joblib.dump(best_model, "subject_success_model.pkl")
    print("✅ Model saved as: subject_success_model.pkl")

    # Final holdout check
    if len(X) > 4:
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        best_model.fit(X_train, y_train)
        predictions = best_model.predict(X_test)
        print("\n🧪 Final Holdout Evaluation:")
        print(f"MAE: {mean_absolute_error(y_test, predictions):.2f}")
        print(f"R²: {r2_score(y_test, predictions):.3f}")


if __name__ == "__main__":
    train_subject_score_model()
