# 원/달러 환율 전망 대시보드 (Streamlit)

**GitHub Actions 가 하루 한 번** 데이터를 수집하고 모델을 돌려 `data/snapshot.json` 을
리포에 커밋합니다. Streamlit 앱은 그 파일을 읽기만 하며, 사용자가 접속할 때는
어떤 연산도 하지 않습니다.

```
GitHub Actions (평일 09:00 KST)          Streamlit Cloud
  수집 → 모델 연산 → snapshot.json  ──커밋──▶  파일 읽기 → 화면 렌더
        (수 초)                                 (수십 ms)
```

## 왜 이 구조인가

Streamlit Community Cloud 는 컨테이너 파일시스템이 **휘발성**입니다. 앱 안에서
APScheduler 로 스냅샷을 만들어 저장해도 재시작하면 사라지고, 슬립에서 깨어날 때
다시 몇 초씩 연산하게 됩니다. 스냅샷을 리포에 커밋해 두면 배포본에 항상 포함되므로
재시작과 무관하게 즉시 뜹니다. 덤으로 갱신 이력이 git log 에 남습니다.

## 로컬 실행

```bash
pip install -r requirements.txt
python -m app.pipeline --force     # 스냅샷 최초 생성
streamlit run streamlit_app.py
```

## GitHub 배포

1. 리포를 만들고 푸시합니다. **`data/snapshot.json` 을 반드시 커밋하세요.**
   `.gitignore` 에 넣으면 첫 배포 때 화면이 비어 있습니다.

   ```bash
   git init && git add -A && git commit -m "init"
   git remote add origin https://github.com/<계정>/<리포>.git
   git push -u origin main
   ```

2. Settings → Actions → General → Workflow permissions 에서
   **Read and write permissions** 를 켭니다. 봇이 스냅샷을 커밋하려면 필요합니다.

3. share.streamlit.io 에서 리포를 연결하고 메인 파일을 `streamlit_app.py` 로 지정합니다.

4. Actions 탭에서 `일간 스냅샷 갱신` 워크플로를 한 번 수동 실행(`Run workflow`)해
   정상 동작을 확인합니다.

## 실데이터로 전환

기본은 샘플 모드라 API 키 없이 동작합니다.

**GitHub** — Settings → Secrets and variables → Actions
- Variables: `FX_USE_SAMPLE` = `false`
- Secrets: `ECOS_API_KEY`, `FRED_API_KEY`

**Streamlit Cloud** — App settings → Secrets
```toml
FX_USE_SAMPLE = "false"
ECOS_API_KEY = "발급받은키"
FRED_API_KEY = "발급받은키"
```

키 발급: [ECOS](https://ecos.bok.or.kr) · [FRED](https://fred.stlouisfed.org/docs/api/api_key.html)

`sources.py` 의 `load_raw()` 가 환율(ECOS 731Y001), 한국 기준금리(722Y001),
미국 금리·달러인덱스·유가(FRED)를 조회합니다. 경상수지·자본유출입·CDS·내재변동성·
감성지수는 아직 샘플로 채워지므로, 통계표 코드를 확인해 순차적으로 교체하면 됩니다.

## 구조

```
streamlit_app.py              페이지 레이아웃 (개인용 → 전문가용)
app/
  config.py                   설정 · st.secrets/환경변수 자동 인식
  sources.py                  수집 — ECOS / FRED / 샘플
  analytics.py                모델 — 시나리오, ARIMA, GARCH, 몬테카를로, VaR, 요인분해, 백테스팅
  charts.py                   Plotly Figure 생성 (연산 없음)
  pipeline.py                 배치 진입점
data/snapshot.json            커밋되는 스냅샷
.github/workflows/daily-snapshot.yml
```

## 그래프 목록

**개인용** — P-01 과거 추이 · P-02 시나리오 밴드(메인) · P-03 변동성 밴드

**전문가용**
- 01 거시: E-01 한미 금리차 · E-02 DXY · E-03 무역수지 · E-04 자본유출입
- 02 모델링: E-05 내재변동성 · E-06 감성지수 · E-07 CDS · E-08 GARCH ·
  E-09 몬테카를로 · E-10 백테스팅 · E-11 이벤트 타임라인
- 03 리스크: E-12 충격반응 · E-13 신뢰구간 · E-14 특징중요도 · E-15 상관행렬 ·
  E-16 캐리트레이드 · E-17 VaR/CVaR · E-18 요인분해
- 04 추적: E-19 최신 지표 · E-20 모델 검증 결과

## 장애 대응

- 배치가 실패하면 워크플로가 종료 코드 1 로 끝나고 **커밋이 일어나지 않습니다.**
  직전 스냅샷이 그대로 남아 대시보드는 계속 동작합니다.
- 스냅샷 쓰기는 임시파일 → `replace()` 원자적 교체이며, 손상 시
  `snapshot_backup.json` 으로 자동 폴백합니다.
- 주말은 시장 데이터가 없어 스케줄 실행 시 건너뜁니다(`--force` 로 무시 가능).
- `statsmodels` / `arch` 가 없으면 각각 랜덤워크·EWMA 폴백으로 동작합니다.
- Actions 무료 한도에서 이 워크플로는 실행당 1~2분이라 여유롭습니다.

## 유의사항

- 현재 모든 수치는 **샘플**입니다. 공개 전 데이터 출처, 갱신 주기, 모델 가정을
  방법론 문서로 정리하세요. 전문가는 그래프 개수보다 이 문서를 먼저 봅니다.
- "최종 갱신" 표시는 신뢰도에 직결되므로 지우지 마세요.
- 백테스팅에 **랜덤워크를 벤치마크로** 포함했습니다. 환율 단기 예측에서는
  정교한 모델이 랜덤워크를 이기지 못하는 경우가 흔한데, 이 비교를 그대로 노출하는
  편이 과신을 막고 신뢰도에도 유리합니다.
- 투자 자문이 아닙니다.
