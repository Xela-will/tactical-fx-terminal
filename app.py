import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh
from datetime import datetime
import pytz
import os

# =========================================================
# 1. Page Configuration & Custom Tactical Theme
# =========================================================
st.set_page_config(page_title="Tactical War Room | FX Terminal", layout="wide")

refresh_cycle = st_autorefresh(interval=20000, limit=2000, key="fx_stream_sync")

st.markdown("""
<style>
    .stApp {
        background-color: #0b0f19;
        color: #f3f4f6;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    div[data-testid="stMetric"] {
        background: linear-gradient(135deg, rgba(17, 24, 39, 0.85) 0%, rgba(15, 23, 42, 0.65) 100%);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
        backdrop-filter: blur(10px);
        transition: transform 0.2s ease, border-color 0.2s ease;
    }
    div[data-testid="stMetric"]:hover {
        transform: translateY(-2px);
        border-color: rgba(16, 185, 129, 0.4);
    }
    div[data-testid="stMetricLabel"] p {
        font-size: 0.8rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: #94a3b8 !important;
    }
    div[data-testid="stMetricValue"] div {
        font-family: 'JetBrains Mono', 'SF Mono', Consolas, monospace !important;
        font-weight: 700 !important;
        color: #f8fafc !important;
    }
    section[data-testid="stSidebar"] {
        background-color: #080c14 !important;
        border-right: 1px solid rgba(255, 255, 255, 0.06);
    }
    section[data-testid="stSidebar"] h1, 
    section[data-testid="stSidebar"] h2, 
    section[data-testid="stSidebar"] h3 {
        color: #10b981 !important;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }
    div[data-testid="stExpander"] {
        background: rgba(15, 23, 42, 0.55) !important;
        border: 1px solid rgba(255, 255, 255, 0.08) !important;
        border-radius: 12px !important;
        overflow: hidden;
    }
    .stButton>button {
        border-radius: 8px;
        background: linear-gradient(135deg, #059669 0%, #10b981 100%);
        color: #ffffff;
        font-weight: 600;
        border: none;
        box-shadow: 0 2px 10px rgba(16, 185, 129, 0.3);
        transition: all 0.2s ease;
    }
    .stButton>button:hover {
        background: linear-gradient(135deg, #10b981 0%, #34d399 100%);
        box-shadow: 0 4px 16px rgba(16, 185, 129, 0.5);
        transform: translateY(-1px);
    }
</style>
""", unsafe_allow_html=True)

# =========================================================
# 2. Watchlist Roster & Session Rules
# =========================================================
FOREX_ROSTER = {
    "USD/JPY": "USDJPY=X",
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "Gold (GC=F)": "GC=F",
    "Bitcoin (BTC/USD)": "BTC-USD",
    "USD/CAD": "USDCAD=X",
    "AUD/USD": "AUDUSD=X",
    "USD/CHF": "USDCHF=X",
    "NZD/USD": "NZDUSD=X",
    "GBP/JPY": "GBPJPY=X",
    "EUR/JPY": "EURJPY=X",
    "EUR/GBP": "EURGBP=X"
}

st.sidebar.title("Tactical Room")
timeframe = st.sidebar.selectbox("Match Timeframe", ["1m", "5m", "15m", "30m", "1h", "4h", "1d"], index=2)
target_rr = st.sidebar.selectbox("Tactical Risk:Reward Profile", [1.5, 2.0, 2.5], index=1)
adx_min = st.sidebar.slider("Chop Filter: Min ADX Velocity", min_value=15, max_value=32, value=22, step=1)

st.sidebar.subheader("Execution Quality Gates")
require_rejection_wick = st.sidebar.checkbox("Require Rejection Wick Confirmation", value=True,
                                             help="Only strike if candle shows rejection wick at the 20 EMA and closes in trend direction.")
pullback_atr_depth = st.sidebar.slider("Pullback Tolerance (x ATR)", 0.2, 0.8, 0.45, 0.05,
                                       help="How close price must touch the 20 EMA relative to volatility.")

