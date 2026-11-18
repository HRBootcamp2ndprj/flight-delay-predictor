"""웹 서비스용: '날씨를 뺀' 학습 피처를 aggregates/ 만 조회해서 만든다.

규칙 (학습셋과 동일)
  - 운항월 M 의 BTS 기반 피처는 src = min(M-3, as_of 월-3) 월 말까지 공개된 BTS만 사용
  - hist_*        : src-11 ~ src 월 실적 (monthly_outcomes_*), 베이지안 평활 m=50
  - *_proxy_ly    : 운항일 D-364/371/357 의 예정 편수 평균 (sched_counts_*)
  - *_proxy_recent: src 월 중 운항일과 같은 요일인 날들의 평균 편수
  - origin_yoy_ratio: 출발 공항 src 월 편수 / src-12 월 편수
  - tail_*_hist   : 참조일(D-364/371/357 + src 월 같은 요일)의 같은 항공사·편명·출발 공항 편 기체 일정 (tail_sameday/)
  - Distance      : route_distance (src 이하 최신 월), CRSElapsedTime: 예정 출발·도착 시각과 공항 시간대로 계산

집계표 범위: src 가 집계표의 마지막 달보다 뒤면 그 달 표가 비어 피처가 0 이 된다. 그래서
  on_stale="clamp"(기본) → src 를 집계표 마지막 달로 내리고 source_clamped=True, source_lag_months 로 표시
  on_stale="raise"       → StaleAggregatesError
학습셋에서는 source_lag_months 가 항상 3 이다. 값이 크면 집계표를 갱신해야 한다.

사용:
    from service_features import build_service_features, build_service_features_batch
    build_service_features(dict(Reporting_Airline="DL", Flight_Number_Reporting_Airline="1209", Origin="PDX",
                                Dest="SLC", FlightDate="2025-08-23", CRSDepTime="1315", CRSArrTime="1607"),
                           as_of_date="2025-08-20", features=model_features)
    # 출발 시각만 다른 여러 편은 한 번에 (조회를 한 번만 한다)
    build_service_features_batch([dict(f, CRSDepTime=t) for t in times], as_of_date="2025-08-20")
"""
import sys
import warnings
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import column_selection as S  # noqa: E402
import config as C  # noqa: E402
import feature_engineering as FE  # noqa: E402
from preprocess_flights import load_station_map, local_naive, localize  # noqa: E402

FMT = "%Y-%m-%d"
INPUT_COLS = ("Reporting_Airline", "Flight_Number_Reporting_Airline", "Origin", "Dest", "FlightDate", "CRSDepTime",
              "CRSArrTime")


class StaleAggregatesError(ValueError):
    """기준월(src)이 집계표 범위를 넘음 → preprocess_flights.py 로 aggregates/ 갱신 필요."""


@lru_cache(maxsize=None)
def _station_map():
    return load_station_map()


@lru_cache(maxsize=1)
def last_aggregate_month():
    """집계표에 실적·편수가 모두 들어 있는 마지막 달 (편수 표는 그 달 말일까지 있어야 완전한 달)."""
    hist_last = pd.Period(pd.read_parquet(C.AGG / "monthly_outcomes_hist_carrier.parquet", columns=["ym"])["ym"].max(),
                          freq="M")
    last_day = pd.Timestamp(pd.read_parquet(C.AGG / "sched_counts_origin_sched_deps_day.parquet",
                                            columns=["FlightDate"])["FlightDate"].max())
    sched_last = last_day.to_period("M") if last_day.is_month_end else last_day.to_period("M") - 1
    return min(hist_last, sched_last)


@lru_cache(maxsize=64)
def _hist_table(name, src):
    """src(월 문자열)를 마지막 달로 하는 12개월 창의 hist 표."""
    sp = pd.Period(src, freq="M")
    months = [str(sp - i) for i in range(C.HIST_WINDOW_MONTHS)]
    counts = pd.read_parquet(C.AGG / f"monthly_outcomes_{name}.parquet", filters=[("ym", "in", months)])
    target = str(sp + C.BTS_LAG_MONTHS)
    t = FE.rolling_hist_table(counts, name, [target], C.HIST_WINDOW_MONTHS, C.HIST_SMOOTH_M, lag=C.BTS_LAG_MONTHS)
    return t.drop(columns=["hist_month", "window_first_month", "window_last_month"])


@lru_cache(maxsize=256)
def _sched(name, lo, hi):
    return pd.read_parquet(C.AGG / f"sched_counts_{name}.parquet",
                           filters=[("FlightDate", ">=", lo), ("FlightDate", "<=", hi)])


