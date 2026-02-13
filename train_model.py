# train_model.py
import pandas as pd
import numpy as np

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, classification_report

import xgboost as xgb
import joblib

# ----------------------------------------------------
# 1. Load main training data
# ----------------------------------------------------
TRAIN_FILE = "Training.csv"              # main symptom–disease data
CURES_FILE = "disease_cures_filled.csv"  # file you just provided

train = pd.read_csv(TRAIN_FILE)

TARGET = "prognosis"
EXTRA_DROP = ["Cures/Precautions", "Prescreption"]

# drop target + any non-feature columns
cols_to_drop = [TARGET] + [c for c in EXTRA_DROP if c in train.columns]
X = train.drop(columns=cols_to_drop, errors="ignore")
y = train[TARGET]

symptom_cols = X.columns.tolist()

print("Number of symptom/features:", len(symptom_cols))
print("First 10 features:", symptom_cols[:10])

print("\nClass distribution:")
print(y.value_counts())

# ----------------------------------------------------
# 2. Build disease → cure mapping from CURES_FILE
# ----------------------------------------------------
try:
    cures_df = pd.read_csv(CURES_FILE)

    # try to find a column that looks like "cure" or "precaution"
    possible_cure_cols = [
        c for c in cures_df.columns
        if "cure" in c.lower() or "precaution" in c.lower()
    ]

    if not possible_cure_cols:
        print("\n[WARN] No cure/precaution column found in disease_cures_filled.csv")
        disease_to_cure = {}
    else:
        cure_col = possible_cure_cols[0]
        print(f"\nUsing cure column from disease_cures_filled.csv: {cure_col}")

        # expect there to be a 'prognosis' column
        if "prognosis" not in cures_df.columns:
            raise ValueError("disease_cures_filled.csv must have a 'prognosis' column")

        disease_to_cure = (
            cures_df[["prognosis", cure_col]]
            .dropna()
            .drop_duplicates("prognosis")
            .set_index("prognosis")[cure_col]
            .to_dict()
        )

        print(f"Loaded cures for {len(disease_to_cure)} diseases.")

except Exception as e:
    print("\n[WARN] Could not build disease→cure mapping:", e)
    disease_to_cure = {}

# ----------------------------------------------------
# 3. Preprocessing (impute only – no scaling for 0/1)
# ----------------------------------------------------
num_tf = Pipeline(
    steps=[
        ("imputer", SimpleImputer(strategy="most_frequent"))
    ]
)

preprocessor = ColumnTransformer(
    transformers=[
        ("num", num_tf, symptom_cols)
    ],
    remainder="drop"
)

# ----------------------------------------------------
# 4. Encode labels + define model
# ----------------------------------------------------
le = LabelEncoder()
y_enc = le.fit_transform(y)

xgb_model = xgb.XGBClassifier(
    objective="multi:softprob",
    eval_metric="mlogloss",
    num_class=len(le.classes_),

    n_estimators=400,
    max_depth=5,
    learning_rate=0.05,

    subsample=0.8,
    colsample_bytree=0.8,
    reg_lambda=1.0,
    reg_alpha=0.0,

    n_jobs=-1,
    tree_method="hist",
    random_state=42,
)

pipe = Pipeline(
    steps=[
        ("preprocessor", preprocessor),
        ("xgbclassifier", xgb_model),
    ]
)

# ----------------------------------------------------
# 5. Train / validation
# ----------------------------------------------------
X_train, X_val, y_train, y_val = train_test_split(
    X,
    y_enc,
    test_size=0.2,
    stratify=y_enc,
    random_state=42,
)

print("\nFitting model...")
pipe.fit(X_train, y_train)

# ----------------------------------------------------
# 6. Evaluation
# ----------------------------------------------------
y_pred = pipe.predict(X_val)

acc = accuracy_score(y_val, y_pred)
print("\nValidation accuracy:", acc)

print("\nClassification report:")
print(
    classification_report(
        y_val,
        y_pred,
        target_names=le.classes_,
    )
)

# ----------------------------------------------------
# 7. Save model, label encoder & cures mapping
# ----------------------------------------------------
MODEL_PATH = "disease_prediction_model.joblib"
LE_PATH = "label_encoder.joblib"
CURES_PATH = "disease_cures.joblib"

joblib.dump(pipe, MODEL_PATH)
joblib.dump(le, LE_PATH)
joblib.dump(disease_to_cure, CURES_PATH)

print(f"\nSaved model to: {MODEL_PATH}")
print(f"Saved label encoder to: {LE_PATH}")
print(f"Saved disease→cure map to: {CURES_PATH}")
