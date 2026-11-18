# Flight Delay Predictor

BTS 항공 운항 데이터로 미국 국내선의 **지연**(출발 15분 이상)과 **결항** 확률을 예측하는 서비스.
용어 정의는 [CONTEXT.md](CONTEXT.md), 주요 결정은 [docs/adr/](docs/adr/) 참고.

## 구조

```
app/            Flask 서버 + 프론트 (static/index.html, app.js)
  predictor.py  예측기 인터페이스. 모델 파일이 없으면 더미 예측기 사용
  data/         드롭다운용 항공사·공항 목록 (임시값)
ml/             데이터 처리·학습 코드 (팀 작업 영역)
models/         학습된 모델 파일 (model.joblib)
tests/          API 테스트
```

상단 배경 영상(`app/static/video/sky-loop.mp4`)은 Coverr의 "Airplane flying through the clouds"를 반복 재생용으로 이어 붙이고 1280px로 압축한 것입니다. Coverr 라이선스로 출처 표기 없이 사용할 수 있습니다.

## 실행

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
flask --app app run --debug     # http://localhost:5000
pytest
```

## API

- `GET /api/options` → `{ airlines: [{code, name}], airports: [{code, name}] }`
- `POST /api/predict/hourly` 같은 요청 본문 → `{ model_version, hours: [{hour, delay_probability, cancel_probability}] }` (06~22시, 예정 소요시간 유지)
- `POST /api/predict` 요청 본문 `{ airline, origin, dest, date: "YYYY-MM-DD", dep_time: "HH:MM", arr_time: "HH:MM" }` (시각은 각 공항 현지 시각)
  - 200 → `{ delay_probability, cancel_probability, model_version }`
  - 400 → `{ errors: { <필드>: <메시지> } }`

## 모델 붙이기

`models/model.joblib`을 두고, 데이터 팀 `src/` 폴더 경로를 `FLIGHT_FEATURES_SRC`에 지정한 뒤 서버를 재시작하면 더미 대신 실제 모델이 쓰입니다.
서버는 그 폴더의 `service_features.build_service_features`로 피처를 만들고, 피처 생성에 필요한 `aggregates/`는 데이터 팀 `config`가 가리키는 경로에서 읽습니다.

```bash
FLIGHT_FEATURES_SRC=/path/to/airline_delay/src flask --app app run
```

모델 파일 형식과 이유는 [ADR-0002](docs/adr/0002-service-features-and-model-artifact.md)에 있습니다.
