# train_model.py

import os
import warnings
import joblib
import numpy as np
import pandas as pd
from collections import defaultdict
from datetime import datetime, timezone   # <-- timezone added

from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import pairwise_distances
from sklearn.model_selection import GroupKFold, RandomizedSearchCV, train_test_split
from sklearn.decomposition import TruncatedSVD
from sklearn.kernel_ridge import KernelRidge
from sklearn.pipeline import Pipeline
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.utils.validation import check_is_fitted
from scipy.stats import loguniform
from sklearn.isotonic import IsotonicRegression
from sklearn.preprocessing import StandardScaler  # kept for compatibility if needed

from sentence_transformers import SentenceTransformer

from backend.app.services.syllabus_matcher import extract_subject_skills_from_supabase
from backend.app.services.skill_extractor import extract_skills_from_jobs
from backend.app.services.evaluator import normalize_skills
from backend.app.services.evaluator import compute_subject_scores

# =========================
# Config
# =========================
EMBED_MODEL = "all-MiniLM-L6-v2"  # use a different model for features than labels if you can
bert_model = SentenceTransformer(EMBED_MODEL)

# Clustering / features
CLUSTER_DISTANCE_THRESHOLD = 0.35  # cosine distance threshold; tune 0.30–0.50
TOPK = 3                           # top-k pooling for per-cluster similarity
RECENCY_HALFLIFE_DAYS = None       # set e.g. 90 to enable recency decay on demand weights

# Files
FEATURE_SKILLS_FILE = "subject_model_features.pkl"
MODEL_BUNDLE_FILE = "subject_success_model.pkl"
COURSE_SCORES_CSV = "bert_course_scores.csv"

# =========================
# Utilities
# =========================
def _parse_date(s):
    try:
        return datetime.fromisoformat(s).date()
    except Exception:
        return None

def clean_market_skills(raw_skills: list[str]) -> list[str]:
    skills = []
    for skill in raw_skills:
        if not isinstance(skill, str):
            continue
        cleaned = skill.strip().lower()
        if cleaned:
            norm = normalize_skills([cleaned])
            if norm:
                skills.append(norm[0])
    return skills

def encode_norm(texts: list[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, bert_model.get_sentence_embedding_dimension()), dtype=np.float32)
    return bert_model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)

def topk_mean(a: np.ndarray, k=3, axis=-1) -> np.ndarray:
    """
    Mean of the top-k values along the given axis.
    Correctly slices along `axis` (not always the last axis).
    """
    if a.size == 0:
        return np.array([], dtype=np.float32)
    k = max(1, min(k, a.shape[axis]))
    # indices of the top-k along axis
    idx = np.argpartition(a, kth=-k, axis=axis)
    # build a slice that selects the last k indices along `axis`
    take_idx = [slice(None)] * a.ndim
    take_idx[axis] = slice(-k, None)
    topk_idx = np.take(idx, indices=range(a.shape[axis]-k, a.shape[axis]), axis=axis)
    topk_vals = np.take_along_axis(a, topk_idx, axis=axis)
    return topk_vals.mean(axis=axis)

# =========================
# Clustering of market skills
# =========================
def cluster_market_skills(all_market_skills: list[str]):
    """
    Returns:
      cluster_centroids: [C, D]
      cluster_members:   list[list[int]] indices of all_market_skills per cluster
      labels:            [N] cluster label per skill
      market_embeddings: [N, D]
    """
    market_embeddings = encode_norm(all_market_skills)
    if len(all_market_skills) <= 1:
        return (
            market_embeddings.copy(),
            [list(range(len(all_market_skills)))],
            np.zeros(len(all_market_skills), dtype=int),
            market_embeddings,
        )

    # cosine distance over normalized embeddings
    dist = pairwise_distances(market_embeddings, metric="cosine")

    # sklearn >=1.2 uses `metric`; older versions used `affinity`
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

    cluster2idxs = defaultdict(list)
    for i, c in enumerate(labels):
        cluster2idxs[c].append(i)

    cluster_centroids = []
    cluster_members = []
    for c, idxs in sorted(cluster2idxs.items()):
        cluster_centroids.append(market_embeddings[idxs].mean(axis=0))
        cluster_members.append(idxs)

    cluster_centroids = np.vstack(cluster_centroids)
    return cluster_centroids, cluster_members, labels, market_embeddings

