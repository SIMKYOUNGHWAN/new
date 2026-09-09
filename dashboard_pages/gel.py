"""조지아 라리(USD/GEL) 환율 전망 대시보드.

스냅샷은 GitHub Actions 가 하루 한 번 생성해 리포에 커밋한다.
이 앱은 그 파일을 읽기만 하며, 모델 연산을 하지 않는다.
"""
from __future__ import annotations

import streamlit as st

from gel_app import charts, config, pipeline

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


@st.cache_data(ttl=config.CACHE_TTL, show_spinner="데이터를 불러오는 중…")
def get_snapshot() -> dict | None:
    return pipeline.load_snapshot()


snap = get_snapshot()

if snap is None:
    st.error("스냅샷이 없습니다.")
    st.markdown(
        "로컬에서는 아래 명령으로 생성하세요. 배포 환경에서는 "
        "GitHub Actions 워크플로가 하루 한 번 생성합니다."
    )
    st.code("python -m gel_app.pipeline --force", language="bash")
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
    st.title("조지아 라리 환율, 시나리오로 미리 그려봅니다")
    st.markdown(
        '<p style="color:#8CA0B4;max-width:560px;margin-top:-6px;">'
        "단일 예측값 대신 강세·중립·약세 시나리오의 범위로 보여드립니다. "
        "위쪽 요약을 먼저 보고, 근거가 궁금하면 아래 심화 분석을 펼치세요.</p>",
        unsafe_allow_html=True,
    )
with head_r:
    mode_ko = "샘플" if meta["mode"] == "sample" else "실데이터"
    st.metric(f"USD/GEL ({mode_ko})",
              f"{summary['latest']:,.4f}",
              f"{summary['change_pct']:+.2f}%")

st.markdown(
    f'<div class="band">최종 갱신 <b>{meta["generated_at_display"]}</b> · '
    f'데이터 모드 {meta["mode"]} · 예측 {meta["forecast_months"]}개월 · '
    f'몬테카를로 {meta["mc_simulations"]:,}회 시뮬레이션<br>'
    "본 페이지는 투자 자문이 아니며, 모든 예측값은 상당한 불확실성을 포함합니다."
    "</div>",
    unsafe_allow_html=True,
)

_sampled = summary.get("sampled_indicators") or []
if _sampled and meta["mode"] == "live":
    st.warning(
        "다음 지표는 공개 API 가 확인되지 않아 **샘플 데이터**로 표시됩니다: "
        + ", ".join(_sampled)
    )

