import os
import warnings
import time
import logging
import joblib
import numpy as np
import pandas as pd
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from backend.app.ml.models import BlendedRegressor

# ─────────────────────────────────────────────
# Logging setup
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("trainer")

class Timer:
    def __init__(self, what: str):
        self.what = what
        self.t0 = None
    def __enter__(self):
        self.t0 = time.perf_counter()
        log.info(f"▶️  {self.what} …")
        return self
    def __exit__(self, exc_type, exc, tb):
        dt = time.perf_counter() - self.t0
        if exc:
            log.error(f"⛔ {self.what} failed after {dt:.2f}s: {exc}")
        else:
            log.info(f"✅ {self.what} done in {dt:.2f}s")

# Silence tokenizer fork warnings during parallel CV (optional but nice)
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# scikit-learn stuff
from sklearn.cluster import AgglomerativeClustering
from sklearn.metrics import pairwise_distances
from sklearn.model_selection import GroupKFold, RandomizedSearchCV, train_test_split, cross_val_score, learning_curve
from sklearn.decomposition import TruncatedSVD
from sklearn.kernel_ridge import KernelRidge
from sklearn.pipeline import Pipeline
from sklearn.metrics import mean_absolute_error, r2_score, make_scorer
from sklearn.isotonic import IsotonicRegression
from sklearn.inspection import permutation_importance
from sklearn.dummy import DummyRegressor
from scipy.stats import loguniform
from scipy.stats import spearmanr

# Optional: LightGBM for stacking (will gracefully degrade if missing)
try:
    import lightgbm as lgb
    HAS_LGB = True
except Exception:
    HAS_LGB = False

# sentence embeddings
from sentence_transformers import SentenceTransformer

# import functions from our backend services
from backend.app.services.skill_extractor import extract_skills_from_jobs
from backend.app.services.evaluator import normalize_skills, compute_subject_scores

# 🔄 NEW: pull skills from course_skills_dataset
from backend.app.services.dataset_skill_extractor import (
    extract_dataset_skills_from_supabase,
    fetch_dataset_skills_from_db,
)

# ─────────────────────────────────────────────
# Config (with speed knobs)
# ─────────────────────────────────────────────
EMBED_MODEL = "all-MiniLM-L6-v2"
# Speed/feature knobs (you can tweak)
FAST_MODE = False
USE_LGB = True
USE_JOB_FEATURES = True
MAX_SYNTH_JOBS = 40
RSCV_N_ITER = 80  # ↑ wider search
SVD_CANDIDATES = [16, 32, 48, 64, 96, 128]

if FAST_MODE:
    USE_LGB = False
    USE_JOB_FEATURES = False
    MAX_SYNTH_JOBS = 20
    RSCV_N_ITER = 20
    SVD_CANDIDATES = [32, 48, 64]

# clustering settings
CLUSTER_DISTANCE_THRESHOLD = 0.35  # smaller = more clusters
TOPK = 3                           # take top-3 most similar skills
RECENCY_HALFLIFE_DAYS = 90         # newer skills weigh more (enabled)

# paths pinned to backend/app/ml
ML_DIR = Path(__file__).resolve().parent
ML_DIR.mkdir(parents=True, exist_ok=True)
FEATURE_SKILLS_FILE = ML_DIR / "subject_model_features.pkl"
MODEL_BUNDLE_FILE   = ML_DIR / "subject_success_model.pkl"
COURSE_SCORES_CSV   = ML_DIR / "bert_course_scores.csv"
CLUSTER_CACHE_FILE  = ML_DIR / "cluster_cache.pkl"
TRAIN_RUNS_CSV      = ML_DIR / "training_runs.csv"

# =====================
# Metrics: Spearman ρ
# =====================
def spearmanr_safe(y_true, y_pred) -> float:
    try:
        rho, _ = spearmanr(y_true, y_pred)
        if rho is None or np.isnan(rho):
            return 0.0
        return float(rho)
    except Exception:
        return 0.0

SPEARMAN_SCORER = make_scorer(spearmanr_safe, greater_is_better=True)

