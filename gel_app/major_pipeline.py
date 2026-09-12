"""ECB 공식 환율만 사용하는 주요 통화 배치. 샘플 폴백 없음."""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .analytics import cross_analysis

FILE = Path(__file__).resolve().parent.parent / "major_data" / "snapshot.json"
SOURCE = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
CODES = ("CNY", "EUR", "GBP", "JPY", "TRY")


def parse_history(csv: bytes, now=None) -> pd.DataFrame:
    now = pd.Timestamp(now or datetime.now(timezone.utc)).tz_localize(None).normalize()
    frame = pd.read_csv(io.BytesIO(csv), parse_dates=["Date"]).set_index("Date").sort_index()
    frame = frame.loc[(frame.index >= now - pd.DateOffset(years=3)) & (frame.index <= now)]
    quoted_codes = [code for code in CODES if code != "EUR"]
    frame = frame[["USD", *quoted_codes]].apply(pd.to_numeric, errors="raise")
    if frame.index.has_duplicates or len(frame) < 600:
        raise ValueError("ECB 일간 환율 이력이 부족하거나 날짜가 중복되었습니다.")
    if not np.isfinite(frame.to_numpy()).all() or not (frame > 0).all().all():
        raise ValueError("ECB 환율에 누락 또는 유효하지 않은 가격이 있습니다.")
    if (now - frame.index[-1]).days > 7:
        raise ValueError("ECB 최신 공시가 7일 이상 오래되었습니다.")
    # 원본 단위는 각 통화/EUR. USD로 나누면 각 통화/USD.
    result = frame[quoted_codes].div(frame["USD"], axis=0)
    result["EUR"] = 1.0 / frame["USD"]
    return result


def fetch_history() -> pd.DataFrame:
    with requests.Session() as session:
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        session.mount("https://", HTTPAdapter(max_retries=retry))
        response = session.get(SOURCE, timeout=(15, 60))
        response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        return parse_history(archive.read("eurofxref-hist.csv"))


def build_snapshot(frame: pd.DataFrame) -> dict:
    crosses = {}
    for code in CODES:
        px = frame[code]
        digits = 3 if code == "JPY" else 4
        crosses[code] = {
            "pair": f"USD/{code}", "digits": digits,
            "labels": px.tail(250).index.strftime("%Y-%m-%d").tolist(),
            "values": px.tail(250).round(digits).tolist(),
            "analysis": cross_analysis(px),
        }
    return {"crosses": crosses, "summary": {"sampled_indicators": []},
            "meta": {"mode": "live", "source": "European Central Bank",
                     "source_url": SOURCE, "as_of": frame.index[-1].strftime("%Y-%m-%d"),
                     "generated_at_display": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}}


def load_snapshot():
    try:
        snap = json.loads(FILE.read_text(encoding="utf-8"))
        if snap.get("meta", {}).get("mode") != "live":
            return None
        return snap
    except (OSError, ValueError):
        return None


def run_batch():
    snap = build_snapshot(fetch_history())
    # 검증·모델 계산·JSON 직렬화가 모두 성공한 경우에만 기존 파일 교체.
    content = json.dumps(snap, ensure_ascii=False, allow_nan=False, indent=1)
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(FILE)
    print("ECB 실제 환율 저장 완료:", snap["meta"]["as_of"], list(snap["crosses"]))


if __name__ == "__main__":
    run_batch()

