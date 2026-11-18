# ml/data_pipeline/

BTS 운항 데이터와 IEM 공항 기상(METAR)을 합쳐 학습셋(`processed_v3/`)을 만드는 코드.
데이터 자체는 용량이 커서 저장소에 없고, 별도로 공유한다.

## 데이터 폴더 지정

코드는 아래 구조의 **데이터 폴더**를 읽고 씁니다.

```
<데이터 폴더>/
  flight_expectation/flight_expectation/data/bts_selected/   BTS 원본 (월별)
  weather/station_map.csv, weather/asos_raw/                 IEM 기상 원본 (ml/weather_download 로 받음)
  processed_v2/                                              v2 기상 결합 결과 (v3가 재사용)
  processed_v3/                                              최종 결과 (merged/, ml/, aggregates/)
```

환경변수 `AIRLINE_DATA_ROOT`에 이 폴더 경로를 넣으세요.
지정하지 않으면 이 파일의 상위 폴더 중 `weather/station_map.csv`가 있는 곳을 찾습니다.

데이터 폴더가 없어도 `service_features.py`(서비스용 피처 생성)는 저장소의 [`data/aggregates/`](../../data/aggregates/)와
`ml/weather_download/station_map.csv`로 동작합니다.

```bash
export AIRLINE_DATA_ROOT=/path/to/airline_delay        # Windows PowerShell: $env:AIRLINE_DATA_ROOT="C:\...\airline_delay"
```

## 실행 순서

```bash
python ml/weather_download/build_station_map.py   # 공항 → IEM 관측소 매핑
python ml/weather_download/download_asos.py       # 기상 원본 다운로드 (오래 걸림)
python ml/weather_download/validate_asos.py
python -X utf8 ml/data_pipeline/preprocess_weather.py
python -X utf8 ml/data_pipeline/preprocess_flights.py
python -X utf8 ml/data_pipeline/merge_datasets.py
python -X utf8 ml/data_pipeline/validate_dataset.py   # processed_v3/*_report.md 생성
python -X utf8 ml/data_pipeline/visualize_v3.py       # 발표용 차트 (화면 표시)
```

## 파일

| 파일 | 역할 |
|---|---|
| `config.py` | 경로·기간·샘플링 비율 등 상수 |
| `column_selection.py` | 사용 컬럼, 피처 목록(base, with_dest_weather …), 학습 금지 컬럼 |
| `feature_engineering.py` | 기상·달력·혼잡도·과거 실적·기체 일정 피처 |
| `preprocess_weather.py` | METAR 품질 검사와 관측 피처 |
| `preprocess_flights.py` | 레이블, 층화 샘플링, BTS 집계표, 과거 실적 피처 |
| `merge_datasets.py` | 항공편 + 출발·도착 공항 기상 결합 → `merged/`, `ml/` |
| `service_features.py` | 서비스 시점에 같은 피처를 만드는 함수 (`build_service_features`) |
| `validate_dataset.py` | 누수·결측·서비스 일치 검증 리포트 |
| `inspect_data.py` | 원본 탐색 (v1) |
| `visualize_v3.py` | 발표용 시각화 |
| `meta/` | `feature_lists.json`, 품질·피처 선택 리포트 (최신 실행 결과) |

## 서비스에서 피처 만들기 (`service_features.py`)

```python
from service_features import build_service_features, build_service_features_batch
feats = bundle["features"]                       # 모델 파일의 피처 목록
x = build_service_features(flight, as_of_date=today, features=feats)            # 한 편 → dict
X = build_service_features_batch(flights, as_of_date=today, features=feats)     # 여러 편 → DataFrame (입력 순서)
```

- `features`를 넘기면 목록에 없는 단계(기체 일정 `tail_*_hist`, 작년 대비 `*_proxy_ly` 등)는 계산하지 않습니다.
- 출발 시각만 다른 여러 편은 `build_service_features_batch`로 한 번에 넘기세요. 17편 기준 0.1~0.4초입니다
  (한 편씩 17번 부르면 1.8~6.4초).
- **집계표 범위:** 기준월(운항월 − 3, 예측일 월 − 3 중 이른 달)이 `data/aggregates`의 마지막 달보다 뒤면
  - `on_stale="clamp"`(기본): 마지막 달로 내려 계산하고 경고를 냅니다. 결과의 `source_clamped=True`.
  - `on_stale="raise"`: `StaleAggregatesError`.
  - 결과의 `source_lag_months`(운항월 − 기준월)는 학습셋에서 항상 3입니다. 이보다 크면 집계표 갱신이 필요합니다.
- 공항 시간대를 모르면 `CRSElapsedTime`은 NaN입니다.

## 핵심 설계

- **예측 시점** = 예정 출발 UTC − 3시간. 기상은 그 이전 최신 관측만 사용 (`merge_asof` backward, 2시간 이내).
- **레이블** `label`: 0 정상 / 1 출발 15분 이상 지연 / 2 결항. 도착 기준은 `label_arr` (평가용).
- **BTS 공개 지연**: 운항월 M의 피처는 M−3월까지 공개된 BTS만 사용 (과거 실적·혼잡도·기체 일정).
- **분할**: train 2022–23 / validation 2024 / test 2025. train은 정상편 20%만 샘플 → 학습 시 `sample_weight` 사용.

> 저장소의 CONTEXT.md·ADR-0001은 예약 시점 예측과 `ArrDel15` 기준을 가정합니다.
> 이 파이프라인은 출발 3시간 전 예측과 출발 지연 기준이므로 팀 합의가 필요합니다.
