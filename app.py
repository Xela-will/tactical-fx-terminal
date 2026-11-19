import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh
from datetime import datetime
import pytz
import requests
import os

def send_telegram_alert(message):
    bot_token = "9147061627:AAHW0mNPH13a-MNBquysnPceFR7WMKv1Pfw"
    chat_id = "7108814293"
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception:
        pass

# =========================================================
# 1. Page Configuration & Custom Tactical Theme
# =========================================================
st.set_page_config(page_title="Tactical War Room | FX MTF Terminal", layout="wide")

refresh_cycle = st_autorefresh(interval=25000, limit=2000, key="fx_stream_sync")

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
    }
</style>
""", unsafe_allow_html=True)

# =========================================================
# 2. Watchlist & MTF Matrix Configuration
# =========================================================
WATCHLIST = {
    "Gold (GC=F)": "GC=F",
    "USD/JPY": "USDJPY=X",
    "GBP/JPY": "GBPJPY=X",
    "EUR/JPY": "EURJPY=X",
    "Bitcoin (BTC/USD)": "BTC-USD",
    "EUR/USD": "EURUSD=X",
    "GBP/USD": "GBPUSD=X",
    "USD/CAD": "USDCAD=X",
    "AUD/USD": "AUDUSD=X"
}

MTF_CONFIG = {
    "5m":  {"htf": "15m", "ltf_period": "5d",  "htf_period": "10d"},
    "15m": {"htf": "1h",  "ltf_period": "10d", "htf_period": "30d"},
    "30m": {"htf": "4h",  "ltf_period": "20d", "htf_period": "60d"},
    "1h":  {"htf": "1d",  "ltf_period": "60d", "htf_period": "2y"},
    "4h":  {"htf": "1d",  "ltf_period": "120d", "htf_period": "2y"},
    "1d":  {"htf": "1wk", "ltf_period": "2y",  "htf_period": "5y"}
}

st.sidebar.title("Tactical Room")

timeframe = st.sidebar.selectbox("Match Timeframe (LTF)", list(MTF_CONFIG.keys()), index=1)
htf_tf = MTF_CONFIG[timeframe]["htf"]

use_htf = st.sidebar.checkbox(f"Enforce {htf_tf.upper()} Trend Anchor", value=True)
target_rr = st.sidebar.select_slider("Target R:R Profile", options=[1.0, 1.2, 1.5, 2.0, 2.5, 3.0], value=2.0)
trade_management = st.sidebar.selectbox("Position Management", ["No Breakeven (Pure Target/Stop)", "Move to BE at +1.0R"], index=0)
stop_model = st.sidebar.selectbox("Defensive Stop Model", ["Structural (Recent Swing Low/High)", "Volatility (1.5x ATR)"], index=0)

adx_min = st.sidebar.slider("Chop Gate: Min ADX Velocity", min_value=15, max_value=30, value=20, step=1)
pullback_atr_depth = st.sidebar.slider("Pullback Tolerance (x ATR)", 0.2, 0.8, 0.45, 0.05)

st.sidebar.write("---")
st.sidebar.subheader("Capital & Sizing")
account_nav = st.sidebar.number_input("Account NAV ($)", value=500.0, step=50.0)
risk_pct = st.sidebar.slider("Cash Risk per Trade (%)", min_value=0.5, max_value=3.0, value=1.5, step=0.5) / 100.0
max_margin_pct = st.sidebar.slider("Max Margin Cap (%)", min_value=10, max_value=50, value=30, step=5) / 100.0

# =========================================================
# 3. Session Timing Engine
# =========================================================
est_tz = pytz.timezone("US/Eastern")
now_est = datetime.now(est_tz)

def evaluate_session_timing(ticker_label, dt, tf_label):
    if "BTC" in ticker_label:
        return True, "Crypto 24/7"
    if tf_label in ["4h", "1d"]:
        return True, "Macro Session"
    
    try:
        dt_est = dt.tz_convert(est_tz) if dt.tzinfo else pytz.timezone("UTC").localize(dt).astimezone(est_tz)
    except Exception:
        dt_est = dt
        
    hour_est = dt_est.hour + (dt_est.minute / 60.0)

    if any(k in ticker_label for k in ["JPY", "AUD"]):
        active = (hour_est >= 19.0 or hour_est <= 4.5) or (3.0 <= hour_est <= 11.5) or (8.0 <= hour_est <= 16.3)
        return active, "Tokyo / Core"
    if any(k in ticker_label for k in ["EUR", "GBP"]) and "USD" not in ticker_label:
        return (3.0 <= hour_est <= 12.0), "London Core"
    if any(k in ticker_label for k in ["USD", "CAD", "GC=F"]):
        active = (8.0 <= hour_est <= 16.3) or (3.0 <= hour_est <= 11.5)
        return active, "NY / London"
    return True, "Open Liquidity"

def is_session_active(ticker_label):
    return evaluate_session_timing(ticker_label, now_est, timeframe)

# =========================================================
# 4. Resilient Data Pipeline & Quantitative Indicators
# =========================================================
@st.cache_data(ttl=25)
def download_clean_ticker(symbol, interval, period):
    try:
        df = yf.download(symbol, period=period, interval=interval, progress=False)
        if df is None or df.empty:
            return None
        
        # Flatten MultiIndex if yfinance wrapped single ticker
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df = df.dropna(subset=['Close'])
        if len(df) < 30:
            return None
            
        df.index = pd.to_datetime(df.index, utc=True)
        df = df[~df.index.duplicated(keep='first')].sort_index()
        return df
    except Exception:
        return None

def process_mtf_indicators(df_ltf, df_htf, enforce_htf):
    if df_ltf is None or len(df_ltf) < 55:
        return None

    df_ltf = df_ltf.copy()

    # HTF 50 EMA Alignment
    if df_htf is not None and len(df_htf) >= 30:
        df_htf = df_htf.copy()
        df_htf['HTF_50EMA'] = df_htf['Close'].ewm(span=50, adjust=False).mean()
        df_htf['HTF_Bull'] = (df_htf['Close'] > df_htf['HTF_50EMA']).astype(int)
        df_htf['HTF_Bear'] = (df_htf['Close'] < df_htf['HTF_50EMA']).astype(int)

if active_buys or active_sells:
    alerts = []
    if active_buys: 
        alerts.append(f"🟢 **LIVE MTF BUY:** {', '.join(active_buys)}")
        send_telegram_alert(f"🟢 *TACTICAL MTF BUY ALERT*\nInstruments: {', '.join(active_buys)}\nTimeframe: {timeframe} | Macro: {htf_tf.upper()}")
    if active_sells: 
        alerts.append(f"🔴 **LIVE MTF SELL:** {', '.join(active_sells)}")
        send_telegram_alert(f"🔴 *TACTICAL MTF SELL ALERT*\nInstruments: {', '.join(active_sells)}\nTimeframe: {timeframe} | Macro: {htf_tf.upper()}")
    st.success(" | ".join(alerts))
        
        htf_shifted = df_htf[['HTF_50EMA', 'HTF_Bull', 'HTF_Bear']].shift(1)

        try:
            df = pd.merge_asof(
                df_ltf,
                htf_shifted,
                left_index=True,
                right_index=True,
                direction='backward'
            )
            df['HTF_Bull'] = df['HTF_Bull'].fillna(0).astype(bool)
            df['HTF_Bear'] = df['HTF_Bear'].fillna(0).astype(bool)
        except Exception:
            df = df_ltf
            df['HTF_Bull'] = True
            df['HTF_Bear'] = True
            df['HTF_50EMA'] = np.nan
    else:
        df = df_ltf
        df['HTF_Bull'] = True
        df['HTF_Bear'] = True
        df['HTF_50EMA'] = np.nan

    # LTF Indicators
    df['Midfield_200EMA'] = df['Close'].ewm(span=200, adjust=False).mean()
    df['Tempo_20EMA'] = df['Close'].ewm(span=20, adjust=False).mean()

    # Wilder's True Range & ATR(14)
    hl = df['High'] - df['Low']
    hc = (df['High'] - df['Close'].shift(1)).abs()
    lc = (df['Low'] - df['Close'].shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df['ATR_14'] = tr.ewm(alpha=1/14, adjust=False).mean()

    # Wilder's ADX(14)
    up_move = df['High'] - df['High'].shift(1)
    down_move = df['Low'].shift(1) - df['Low']
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr_smooth = tr.ewm(alpha=1/14, adjust=False).mean()
    plus_di = 100 * (pd.Series(plus_dm, index=df.index).ewm(alpha=1/14, adjust=False).mean() / tr_smooth)
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).ewm(alpha=1/14, adjust=False).mean() / tr_smooth)
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)).fillna(0)
    df['ADX'] = dx.ewm(alpha=1/14, adjust=False).mean().fillna(0)

    # Wilder's RSI(14)
    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    df['RSI'] = (100 - (100 / (1 + rs))).fillna(50)

    # Trend Angle Slope
    slope_diff = df['Midfield_200EMA'] - df['Midfield_200EMA'].shift(5)
    df['EMA200_Slope_Bull'] = slope_diff > (df['ATR_14'] * 0.02)
    df['EMA200_Slope_Bear'] = slope_diff < -(df['ATR_14'] * 0.02)

    # Pullback Buffer & Candlestick Confirmation
    box_buffer = df['ATR_14'] * pullback_atr_depth
    bull_pullback = (df['Low'] <= df['Tempo_20EMA'] + box_buffer) & (df['Close'] >= df['Tempo_20EMA'] - box_buffer)
    bear_rally = (df['High'] >= df['Tempo_20EMA'] - box_buffer) & (df['Close'] <= df['Tempo_20EMA'] + box_buffer)

    body_size = (df['Close'] - df['Open']).abs()
    lower_wick = df[['Open', 'Close']].min(axis=1) - df['Low']
    upper_wick = df['High'] - df[['Open', 'Close']].max(axis=1)

    bull_rejection = (lower_wick >= body_size * 0.35) | (df['Close'] > df['Open'])
    bear_rejection = (upper_wick >= body_size * 0.35) | (df['Close'] < df['Open'])

    has_velocity = df['ADX'] >= adx_min
    bull_structure = (df['Close'] > df['Midfield_200EMA']) & df['EMA200_Slope_Bull'] & has_velocity
    bear_structure = (df['Close'] < df['Midfield_200EMA']) & df['EMA200_Slope_Bear'] & has_velocity

    htf_long_ok = df['HTF_Bull'] if enforce_htf else True
    htf_short_ok = df['HTF_Bear'] if enforce_htf else True

    df['Striker_Buy'] = bull_structure & bull_pullback & bull_rejection & (df['RSI'] >= 40) & (df['RSI'] <= 65) & htf_long_ok
    df['Striker_Sell'] = bear_structure & bear_rally & bear_rejection & (df['RSI'] >= 35) & (df['RSI'] <= 60) & htf_short_ok

    return df

@st.cache_data(ttl=25)
def scan_all_markets(roster, ltf_tf, cfg, enforce_htf):
    results = {}
    for label, sym in roster.items():
        df_ltf = download_clean_ticker(sym, ltf_tf, cfg["ltf_period"])
        df_htf = download_clean_ticker(sym, cfg["htf"], cfg["htf_period"])
        
        if df_ltf is not None and not df_ltf.empty:
            processed = process_mtf_indicators(df_ltf, df_htf, enforce_htf)
            if processed is not None and not processed.empty:
                results[label] = processed
    return results

market_data = scan_all_markets(WATCHLIST, timeframe, MTF_CONFIG[timeframe], use_htf)

if not market_data:
    st.error(f"⚠️ Market data returned empty for `{timeframe}`. Try switching timeframes.")
    st.stop()

# =========================================================
# 5. Tactical Radar Scanner
# =========================================================
st.title("Tactical Radar: All-Pitch Scanner")
st.caption(f"Pitch Clock: {now_est.strftime('%H:%M:%S EST')} | Frame: `{timeframe}` | Macro Anchor: `{htf_tf.upper()}` 50 EMA")

radar_records = []
active_buys, active_sells = [], []

for label, df_item in market_data.items():
    latest = df_item.iloc[-1]
    sym = WATCHLIST[label]
    is_jpy = "JPY" in sym
    is_crypto = "BTC" in sym
    session_ok, _ = is_session_active(label)

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

    htf_state = "🟢 Bull" if bool(latest.get('HTF_Bull', False)) else "🔴 Bear"
    p_dec = 1 if is_crypto else (3 if is_jpy else 5)

    radar_records.append({
        "Instrument": label,
        "Signal": status,
        f"{htf_tf.upper()} Trend": htf_state,
        "Price": f"{latest['Close']:.{p_dec}f}",
        "ADX Velocity": f"{latest['ADX']:.1f}",
        "RSI": f"{latest['RSI']:.1f}",
        f"Defensive SL ({'USD' if is_crypto else 'Pips'})": f"{stop_units:.1f}"
    })

if active_buys or active_sells:
    alerts = []
    if active_buys: alerts.append(f"🟢 **LIVE MTF BUY:** {', '.join(active_buys)}")
    if active_sells: alerts.append(f"🔴 **LIVE MTF SELL:** {', '.join(active_sells)}")
    st.success(" | ".join(alerts))
else:
    st.info(f"🟡 **Pitch Clean:** No setups currently aligning with `{timeframe}` momentum + `{htf_tf.upper()}` macro direction.")

with st.expander("Tactical Matchday Board (Quick Scanner)", expanded=True):
    radar_df = pd.DataFrame(radar_records)
    if not radar_df.empty:
        radar_df['Rank'] = radar_df['Signal'].apply(lambda x: 0 if ("🟢" in x or "🔴" in x) else (1 if "⏸️" in x else 2))
        radar_df = radar_df.sort_values(by=['Rank', 'Instrument']).drop(columns=['Rank'])
        st.dataframe(radar_df, use_container_width=True, hide_index=True)

st.write("---")

# =========================================================
# 6. Detailed Pitch Inspector
# =========================================================
pitch_options = list(market_data.keys())
if "selected_pitch_key" not in st.session_state or st.session_state.selected_pitch_key not in pitch_options:
    st.session_state.selected_pitch_key = pitch_options[0]

selected_label = st.selectbox("Select Pitch to Inspect in Detail:", pitch_options, key="selected_pitch_key")

df = market_data[selected_label]
pair = WATCHLIST[selected_label]
latest = df.iloc[-1]
session_ok, session_name = is_session_active(selected_label)

is_jpy = "JPY" in pair
is_crypto = "BTC" in pair
is_gold = "GC=F" in pair
p_dec = 1 if is_crypto else (3 if is_jpy else 5)
pip_scale = 1.0 if is_crypto else (0.01 if is_jpy else 0.0001)

# Defensive Stop Computation (Structural vs ATR)
if "Structural" in stop_model and len(df) >= 6:
    swing_low = df['Low'].iloc[-6:-1].min()
    swing_high = df['High'].iloc[-6:-1].max()
    buffer_amt = latest['ATR_14'] * 0.3
    
    # Calculate for Long
    raw_dist_long = (latest['Close'] - (swing_low - buffer_amt))
    # Calculate for Short
    raw_dist_short = ((swing_high + buffer_amt) - latest['Close'])
    
    # Base stop distance on active possession
    stop_distance_price = max(raw_dist_long if latest['Close'] > latest['Midfield_200EMA'] else raw_dist_short, 8.0 * pip_scale)
else:
    stop_distance_price = max(latest['ATR_14'] * 1.5, 8.0 * pip_scale if not is_crypto else latest['ATR_14'] * 1.5)

stop_metric = stop_distance_price / pip_scale
metric_label = "USD ($)" if is_crypto else "Pips"

# Position Sizing
if is_crypto:
    margin_rate = 0.50
    risk_dollars = account_nav * risk_pct
    allowed_units = risk_dollars / stop_distance_price
    required_margin = allowed_units * latest['Close'] * margin_rate
    sizing_label = f"{allowed_units:.3f} BTC"
else:
    margin_rate = 0.05 if (is_jpy or is_gold) else 0.02
    pip_value_std_lot = (pip_scale / latest['Close']) * 100_000 if is_jpy else 10.0
    risk_dollars = account_nav * risk_pct
    lots_by_risk = risk_dollars / (stop_metric * pip_value_std_lot)

    max_margin_dollars = account_nav * max_margin_pct
    margin_per_lot = 100000.0 * margin_rate
    lots_by_margin = max_margin_dollars / margin_per_lot

    allowed_standard_lots = min(lots_by_risk, lots_by_margin)
    required_margin = allowed_standard_lots * margin_per_lot
    units_count = allowed_standard_lots * 100_000
    sizing_label = f"{units_count:,.0f} Units ({allowed_standard_lots:.3f} Lots)" if allowed_standard_lots < 0.1 else f"{allowed_standard_lots:.2f} Std Lots"

price_fmt = f"{latest['Close']:.{p_dec}f}"
in_possession = bool(latest['Close'] > latest['Midfield_200EMA'])
htf_is_bull = bool(latest.get('HTF_Bull', False))

status_color = "#10b981" if in_possession else "#ef4444"
status_text = "POSSESSION" if in_possession else "DEFENDING"
htf_badge_color = "#10b981" if htf_is_bull else "#ef4444"

st.markdown(f"""
<div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 1.2rem;">
    <h2 style="margin: 0; font-size: 1.5rem; font-weight: 700;">Pitch Focus: {selected_label} <span style="font-size: 0.95rem; color: #64748b; font-weight: 400;">[{timeframe}]</span></h2>
    <div style="display: flex; gap: 8px;">
        <span style="background: rgba({ '16, 185, 129' if htf_is_bull else '239, 68, 68' }, 0.15); 
                     color: {htf_badge_color}; border: 1px solid {htf_badge_color}; padding: 4px 12px; border-radius: 16px; font-size: 0.8rem; font-weight: 700;">
            MACRO [{htf_tf.upper()}]: {'BULLISH' if htf_is_bull else 'BEARISH'}
        </span>
        <span style="background: rgba({ '16, 185, 129' if in_possession else '239, 68, 68' }, 0.15); 
                     color: {status_color}; border: 1px solid {status_color}; padding: 4px 12px; border-radius: 16px; font-size: 0.8rem; font-weight: 700;">
            {status_text}
        </span>
    </div>
