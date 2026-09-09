"""실제 조지아 라리 환율과 전문가 분석."""
import html
import pandas as pd
import streamlit as st
from gel_app import charts, live_pipeline

snap = live_pipeline.load_snapshot()
st.title("조지아 라리화")
if not snap:
    st.error("검증된 실제 스냅샷이 없습니다. 라리화 일간 갱신 배치를 확인해 주세요.")
    st.stop()
summary = snap["summary"]
st.info("실제 데이터 · NBG 공식 고시환율 · 1 USD당 GEL 금액")
st.markdown("[환율 원본: 조지아 국립은행(NBG)](https://nbg.gov.ge/en/monetary-policy/currency)")
st.caption(f"공시 기준일 {summary['as_of']} · 수집 {snap['meta']['generated_at_display']} · 실제 관측 {snap['observations']}개")
age = (pd.Timestamp.now().normalize() - pd.Timestamp(summary["as_of"])).days
if age > 4:
    st.warning(f"최신 환율 공시가 {age}일 전입니다. 갱신 상태를 확인해 주세요.")
if snap["meta"].get("failed_dates"):
    st.warning(f"일부 날짜 수집 실패: {len(snap['meta']['failed_dates'])}일. 기존 실제 공시값을 유지하며 누락값은 만들지 않습니다.")
st.caption("환율 상승은 라리 약세, 하락은 라리 강세입니다. 예측값은 실제 환율로 계산한 모델 결과입니다.")
counter = 0


def show(fig, price=False):
    global counter
    counter += 1
    if price:
        fig.update_yaxes(tickformat=".4f", title_text="GEL / 1 USD")
    st.plotly_chart(fig, width="stretch", key=f"gel-live-{counter}", config={"displayModeBar": False})


def context_chart(key, name):
    item = snap["context"].get(key, {})
    st.markdown(f"**{name}**")
    if not item.get("available"):
        st.info("데이터 미연결 · " + item.get("reason", "수집되지 않음"))
        if item.get("url"):
            st.link_button("공식 통계 확인", item["url"])
        return
    st.metric(item["name"], f"{item['values'][-1]:,.3f} {item['unit']}")
    fig = charts.simple_line(item, charts.C["expert"])
    fig.update_yaxes(title_text=item["unit"])
    show(fig)
    st.caption(f"{item['frequency']} 자료 · 최신 관측 {item['labels'][-1]} · {item['source']}")
    st.link_button(f"{name} 원본", item["url"], key=f"source-{key}")
    if item["frequency"] == "연간":
        st.caption("연간 공표 통계이며 월간 값으로 보간하지 않습니다.")
        if int(item["labels"][-1]) < pd.Timestamp.now().year - 2:
            st.warning("최근 연도 공표가 없어 과거 참고 자료만 표시합니다.")
    if item.get("refresh_failed"):
        st.warning("이번 수집에 실패해 이전에 확인한 실제 자료를 표시합니다.")


personal, expert = st.tabs(["개인용 — 핵심 요약", "전문가용 — 심화 분석"])
with personal:
    st.header("개인용 — 핵심 요약")
    a,b,c = st.columns(3)
    a.metric("USD/GEL", f"{summary['latest']:.4f}", f"{summary['change_pct']:+.3f}%")
    b.metric("EUR/GEL", f"{snap['eurgel']['values'][-1]:.4f}")
    c.metric("다음 20개 관측 후 중앙값", f"{snap['forecast20']['median']:.4f}")
    show(charts.simple_line(snap["daily"], charts.C["personal"]), True)
    st.subheader("유로 대비 라리 환율")
    eur_fig = charts.simple_line(snap["eurgel"], charts.C["expert"])
    eur_fig.update_yaxes(title_text="GEL / 1 EUR", tickformat=".4f")
    show(eur_fig)
    st.subheader("12개월 시나리오")
    history = snap["history"]
    keep = [i for i,d in enumerate(history["labels"]) if d <= snap["model_as_of"][:7]]
    hist = {k: [v[i] for i in keep] for k,v in history.items()}
    show(charts.scenario(hist, snap["scenario"]), True)
    st.caption(f"월간 학습 마지막 관측 {snap['model_as_of']} · 강세·중립·약세는 변동성 기반 가정 경로입니다.")
    show(charts.bollinger(snap["bollinger"]), True)
    st.caption("20관측 이동평균 ± 2표준편차 밴드")
    st.subheader("단기 방향과 환전 계산")
    d = snap["direction"]
    if d["available"]:
        st.metric("다음 20개 관측 후 상승 확률", f"{d['up_probability']:.1f}%")
        st.caption(f"실제 가격만 사용한 로지스틱 모델 · 검증 {d['n']}건으로 표본이 적어 해석에 주의가 필요합니다.")
    else:
        st.info(d["reason"])
    f = snap["forecast20"]
    st.caption(f"20개 관측 후 시뮬레이션 90% 범위: {f['lower']:.4f} ~ {f['upper']:.4f} GEL")
    amount = st.number_input("환전할 달러 (USD)", min_value=0.0, value=1000.0, step=100.0)
    st.metric("환산 라리", f"{amount * summary['latest']:,.2f} GEL")
    st.caption("은행 수수료·스프레드는 포함하지 않습니다.")

