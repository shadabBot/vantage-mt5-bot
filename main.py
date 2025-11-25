import MetaTrader5 as mt5
import pandas as pd
import time
from datetime import datetime
import pytz
from flask import Flask
import threading
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ==================== EMAIL NOTIFICATION ====================
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "sayedshadabali8421@gmail.com"
SENDER_PASSWORD = "eynj eiip itff nbga"  # Your Gmail App Password
RECIPIENTS = ["tasksubmission878@gmail.com", "eventshadab@gmail.com"]

def send_email_notification(subject: str, message: str) -> None:
    try:
        msg = MIMEMultipart()
        msg["From"] = SENDER_EMAIL
        msg["Subject"] = subject
        to_list = [a.strip() for a in RECIPIENTS if a.strip()]
        if not to_list:
            print("No recipients")
            return
        msg["To"] = ", ".join(to_list)
        msg.attach(MIMEText(message, "html"))
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, to_list, msg.as_string())
        print(f"Email sent: {subject}")
    except Exception as e:
        print(f"Email failed: {e}")

# ==================== CONFIG (FROM ENV VARS) ====================
LOGIN = int(os.getenv("MT5_LOGIN"))        # 11367607
PASSWORD = os.getenv("MT5_PASSWORD")       # Tccd@12345
SERVER = os.getenv("MT5_SERVER")           # VantageInternational-Demo

SYMBOL = "XAUUSD"
LOT_SIZE = 0.10
RISK_REWARD = 2.5
MAGIC = 987654
CHECK_INTERVAL = 1
LOOKBACK = 10000
MAX_TRADES_PER_DAY = 10
COOLDOWN_BARS = 10
EMA_FAST = 9
EMA_SLOW = 21
ATR_PERIOD = 14
SL_ATR_BUFFER = 0.1
MIN_BODY_PCT = 0.20
USE_BODY_FILTER = False
VOL_MULT = 1.05
USE_VOLUME_FILTER = False
PARTIAL_AT_1R_PCT = 40
USE_EMA_FILTER = True
USE_TRAILING_STOP = True
TRAILING_STOP_ATR = 1.0
ENTRY_TF = mt5.TIMEFRAME_M5
HTF_TF = mt5.TIMEFRAME_M30
SERVER_TZ = pytz.timezone("Europe/Moscow")  # UTC+3

# ==================== Flask Dashboard ====================
app = Flask(__name__)
@app.route('/')
def home():
    info = mt5.account_info()
    if not info:
        return "<h1>Connecting to Vantage MT5...</h1>"
    return f"""
    <h1>Vantage MT5 Bot Running 24/7</h1>
    <h2>Account: {info.login} | Balance: ${info.balance:,.2f}</h2>
    <p>Equity: ${info.equity:,.2f} | Profit: ${info.profit:,.2f}</p>
    <p>Symbol: {SYMBOL} | Lot: {LOT_SIZE} | Time: {datetime.now(SERVER_TZ)}</p>
    <hr><small>Render.com Free Tier • 24/7 Uptime</small>
    """
threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()

# ==================== MT5 CONNECT ====================
print("Initializing MT5...")
if not mt5.initialize(login=LOGIN, password=PASSWORD, server=SERVER):
    print("MT5 init failed:", mt5.last_error())
    quit()

info = mt5.account_info()
print(f"CONNECTED → Vantage Demo | Login: {info.login} | Balance: ${info.balance:,.2f}")

# ==================== UTILITIES (100% SAME AS LOCAL) ====================
def get_data(symbol, timeframe, n=LOOKBACK):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n)
    if rates is None or len(rates) == 0: return None
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s").dt.tz_localize("UTC").dt.tz_convert(SERVER_TZ)
    return df

def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()

def atr(df, period=14):
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift()).abs()
    lc = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.rolling(period).mean()

def vwap(df):
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    df['day'] = df['time'].dt.date
    df['pv'] = typical_price * df["tick_volume"]
    df['cum_pv'] = df.groupby('day')['pv'].cumsum()
    df['cum_vol'] = df.groupby('day')['tick_volume'].cumsum()
    return df['cum_pv'] / df['cum_vol']