st.sidebar.write("---")
st.sidebar.subheader("Account & Risk Management")
account_nav = st.sidebar.number_input("Account NAV ($)", value=500.0, step=50.0)
risk_pct = st.sidebar.slider("Cash Risk per Trade (%)", min_value=0.5, max_value=3.0, value=1.5, step=0.5) / 100.0
max_margin_pct = st.sidebar.slider("Max Margin Cap (%)", min_value=10, max_value=50, value=30, step=5) / 100.0

st.sidebar.write("---")
sidebar_gemini_key = st.sidebar.text_input("Gemini API Key (Optional)", type="password")
st.sidebar.caption(f"Sync Cycle: {refresh_cycle} | Status: Live Feed")

# =========================================================
# 3. Session Timing Engine
# =========================================================
est_tz = pytz.timezone("US/Eastern")
now_est = datetime.now(est_tz)

def evaluate_session_timing(ticker_label, dt, tf_label):
    if tf_label in ["4h", "1d"]:
        return True, "Macro Session"
    if "BTC" in ticker_label:
        return True, "Crypto 24/7"
    
    try:
        if dt.tzinfo is None:
            dt_est = pytz.timezone("UTC").localize(dt).astimezone(est_tz)
        else:
            dt_est = dt.astimezone(est_tz)
    except Exception:
        dt_est = dt
        
    hour_est = dt_est.hour + (dt_est.minute / 60.0)

    # London Core: 03:00 - 11:30 EST
    # NY Overlap: 08:00 - 16:30 EST
    # Asian Session (JPY/AUD/NZD): 19:00 - 04:00 EST
    if any(k in ticker_label for k in ["JPY", "AUD", "NZD"]):
        active = (hour_est >= 19.0 or hour_est <= 4.5) or (3.0 <= hour_est <= 11.5) or (8.0 <= hour_est <= 16.3)
        return active, "Tokyo / Core Active"
    if any(k in ticker_label for k in ["EUR", "GBP", "CHF"]) and "USD" not in ticker_label:
        return (3.0 <= hour_est <= 12.0), "London Core"
    if any(k in ticker_label for k in ["USD", "CAD", "GC=F"]):
        active = (8.0 <= hour_est <= 16.3) or (3.0 <= hour_est <= 11.5)
        return active, "NY / London Overlap"
        
    return True, "Open Liquidity"

def is_session_active(ticker_label):
    return evaluate_session_timing(ticker_label, now_est, timeframe)

# =========================================================
# 4. Quantitative Indicators & Strike Engine
# =========================================================
period_map = {"1m": "1d", "5m": "5d", "15m": "10d", "30m": "20d", "1h": "30d", "4h": "60d", "1d": "1y"}
fetch_period = period_map.get(timeframe, "10d")

