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

# 1. Page Configuration
st.set_page_config(page_title="Tactical FX Terminal", layout="wide")

# Polling engine: Auto-refreshes every 20 seconds
refresh_cycle = st_autorefresh(interval=20000, limit=2000, key="fx_stream_sync")

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

st.sidebar.write("---")
st.sidebar.subheader("AI Intelligence Layer")
sidebar_gemini_key = st.sidebar.text_input("Gemini API Key (Optional)", type="password", help="Leave blank if set in Streamlit Secrets")

st.sidebar.caption(f"Sync Cycle: {refresh_cycle} | Status: Connected")

# 4. Session Liquidity Filter (EST Timezone)
est_tz = pytz.timezone("US/Eastern")
now_est = datetime.now(est_tz)
current_hour_est = now_est.hour + (now_est.minute / 60.0)

def is_session_active(ticker_label):
    if "BTC" in ticker_label:
        return True, "Crypto 24/7"
    if any(k in ticker_label for k in ["EUR", "GBP", "CHF"]) and "USD" not in ticker_label and "JPY" not in ticker_label:
        active = (3.0 <= current_hour_est <= 12.0)
        return active, "London Core (03:00 - 12:00 EST)"
    if any(k in ticker_label for k in ["USD", "CAD", "GC=F"]):
        active = (8.0 <= current_hour_est <= 16.3) or (3.0 <= current_hour_est <= 11.5)
        return active, "NY / London Overlap (08:00 - 16:30 EST)"
    if any(k in ticker_label for k in ["JPY", "AUD", "NZD"]):
        active = (current_hour_est >= 19.0 or current_hour_est <= 4.0) or (3.0 <= current_hour_est <= 11.5)
        return active, "Tokyo / London Active"
    return True, "Open Liquidity"

# 5. Data Fetching & Indicators
period_map = {"1m": "1d", "5m": "5d", "15m": "10d", "30m": "20d", "1h": "30d", "4h": "60d", "1d": "1y"}
fetch_period = period_map.get(timeframe, "10d")