with expert:
    st.header("전문가용 — 심화 분석")
    with st.expander("01 · 외화 유입과 실물경제"):
        st.caption("공식 연간 통계로 경제 구조를 확인합니다. 월간 환율 모델의 입력으로 사용하지 않습니다.")
        for key, name in (("remittance","송금 유입"),("tourism","관광 수입"),("fdi","FDI 유입"),("trade_bal","무역수지"),("gdp","경제성장")):
            context_chart(key,name)
    with st.expander("02 · 통화정책 및 NBG"):
        for key,name in (("nbg_rate","정책금리"),("inflation","물가"),("reserves","외환보유고"),("larization","라리화 비율"),("intervention","외환시장 개입")):
            context_chart(key,name)
    with st.expander("03 · 지역 통화와 글로벌 지표"):
        show(charts.peer_currencies(snap["peers"]))
        st.caption("각 통화의 GEL 가격을 첫 관측값 대비 변화율(%)로 비교합니다.")
        for key,name in (("dxy","미국 광의 무역가중 달러지수"),("vix","VIX"),("oil","WTI 유가")):
            context_chart(key,name)
        st.caption("광의 무역가중 달러지수(DTWEXBGS)는 ICE DXY와 다른 지수입니다.")
    with st.expander("04 · 추세와 계절성"):
        seas = snap["seasonality"]
        if seas.get("available"):
            show(charts.seasonal_decomp(seas), True)
            show(charts.month_effect(seas))
            st.caption("STL 12개월 주기 분해 · 과거 반복 패턴이며 미래 반복을 보장하지 않습니다.")
        else:
            st.info(seas.get("reason", "계절성 자료 부족"))
    with st.expander("05 · 확률모형 및 검증"):
        st.subheader("ARIMA 예측과 80% 구간")
        show(charts.interval(snap["arima"]), True)
        st.caption(snap["arima"]["method"])
        st.subheader("몬테카를로 5·25·50·75·95 분위")
        show(charts.monte_carlo(snap["monte_carlo"]), True)
        st.caption("월간 로그수익률의 정규분포 가정 · 5,000개 경로")
        vol = snap["garch"]
        fig = charts.garch(vol)
        last = pd.Timestamp(vol["history_labels"][-1])
        fig.data[1].x = [last.strftime("%Y-%m-%d")] + pd.bdate_range(last + pd.offsets.BDay(), periods=len(vol["forecast"])).strftime("%Y-%m-%d").tolist()
        fig.update_yaxes(title_text="연율화 변동성 (%)")
        show(fig)
        st.caption(f"{vol['method']} · 연 252관측 가정")
        bt = snap["backtest"]
        st.dataframe(pd.DataFrame({"모델":bt["labels"],"RMSE (GEL)":bt["rmse"]}), hide_index=True,
                     column_config={"RMSE (GEL)":st.column_config.NumberColumn(format="%.6f")})
        st.caption(f"{bt['method']} · {bt['test_months']}개월 검증. 매 시점 이전 자료로만 다음 월을 예측합니다.")
    with st.expander("06 · 리스크와 구조 분석"):
        r = snap["risk"]
        a,b,c = st.columns(3)
        a.metric("20관측 상승 VaR 95%", f"{r['var95_pct']:.3f}%")
        b.metric("20관측 상승 CVaR 95%", f"{r['cvar95_pct']:.3f}%")
        c.metric("기간 최대 낙폭", f"{r['max_drawdown_pct']:.3f}%")
        st.caption(f"과거 20관측 수익률 {r['sample_size']}개(중첩 구간)의 경험적 분위와 꼬리 평균입니다. 달러 매입자의 GEL 비용 증가 방향을 봅니다.")
        if snap["correlations"]["assets"]:
            show(charts.heatmap(snap["correlations"]))
            st.caption("일별 로그수익률 상관관계 · 쌍별 공통 관측 최소 60개 · 인과관계가 아닙니다.")
        show(charts.decomposition(snap["decomposition"]))
        st.caption("월별 로그변동(%) 항등식: USD/GEL = EUR/GEL ÷ EUR/USD. 송금·정책의 인과 기여도 추정이 아닙니다.")
    with st.expander("07 · 방향모델 상세와 신뢰도"):
        if not d["available"]:
            st.info(d["reason"])
        else:
            st.dataframe(pd.DataFrame([{"모델":"로지스틱", "정확도(%)":d["accuracy"],"균형정확도(%)":d["balanced_accuracy"],"기준선(%)":d["baseline"],"Brier 점수":d["brier"],"검증 건수":d["n"]}]), hide_index=True)
            st.caption("확장 학습·20관측 간격 검증. 각 학습과 검증 사이에 예측기간 20관측을 제외해 미래 정보 누출을 막습니다. 기준선은 각 학습구간의 다수 방향입니다.")
            show(charts.simple_line({"labels":d["labels"],"values":d["probabilities"]}, charts.C["expert"]))
            st.caption("검증 시점의 상승확률(%)")
            st.dataframe(pd.DataFrame(d["confusion"],index=["실제 하락/보합","실제 상승"],columns=["예측 하락/보합","예측 상승"]))
            st.dataframe(pd.DataFrame({"변수":list(d["coefficients"]), "표준화 계수":list(d["coefficients"].values())}),hide_index=True)
            st.caption("계수는 모델 내부의 방향·크기이며 인과 기여도나 중요도 백분율이 아닙니다.")
            st.dataframe(pd.DataFrame(d["reliability"]),hide_index=True)
            st.caption("확률 구간별 실제 상승 비율입니다. 표본이 작아 별도의 확률 보정은 적용하지 않았습니다.")
    with st.expander("08 · 실제 예측 이력 추적"):
        t = snap["tracking"]
        a,b,c,e = st.columns(4)
        a.metric("기록된 예측",f"{t['total']}건")
        b.metric("채점 완료",f"{t['scored']}건")
        c.metric("방향 적중률",f"{t['direction_hit_rate']}%" if t["direction_hit_rate"] is not None else "집계 전")
        e.metric("밴드 적중률",f"{t['band_coverage']}%" if t["band_coverage"] is not None else "집계 전")
        st.dataframe(pd.DataFrame(t["recent"]).rename(columns={
            "date":"예측 기록일","as_of":"환율 기준일","spot":"기준 환율","lower":"하단 5%",
            "median":"예측 중앙값","upper":"상단 95%","probability":"상승 확률(%)",
            "actual":"실제 환율","actual_date":"채점 공시일","correct":"방향 적중","within_band":"밴드 적중"}),hide_index=True)
        st.caption("배치 실행일별 최초 실제 예측을 보존합니다. 기준 공시일 이후 20개 관측이 쌓이면 채점합니다. 기존 샘플 기록은 집계에서 제외했습니다.")
    with st.expander("09 · 데이터 현황 및 방법론"):
        rows = [{"항목":v.get("name", {"larization":"라리화 비율","intervention":"외환시장 개입"}.get(k,k)),"상태":"실제 자료" if v.get("available") else "미연결",
                 "주기":v.get("frequency","—"),"최신 관측":v.get("labels",["—"])[-1],
                 "출처":v.get("source","—")} for k,v in snap["context"].items()]
        st.dataframe(pd.DataFrame(rows),hide_index=True)
        st.write("환율은 NBG 공시 단위(quantity)로 나눠 1단위 가격으로 정규화합니다. 필수 실제 환율 수집 실패 시 기존 실제 스냅샷을 보존합니다.")
        st.write("월간 모델은 미완료 월을 제외하고 학습합니다. 거시 통계는 공표 주기가 다르므로 가격 방향모델에 넣지 않습니다.")

st.header("조지아 환율 최신 뉴스")
news = snap["news"]
st.caption(f"현지 언론 원제 · 최근 {news['window_days']}일 · 수집 {news['collected_at']}")
choice = st.radio("뉴스 범위",["전체","환율·통화정책","관련 경제"],horizontal=True)
items = [item for item in news["items"] if choice == "전체" or item["category"] == choice]
if not items:
    st.info("해당 기간에 수집된 기사가 없습니다.")
for item in items:
    st.link_button(item["title"], item["link"], width="stretch")
    st.caption(f"{item['source']} · {item['published']} · {item['category']}")
st.dataframe(pd.DataFrame(news["sources"]),hide_index=True)
st.caption("기사 제목·출처·발행일과 원문 링크만 제공합니다. 기사는 예측 모델의 입력이 아닙니다.")