def process_indicators(df):
    if df is None or len(df) < 55:
        return None
    df = df.copy()

    # Dynamic EMAs
    df['Midfield_200EMA'] = df['Close'].ewm(span=200, adjust=False).mean()
    df['Tempo_20EMA'] = df['Close'].ewm(span=20, adjust=False).mean()

    # Wilder's True Range & ATR(14)
    hl = df['High'] - df['Low']
    hc = (df['High'] - df['Close'].shift(1)).abs()
    lc = (df['Low'] - df['Close'].shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df['ATR_14'] = tr.ewm(alpha=1/14, adjust=False).mean()

    # Wilder's Directional Movement & Smoothed ADX(14)
    up_move = df['High'] - df['High'].shift(1)
    down_move = df['Low'].shift(1) - df['Low']
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr_smooth = tr.ewm(alpha=1/14, adjust=False).mean()
    plus_di = 100 * (pd.Series(plus_dm, index=df.index).ewm(alpha=1/14, adjust=False).mean() / tr_smooth)
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).ewm(alpha=1/14, adjust=False).mean() / tr_smooth)
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)).fillna(0)
    df['ADX'] = dx.ewm(alpha=1/14, adjust=False).mean().fillna(0)

    # RSI (14) with exponential smoothing
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    df['RSI'] = 100 - (100 / (1 + rs))
    df['RSI'] = df['RSI'].fillna(50)

    # 200 EMA Slope Direction
    slope_diff = df['Midfield_200EMA'] - df['Midfield_200EMA'].shift(5)
    df['EMA200_Slope_Bull'] = slope_diff > (df['ATR_14'] * 0.04)
    df['EMA200_Slope_Bear'] = slope_diff < -(df['ATR_14'] * 0.04)

    # ATR-Normalized Pullback Zone
    box_buffer = df['ATR_14'] * pullback_atr_depth
    bull_pullback = (df['Low'] <= df['Tempo_20EMA'] + box_buffer) & (df['Close'] >= df['Tempo_20EMA'] - box_buffer)
    bear_rally = (df['High'] >= df['Tempo_20EMA'] - box_buffer) & (df['Close'] <= df['Tempo_20EMA'] + box_buffer)

    # Candlestick Anatomy & Rejection Wicks
    body_size = (df['Close'] - df['Open']).abs()
    lower_wick = df[['Open', 'Close']].min(axis=1) - df['Low']
    upper_wick = df['High'] - df[['Open', 'Close']].max(axis=1)

    bull_rejection = (lower_wick >= body_size * 0.6) | (df['Close'] > df['Open']) if require_rejection_wick else True
    bear_rejection = (upper_wick >= body_size * 0.6) | (df['Close'] < df['Open']) if require_rejection_wick else True

    # Signal Rules
    has_velocity = df['ADX'] >= adx_min
    bull_structure = (df['Close'] > df['Midfield_200EMA']) & df['EMA200_Slope_Bull'] & has_velocity
    bear_structure = (df['Close'] < df['Midfield_200EMA']) & df['EMA200_Slope_Bear'] & has_velocity

    df['Striker_Buy'] = bull_structure & bull_pullback & bull_rejection & (df['RSI'] >= 40) & (df['RSI'] <= 60)
    df['Striker_Sell'] = bear_structure & bear_rally & bear_rejection & (df['RSI'] >= 40) & (df['RSI'] <= 60)

    return df

@st.cache_data(ttl=20)
def scan_all_markets(roster, interval, period):
    ticker_symbols = list(roster.values())
    raw_data = yf.download(ticker_symbols, period=period, interval=interval, group_by='ticker', progress=False)

    results = {}
    for label, sym in roster.items():
        try:
            if isinstance(raw_data.columns, pd.MultiIndex):
                if sym in raw_data.columns.levels[0]:
                    df_pair = raw_data[sym].dropna(subset=['Close'])
                else:
                    continue
            else:
                df_pair = raw_data.dropna(subset=['Close'])

            df_processed = process_indicators(df_pair)
            if df_processed is not None and not df_processed.empty:
                results[label] = df_processed
        except Exception:
            continue
    return results

market_data = scan_all_markets(FOREX_ROSTER, timeframe, fetch_period)

# =========================================================
# 5. Tactical Radar Scanner
# =========================================================
st.title("Tactical Radar: All-Pitch Scanner")
st.caption(f"Pitch Clock: {now_est.strftime('%H:%M:%S EST')} (NY Time) | Velocity Gate: ADX $\ge$ {adx_min}")

radar_records = []
active_buys, active_sells = [], []

for label, df_item in market_data.items():
    latest = df_item.iloc[-1]
    sym = FOREX_ROSTER[label]
    is_jpy = "JPY" in sym
    is_crypto = "BTC" in sym
    session_ok, session_name = is_session_active(label)

    pip_scale = 1.0 if is_crypto else (0.01 if is_jpy else 0.0001)
    raw_stop = (latest['ATR_14'] * 1.5) / pip_scale
    stop_units = max(raw_stop, 8.0) if not is_crypto else (latest['ATR_14'] * 1.5)

    status = "STANDBY"
    if bool(latest['Striker_Buy']):
        status = "🟢 BUY" if session_ok else "⏸️ BUY (Off-Hours)"
        if session_ok: active_buys.append(label)
    elif bool(latest['Striker_Sell']):
        status = "🔴 SELL" if session_ok else "⏸️ SELL (Off-Hours)"
        if session_ok: active_sells.append(label)

    p_dec = 1 if is_crypto else (3 if is_jpy else 5)
    radar_records.append({
        "Instrument": label,
        "Signal": status,
        "Session": "Active" if session_ok else "Low Volume",
        "Price": f"{latest['Close']:.{p_dec}f}",
        "ADX Velocity": f"{latest['ADX']:.1f}",
        "RSI": f"{latest['RSI']:.1f}",
        f"Defensive SL ({'USD' if is_crypto else 'Pips'})": f"{stop_units:.1f}"
    })

