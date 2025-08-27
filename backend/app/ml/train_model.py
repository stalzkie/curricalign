import os
import warnings
import joblib
import numpy as np
import pandas as pd
from collections import defaultdict
from datetime import datetime, timezone   # added timezone to avoid deprecation warnings
from pathlib import Path  # ← added

# scikit-learn stuff
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import pairwise_distances
from sklearn.model_selection import GroupKFold, RandomizedSearchCV, train_test_split
from sklearn.decomposition import TruncatedSVD
from sklearn.kernel_ridge import KernelRidge
from sklearn.pipeline import Pipeline
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.isotonic import IsotonicRegression
from sklearn.preprocessing import StandardScaler  # might be used later
from scipy.stats import loguniform

# sentence embeddings
from sentence_transformers import SentenceTransformer

# import functions from our backend services
from backend.app.services.syllabus_matcher import extract_subject_skills_from_supabase
from backend.app.services.skill_extractor import extract_skills_from_jobs
from backend.app.services.evaluator import normalize_skills, compute_subject_scores

# Config
# we use a pretrained BERT-like model to embed skills
EMBED_MODEL = "all-MiniLM-L6-v2"
bert_model = SentenceTransformer(EMBED_MODEL)

# clustering settings
CLUSTER_DISTANCE_THRESHOLD = 0.35  # smaller = more clusters
TOPK = 3                           # take top-3 most similar skills
RECENCY_HALFLIFE_DAYS = None       # if set, weights newer skills higher

# ---------------- paths pinned to backend/app/ml ----------------
ML_DIR = Path(__file__).resolve().parent
ML_DIR.mkdir(parents=True, exist_ok=True)

# file names where we save intermediate results
FEATURE_SKILLS_FILE = ML_DIR / "subject_model_features.pkl"
MODEL_BUNDLE_FILE   = ML_DIR / "subject_success_model.pkl"
COURSE_SCORES_CSV   = ML_DIR / "bert_course_scores.csv"
# ----------------------------------------------------------------

# Utilities
def _parse_date(s):
    """try to parse a string as a date, else return None"""
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        return None

def clean_market_skills(raw_skills: list[str]) -> list[str]:
    """normalize raw job skills (lowercase, strip spaces, etc.)"""
    skills = []
    for skill in raw_skills:
        if not isinstance(skill, str):
            continue
        cleaned = skill.strip().lower()
        if cleaned:
            norm = normalize_skills([cleaned])  # further normalization
            if norm:
                skills.append(norm[0])
    return skills

def encode_norm(texts: list[str]) -> np.ndarray:
    """encode text into normalized embeddings"""
    if not texts:
        return np.zeros((0, bert_model.get_sentence_embedding_dimension()), dtype=np.float32)
    return bert_model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)

def topk_mean(a: np.ndarray, k=3, axis=-1) -> np.ndarray:
    """take mean of top-k values along axis"""
    if a.size == 0:
        return np.array([], dtype=np.float32)
    k = max(1, min(k, a.shape[axis]))
    idx = np.argpartition(a, kth=-k, axis=axis)
    topk_idx = np.take(idx, indices=range(a.shape[axis]-k, a.shape[axis]), axis=axis)
    topk_vals = np.take_along_axis(a, topk_idx, axis=axis)
    return topk_vals.mean(axis=axis)

# Clustering job skills
def cluster_market_skills(all_market_skills: list[str]):
    """
    Cluster similar job skills into groups using agglomerative clustering.
    Returns cluster centers, members, labels, and embeddings.
    """
    market_embeddings = encode_norm(all_market_skills)
    if len(all_market_skills) <= 1:
        # edge case: only one skill
        return (market_embeddings.copy(),
                [list(range(len(all_market_skills)))],
                np.zeros(len(all_market_skills), dtype=int),
                market_embeddings)

    dist = pairwise_distances(market_embeddings, metric="cosine")

    # handle sklearn version differences (metric vs affinity)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            clustering = AgglomerativeClustering(
                metric="precomputed",
                linkage="average",
                distance_threshold=CLUSTER_DISTANCE_THRESHOLD,
                n_clusters=None,
                compute_full_tree=True,
            )
        except TypeError:
            clustering = AgglomerativeClustering(
                affinity="precomputed",
                linkage="average",
                distance_threshold=CLUSTER_DISTANCE_THRESHOLD,
                n_clusters=None,
                compute_full_tree=True,
            )
        labels = clustering.fit_predict(dist)

    # group skills by cluster
    cluster2idxs = defaultdict(list)
    for i, c in enumerate(labels):
        cluster2idxs[c].append(i)

    # compute cluster centroids (mean embedding)
    cluster_centroids = []
    cluster_members = []
    for c, idxs in sorted(cluster2idxs.items()):
        cluster_centroids.append(market_embeddings[idxs].mean(axis=0))
        cluster_members.append(idxs)

    cluster_centroids = np.vstack(cluster_centroids)
    return cluster_centroids, cluster_members, labels, market_embeddings

