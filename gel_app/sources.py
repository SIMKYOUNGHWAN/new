"""데이터 수집 계층 (조지아 라리).

환율은 NBG, 글로벌 지표는 FRED 에서 받는다. 조지아 거시지표(송금·관광·
FDI·라리화 비율)는 공개 API 가 확인되지 않아 아직 샘플이며, 화면에
어떤 지표가 샘플인지 표시한다.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd
import requests

from . import config, nbg

log = logging.getLogger(__name__)


# ---------------------------------------------------------------- FRED
def fetch_fred(series_id: str, start: str) -> pd.Series:
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
    vals = start_val + np.cumsum(rng.normal(drift, vol, n))

    end = pd.Timestamp(date.today())
    offset = pd.tseries.frequencies.to_offset(freq)
    if not offset.is_on_offset(end):
        end = end + offset
    return pd.Series(vals, index=pd.date_range(end=end, periods=n, freq=freq))


def _seasonal(n: int, base: float, amp: float, noise: float,
              seed: int) -> pd.Series:
    """관광·송금처럼 계절성이 뚜렷한 월별 지표용 샘플."""
    rng = np.random.default_rng(seed)
    end = pd.Timestamp(date.today())
    idx = pd.date_range(end=end + pd.tseries.frequencies.to_offset("ME"),
                        periods=n, freq="ME")
    # 여름(7~8월)에 정점을 찍는 형태
    season = amp * np.sin(2 * np.pi * (idx.month - 4) / 12)
    return pd.Series(base + season + rng.normal(0, noise, n), index=idx)


def sample_bundle() -> dict[str, pd.Series]:
    """모든 지표의 샘플 시계열. 라리 수준(USD/GEL ≈ 2.7)에 맞춘다."""
    bundle = {
        "usdgel":     _sample_series(750, 2.70, 0.006, 0.0, "B", seed=1),
        "eurgel":     _sample_series(750, 3.10, 0.008, 0.0, "B", seed=2),
        "rubgel":     _sample_series(750, 0.030, 0.0004, 0.0, "B", seed=3),
        "trygel":     _sample_series(750, 0.080, 0.0009, -0.00005, "B", seed=4),
        "amdgel":     _sample_series(750, 0.0070, 0.00005, 0.0, "B", seed=5),
        "azngel":     _sample_series(750, 1.59, 0.004, 0.0, "B", seed=6),
        "dxy":        _sample_series(750, 101.0, 0.35, 0.002, "B", seed=7),
        "oil":        _sample_series(750, 78, 1.3, 0.0, "B", seed=8),
        "vix":        _sample_series(750, 17, 0.9, 0.0, "B", seed=9),
        # 조지아 거시 — 계절성 있는 월별 지표
        "remittance": _seasonal(36, 320, 60, 25, seed=10),      # 백만 달러
        "tourism":    _seasonal(36, 350, 220, 40, seed=11),     # 백만 달러
        "fdi":        _sample_series(36, 180, 45, 0.0, "ME", seed=12),
        "trade_bal":  _sample_series(36, -650, 90, 0.0, "ME", seed=13),
        "nbg_rate":   _sample_series(36, 8.0, 0.12, -0.02, "ME", seed=14),
        "reserves":   _sample_series(36, 4800, 130, 5.0, "ME", seed=15),
        "larization": _sample_series(36, 55, 0.6, 0.08, "ME", seed=16),  # %
        "intervention": _sample_series(36, 120, 180, 0.0, "ME", seed=17),
    }
    for key, floor in (("vix", 9.0), ("tourism", 60.0), ("remittance", 120.0),
                       ("reserves", 3000.0), ("nbg_rate", 4.0)):
        bundle[key] = bundle[key].clip(lower=floor)
    return bundle


# ---------------------------------------------------------------- 통합
CURRENCY_KEYS = {
    "USD": "usdgel", "EUR": "eurgel", "RUB": "rubgel",
    "TRY": "trygel", "AMD": "amdgel", "AZN": "azngel",
}


def load_raw() -> dict[str, pd.Series]:
    """설정에 따라 실 API 또는 샘플 데이터를 반환한다.

    환율(NBG)이 실패하면 배치를 중단해 이전 스냅샷을 유지한다.
    보조 지표는 개별적으로 실패해도 샘플로 대체하고 계속 진행한다.
    """
    if config.USE_SAMPLE:
        log.info("샘플 데이터 모드로 수집합니다.")
        b = sample_bundle()
        b["_sampled"] = []
        b["_backfill_left"] = 0
        return b

    log.info("실 API 모드로 수집합니다.")
    end = date.today()
    fred_start = (end - timedelta(days=365 * config.HISTORY_YEARS)).strftime("%Y-%m-%d")

    bundle: dict[str, pd.Series] = {}
    fallback = sample_bundle()
    sampled: list[str] = []

    def _try(key: str, fn, label: str) -> None:
        try:
            s = fn()
            if len(s) == 0:
                raise RuntimeError("빈 응답")
            bundle[key] = s
        except Exception as exc:
            log.warning("%s 실패, 샘플로 대체: %s", label, exc)
            bundle[key] = fallback[key]
            sampled.append(label)

    # ---- 환율: 실패하면 배치 중단 ----
    rates = nbg.update_rates()
    for code, key in CURRENCY_KEYS.items():
        if code in rates.columns:
            s = rates[code].dropna()
            if len(s) > 0:
                bundle[key] = s
                continue
        log.warning("%s 환율이 없어 샘플로 대체합니다.", code)
        bundle[key] = fallback[key]
        sampled.append(f"{code}/GEL")

    if "usdgel" not in bundle or len(bundle["usdgel"]) < 60:
        raise RuntimeError("USD/GEL 환율이 부족해 배치를 중단합니다.")

    # ---- 글로벌 지표 ----
    _try("dxy", lambda: fetch_fred("DTWEXBGS", fred_start), "달러인덱스")
    _try("oil", lambda: fetch_fred("DCOILWTICO", fred_start), "유가")
    _try("vix", lambda: fetch_fred("VIXCLS", fred_start), "VIX")

    # ---- 조지아 거시 ----
    # NBG·Geostat 이 월별로 공표하지만 공개 API 가 확인되지 않았다.
    # 엔드포인트를 찾으면 아래를 _try 로 교체하면 된다.
    for key, label in (
        ("remittance", "송금 유입"),
        ("tourism", "관광 수입"),
        ("fdi", "FDI 유입"),
        ("trade_bal", "무역수지"),
        ("nbg_rate", "NBG 정책금리"),
        ("reserves", "외환보유고"),
        ("larization", "라리화 비율"),
        ("intervention", "NBG 외환개입"),
    ):
        bundle[key] = fallback[key]
        sampled.append(label)

    if sampled:
        log.warning("샘플로 대체된 지표: %s", ", ".join(sampled))

    bundle["_sampled"] = sampled
    bundle["_backfill_left"] = nbg.remaining_backfill()
    return bundle

