"""배치 파이프라인.

GitHub Actions 가 하루 한 번 실행한다. 결과 snapshot.json 은 리포에 커밋되어
Streamlit 앱이 읽는다. 웹 요청 경로에서는 절대 호출하지 않는다.

    python -m app.pipeline
"""
from __future__ import annotations

import json
import logging
import shutil
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from . import analytics, config, sources

log = logging.getLogger(__name__)


def run_batch(force: bool = False) -> dict:
    started = time.perf_counter()
    now = datetime.now(ZoneInfo(config.TIMEZONE))

    if not force and now.weekday() >= 5:
        log.info("주말(%s)이므로 배치를 건너뜁니다.", now.strftime("%a"))
        return {"skipped": True}

    log.info("배치 시작: %s", now.isoformat())

    raw = sources.load_raw()
    log.info("데이터 수집 완료: %d개 시계열", len(raw))

    snapshot = analytics.build_snapshot(raw)
    elapsed = time.perf_counter() - started

    snapshot["meta"] = {
        "generated_at": now.isoformat(),
        "generated_at_display": now.strftime("%Y-%m-%d %H:%M KST"),
        "mode": "sample" if config.USE_SAMPLE else "live",
        "elapsed_sec": round(elapsed, 2),
        "forecast_months": config.FORECAST_MONTHS,
        "mc_simulations": config.MC_SIMULATIONS,
    }

    _write_atomic(snapshot)
    log.info("배치 완료 (%.2fs) -> %s", elapsed, config.SNAPSHOT_FILE)
    return snapshot


def _write_atomic(snapshot: dict) -> None:
    if config.SNAPSHOT_FILE.exists():
        shutil.copy2(config.SNAPSHOT_FILE, config.SNAPSHOT_BACKUP)
    tmp = config.SNAPSHOT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(config.SNAPSHOT_FILE)


def load_snapshot() -> dict | None:
    """스냅샷을 읽는다. 손상 시 백업본으로 폴백한다."""
    for path in (config.SNAPSHOT_FILE, config.SNAPSHOT_BACKUP):
        if not path.exists():
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.error("스냅샷 읽기 실패 (%s): %s", path.name, exc)
    return None


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    try:
        run_batch(force="--force" in sys.argv)
    except Exception:
        log.exception("배치 실패 - 기존 스냅샷을 유지합니다.")
        sys.exit(1)