# Feature Engineering
def compute_demand_weights_per_cluster(cluster_members, all_market_skills, job_skill_tree, recency_halflife_days=None):
    """
    Compute demand weights per cluster.
    More frequent (and newer) skills increase the weight.
    """
    cluster_freq = np.zeros(len(cluster_members), dtype=np.float32)
    today = datetime.now(timezone.utc).date()

    for c, idxs in enumerate(cluster_members):
        f = 0.0
        weight_sum = 0.0
        for i in idxs:
            skill = all_market_skills[i]
            info = job_skill_tree.get(skill)
            # job_skill_tree maps skill -> count or dict with count + last_seen
            if isinstance(info, (int, float)):
                count = float(info)
                last_seen = None
            elif isinstance(info, dict):
                count = float(info.get('count', 1.0))
                last_seen = _parse_date(str(info.get('last_seen'))) if info.get('last_seen') else None
            else:
                count = 1.0
                last_seen = None

            rec_boost = 1.0
            if recency_halflife_days and last_seen:
                # exponential decay: newer = higher weight
                days_ago = max(0, (today - last_seen).days)
                rec_boost = np.exp(-np.log(2) * days_ago / recency_halflife_days)

            f += count * rec_boost
            weight_sum += 1.0

        if weight_sum > 0:
            f = f / weight_sum
        cluster_freq[c] = f

    if cluster_freq.max() > 0:
        cluster_freq /= cluster_freq.max()
    return cluster_freq

def compute_course_cluster_features(course_skills, cluster_centroids, cluster_members, all_market_skills, job_skill_tree, topk=TOPK):
    """compute feature vector for a course based on skill similarity + demand"""
    if not course_skills or cluster_centroids.size == 0:
        return np.zeros(len(cluster_members), dtype=np.float32)

    cs_emb = encode_norm(course_skills)           # encode course skills
    sims = cs_emb @ cluster_centroids.T           # cosine similarity
    pooled = topk_mean(sims, k=topk, axis=0)      # take top-k similarity per cluster

    cluster_freq = compute_demand_weights_per_cluster(
        cluster_members, all_market_skills, job_skill_tree, RECENCY_HALFLIFE_DAYS
    )
    features = pooled * (0.5 + 0.5 * cluster_freq)  # combine similarity + demand
    return features.astype(np.float32)

def summarize_course_vs_market(course_skills, cluster_centroids):
    """summary stats of how a course matches market clusters"""
    if not course_skills or cluster_centroids.size == 0:
        return np.array([0, 0, 0, 0], dtype=np.float32)
    cs_emb = encode_norm(course_skills)
    sims = cs_emb @ cluster_centroids.T
    max_per_skill = sims.max(axis=1)
    max_per_cluster = sims.max(axis=0)
    summary = np.array([
        float(max_per_skill.mean()),          # avg similarity
        float((max_per_skill > 0.60).mean()), # share of strong skills
        float(max_per_cluster.mean()),        # avg cluster coverage
        float(max_per_cluster.std()),         # variation
    ], dtype=np.float32)
    return summary