def process_indicators(df):
    if df is None or len(df) < 50:
        return None
    df = df.copy()
    df['Midfield_200EMA'] = df['Close'].ewm(span=200, adjust=False).mean()
    df['Tempo_20EMA'] = df['Close'].ewm(span=20, adjust=False).mean()

    hl = df['High'] - df['Low']
    hc = (df['High'] - df['Close'].shift()).abs()
    lc = (df['Low'] - df['Close'].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df['ATR_14'] = tr.rolling(window=14).mean()

    delta = df['Close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    in_possession_bull = df['Close'] > df['Midfield_200EMA']
    pullback_to_box = (df['Low'] <= df['Tempo_20EMA']) & (df['Close'] >= df['Tempo_20EMA'] * 0.998)
    striker_primed_bull = (df['RSI'] >= 40) & (df['RSI'] <= 55)
    df['Striker_Buy'] = in_possession_bull & pullback_to_box & striker_primed_bull

    in_possession_bear = df['Close'] < df['Midfield_200EMA']
    rally_to_box = (df['High'] >= df['Tempo_20EMA']) & (df['Close'] <= df['Tempo_20EMA'] * 1.002)
    striker_primed_bear = (df['RSI'] >= 45) & (df['RSI'] <= 60)
    df['Striker_Sell'] = in_possession_bear & rally_to_box & striker_primed_bear

    return df

@st.cache_data(ttl=15)
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

# 6. Tactical Radar Scanner
st.title("Tactical Radar: All-Pitch Scanner")
st.caption(f"Pitch Clock: {now_est.strftime('%H:%M:%S EST')} (New York Time)")

radar_records = []
active_buys = []
active_sells = []

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
        if session_ok:
            status = "🟢 BUY"
            active_buys.append(label)
        else:
            status = "⏸️ BUY (Off-Hours)"
    elif bool(latest['Striker_Sell']):
        if session_ok:
            status = "🔴 SELL"
            active_sells.append(label)
        else:
            status = "⏸️ SELL (Off-Hours)"

    p_dec = 1 if is_crypto else (3 if is_jpy else 5)
    radar_records.append({
        "Instrument": label,
        "Signal": status,
        "Session State": "Active" if session_ok else "Closed / Low Liquidity",
        "Price": f"{latest['Close']:.{p_dec}f}",
        "Possession": "Attacking" if latest['Close'] > latest['Midfield_200EMA'] else "Defending",
        "RSI": f"{latest['RSI']:.1f}",
        f"Stop ({'USD' if is_crypto else 'Pips'})": f"{stop_units:.1f}"
    })

if active_buys or active_sells:
    alert_msg = []
    if active_buys:
        alert_msg.append(f"🟢 **LIVE BUY:** {', '.join(active_buys)}")
    if active_sells:
        alert_msg.append(f"🔴 **LIVE SELL:** {', '.join(active_sells)}")
    st.success(" | ".join(alert_msg))
else:
    st.info("🟡 **Radar Clean:** No instruments in strike zone during active market sessions.")

with st.expander("Tactical Matchday Board (Quick Scanner)", expanded=True):
    radar_df = pd.DataFrame(radar_records)
    if not radar_df.empty:
        radar_df['Rank'] = radar_df['Signal'].apply(lambda x: 0 if ("🟢" in x or "🔴" in x) else (1 if "⏸️" in x else 2))
        radar_df = radar_df.sort_values(by=['Rank', 'Instrument']).drop(columns=['Rank'])
        st.dataframe(radar_df, use_container_width=True, hide_index=True)

st.write("---")

# 7. Detailed Pitch Inspector
selected_label = st.selectbox(
    "Select Pitch to Inspect in Detail:",
    list(market_data.keys()),
    index=0 if not (active_buys + active_sells) else list(market_data.keys()).index((active_buys + active_sells)[0])
)

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
    allowed_standard_lots = risk_dollars / stop_distance_price
    required_margin = allowed_standard_lots * latest['Close'] * margin_rate
    sizing_label = f"{allowed_standard_lots:.3f} BTC Coins"
else:
    pip_scale = 0.01 if is_jpy else 0.0001
    margin_rate = 0.05 if (is_jpy or is_gold) else 0.02
    metric_label = "Pips"
    
    raw_pips = (latest['ATR_14'] * 1.5) / pip_scale
    stop_metric = max(raw_pips, 8.0)
    stop_distance_price = stop_metric * pip_scale

    pip_value_std_lot = (pip_scale / latest['Close']) * 100_000 if is_jpy else 10.0
    risk_dollars = account_nav * risk_pct
    lots_by_risk = risk_dollars / (stop_metric * pip_value_std_lot)

    max_margin_dollars = account_nav * max_margin_pct
    margin_per_lot = 100000.0 * margin_rate
    lots_by_margin = max_margin_dollars / margin_per_lot

    allowed_standard_lots = min(lots_by_risk, lots_by_margin, 10.0)
    required_margin = allowed_standard_lots * margin_per_lot
    sizing_label = f"{allowed_standard_lots:.2f} Standard Lots"

p_dec = 1 if is_crypto else (3 if is_jpy else 5)
price_fmt = f"{latest['Close']:.{p_dec}f}"
in_possession = bool(latest['Close'] > latest['Midfield_200EMA'])
active_buy_signal = bool(latest['Striker_Buy'])
active_sell_signal = bool(latest['Striker_Sell'])

st.subheader(f"Tactical Pitch: {selected_label} [{timeframe}]")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Live Price", price_fmt)
c2.metric("Possession", "ATTACKING" if in_possession else "DEFENDING", delta="Above 200 EMA" if in_possession else "-Below 200 EMA")
c3.metric("Defensive Stop", f"{stop_metric:.1f} {metric_label}", f"Target: +{stop_metric * 2:.1f} (1:2)")
c4.metric("Strict Sizing (OANDA)", sizing_label, f"Margin: ${required_margin:,.0f} ({int(1/margin_rate)}:1)")

# 8. Active Directive Box
if active_buy_signal and session_ok:
    sl_price = latest['Close'] - stop_distance_price
    tp_price = latest['Close'] + (stop_distance_price * 2.0)
    st.success(f"""
    ### 🟢 ACTIVE DIRECTIVE: BUY / LONG SIGNAL
    * **Order Type:** Market Buy
    * **Entry Price:** `{latest['Close']:.{p_dec}f}`
    * **Stop Loss (SL):** `{sl_price:.{p_dec}f}` (-{stop_metric:.1f} {metric_label})
    * **Take Profit (TP):** `{tp_price:.{p_dec}f}` (+{stop_metric * 2:.1f} {metric_label} | 1:2 R:R)
    * **Suggested Sizing:** `{sizing_label}`
    * **Tactical Confirmation:** Above 200 EMA + Retest 20 EMA + RSI primed ({latest['RSI']:.1f})
    """)
elif active_sell_signal and session_ok:
    sl_price = latest['Close'] + stop_distance_price
    tp_price = latest['Close'] - (stop_distance_price * 2.0)
    st.error(f"""
    ### 🔴 ACTIVE DIRECTIVE: SELL / SHORT SIGNAL
    * **Order Type:** Market Sell
    * **Entry Price:** `{latest['Close']:.{p_dec}f}`
    * **Stop Loss (SL):** `{sl_price:.{p_dec}f}` (+{stop_metric:.1f} {metric_label})
    * **Take Profit (TP):** `{tp_price:.{p_dec}f}` (-{stop_metric * 2:.1f} {metric_label} | 1:2 R:R)
    * **Suggested Sizing:** `{sizing_label}`
    * **Tactical Confirmation:** Below 200 EMA + Rally 20 EMA + RSI primed ({latest['RSI']:.1f})
    """)
elif (active_buy_signal or active_sell_signal) and not session_ok:
    st.warning(f"""
    ### ⏸️ DIRECTIVE PAUSED: OFF-HOURS / LOW LIQUIDITY
    * **Technical Setup Met:** Technical conditions fired on chart.
    * **Session Guard:** Blocked because **{selected_label}** trades during **{session_name}**.
    * **Reason:** Current time ({now_est.strftime('%H:%M EST')}) has minimal institutional liquidity. Spreads can widen and price will stall. Wait for active session open.
    """)
else:
    dist_to_ema20 = abs(latest['Close'] - latest['Tempo_20EMA']) / pip_scale
    st.info(f"""
    ### 🟡 TACTICAL DIRECTIVE: STAND BY (PATIENT POSSESSION)
    * **Status:** No trigger on active candle. Maintain position discipline.
    * **Tactical Read:** Retest at 20 EMA is {dist_to_ema20:.1f} {metric_label} away at `{latest['Tempo_20EMA']:.{p_dec}f}`. Current RSI: `{latest['RSI']:.1f}`.
    * **Session Status:** {session_name} ({'Active' if session_ok else 'Closed / Low Volume'}).
    """)

# =========================================================
# 9. 🤖 AI ASSISTANT MANAGER (TACTICAL DEBRIEF)
# =========================================================
st.write("---")
with st.expander("🤖 AI Assistant Manager (Tactical Debrief)", expanded=True):
    col_ai_btn, col_ai_status = st.columns([1, 4])
    run_ai = col_ai_btn.button("Generate Tactical Briefing")
    
    # Check for Gemini API Key in Secrets or Sidebar
    active_gemini_key = sidebar_gemini_key or st.secrets.get("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY"))

    if run_ai:
        if active_gemini_key:
            try:
                from google import genai
                client = genai.Client(api_key=active_gemini_key)
                
                signal_label = "BUY" if (active_buy_signal and session_ok) else ("SELL" if (active_sell_signal and session_ok) else ("OFF_HOURS" if (active_buy_signal or active_sell_signal) else "STANDBY"))
                
                prompt = f"""
                You are an elite quantitative football-themed FX risk manager and tactical analyst.
                Evaluate this live market state:
                - Instrument: {selected_label}
                - Timeframe: {timeframe}
                - Current Price: {latest['Close']:.{p_dec}f}
                - Midfield 200 EMA: {latest['Midfield_200EMA']:.{p_dec}f} ({'Above' if in_possession else 'Below'})
                - Tempo 20 EMA: {latest['Tempo_20EMA']:.{p_dec}f}
                - RSI: {latest['RSI']:.1f}
                - ATR Stop Distance: {stop_metric:.1f} {metric_label}
                - Session: {session_name} ({'Active' if session_ok else 'Illiquid'})
                - System Directive: {signal_label}

                Provide a sharp, 3-point tactical debrief:
                1. 🏟️ Pitch & Liquidity Condition (Does current market session support momentum?)
                2. ⚽ Tactical Setup Evaluation (Is this a high-quality strike or a false breakout/trap?)
                3. 🛡️ Defensive Command (Actionable directive on whether to execute, wait, or protect capital)
                Keep it disciplined, direct, and under 150 words.
                """
                with st.spinner("AI analyzing tactical pitch and liquidity depth..."):
                    res = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=prompt
                    )
                    st.markdown(res.text)
            except Exception as e:
                st.error(f"AI connection error: {str(e)}")
        else:
            # Algorithmic fallback if no API key is provided
            st.info("💡 *No Gemini API Key detected. Using local algorithmic tactical debrief (add key in sidebar or Streamlit Secrets for full LLM analysis):*")
            
            # Rule-based algorithmic evaluation
            spread_risk = "High spread penalty risk" if stop_metric < 12.0 else "Healthy buffer over spread"
            momentum_state = "Overbought" if latest['RSI'] > 65 else ("Oversold" if latest['RSI'] < 35 else "Balanced momentum")
            
            st.markdown(f"""
            * **🏟️ Liquidity & Pitch Status:** Market session is **{session_name}** ({'Open with institutional backing' if session_ok else 'Illiquid off-hours; high risk of stalled price'}).
            * **⚽ Momentum & Value:** RSI stands at **{latest['RSI']:.1f}** ({momentum_state}). Price is {'controlling macro midfield above the 200 EMA' if in_possession else 'pinned back under the defensive 200 EMA line'}.
            * **🛡️ Defensive Verdict:** Stop distance is **{stop_metric:.1f} {metric_label}** ({spread_risk}). Sizing strictly capped at **{sizing_label}**. Maintain adherence to the active directive box above.
            """)