if active_buys or active_sells:
    alerts = []
    if active_buys: alerts.append(f"🟢 **LIVE STRIKE BUY:** {', '.join(active_buys)}")
    if active_sells: alerts.append(f"🔴 **LIVE STRIKE SELL:** {', '.join(active_sells)}")
    st.success(" | ".join(alerts))
else:
    st.info(f"🟡 **Pitch Clean:** No setups currently meeting the ADX $\ge$ {adx_min} velocity and rejection threshold.")

with st.expander("Tactical Matchday Board (Quick Scanner)", expanded=True):
    radar_df = pd.DataFrame(radar_records)
    if not radar_df.empty:
        radar_df['Rank'] = radar_df['Signal'].apply(lambda x: 0 if ("🟢" in x or "🔴" in x) else (1 if "⏸️" in x else 2))
        radar_df = radar_df.sort_values(by=['Rank', 'Instrument']).drop(columns=['Rank'])
        st.dataframe(radar_df, use_container_width=True, hide_index=True)

st.write("---")

# =========================================================
# 6. Detailed Pitch Inspector & Precise Position Sizing
# =========================================================
pitch_options = list(market_data.keys())
if "selected_pitch_key" not in st.session_state or st.session_state.selected_pitch_key not in pitch_options:
    st.session_state.selected_pitch_key = pitch_options[0]

selected_label = st.selectbox("Select Pitch to Inspect in Detail:", pitch_options, key="selected_pitch_key")

df = market_data[selected_label]
pair = FOREX_ROSTER[selected_label]
latest = df.iloc[-1]
session_ok, session_name = is_session_active(selected_label)

is_jpy = "JPY" in pair
is_crypto = "BTC" in pair
is_gold = "GC=F" in pair

if is_crypto:
    pip_scale = 1.0
    margin_rate = 0.50
    stop_distance_price = latest['ATR_14'] * 1.5
    stop_metric = stop_distance_price
    metric_label = "USD ($)"
    risk_dollars = account_nav * risk_pct
    allowed_units = risk_dollars / stop_distance_price
    required_margin = allowed_units * latest['Close'] * margin_rate
    sizing_label = f"{allowed_units:.3f} BTC"
else:
    pip_scale = 0.01 if is_jpy else 0.0001
    margin_rate = 0.05 if (is_jpy or is_gold) else 0.02
    metric_label = "Pips"

    raw_pips = (latest['ATR_14'] * 1.5) / pip_scale
    stop_metric = max(raw_pips, 8.0)
    stop_distance_price = stop_metric * pip_scale

    # OANDA Pip Value Formula
    pip_value_std_lot = (pip_scale / latest['Close']) * 100_000 if is_jpy else 10.0
    risk_dollars = account_nav * risk_pct
    lots_by_risk = risk_dollars / (stop_metric * pip_value_std_lot)

    max_margin_dollars = account_nav * max_margin_pct
    margin_per_lot = 100000.0 * margin_rate
    lots_by_margin = max_margin_dollars / margin_per_lot

    allowed_standard_lots = min(lots_by_risk, lots_by_margin)
    required_margin = allowed_standard_lots * margin_per_lot
    
    # Render units or micro-lots cleanly for smaller accounts
    units_count = allowed_standard_lots * 100_000
    if allowed_standard_lots < 0.1:
        sizing_label = f"{units_count:,.0f} Units ({allowed_standard_lots:.3f} Lots)"
    else:
        sizing_label = f"{allowed_standard_lots:.2f} Std Lots"