def place_order(order_type, sl, tp):
    tick = mt5.symbol_info_tick(SYMBOL)
    if not tick: return False, None
    price = tick.ask if order_type == "BUY" else tick.bid
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": LOT_SIZE,
        "type": mt5.ORDER_TYPE_BUY if order_type == "BUY" else mt5.ORDER_TYPE_SELL,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 30,
        "magic": MAGIC,
        "comment": "VWAP + EMA Strategy",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK
    }
    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        subject = f"Trade Opened ({order_type}) on {SYMBOL}"
        message = f"""
        <h3>New Trade Opened</h3>
        <p><b>Type:</b> {order_type}</p>
        <p><b>Entry:</b> {price:.2f}</p>
        <p><b>SL:</b> {sl:.2f}</p>
        <p><b>TP:</b> {tp:.2f}</p>
        <p><b>Lot:</b> {LOT_SIZE}</p>
        <p><b>Time:</b> {datetime.now(SERVER_TZ)}</p>
        """
        send_email_notification(subject, message)
        return True, result.order
    else:
        print(f"Order failed: {result}")
        return False, None

def modify_sltp(ticket, new_sl, new_tp):
    request = {"action": mt5.TRADE_ACTION_SLTP, "position": ticket, "sl": new_sl, "tp": new_tp}
    result = mt5.order_send(request)
    return result.retcode == mt5.TRADE_RETCODE_DONE

def partial_close(ticket, pct, order_type):
    pos = mt5.positions_get(ticket=ticket)
    if not pos: return False, 0.0
    pos = pos[0]
    close_vol = pos.volume * (pct / 100)
    close_type = mt5.ORDER_TYPE_SELL if order_type == "BUY" else mt5.ORDER_TYPE_BUY
    price = mt5.symbol_info_tick(SYMBOL).bid if close_type == mt5.ORDER_TYPE_SELL else mt5.symbol_info_tick(SYMBOL).ask
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": close_vol,
        "type": close_type,
        "position": ticket,
        "price": price,
        "deviation": 30,
        "magic": MAGIC,
        "comment": "Partial Close",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK
    }
    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE and pct < 100:
        send_email_notification(f"Partial Close {pct}%", f"Closed {close_vol:.2f} lots at {price:.2f}")
    return result.retcode == mt5.TRADE_RETCODE_DONE, pos.profit

# ==================== STRATEGY (100% IDENTICAL) ====================
trades_today = 0
last_trade_day = None
cooldown_bars = 0
last_bar_time = None
last_entry_risk = None
be_moved = False
partial_closed = False
current_ticket = None
last_signal = None

print("Starting VWAP + EMA Strategy Bot on Vantage Demo (24/7 on Render.com)")

