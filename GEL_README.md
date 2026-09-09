# 조지아 라리(USD/GEL) 환율 전망 대시보드

**GitHub Actions 가 하루 한 번** NBG 에서 환율을 받아 모델을 돌리고
`gel_data/snapshot.json` 을 리포에 커밋합니다. Streamlit 앱은 그 파일을 읽기만 하며,
사용자가 접속할 때는 어떤 연산도 하지 않습니다.

```
GitHub Actions (평일 UTC 14:00 = 트빌리시 18:00)     Streamlit Cloud
  NBG 증분 수집 → 모델 연산 → snapshot.json  ──커밋──▶  파일 읽기 → 화면 렌더
```

## 로컬 실행

```bash
pip install -r requirements.txt
python -m app.pipeline --force     # 스냅샷 최초 생성 (샘플 모드)
streamlit run streamlit_app.py
```

## 실데이터로 전환

NBG 환율 API 는 **인증이 필요 없습니다.** FRED 키만 있으면 됩니다.

**GitHub** — Settings → Secrets and variables → Actions
- Variables: `GEL_USE_SAMPLE` = `false`, `NBG_BACKFILL_LIMIT` = `120`
- Secrets: `FRED_API_KEY`

**Streamlit Cloud** — App settings → Secrets
```toml
FX_USE_SAMPLE = "false"
FRED_API_KEY = "발급받은키"
```

FRED 키 발급: https://fred.stlouisfed.org/docs/api/api_key.html

## NBG API 의 핵심 제약

이 API 는 **날짜를 하나씩만** 조회합니다. 3년치면 750회 호출이라 매번 받을 수
없습니다. 그래서 `gel_data/nbg_rates.csv` 에 캐시해 두고 빠진 날짜만 증분으로 채웁니다.

- 한 번의 배치에서 최대 `NBG_BACKFILL_LIMIT`(기본 120)일까지만 수집
- 과거분은 여러 번의 배치에 걸쳐 채워짐 (3년치면 약 7회)
- 화면 상단에 남은 일수가 표시됨
- **캐시 파일도 반드시 커밋해야 합니다** (워크플로에 포함되어 있음)

빨리 채우려면 `NBG_BACKFILL_LIMIT` 을 올리고 워크플로를 여러 번 수동 실행하세요.

## quantity 정규화 — 놓치면 100배 오차

NBG 응답의 `rate` 는 `quantity` 단위당 가격입니다.

| 통화 | rate | quantity | 1단위 가격 |
|---|---|---|---|
| USD | 2.6741 | 1 | 2.6741 |
| RUB | 3.05 | 100 | 0.0305 |
| AMD | 7.2691 | 1000 | 0.0072691 |

`gel_app/nbg.py` 의 `fetch_day()` 가 `rate / quantity` 로 정규화합니다.

## 구조

```
streamlit_app.py              페이지 레이아웃 (개인용 → 전문가용 → 뉴스)
gel_app/
  config.py                   설정 · 트빌리시 시간대 · NBG/FRED
  nbg.py                      NBG 환율 수집 + 증분 캐시 + 단위 정규화
  sources.py                  수집 통합 — NBG / FRED / 샘플
  analytics.py                모델 — 시나리오, STL, SARIMA, GARCH, 몬테카를로, VaR
  direction.py                1개월 방향 예측 + 확률 보정
  tracking.py                 예측 이력 기록·채점
  news.py                     조지아 매체 RSS
  charts.py                   Plotly Figure 생성 (연산 없음)
  pipeline.py                 배치 진입점
data/
  snapshot.json               커밋되는 스냅샷
  nbg_rates.csv               환율 캐시 (반드시 커밋)
```

## 그래프 목록

**개인용** — P-01 과거 추이 · P-02 시나리오 밴드(메인) · P-03 변동성 밴드 ·
P-04 EUR/GEL 병행 · P-05 1개월 방향 예측

**전문가용**
- 01 외화 유입: E-01 송금 · E-02 관광 · E-03 FDI · E-04 무역수지
- 02 통화정책: E-05 NBG 금리 · E-06 라리화 비율 · E-07 외환보유고 · E-08 개입
- 03 지역·글로벌: E-09 지역통화 동조화 · E-10 DXY · E-11 VIX · E-12 유가
- 04 계절성: E-13 STL 분해 · E-14 월별 계절 효과
- 05 확률모형: E-15 몬테카를로 · E-16 SARIMA · E-17 GARCH · E-18 백테스팅
- 06 리스크: E-19 VaR/CVaR · E-20 상관행렬 · E-21 요인분해
- 07 방향예측: E-22 성능비교 · E-23 기여변수 · E-24 확률추이 · E-25 혼동행렬 · E-26 신뢰도곡선
- 08 이력: E-27 예측 대 실제
- 09 데이터 현황

## 원화 버전과 달라진 점

| 항목 | 원화 | 라리 |
|---|---|---|
| 환율 소스 | ECOS | NBG (증분 수집 필요) |
| 거시 지표 | 금리차·무역수지·자본유출입 | 송금·관광·FDI·라리화 비율 |
| 시계열 모델 | ARIMA | **SARIMA** (관광 계절성) |
| 계절성 | 없음 | **STL 분해 추가** |
| 방향예측 특징 | 한미금리차·내재변동성 | 지역통화·계절성·무변동 지속일 |
| 상관행렬 | 코스피·CDS | RUB·TRY 등 지역통화 |
| 뉴스 | 한국 경제지 | 조지아 영문 매체 |

## 아직 샘플인 지표

송금·관광·FDI·무역수지·NBG 금리·외환보유고·라리화 비율·외환개입.

NBG 와 Geostat 이 매월 공표하는 것은 확인했으나 공개 API 를 찾지 못했습니다.
엔드포인트를 찾으면 `sources.py` 의 해당 블록을 `_try` 로 교체하면 됩니다.
화면 상단에 어떤 지표가 샘플인지 경고로 표시됩니다.

## 장애 대응

- NBG 환율 수집이 전면 실패하면 기존 캐시를 사용하고, 캐시조차 없으면
  배치를 중단해 이전 스냅샷을 유지합니다.
- 연속 20회 실패하면 수집을 중단합니다(차단 방지).
- 보조 지표는 개별 실패해도 샘플로 대체하고 진행합니다.
- `statsmodels` / `arch` / `lightgbm` 이 없으면 각각 폴백으로 동작합니다.

## 유의사항

- 라리는 NBG 개입으로 환율이 며칠씩 고정되는 구간이 있습니다. 방향 예측의
  **무변동 비중**을 반드시 함께 보세요.
- 백테스팅에 랜덤워크를 벤치마크로 포함했습니다. 이 비교를 그대로 노출하는
  편이 과신을 막고 신뢰도에도 유리합니다.
- 투자 자문이 아닙니다.

