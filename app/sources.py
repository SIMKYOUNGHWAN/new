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


def fetch_ecos_any(candidates: list[tuple[str, str, str]], start: str, end: str,
                   label: str) -> pd.Series:
    """여러 (통계표, 항목, 주기) 후보를 차례로 시도해 처음 성공한 것을 쓴다.

    ECOS 는 같은 지표라도 통계표에 따라 항목코드 체계가 달라서
    (예: 301Y013 은 000000, 301Y017 은 SA000) 후보를 두고 폴백한다.
    """
    errors = []
    for stat, item, cycle in candidates:
        try:
            s = fetch_ecos(stat, item, start, end, cycle)
            if len(s) > 0:
                log.info("%s: %s/%s (%s) 사용, %d개", label, stat, item, cycle, len(s))
                return s
        except Exception as exc:
            errors.append(f"{stat}/{item}({cycle}): {exc}")
    raise RuntimeError(f"{label} 조회 실패 — " + " | ".join(errors))


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

    핵심 지표(환율)가 실패하면 예외를 올려 배치가 이전 스냅샷을 유지하게 한다.
    보조 지표는 개별적으로 실패해도 샘플로 대체하고 계속 진행한다 —
    지표 하나 때문에 대시보드 전체가 멈추는 편이 더 나쁘다.
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
    fallback = sample_bundle()
    sampled: list[str] = []

    def _try(key: str, fn, label: str) -> None:
        """보조 지표용. 실패하면 샘플로 대체하고 기록만 남긴다."""
        try:
            s = fn()
            if len(s) == 0:
                raise RuntimeError("빈 응답")
            bundle[key] = s
        except Exception as exc:
            log.warning("%s 실패, 샘플로 대체: %s", label, exc)
            bundle[key] = fallback[key]
            sampled.append(label)

    # ---- 핵심 지표: 실패하면 배치를 중단한다 ----
    bundle["usdkrw"] = fetch_ecos("731Y001", "0000001", start_d, end_d, "D")
    bundle["kr_rate"] = fetch_ecos("722Y001", "0101000", start_m, end_m, "M")
    bundle["us_rate"] = fetch_fred("FEDFUNDS", fred_start)
    bundle["dxy"] = fetch_fred("DTWEXBGS", fred_start)

    # ---- 보조 지표 ----
    _try("oil", lambda: fetch_fred("DCOILWTICO", fred_start), "유가")
    _try("kospi", lambda: fetch_ecos("802Y001", "0001000", start_d, end_d, "D"),
         "코스피")

    # 경상수지 — 통계표에 따라 항목코드 체계가 달라 후보를 둔다.
    _try("trade_bal", lambda: fetch_ecos_any(
        [("301Y013", "000000", "M"), ("301Y017", "SA000", "M")],
        start_m, end_m, "경상수지"), "경상수지")

    # 외국인 자본 유출입 = 증권투자(부채). 양수면 유입, 음수면 유출.
    _try("flows", lambda: fetch_ecos_any(
        [("301Y013", "BOPF22000000", "M")],
        start_m, end_m, "증권투자(부채)"), "자본유출입")

    # CDS 대체 — 회사채(AA-) 와 국고채(3년) 의 신용 스프레드.
    # 둘 다 원화 기준이라 환율 효과가 섞이지 않고 국내 신용위험만 남는다.
    def _credit_spread() -> pd.Series:
        corp = fetch_ecos_any(
            [("817Y002", "010300000", "D"), ("721Y001", "010300000", "D")],
            start_d, end_d, "회사채(AA-)")
        govt = fetch_ecos_any(
            [("817Y002", "010200000", "D"), ("721Y001", "010200000", "D")],
            start_d, end_d, "국고채(3년)")
        # 연% 차이를 bp 로 환산한다.
        spread = (corp - govt).dropna() * 100
        if len(spread) == 0:
            raise RuntimeError("스프레드 계산 결과가 비었습니다")
        return spread

    _try("cds", _credit_spread, "신용 스프레드")

    # 감성지수 대체 — VIX 를 표준화해 -1~+1 범위로 뒤집는다.
    # VIX 가 높을수록(공포) 감성은 음수가 되어야 방향이 맞는다.
    def _sentiment() -> pd.Series:
        vix = fetch_fred("VIXCLS", fred_start)
        z = (vix - vix.rolling(120, min_periods=20).mean()) \
            / vix.rolling(120, min_periods=20).std()
        return (-z).clip(-3, 3).dropna()

    _try("sentiment", _sentiment, "시장심리(VIX)")

    # 내재변동성 대체 — 환율의 실현변동성(20일, 연율화).
    def _realized_vol() -> pd.Series:
        px = bundle["usdkrw"]
        ret = np.log(px / px.shift(1))
        return (ret.rolling(20).std() * np.sqrt(252) * 100).dropna()

    _try("implied_vol", _realized_vol, "실현변동성")

    # 캐리 지표 — 한미 금리차를 일별로 펼친다.
    def _carry() -> pd.Series:
        kr = bundle["kr_rate"].reindex(bundle["usdkrw"].index).ffill()
        us = bundle["us_rate"].reindex(bundle["usdkrw"].index).ffill()
        return (kr - us).dropna()

    _try("carry", _carry, "금리차")

    if sampled:
        log.warning("샘플로 대체된 지표: %s", ", ".join(sampled))
    bundle["_sampled"] = sampled          # 화면에 표시하기 위해 함께 넘긴다

    return bundle
