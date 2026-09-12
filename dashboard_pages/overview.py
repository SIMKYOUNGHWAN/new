"""7개 통화 통합 비교 페이지."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dashboard_pages.overview_data import NAMES, ROUTES, load, align, strength, window, changes, forecast, convert

COLORS = {"KRW":"#4C78A8","GEL":"#E45756","CNY":"#F2A541","EUR":"#54A24B","GBP":"#B279A2","JPY":"#28A6A0","TRY":"#D56DB5"}
st.title("🌐 글로벌 환율 종합")
st.caption("일곱 통화의 강세·약세, 위험, 전망을 실제 공시 데이터로 비교합니다.")
daily, monthly, sources, errors = load()
for error in errors:
    st.warning(error)
available = [c for c in NAMES if c in daily and len(daily[c]) > 1]
if not available:
    st.error("비교할 실제 환율 데이터가 없습니다.")
    st.stop()
selected = st.multiselect("비교할 통화", available, default=available, format_func=lambda c:NAMES[c])
a,b = st.columns(2)
with a:
    period = st.selectbox("비교 기간",["1주","1개월","3개월"],index=2)
with b:
    base = st.radio("비교 기준",["USD","KRW"] if "KRW" in available else ["USD"],
                    format_func=lambda c:"달러 기준" if c=="USD" else "원화 기준",horizontal=True)
if not selected:
    st.info("비교할 통화를 하나 이상 선택해 주세요.")
    st.stop()
needed = list(dict.fromkeys(selected + (["KRW"] if base == "KRW" else [])))
prices = align(daily,needed)
if len(prices) < 2:
    st.warning("선택한 통화의 공통 관측일이 부족합니다.")
    st.stop()
values = strength(prices,base)[selected]
days = {"1주":7,"1개월":30,"3개월":90}[period]
view = window(values,days)
if view is None:
    st.warning(f"{period} 이력이 부족해 확보된 전체 공통 구간으로 표시합니다.")
    view = values
asof = prices.index[-1]
st.info(f"공통 비교일 {asof:%Y-%m-%d} · 비교 시작 {view.index[0]:%Y-%m-%d} · {len(view)}개 공통 관측")
st.caption("휴일·공시시각이 다른 자료를 같은 날짜끼리만 대조합니다. 결측값은 보간하지 않습니다. 위로 갈수록 해당 통화 강세입니다.")
if (pd.Timestamp.now().normalize()-asof).days > 4:
    st.warning("공통 비교일이 4일 이상 지났습니다. 아래 출처별 최신 관측일을 확인해 주세요.")
indexed = view.div(view.iloc[0])*100
rank = (indexed.iloc[-1]-100).sort_values(ascending=False)
nonbase = rank.drop("KRW",errors="ignore") if base=="KRW" else rank
if len(nonbase):
    a,b,c = st.columns(3)
    a.metric("상대적으로 가장 강한 통화",NAMES[nonbase.index[0]],f"{nonbase.iloc[0]:+.2f}%")
    b.metric("상대적으로 가장 약한 통화",NAMES[nonbase.index[-1]],f"{nonbase.iloc[-1]:+.2f}%")
    c.metric("공통 관측 통화",f"{len(selected)}개")


def plot(fig,key,height=380):
    fig.update_layout(height=height,margin=dict(l=15,r=15,t=30,b=25),legend=dict(orientation="h",y=1.14),
                      hovermode="x unified")
    st.plotly_chart(fig,width="stretch",key=key,config={"displayModeBar":False})


def lines(frame):
    fig = go.Figure()
    for code in frame:
        fig.add_scatter(x=frame.index,y=frame[code],name=NAMES[code],line=dict(color=COLORS[code]))
    return fig


st.subheader("01 · 통화 강세·약세 비교선")
fig = lines(indexed)
fig.add_hline(y=100,line_dash="dot",line_color="gray")
fig.update_yaxes(title="시작점 = 100")
plot(fig,"strength",440)
left,right = st.columns(2)
with left:
    st.subheader("02 · 강세 순위")
    fig = go.Figure(go.Bar(x=rank.values,y=[NAMES[c] for c in rank.index],orientation="h",
                          marker_color=[COLORS[c] for c in rank.index],text=[f"{v:+.2f}%" for v in rank],textposition="auto"))
    fig.update_yaxes(autorange="reversed")
    fig.update_xaxes(title="가치 변화율 (%)",zeroline=True)
    plot(fig,"ranking")
with right:
    st.subheader("03 · 기간별 히트맵")
    table = changes(values)
    fig = go.Figure(go.Heatmap(z=table.values,x=table.columns,y=[NAMES[c] for c in table.index],
                              colorscale="RdBu",zmid=0,text=table.round(2).values,texttemplate="%{text}%",
                              hovertemplate="%{y} · %{x}: %{z:.2f}%<extra></extra>"))
    plot(fig,"changes")
    st.caption("기간 시작일은 목표 날짜와 같거나 이전인 가장 가까운 공통 관측일입니다. 부족한 기간은 빈칸입니다.")

st.subheader("04 · 동일 기준 전망 밴드")
st.caption("개별 페이지의 서로 다른 모델을 섞지 않고, 완료된 월의 로그수익률로 모든 통화에 같은 모델을 적용합니다. 오늘의 가치=100, 향후 12개월의 중앙값과 90% 가정 범위입니다.")
monthly_frame = align(monthly,needed)
forecasts = forecast(monthly_frame,asof,base)
if not forecasts:
    st.info("완료된 공통 월 데이터가 25개월 이상 필요합니다.")
else:
    cols = st.columns(3)
    for i, code in enumerate(selected):
        with cols[i%3]:
            st.markdown(f"**{NAMES[code]}**")
            f = forecasts[code]
            x = [asof.strftime("%Y-%m-%d")]+f["labels"]
            fig = go.Figure()
            fig.add_scatter(x=x,y=[100]+f["upper"],line=dict(width=0),showlegend=False)
            fig.add_scatter(x=x,y=[100]+f["lower"],fill="tonexty",line=dict(width=0),fillcolor="rgba(76,120,168,.16)",name="90% 범위")
            fig.add_scatter(x=x,y=[100]+f["median"],line=dict(color=COLORS[code]),name="중앙값")
            fig.add_hline(y=100,line_dash="dot")
            # Common axis makes uncertainty comparable across all small charts.
            displayed = [forecasts[c] for c in selected]
            fig.update_yaxes(range=[min(min(t["lower"]) for t in displayed)*.98,max(max(t["upper"]) for t in displayed)*1.02])
            plot(fig,f"forecast-{code}",270)
    st.caption(f"공통 학습 구간 {f['train_start']} ~ {f['train_end']} · 월 수익률 {f['months']}개 · 정규분포 가정이며 목표가·적중확률이 아닙니다.")
    if base=="KRW" and "KRW" in selected:
        st.caption("원화 기준에서 원화 자체는 기준선 100으로 고정됩니다.")

left,right = st.columns(2)
returns = np.log(view/view.shift()).dropna()
varying = [c for c in returns if returns[c].std()>1e-10]
with left:
    st.subheader("05 · 위험·강세 분포")
    if len(returns)<10 or not varying:
        st.info("변동성 비교에는 공통 수익률 관측이 10개 이상 필요합니다.")
    else:
        vol = returns[varying].std()*np.sqrt(252)*100
        fig = go.Figure()
        for code in varying:
            fig.add_scatter(x=[vol[code]],y=[rank[code]],text=[NAMES[code]],mode="markers+text",
                            textposition="top center",name=NAMES[code],marker=dict(size=15,color=COLORS[code]))
        fig.update_xaxes(title="연율화 변동성 (%)")
        fig.update_yaxes(title="선택 기간 강세율 (%)")
        plot(fig,"risk")
        st.caption("동일 공통 구간 수익률 표준편차 × √252. 휴일로 빠진 구간도 있어 근사 연율화 값입니다.")
with right:
    st.subheader("06 · 통화 간 상관관계")
    if len(returns)<10 or len(varying)<2:
        st.info("변동하는 통화 2개, 공통 수익률 관측 10개 이상이 필요합니다.")
    else:
        corr = returns[varying].corr()
        fig = go.Figure(go.Heatmap(z=corr.values,x=[NAMES[c] for c in varying],y=[NAMES[c] for c in varying],
                                  zmin=-1,zmax=1,zmid=0,colorscale="RdBu",text=corr.round(2).values,texttemplate="%{text}"))
        plot(fig,"correlation")
        st.caption("같은 날짜의 로그수익률 기준입니다. 공통 기준통화의 영향이 포함되며 인과관계가 아닙니다.")

st.subheader("07 · 원화 예산으로 살 수 있는 외화")
if "KRW" not in daily:
    st.info("원화 실제 데이터가 없어 계산할 수 없습니다.")
else:
    budget = st.number_input("환전 예산 (원)",min_value=0.0,value=1000000.0,step=100000.0)
    exchange_codes = [c for c in selected if c!="KRW"]
    if not exchange_codes:
        st.info("원화 외의 통화를 선택해 주세요.")
    else:
        exchange_prices = align(daily,["KRW"]+exchange_codes)
        exchange_view = window(exchange_prices,days)
        if exchange_view is None:
            exchange_view = exchange_prices
        if exchange_view.empty:
            st.info("환전 계산에 필요한 공통 관측일이 없습니다.")
        else:
            amounts = convert(exchange_view,budget)
            cols = st.columns(3)
            for i, code in enumerate(exchange_codes):
                with cols[i%3]:
                    st.metric(NAMES[code],f"{amounts[code].iloc[-1]:,.2f} {code}")
                    fig = go.Figure(go.Scatter(x=amounts.index,y=amounts[code],line=dict(color=COLORS[code])))
                    fig.update_yaxes(title=code)
                    plot(fig,f"exchange-{code}",230)
            st.caption(f"환전 기준일 {exchange_view.index[-1]:%Y-%m-%d} · 외화 금액 = 원화 예산 × (외화/USD) ÷ (KRW/USD). 수수료·스프레드 제외. 통화별 단위가 달라 별도 축으로 표시합니다.")

with st.expander("최신 공시·출처 및 상세 페이지",expanded=True):
    st.dataframe(pd.DataFrame([{"통화":NAMES[c],"1 USD당 금액":daily[c].iloc[-1],"개별 최신일":str(daily[c].index[-1].date()),
                               "출처":sources[c],"일간 관측":len(daily[c])} for c in selected]),hide_index=True)
    st.caption("최신 공시 표와 공통 날짜 비교 그래프는 기준일이 다를 수 있습니다. 원화는 기존 스냅샷의 실제 일간 가격 구간(최대 101개)을 사용합니다.")
    cols = st.columns(3)
    for i,c in enumerate(selected):
        cols[i%3].link_button(NAMES[c],"https://nazkvnevxccc4rzxqxxbch.streamlit.app"+ROUTES[c])