# ==========================
# Skill cleaning / canonical
# ==========================
_CANON_MAP = {
    "js": "javascript",
    "nodejs": "node.js",
    "node js": "node.js",
    "ts": "typescript",
    "py": "python",
    "py torch": "pytorch",
    "tensorflow 2": "tensorflow",
    "sql database": "sql",
    "gcp": "google cloud",
    "aws cloud": "aws",
    "ms excel": "excel",
    "power bi": "powerbi",
    "reactjs": "react",
    "vuejs": "vue",
    "nlp": "natural language processing",
    "cv": "computer vision",
}

def canonicalize_skill(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace("–", "-").replace("—", "-")
    s = "".join(ch if (ch.isalnum() or ch.isspace() or ch in {'.','-','+'}) else " " for ch in s)
    s = " ".join(s.split())
    if len(s) <= 1:
        return ""
    return _CANON_MAP.get(s, s)

# Utilities
def _parse_date(s):
    try:
        return datetime.fromisoformat(str(s)).date()
    except Exception:
        return None

def clean_market_skills(raw_skills: list[str]) -> list[str]:
    skills = []
    for skill in raw_skills:
        if not isinstance(skill, str):
            continue
        cleaned = canonicalize_skill(skill)
        if cleaned:
            norm = normalize_skills([cleaned])
            if norm and isinstance(norm, list) and isinstance(norm[0], str):
                cand = canonicalize_skill(norm[0])
                if cand and len(cand) >= 2:
                    skills.append(cand)
    return skills

def encode_norm(texts: list[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, bert_model.get_sentence_embedding_dimension()), dtype=np.float32)
    return bert_model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)

def topk_mean(a: np.ndarray, k=3, axis=-1) -> np.ndarray:
    if a.size == 0:
        return np.array([], dtype=np.float32)
    k = max(1, min(k, a.shape[axis]))
    idx = np.argpartition(a, kth=-k, axis=axis)
    topk_idx = np.take(idx, indices=range(a.shape[axis]-k, a.shape[axis]), axis=axis)
    topk_vals = np.take_along_axis(a, topk_idx, axis=axis)
    return topk_vals.mean(axis=axis)

# ==========================================
# Clustering job skills (with cache/reuse)
# ==========================================
def cluster_market_skills(all_market_skills: list[str]):
    market_embeddings = encode_norm(all_market_skills)
    if len(all_market_skills) <= 1:
        return (market_embeddings.copy(),
                [list(range(len(all_market_skills)))],
                np.zeros(len(all_market_skills), dtype=int),
                market_embeddings)

    dist = pairwise_distances(market_embeddings, metric="cosine")

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

def load_or_build_clusters(all_market_skills):
    """Freeze & reuse clusters across runs for stability."""
    if CLUSTER_CACHE_FILE.exists():
        cache = joblib.load(CLUSTER_CACHE_FILE)
        if cache.get("all_market_skills_hash") == hash(tuple(all_market_skills)):
            log.info(f"♻️  Using cached clusters from {CLUSTER_CACHE_FILE.name}")
            return (
                cache["cluster_centroids"],
                cache["cluster_members"],
                cache["labels"],
                cache["market_embeddings"],
            )
        else:
            log.info("🧹 Market skills changed — rebuilding clusters")
    with Timer("Clustering market skills"):
        cluster_centroids, cluster_members, labels, market_embeddings = cluster_market_skills(all_market_skills)
    cache = dict(
        cluster_centroids=cluster_centroids,
        cluster_members=cluster_members,
        labels=labels,
        market_embeddings=market_embeddings,
        all_market_skills_hash=hash(tuple(all_market_skills)),
    )
    joblib.dump(cache, CLUSTER_CACHE_FILE)
    log.info(f"💾 Saved cluster cache → {CLUSTER_CACHE_FILE.name} (clusters={len(cluster_members)})")
    return cluster_centroids, cluster_members, labels, market_embeddings

