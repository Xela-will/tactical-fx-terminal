import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh

# 1. Page Configuration
st.set_page_config(page_title="Tactical FX Terminal", layout="wide")

# Polling engine: Auto-refreshes every 15 seconds
refresh_cycle = st_autorefresh(interval=15000, limit=2000, key="fx_stream_sync")

# 2. Watchlist Roster
FOREX_ROSTER = {
    "USD/CAD": "USDCAD=X",
    "USD/JPY": "USDJPY=X",
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "AUD/USD": "AUDUSD=X",
    "USD/CHF": "USDCHF=X",
    "NZD/USD": "NZDUSD=X",
    "GBP/JPY": "GBPJPY=X",
    "EUR/JPY": "EURJPY=X",
    "EUR/GBP": "EURGBP=X",
    "Gold (GC=F)": "GC=F",
    "Bitcoin (BTC/USD)": "BTC-USD"
}

# 3. Sidebar Controls
st.sidebar.title("Tactical Room")
selected_label = st.sidebar.selectbox("Active Instrument", list(FOREX_ROSTER.keys()), index=0)
pair = FOREX_ROSTER[selected_label]

timeframe = st.sidebar.selectbox(
    "Match Timeframe", 
    ["1m", "5m", "15m", "30m", "1h", "4h", "1d"], 
    index=2
)

st.sidebar.write("---")
st.sidebar.subheader("Account & Risk Settings")
account_nav = st.sidebar.number_input("OANDA Balance / NAV ($)", value=798000.0, step=10000.0)
risk_pct = st.sidebar.slider("Cash Risk per Trade (%)", min_value=0.1, max_value=2.0, value=0.5, step=0.1) / 100.0
max_margin_pct = st.sidebar.slider("Max Collateral Allowed (%)", min_value=5, max_value=40, value=20, step=5) / 100.0

st.sidebar.caption(f"Sync Cycle: {refresh_cycle} | Status: Connected")

# 4. Data Ingestion
period_map = {"1m": "1d", "5m": "5d", "15m": "10d", "30m": "20d", "1h": "30d", "4h": "60d", "1d": "1y"}
fetch_period = period_map.get(timeframe, "10d")

