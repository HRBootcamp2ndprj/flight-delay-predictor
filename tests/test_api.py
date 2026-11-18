from datetime import date

import pytest

from app import create_app
from app.predictor import DummyPredictor, Prediction


class FixedPredictor:
    def __init__(self):
        self.last_request = None

    def predict(self, request):
        self.last_request = request
        return Prediction(0.25, 0.03, "fixed")


TODAY = date(2024, 6, 1)  # 테스트용 고정 "오늘"
VALID = {"airline": "AA", "origin": "JFK", "dest": "LAX", "date": "2024-07-04", "dep_time": "17:30", "arr_time": "20:45"}


@pytest.fixture
def predictor():
    return FixedPredictor()


@pytest.fixture
def client(predictor):
    return create_app(predictor, today=lambda: TODAY).test_client()


def test_index_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert b"<form" in res.data


def test_options_lists_airlines_and_airports(client):
    data = client.get("/api/options").get_json()
    assert any(a["code"] == "AA" for a in data["airlines"])
    assert any(a["code"] == "JFK" for a in data["airports"])


def test_predict_returns_probabilities(client):
    res = client.post("/api/predict", json=VALID)
    assert res.status_code == 200
    assert res.get_json() == {"delay_probability": 0.25, "cancel_probability": 0.03, "model_version": "fixed"}


def test_predict_builds_service_flight(client, predictor):
    client.post("/api/predict", json={**VALID, "airline": "aa", "dep_time": "07:05"})
    req = predictor.last_request
    assert req.as_of == TODAY
    assert req.to_service_flight() == {
        "Reporting_Airline": "AA",
        "Flight_Number_Reporting_Airline": "",
        "Origin": "JFK",
        "Dest": "LAX",
        "FlightDate": "2024-07-04",
        "CRSDepTime": "0705",
        "CRSArrTime": "2045",
    }


@pytest.mark.parametrize(
    "override, field",
    [
        ({"airline": "ZZ"}, "airline"),
        ({"origin": "XXX"}, "origin"),
        ({"dest": "JFK"}, "dest"),
        ({"date": "2024-13-01"}, "date"),
        ({"date": "2024-05-31"}, "date"),  # 어제
        ({"date": "2025-06-02"}, "date"),  # 366일 뒤
        ({"dep_time": "25:00"}, "dep_time"),
        ({"dep_time": "noon"}, "dep_time"),
        ({"arr_time": ""}, "arr_time"),
        ({"arr_time": "24:00"}, "arr_time"),
    ],
)
def test_predict_rejects_invalid_input(client, override, field):
    res = client.post("/api/predict", json={**VALID, **override})
    assert res.status_code == 400
    assert field in res.get_json()["errors"]


def test_predict_requires_json(client):
    res = client.post("/api/predict", data="nope")
    assert res.status_code == 400


def test_app_falls_back_to_dummy_without_model_files(tmp_path):
    from app.predictor import load_predictor

    assert isinstance(load_predictor(tmp_path), DummyPredictor)


def test_dummy_is_deterministic_and_bounded():
    app = create_app(DummyPredictor(), today=lambda: TODAY).test_client()
    a = app.post("/api/predict", json=VALID).get_json()
    b = app.post("/api/predict", json=VALID).get_json()
    assert a == b
    assert 0 <= a["delay_probability"] <= 1
    assert 0 <= a["cancel_probability"] <= 1
    assert a["model_version"] == "dummy-0"


@pytest.mark.parametrize("d", ["2024-06-01", "2025-06-01"])  # 오늘, 365일 뒤
def test_predict_accepts_booking_window_edges(client, d):
    assert client.post("/api/predict", json={**VALID, "date": d}).status_code == 200


def test_hourly_varies_only_departure_hour(client, predictor):
    seen = []
    predictor.predict = lambda r: (seen.append(r), Prediction(0.1, 0.01, "fixed"))[1]
    res = client.post("/api/predict/hourly", json=VALID)
    assert res.status_code == 200
    data = res.get_json()
    assert data["model_version"] == "fixed"
    assert [h["hour"] for h in data["hours"]] == list(range(6, 23))
    assert data["hours"][0] == {"hour": 6, "delay_probability": 0.1, "cancel_probability": 0.01}
    assert {(r.airline, r.origin, r.dest, r.flight_date) for r in seen} == {("AA", "JFK", "LAX", date(2024, 7, 4))}
    assert [(r.dep_hour, r.dep_minute) for r in seen] == [(h, 0) for h in range(6, 23)]
    # 예정 소요시간 3시간 15분 유지: 17:30 -> 20:45 이므로 06:00 -> 09:15, 22:00 -> 다음날 01:15
    assert (seen[0].arr_hour, seen[0].arr_minute) == (9, 15)
    assert (seen[-1].arr_hour, seen[-1].arr_minute) == (1, 15)


def test_hourly_validates_like_predict(client):
    res = client.post("/api/predict/hourly", json={**VALID, "origin": "XXX"})
    assert res.status_code == 400
    assert "origin" in res.get_json()["errors"]


def test_sky_video_assets_served(client):
    for path in ("/static/video/sky-loop.mp4", "/static/video/sky-loop-poster.jpg"):
        res = client.get(path)
        assert res.status_code == 200, path
        res.close()
