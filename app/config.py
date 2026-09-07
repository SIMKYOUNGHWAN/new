"""애플리케이션 설정.

Streamlit Cloud 에서는 st.secrets, GitHub Actions 에서는 환경변수를 읽는다.
"""
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SNAPSHOT_FILE = DATA_DIR / "snapshot.json"
SNAPSHOT_BACKUP = DATA_DIR / "snapshot_backup.json"

DATA_DIR.mkdir(exist_ok=True)

TIMEZONE = "Asia/Seoul"


def _secret(key: str, default: str = "") -> str:
    """st.secrets 우선, 없으면 환경변수. Streamlit 밖에서도 안전하게 동작한다."""
    try:
        import streamlit as st
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.getenv(key, default)


# 샘플 모드면 API 키 없이 동작한다.
USE_SAMPLE = _secret("FX_USE_SAMPLE", "true").lower() == "true"

ECOS_API_KEY = _secret("ECOS_API_KEY")
ECOS_BASE = "https://ecos.bok.or.kr/api/StatisticSearch"

FRED_API_KEY = _secret("FRED_API_KEY")
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# ---- 모델 파라미터 ----
FORECAST_MONTHS = 12
MC_SIMULATIONS = 5000
HISTORY_MONTHS = 36

# ---- 캐시 ----
# 스냅샷이 커밋으로 갱신되므로 넉넉히 잡아도 된다(초).
CACHE_TTL = 3600
