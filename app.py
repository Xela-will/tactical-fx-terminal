import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh

# 1. Page Configuration
st.set_page_config(page_title="Tactical FX Terminal", layout="wide")

# Polling engine: Auto-refreshes every 15 seconds (15,000 ms)
refresh_cycle = st_autorefresh(interval=15000, limit=2000, key="fx_stream_sync")

# 2. Sidebar Tactical Controls
st.sidebar.title("Tactical Room")
pair = st.sidebar.selectbox(
    "Active Instrument",
    ["USDJPY=X", "EURUSD=X", "GBPUSD=X", "GBPJPY=X", "GC=F"],
    index=0
)
timeframe = st.sidebar.selectbox("Match Timeframe", ["5m", "15m", "1h"], index=0)

st.sidebar.write("---")
st.sidebar.subheader("Account & Risk Settings")
account_nav = st.sidebar.number_input("OANDA Balance / NAV ($)", value=798000.0, step=10000.0)
risk_pct = st.sidebar.slider("Cash Risk per Trade (%)", min_value=0.1, max_value=2.0, value=0.5, step=0.1) / 100.0
max_margin_pct = st.sidebar.slider("Max Collateral Allowed (%)", min_value=5, max_value=40, value=20, step=5) / 100.0

st.sidebar.caption(f"Sync Cycle: {refresh_cycle} | Feed: Active")

# 3. Market Data Ingestion
@st.cache_data(ttl=12)
def load_market_data(ticker, interval):
    df = yf.download(ticker, period="5d", interval=interval, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

df = load_market_data(pair, timeframe)

if df is not None and not df.empty:
    # 4. Technical Indicators
    df['Midfield_200EMA'] = df['Close'].ewm(span=200, adjust=False).mean()
    df['Tempo_20EMA'] = df['Close'].ewm(span=20, adjust=False).mean()

    # Volatility / ATR
    high_low = df['High'] - df['Low']
    high_close = (df['High'] - df['Close'].shift()).abs()
    low_close = (df['Low'] - df['Close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['ATR_14'] = tr.rolling(window=14).mean()

    # Momentum RSI
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # Tactical Rules
    in_possession = df['Close'] > df['Midfield_200EMA']
    pullback_to_box = (df['Low'] <= df['Tempo_20EMA']) & (df['Close'] >= df['Tempo_20EMA'] * 0.998)
    striker_primed = (df['RSI'] >= 40) & (df['RSI'] <= 55)
    df['Striker_Buy'] = in_possession & pullback_to_box & striker_primed

    # 5. OANDA Defensive Math (With 20:1 Leverage Check)
    latest = df.iloc[-1]
    is_jpy = "JPY" in pair
    pip_scale = 0.01 if is_jpy else 0.0001
    margin_rate = 0.05 if is_jpy else 0.02  # 20:1 for JPY (5%), 50:1 for EUR/GBP (2%)

    stop_distance_price = latest['ATR_14'] * 1.5
    stop_pips = stop_distance_price / pip_scale

    # Dollar value of 1 pip for 1 standard lot (100,000 units)
    pip_value_std_lot = (pip_scale / latest['Close']) * 100_000 if is_jpy else 10.0

    # Risk-based lot sizing
    risk_dollars = account_nav * risk_pct
    lots_by_risk = risk_dollars / (stop_pips * pip_value_std_lot)

    # Margin-cap lot sizing (prevents tying up too much collateral)
    max_margin_dollars = account_nav * max_margin_pct
    notional_per_lot = 100000.0  # standard lot
    margin_per_lot = notional_per_lot * margin_rate
    lots_by_margin = max_margin_dollars / margin_per_lot

    # Final bounded sizing
    allowed_standard_lots = min(lots_by_risk, lots_by_margin)
    required_margin = allowed_standard_lots * margin_per_lot

    suggested_stop = latest['Close'] - stop_distance_price
    take_profit = latest['Close'] + (stop_distance_price * 2.0)

    # 6. Top Metrics Bar
    price_fmt = f"{latest['Close']:.3f}" if is_jpy else f"{latest['Close']:.5f}"
    st.title(f"Tactical Pitch: {pair} [{timeframe}]")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Live Market Price", price_fmt)
    c2.metric(
        "Possession Status", 
        "ATTACKING" if in_possession else "DEFENDING", 
        delta="Above 200 EMA" if in_possession else "-Below 200 EMA"
    )
    c3.metric(
        "Defensive Stop Distance", 
        f"{stop_pips:.1f} Pips", 
        f"Target: +{stop_pips * 2:.1f} Pips (1:2)"
    )
    c4.metric(
        "Strict Sizing (OANDA)", 
        f"{allowed_standard_lots:.2f} Lots", 
        f"Margin: ${required_margin:,.0f} ({margin_rate*100:.0f}:1)"
    )

    # 7. Interactive Multi-Pane Plotly Chart
    fig = make_subplots(
        rows=2, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.05, 
        row_heights=[0.75, 0.25]
    )

    # Candlestick chart
    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        name="Price"
    ), row=1, col=1)

    # Midfield & Tempo Lines
    fig.add_trace(go.Scatter(x=df.index, y=df['Midfield_200EMA'], line=dict(color='#eab308', width=2), name="Midfield (200 EMA)"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['Tempo_20EMA'], line=dict(color='#38bdf8', width=1.5, dash='dot'), name="Tempo (20 EMA)"), row=1, col=1)

    # Striker Markers
    striker_plays = df[df['Striker_Buy']]
    marker_y = striker_plays['Low'] * (0.999 if is_jpy else 0.9998)
    fig.add_trace(go.Scatter(
        x=striker_plays.index, y=marker_y, mode='markers',
        marker=dict(symbol='triangle-up', size=11, color='#22c55e'),
        name="Striker Entry"
    ), row=1, col=1)

    # RSI Pane
    fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='#c084fc', width=1.5), name="RSI Stamina"), row=2, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="#ef4444", row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="#22c55e", row=2, col=1)

    fig.update_layout(
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        height=680,
        margin=dict(l=20, r=20, t=20, b=20)
    )
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])

    st.plotly_chart(fig, use_container_width=True)
else:
    st.warning("Awaiting market data connection...")