p_dec = 1 if is_crypto else (3 if is_jpy else 5)
price_fmt = f"{latest['Close']:.{p_dec}f}"
in_possession = bool(latest['Close'] > latest['Midfield_200EMA'])
active_buy = bool(latest['Striker_Buy'])
active_sell = bool(latest['Striker_Sell'])

status_color = "#10b981" if in_possession else "#ef4444"
status_text = "POSSESSION (ATTACKING)" if in_possession else "DEFENDING (COUNTER-ATTACK)"

st.markdown(f"""
<div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 1.2rem;">
    <h2 style="margin: 0; font-size: 1.5rem; font-weight: 700;">Pitch Focus: {selected_label} <span style="font-size: 0.95rem; color: #64748b; font-weight: 400;">[{timeframe}]</span></h2>
    <span style="background: rgba({ '16, 185, 129' if in_possession else '239, 68, 68' }, 0.15); 
                 color: {status_color}; border: 1px solid {status_color}; padding: 4px 12px; border-radius: 16px; font-size: 0.8rem; font-weight: 700;">
        {status_text}
    </span>
</div>
""", unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Live Market Price", price_fmt)
c2.metric("ADX Momentum", f"{latest['ADX']:.1f}", delta="Trending" if latest['ADX'] >= adx_min else "-Chop Zone")
c3.metric("Defensive Stop (1.5x ATR)", f"{stop_metric:.1f} {metric_label}", f"Target: +{stop_metric * target_rr:.1f} (1:{target_rr})")
c4.metric(f"Strict Size ({risk_pct*100:.1f}% Risk)", sizing_label, f"Req Margin: ${required_margin:,.2f}")

# =========================================================
# 7. Active Directive Box
# =========================================================
tp_mult = float(target_rr)
if active_buy and session_ok:
    sl_price = latest['Close'] - stop_distance_price
    tp_price = latest['Close'] + (stop_distance_price * tp_mult)
    st.success(f"""
    ### 🟢 ACTIVE DIRECTIVE: BUY / LONG SIGNAL
    * **Order Type:** Market Buy
    * **Entry Price:** `{latest['Close']:.{p_dec}f}`
    * **Stop Loss (SL):** `{sl_price:.{p_dec}f}` (-{stop_metric:.1f} {metric_label})
    * **Take Profit (TP):** `{tp_price:.{p_dec}f}` (+{stop_metric * tp_mult:.1f} {metric_label} | 1:{tp_mult} R:R)
    * **Defensive Rule:** Move SL to Breakeven after reaching +1.0R (`{latest['Close'] + stop_distance_price:.{p_dec}f}`).
    """)
elif active_sell and session_ok:
    sl_price = latest['Close'] + stop_distance_price
    tp_price = latest['Close'] - (stop_distance_price * tp_mult)
    st.error(f"""
    ### 🔴 ACTIVE DIRECTIVE: SELL / SHORT SIGNAL
    * **Order Type:** Market Sell
    * **Entry Price:** `{latest['Close']:.{p_dec}f}`
    * **Stop Loss (SL):** `{sl_price:.{p_dec}f}` (+{stop_metric:.1f} {metric_label})
    * **Take Profit (TP):** `{tp_price:.{p_dec}f}` (-{stop_metric * tp_mult:.1f} {metric_label} | 1:{tp_mult} R:R)
    * **Defensive Rule:** Move SL to Breakeven after reaching +1.0R (`{latest['Close'] - stop_distance_price:.{p_dec}f}`).
    """)
else:
    st.info(f"""
    ### 🟡 TACTICAL DIRECTIVE: STAND BY (PATIENT POSSESSION)
    * **Status:** No qualified setup. Current ADX is `{latest['ADX']:.1f}` (Requires $\ge$ {adx_min} for trend velocity).
    * **Session:** {session_name} ({'Active' if session_ok else 'Off-Hours'}).
    """)

# =========================================================
# 8. Interactive Pitch Chart
# =========================================================
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.75, 0.25])