# Feature Engineering
def compute_demand_weights_per_cluster(cluster_members, all_market_skills, job_skill_tree, recency_halflife_days=None):
    cluster_freq = np.zeros(len(cluster_members), dtype=np.float32)
    today = datetime.now(timezone.utc).date()

    def _skill_stats(skill):
        info = job_skill_tree.get(skill)
        if isinstance(info, (int, float)):
            return float(info), None
        elif isinstance(info, dict):
            count = float(info.get("count", 1.0))
            last_seen = _parse_date(info.get("last_seen")) if info.get("last_seen") else None
            return count, last_seen
        return 1.0, None

    for c, idxs in enumerate(cluster_members):
        f = 0.0
        weight_sum = 0.0
        for i in idxs:
            skill = all_market_skills[i]
            count, last_seen = _skill_stats(skill)
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

def compute_course_cluster_features(course_skills, cluster_centroids, cluster_members, all_market_skills, job_skill_tree, topk=TOPK):
    if not course_skills or cluster_centroids.size == 0:
        return np.zeros(len(cluster_members), dtype=np.float32)

    taught = [canonicalize_skill(s) for s in course_skills if isinstance(s, str) and s.strip()]
    taught = [t for t in taught if t and len(t) >= 2]
    cs_emb = encode_norm(taught)
    sims = cs_emb @ cluster_centroids.T
    pooled = topk_mean(sims, k=topk, axis=0)

    cluster_freq = compute_demand_weights_per_cluster(
        cluster_members, all_market_skills, job_skill_tree, RECENCY_HALFLIFE_DAYS
    )
    features = pooled * (0.5 + 0.5 * cluster_freq)
    return features.astype(np.float32)

def summarize_course_vs_market(course_skills, cluster_centroids):
    if not course_skills or cluster_centroids.size == 0:
        return np.array([0, 0, 0, 0], dtype=np.float32)
    taught = [canonicalize_skill(s) for s in course_skills if isinstance(s, str) and s.strip()]
    taught = [t for t in taught if t and len(t) >= 2]
    cs_emb = encode_norm(taught)
    sims = cs_emb @ cluster_centroids.T
    max_per_skill = sims.max(axis=1)
    max_per_cluster = sims.max(axis=0)
    return np.array([
        float(max_per_skill.mean()),
        float((max_per_skill > 0.60).mean()),
        float(max_per_cluster.mean()),
        float(max_per_cluster.std()),
    ], dtype=np.float32)

# =======================================
# Job-level similarity features (UPGRADED)
# =======================================
def _build_job_docs_from_job_skill_tree(job_skill_tree, all_market_skills, labels, cluster_members, top_per_cluster=10):
    def _count(skill):
        info = job_skill_tree.get(skill)
        if isinstance(info, (int, float)):
            return float(info)
        elif isinstance(info, dict):
            return float(info.get("count", 1.0))
        return 1.0

    jobs = []
    for members in cluster_members:
        idxs = sorted(members, key=lambda i: _count(all_market_skills[i]), reverse=True)[:top_per_cluster]
        skills = [all_market_skills[i] for i in idxs]
        skills = [canonicalize_skill(s) for s in skills if s]
        skills = [s for s in skills if s and len(s) >= 2]
        if skills:
            jobs.append(skills)
    if MAX_SYNTH_JOBS is not None and len(jobs) > MAX_SYNTH_JOBS:
        jobs = jobs[:MAX_SYNTH_JOBS]
    return jobs