</div>
""", unsafe_allow_html=True)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Live Market Price", price_fmt)
c2.metric("ADX Momentum", f"{latest['ADX']:.1f}", delta="Trending" if latest['ADX'] >= adx_min else "-Chop Zone")
c3.metric(f"Defensive Stop", f"{stop_metric:.1f} {metric_label}", f"Target: +{stop_metric * target_rr:.1f} (1:{target_rr})")
c4.metric(f"Strict Size ({risk_pct*100:.1f}% Risk)", sizing_label, f"Req Margin: ${required_margin:,.2f}")

# =========================================================
# 7. Restored Active Directive Box (Buy/Sell, Entry, SL, TP)
# =========================================================
active_buy = bool(latest['Striker_Buy'])
active_sell = bool(latest['Striker_Sell'])
tp_mult = float(target_rr)

if active_buy and session_ok:
    sl_price = latest['Close'] - stop_distance_price
    tp_price = latest['Close'] + (stop_distance_price * tp_mult)
    st.success(f"""
    ### 🟢 ACTIVE DIRECTIVE: BUY / LONG SIGNAL
    * **Action:** Market Buy
    * **Entry Price:** `{latest['Close']:.{p_dec}f}`
    * **Stop Loss (SL):** `{sl_price:.{p_dec}f}` (-{stop_metric:.1f} {metric_label})
    * **Take Profit (TP):** `{tp_price:.{p_dec}f}` (+{stop_metric * tp_mult:.1f} {metric_label} | 1:{tp_mult} R:R Profile)
    * **Execution Quality:** Macro `{htf_tf.upper()}` 50 EMA aligned + ADX `{latest['ADX']:.1f}` velocity confirmed.
    * **Management Rule:** { 'Hands off — Target or Stop only.' if 'No Breakeven' in trade_management else f'Lock SL to breakeven once price reaches +{stop_metric:.1f} {metric_label}.' }
    """)
elif active_sell and session_ok:
    sl_price = latest['Close'] + stop_distance_price
    tp_price = latest['Close'] - (stop_distance_price * tp_mult)
    st.error(f"""
    ### 🔴 ACTIVE DIRECTIVE: SELL / SHORT SIGNAL
    * **Action:** Market Sell
    * **Entry Price:** `{latest['Close']:.{p_dec}f}`
    * **Stop Loss (SL):** `{sl_price:.{p_dec}f}` (+{stop_metric:.1f} {metric_label})
    * **Take Profit (TP):** `{tp_price:.{p_dec}f}` (-{stop_metric * tp_mult:.1f} {metric_label} | 1:{tp_mult} R:R Profile)
    * **Execution Quality:** Macro `{htf_tf.upper()}` 50 EMA aligned + ADX `{latest['ADX']:.1f}` velocity confirmed.
    * **Management Rule:** { 'Hands off — Target or Stop only.' if 'No Breakeven' in trade_management else f'Lock SL to breakeven once price reaches -{stop_metric:.1f} {metric_label}.' }
    """)
else:
    status_reason = f"Macro {htf_tf.upper()} is {'Bullish' if htf_is_bull else 'Bearish'}. Waiting for pullbacks to the 20 EMA." if use_htf else "Scanning for structure touch."
    st.info(f"""
    ### 🟡 TACTICAL DIRECTIVE: STAND BY (PATIENT POSSESSION)
    * **Status:** No qualified setup on `{timeframe}` pitch. ADX: `{latest['ADX']:.1f}` (Requires $\ge$ {adx_min}).
    * **Market Session:** {session_name} ({'Active' if session_ok else 'Low Volume'}).
    * **Alignment:** {status_reason}
    """)

# =========================================================
# 8. Interactive Pitch Chart
# =========================================================
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=[0.75, 0.25])

fig.add_trace(go.Candlestick(
    x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="Price"
), row=1, col=1)

fig.add_trace(go.Scatter(
    x=df.index, y=df['Midfield_200EMA'], line=dict(color='#eab308', width=2), name="LTF 200 EMA"
), row=1, col=1)

fig.add_trace(go.Scatter(
    x=df.index, y=df['Tempo_20EMA'], line=dict(color='#38bdf8', width=1.5, dash='dot'), name="LTF 20 EMA"
), row=1, col=1)

if 'HTF_50EMA' in df.columns and not df['HTF_50EMA'].isna().all():
    fig.add_trace(go.Scatter(
        x=df.index, y=df['HTF_50EMA'], line=dict(color='#a855f7', width=2, dash='dash'), name=f"Macro {htf_tf.upper()} 50 EMA"
    ), row=1, col=1)

buy_plays = df[df['Striker_Buy']]
fig.add_trace(go.Scatter(
    x=buy_plays.index, y=buy_plays['Low'] * (0.999 if is_jpy or is_crypto else 0.9998),
    mode='markers', marker=dict(symbol='triangle-up', size=11, color='#22c55e'), name="MTF Buy"
), row=1, col=1)

sell_plays = df[df['Striker_Sell']]
fig.add_trace(go.Scatter(
    x=sell_plays.index, y=sell_plays['High'] * (1.001 if is_jpy or is_crypto else 1.0002),
    mode='markers', marker=dict(symbol='triangle-down', size=11, color='#ef4444'), name="MTF Sell"
), row=1, col=1)

fig.add_trace(go.Scatter(x=df.index, y=df['ADX'], line=dict(color='#38bdf8', width=1.5), name="ADX Velocity"), row=2, col=1)
fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='#c084fc', width=1.2, dash='dot'), name="RSI Stamina"), row=2, col=1)
fig.add_hline(y=adx_min, line_dash="dash", line_color="#38bdf8", row=2, col=1)

fig.update_layout(
    template="plotly_dark",
    paper_bgcolor="#0b0f19",
    plot_bgcolor="#080c14",
    xaxis_rangeslider_visible=False,
    height=600,
    margin=dict(l=15, r=15, t=10, b=15),
    uirevision=pair
)
if not is_crypto:
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])

st.plotly_chart(fig, use_container_width=True, key=f"pitch_{pair}")

# =========================================================
# 9. Realistic Backtester Engine
# =========================================================
st.write("---")
st.subheader(f"Tactical Match Performance & Expectancy: {selected_label} [{timeframe} + {htf_tf.upper()}]")

def calculate_historical_performance(df, ticker_label, is_crypto, is_jpy, rr_target, management_mode, stop_type):
    trades = []
    pip_scale = 1.0 if is_crypto else (0.01 if is_jpy else 0.0001)

    in_trade = False
    active = {}
    use_be = ("Move to BE" in management_mode)

    for i in range(50, len(df)):
        row = df.iloc[i]

        if in_trade:
            if active['type'] == 'BUY':
                if use_be and not active['be_triggered'] and row['High'] >= active['be_threshold']:
                    active['sl'] = active['entry']
                    active['be_triggered'] = True

                if row['Low'] <= active['sl']:
                    res = "SCRATCH" if active['be_triggered'] else "LOSS"
                    r_val = 0.0 if active['be_triggered'] else -1.0
                    trades.append({
                        "Match Time": active['time'], "Tactic": "BUY", "Entry": active['entry'],
                        "Stop Loss": active['sl'], "Target": active['tp'],
                        f"Risk ({metric_label})": active['risk'], "Result": res, "R-Return": f"{r_val:+.1f} R",
                        "r_numeric": r_val
                    })
                    in_trade = False
                elif row['High'] >= active['tp']:
                    trades.append({
                        "Match Time": active['time'], "Tactic": "BUY", "Entry": active['entry'],
                        "Stop Loss": active['sl'], "Target": active['tp'],
                        f"Risk ({metric_label})": active['risk'], "Result": "WIN", "R-Return": f"+{rr_target:.1f} R",
                        "r_numeric": rr_target
                    })
                    in_trade = False

            elif active['type'] == 'SELL':
                if use_be and not active['be_triggered'] and row['Low'] <= active['be_threshold']:
                    active['sl'] = active['entry']
                    active['be_triggered'] = True

                if row['High'] >= active['sl']:
                    res = "SCRATCH" if active['be_triggered'] else "LOSS"
                    r_val = 0.0 if active['be_triggered'] else -1.0
                    trades.append({
                        "Match Time": active['time'], "Tactic": "SELL", "Entry": active['entry'],
                        "Stop Loss": active['sl'], "Target": active['tp'],
                        f"Risk ({metric_label})": active['risk'], "Result": res, "R-Return": f"{r_val:+.1f} R",
                        "r_numeric": r_val
                    })
                    in_trade = False
                elif row['Low'] <= active['tp']:
                    trades.append({
                        "Match Time": active['time'], "Tactic": "SELL", "Entry": active['entry'],
                        "Stop Loss": active['sl'], "Target": active['tp'],
                        f"Risk ({metric_label})": active['risk'], "Result": "WIN", "R-Return": f"+{rr_target:.1f} R",
                        "r_numeric": rr_target
                    })
                    in_trade = False
            continue

        session_valid, _ = evaluate_session_timing(ticker_label, row.name, timeframe)
        if not session_valid:
            continue

        is_buy = bool(row['Striker_Buy'])
        is_sell = bool(row['Striker_Sell'])
        if not (is_buy or is_sell):
            continue

        entry_price = row['Close']

        # Determine Stop Distance
        if "Structural" in stop_type and i >= 6:
            swing_low = df['Low'].iloc[i-5:i].min()
            swing_high = df['High'].iloc[i-5:i].max()
            buffer_amt = row['ATR_14'] * 0.3
            if is_buy:
                sl_price = swing_low - buffer_amt
                stop_dist = max(entry_price - sl_price, 8.0 * pip_scale)
                sl_price = entry_price - stop_dist
            else:
                sl_price = swing_high + buffer_amt
                stop_dist = max(sl_price - entry_price, 8.0 * pip_scale)
                sl_price = entry_price + stop_dist
        else:
            raw_stop = (row['ATR_14'] * 1.5) / pip_scale
            stop_units = max(raw_stop, 8.0) if not is_crypto else (row['ATR_14'] * 1.5)
            stop_dist = stop_units * pip_scale
            sl_price = (entry_price - stop_dist) if is_buy else (entry_price + stop_dist)

        tp_dist = stop_dist * rr_target
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
            "risk": round(stop_dist / pip_scale, 1)
        }

    return pd.DataFrame(trades)

perf_df = calculate_historical_performance(df, selected_label, is_crypto, is_jpy, target_rr, trade_management, stop_model)

if not perf_df.empty:
    completed = perf_df[perf_df['Result'].isin(['WIN', 'LOSS', 'SCRATCH'])]
    wins = len(completed[completed['Result'] == 'WIN'])
    scratches = len(completed[completed['Result'] == 'SCRATCH'])
    losses = len(completed[completed['Result'] == 'LOSS'])
    total_decided = wins + losses

    win_rate = (wins / total_decided * 100) if total_decided > 0 else 0.0
    net_r = completed['r_numeric'].sum()

    b1, b2, b3, b4 = st.columns(4)
    b1.metric("Disciplined Plays", f"{len(perf_df)} Total", f"{len(completed)} Closed")
    b2.metric("Decisive Win Rate", f"{win_rate:.1f}%", f"{wins}W - {scratches}BE - {losses}L")
    b3.metric("Net Tactical Expectancy", f"{net_r:+.1f} R", delta="Net Positive" if net_r > 0 else "-Drawdown")
    b4.metric("Management Mode", trade_management.split()[0], f"Target 1:{target_rr:.1f}")

    with st.expander(f"Detailed Match Call Log ({len(perf_df)} Total Plays)", expanded=False):
        st.dataframe(perf_df.drop(columns=['r_numeric']).iloc[::-1], use_container_width=True, hide_index=True)
else:
    st.info(f"No setups triggered during active liquidity windows meeting LTF + {htf_tf.upper()} alignment.")
