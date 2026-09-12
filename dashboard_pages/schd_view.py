"""SCHD summary and detailed analysis, shared by overview and /schd."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.schd import load_snapshot, performance, income, scenario

OFFICIAL = "https://www.schwabassetmanagement.com/products/schd"


def render(compact=False):
    if compact:
        st.subheader("09 · SCHD 미국 배당주 ETF")
    else:
        st.title("SCHD · 배당과 환율을 함께")
    st.caption("배당 현금흐름 · 배당 재투자 성과 · 원화 기준 손익")
    snap = load_snapshot()
    if not snap:
        st.info("SCHD 실제 데이터를 준비 중입니다. 데이터가 없으면 가상 수치를 표시하지 않습니다.")
        return
    meta, div = snap['meta'], snap['dividend']
    st.caption(f"주가·분배금 기준 {meta['price_asof']} · 원화 비교 공통일 {meta['common_asof']} · 일별 데이터, 실시간 호가 아님")
    age = (pd.Timestamp.now(tz='UTC').date()-pd.Timestamp(meta['common_asof']).date()).days
    if age > 4:
        st.warning(f"공통 관측일이 {age}일 전입니다. 데이터 갱신 상태를 확인하세요.")
    a,b,c = st.columns(3)
    a.metric("최근 종가", f"${snap['latest_price']:,.2f}")
    b.metric("최근 12개월 분배금 수익률", f"{div['yield_pct']:.2f}%")
    growth = div['growth']['5']
    c.metric("5년 분배금 연평균 성장률", '자료 부족' if growth is None else f"{growth:.2f}%")
    st.caption(f"주당 최근 12개월 분배금 ${div['ttm']:.4f} ÷ 최근 종가. 5년 성장은 {div['growth_end']-5}~{div['growth_end']} 완료 연도 비교. SEC 수익률과 다른 지표입니다.")
    if compact:
        st.link_button("SCHD 상세 분석·배당 계산기 열기", "https://nazkvnevxccc4rzxqxxbch.streamlit.app/schd")
        return

    st.markdown(f"[운용사 공식 상품·분배금 자료]({OFFICIAL}) · [가격·조정주가 출처](https://finance.yahoo.com/quote/SCHD/history/) · [환율 출처: ECB](https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip)")
    history = snap['history']
    frame = pd.DataFrame({c:history[c] for c in ('close','adjusted','fx')}, index=pd.to_datetime(history['dates']))
    returns_tab, dividends_tab, calculator_tab = st.tabs(["총수익·하락 위험", "분배금 성장", "원화 배당·환율 계산"])
    with returns_tab:
        years = st.selectbox("분석 기간", [1,3,5], index=2, format_func=lambda n:f"최근 {n}년", key="schd-years")
        result = performance(frame, years)
        if result is None:
            st.info("선택 기간의 실제 이력이 부족합니다.")
        else:
            wealth = result['wealth']
            st.caption(f"{wealth.index[0]:%Y-%m-%d} ~ {wealth.index[-1]:%Y-%m-%d} · 배당 전액 재투자 · 세전")
            st.dataframe(pd.DataFrame([{"기준":'달러' if c=='USD' else '원화',
                "누적 총수익률 (%)":result['return'][c], "연평균 수익률 (%)":result['cagr'][c],
                "최대낙폭 (%)":result['mdd'][c]} for c in ('USD','KRW')]), hide_index=True,
                column_config={c:st.column_config.NumberColumn(format="%.2f") for c in ('누적 총수익률 (%)','연평균 수익률 (%)','최대낙폭 (%)')})
            fig = go.Figure()
            for code,label,color in [('USD','달러 · 배당 재투자','#38BDF8'),('KRW','원화 · 배당 재투자','#FBBF24')]:
                fig.add_scatter(x=wealth.index,y=wealth[code],name=label,line=dict(color=color))
            price = result['view'].close
            fig.add_scatter(x=price.index,y=price/price.iloc[0]*100,name='달러 · 가격만',line=dict(dash='dot',color='#94A3B8'))
            fig.update_layout(yaxis_title='시작금액 = 100',hovermode='x unified',legend=dict(orientation='h'))
            st.plotly_chart(fig,width='stretch')
            dd = wealth/wealth.cummax()*100-100
            fig = go.Figure()
            for c in ('USD','KRW'):
                fig.add_scatter(x=dd.index,y=dd[c],name=c)
            fig.update_layout(title='고점 대비 하락률',yaxis_title='낙폭 (%)',hovermode='x unified')
            st.plotly_chart(fig,width='stretch')
            st.caption("배당·분할 조정주가로 총수익을 계산합니다. 원화 성과는 달러 자산을 계속 보유하고 마지막에 환전하는 가정입니다. 주가·ECB 환율의 공통 관측일만 사용하며, 같은 날짜라도 공시 시각은 다릅니다. 빠진 날짜의 낙폭은 포착하지 못할 수 있습니다.")

    with dividends_tab:
        annual = pd.DataFrame(div['annual'])
        annual['구분'] = annual.complete.map({True:'완료 연도',False:'부분 연도 · 성장 비교 제외'})
        fig = go.Figure(go.Bar(x=annual.year.astype(str),y=annual.amount,
            marker_color=['#34D399' if x else '#64748B' for x in annual.complete],
            customdata=annual['구분'],hovertemplate='%{x}: $%{y:.4f}<br>%{customdata}<extra></extra>'))
        fig.update_layout(title='연도별 주당 분배금 · 현재 주식 수 기준',yaxis_title='USD / 주')
        st.plotly_chart(fig,width='stretch')
        a,b,c = st.columns(3)
        for col,n in zip((a,b,c),(1,3,5)):
            value = div['growth'][str(n)]
            col.metric(f"{n}년 분배금 연평균 성장률",'자료 부족' if value is None else f"{value:.2f}%")
        st.caption("2024년 3대 1 분할이 이미 반영된 Yahoo 분배금을 사용하며 다시 3으로 나누지 않습니다. 올해 누계와 최초 부분 연도는 성장률 비교에서 제외합니다. 분배금은 배당락일 기준으로 묶습니다.")
        distributions = pd.DataFrame(snap['distributions']).tail(12).iloc[::-1]
        st.dataframe(distributions.rename(columns={'ex_date':'배당락일 (지급일 아님)','amount':'분할 반영 주당 분배금 (USD)'}),hide_index=True)

    with calculator_tab:
        st.caption("현재 분배금이 앞으로 1년 반복된다는 가정입니다. 미래 지급액·수익을 예측하거나 보장하지 않습니다.")
        a,b = st.columns(2)
        budget = a.number_input("투자 예산 (원)",min_value=0.0,value=10000000.0,step=1000000.0,key='schd-budget')
        withholding = b.number_input("가정 배당 원천징수율 (%)",min_value=0.0,max_value=100.0,value=15.0,step=0.1,key='schd-tax')
        st.caption("15%는 변경 가능한 계산 가정입니다. 개인별 최종 세율이 아니며 한국 추가 과세·매매차익세·환전/거래 수수료는 계산하지 않습니다.")
        a,b = st.columns(2)
        price = a.number_input("가정 매수가 (USD/주)",min_value=0.01,value=float(frame.close.iloc[-1]),step=0.1,key='schd-price')
        fx = b.number_input("가정 환율 (원/USD)",min_value=0.01,value=float(frame.fx.iloc[-1]),step=1.0,key='schd-fx')
        st.caption(f"초기 매수가·환율은 공통 관측일 {meta['common_asof']} 기준이며 직접 변경할 수 있습니다.")
        ttm = st.number_input("가정 1년 주당 분배금 (USD)",min_value=0.0,value=float(div['ttm']),step=0.01,key='schd-dividend')
        inc = income(budget,price,fx,ttm,withholding)
        a,b,c = st.columns(3)
        a.metric("매수 가능 수량 · 정수주",f"{inc['shares']:,}주")
        b.metric("가정 연 배당 · 원천징수 차감",f"{inc['net']*fx:,.0f}원",help='입력 환율로 환산. 지급일 환율에 따라 달라집니다.')
        c.metric("월평균 환산 · 월배당 아님",f"{inc['net']*fx/12:,.0f}원")
        st.caption(f"세전 연 배당 ${inc['gross']:,.2f} · 원천징수 차감 ${inc['net']:,.2f} · 남는 달러 현금 ${inc['cash_usd']:,.2f}. 분배금 재투자 없이 현금 보유 가정.")
        changes = [-20,-10,0,10,20]
        rows = []
        if budget > 0:
            for pr in changes:
                rows.append([100*(scenario(budget,price,fx,ttm,withholding,pr,fr)/budget-1) for fr in changes])
            fig = go.Figure(go.Heatmap(z=rows,x=[f'{x:+d}%' for x in changes],y=[f'{x:+d}%' for x in changes],
                zmid=0,colorscale='RdBu',text=np_round(rows),texttemplate='%{text}%',
                hovertemplate='환율 %{x} · 주가 %{y}<br>원화 손익률 %{z:.2f}%<extra></extra>'))
            fig.update_layout(title='1년 뒤 주가·환율별 원화 손익률 가정',xaxis_title='원/달러 환율 변화 (상승 = 달러 강세)',yaxis_title='SCHD 주가 변화 (배당 제외)')
            st.plotly_chart(fig,width='stretch')
            st.caption("기말 달러자산 = 주식의 기말 가치 + 남은 현금 + 원천징수 차감 배당. 이를 기말 환율로 원화 환산합니다. 배당금과 잔여 현금도 달러로 보유하며 이자는 붙이지 않습니다.")
        else:
            st.info("투자 예산을 입력하면 환율·주가별 손익표가 표시됩니다.")
        st.caption("정기예금과 비교할 때도 동일한 1년·원화·세금 가정을 사용하세요. SCHD 주가 수익률은 확정 이자가 아닙니다.")

    with st.expander("데이터·계산 방법과 추가로 볼 지표"):
        st.write("TTM 수익률은 최근 1년 배당락 분배금 합계/최근 종가입니다. SEC 30일 수익률이나 향후 확정 배당률이 아닙니다. 연도별 성장률은 완료 연도끼리 비교합니다.")
        st.write("총수익은 Yahoo 조정주가 비율, 원화 총수익은 조정주가×ECB 원/달러 환율 비율입니다. ETF 운용비용은 과거 가격에 반영되므로 다시 차감하지 않습니다. 개인 세금과 수수료는 과거 총수익에서 제외되어 있습니다.")
        st.write("은행 정기예금과 달리 원금·분배금이 변동합니다. 운용사 공식 자료의 편입 업종·상위 종목 비중, PER·ROE·현금흐름, 분배금 공시도 함께 확인하세요. 이 페이지는 해당 기업 재무지표를 자동 분석하지 않습니다.")
        st.caption(f"데이터 생성: {meta['generated_at']} · 평일 배치 자동 갱신, 실패 시 이전 자료 유지 · 미래 전망 모델을 사용하지 않습니다.")


def np_round(rows):
    return [[round(v,2) for v in row] for row in rows]