def build_job_level_features(course_skills, job_skill_tree, all_market_skills, labels, cluster_members):
    taught = [canonicalize_skill(s) for s in course_skills if isinstance(s, str) and s.strip()]
    taught = [t for t in taught if t and len(t) >= 2]
    if not taught:
        return np.zeros(8, dtype=np.float32)  # updated length

    job_skill_sets = None
    try:
        from backend.app.services.skill_extractor import fetch_job_skill_sets  # optional
        job_skill_sets = fetch_job_skill_sets()
        if job_skill_sets:
            log.debug(f"Using {len(job_skill_sets)} real job docs for job-sim features")
    except Exception:
        job_skill_sets = None

    if not job_skill_sets:
        job_skill_sets = _build_job_docs_from_job_skill_tree(job_skill_tree, all_market_skills, labels, cluster_members)

    if not job_skill_sets:
        return np.zeros(8, dtype=np.float32)

    cs_emb = encode_norm(taught)
    course_vec = (cs_emb.mean(axis=0, keepdims=True)
                  if cs_emb.size else
                  np.zeros((1, bert_model.get_sentence_embedding_dimension()), dtype=np.float32))

    job_vecs = []
    for doc in job_skill_sets:
        emb = encode_norm(doc)
        if emb.size:
            job_vecs.append(emb.mean(axis=0))
    if not job_vecs:
        return np.zeros(8, dtype=np.float32)

    job_mat = np.vstack(job_vecs)
    sims = (course_vec @ job_mat.T).ravel()

    mean_sim = float(np.mean(sims))
    max_sim  = float(np.max(sims))
    share_060 = float(np.mean(sims > 0.60))
    q05, q50, q75, q95 = np.percentile(sims, [5, 50, 75, 95])
    share_070 = float(np.mean(sims > 0.70))

    return np.array([mean_sim, max_sim, share_060, q95, q50, q75, q05, share_070], dtype=np.float32)

