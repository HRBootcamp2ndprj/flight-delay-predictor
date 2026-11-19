"""드롭다운 목록(app/data/airlines.json, airports.json)을 BTS 집계표에서 만든다.

최근 12개월(집계표 마지막 달 기준)에 운항 기록이 있는 항공사와 공항을 운항이 많은 순으로 담는다.
이름은 app/data/names.json(사람이 관리)에서 붙이고, 거기 없는 공항은 station_map.csv 이름을 다듬어 영문으로만 쓴다.
집계표를 갱신하면 이 스크립트도 다시 돌린다:
    python ml/build_options.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
AGG = REPO / "data" / "aggregates"
DATA = REPO / "app" / "data"
STATION_MAP = REPO / "ml" / "weather_download" / "station_map.csv"

# station_map 이름 끝의 공항 종류·관측소 표기는 화면에 필요 없다
NOISE = re.compile(r"\s*(\((ASOS|AW|CIV|AWOS)\)|INTL\.?|INTERNATIONAL|ARPT|AIRPORT|APT|MUNI(CIPAL)?|RGNL|REGIONAL|FIELD|"
                   r"AFB|\(AW\)|\(CIV\))\s*", re.I)


def tidy(station_name: str) -> str:
    name = NOISE.sub(" ", station_name.replace("_", " ")).strip(" -/")
    name = re.sub(r"\s+", " ", name)
    return name.title() if name.isupper() or name.islower() else name


def recent_counts(table: str, key: str) -> pd.Series:
    df = pd.read_parquet(AGG / f"monthly_outcomes_{table}.parquet", columns=["ym", key, "n"])
    last = pd.Period(df["ym"].max(), freq="M")
    return df[df["ym"] > str(last - 12)].groupby(key)["n"].sum()


def build() -> tuple[list[dict], list[dict]]:
    names = json.loads((DATA / "names.json").read_text(encoding="utf-8"))
    stations = pd.read_csv(STATION_MAP).set_index("bts_iata")["station_name"]

    carriers = recent_counts("hist_carrier", "Reporting_Airline").sort_values(ascending=False)
    missing = [c for c in carriers.index if c not in names["airlines"]]
    if missing:
        raise SystemExit(f"app/data/names.json 에 항공사 이름을 추가하세요: {missing}")
    airlines = [{"code": c, **names["airlines"][c]} for c in carriers.index]

    traffic = recent_counts("hist_origin", "Origin").add(recent_counts("hist_dest", "Dest"), fill_value=0)
    # 예정 소요시간을 계산하려면 공항 시간대가 필요하다
    traffic = traffic[traffic.index.isin(stations.index)].sort_values(ascending=False)
    airports = [{"code": c, **names["airports"].get(c, {"name": tidy(stations[c])})} for c in traffic.index]
    return airlines, airports


def main() -> None:
    airlines, airports = build()
    for name, rows in (("airlines", airlines), ("airports", airports)):
        (DATA / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    named = sum("name_ko" in a for a in airports)
    print(f"항공사 {len(airlines)}곳, 공항 {len(airports)}곳 (한글 이름 {named}곳) → app/data/")


if __name__ == "__main__":
    main()
