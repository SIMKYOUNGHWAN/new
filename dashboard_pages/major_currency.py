"""주요 통화 공통 화면 — 각 통화의 독립적인 교차환율 분석."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from gel_app import charts, pipeline


def render(code: str, title: str, description: str) -> None:
    st.title(title)
    st.caption(f"{description} · 1 USD를 사는 데 필요한 {code} 금액")
    snap = pipeline.load_snapshot()
    if not snap:
        st.error("스냅샷이 없습니다. 일간 스냅샷 배치를 실행해 주세요.")
        return
    series = snap.get("crosses", {}).get(code, {})
    if not series.get("values"):
        st.info("이 통화의 초기 데이터를 준비 중입니다.")
        return
    sample = snap.get("meta", {}).get("mode", "").lower() != "live"
    fallback = snap.get("summary", {}).get("sampled_indicators", [])
    sample = sample or any(label in fallback for label in ("USD/GEL", f"{code}/GEL"))
    if sample:
        st.warning("샘플 데이터 · 아래 환율, 전망 및 성과는 화면 시연용입니다. 실제 시장 시세가 아닙니다.")
    else:
        st.info("NBG 고시환율로 계산한 교차환율입니다. 실시간 거래 호가와 차이가 있습니다.")
    st.caption(f"관측 기준일: {series['labels'][-1]} · 배치 갱신: {snap.get('meta', {}).get('generated_at_display', '—')}")
    st.caption(f"환율 상승 = {title} 약세 / 하락 = 강세 · 모든 가격 단위: {code}/USD")
    digits = series.get("digits", 4)
    fmt = lambda value: f"{value:,.{digits}f}"
    latest = series["values"][-1]
    prev = series["values"][-2] if len(series["values"]) > 1 else latest
    analysis = series.get("analysis", {})

    def chart(fig, price=True):
        if price:
            fig.update_yaxes(tickformat=f",.{digits}f", title_text=f"{code}/USD")
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    personal, expert = st.tabs(["개인용 — 핵심 요약", "전문가용 — 심화 분석"])
    with personal:
        st.header("개인용 — 핵심 요약")
        st.subheader("01 · 현재 환율과 최근 흐름")
        a, b, c = st.columns(3)
        a.metric(f"현재 {series['pair']}", fmt(latest), f"{(latest / prev - 1) * 100:+.2f}%")
        b.metric("최근 관측 구간 최저", fmt(min(series["values"])))
        c.metric("최근 관측 구간 최고", fmt(max(series["values"])))
        chart(charts.simple_line(series, charts.C["personal"]))
        st.caption("최저·최고는 위 차트의 최대 250개 관측값 기준입니다. 변화율은 직전 관측값 대비입니다.")
        st.subheader("02 · 환전 금액 계산")
        amount = st.number_input("달러 금액 (USD)", min_value=0.0, value=1000.0, step=100.0, key=f"{code}_amount")
        st.metric(f"필요한 {title}", f"{fmt(amount * latest)} {code}")
        st.caption("수수료와 은행 환전 스프레드는 포함하지 않습니다.")
        st.subheader("03 · 12개월 전망 시나리오")
        if analysis.get("available"):
            sc = analysis["scenario"]
            model_hist = analysis["history"]
            # Keep the chart anchor aligned with the completed-month model.
            model_hist = {k: v[:len(v) - 1] if model_hist["labels"][-1] > analysis["model_as_of"][:7] else v
                          for k, v in model_hist.items()}
            chart(charts.scenario(model_hist, sc))
            st.caption("강세·중립·약세는 과거 평균 수익률과 변동성으로 계산한 가정 경로입니다. 확률이나 목표가가 아닙니다.")
            mc = analysis["monte_carlo"]
            st.dataframe(pd.DataFrame({
                "전망 월": mc["labels"],
                f"하단 5% ({code})": mc["p05"],
                f"중앙값 ({code})": mc["p50"],
                f"상단 95% ({code})": mc["p95"],
            }), hide_index=True, width="stretch")
        else:
            st.info(analysis.get("reason", "분석 스냅샷 갱신 후 전망이 표시됩니다."))
        st.subheader("04 · 최근 가격 밴드")
        if analysis.get("bollinger", {}).get("labels"):
            chart(charts.bollinger(analysis["bollinger"]))
            st.caption("20개 관측값 이동평균 ± 2표준편차. 밴드 이탈만으로 매수·매도를 판단할 수 없습니다.")

    with expert:
        st.header("전문가용 — 심화 분석")
        if not analysis.get("available"):
            st.info(analysis.get("reason", "분석 스냅샷 갱신을 기다리고 있습니다."))
            return
        st.caption(f"월간 모델 학습 마지막 관측: {analysis['model_as_of']} · 총 일간 관측: {analysis['observations']}개")
        st.subheader("01 · 시계열 모델 전망")
        chart(charts.interval(analysis["arima"]))
        st.caption(f"사용 모델: {analysis['arima']['method']} · 음영은 모델 가정에 따른 80% 예측 구간입니다.")
        st.subheader("02 · 변동성 분석")
        volatility = analysis["garch"]
        vol_fig = charts.garch(volatility)
        last_date = pd.Timestamp(volatility["history_labels"][-1])
        forecast_dates = pd.bdate_range(last_date + pd.offsets.BDay(1), periods=len(volatility["forecast"]))
        # Plotly date axes cannot render the shared chart's "+1D" category labels.
        vol_fig.data[1].x = [last_date.strftime("%Y-%m-%d")] + forecast_dates.strftime("%Y-%m-%d").tolist()
        vol_fig.update_yaxes(title_text="연율화 변동성 (%)")
        chart(vol_fig, price=False)
        st.caption(f"{analysis['garch']['method']} · 연율화 변동성(%) · 향후 20개 관측일 전망, 연간 252개 관측 가정")
        st.subheader("03 · 몬테카를로와 하방·상방 위험")
        chart(charts.monte_carlo(analysis["monte_carlo"]))
        mc = analysis["monte_carlo"]
        st.caption(f"월간 로그수익률의 정규분포를 가정한 {mc['n_sims']:,}개 경로. 5~95% 범위이며 극단적 시장 충격은 과소평가될 수 있습니다.")
        anchor = analysis["scenario"]["anchor"]
        rows = []
        for i in (0, 2, 5, 11):
            rows.append({"전망 월": mc["labels"][i], "강세 방향 5% 변동(%)": round((mc["p05"][i] / anchor - 1) * 100, 2),
                         "약세 방향 95% 변동(%)": round((mc["p95"][i] / anchor - 1) * 100, 2)})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption("변동률은 월간 모델의 마지막 가격 대비이며 손실 확정값이 아닙니다.")
        st.subheader("04 · 추세와 계절성")
        seasonal = analysis["seasonality"]
        if seasonal.get("available"):
            chart(charts.seasonal_decomp(seasonal))
            chart(charts.month_effect(seasonal))
            st.caption("STL 12개월 주기 분해. 월별 계절 성분은 과거 패턴이며 미래 반복을 보장하지 않습니다.")
        else:
            st.info(seasonal.get("reason", "계절성 분석 불가"))
        st.subheader("05 · 모델별 백테스트")
        bt = analysis["backtest"]
        st.dataframe(pd.DataFrame({"모델": bt["labels"], f"RMSE ({code}/USD)": bt["rmse"]}),
                     hide_index=True, width="stretch",
                     column_config={f"RMSE ({code}/USD)": st.column_config.NumberColumn(format="%.6f")})
        st.caption(f"마지막 {bt['test_months']}개월을 제외하고 학습한 뒤 해당 기간을 한 번에 예측한 고정 분할 검증입니다. RMSE는 작을수록 좋습니다. 앙상블은 랜덤워크·이동평균·드리프트의 평균입니다.")
        with st.expander("데이터와 계산 방법", expanded=False):
            st.write(f"각 날짜의 (GEL/USD) ÷ (GEL/{code})로 교차환율을 계산합니다. 네 통화의 모델은 각각의 시계열로 따로 학습합니다.")
            st.write("완료되지 않은 당월은 월간 모델 학습에서 제외합니다. 일간 차트·가격 밴드·변동성은 최신 관측값까지 사용합니다.")
            st.write("실제 데이터가 부족하면 심화 분석을 보류합니다. 국가별 금리·물가 등 거시지표와 실시간 뉴스는 이 페이지에 아직 연결되어 있지 않습니다.")
            st.write("백테스트는 과거 자료 재현입니다. 일별 예측을 저장하고 미래 실제값으로 채점하는 예측 이력 기능은 이 네 통화에는 아직 제공하지 않습니다.")