# ===========================
# Main training pipeline
# ===========================
def train_subject_score_model(skip_extraction=False):
    log.info("Starting training")
    log.info(f"Config: FAST_MODE={FAST_MODE} | USE_JOB_FEATURES={USE_JOB_FEATURES} | USE_LGB={USE_LGB and HAS_LGB} | "
             f"SVD_CANDIDATES={SVD_CANDIDATES} | RSCV_N_ITER={RSCV_N_ITER} | RECENCY_HALFLIFE_DAYS={RECENCY_HALFLIFE_DAYS}")
    with Timer(f"Loading embedder '{EMBED_MODEL}'"):
        global bert_model
        bert_model = SentenceTransformer(EMBED_MODEL)

    # load course skills (from course_skills_dataset)
    log.info("📄 Loading course skills (source: course_skills_dataset)")
    if skip_extraction:
        with Timer("Fetch course skills from DB (read-only)"):
            subject_skills_map = fetch_dataset_skills_from_db()
    else:
        with Timer("Extract/refresh course skills via Gemini → course_skills_dataset"):
            subject_skills_map = extract_dataset_skills_from_supabase()

    if not subject_skills_map:
        log.warning("❌ No subjects parsed. Exiting.")
        return
    log.info(f"Courses loaded: {len(subject_skills_map)}")

    # load job skills
    log.info("🌐 Loading job-market skills")
    if skip_extraction:
        from backend.app.services.skill_extractor import fetch_skills_from_supabase
        with Timer("Fetch job skills from DB"):
            job_skill_tree = fetch_skills_from_supabase()
    else:
        with Timer("Extract job skills from jobs"):
            job_skill_tree = extract_skills_from_jobs()

    if not job_skill_tree:
        log.warning("❌ No skills extracted from jobs. Exiting.")
        return
    log.info(f"Unique market skills (raw keys): {len(job_skill_tree)}")

    # normalize job skills
    with Timer("Cleaning/canonicalizing market skills"):
        raw_skills = list(job_skill_tree.keys())
        all_market_skills = sorted(set(clean_market_skills(raw_skills)))
    if not all_market_skills:
        log.warning("❌ No usable job skills found.")
        return
    joblib.dump(all_market_skills, FEATURE_SKILLS_FILE)
    log.info(f"Clean market skills: {len(all_market_skills)} (saved → {FEATURE_SKILLS_FILE.name})")

    # clusters (reuse cache when possible)
    cluster_centroids, cluster_members, labels, market_embeddings = load_or_build_clusters(all_market_skills)
    log.info(f"Clusters: {len(cluster_members)} | Centroid dim: {cluster_centroids.shape[1]}")

    # training-time cluster frequency (with recency)
    with Timer("Computing demand weights w/ recency"):
        cluster_freq_train = compute_demand_weights_per_cluster(
            cluster_members, all_market_skills, job_skill_tree, RECENCY_HALFLIFE_DAYS
        )

    # targets
    with Timer("Computing target scores for courses"):
        scored_subjects = compute_subject_scores(subject_skills_map, job_skill_tree)
    if len(scored_subjects) < 2:
        log.warning("❌ Not enough training samples.")
        return
    log.info(f"Scored subjects: {len(scored_subjects)}")

    # build features
    with Timer("Building feature matrix"):
        X_list, y_list, courses_list, records = [], [], [], []
        for item in scored_subjects:
            taught_skills = [s.strip().lower() for s in item.get("skills_taught", []) if isinstance(s, str) and s.strip()]
            if not taught_skills:
                continue
            try:
                cluster_vec = compute_course_cluster_features(
                    taught_skills, cluster_centroids, cluster_members, all_market_skills, job_skill_tree, topk=TOPK
                )
                summary_vec = summarize_course_vs_market(taught_skills, cluster_centroids)
                job_sim_vec = np.zeros(8, dtype=np.float32)  # updated length
                if USE_JOB_FEATURES:
                    job_sim_vec = build_job_level_features(
                        taught_skills, job_skill_tree, all_market_skills, labels, cluster_members
                    )
                feat_vec = np.concatenate([cluster_vec, summary_vec, job_sim_vec], axis=0)

                X_list.append(feat_vec)
                y_list.append(float(item["score"]))
                course_name = item.get("course", "unknown_course")
                courses_list.append(course_name)

                records.append({
                    "course": course_name,
                    "skills_taught": ", ".join([canonicalize_skill(s) for s in taught_skills]),
                    "skills_in_market": ", ".join(item.get("skills_in_market", [])),
                    "score": float(item["score"])
                })
            except Exception as e:
                log.warning(f"❌ Feature generation failed for {item.get('course','?')}: {e}")

    if len(X_list) < 2:
        log.warning("❌ Not enough data to train. Exiting.")
        return

    X = np.vstack(X_list)
    y = np.array(y_list, dtype=np.float32)
    groups = np.array(courses_list)
    pd.DataFrame(records).to_csv(COURSE_SCORES_CSV, index=False)
    log.info(f"Feature matrix: X={X.shape}, y={y.shape} (saved course-level CSV → {COURSE_SCORES_CSV.name})")

    # CV/search
    n_splits = min(5, max(2, len(np.unique(groups))))
    gkf = GroupKFold(n_splits=n_splits)
    pipe = Pipeline([
        ("svd", TruncatedSVD(n_components=min(128, max(2, X.shape[1] - 1)), random_state=42)),
        ("krr", KernelRidge(kernel="rbf"))
    ])
    # widen search; if high-dim, allow bigger SVD
    svd_grid = SVD_CANDIDATES.copy()
    if X.shape[1] > 128:
        svd_grid += [160, 192]
    param_dist = {
        "svd__n_components": svd_grid if X.shape[1] >= 16 else [min(X.shape[1]-1, 8), min(X.shape[1]-1, 12)],
        "krr__alpha": loguniform(1e-4, 1e1),   # widened
        "krr__gamma": loguniform(5e-4, 5e0),   # widened
    }
    scoring = {"r2": "r2", "neg_mae": "neg_mean_absolute_error", "spearman": SPEARMAN_SCORER}

    with Timer(f"Hyperparameter search (RandomizedSearchCV, n_iter={RSCV_N_ITER}, folds={n_splits})"):
        search = RandomizedSearchCV(
            pipe,
            param_distributions=param_dist,
            n_iter=RSCV_N_ITER,
            scoring=scoring,
            refit="r2",
            cv=gkf,
            n_jobs=-1,
            random_state=42,
            verbose=1
        )
        search.fit(X, y, groups=groups)
        best_model = search.best_estimator_

    best_idx = search.best_index_
    cv_r2_mean       = float(search.cv_results_()["mean_test_r2"][best_idx]) if callable(getattr(search, "cv_results_", None)) else float(search.cv_results_["mean_test_r2"][best_idx])
    cv_mae_mean      = float(-search.cv_results_["mean_test_neg_mae"][best_idx]) if not callable(getattr(search, "cv_results_", None)) else float(-search.cv_results_()["mean_test_neg_mae"][best_idx])
    cv_spearman_mean = float(search.cv_results_["mean_test_spearman"][best_idx]) if not callable(getattr(search, "cv_results_", None)) else float(search.cv_results_()["mean_test_spearman"][best_idx])
    log.info(f"[CV] R²={cv_r2_mean:.3f} | MAE={cv_mae_mean:.2f} | ρ={cv_spearman_mean:.3f}")
    log.info(f"[CV] Best params: {search.best_params_}")

    # Diagnostics: Dummy baseline and learning curve
    with Timer("Diagnostics: baseline and learning curve"):
        base = DummyRegressor(strategy="mean")
        base_r2 = cross_val_score(base, X, y, cv=gkf, groups=groups, scoring="r2").mean()
        log.info(f"[BASELINE] R²={base_r2:.3f}")
        sizes, tr_scores, cv_scores = learning_curve(
            best_model, X, y, groups=groups, cv=gkf, scoring="r2",
            train_sizes=np.linspace(0.2, 1.0, 5), n_jobs=-1, shuffle=True, random_state=42
        )
        log.info(f"[LC] train={np.round(tr_scores.mean(axis=1), 3)} | cv={np.round(cv_scores.mean(axis=1), 3)}")

    lgb_model = None
    if HAS_LGB and USE_LGB:
        lgb_model = lgb.LGBMRegressor(
            n_estimators=900, learning_rate=0.03,
            subsample=0.8, colsample_bytree=0.8, max_depth=-1,
            num_leaves=31, random_state=42, reg_lambda=1.0,
        )
        log.info("🧱 LightGBM enabled for stacking (installed and active)")
    else:
        if USE_LGB and not HAS_LGB:
            log.warning("⚠️ USE_LGB=True but LightGBM not installed; falling back to KernelRidge only")
        log.info("🧱 LightGBM disabled or not installed — using KernelRidge only")

    with Timer("Fitting blended model"):
        blended = BlendedRegressor(best_model, lgb_model)
        blended.fit(X, y)

    # Diagnostics: permutation importance (on the SVD+KRR pipe)
    try:
        with Timer("Diagnostics: permutation importance (R²)"):
            imp = permutation_importance(best_model, X, y, scoring="r2", n_repeats=10, random_state=42)
            top_idx = np.argsort(imp.importances_mean)[-10:]
            log.info(f"[IMP] top-dim indices: {top_idx.tolist()} | gains={np.round(imp.importances_mean[top_idx], 4).tolist()}")
    except Exception as e:
        log.info(f"[IMP] skipped ({e})")

    # Calibration
    with Timer("Calibrating predictions (Isotonic)"):
        raw_pred = blended.predict(X)
        iso = IsotonicRegression(out_of_bounds="clip", y_min=float(np.min(y)), y_max=float(np.max(y)))
        iso.fit(raw_pred, y)

    # Holdout evaluation
    holdout_metrics = None
    if len(X) > 8:
        with Timer("Holdout evaluation (80/20 split)"):
            X_tr, X_te, y_tr, y_te, g_tr, g_te = train_test_split(
                X, y, groups, test_size=0.2, random_state=42
            )
            blended.fit(X_tr, y_tr)
            hold_raw = blended.predict(X_te)
            hold_pred = iso.predict(hold_raw)

            r2_h   = float(r2_score(y_te, hold_pred))
            mae_h  = float(mean_absolute_error(y_te, hold_pred))
            rho_h  = float(spearmanr_safe(y_te, hold_pred))

            log.info(f"[HOLDOUT] MAE={mae_h:.2f} | R²={r2_h:.3f} | ρ={rho_h:.3f}")

            blended.fit(X, y)
            iso.fit(blended.predict(X), y)

            holdout_metrics = {"r2": r2_h, "mae": mae_h, "spearman": rho_h}
    else:
        log.info("HOLDOUT skipped (not enough samples)")

    # Log run row
    run_row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "n_samples": int(len(y)),
        "n_features": int(X.shape[1]),
        "cv_r2": cv_r2_mean,
        "cv_mae": cv_mae_mean,
        "cv_spearman": cv_spearman_mean,
        "holdout_r2": holdout_metrics["r2"] if holdout_metrics else None,
        "holdout_mae": holdout_metrics["mae"] if holdout_metrics else None,
        "holdout_spearman": holdout_metrics["spearman"] if holdout_metrics else None,
        "best_params": str(search.best_params_),
        "topk": int(TOPK),
        "cluster_distance_threshold": float(CLUSTER_DISTANCE_THRESHOLD),
        "recency_halflife_days": int(RECENCY_HALFLIFE_DAYS) if RECENCY_HALFLIFE_DAYS else None,
        "embed_model": EMBED_MODEL,
        "has_lightgbm": bool(HAS_LGB and USE_LGB),
    }
    df_row = pd.DataFrame([run_row])
    if TRAIN_RUNS_CSV.exists():
        old = pd.read_csv(TRAIN_RUNS_CSV)
        pd.concat([old, df_row], ignore_index=True).to_csv(TRAIN_RUNS_CSV, index=False)
    else:
        df_row.to_csv(TRAIN_RUNS_CSV, index=False)
    log.info(f"📝 Logged metrics → {TRAIN_RUNS_CSV.name}")

    # Save bundle
    bundle = {
        "model": blended,
        "calibrator": iso,
        "cluster_centroids": cluster_centroids.astype(np.float32),
        "cluster_members": cluster_members,
        "all_market_skills": all_market_skills,
        "market_cluster_labels": labels.astype(int),
        "embed_model_name": EMBED_MODEL,
        "topk": TOPK,
        "cluster_distance_threshold": CLUSTER_DISTANCE_THRESHOLD,
        "recency_halflife_days": RECENCY_HALFLIFE_DAYS,
        "feature_tail": [
            "avg_skill_coverage", "share_strong_skills", "avg_cluster_hit", "cluster_hit_std",
            # upgraded job-sim tail (8 dims)
            "job_mean_sim", "job_max_sim", "job_share_gt_0.6", "job_q95",
            "job_q50", "job_q75", "job_q05", "job_share_gt_0.7"
        ],
        "cluster_freq_train": cluster_freq_train.astype(np.float32),
        "metrics_cv": {
            "r2": cv_r2_mean,
            "mae": cv_mae_mean,
            "spearman": cv_spearman_mean,
            "best_params": search.best_params_,
            "n_splits": int(gkf.get_n_splits()),
        },
        "metrics_holdout": holdout_metrics,
        "has_lightgbm": bool(HAS_LGB and USE_LGB),
    }
    with Timer(f"Saving model bundle → {MODEL_BUNDLE_FILE.name}"):
        joblib.dump(bundle, MODEL_BUNDLE_FILE)

    log.info("🎉 Training complete")