_left = summary.get("backfill_left", 0)
if _left > 0:
    st.info(
        f"과거 환율 {_left}일치를 아직 수집 중입니다. NBG API 는 날짜를 하나씩만 "
        "조회할 수 있어 여러 번의 배치에 걸쳐 채워집니다. 그동안 그래프의 "
        "과거 구간이 짧게 보일 수 있습니다."
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
m1.metric("강세 시나리오 (12개월)", f"{sc['bull'][-1]:,.3f}")
m2.metric("중립 시나리오 (12개월)", f"{sc['base'][-1]:,.3f}")
m3.metric("약세 시나리오 (12개월)", f"{sc['bear'][-1]:,.3f}")

c1, c2 = st.columns(2)
with c1:
    label("USD/GEL 과거 추이", "P-01", "최근 36개월 월말 종가 기준입니다.")
    show(charts.history(snap["history"]), "p01")
with c2:
    label("변동성 지표 (이동평균·밴드)", "P-03", "20일 이동평균과 ±2 표준편차 밴드입니다.")
    show(charts.bollinger(snap["bollinger"]), "p03")

label("EUR/GEL 병행 추이", "P-04",
      "조지아는 EU 교역·송금 비중이 커서 유로 대비 움직임도 함께 봐야 합니다.")
show(charts.simple_line(snap["eurgel"], charts.C["expert"]), "p04")

# ---- P-05 방향 예측 ----
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
            f'<b>{lv["median"]:,.3f}</b> · 90% 구간 '
            f'{lv["lower"]:,.3f} ~ {lv["upper"]:,.3f}</div>',
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
    if d.get("flat_note"):
        st.markdown(f'<div class="band">{d["flat_note"]}</div>',
                    unsafe_allow_html=True)

# ---------------------------------------------------------------- 전문가용
st.markdown("---")
st.subheader("전문가용 — 심화 분석")
st.markdown(
    '<p class="note">외화 유입 구조부터 확률모형·검증 결과까지 단계별로 제공합니다.</p>',
    unsafe_allow_html=True,
)

with st.expander("01 · 외화 유입 (조지아 경제의 핵심)", expanded=False):
    st.markdown(
        '<div class="band">조지아는 송금·관광·FDI 가 외화 공급의 대부분을 '
        "차지하는 소규모 개방경제입니다. 한국처럼 자본시장 흐름이 아니라 "
        "이 세 가지가 라리 환율을 좌우합니다.</div>",
        unsafe_allow_html=True,
    )
    a, b = st.columns(2)
    with a:
        label("송금 유입", "E-01", "최대 외화 공급원입니다. 단위 백만 달러.")
        show(charts.signed_bar(snap["remittance"]), "e01")
        label("FDI 유입", "E-03", "FDI 규모가 환율 안정성을 좌우합니다.")
        show(charts.signed_bar(snap["fdi"]), "e03")
    with b:
        label("관광 수입", "E-02", "여름 성수기 계절성이 매우 강합니다.")
        show(charts.signed_bar(snap["tourism"]), "e02")
        label("무역수지", "E-04", "만성 적자 구조입니다.")
        show(charts.signed_bar(snap["trade_bal"]), "e04")

with st.expander("02 · 통화정책 및 NBG", expanded=False):
    a, b = st.columns(2)
    with a:
        label("NBG 정책금리", "E-05")
        show(charts.simple_line(snap["nbg_rate"], charts.C["expert"]), "e05")
        label("외환보유고", "E-07", "단위 백만 달러.")
        show(charts.simple_line(snap["reserves"], charts.C["personal"]), "e07")
    with b:
        label("라리화 비율 (larization)", "E-06",
              "예금의 라리 전환 비율입니다. 높을수록 라리 수요가 큽니다.")
        show(charts.simple_line(snap["larization"], charts.C["personal"]), "e06")
        label("NBG 외환시장 개입", "E-08",
              "양수는 달러 매입(라리 공급), 음수는 달러 매도입니다.")
        show(charts.signed_bar(snap["intervention"]), "e08")

with st.expander("03 · 지역 통화 및 글로벌 지표", expanded=False):
    label("지역 통화 동조화", "E-09",
          "1년 전 대비 변화율입니다. 조지아는 러시아·터키·아르메니아와 "
          "교역·송금 연결이 강해 이들 통화와 함께 움직이는 경향이 있습니다.")
    if snap.get("peers"):
        show(charts.peer_currencies(snap["peers"]), "e09")
    else:
        st.info("지역 통화 데이터가 부족합니다.")

    a, b = st.columns(2)
    with a:
        label("달러인덱스(DXY)", "E-10")
        show(charts.simple_line(snap["dxy"], charts.C["expert"]), "e10")
    with b:
        label("VIX (글로벌 위험선호)", "E-11")
        show(charts.simple_line(snap["vix"], charts.C["risk"], fill=True), "e11")
    label("유가 (WTI)", "E-12", "조지아는 에너지 순수입국입니다.")
    show(charts.simple_line(snap["oil"], charts.C["personal"]), "e12")

with st.expander("04 · 계절성 분석 (라리 특유)", expanded=False):
    seas = snap.get("seasonality", {})
    if not seas.get("available"):
        st.info(f"계절성 분해를 사용할 수 없습니다: {seas.get('reason', '원인 미상')}")
    else:
        st.markdown(
            f'<div class="band">계절성 강도 <b>{seas["strength"]}</b> (0~1). '
            f'{seas["note"]}</div>', unsafe_allow_html=True)
        a, b = st.columns(2)
        with a:
            label("STL 분해 — 실제와 추세", "E-13",
                  "계절 성분을 걷어낸 추세선입니다.")
            show(charts.seasonal_decomp(seas), "e13")
        with b:
            label("월별 계절 효과", "E-14",
                  "양수면 그 달에 환율이 오르는(라리 약세) 경향입니다.")
            show(charts.month_effect(seas), "e14")

with st.expander("05 · 확률 모형 및 검증", expanded=False):
    a, b = st.columns(2)
    with a:
        label("몬테카를로 시뮬레이션 밴드", "E-15",
              f"{snap['monte_carlo']['n_sims']:,}개 경로의 5·25·50·75·95 분위입니다.")
        show(charts.monte_carlo(snap["monte_carlo"]), "e15")
        label("GARCH 기반 변동성 예측", "E-17",
              f"적합 모델: {snap['garch']['method']}")
        show(charts.garch(snap["garch"]), "e17")
    with b:
        label("SARIMA 신뢰구간", "E-16",
              f"적합 모델: {snap['arima']['method']} · 80% 구간")
        show(charts.interval(snap["arima"]), "e16")
        label("모델별 백테스팅 정확도", "E-18", snap["backtest"]["note"])
        show(charts.backtest(snap["backtest"]), "e18")

    mc = snap["monte_carlo"]
    q1, q2, q3 = st.columns(3)
    q1.metric("12개월 후 평균", f"{mc['terminal_mean']:,.3f}")
    q2.metric("하위 5% 시나리오", f"{mc['terminal_p05']:,.3f}")
    q3.metric("상위 95% 시나리오", f"{mc['terminal_p95']:,.3f}")

with st.expander("06 · 리스크·구조 분석", expanded=False):
    a, b = st.columns(2)
    with a:
        label("극단 리스크(VaR/CVaR)", "E-19", snap["tail_risk"]["note"])
        show(charts.tail_risk(snap["tail_risk"]), "e19")
    with b:
        label("환율-자산군 상관관계", "E-20")
        show(charts.heatmap(snap["correlations"]), "e20")
    label("환율 변동요인 분해", "E-21",
          "월별 변동분을 송금·관광·투자·정책 기여도로 나눈 스택 그래프입니다.")
    show(charts.decomposition(snap["decomposition"]), "e21")

with st.expander("07 · 방향 예측 모델 상세", expanded=False):
    if not d.get("available"):
        st.info(f"방향 예측을 사용할 수 없습니다: {d.get('reason', '원인 미상')}")
    else:
        st.markdown(
            '<div class="band">적중률은 <b>기준선</b>과 함께 읽어야 합니다. '
            "기준선은 다수 클래스만 계속 찍었을 때의 적중률이라, 이를 넘지 못하면 "
            "예측력이 없는 것입니다.</div>",
            unsafe_allow_html=True,
        )
        a, b = st.columns(2)
        with a:
            label("모델별 성능 비교", "E-22",
                  "적중률·균형정확도·기준선을 나란히 놓았습니다.")
            show(charts.model_compare(d["metrics"]), "e22")
            label("기여변수 Top 6", "E-23", "이번 예측에서 비중이 컸던 지표입니다.")
            show(charts.importance({"importance": dict(zip(
                d["importance"]["labels"],
                [v / 100 for v in d["importance"]["values"]]))}), "e23")
        with b:
            label("상승확률 추이", "E-24",
                  "walk-forward 검증 구간의 모델별 상승확률입니다.")
            show(charts.proba_history(d), "e24")
            best = d["metrics"][d["best_model"]]
            label("혼동행렬", "E-25",
                  f"{d['best_model']} 기준 · 대각선이 맞힌 경우입니다.")
            show(charts.confusion(best), "e25")

        rows = {"모델": [], "적중률": [], "기준선": [], "균형정확도": [],
                "우위": [], "상승재현율": [], "하락재현율": []}
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
            f"검증 방식: walk-forward. 실제 상승 비율 "
            f"{list(d['metrics'].values())[0]['actual_up_rate']}% · "
            f"무변동 구간 비중 {d.get('flat_share', '—')}%. "
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

with st.expander("08 · 예측 이력 추적", expanded=False):
    t = snap.get("tracking", {})
    if not t.get("total"):
        st.info("아직 기록된 예측이 없습니다. 배치가 실행될 때마다 쌓입니다.")
    else:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("기록된 예측", f"{t['total']}건")
        k2.metric("채점 완료", f"{t['scored']}건")
        k3.metric("방향 적중률",
                  f"{t['direction_hit_rate']}%"
                  if t.get("direction_hit_rate") is not None else "집계 전")
        k4.metric("밴드 적중률",
                  f"{t['band_coverage']}%"
                  if t.get("band_coverage") is not None else "집계 전")
        label("예측 대 실제", "E-27", "기록된 예측과 실제값을 대조합니다.")
        if t["total"] < 2:
            st.info("기록이 1건뿐이라 아직 추이를 그릴 수 없습니다.")
        else:
            show(charts.tracking_history(t), "e27")
        st.caption(t.get("note", ""))

with st.expander("09 · 데이터 현황", expanded=False):
    a, b = st.columns(2)
    with a:
        st.markdown("**최신 지표 (스냅샷 기준)**")
        st.dataframe(
            {
                "지표": ["USD/GEL", "EUR/GEL", "달러인덱스", "VIX", "유가(WTI)"],
                "값": [
                    f"{summary['latest']:,.4f}",
                    f"{snap['eurgel']['values'][-1]:,.4f}",
                    f"{snap['dxy']['values'][-1]:,.2f}",
                    f"{snap['vix']['values'][-1]:,.2f}",
                    f"${snap['oil']['values'][-1]:,.2f}",
                ],
            },
            hide_index=True, width="stretch",
        )
        st.caption(f"생성 소요 {meta['elapsed_sec']}초 · {meta['generated_at_display']}")
    with b:
        st.markdown("**모델 검증 결과**")
        bt = snap["backtest"]
        st.dataframe({"모델": bt["labels"], "RMSE": bt["rmse"]},
                     hide_index=True, width="stretch")
        st.caption(
            f"최근 {bt['test_months']}개월 walk-forward 검증. "
            "랜덤워크를 벤치마크로 포함했습니다 — 환율 단기 예측에서는 "
            "정교한 모델이 랜덤워크를 이기지 못하는 경우가 흔합니다."
        )

# ---------------------------------------------------------------- 참고 뉴스
st.markdown("---")
_news = snap.get("news", {})
st.subheader("참고 뉴스")
if not _news.get("available"):
    st.caption(f"표시할 뉴스가 없습니다. ({_news.get('reason', '수집되지 않음')})")
else:
    st.markdown(
        '<p class="note">조지아 경제·환율 관련 키워드가 제목에 포함된 최근 기사입니다. '
        '<b>기사와 환율 움직임 사이에 인과관계가 있다는 뜻은 아닙니다.</b> '
        '제목을 누르면 원문으로 이동합니다.</p>',
        unsafe_allow_html=True,
    )
    left, right = st.columns(2)
    for i, item in enumerate(_news["items"]):
        with (left if i % 2 == 0 else right):
            when = f' · {item["published"]}' if item.get("published") else ""
            st.markdown(
                f'<div style="background:#121E2C;border:1px solid #22364B;'
                f'border-radius:4px;padding:10px 13px;margin-bottom:8px;">'
                f'<a href="{item["link"]}" target="_blank" '
                f'style="color:#E8EEF4;text-decoration:none;font-size:13px;'
                f'line-height:1.5;">{item["title"]}</a>'
                f'<div style="color:#5C7188;font-size:11px;margin-top:5px;">'
                f'{item["source"]}{when}</div></div>',
                unsafe_allow_html=True,
            )
    st.caption(
        f"수집 시각 {_news.get('collected_at', '—')} · "
        f"출처 {', '.join(_news.get('sources_ok', [])) or '없음'}"
        + (f" · 실패 {', '.join(_news['sources_failed'])}"
           if _news.get("sources_failed") else "")
    )

st.markdown("---")
with st.expander("방법론 · 가정과 한계", expanded=False):
    _method = config.BASE_DIR / "GEL_METHODOLOGY.md"
    if _method.exists():
        st.markdown(_method.read_text(encoding="utf-8"))
    else:
        st.info("GEL_METHODOLOGY.md 를 찾을 수 없습니다.")

st.caption(
    "데이터 출처: 조지아 국립은행(NBG) 환율 API, FRED. "
    "송금·관광·FDI·라리화 비율 등 조지아 거시지표는 공개 API 가 확인되지 않아 "
    "현재 샘플 데이터입니다. 모델의 가정과 한계는 위 방법론을 참고하세요. "
    "본 페이지는 투자 자문이 아닙니다."
)

