"""실제 거시지표: 세계은행 연간 통계, NBG 정책금리, FRED 일별 지표."""
import io
import re
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup

WB = {
    "remittance": ("해외 개인송금 수취", "BX.TRF.PWKR.CD.DT", "백만 USD", 1e6),
    "tourism": ("국제관광 수입", "ST.INT.RCPT.CD", "백만 USD", 1e6),
    "fdi": ("외국인직접투자 순유입", "BX.KLT.DINV.CD.WD", "백만 USD", 1e6),
    "trade_bal": ("상품·서비스 무역수지", "NE.RSB.GNFS.CD", "백만 USD", 1e6),
    "reserves": ("총 외환보유고 (금 포함)", "FI.RES.TOTL.CD", "백만 USD", 1e6),
    "inflation": ("소비자물가 상승률", "FP.CPI.TOTL.ZG", "%", 1),
    "gdp": ("실질 GDP 성장률", "NY.GDP.MKTP.KD.ZG", "%", 1),
}
POLICY = "https://nbg.gov.ge/en/monetary-policy/committee-decisions"


def get(url, **kwargs):
    for attempt in range(2):
        try:
            r = requests.get(url, timeout=(10, 25), **kwargs)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if attempt:
                raise
            time.sleep(1)


def wb_series(key):
    name, indicator, unit, divisor = WB[key]
    url = f"https://api.worldbank.org/v2/country/GEO/indicator/{indicator}"
    result = get(url, params={"format": "json", "per_page": 30}).json()
    values = sorted((item["date"], float(item["value"]) / divisor)
                    for item in result[1] if item.get("value") is not None)
    if not values:
        raise ValueError("공표값 없음")
    values = values[-12:]
    return {"available": True, "name": name, "unit": unit, "frequency": "연간",
            "labels": [x[0] for x in values], "values": [round(x[1], 3) for x in values],
            "source": "World Bank WDI", "url": f"https://data.worldbank.org/indicator/{indicator}?locations=GE",
            "source_updated": result[0].get("lastupdated", "")}


def policy_series():
    soup = BeautifulSoup(get(POLICY).text, "html.parser")
    text = soup.get_text(" ", strip=True)
    part = text.split("New Rate (%)")[-1]
    matches = re.findall(r"(\d{2}\.\d{2}\.\d{2})\s+[-−]?\d+(?:\.\d+)?\s+(\d+(?:\.\d+)?)", part)
    values = sorted((pd.to_datetime(day, format="%d.%m.%y").strftime("%Y-%m-%d"), float(rate))
                    for day, rate in matches)
    if not values or any(not 0 <= v <= 100 for _, v in values):
        raise ValueError("정책금리 표 파싱 실패")
    return {"available": True, "name": "NBG 정책금리", "unit": "%", "frequency": "결정일",
            "labels": [d for d, _ in values], "values": [v for _, v in values],
            "source": "NBG Monetary Policy Committee", "url": POLICY}


def fred_series(series_id, name, unit):
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv"
    frame = pd.read_csv(io.StringIO(get(url, params={"id": series_id}).text), index_col=0, parse_dates=True)
    s = pd.to_numeric(frame[series_id], errors="coerce").dropna().tail(250)
    if s.empty or not np.isfinite(s.to_numpy()).all():
        raise ValueError("FRED 공표값 없음")
    return {"available": True, "name": name, "unit": unit, "frequency": "일별",
            "labels": s.index.strftime("%Y-%m-%d").tolist(), "values": s.round(3).tolist(),
            "source": "FRED", "url": f"https://fred.stlouisfed.org/series/{series_id}"}


def collect():
    tasks = {key: (lambda k=key: wb_series(k)) for key in WB}
    tasks.update({
        "nbg_rate": policy_series,
        "dxy": lambda: fred_series("DTWEXBGS", "미국 광의 무역가중 달러지수", "지수"),
        "vix": lambda: fred_series("VIXCLS", "VIX", "지수"),
        "oil": lambda: fred_series("DCOILWTICO", "WTI 현물유가", "USD/배럴"),
    })
    def run(item):
        key, fn = item
        try:
            return key, fn()
        except Exception as exc:
            return key, {"available": False, "reason": str(exc)[:160]}
    with ThreadPoolExecutor(max_workers=3) as pool:
        out = dict(pool.map(run, tasks.items()))
    for key in ("larization", "intervention"):
        out[key] = {"available": False, "reason": "검증된 자동 수집 시계열 미연결",
                    "url": "https://nbg.gov.ge/en/statistics/statistics-data"}
    return out