# Inference helpers
def load_model_bundle(path=MODEL_BUNDLE_FILE):
    bundle = joblib.load(path)
    assert "model" in bundle and "calibrator" in bundle and "cluster_centroids" in bundle
    return bundle

def build_features_for_course(course_skills, bundle, job_skill_tree):
    taught = [s.strip().lower() for s in course_skills if isinstance(s, str) and s.strip()]
    cluster_vec = compute_course_cluster_features(
        taught, bundle["cluster_centroids"], bundle["cluster_members"], bundle["all_market_skills"],
        job_skill_tree, topk=bundle.get("topk", TOPK)
    )
    summary_vec = summarize_course_vs_market(taught, bundle["cluster_centroids"])
    job_sim_vec = build_job_level_features(
        taught, job_skill_tree, bundle["all_market_skills"], bundle.get("market_cluster_labels", np.array([])),
        bundle["cluster_members"]
    )
    return np.concatenate([cluster_vec, summary_vec, job_sim_vec], axis=0)[None, :]

def predict_course_score(course_skills, job_skill_tree, bundle_path=MODEL_BUNDLE_FILE):
    bundle = load_model_bundle(bundle_path)
    X_new = build_features_for_course(course_skills, bundle, job_skill_tree)
    raw = bundle["model"].predict(X_new)
    y_hat = bundle["calibrator"].predict(raw)
    return float(y_hat[0])

# run training if executed directly
if __name__ == "__main__":
    train_subject_score_model(skip_extraction=True)