fig.add_trace(go.Candlestick(
    x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
    name="Price"
), row=1, col=1)

fig.add_trace(go.Scatter(
    x=df.index, y=df['Midfield_200EMA'], line=dict(color='#eab308', width=2), name="Midfield (200 EMA)"
), row=1, col=1)

fig.add_trace(go.Scatter(
    x=df.index, y=df['Tempo_20EMA'], line=dict(color='#38bdf8', width=1.5, dash='dot'), name="Tempo (20 EMA)"
), row=1, col=1)

buy_plays = df[df['Striker_Buy']]
fig.add_trace(go.Scatter(
    x=buy_plays.index, y=buy_plays['Low'] * (0.999 if is_jpy or is_crypto else 0.9998),
    mode='markers', marker=dict(symbol='triangle-up', size=11, color='#22c55e'), name="Buy Entry"
), row=1, col=1)

sell_plays = df[df['Striker_Sell']]
fig.add_trace(go.Scatter(
    x=sell_plays.index, y=sell_plays['High'] * (1.001 if is_jpy or is_crypto else 1.0002),
    mode='markers', marker=dict(symbol='triangle-down', size=11, color='#ef4444'), name="Sell Entry"
), row=1, col=1)

fig.add_trace(go.Scatter(x=df.index, y=df['ADX'], line=dict(color='#38bdf8', width=1.5), name="ADX Velocity"), row=2, col=1)
fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='#c084fc', width=1.2, dash='dot'), name="RSI Stamina"), row=2, col=1)
fig.add_hline(y=adx_min, line_dash="dash", line_color="#38bdf8", row=2, col=1)

fig.update_layout(
    template="plotly_dark",
    paper_bgcolor="#0b0f19",
    plot_bgcolor="#080c14",
    xaxis_rangeslider_visible=False,
    height=640,
    margin=dict(l=15, r=15, t=10, b=15),
    uirevision=pair,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=11, color="#94a3b8"), bgcolor="rgba(0,0,0,0)")
)
if not is_crypto:
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])

st.plotly_chart(fig, use_container_width=True, key=f"pitch_{pair}")

# =========================================================
# 9. Realistic Backtester Engine (No Same-Bar Lookahead)
# =========================================================
st.write("---")
st.subheader(f"Tactical Match Performance & Win Rate: {selected_label} [{timeframe}]")