while True:
    ltf_df = get_data(SYMBOL, ENTRY_TF)
    htf_df = get_data(SYMBOL, HTF_TF, LOOKBACK // 6)
    if ltf_df is None or htf_df is None or len(ltf_df) < 50:
        time.sleep(CHECK_INTERVAL)
        continue

    curr_time = ltf_df["time"].iloc[-1]
    system_time = datetime.now(SERVER_TZ)

    # === POSITION MONITORING (SL/TP HIT) ===
    if current_ticket:
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick and (pos := mt5.positions_get(ticket=current_ticket)):
            pos = pos[0]
            price = tick.bid if last_signal == "BUY" else tick.ask
            if (last_signal == "BUY" and price <= pos.sl) or (last_signal == "SELL" and price >= pos.sl) or \
               (last_signal == "BUY" and price >= pos.tp) or (last_signal == "SELL" and price <= pos.tp):
                reason = "STOP LOSS" if (price <= pos.sl if last_signal == "BUY" else price >= pos.sl) else "TAKE PROFIT"
                partial_close(current_ticket, 100, last_signal)
                hist = mt5.history_deals_get(position=current_ticket)
                profit = hist[-1].profit if hist else pos.profit
                send_email_notification(f"{reason} HIT", f"P&L: {profit:+.2f} | Price: {price:.2f}")
                current_ticket = last_signal = last_entry_risk = None
                be_moved = partial_closed = False

    if last_bar_time == curr_time:
        time.sleep(CHECK_INTERVAL)
        continue
    last_bar_time = curr_time

    if last_trade_day != curr_time.date():
        trades_today = 0
        last_trade_day = curr_time.date()
        cooldown_bars = 0

    # Indicators
    ltf_df["ema_fast"] = ema(ltf_df["close"], EMA_FAST)
    ltf_df["ema_slow"] = ema(ltf_df["close"], EMA_SLOW)
    ltf_df["atr"] = atr(ltf_df, ATR_PERIOD)
    ltf_df["vwap"] = vwap(ltf_df)

    close = ltf_df["close"].iloc[-1]
    open_ = ltf_df["open"].iloc[-1]
    high = ltf_df["high"].iloc[-1]
    low = ltf_df["low"].iloc[-1]
    vol = ltf_df["tick_volume"].iloc[-1]
    vol_prev = ltf_df["tick_volume"].iloc[-2]

    body_pct = abs(close - open_) / max(high - low, 0.00001)
    bull = close > open_ and (body_pct >= MIN_BODY_PCT if USE_BODY_FILTER else True)
    bear = close < open_ and (body_pct >= MIN_BODY_PCT if USE_BODY_FILTER else True)
    vol_ok = True if not USE_VOLUME_FILTER else vol >= vol_prev * VOL_MULT
    trend_up = (not USE_EMA_FILTER) or (ltf_df.ema_fast.iloc[-1] > ltf_df.ema_slow.iloc[-1] and close > ltf_df.vwap.iloc[-1])
    trend_down = (not USE_EMA_FILTER) or (ltf_df.ema_fast.iloc[-1] < ltf_df.ema_slow.iloc[-1] and close < ltf_df.vwap.iloc[-1])
    htf_bull = htf_df.close.iloc[-1] > htf_df.open.iloc[-1]

    atr_val = ltf_df.atr.iloc[-1]
    sl_long = htf_df.low.iloc[-2] - atr_val * SL_ATR_BUFFER
    tp_long = close + (close - sl_long) * RISK_REWARD
    sl_short = htf_df.high.iloc[-2] + atr_val * SL_ATR_BUFFER
    tp_short = close - (sl_short - close) * RISK_REWARD

    can_enter = cooldown_bars == 0 and trades_today < MAX_TRADES_PER_DAY

    # Entry
    if can_enter and bull and htf_bull and trend_up and vol_ok and not current_ticket:
        success, ticket = place_order("BUY", sl_long, tp_long)
        if success:
            current_ticket = ticket
            last_signal = "BUY"
            last_entry_risk = close - sl_long
            trades_today += 1
            cooldown_bars = COOLDOWN_BARS

    elif can_enter and bear and not htf_bull and trend_down and vol_ok and not current_ticket:
        success, ticket = place_order("SELL", sl_short, tp_short)
        if success:
            current_ticket = ticket
            last_signal = "SELL"
            last_entry_risk = sl_short - close
            trades_today += 1
            cooldown_bars = COOLDOWN_BARS

    # Management
    if current_ticket and last_entry_risk and (pos := mt5.positions_get(ticket=current_ticket)):
        pos = pos[0]
        # Partial at 1R
        if PARTIAL_AT_1R_PCT > 0 and not partial_closed:
            if (last_signal == "BUY" and high >= pos.price_open + last_entry_risk) or \
               (last_signal == "SELL" and low <= pos.price_open - last_entry_risk):
                partial_close(current_ticket, PARTIAL_AT_1R_PCT, last_signal)
                partial_closed = True
        # Breakeven
        if not be_moved and ((last_signal == "BUY" and close > open_ and ltf_df.close.iloc[-2] > ltf_df.open.iloc[-2]) or
                             (last_signal == "SELL" and close < open_ and ltf_df.close.iloc[-2] < ltf_df.open.iloc[-2])):
            modify_sltp(current_ticket, pos.price_open, pos.tp)
            be_moved = True
        # Trailing
        if USE_TRAILING_STOP:
            if last_signal == "BUY":
                new_sl = max(pos.sl, high - atr_val * TRAILING_STOP_ATR)
                if new_sl > pos.sl:
                    modify_sltp(current_ticket, new_sl, pos.tp)
            else:
                new_sl = min(pos.sl, low + atr_val * TRAILING_STOP_ATR)
                if new_sl < pos.sl:
                    modify_sltp(current_ticket, new_sl, pos.tp)

    if cooldown_bars > 0:
        cooldown_bars -= 1
    time.sleep(CHECK_INTERVAL)