@lru_cache(maxsize=32)
def _tail_month(period):
    p = pd.Period(period, freq="M")
    f = C.AGG / "tail_sameday" / f"year={p.year}" / f"month={p.month:02d}" / "part.parquet"
    if not f.exists():
        return None
    t = pd.read_parquet(f, columns=["FlightDate"] + FE.TAIL_KEY + ["tail_leg_index_of_day", "tail_sched_turn_min",
                                                                  "tail_prev_origin", "tail_prev_sched_elapsed"])
    t["FlightDate"] = pd.to_datetime(t["FlightDate"])
    return t


@lru_cache(maxsize=1)
def _route_distance():
    return pd.read_parquet(C.AGG / "route_distance.parquet")


def _elapsed_minutes(f, sm):
    """예정 소요시간: 도착 현지 날짜를 출발일 0/+1/-1일 중 0 < (도착 UTC - 출발 UTC) <= 24h 인 가장 이른 값으로.
    공항 시간대를 모르거나 시각이 잘못되면 NaN."""
    dep, _ = localize(local_naive(f["FlightDate"], f["CRSDepTime"]), f["Origin"].map(sm["timezone"]))
    best = pd.Series(np.nan, index=f.index)
    for k in (-1, 0, 1):
        arr, _ = localize(local_naive(f["FlightDate"], f["CRSArrTime"]) + pd.Timedelta(days=k),
                          f["Dest"].map(sm["timezone"]))
        m = (arr - dep).dt.total_seconds() / 60
        ok = (m > 0) & (m <= 24 * 60) & (best.isna() | (m < best))
        best = best.where(~ok, m)
    return best


def _source_months(dates, as_of_date, on_stale):
    """행별 기준월 src 와 집계표 범위로 내렸는지 여부."""
    cap = pd.Timestamp(as_of_date).to_period("M") - C.BTS_LAG_MONTHS
    src = pd.Series([min(C.source_month(m), cap) for m in dates.dt.to_period("M")], index=dates.index)
    last = last_aggregate_month()
    stale = src > last
    if stale.any():
        msg = (f"기준월 {src[stale].max()} 이 집계표 마지막 달 {last} 보다 뒤입니다 — "
               "preprocess_flights.py 로 aggregates/ 를 갱신하세요")
        if on_stale == "raise":
            raise StaleAggregatesError(msg)
        warnings.warn(msg + f" (지금은 {last} 로 계산)", stacklevel=3)
    return src.where(~stale, last), stale


def _needs(features):
    """만들 피처 목록에서 비싼 단계(과거 실적·작년 대비·최근 혼잡도·기체 일정)가 필요한지."""
    if features is None:
        return dict(hist=True, ly=True, recent=True, tail=True)
    fs = set(features)
    return dict(hist=any(x.startswith("hist_") for x in fs),
                ly=any(x.endswith("_proxy_ly") for x in fs),
                recent=any(x.endswith("_proxy_recent") for x in fs) or "origin_yoy_ratio" in fs,
                tail=bool(fs & set(FE.TAIL_HIST_FEATURES)))


