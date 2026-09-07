"""원/달러 환율 전망 대시보드.

스냅샷은 GitHub Actions 가 하루 한 번 생성해 리포에 커밋한다.
이 앱은 그 파일을 읽기만 하며, 모델 연산을 하지 않는다.
"""
from __future__ import annotations

import streamlit as st

from app import charts, config, pipeline

st.set_page_config(
    page_title="원/달러 환율 전망",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
  .stApp { background:#0B1420; }
  section.main > div { padding-top:1.2rem; }
  h1,h2,h3 { color:#E8EEF4 !important; letter-spacing:-0.01em; }
  .stPlotlyChart { background:#121E2C; border:1px solid #22364B;
                   border-radius:4px; padding:6px 10px 2px; }
  div[data-testid="stMetric"] { background:#121E2C; border:1px solid #22364B;
                                border-radius:4px; padding:12px 16px; }
  div[data-testid="stMetricValue"] { font-size:26px; }
  .chart-label { font-size:13px; font-weight:600; color:#E8EEF4;
                 margin:14px 0 4px; display:flex; justify-content:space-between; }
  .chart-label span.code { color:#5C7188; font-weight:400; font-size:11px; }
  .note { font-size:12px; color:#8CA0B4; margin:2px 0 10px; }
  .band { border-left:2px solid #E3A94D; background:#121E2C;
          padding:9px 14px; font-size:12px; color:#8CA0B4; margin-bottom:6px; }
  hr { border-color:#22364B; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------- 데이터
@st.cache_data(ttl=config.CACHE_TTL, show_spinner="데이터를 불러오는 중…")
def get_snapshot() -> dict | None:
    """커밋된 스냅샷을 읽어 캐시한다. 요청마다 연산하지 않는다."""
    return pipeline.load_snapshot()


snap = get_snapshot()

if snap is None:
    st.error("스냅샷이 없습니다.")
    st.markdown(
        "로컬에서는 아래 명령으로 생성하세요. 배포 환경에서는 "
        "GitHub Actions 워크플로가 하루 한 번 생성합니다."
    )
    st.code("python -m app.pipeline --force", language="bash")
    st.stop()

meta, summary = snap["meta"], snap["summary"]


def label(title: str, code: str, note: str = "") -> None:
    st.markdown(
        f'<div class="chart-label">{title}<span class="code">{code}</span></div>',
        unsafe_allow_html=True,
    )
    if note:
        st.markdown(f'<div class="note">{note}</div>', unsafe_allow_html=True)


CFG = {"displayModeBar": False}


def show(fig, key: str) -> None:
    st.plotly_chart(fig, width="stretch", config=CFG, key=key)


# ---------------------------------------------------------------- 헤더
head_l, head_r = st.columns([3, 1.1])
with head_l:
    st.title("원/달러 환율, 시나리오로 미리 그려봅니다")
    st.markdown(
        '<p style="color:#8CA0B4;max-width:560px;margin-top:-6px;">'
        "단일 예측값 대신 강세·중립·약세 시나리오의 범위로 보여드립니다. "
        "위쪽 요약을 먼저 보고, 근거가 궁금하면 아래 심화 분석을 펼치세요.</p>",
        unsafe_allow_html=True,
    )
with head_r:
    mode_ko = "샘플" if meta["mode"] == "sample" else "실데이터"
    st.metric(f"현재 환율 ({mode_ko})",
              f"{summary['latest']:,.2f}",
              f"{summary['change_pct']:+.2f}%")

st.markdown(
    f'<div class="band">최종 갱신 <b>{meta["generated_at_display"]}</b> · '
    f'데이터 모드 {meta["mode"]} · 예측 {meta["forecast_months"]}개월 · '
    f'몬테카를로 {meta["mc_simulations"]:,}회 시뮬레이션<br>'
    "본 페이지는 투자 자문이 아니며, 모든 예측값은 상당한 불확실성을 포함합니다."
    "</div>",
    unsafe_allow_html=True,
)

# 일부 지표만 실패했을 때 조용히 샘플이 섞이면 오해를 부른다. 명시한다.
_sampled = summary.get("sampled_indicators") or []
if _sampled and meta["mode"] == "live":
    st.warning(
        "다음 지표는 이번 갱신에서 조회에 실패해 **샘플 데이터**로 표시됩니다: "
        + ", ".join(_sampled)
    )

# ---------------------------------------------------------------- 개인용
st.markdown("---")
st.subheader("개인용 — 핵심 요약")
st.markdown('<p class="note">복잡한 지표 없이, 지금 흐름과 앞으로의 범위만 빠르게 확인하세요.</p>',
            unsafe_allow_html=True)

sc = snap["scenario"]
label("시나리오별 환율 전망 밴드", "P-02 · 메인",
      "과거는 실선, 향후 12개월은 강세·중립·약세 3개 경로를 점선으로 표시했습니다.")
show(charts.scenario(snap["history"], sc), "p02")

m1, m2, m3 = st.columns(3)
m1.metric("강세 시나리오 (12개월)", f"{sc['bull'][-1]:,.0f}원")
m2.metric("중립 시나리오 (12개월)", f"{sc['base'][-1]:,.0f}원")
m3.metric("약세 시나리오 (12개월)", f"{sc['bear'][-1]:,.0f}원")

c1, c2 = st.columns(2)
with c1:
    label("원/달러 환율 과거 추이", "P-01", "최근 36개월 월말 종가 기준입니다.")
    show(charts.history(snap["history"]), "p01")
with c2:
    label("변동성 지표 (이동평균·밴드)", "P-03", "20일 이동평균과 ±2 표준편차 밴드입니다.")
    show(charts.bollinger(snap["bollinger"]), "p03")

# ---- P-05 1개월 방향 예측 ----
d = snap.get("direction", {})
label("1개월 방향 예측", "P-05",
      "향후 약 1개월 뒤 환율이 오를지 내릴지의 확률입니다.")

if not d.get("available"):
    st.info(f"방향 예측을 사용할 수 없습니다: {d.get('reason', '원인 미상')}")
else:
    best = d["metrics"][d["best_model"]]
    p1, p2, p3 = st.columns(3)
    p1.metric("상승 확률", f"{d['up_probability']}%")
    p2.metric("하락 확률", f"{d['down_probability']}%")
    p3.metric("적중률 (검증)", f"{best['accuracy']}%",
              f"기준선 대비 {best['edge']:+.1f}%p")

    if lv := d.get("level_1m"):
        st.markdown(
            f'<div class="note">1개월 후 수치 전망 — 중앙값 '
            f'<b>{lv["median"]:,.0f}원</b> · 90% 구간 '
            f'{lv["lower"]:,.0f} ~ {lv["upper"]:,.0f}원</div>',
            unsafe_allow_html=True,
        )

    cal_line = ""
    if d.get("calibrated"):
        cal_line = (
            f'확률 보정 적용 (Platt scaling) · 보정 전 원값 '
            f'{d["raw_up_probability"]}% → 보정 후 {d["up_probability"]}%<br>'
        )

    st.markdown(
        f'<div class="band">사용 모델 <b>{d["best_model"]}</b> · '
        f'검증 표본 {best["n_samples"]}건 · 균형 정확도 {best["balanced_accuracy"]}%<br>'
        f'{cal_line}{d["caveat"]}</div>',
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------- 전문가용
st.markdown("---")
st.subheader("전문가용 — 심화 분석")
st.markdown(
    '<p class="note">근거가 되는 거시지표부터 확률모형·검증 결과까지 단계별로 제공합니다.</p>',
    unsafe_allow_html=True,
)

with st.expander("01 · 거시경제 지표", expanded=False):
    a, b = st.columns(2)
    with a:
        label("한미 기준금리 차이", "E-01")
        show(charts.signed_bar(snap["rate_gap"]), "e01")
        label("경상수지·무역수지", "E-03")
        show(charts.signed_bar(snap["trade"]), "e03")
    with b:
        label("달러인덱스(DXY) 추이", "E-02")
        show(charts.simple_line(snap["dxy"], charts.C["expert"]), "e02")
        label("외국인 자본 순유출입", "E-04")
        show(charts.signed_bar(snap["flows"]), "e04")

with st.expander("02 · 심화 모델링", expanded=False):
    a, b = st.columns(2)
    with a:
        label("실현변동성 (20일·연율화)", "E-05",
              "옵션 내재변동성은 유료 데이터라 환율의 실현변동성으로 대체했습니다.")
        show(charts.simple_line(snap["implied_vol"], charts.C["risk"], fill=True), "e05")
        label("신용 스프레드 (회사채AA− − 국고채3년)", "E-07",
              "CDS 는 유료 데이터라 국내 신용 스프레드로 대체했습니다. 단위 bp.")
        show(charts.simple_line(snap["cds"], charts.C["expert"]), "e07")
        label("몬테카를로 시뮬레이션 밴드", "E-09",
              f"{snap['monte_carlo']['n_sims']:,}개 경로의 5·25·50·75·95 분위입니다.")
        show(charts.monte_carlo(snap["monte_carlo"]), "e09")
    with b:
        label("시장심리 지수 (VIX 기반)", "E-06",
              "VIX 를 표준화해 부호를 뒤집었습니다. 음수일수록 위험회피 심리입니다.")
        show(charts.signed_bar(snap["sentiment"]), "e06")
        label("GARCH 기반 변동성 예측", "E-08",
              f"적합 모델: {snap['garch']['method']}")
        show(charts.garch(snap["garch"]), "e08")
        label("모델별 백테스팅 정확도", "E-10", snap["backtest"]["note"])
        show(charts.backtest(snap["backtest"]), "e10")

    mc = snap["monte_carlo"]
    q1, q2, q3 = st.columns(3)
    q1.metric("12개월 후 평균", f"{mc['terminal_mean']:,.0f}원")
    q2.metric("하위 5% 시나리오", f"{mc['terminal_p05']:,.0f}원")
    q3.metric("상위 95% 시나리오", f"{mc['terminal_p95']:,.0f}원")

    label("이벤트 기반 조건부 시나리오 타임라인", "E-11",
          "FOMC·한국은행 금통위 등 주요 이벤트 시점을 환율 흐름과 함께 표시합니다.")
    show(charts.events(snap["history"]), "e11")

with st.expander("03 · 리스크·구조 분석", expanded=False):
    a, b = st.columns(2)
    with a:
        label("VAR 충격반응 함수", "E-12", "기준 시점 대비 누적 반응 경로입니다.")
        show(charts.impulse(snap["arima"]), "e12")
        label("머신러닝 특징중요도", "E-14",
              "단위가 다른 요인을 비교하기 위해 표준화 계수 기준 상대 기여도로 계산했습니다.")
        show(charts.importance(snap["decomposition"]), "e14")
        label("한미 금리차 (일별)", "E-16")
        show(charts.simple_line(snap["carry"], charts.C["personal"]), "e16")
    with b:
        label("베이지안(BSTS) 신뢰구간", "E-13",
              f"적합 모델: {snap['arima']['method']} · 80% 구간")
        show(charts.interval(snap["arima"]), "e13")
        label("환율-자산군 상관관계", "E-15")
        show(charts.heatmap(snap["correlations"]), "e15")
        label("극단 리스크(VaR/CVaR)", "E-17", snap["tail_risk"]["note"])
        show(charts.tail_risk(snap["tail_risk"]), "e17")

    label("환율 변동요인 분해", "E-18",
          "월별 변동분을 회귀 기여도로 나눈 스택 그래프입니다.")
    show(charts.decomposition(snap["decomposition"]), "e18")

with st.expander("04 · 방향 예측 모델 상세", expanded=False):
    if not d.get("available"):
        st.info(f"방향 예측을 사용할 수 없습니다: {d.get('reason', '원인 미상')}")
    else:
        st.markdown(
            '<div class="band">적중률은 <b>기준선</b>과 함께 읽어야 합니다. '
            "기준선은 다수 클래스만 계속 찍었을 때의 적중률이라, 이를 넘지 못하면 "
            "예측력이 없는 것입니다. 상승·하락 표본이 불균형할 때는 균형 정확도가 "
            "더 정직한 지표입니다.</div>",
            unsafe_allow_html=True,
        )
        a, b = st.columns(2)
        with a:
            label("모델별 성능 비교", "E-21",
                  "적중률·균형정확도·기준선을 나란히 놓았습니다.")
            show(charts.model_compare(d["metrics"]), "e21")
            label("기여변수 Top 6", "E-22",
                  "이번 예측에서 비중이 컸던 지표입니다.")
            show(charts.importance({"importance": dict(zip(
                d["importance"]["labels"],
                [v / 100 for v in d["importance"]["values"]]))}), "e22")
        with b:
            label("상승확률 추이", "E-23",
                  "walk-forward 검증 구간의 모델별 상승확률입니다.")
            show(charts.proba_history(d), "e23")
            best = d["metrics"][d["best_model"]]
            label("혼동행렬", "E-24",
                  f"{d['best_model']} 기준 · 대각선이 맞힌 경우입니다.")
            show(charts.confusion(best), "e24")

        rows = {
            "모델": [], "적중률": [], "기준선": [],
            "균형정확도": [], "우위": [], "상승재현율": [], "하락재현율": [],
        }
        for name, m in d["metrics"].items():
            rows["모델"].append(name)
            rows["적중률"].append(f"{m['accuracy']}%")
            rows["기준선"].append(f"{m['baseline']}%")
            rows["균형정확도"].append(f"{m['balanced_accuracy']}%")
            rows["우위"].append(f"{m['edge']:+.1f}%p")
            rows["상승재현율"].append(f"{m['recall_up']}%")
            rows["하락재현율"].append(f"{m['recall_down']}%")
        st.dataframe(rows, hide_index=True, width="stretch")
        st.caption(
            f"검증 방식: walk-forward (과거로 학습 → 미래 예측 → 이동). "
            f"실제 상승 비율 {list(d['metrics'].values())[0]['actual_up_rate']}%. "
            "우위가 음수면 그 모델은 기준선보다 못합니다."
        )

        cal = d.get("calibration", {})
        if cal.get("before", {}).get("predicted"):
            label("확률 보정 (신뢰도 곡선)", "E-26",
                  "예측 확률 구간별로 실제 상승 비율을 센 것입니다. "
                  "점선(대각선)에 가까울수록 확률을 그대로 믿을 수 있습니다.")
            g1, g2 = st.columns([2, 1])
            with g1:
                show(charts.reliability_curve(cal), "e26")
            with g2:
                b_err = cal["before"].get("calibration_error")
                a_err = cal["after"].get("calibration_error")
                st.metric("보정 전 오차", f"{b_err}%p" if b_err is not None else "—")
                st.metric("보정 후 오차", f"{a_err}%p" if a_err is not None else "—",
                          f"{a_err - b_err:+.1f}%p"
                          if (a_err is not None and b_err is not None) else None,
                          delta_color="inverse")
                st.caption(f"방식: {cal.get('method', '미적용')}")
            st.caption(cal.get("note", ""))

with st.expander("05 · 예측 이력 추적", expanded=False):
    t = snap.get("tracking", {})
    if not t.get("total"):
        st.info("아직 기록된 예측이 없습니다. 배치가 실행될 때마다 쌓입니다.")
    else:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("기록된 예측", f"{t['total']}건")
        k2.metric("채점 완료", f"{t['scored']}건")
        k3.metric("방향 적중률",
                  f"{t['direction_hit_rate']}%" if t.get("direction_hit_rate")
                  is not None else "집계 전")
        k4.metric("밴드 적중률",
                  f"{t['band_coverage']}%" if t.get("band_coverage")
                  is not None else "집계 전")

        label("예측 대 실제", "E-25", "기록된 예측과 실제값을 대조합니다.")
        if t["total"] < 2:
            st.info(
                "기록이 1건뿐이라 아직 추이를 그릴 수 없습니다. "
                "배치가 며칠 더 실행되면 그래프가 나타납니다."
            )
        else:
            show(charts.tracking_history(t), "e25")
        st.caption(t.get("note", ""))

with st.expander("06 · 데이터 현황 및 모델 추적", expanded=False):
    a, b = st.columns(2)
    with a:
        st.markdown("**최신 지표 (스냅샷 기준)**")
        st.dataframe(
            {
                "지표": ["USD/KRW", "달러인덱스", "한미 금리차", "실현변동성", "신용 스프레드"],
                "값": [
                    f"{summary['latest']:,.2f}",
                    f"{snap['dxy']['values'][-1]:,.2f}",
                    f"{snap['rate_gap']['values'][-1]:+.2f}%",
                    f"{snap['implied_vol']['values'][-1]:.2f}%",
                    f"{snap['cds']['values'][-1]:.0f}bp",
                ],
            },
            hide_index=True, width="stretch",
        )
        st.caption(f"생성 소요 {meta['elapsed_sec']}초 · {meta['generated_at_display']}")
    with b:
        st.markdown("**모델 검증 결과**")
        bt = snap["backtest"]
        st.dataframe(
            {"모델": bt["labels"], "RMSE": bt["rmse"]},
            hide_index=True, width="stretch",
        )
        st.caption(
            f"최근 {bt['test_months']}개월 walk-forward 검증. "
            "랜덤워크를 벤치마크로 포함했습니다 — 환율 단기 예측에서는 "
            "정교한 모델이 랜덤워크를 이기지 못하는 경우가 흔합니다."
        )

st.markdown("---")
with st.expander("방법론 · 가정과 한계", expanded=False):
    _method = config.BASE_DIR / "METHODOLOGY.md"
    if _method.exists():
        st.markdown(_method.read_text(encoding="utf-8"))
    else:
        st.info("METHODOLOGY.md 를 찾을 수 없습니다.")

st.caption(
    "데이터 출처: 한국은행 경제통계시스템(ECOS), FRED. "
    "옵션 내재변동성·CDS·뉴스 감성지수는 유료 또는 미공개 데이터라 각각 "
    "실현변동성·신용 스프레드·VIX 기반 지표로 대체했습니다. "
    "모델의 가정과 한계는 위 방법론을 참고하세요. 본 페이지는 투자 자문이 아닙니다."
)
