# delay-cast

BTS 항공 운항 데이터로 미국 국내선의 **지연**(출발 15분 이상)과 **결항** 확률을 예측하는 서비스.
용어 정의는 [CONTEXT.md](CONTEXT.md), 주요 결정은 [docs/adr/](docs/adr/) 참고.

## 구조

```
app/            Flask 서버 + 프론트 (static/index.html, app.js, style.css, video/)
  predictor.py  예측기. models/model.joblib 이 없으면 더미 예측기 사용
  data/         드롭다운용 항공사·공항 목록 (임시값. 학습 데이터 범위로 바꿀 예정)
ml/             모델 담당 안내
  data_pipeline/  데이터 팀 파이프라인. service_features.py 가 서비스 피처를 만든다
  weather_download/  공항 기상 다운로드, station_map.csv (공항 시간대)
data/aggregates/  서비스 피처용 BTS 집계표 (데이터 팀이 갱신)
models/         학습된 모델 파일 (model.joblib, 커밋하지 않음)
tests/          API 테스트, 모델 계약(ADR-0002) 테스트
docs/adr/       주요 결정 기록
docs/design/    화면 스크린샷
```

서비스 피처에 필요한 코드와 데이터(`ml/data_pipeline/`, `data/aggregates/`, `station_map.csv`)는 저장소에 있습니다. 실제 모델로 서버를 띄우려면 `models/model.joblib`([ADR-0002](docs/adr/0002-service-features-and-model-artifact.md) 형식)만 받으면 됩니다. 학습셋과 BTS 원본은 용량 때문에 저장소 밖에 있습니다([ml/data_pipeline/README.md](ml/data_pipeline/README.md)).

집계표는 새 BTS 달이 공개될 때마다 데이터 팀이 `preprocess_flights.py`로 갱신합니다. 갱신이 밀리면 예측 가능한 출발일이 줄어들고, 화면이 그 이유를 보여 줍니다.

상단 배경 영상(`app/static/video/sky-loop.mp4`)은 Coverr의 "Airplane flying through the clouds"를 반복 재생용으로 이어 붙이고 1280px로 압축한 것입니다. Coverr 라이선스로 출처 표기 없이 사용할 수 있습니다.

## 실행

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
flask --app app run --debug     # http://localhost:5000
pytest
```

## API

- `GET /api/options` → `{ airlines: [{code, name, name_ko}], airports: [{code, name, name_ko}], dates: {min, max, limit_note} }`
  - `dates.max`는 예측 가능한 마지막 출발일. 집계표가 오래돼 365일보다 짧아지면 `limit_note`에 이유가 담긴다
- `POST /api/predict/hourly` 같은 요청 본문 → `{ model_version, hours: [{hour, delay_probability, cancel_probability}] }` (06~22시, 예정 소요시간 유지)
- `POST /api/predict` 요청 본문 `{ airline, origin, dest, date: "YYYY-MM-DD", dep_time: "HH:MM", arr_time: "HH:MM" }` (시각은 각 공항 현지 시각)
  - 200 → `{ delay_probability, cancel_probability, model_version }`
  - 400 → `{ errors: { <필드>: <메시지> } }` (예측 가능 기간 밖의 날짜도 `date` 오류)
  - 500 → `{ errors: { _: <메시지> } }` (피처 생성이나 모델 예측 실패)

## 모델 붙이기

`models/model.joblib`을 두고 서버를 재시작하면 더미 대신 실제 모델이 쓰입니다. 모델 팀 학습 결과(`machine` 브랜치의 `team2/outputs`)는 아래처럼 이 파일로 묶습니다. 모델 파일이 Git LFS에 있으므로 먼저 `git lfs pull`로 받습니다.

```bash
python ml/package_model.py /path/to/team2/outputs     # → models/model.joblib
```
 피처는 `ml/data_pipeline/service_features.py`(데이터 팀 `data-mgb` 브랜치)로 만들고, 다른 경로를 쓰려면 `FLIGHT_FEATURES_SRC`에 지정합니다.
서버는 그 폴더의 `service_features.build_service_features`로 피처를 만들고, `aggregates/`와 `station_map.csv`는 데이터 팀 `config`가 가리키는 경로에서 읽습니다.
모델 파일이 계약에 맞지 않거나 `service_features.py`를 찾지 못하면 서버가 시작하지 않고 이유를 알려 줍니다.

```bash
flask --app app run                                        # ml/data_pipeline 사용
FLIGHT_FEATURES_SRC=/other/path/to/data_pipeline flask --app app run   # 다른 경로를 쓸 때
```

모델 파일 형식과 이유는 [ADR-0002](docs/adr/0002-service-features-and-model-artifact.md)에 있습니다.