def calculate_historical_performance(df, ticker_label, is_crypto, is_jpy, rr_target):
    trades = []
    pip_scale = 1.0 if is_crypto else (0.01 if is_jpy else 0.0001)

    in_trade = False
    active = {}

    for i in range(50, len(df)):
        row = df.iloc[i]

        if in_trade:
            # BUY POSITION EVALUATION
            if active['type'] == 'BUY':
                # Check Breakeven threshold reached
                if not active['be_triggered'] and row['High'] >= active['be_threshold']:
                    active['sl'] = active['entry']
                    active['be_triggered'] = True

                # Check Stop Loss hit
                if row['Low'] <= active['sl']:
                    res = "SCRATCH" if active['be_triggered'] else "LOSS"
                    r_val = 0.0 if active['be_triggered'] else -1.0
                    trades.append({
                        "Match Time": active['time'],
                        "Tactic": "BUY",
                        "Entry": active['entry'],
                        "Stop Loss": active['sl'],
                        "Target": active['tp'],
                        f"Risk ({metric_label})": active['risk'],
                        "Result": res,
                        "R-Return": f"{r_val:+.1f} R"
                    })
                    in_trade = False
                # Check Take Profit hit
                elif row['High'] >= active['tp']:
                    trades.append({
                        "Match Time": active['time'],
                        "Tactic": "BUY",
                        "Entry": active['entry'],
                        "Stop Loss": active['sl'],
                        "Target": active['tp'],
                        f"Risk ({metric_label})": active['risk'],
                        "Result": "WIN",
                        "R-Return": f"+{rr_target:.1f} R"
                    })
                    in_trade = False

            # SELL POSITION EVALUATION
            elif active['type'] == 'SELL':
                if not active['be_triggered'] and row['Low'] <= active['be_threshold']:
                    active['sl'] = active['entry']
                    active['be_triggered'] = True

                if row['High'] >= active['sl']:
                    res = "SCRATCH" if active['be_triggered'] else "LOSS"
                    r_val = 0.0 if active['be_triggered'] else -1.0
                    trades.append({
                        "Match Time": active['time'],
                        "Tactic": "SELL",
                        "Entry": active['entry'],
                        "Stop Loss": active['sl'],
                        "Target": active['tp'],
                        f"Risk ({metric_label})": active['risk'],
                        "Result": res,
                        "R-Return": f"{r_val:+.1f} R"
                    })
                    in_trade = False
                elif row['Low'] <= active['tp']:
                    trades.append({
                        "Match Time": active['time'],
                        "Tactic": "SELL",
                        "Entry": active['entry'],
                        "Stop Loss": active['sl'],
                        "Target": active['tp'],
                        f"Risk ({metric_label})": active['risk'],
                        "Result": "WIN",
                        "R-Return": f"+{rr_target:.1f} R"
                    })
                    in_trade = False
            continue

        # Look for New Entries
        session_valid, _ = evaluate_session_timing(ticker_label, row.name, timeframe)
        if not session_valid:
            continue

        is_buy = bool(row['Striker_Buy'])
        is_sell = bool(row['Striker_Sell'])
        if not (is_buy or is_sell):
            continue

        entry_price = row['Close']
        raw_stop = (row['ATR_14'] * 1.5) / pip_scale
        stop_units = max(raw_stop, 8.0) if not is_crypto else (row['ATR_14'] * 1.5)
        stop_dist = stop_units * pip_scale
        tp_dist = stop_dist * rr_target

        sl_price = (entry_price - stop_dist) if is_buy else (entry_price + stop_dist)
        tp_price = (entry_price + tp_dist) if is_buy else (entry_price - tp_dist)
        be_trigger_price = (entry_price + stop_dist) if is_buy else (entry_price - stop_dist)

        in_trade = True
        active = {
            "time": row.name.strftime('%Y-%m-%d %H:%M'),
            "type": "BUY" if is_buy else "SELL",
            "entry": round(entry_price, p_dec),
            "sl": round(sl_price, p_dec),
            "tp": round(tp_price, p_dec),
            "be_threshold": round(be_trigger_price, p_dec),
            "be_triggered": False,
            "risk": round(stop_units, 1)
        }

    return pd.DataFrame(trades)

perf_df = calculate_historical_performance(df, selected_label, is_crypto, is_jpy, target_rr)

if not perf_df.empty:
    completed = perf_df[perf_df['Result'].isin(['WIN', 'LOSS', 'SCRATCH'])]
    wins = len(completed[completed['Result'] == 'WIN'])
    scratches = len(completed[completed['Result'] == 'SCRATCH'])
    losses = len(completed[completed['Result'] == 'LOSS'])
    total_decided = wins + losses

    win_rate = (wins / total_decided * 100) if total_decided > 0 else 0.0
    net_r = (wins * target_rr) - (losses * 1.0)

    b1, b2, b3, b4 = st.columns(4)
    b1.metric("Disciplined Plays", f"{len(perf_df)} Total", f"{len(completed)} Closed")
    b2.metric("Decisive Win Rate", f"{win_rate:.1f}%", f"{wins}W - {scratches}BE - {losses}L")
    b3.metric("Net Tactical Expectancy", f"{net_r:+.1f} R", delta="Net Positive" if net_r > 0 else "-Drawdown")
    b4.metric("Risk Profile Target", f"1 : {target_rr:.1f}", "Ratchet to BE at +1.0R")

    with st.expander(f"Detailed Match Call Log ({len(perf_df)} Total Plays)", expanded=False):
        st.dataframe(perf_df.iloc[::-1], use_container_width=True, hide_index=True)
else:
    st.info(f"No tactical setups triggered during active liquidity windows with ADX $\ge$ {adx_min}.")
