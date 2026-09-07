"""예측 이력 추적.

매 배치마다 그날의 예측을 append-only 로 기록한다. 시간이 지나 실제값이
나오면 채점한다. 지금 기록해두지 않으면 나중에 소급이 불가능하므로
일찍 심어두는 편이 낫다.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config

log = logging.getLogger(__name__)

HISTORY_FILE = config.DATA_DIR / "predictions.json"
MAX_RECORDS = 500          # 리포가 무한히 커지지 않도록 제한


def _load() -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as exc:
        log.error("예측 이력 읽기 실패: %s", exc)
        return []


def _save(records: list[dict]) -> None:
    tmp = HISTORY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(records[-MAX_RECORDS:], ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(HISTORY_FILE)


def record(snapshot: dict) -> None:
    """오늘 예측을 기록한다. 같은 날짜가 있으면 덮어쓴다."""
    now = datetime.now(ZoneInfo(config.TIMEZONE))
    today = now.strftime("%Y-%m-%d")

    d = snapshot.get("direction", {})
    mc = snapshot.get("monte_carlo", {})

    entry = {
        "date": today,
        "spot": snapshot["summary"]["latest"],
        "up_probability": d.get("up_probability") if d.get("available") else None,
        "best_model": d.get("best_model") if d.get("available") else None,
        "forecast_1m_median": mc.get("p50", [None])[0],
        "forecast_1m_lower": mc.get("p05", [None])[0],
        "forecast_1m_upper": mc.get("p95", [None])[0],
        "actual_1m": None,        # 한 달 뒤 채워진다
        "direction_correct": None,
        "within_band": None,
    }

    records = [r for r in _load() if r.get("date") != today]
    records.append(entry)
    records.sort(key=lambda r: r["date"])

    _score(records, snapshot)
    _save(records)
    log.info("예측 이력 기록: %s (총 %d건)", today, len(records))


def _score(records: list[dict], snapshot: dict) -> None:
    """한 달이 지난 예측에 실제값을 채워 채점한다."""
    hist = snapshot.get("history", {})
    spot_now = snapshot["summary"]["latest"]
    today = datetime.now(ZoneInfo(config.TIMEZONE)).date()

    for r in records:
        if r.get("actual_1m") is not None:
            continue
        try:
            made = datetime.strptime(r["date"], "%Y-%m-%d").date()
        except ValueError:
            continue

        # 30일이 지났으면 현재 환율을 실제값으로 본다.
        if (today - made).days < 30:
            continue

        r["actual_1m"] = spot_now

        if r.get("up_probability") is not None and r.get("spot"):
            predicted_up = r["up_probability"] >= 50
            actual_up = spot_now > r["spot"]
            r["direction_correct"] = bool(predicted_up == actual_up)

        lo, hi = r.get("forecast_1m_lower"), r.get("forecast_1m_upper")
        if lo is not None and hi is not None:
            r["within_band"] = bool(lo <= spot_now <= hi)

    if hist:
        pass    # 향후 정확한 과거 일자 대조로 개선할 여지


def summary() -> dict:
    """대시보드에 표시할 이력 요약."""
    records = _load()
    scored = [r for r in records if r.get("actual_1m") is not None]

    dir_scored = [r for r in scored if r.get("direction_correct") is not None]
    band_scored = [r for r in scored if r.get("within_band") is not None]

    return {
        "total": len(records),
        "scored": len(scored),
        "pending": len(records) - len(scored),
        "direction_hit_rate": (
            round(sum(r["direction_correct"] for r in dir_scored)
                  / len(dir_scored) * 100, 1) if dir_scored else None
        ),
        "band_coverage": (
            round(sum(r["within_band"] for r in band_scored)
                  / len(band_scored) * 100, 1) if band_scored else None
        ),
        "recent": [
            {
                "date": r["date"],
                "spot": r["spot"],
                "up_probability": r.get("up_probability"),
                "forecast": r.get("forecast_1m_median"),
                "actual": r.get("actual_1m"),
                "correct": r.get("direction_correct"),
            }
            for r in records[-12:]
        ],
        "note": (
            "예측 시점부터 30일이 지난 건만 채점합니다. "
            "90% 밴드라면 적중 구간 비율이 90% 근처여야 정상입니다."
        ),
    }
