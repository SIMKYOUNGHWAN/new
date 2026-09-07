"""데이터 수집 계층.

실 API(한국은행 ECOS, FRED)와 샘플 데이터 생성기를 같은 인터페이스로 감싼다.
USE_SAMPLE=True 이면 네트워크 없이 동작한다.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests

from . import config

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- 실 API
def fetch_ecos(stat_code: str, item_code: str, start: str, end: str,
               cycle: str = "D") -> pd.Series:
    """한국은행 ECOS 통계 조회. 실패 시 예외를 올린다."""
    if not config.ECOS_API_KEY:
        raise RuntimeError("ECOS_API_KEY 가 설정되지 않았습니다.")

    url = (f"{config.ECOS_BASE}/{config.ECOS_API_KEY}/json/kr/1/10000/"
           f"{stat_code}/{cycle}/{start}/{end}/{item_code}")
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    payload = resp.json()

    rows = payload.get("StatisticSearch", {}).get("row", [])
    if not rows:
        raise RuntimeError(f"ECOS 응답에 데이터가 없습니다: {stat_code}/{item_code}")

    idx = pd.to_datetime([r["TIME"] for r in rows], format="%Y%m%d"
                         if cycle == "D" else "%Y%m")
    vals = pd.to_numeric([r["DATA_VALUE"] for r in rows], errors="coerce")
    return pd.Series(vals, index=idx).dropna().sort_index()


def fetch_fred(series_id: str, start: str) -> pd.Series:
    """FRED 시계열 조회. 실패 시 예외를 올린다."""
    if not config.FRED_API_KEY:
        raise RuntimeError("FRED_API_KEY 가 설정되지 않았습니다.")

    params = {
        "series_id": series_id,
        "api_key": config.FRED_API_KEY,
        "file_type": "json",
        "observation_start": start,
    }
    resp = requests.get(config.FRED_BASE, params=params, timeout=20)
    resp.raise_for_status()
    obs = resp.json().get("observations", [])

    idx, vals = [], []
    for o in obs:
        if o["value"] in (".", "", None):
            continue
        idx.append(pd.to_datetime(o["date"]))
        vals.append(float(o["value"]))
    if not vals:
        raise RuntimeError(f"FRED 응답에 데이터가 없습니다: {series_id}")
    return pd.Series(vals, index=pd.DatetimeIndex(idx)).sort_index()


# ---------------------------------------------------------------- 샘플
def _sample_series(n: int, start_val: float, vol: float, drift: float = 0.0,
                   freq: str = "D", seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    steps = rng.normal(drift, vol, n)
    vals = start_val + np.cumsum(steps)

    # end 가 해당 freq 의 유효 시점이 아니면 date_range 가 한 칸 짧아지므로
    # 오프셋으로 끝점을 먼저 정렬한다.
    end = pd.Timestamp(date.today())
    offset = pd.tseries.frequencies.to_offset(freq)
    if not offset.is_on_offset(end):
        end = end + offset

    idx = pd.date_range(end=end, periods=n, freq=freq)
    return pd.Series(vals, index=idx)


def sample_bundle() -> dict[str, pd.Series]:
    """모든 지표의 샘플 시계열을 생성한다."""
    bundle = {
        "usdkrw":     _sample_series(750, 1290, 4.5, 0.05, "B", seed=1),
        "dxy":        _sample_series(750, 101.0, 0.35, 0.002, "B", seed=2),
        "kr_rate":    _sample_series(36, 3.50, 0.06, -0.01, "ME", seed=3),
        "us_rate":    _sample_series(36, 5.25, 0.08, -0.03, "ME", seed=4),
        "trade_bal":  _sample_series(36, 30, 18, 0.2, "ME", seed=5),
        "flows":      _sample_series(36, 200, 700, 0, "ME", seed=6),
        "cds":        _sample_series(36, 32, 1.6, 0.0, "ME", seed=7),
        "implied_vol": _sample_series(120, 7.8, 0.25, 0, "B", seed=8),
        "sentiment":  _sample_series(60, 0.0, 0.30, 0, "B", seed=9),
        "carry":      _sample_series(36, 3.2, 0.15, -0.01, "ME", seed=10),
        "kospi":      _sample_series(750, 2600, 22, 0.3, "B", seed=11),
        "oil":        _sample_series(750, 78, 1.3, 0.0, "B", seed=12),
    }
    # 음수가 될 수 없는 지표는 하한을 둔다.
    for key, floor in (("cds", 8.0), ("implied_vol", 3.0), ("carry", 0.5)):
        bundle[key] = bundle[key].clip(lower=floor)
    return bundle


# ---------------------------------------------------------------- 통합
def load_raw() -> dict[str, pd.Series]:
    """설정에 따라 실 API 또는 샘플 데이터를 반환한다.

    실 API 호출이 하나라도 실패하면 전체를 샘플로 대체하지 않고
    예외를 올려 배치가 이전 스냅샷을 유지하도록 한다.
    """
    if config.USE_SAMPLE:
        log.info("샘플 데이터 모드로 수집합니다.")
        return sample_bundle()

    log.info("실 API 모드로 수집합니다.")
    end = date.today()
    start_d = (end - timedelta(days=365 * 3)).strftime("%Y%m%d")
    start_m = (end - timedelta(days=365 * 3)).strftime("%Y%m")
    end_d = end.strftime("%Y%m%d")
    end_m = end.strftime("%Y%m")
    fred_start = (end - timedelta(days=365 * 3)).strftime("%Y-%m-%d")

    bundle: dict[str, pd.Series] = {}

    # 원/달러 환율 (ECOS 731Y001, 0000001 = 원/미국달러)
    bundle["usdkrw"] = fetch_ecos("731Y001", "0000001", start_d, end_d, "D")
    # 한국 기준금리 (ECOS 722Y001, 0101000)
    bundle["kr_rate"] = fetch_ecos("722Y001", "0101000", start_m, end_m, "M")

    # 미국 지표는 FRED
    bundle["us_rate"] = fetch_fred("FEDFUNDS", fred_start)
    bundle["dxy"] = fetch_fred("DTWEXBGS", fred_start)
    bundle["oil"] = fetch_fred("DCOILWTICO", fred_start)

    # 아직 매핑하지 않은 지표는 샘플로 채운다(부분 도입 단계).
    fallback = sample_bundle()
    for key in ("trade_bal", "flows", "cds", "implied_vol",
                "sentiment", "carry", "kospi"):
        bundle.setdefault(key, fallback[key])

    return bundle
