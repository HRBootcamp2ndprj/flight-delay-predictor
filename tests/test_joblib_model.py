"""ADR-0001 계약대로 저장한 실제 sklearn Pipeline을 models/ 에 두었을 때의 동작."""

from datetime import date

import joblib
import pandas as pd
import pytest
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from app import create_app
from app.predictor import FEATURE_COLUMNS, load_predictor

TODAY = date(2024, 6, 1)
SEEN = {"airline": "AA", "origin": "JFK", "dest": "LAX", "date": "2024-07-04", "dep_time": "17:30"}
UNSEEN = {**SEEN, "airline": "UA", "origin": "ORD", "dest": "SFO"}  # 학습 데이터에 없는 범주


def save_models(models_dir, handle_unknown):
    X = pd.DataFrame(
        [
            {"FlightDate": "2024-07-04", "Month": 7, "DayofMonth": 4, "DayOfWeek": 4, "CRSDepTime": t,
             "Reporting_Airline": al, "Origin": o, "Dest": d}
            for al, o, d in [("AA", "JFK", "LAX"), ("DL", "ATL", "MCO")]
            for t in (800, 1800)
        ],
        columns=FEATURE_COLUMNS,
    )
    y = [0, 1, 0, 1]
    pre = ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown=handle_unknown), ["Reporting_Airline", "Origin", "Dest"]),
        ("num", "passthrough", ["CRSDepTime"]),
    ])
    pipe = Pipeline([("pre", pre), ("clf", LogisticRegression())]).fit(X, y)
    joblib.dump(pipe, models_dir / "delay.joblib")
    joblib.dump(pipe, models_dir / "cancel.joblib")


def client_for(models_dir):
    return create_app(load_predictor(models_dir), today=lambda: TODAY).test_client()


@pytest.mark.parametrize("endpoint", ["/api/predict", "/api/predict/hourly"])
def test_contract_model_serves_probabilities(tmp_path, endpoint):
    save_models(tmp_path, handle_unknown="ignore")
    client = client_for(tmp_path)
    for body in (SEEN, UNSEEN):
        res = client.post(endpoint, json=body)
        assert res.status_code == 200
        assert res.get_json()["model_version"].startswith("joblib:")


@pytest.mark.parametrize("endpoint", ["/api/predict", "/api/predict/hourly"])
def test_model_failure_returns_json_error(tmp_path, endpoint):
    save_models(tmp_path, handle_unknown="error")
    res = client_for(tmp_path).post(endpoint, json=UNSEEN)
    assert res.status_code == 500
    assert res.is_json
    assert "_" in res.get_json()["errors"]
