# ml/

데이터 수집 → 전처리 → 학습 코드를 두는 곳.

산출물은 `models/model.joblib` 하나입니다. 계약은 [ADR-0002](../docs/adr/0002-service-features-and-model-artifact.md)를 따릅니다.

```python
lists = json.load(open("processed_v3/feature_lists.json", encoding="utf-8"))
feats = lists["no_weather"]                      # 지금 서비스는 기상 없는 모델
cats = [c for c in lists["categorical"] if c in feats]
for c in cats:
    train[c] = train[c].astype("category")
model = xgb.XGBClassifier(enable_categorical=True, ...).fit(train[feats], train["label"])
joblib.dump({
    "model": model,                              # predict_proba 열 순서 = [정상, 지연, 결항]
    "features": feats,
    "categories": {c: list(train[c].cat.categories) for c in cats},
    "normal_sample_rate": 0.2,                   # sample_weight 로 학습했다면 1.0
    "version": "xgb-no_weather-2026-11-18",
}, "models/model.joblib")
```

## 팀 합의가 필요한 항목 (미정)

- 기상 포함 모델(출발 3시간 전 예측)을 서비스에 붙일지와, 실시간 METAR를 어디서 받을지
- 예측 가능 기간(지금 365일) 안의 먼 미래 항공편 성능 (학습셋은 운항월과 BTS 기준월 간격이 항상 3개월)
- 데이터 범위: 기간(코로나 시기 포함 여부), 공항·항공사 범위 → 범위가 정해지면 `app/data/*.json` 갱신
