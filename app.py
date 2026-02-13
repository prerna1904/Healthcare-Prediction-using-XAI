# app.py
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import joblib
import shap
import numpy as np
import pandas as pd
import base64
import traceback
import io

import matplotlib
matplotlib.use("Agg")  # non-GUI backend
import matplotlib.pyplot as plt

def normalize_name(s: str) -> str:
    """Lowercase and keep only alphanumeric characters for matching."""
    return "".join(ch for ch in str(s).lower() if ch.isalnum())

app = Flask(__name__, static_folder=".", static_url_path="")
CORS(app)

MODEL_PATH = "disease_prediction_model.joblib"
LE_PATH = "label_encoder.joblib"
CURES_PATH = "disease_cures.joblib"

try:
    pipe = joblib.load(MODEL_PATH)
    le = joblib.load(LE_PATH)

    # Load cures and normalize 
    try:
        raw_cures_map = joblib.load(CURES_PATH)
        cures_map = {normalize_name(k): v for k, v in raw_cures_map.items()}
        print(f"Cures map loaded with {len(cures_map)} entries (normalized).")
    except Exception as e:
        print("Warning: could not load cures map:", e)
        cures_map = {}

    # preprocessor 
    pre = (
        pipe.named_steps.get("preprocessor")
        or pipe.named_steps.get("columntransformer")
    )

    model = (
        pipe.named_steps.get("xgbclassifier")
        or pipe.named_steps.get("xgb")
        or pipe.named_steps.get("rf")
        or pipe.named_steps.get("randomforestclassifier")
    )

    print("Model and encoder loaded.")
    print("Model step type:", type(model))
except Exception as e:
    pipe = None
    le = None
    pre = None
    model = None
    cures_map = {}
    print("Error loading model/encoder:", e)

def get_original_columns(ct):
    """Extract original column names from a ColumnTransformer."""
    if ct is None:
        return []
    cols = []
    try:
        for name, trans, cols_spec in ct.transformers_:
            if cols_spec is None or cols_spec == "drop":
                continue
            if isinstance(cols_spec, (list, tuple, np.ndarray)):
                cols.extend(list(cols_spec))
            else:
                try:
                    names_out = ct.get_feature_names_out()
                    cols = list(names_out)
                    break
                except Exception:
                    continue
    except Exception:
        pass
    return list(dict.fromkeys(cols))


original_cols = get_original_columns(pre)
print("Original cols count:", len(original_cols))

DISEASE_SYMPTOM_MAP = {
    "dengue": ["fever", "rash", "red spots", "headache", "fatigue", "body ache"],
    "chicken pox": ["itching", "rash", "red spots", "fever", "body ache"],
    "measles": ["fever", "rash", "red spots", "cough", "runny nose"],
    "fungal infection": ["itching", "skin rash", "red patches"],
    "allergy": ["itching", "rash", "sneezing", "red spots"],
    "bronchial asthma": ["cough", "wheezing", "breathlessness"],
    "pneumonia": ["fever", "cough", "breathlessness", "chest pain"],
    "covid": ["fever", "cough", "fatigue", "sore throat", "body ache"],
    "migraine": ["headache", "nausea", "vomiting", "sensitivity"],
    "jaundice": ["yellow skin", "yellow eyes", "fatigue", "nausea"],
    "urinary tract infection": [
        "burning urination",
        "frequent urination",
        "pelvic pain",
        "lower abdominal pain",
    ],
    "malaria": ["fever", "chills", "sweating", "headache", "body ache"],
    "gerd": ["heartburn", "acid reflux", "chest burning"],
    "typhoid": ["fever", "abdominal pain", "headache", "fatigue"],

}


def symptom_match_score(input_symptoms, disease_name):
    """
    Returns a rule-based match score in [0,1].
    0 => no rule match / no rule defined
    1 => all expected key symptoms present
    """
    expected = DISEASE_SYMPTOM_MAP.get(disease_name.lower(), [])
    if not expected:
        return 0.0

    sym_norm = [s.lower() for s in input_symptoms]
    hits = 0
    for exp in expected:
        exp_norm = exp.lower()
        if any(exp_norm in s or s in exp_norm for s in sym_norm):
            hits += 1

    return hits / len(expected) if expected else 0.0


@app.route("/")
def home():
    return send_file("index.html")


