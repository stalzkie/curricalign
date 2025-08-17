import os
import json
import math
import joblib
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.model_selection import train_test_split, KFold, cross_val_score
from sklearn.experimental import enable_hist_gradient_boosting  # noqa: F401
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score

MODEL_PATH = "query_quality_model.pkl"
META_PATH = "query_quality_model.meta.json"
DATA_PATH = "query_training_data.csv"

# Columns we’ll use if present (auto-detect)
CANDIDATE_NUMERIC = [
    "trend_value",
    "is_cs_term",                # (0/1) from pipeline
    "gemini_is_cs",              # (0/1)
    "gemini_confidence",         # [0..1]
    "semantic_cs_sim",           # cosine to CS centroid
    "semantic_nc_sim",           # cosine to Non-CS centroid
    "semantic_margin",           # cs_sim - nc_sim
    "word_count",
    "char_len",
    "unique_token_ratio",
    "has_digits",                # (0/1)
    "has_strong_term",           # (0/1)
    "has_moderate_term",         # (0/1)
    "has_negative_term",         # (0/1)
    "is_borderline",             # (0/1) after fast+semantic, before Gemini
    "days_since_collected"       # if collected_at present
]

CANDIDATE_CATEGORICAL = [
    "source",    # e.g., google_trends, google_trends_fallback, jobs_fallback
    "region"     # e.g., PH
]

TARGET_COL = "query_score"  # (0..100 recommended)


def _safe_bool(x):
    try:
        return int(bool(int(x))) if str(x).isdigit() else int(bool(float(x)))
    except Exception:
        if isinstance(x, str):
            x_low = x.strip().lower()
            if x_low in ("true", "yes"): return 1
            if x_low in ("false", "no"): return 0
        return 0


def _engineer_from_query(df: pd.DataFrame) -> pd.DataFrame:
    """Create structural features from the raw query, if available."""
    if "query" not in df.columns:
        return df

    q = df["query"].fillna("").astype(str)
    toks = q.str.lower().str.replace(r"[^a-z0-9#+.\s]", " ", regex=True).str.split()

    df["word_count"] = toks.apply(len)
    df["char_len"] = q.str.len()
    df["has_digits"] = q.str.contains(r"\d", regex=True).astype(int)

    # unique token ratio
    def _uniq_ratio(lst):
        return 0.0 if not lst else len(set(lst)) / max(1, len(lst))
    df["unique_token_ratio"] = toks.apply(_uniq_ratio)

    return df


def _engineer_from_time(df: pd.DataFrame) -> pd.DataFrame:
    """Compute days_since_collected if collected_at exists."""
    if "collected_at" not in df.columns:
        return df
    try:
        ts = pd.to_datetime(df["collected_at"], errors="coerce", utc=True)
        now = pd.Timestamp(datetime.now(timezone.utc))
        df["days_since_collected"] = (now - ts).dt.total_seconds() / 86400.0
        df["days_since_collected"] = df["days_since_collected"].fillna(df["days_since_collected"].median())
    except Exception:
        df["days_since_collected"] = df.get("days_since_collected", 0.0)
    return df


def _coerce_flag_columns(df: pd.DataFrame, cols):
    for c in cols:
        if c in df.columns:
            df[c] = df[c].apply(_safe_bool)
    return df


def train_query_model():
    # 1) Load
    try:
        df = pd.read_csv(DATA_PATH)
    except FileNotFoundError:
        print(f"❌ Dataset not found: {DATA_PATH}")
        return
    except Exception as e:
        print(f"❌ Error loading dataset: {e}")
        return

    print("📊 Loaded dataset with", len(df), "rows")

    # 2) Basic checks
    if TARGET_COL not in df.columns:
        print(f"❌ Missing target column '{TARGET_COL}' in dataset.")
        return

    # 3) Feature engineering from raw text/time if present
    df = _engineer_from_query(df)
    df = _engineer_from_time(df)

    # 4) Coerce typical boolean-like columns to {0,1}
    df = _coerce_flag_columns(df, [
        "is_cs_term", "gemini_is_cs", "has_digits",
        "has_strong_term", "has_moderate_term", "has_negative_term", "is_borderline"
    ])

    # 5) Select available features can auto-detect
    numeric_features = [c for c in CANDIDATE_NUMERIC if c in df.columns]
    categorical_features = [c for c in CANDIDATE_CATEGORICAL if c in df.columns]

    # Fallback to minimal feature set if needed
    if not numeric_features and not categorical_features:
        minimal = ["is_cs_term", "word_count", "trend_value"]
        if not all(col in df.columns for col in minimal):
            print(f"❌ Missing required columns. Need either enhanced features or minimal {minimal}.")
            return
        numeric_features = minimal

    print("🧩 Using features:")
    for c in numeric_features: print("  •", c)
    for c in categorical_features: print("  • (cat)", c)

    X_num = df[numeric_features].copy()
    for c in numeric_features:
        X_num[c] = pd.to_numeric(X_num[c], errors="coerce")
    X_num = X_num.fillna(X_num.median(numeric_only=True))

    X = None
    transformers = []
    if numeric_features:
        transformers.append(("num", StandardScaler(with_mean=True, with_std=True), numeric_features))
    if categorical_features:
        transformers.append(("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categorical_features))

    pre = ColumnTransformer(transformers=transformers)

    y = df[TARGET_COL].astype(float)

    # 6) Train / Test split
    X_train, X_test, y_train, y_test = train_test_split(
        df[numeric_features + categorical_features], y, test_size=0.2, random_state=42
    )

    # 7) Build model with early stopping
    model = HistGradientBoostingRegressor(
        loss="squared_error",
        learning_rate=0.06,
        max_depth=None,
        max_iter=600,
        l2_regularization=0.0,
        early_stopping=True,
        validation_fraction=0.1,
        n_iter_no_change=30,
        random_state=42
    )

    # 8) Pipeline
    from sklearn.pipeline import Pipeline
    pipe = Pipeline([
        ("pre", pre),
        ("hgb", model)
    ])

    # 9) Cross‑validation (MAE)
    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    cv_mae = -cross_val_score(pipe, df[numeric_features + categorical_features], y, cv=kf, scoring="neg_mean_absolute_error")
    print(f"🧪 5‑Fold CV MAE: mean={cv_mae.mean():.2f}, std={cv_mae.std():.2f}")

    # 10) Fit & evaluate on holdout
    print("🏋️ Training model...")
    pipe.fit(X_train, y_train)
    preds = pipe.predict(X_test)
    mae = mean_absolute_error(y_test, preds)
    r2 = r2_score(y_test, preds)
    print("\n🧪 Holdout Evaluation:")
    print(f"MAE: {mae:.2f}")
    print(f"R²:  {r2:.3f}")

    # 11) Save model + metadata
    joblib.dump(pipe, MODEL_PATH)
    meta = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "model": "HistGradientBoostingRegressor",
        "features_numeric": numeric_features,
        "features_categorical": categorical_features,
        "cv_mae_mean": float(cv_mae.mean()),
        "cv_mae_std": float(cv_mae.std()),
        "holdout_mae": float(mae),
        "holdout_r2": float(r2),
        "dataset_rows": int(len(df)),
        "dataset_path": DATA_PATH
    }
    with open(META_PATH, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"✅ Model saved to {MODEL_PATH}")
    print(f"📝 Metadata saved to {META_PATH}")


if __name__ == "__main__":
    train_query_model()