# 10. Interactive Chart
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.75, 0.25])

fig.add_trace(go.Candlestick(
    x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
    name="Price"
), row=1, col=1)

fig.add_trace(go.Scatter(x=df.index, y=df['Midfield_200EMA'], line=dict(color='#eab308', width=2), name="Midfield (200 EMA)"), row=1, col=1)
fig.add_trace(go.Scatter(x=df.index, y=df['Tempo_20EMA'], line=dict(color='#38bdf8', width=1.5, dash='dot'), name="Tempo (20 EMA)"), row=1, col=1)

buy_plays = df[df['Striker_Buy']]
fig.add_trace(go.Scatter(
    x=buy_plays.index, y=buy_plays['Low'] * (0.999 if is_jpy or is_crypto else 0.9998),
    mode='markers', marker=dict(symbol='triangle-up', size=11, color='#22c55e'),
    name="Buy Entry"
), row=1, col=1)

sell_plays = df[df['Striker_Sell']]
fig.add_trace(go.Scatter(
    x=sell_plays.index, y=sell_plays['High'] * (1.001 if is_jpy or is_crypto else 1.0002),
    mode='markers', marker=dict(symbol='triangle-down', size=11, color='#ef4444'),
    name="Sell Entry"
), row=1, col=1)

fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], line=dict(color='#c084fc', width=1.5), name="RSI Stamina"), row=2, col=1)
fig.add_hline(y=70, line_dash="dash", line_color="#ef4444", row=2, col=1)
fig.add_hline(y=30, line_dash="dash", line_color="#22c55e", row=2, col=1)

fig.update_layout(
    template="plotly_dark",
    xaxis_rangeslider_visible=False,
    height=680,
    margin=dict(l=20, r=20, t=20, b=20),
    uirevision=pair
)

if not is_crypto:
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])

st.plotly_chart(fig, use_container_width=True, key=f"pitch_{pair}")