@app.route("/predict", methods=["POST"])
def predict():
    if pipe is None or le is None:
        return jsonify({"error": "Model or label encoder not loaded on server."})

    try:
        data = request.get_json(force=True)
        symptoms = data.get("symptoms", [])
        symptoms = [str(s).strip() for s in symptoms if str(s).strip()]
        if original_cols:
            original_cols_local = original_cols
        else:
            original_cols_local = get_original_columns(pre)
            if not original_cols_local:
                return jsonify(
                    {
                        "error": "Server doesn't know input feature names. Re-train or inspect preprocessor."
                    }
                )

       
        norm_map_local = {normalize_name(c): c for c in original_cols_local}

       
        row = {c: 0 for c in original_cols_local}

        for s in symptoms:
            key = normalize_name(s)
            if key in norm_map_local:
                row[norm_map_local[key]] = 1
            else:
                for col in original_cols_local:
                    if key in normalize_name(col):
                        row[col] = 1
                        break

        df = pd.DataFrame([row], columns=original_cols_local).astype(float)

        probs = pipe.predict_proba(df)[0]
        probs = np.asarray(probs, dtype=float)

        if probs.sum() > 0:
            probs = probs / probs.sum()

        pred_class = int(np.argmax(probs))

        ranked = []
        sorted_idx = np.argsort(probs)[::-1]

        for i in sorted_idx:
            disease_name = le.inverse_transform([i])[0]
            ml_prob = float(probs[i])
            rule_score = symptom_match_score(symptoms, disease_name)
            final_score = 0.7 * ml_prob + 0.3 * rule_score

            ranked.append(
                {
                    "label": disease_name,
                    "ml_prob": ml_prob,
                    "rule_score": rule_score,
                    "final": final_score,
                }
            )

        ranked = sorted(ranked, key=lambda x: x["final"], reverse=True)

        top = [r for r in ranked if r["final"] > 0.10]
        if not top:
            top = [ranked[0]]

        top3 = [
            {"label": r["label"], "prob": float(r["final"])} for r in top[:3]
        ]

        img_b64 = None
        try:
            if model is not None:
                sample_trans = pre.transform(df) if pre is not None else df.values

                explainer = shap.TreeExplainer(model)
                shap_values = explainer.shap_values(sample_trans)

                if isinstance(shap_values, list):
                    class_idx = pred_class if pred_class < len(shap_values) else 0
                    class_shap = shap_values[class_idx][0]
                    if isinstance(explainer.expected_value, (list, np.ndarray)):
                        expected = explainer.expected_value[class_idx]
                    else:
                        expected = explainer.expected_value
                elif isinstance(shap_values, np.ndarray):
                    if shap_values.ndim == 3:
                        class_idx = pred_class if pred_class < shap_values.shape[0] else 0
                        class_shap = shap_values[class_idx][0]
                        if isinstance(explainer.expected_value, (list, np.ndarray)):
                            expected = explainer.expected_value[class_idx]
                        else:
                            expected = explainer.expected_value
                    elif shap_values.ndim == 2:
                        class_shap = shap_values[0]
                        expected = explainer.expected_value
                    elif shap_values.ndim == 1:
                        class_shap = shap_values
                        expected = explainer.expected_value
                    else:
                        raise ValueError(
                            f"Unsupported shap_values ndim: {shap_values.ndim}"
                        )
                else:
                    raise ValueError("Unsupported shap_values type")

                try:
                    transformed_feature_names = pre.get_feature_names_out()
                except Exception:
                    transformed_feature_names = original_cols_local

                sample_arr = np.asarray(sample_trans)[0]

                exp = shap.Explanation(
                    values=class_shap,
                    base_values=expected,
                    data=sample_arr,
                    feature_names=transformed_feature_names,
                )

                plt.figure(figsize=(8, 5))
                shap.plots.waterfall(exp, show=False, max_display=12)
                buf = io.BytesIO()
                plt.savefig(buf, format="png", bbox_inches="tight")
                plt.close()
                buf.seek(0)
                img_b64 = base64.b64encode(buf.read()).decode()
        except Exception as shap_err:
            print("SHAP error:", shap_err)
            img_b64 = None

        best_label = top3[0]["label"]
        best_key = normalize_name(best_label)
        cure_text = cures_map.get(
            best_key, "Rest, hydration, consult doctor"
        )

        return jsonify(
            {
                "top3": top3,
                "cures": cure_text,
                "shap_plot": img_b64,
            }
        )

    except Exception:
        tb = traceback.format_exc()
        print("Error in /predict:", tb)
        return jsonify({"error": tb})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
