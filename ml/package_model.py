"""모델 팀 학습 결과(team2/outputs)를 서버가 읽는 models/model.joblib (ADR-0002 형식)으로 묶는다.

모델 팀의 train.py 는 기상 없는 모델을 outputs/models/no_weather.joblib 에 (전처리를 품은 sklearn Pipeline),
피처 목록과 온도 보정값을 outputs/metadata.json 의 "no_weather" 에 저장한다. 이 스크립트는 둘을 한 dict 로 묶는다.
모델 팀이 train.py 에서 ADR-0002 형식으로 바로 저장하게 되면 이 스크립트는 지운다.

사용:
    python ml/package_model.py /path/to/team2/outputs            # → models/model.joblib
    python ml/package_model.py /path/to/team2/outputs -o out.joblib
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import joblib

REPO = Path(__file__).resolve().parents[1]


def package(outputs: Path) -> dict:
    meta = json.loads((outputs / "metadata.json").read_text(encoding="utf-8"))
    nw = meta.get("no_weather")
    if not nw or not {"features", "temperature"} <= set(nw):
        raise SystemExit("metadata.json 에 no_weather.features / no_weather.temperature 가 없습니다.")
    # 모델 팀은 sample_weight 로 학습해 정상편 샘플링을 이미 되돌렸다. 다른 방식이면 normal_sample_rate 를 정할 수 없다
    if meta.get("training_correction") != "sample_weight only":
        raise SystemExit(f"training_correction 이 'sample_weight only' 가 아닙니다: {meta.get('training_correction')!r}")
    model_path = outputs / "models" / "no_weather.joblib"
    if model_path.read_bytes()[:7] == b"version":
        raise SystemExit(f"{model_path} 가 Git LFS 포인터입니다. 'git lfs pull' 로 실제 파일을 받으세요.")
    model = joblib.load(model_path)
    sha = hashlib.sha256(model_path.read_bytes()).hexdigest()[:8]
    return {
        "model": model,
        "features": list(nw["features"]),
        "categories": {},  # 범주형은 모델 Pipeline 의 OrdinalEncoder 가 처리한다 (모르는 값은 -1)
        "normal_sample_rate": 1.0,
        "temperature": float(nw["temperature"]),
        "version": f"{meta.get('data_version', 'v3')}-no_weather-{sha}",
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("outputs", type=Path, help="모델 팀 결과 폴더 (metadata.json, models/no_weather.joblib)")
    p.add_argument("-o", "--out", type=Path, default=REPO / "models" / "model.joblib")
    args = p.parse_args()
    artifact = package(args.outputs)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, args.out)
    print(f"{args.out} 저장: version={artifact['version']}, 피처 {len(artifact['features'])}개, "
          f"temperature={artifact['temperature']:.4f}")


if __name__ == "__main__":
    main()