# =========================
# Feature Engineering
# =========================
def compute_demand_weights_per_cluster(cluster_members, all_market_skills, job_skill_tree, recency_halflife_days=None):
    """
    Returns normalized demand weights per cluster in [0,1].
    job_skill_tree can map skill -> int or skill -> dict with 'count' and optional 'last_seen'.
    """
    cluster_freq = np.zeros(len(cluster_members), dtype=np.float32)
    today = datetime.now(timezone.utc).date()   # <-- fix deprecation

    for c, idxs in enumerate(cluster_members):
        f = 0.0
        weight_sum = 0.0
        for i in idxs:
            skill = all_market_skills[i]
            info = job_skill_tree.get(skill)
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

def compute_course_cluster_features(
    course_skills: list[str],
    cluster_centroids: np.ndarray,
    cluster_members: list[list[int]],
    all_market_skills: list[str],
    job_skill_tree: dict,
    topk: int = TOPK,
) -> np.ndarray:
    if not course_skills or cluster_centroids.size == 0:
        return np.zeros(len(cluster_members), dtype=np.float32)

    cs_emb = encode_norm(course_skills)           # [S, D]
    sims = cs_emb @ cluster_centroids.T           # [S, C] cosine
    pooled = topk_mean(sims, k=topk, axis=0)      # [C]  <-- now correct

    cluster_freq = compute_demand_weights_per_cluster(
        cluster_members, all_market_skills, job_skill_tree, RECENCY_HALFLIFE_DAYS
    )
    features = pooled * (0.5 + 0.5 * cluster_freq)
    return features.astype(np.float32)

def summarize_course_vs_market(course_skills: list[str], cluster_centroids: np.ndarray) -> np.ndarray:
    if not course_skills or cluster_centroids.size == 0:
        return np.array([0, 0, 0, 0], dtype=np.float32)
    cs_emb = encode_norm(course_skills)
    sims = cs_emb @ cluster_centroids.T  # [S, C]
    max_per_skill = sims.max(axis=1)
    max_per_cluster = sims.max(axis=0)
    summary = np.array([
        float(max_per_skill.mean()),
        float((max_per_skill > 0.60).mean()),
        float(max_per_cluster.mean()),
        float(max_per_cluster.std()),
    ], dtype=np.float32)
    return summary

