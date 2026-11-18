# ml/

모델 담당이 보는 안내. 데이터 처리와 학습 데이터 생성은 데이터 팀 코드(`airline_delay/src/`)와 문서(`processed_v3/` 안의 데이터셋 v3 PDF, `data_quality_report.md`)가 기준이다.

## 데이터

- 학습셋은 `processed_v3/ml/split=train|validation|test/part-YYYY-MM.parquet`. 모델 담당은 `ml/`과 `feature_lists.json`만 받으면 된다(약 380 MB).
- 기간과 분할: train 2022~2023년, validation 2024년, test 2025년 운항.
- 레이블 `label`: 0 정상, 1 지연(출발 15분 이상), 2 결항. 용어는 [CONTEXT.md](../CONTEXT.md).
- train은 정상편만 20%로 줄였다(정상 40.8% / 지연 54.0% / 결항 5.2%). validation과 test는 원본 비율 그대로다.

## 학습 규칙

- 피처는 `feature_lists.json`의 목록에서만 고른다. 지금 서비스는 기상 없는 `no_weather` 목록을 쓴다. 기상 피처는 서비스에서 만들 수 없어서, 들어 있으면 서버가 시작하지 않는다.
- 학습 금지 컬럼(실제 시각·지연, 결항 사유, `label_arr`, `sample_rate`, `sample_weight`, `*_oracle`, `*_sameday` 등)은 쓰지 않는다.
- 결측 대체, 인코딩, 스케일링은 train에만 fit한다. 결측은 NaN 그대로 둬도 된다(XGBoost가 처리).
- 확률 보정: `sample_weight`로 학습하거나, 아니면 `normal_sample_rate: 0.2`로 저장한다. 서버가 보정한다.
- 평가는 validation·test에서 클래스별 PR-AUC·Recall, macro F1, 로그 손실로 본다. 결항이 1~2%라 정확도는 의미가 없다.
- 실험 순서는 `base` → `base_plus_candidates` → `with_dest_weather` → `experimental_tail`을 권한다. 서비스에 붙일 모델은 그중 `no_weather`로 다시 학습한다.

## 모델 파일

산출물은 `models/model.joblib` 하나다. 계약은 [ADR-0002](../docs/adr/0002-service-features-and-model-artifact.md)를 따른다.

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
- 드롭다운 항공사·공항 목록(`app/data/*.json`)을 학습 데이터 범위로 바꿀 때 기준(편수가 적은 공항을 뺄지 등)
