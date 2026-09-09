"""실제 예측만 별도 파일에 기록. 같은 날 최초 예측을 보존."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from . import config

FILE = config.DATA_DIR / "predictions_live.json"


def update(snapshot, px):
    records = json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else []
    today = datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d")
    for record in records:
        future = px[px.index > record["as_of"]]
        if record.get("actual") is None and len(future) >= 20:
            actual = float(future.iloc[19])
            record["actual"] = actual
            record["actual_date"] = future.index[19].strftime("%Y-%m-%d")
            record["within_band"] = record["lower"] <= actual <= record["upper"]
            record["correct"] = (actual > record["spot"]) == (record["probability"] >= 50) if record["probability"] is not None else None
    if not any(r["date"] == today for r in records):
        d = snapshot["direction"]
        records.append({"date": today, "as_of": px.index[-1].strftime("%Y-%m-%d"), "spot": float(px.iloc[-1]),
                        **snapshot["forecast20"], "probability": d.get("up_probability"),
                        "actual": None, "correct": None, "within_band": None})
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(records, ensure_ascii=False, allow_nan=False, indent=1), encoding="utf-8")
    tmp.replace(FILE)
    scored = [r for r in records if r["actual"] is not None]
    direction = [r for r in scored if r["correct"] is not None]
    return {"total": len(records), "scored": len(scored),
            "direction_hit_rate": round(sum(r["correct"] for r in direction)/len(direction)*100,1) if direction else None,
            "band_coverage": round(sum(r["within_band"] for r in scored)/len(scored)*100,1) if scored else None,
            "recent": records[-90:]}