def build_service_features_batch(flights, as_of_date, features=None, on_stale="clamp"):
    """flights: dict 목록 (Reporting_Airline, Flight_Number_Reporting_Airline, Origin, Dest, FlightDate(YYYY-MM-DD),
    CRSDepTime(hhmm), CRSArrTime(hhmm)). as_of_date: 예측하는 날(이 날 기준 공개된 BTS만 사용).
    features: 만들 피처 이름 목록 (모델 파일의 features). None 이면 전부. 목록에 없는 단계는 계산하지 않는다.
    on_stale: "clamp" | "raise" (모듈 설명 참고).
    반환: 입력 순서대로 DataFrame — 날씨를 뺀 학습 피처 + source_max_month, source_lag_months, source_clamped."""
    if on_stale not in ("clamp", "raise"):
        raise ValueError("on_stale 은 'clamp' 또는 'raise'")
    need = _needs(features)
    sm = _station_map()
    f = pd.DataFrame([{k: str(fl[k]) for k in INPUT_COLS} for fl in flights])
    dates = pd.to_datetime(f["FlightDate"])
    src, clamped = _source_months(dates, as_of_date, on_stale)

    f["DayOfWeek"] = dates.dt.dayofweek + 1               # ISO: 월=1 … 일=7 (BTS DayOfWeek 와 같음)
    f["CRSElapsedTime"] = _elapsed_minutes(f, sm)
    f["dep_hour_local"] = FE.hhmm_to_minutes(f["CRSDepTime"]) % 1440 // 60
    f["arr_hour_local"] = FE.hhmm_to_minutes(f["CRSArrTime"]) % 1440 // 60
    out = FE.flight_calendar_features(f)
    for c in ("Reporting_Airline", "Origin", "Dest", "CRSElapsedTime"):
        out[c] = f[c]

    rd = f[["Origin", "Dest"]].assign(src=src.astype(str)).reset_index().merge(_route_distance(), on=["Origin", "Dest"])
    rd = rd[rd["source_month"] <= rd["src"]].sort_values("source_month").groupby("index")["Distance"].last()
    out["Distance"] = rd.reindex(f.index).astype(float)

    if need["ly"]:
        lags = C.PROXY_LY_LAGS_DAYS
        lo = (dates.min() - pd.Timedelta(days=max(lags))).strftime(FMT)
        hi = (dates.max() - pd.Timedelta(days=min(lags))).strftime(FMT)
        ly = FE.congestion_lag_features(f, {k: _sched(k, lo, hi) for k in FE.CONGESTION_SPECS}, lags, "proxy_ly")
        # 작년 같은 요일 중 가장 늦은 날이 기준월 말보다 뒤면 아직 공개 전 → NaN
        late = (dates - pd.Timedelta(days=min(lags))) > src.map(lambda p: p.end_time.normalize())
        for c in ly.columns:
            out[c] = ly[c].where(~late)

    for sp in sorted(set(src)):                          # 기준월이 같은 행끼리 (보통 하나)
        idx = src.index[src == sp]
        fs = f.loc[idx]
        src_end = sp.end_time.normalize()
        if need["hist"]:
            for name, keys in FE.HIST_SPECS.items():
                t = _hist_table(name, str(sp))
                row = fs[keys].assign(dep_hour_local=fs["dep_hour_local"].astype(float))[keys].merge(
                    t, on=keys, how="left")
                for c in (f"{name}_delay_rate", f"{name}_cancel_rate", f"{name}_n_flights"):
                    out.loc[idx, c] = row[c].to_numpy(dtype=float)
        if need["recent"]:
            src_counts = {k: _sched(k, sp.start_time.strftime(FMT), src_end.strftime(FMT)) for k in FE.CONGESTION_SPECS}
            rec = FE.congestion_recent_features(fs, src_counts, sp)
            for c in rec.columns:
                out.loc[idx, c] = rec[c]
            prev = _sched("origin_sched_deps_day", (sp - 12).start_time.strftime(FMT), (sp - 12).end_time.strftime(FMT))
            yoy = FE.origin_yoy_table(pd.concat([prev, src_counts["origin_sched_deps_day"]]), sp)
            out.loc[idx, "origin_yoy_ratio"] = fs["Origin"].map(yoy).to_numpy(dtype=float)
        if need["tail"]:
            d = pd.to_datetime(fs["FlightDate"])
            periods = {sp} | {pd.Period(x, freq="M") for x in pd.date_range(
                d.min() - pd.Timedelta(days=max(C.TAIL_LY_LAGS_DAYS)), d.max() - pd.Timedelta(days=min(C.TAIL_LY_LAGS_DAYS)))}
            refs = [t for t in (_tail_month(str(p)) for p in sorted(periods) if p <= sp) if t is not None]
            if refs:
                th = FE.tail_hist_features(fs, pd.concat(refs, ignore_index=True), sp, C.TAIL_LY_LAGS_DAYS)
                for k in FE.TAIL_HIST_FEATURES:
                    out.loc[idx, k] = th[k]

    out["source_max_month"] = src.astype(str)
    out["source_lag_months"] = [(m - s).n for m, s in zip(dates.dt.to_period("M"), src)]
    out["source_clamped"] = clamped.to_numpy()
    return out


def build_service_features(flight, as_of_date, features=None, on_stale="clamp"):
    """한 편. 인자는 build_service_features_batch 와 같고 반환은 dict."""
    return build_service_features_batch([flight], as_of_date, features, on_stale).iloc[0].to_dict()


def service_feature_names():
    """build_service_features 가 만드는 학습 피처 (모든 목록에서 기상 피처를 뺀 것)."""
    lists = S.feature_lists("proxy_ly")
    allf = list(dict.fromkeys(f for k, v in lists.items() for f in v))
    weather = set(S.ORIGIN_WEATHER_FEATURES) | set(S.DEST_WEATHER_FEATURES)
    return [f for f in allf if f not in weather]
