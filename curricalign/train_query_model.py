import pandas as pd
import joblib
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score

def train_query_model():
    # Load Query Performance Dataset
    DATA_PATH = "query_training_data.csv"

    try:
        df = pd.read_csv(DATA_PATH)
    except FileNotFoundError:
        print(f"❌ Dataset not found: {DATA_PATH}")
        return
    except Exception as e:
        print(f"❌ Error loading dataset: {e}")
        return

    print("📊 Loaded dataset with", len(df), "entries")

    # Feature Engineering
    feature_cols = ["is_cs_term", "word_count", "trend_value"]
    target_col = "query_score"

    if not all(col in df.columns for col in feature_cols + [target_col]):
        print(f"❌ Missing required columns. Dataset must include: {feature_cols + [target_col]}")
        return

    X = df[feature_cols]
    y = df[target_col]

    # Train/Test Split
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # Train ML Model
    model = GradientBoostingRegressor(
        n_estimators=200,
        learning_rate=0.08,
        max_depth=5,
        random_state=42
    )

    print("🏋️ Training query model...")
    model.fit(X_train, y_train)

    # Evaluate Model
    preds = model.predict(X_test)
    mae = mean_absolute_error(y_test, preds)
    r2 = r2_score(y_test, preds)

    print("\n🧪 Query Model Evaluation:")
    print(f"MAE: {mae:.2f}")
    print(f"R²:  {r2:.3f}")

    # Save Model
    MODEL_PATH = "query_quality_model.pkl"
    joblib.dump(model, MODEL_PATH)
    print(f"✅ Query model saved as: {MODEL_PATH}")

if __name__ == "__main__":
        train_query_model()