@st.cache_data(ttl=12)
def load_market_data(ticker, interval, period):
    df = yf.download(ticker, period=period, interval=interval, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

df = load_market_data(pair, timeframe, fetch_period)

if df is not None and not df.empty:
    # 5. Technical Indicators
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

    # Tactical Setup Definitions
    in_possession_bull = df['Close'] > df['Midfield_200EMA']
    pullback_to_box = (df['Low'] <= df['Tempo_20EMA']) & (df['Close'] >= df['Tempo_20EMA'] * 0.998)
    striker_primed_bull = (df['RSI'] >= 40) & (df['RSI'] <= 55)
    df['Striker_Buy'] = in_possession_bull & pullback_to_box & striker_primed_bull

    in_possession_bear = df['Close'] < df['Midfield_200EMA']
    rally_to_box = (df['High'] >= df['Tempo_20EMA']) & (df['Close'] <= df['Tempo_20EMA'] * 1.002)
    striker_primed_bear = (df['RSI'] >= 45) & (df['RSI'] <= 60)
    df['Striker_Sell'] = in_possession_bear & rally_to_box & striker_primed_bear

    # 6. Sizing & Levels
    latest = df.iloc[-1]
    is_jpy = "JPY" in pair
    pip_scale = 0.01 if is_jpy else 0.0001
    margin_rate = 0.05 if (is_jpy or "GC=F" in pair) else 0.02

    stop_distance_price = latest['ATR_14'] * 1.5
    stop_pips = stop_distance_price / pip_scale

    pip_value_std_lot = (pip_scale / latest['Close']) * 100_000 if is_jpy else 10.0
    risk_dollars = account_nav * risk_pct
    lots_by_risk = risk_dollars / (stop_pips * pip_value_std_lot)

    max_margin_dollars = account_nav * max_margin_pct
    margin_per_lot = 100000.0 * margin_rate
    lots_by_margin = max_margin_dollars / margin_per_lot

    allowed_standard_lots = min(lots_by_risk, lots_by_margin)
    required_margin = allowed_standard_lots * margin_per_lot

    in_possession = bool(latest['Close'] > latest['Midfield_200EMA'])
    active_buy_signal = bool(latest['Striker_Buy'])
    active_sell_signal = bool(latest['Striker_Sell'])

    p_dec = 3 if is_jpy else 5
    price_fmt = f"{latest['Close']:.{p_dec}f}"

    # 7. Metrics Header
    st.title(f"Tactical Pitch: {selected_label} [{timeframe}]")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Live Market Price", price_fmt)
    c2.metric("Possession", "ATTACKING" if in_possession else "DEFENDING", delta="Above 200 EMA" if in_possession else "-Below 200 EMA")
    c3.metric("Defensive Stop Distance", f"{stop_pips:.1f} Pips", f"Target: +{stop_pips * 2:.1f} Pips (1:2)")
    c4.metric("Strict Sizing (OANDA)", f"{allowed_standard_lots:.2f} Lots", f"Margin: ${required_margin:,.0f} ({int(1/margin_rate)}:1)")

    # 8. ACTIVE SIGNAL DIRECTIVE BOX
    st.write("---")
    if active_buy_signal:
        sl_price = latest['Close'] - stop_distance_price
        tp_price = latest['Close'] + (stop_distance_price * 2.0)
        st.success(f"""
        ### 🟢 ACTIVE DIRECTIVE: BUY / LONG SIGNAL
        * **Order Type:** Market Buy
        * **Entry Price:** `{latest['Close']:.{p_dec}f}`
        * **Stop Loss (SL):** `{sl_price:.{p_dec}f}` (-{stop_pips:.1f} Pips)
        * **Take Profit (TP):** `{tp_price:.{p_dec}f}` (+{stop_pips * 2:.1f} Pips | 1:2 R:R)
        * **Suggested Sizing:** `{allowed_standard_lots:.2f} Standard Lots` ({int(allowed_standard_lots * 100000):,} Units)
        * **Tactical Confirmation:** Above 200 EMA + Pullback to 20 EMA touched + RSI primed ({latest['RSI']:.1f})
        """)
    elif active_sell_signal:
        sl_price = latest['Close'] + stop_distance_price
        tp_price = latest['Close'] - (stop_distance_price * 2.0)
        st.error(f"""
        ### 🔴 ACTIVE DIRECTIVE: SELL / SHORT SIGNAL
        * **Order Type:** Market Sell
        * **Entry Price:** `{latest['Close']:.{p_dec}f}`
        * **Stop Loss (SL):** `{sl_price:.{p_dec}f}` (+{stop_pips:.1f} Pips)
        * **Take Profit (TP):** `{tp_price:.{p_dec}f}` (-{stop_pips * 2:.1f} Pips | 1:2 R:R)
        * **Suggested Sizing:** `{allowed_standard_lots:.2f} Standard Lots` ({int(allowed_standard_lots * 100000):,} Units)
        * **Tactical Confirmation:** Below 200 EMA + Rally to 20 EMA touched + RSI primed ({latest['RSI']:.1f})
        """)
    else:
        dist_to_ema20 = abs(latest['Close'] - latest['Tempo_20EMA']) / pip_scale
        reason = (
            f"Holding off. Waiting for value retest at 20 EMA (currently {dist_to_ema20:.1f} pips away at `{latest['Tempo_20EMA']:.{p_dec}f}`). Current RSI: `{latest['RSI']:.1f}`."
        )
        st.warning(f"""
        ### 🟡 TACTICAL DIRECTIVE: STAND BY (PATIENT POSSESSION)
        * **Status:** No trigger on active candle. Maintain position discipline.
        * **Tactical Read:** {reason}
        * **Prepared Defensive Size:** If trigger fires, max allowed size is **{allowed_standard_lots:.2f} Lots** ({stop_pips:.1f} pip stop).
        """)

    # 9. Interactive Chart
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.75, 0.25])

    fig.add_trace(go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        name="Price"
    ), row=1, col=1)

    fig.add_trace(go.Scatter(x=df.index, y=df['Midfield_200EMA'], line=dict(color='#eab308', width=2), name="Midfield (200 EMA)"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['Tempo_20EMA'], line=dict(color='#38bdf8', width=1.5, dash='dot'), name="Tempo (20 EMA)"), row=1, col=1)

    # Buy markers
    buy_plays = df[df['Striker_Buy']]
    fig.add_trace(go.Scatter(
        x=buy_plays.index, y=buy_plays['Low'] * (0.999 if is_jpy else 0.9998),
        mode='markers', marker=dict(symbol='triangle-up', size=11, color='#22c55e'),
        name="Buy Entry"
    ), row=1, col=1)

    # Sell markers
    sell_plays = df[df['Striker_Sell']]
    fig.add_trace(go.Scatter(
        x=sell_plays.index, y=sell_plays['High'] * (1.001 if is_jpy else 1.0002),
        mode='markers', marker=dict(symbol='triangle-down', size=11, color='#ef4444'),
        name="Sell Entry"
    ), row=1, col=1)

    # RSI
    fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='#c084fc', width=1.5), name="RSI Stamina"), row=2, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="#ef4444", row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="#22c55e", row=2, col=1)

    # Layout configuration with state preservation
    fig.update_layout(
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        height=680,
        margin=dict(l=20, r=20, t=20, b=20),
        uirevision=pair  # Locks in trace isolations and user zoom across live data ticks
    )
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])

    st.plotly_chart(fig, use_container_width=True, key=f"pitch_{pair}")
else:
    st.warning("Awaiting market data connection...")