# =========================
# Main training
# =========================
def train_subject_score_model(skip_extraction=False):
    print("📄 Loading syllabus from course_descriptions.py ...")
    if skip_extraction:
        print("🔁 Skipping subject skill extraction (using existing Supabase data)")
        from backend.app.services.syllabus_matcher import fetch_subject_skills_from_db
        subject_skills_map = fetch_subject_skills_from_db()
    else:
        subject_skills_map = extract_subject_skills_from_supabase()

    if not subject_skills_map:
        print("❌ No subjects parsed. Exiting.")
        return

    print("🌐 Extracting job skill frequency from jobs...")
    if skip_extraction:
        print("🔁 Skipping job skill extraction (using existing Supabase data)")
        from backend.app.services.skill_extractor import fetch_skills_from_supabase
        job_skill_tree = fetch_skills_from_supabase()
    else:
        job_skill_tree = extract_skills_from_jobs()

    if not job_skill_tree:
        print("❌ No skills extracted from jobs. Exiting.")
        return

    raw_skills = list(job_skill_tree.keys())
    print(f"🔍 Raw skills loaded from Supabase: {raw_skills[:5]} ({len(raw_skills)} total)")

    all_market_skills = sorted(set(clean_market_skills(raw_skills)))
    print(f"🧹 Cleaned skills: {all_market_skills[:5]} ({len(all_market_skills)} usable)")

    if not all_market_skills:
        print(f"❌ No usable job skills found after cleaning. Raw skill count: {len(raw_skills)}")
        print(f"🔎 Example raw skills: {raw_skills[:10]}")
        return

    joblib.dump(all_market_skills, FEATURE_SKILLS_FILE)
    print(f"📦 Saved normalized feature list ({len(all_market_skills)} skills) to {FEATURE_SKILLS_FILE}")

    print("🧩 Clustering market skills into canonical concepts...")
    cluster_centroids, cluster_members, labels, market_embeddings = cluster_market_skills(all_market_skills)
    print(f"✅ Formed {len(cluster_members)} clusters from {len(all_market_skills)} skills.")

    print("🧠 Generating labels (current evaluator)…")
    scored_subjects = compute_subject_scores(subject_skills_map, job_skill_tree)
    if len(scored_subjects) < 2:
        print(f"❌ Not enough training samples ({len(scored_subjects)}). Need at least 2.")
        return

    # =========================
    # Build feature matrix
    # =========================
    X_list, y_list, courses_list = [], [], []
    records = []

    print("🧮 Encoding training vectors with clustered similarity + demand weighting...")
    for item in scored_subjects:
        taught_skills = [s.strip().lower() for s in item.get("skills_taught", []) if isinstance(s, str) and s.strip()]
        if not taught_skills:
            continue
        try:
            cluster_vec = compute_course_cluster_features(
                taught_skills, cluster_centroids, cluster_members, all_market_skills, job_skill_tree, topk=TOPK
            )
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
        print("❌ Not enough feature samples to train. Exiting.")
        return

    X = np.vstack(X_list)
    y = np.array(y_list, dtype=np.float32)
    groups = np.array(courses_list)

    pd.DataFrame(records).to_csv(COURSE_SCORES_CSV, index=False)
    print(f"📄 Saved raw matches to {COURSE_SCORES_CSV}")

    # =========================
    # Model selection with GroupKFold
    # =========================
    n_splits = min(5, max(2, len(np.unique(groups))))
    gkf = GroupKFold(n_splits=n_splits)
    print(f"\n🔍 Hyperparameter search with GroupKFold (n_splits={n_splits}) ...")

    pipe = Pipeline([
        ("svd", TruncatedSVD(n_components=min(128, max(2, X.shape[1] - 1)), random_state=42)),
        ("krr", KernelRidge(kernel="rbf"))
    ])

    param_dist = {
        "svd__n_components": [16, 32, 48, 64, 96, 128] if X.shape[1] >= 16 else [min(X.shape[1]-1, 8), min(X.shape[1]-1, 12)],
        "krr__alpha": loguniform(1e-3, 1e1),
        "krr__gamma": loguniform(1e-3, 1e0),
    }

    search = RandomizedSearchCV(
        pipe,
        param_distributions=param_dist,
        n_iter=40,
        scoring="r2",
        cv=gkf,
        n_jobs=-1,
        random_state=42,
        verbose=1
    )
    search.fit(X, y, groups=groups)
    print(f"✅ Best CV R²: {search.best_score_:.3f}")
    best_model = search.best_estimator_

    # =========================
    # Final fit + isotonic calibration
    # =========================
    print("\n🏋️ Training best model on full dataset and calibrating ...")
    best_model.fit(X, y)

    raw_pred = best_model.predict(X)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=float(np.min(y)), y_max=float(np.max(y)))
    iso.fit(raw_pred, y)

    if len(X) > 8:
        X_tr, X_te, y_tr, y_te, g_tr, g_te = train_test_split(X, y, groups, test_size=0.2, random_state=42, stratify=None)
        best_model.fit(X_tr, y_tr)
        hold_raw = best_model.predict(X_te)
        hold_pred = iso.predict(hold_raw)
        print("\n🧪 Final Holdout Evaluation:")
        print(f"MAE: {mean_absolute_error(y_te, hold_pred):.2f}")
        print(f"R²: {r2_score(y_te, hold_pred):.3f}")

        best_model.fit(X, y)
        iso.fit(best_model.predict(X), y)

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
    }
    joblib.dump(bundle, MODEL_BUNDLE_FILE)
    print(f"✅ Model bundle saved as: {MODEL_BUNDLE_FILE}")


# =========================
# Inference helper (optional)
# =========================
def load_model_bundle(path=MODEL_BUNDLE_FILE):
    bundle = joblib.load(path)
    assert "model" in bundle and "calibrator" in bundle and "cluster_centroids" in bundle
    return bundle

def build_features_for_course(course_skills: list[str], bundle: dict, job_skill_tree: dict) -> np.ndarray:
    taught = [s.strip().lower() for s in course_skills if isinstance(s, str) and s.strip()]
    cluster_vec = compute_course_cluster_features(
        taught,
        bundle["cluster_centroids"],
        bundle["cluster_members"],
        bundle["all_market_skills"],
        job_skill_tree,
        topk=bundle.get("topk", TOPK),
    )
    summary_vec = summarize_course_vs_market(taught, bundle["cluster_centroids"])
    return np.concatenate([cluster_vec, summary_vec], axis=0)[None, :]

def predict_course_score(course_skills: list[str], job_skill_tree: dict, bundle_path=MODEL_BUNDLE_FILE) -> float:
    bundle = load_model_bundle(bundle_path)
    X_new = build_features_for_course(course_skills, bundle, job_skill_tree)
    raw = bundle["model"].predict(X_new)
    y_hat = bundle["calibrator"].predict(raw)
    return float(y_hat[0])


if __name__ == "__main__":
    train_subject_score_model(skip_extraction=True)
