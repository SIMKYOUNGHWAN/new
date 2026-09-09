"""애플리케이션 설정 (조지아 라리 버전).

Streamlit Cloud 에서는 st.secrets, GitHub Actions 에서는 환경변수를 읽는다.
"""
from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "gel_data"
SNAPSHOT_FILE = DATA_DIR / "snapshot.json"
SNAPSHOT_BACKUP = DATA_DIR / "snapshot_backup.json"
# NBG 는 날짜를 하나씩만 조회할 수 있어 과거분을 캐시해 두고 증분으로 채운다.
RATES_CACHE = DATA_DIR / "nbg_rates.csv"

DATA_DIR.mkdir(exist_ok=True)

# NBG 공시는 트빌리시 17시경이다. 배치도 현지 시각 기준으로 돌린다.
TIMEZONE = "Asia/Tbilisi"


def _secret(key: str, default: str = "") -> str:
    """st.secrets 우선, 없으면 환경변수. Streamlit 밖에서도 안전하게 동작한다."""
    try:
        import streamlit as st
        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.getenv(key, default)


USE_SAMPLE = _secret("GEL_USE_SAMPLE", "true").lower() == "true"

# ---- 데이터 소스 ----
# NBG 환율 API 는 인증이 필요 없다.
NBG_BASE = "https://nbg.gov.ge/gw/api/ct/monetarypolicy/currencies"

# FRED 는 DXY·유가·VIX 용 (무료 키)
FRED_API_KEY = _secret("FRED_API_KEY")
FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# ---- 수집 범위 ----
BASE_CURRENCY = "USD"                 # 주 통화쌍: USD/GEL
# 함께 보여줄 통화. NBG 는 43개 통화를 공표한다.
PEER_CURRENCIES = ["EUR", "RUB", "TRY", "AMD", "AZN", "CNY", "GBP", "JPY"]
HISTORY_YEARS = 3

# 한 번의 배치에서 새로 호출할 최대 일수. NBG 는 날짜당 1회 호출이라
# 과거분을 처음 채울 때 이 값만큼 나눠서 받는다(차단 방지).
MAX_BACKFILL_PER_RUN = int(_secret("NBG_BACKFILL_LIMIT", "120"))
NBG_REQUEST_DELAY = 0.15              # 초. 연속 호출 간격.

# ---- 모델 파라미터 ----
FORECAST_MONTHS = 12
MC_SIMULATIONS = 5000
HISTORY_MONTHS = 36

CACHE_TTL = 3600
PRICE_DIGITS = 4   # 라리는 2.67 수준이라 소수 4자리가 필요하다