# Main training pipeline
def train_subject_score_model(skip_extraction=False):
    """main function that trains the model"""

    # load course skills
    print("📄 Loading syllabus from course_descriptions.py ...")
    if skip_extraction:
        from backend.app.services.syllabus_matcher import fetch_subject_skills_from_db
        subject_skills_map = fetch_subject_skills_from_db()
    else:
        subject_skills_map = extract_subject_skills_from_supabase()

    if not subject_skills_map:
        print("❌ No subjects parsed. Exiting.")
        return

    # load job skills
    print("🌐 Extracting job skill frequency from jobs...")
    if skip_extraction:
        from backend.app.services.skill_extractor import fetch_skills_from_supabase
        job_skill_tree = fetch_skills_from_supabase()
    else:
        job_skill_tree = extract_skills_from_jobs()

    if not job_skill_tree:
        print("❌ No skills extracted from jobs. Exiting.")
        return

    # normalize job skills
    raw_skills = list(job_skill_tree.keys())
    all_market_skills = sorted(set(clean_market_skills(raw_skills)))
    if not all_market_skills:
        print("❌ No usable job skills found.")
        return

    joblib.dump(all_market_skills, FEATURE_SKILLS_FILE)

    # cluster skills into concepts
    cluster_centroids, cluster_members, labels, market_embeddings = cluster_market_skills(all_market_skills)

    # ---------------- NEW: compute and keep training-time cluster frequency -------------
    cluster_freq_train = compute_demand_weights_per_cluster(
        cluster_members, all_market_skills, job_skill_tree, RECENCY_HALFLIFE_DAYS
    )
    # -----------------------------------------------------------------------------------

    # generate target scores
    scored_subjects = compute_subject_scores(subject_skills_map, job_skill_tree)
    if len(scored_subjects) < 2:
        print("❌ Not enough training samples.")
        return

    # build training data
    X_list, y_list, courses_list, records = [], [], [], []
    for item in scored_subjects:
        taught_skills = [s.strip().lower() for s in item.get("skills_taught", []) if isinstance(s, str) and s.strip()]
        if not taught_skills:
            continue
        try:
            cluster_vec = compute_course_cluster_features(taught_skills, cluster_centroids, cluster_members, all_market_skills, job_skill_tree, topk=TOPK)
            summary_vec = summarize_course_vs_market(taught_skills, cluster_centroids)
            feat_vec = np.concatenate([cluster_vec, summary_vec], axis=0)

            X_list.append(feat_vec)
            y_list.append(float(item["score"]))
            course_name = item.get("course", "unknown_course")
            courses_list.append(course_name)

            records.append({
                "course": course_name,
                "skills_taught": ", ".join(taught_skills),
                "skills_in_market": ", ".join(item.get("skills_in_market", [])),
                "score": float(item["score"])
            })
        except Exception as e:
            print(f"❌ Feature generation failed for {item.get('course','?')}: {e}")

    if len(X_list) < 2:
        print("❌ Not enough data to train. Exiting.")
        return

    X = np.vstack(X_list)
    y = np.array(y_list, dtype=np.float32)
    groups = np.array(courses_list)

    pd.DataFrame(records).to_csv(COURSE_SCORES_CSV, index=False)

    # hyperparameter search
    n_splits = min(5, max(2, len(np.unique(groups))))
    gkf = GroupKFold(n_splits=n_splits)

    pipe = Pipeline([
        ("svd", TruncatedSVD(n_components=min(128, max(2, X.shape[1] - 1)), random_state=42)),
        ("krr", KernelRidge(kernel="rbf"))
    ])

    param_dist = {
        "svd__n_components": [16, 32, 48, 64, 96, 128] if X.shape[1] >= 16 else [min(X.shape[1]-1, 8), min(X.shape[1]-1, 12)],
        "krr__alpha": loguniform(1e-3, 1e1),
        "krr__gamma": loguniform(1e-3, 1e0),
    }

    search = RandomizedSearchCV(pipe, param_distributions=param_dist, n_iter=40, scoring="r2", cv=gkf, n_jobs=-1, random_state=42, verbose=1)
    search.fit(X, y, groups=groups)
    best_model = search.best_estimator_

    # calibrate model
    best_model.fit(X, y)
    raw_pred = best_model.predict(X)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=float(np.min(y)), y_max=float(np.max(y)))
    iso.fit(raw_pred, y)

    # optional: holdout evaluation
    if len(X) > 8:
        X_tr, X_te, y_tr, y_te, g_tr, g_te = train_test_split(X, y, groups, test_size=0.2, random_state=42)
        best_model.fit(X_tr, y_tr)
        hold_raw = best_model.predict(X_te)
        hold_pred = iso.predict(hold_raw)
        print(f"MAE: {mean_absolute_error(y_te, hold_pred):.2f}")
        print(f"R²: {r2_score(y_te, hold_pred):.3f}")
        best_model.fit(X, y)
        iso.fit(best_model.predict(X), y)

    # save everything
    bundle = {
        "model": best_model,
        "calibrator": iso,
        "cluster_centroids": cluster_centroids.astype(np.float32),
        "cluster_members": cluster_members,
        "all_market_skills": all_market_skills,
        "market_cluster_labels": labels.astype(int),
        "embed_model_name": EMBED_MODEL,
        "topk": TOPK,
        "cluster_distance_threshold": CLUSTER_DISTANCE_THRESHOLD,
        "recency_halflife_days": RECENCY_HALFLIFE_DAYS,
        "feature_tail": ["avg_skill_coverage", "share_strong_skills", "avg_cluster_hit", "cluster_hit_std"],
        # NEW: training-time cluster frequency snapshot (optional use downstream)
        "cluster_freq_train": cluster_freq_train.astype(np.float32),
    }
    joblib.dump(bundle, MODEL_BUNDLE_FILE)
    print(f"✅ Model bundle saved as: {MODEL_BUNDLE_FILE}")

# Inference helpers
def load_model_bundle(path=MODEL_BUNDLE_FILE):
    """load trained model bundle"""
    bundle = joblib.load(path)
    assert "model" in bundle and "calibrator" in bundle and "cluster_centroids" in bundle
    return bundle

def build_features_for_course(course_skills, bundle, job_skill_tree):
    """convert course skills into features for prediction"""
    taught = [s.strip().lower() for s in course_skills if isinstance(s, str) and s.strip()]
    cluster_vec = compute_course_cluster_features(taught, bundle["cluster_centroids"], bundle["cluster_members"], bundle["all_market_skills"], job_skill_tree, topk=bundle.get("topk", TOPK))
    summary_vec = summarize_course_vs_market(taught, bundle["cluster_centroids"])
    return np.concatenate([cluster_vec, summary_vec], axis=0)[None, :]

def predict_course_score(course_skills, job_skill_tree, bundle_path=MODEL_BUNDLE_FILE):
    """predict alignment score for a single course"""
    bundle = load_model_bundle(bundle_path)
    X_new = build_features_for_course(course_skills, bundle, job_skill_tree)
    raw = bundle["model"].predict(X_new)
    y_hat = bundle["calibrator"].predict(raw)
    return float(y_hat[0])

# run training if executed directly
if __name__ == "__main__":
    train_subject_score_model(skip_extraction=True)
