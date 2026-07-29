import os
import time
import json
import uuid
import requests
import subprocess
import concurrent.futures
from datetime import datetime, timedelta
from dataclasses import dataclass
from binance.client import Client
from binance.exceptions import BinanceAPIException
import numpy as np  # للحسابات الإحصائية (SMA)

# ==========================================
# CONFIGURATION
# ==========================================

@dataclass
class Config:
    api_key: str = 'dmyc2X0llvZ1A1zGAy9wfkqJHqZC20Uv04iYwBmOrnBMLJlnH7SZOsPt4eYGYnoJ'
    secret: str = 'uVax1wfQo0Ns1XIhGgsW4j2yjgB9VPlQWYzWvt1sAeg640WpGRCSqFMPvVyNtu6S'
    telegram_token: str = '8777604170:AAGVQWj7KtRZWKjZQ0BuyIZCHJ3FCmFgQP4'
    telegram_chat_id: str = '6390985342'

cfg = Config()

API_KEY = cfg.api_key
API_SECRET = cfg.secret
TELEGRAM_TOKEN = cfg.telegram_token
TELEGRAM_CHAT_ID = cfg.telegram_chat_id

SYMBOL = 'SOLUSDT'

# ===== استراتيجية DCA متعددة المراحل =====
BUY_AMOUNT_USD = 5.0          # المبلغ الأساسي لكل شراء
MAX_OPEN_POSITIONS = 3        # عدد مراحل الشراء (يتم تعديله ديناميكياً)
DCA_STEPS = [0.0, -1.5, -3.0] # نسب الانخفاض عن آخر سعر شراء (بالنسبة المئوية)
DCA_MULTIPLIERS = [1.0, 1.5, 2.0] # مضاعفات المبلغ لكل مرحلة (1x, 1.5x, 2x)

# ===== إعدادات البيع =====
PROFIT_TARGET_PERCENT = 0.8   # هدف الربح الديناميكي (0.8%)
TRAILING_STOP_PERCENT = 2.0   # وقف الخسارة المتحرك (2% من أعلى سعر)
MIN_PROFIT_USD = 0.05         # هامش أمان صغير جداً (يُستخدم كحد أدنى)

# ===== إعدادات المؤشرات =====
SMA_PERIOD = 20               # فترة المتوسط المتحرك البسيط
RSI_PERIOD = 14               # فترة مؤشر القوة النسبية
RSI_OVERSOLD = 40             # منطقة تشبع بيعي (شراء إذا كان أقل)

# ===== إعدادات عامة =====
JSON_FILE = 'sh.json'
REBUY_WAIT_MINUTES = 5        # انتظار بين مراحل الشراء
SLEEP_SECONDS = 2
RUN_DURATION_HOURS = 6

PROXY_LIST = []
client = None

# ================= بروكسيات (محسّنة) =================

def fetch_free_proxies():
    proxies = []
    sources = [
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=elite",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
        "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    ]
    print("[PROXY] جَلْبُ قَائِمَةِ البُرُوكْسِي...")
    for source in sources:
        try:
            response = requests.get(source, timeout=15)
            if response.status_code == 200:
                lines = response.text.strip().split('\n')
                for line in lines:
                    line = line.strip()
                    if ':' in line and len(line) < 30:
                        proxy_url = f"http://{line}"
                        if proxy_url not in proxies:
                            proxies.append(proxy_url)
        except Exception:
            pass
    proxies = list(dict.fromkeys(proxies))
    print("[PROXY] إِجْمَالِيُّ مَا تَمَّ جَلْبُهُ: %d" % len(proxies))
    return proxies

def test_proxy(proxy_url):
    try:
        proxies = {"http": proxy_url, "https": proxy_url}
        start = time.time()
        response = requests.get("https://testnet.binance.vision/api/v3/ping", proxies=proxies, timeout=3)
        if response.status_code == 200:
            latency = time.time() - start
            return latency
        return None
    except:
        return None

def get_best_proxy():
    global PROXY_LIST
    if not PROXY_LIST:
        PROXY_LIST = fetch_free_proxies()

    print("[PROXY] فَحْصُ %d بُرُوكْسِي..." % min(100, len(PROXY_LIST)))
    tested = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
        futures = {executor.submit(test_proxy, p): p for p in PROXY_LIST[:100]}
        for future in concurrent.futures.as_completed(futures):
            proxy = futures[future]
            latency = future.result()
            if latency:
                tested.append((proxy, latency))
            else:
                if proxy in PROXY_LIST:
                    PROXY_LIST.remove(proxy)

    if not tested:
        print("[PROXY] لَا يُوجَدُ بُرُوكْسِي يَعْمَلُ! جَارِي إِعَادَةُ الجَلْبِ...")
        PROXY_LIST = []
        return None

    tested.sort(key=lambda x: x[1])
    best = tested[0]
    print("[PROXY] الأَفْضَلُ: %s (السُّرْعَةُ: %.2fs)" % (best[0], best[1]))
    return {"http": best[0], "https": best[0]}

def init_client_with_retries():
    global client, PROXY_LIST

    while True:
        for attempt in range(1, 4):
            print("[INIT] مُحَاوَلَةُ الاِتِّصَالِ %d/3..." % attempt)
            proxy = get_best_proxy()
            if proxy is None:
                time.sleep(3)
                continue

            try:
                client = Client(API_KEY, API_SECRET, testnet=True, requests_params={"proxies": proxy})
                client.get_account()
                print("[INIT] تَمَّ الاِتِّصَالُ! البُرُوكْسِي: %s" % proxy['http'])
                return True
            except BinanceAPIException as e:
                print("[INIT] تَمَّ رَفْضُ البُرُوكْسِي: %s" % e)
                if proxy['http'] in PROXY_LIST:
                    PROXY_LIST.remove(proxy['http'])
            except Exception as e:
                print("[INIT] خَطَأٌ: %s" % e)
                if proxy['http'] in PROXY_LIST:
                    PROXY_LIST.remove(proxy['http'])
            time.sleep(2)

        print("[INIT] فَشِلَتْ 3 مُحَاوَلَاتٍ. جَارِي إِعَادَةُ جَلْبِ البُرُوكْسِي...")
        PROXY_LIST = []
        time.sleep(5)

# ================= تليجرام (مع علامة "حساب تجريبي") =================

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    # إضافة علامة "حساب تجريبي" في أعلى كل رسالة
    full_message = "🧪 <b>حساب تجريبي - Testnet</b>\n" + message
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": full_message, "parse_mode": "HTML"}
    for attempt in range(1, 4):
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False

# ================= إدارة الملفات =================

def load_history():
    if os.path.exists(JSON_FILE):
        with open(JSON_FILE, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except:
                pass
    return {}

def save_history(history):
    with open(JSON_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=4, ensure_ascii=False)

def git_commit_and_push():
    for attempt in range(1, 4):
        try:
            subprocess.run(['git', '--work-tree=' + os.getcwd(), 'config', '--global', 'user.name', 'Bot'], check=True)
            subprocess.run(['git', '--work-tree=' + os.getcwd(), 'config', '--global', 'user.email', 'bot@bot.com'], check=True)
            subprocess.run(['git', '--work-tree=' + os.getcwd(), 'add', JSON_FILE], check=True)
            status = subprocess.run(['git', '--work-tree=' + os.getcwd(), 'diff', '--staged', '--quiet'])
            if status.returncode != 0:
                subprocess.run(['git', '--work-tree=' + os.getcwd(), 'commit', '-m', 'تَحْدِيثُ عَمَلِيَّاتِ التَّدَاوُلِ'], check=True)
                subprocess.run(['git', '--work-tree=' + os.getcwd(), 'push'], check=True)
            return True
        except Exception as e:
            print("[GIT] فَشِلَ الرَّفْعُ: %s" % e)
            time.sleep(2)
    return False

# ================= المؤشرات الفنية =================

def get_klines(limit=50):
    """جلب بيانات الشموع لحساب SMA و RSI"""
    try:
        klines = client.get_klines(symbol=SYMBOL, interval=Client.KLINE_INTERVAL_15MINUTE, limit=limit)
        closes = [float(k[4]) for k in klines]
        volumes = [float(k[5]) for k in klines]
        return closes, volumes
    except Exception as e:
        print("[INDICATOR] فَشَلَ جَلْبُ الشَّمُوعِ: %s" % e)
        return None, None

def calculate_sma(closes, period=SMA_PERIOD):
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period

def calculate_rsi(closes, period=RSI_PERIOD):
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0 for d in deltas]
    losses = [-d if d < 0 else 0 for d in deltas]
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def get_trading_signal(current_price):
    """إرجاع (signal, reason) حيث signal = 'buy' أو 'wait'"""
    closes, volumes = get_klines(50)
    if closes is None:
        return 'wait', "فشل جلب البيانات"

    sma = calculate_sma(closes)
    rsi = calculate_rsi(closes)

    # الشروط:
    # 1. السعر الحالي أقل من SMA (إشارة شراء)
    # 2. RSI أقل من 40 (منطقة تشبع بيعي)
    # 3. حجم التداول أعلى من متوسط آخر 10 شموع (تأكيد)
    avg_volume = np.mean(volumes[-10:]) if len(volumes) >= 10 else 0
    current_volume = volumes[-1] if volumes else 0

    buy_signals = []
    if sma is not None and current_price < sma:
        buy_signals.append(f"SMA ({sma:.2f})")
    if rsi is not None and rsi < RSI_OVERSOLD:
        buy_signals.append(f"RSI ({rsi:.1f})")
    if current_volume > avg_volume * 0.8:  # حجم أعلى من 80% من المتوسط
        buy_signals.append(f"Volume ({current_volume:.0f} > {avg_volume*0.8:.0f})")

    if len(buy_signals) >= 2:  # على الأقل شرطان متحققان
        return 'buy', f"إشارة شراء: {', '.join(buy_signals)}"
    else:
        return 'wait', f"انتظار: SMA={sma:.2f if sma else 'None'}, RSI={rsi:.1f if rsi else 'None'}"

# ================= حسابات =================

def calculate_sell_thresholds(buy_price, qty, buy_fee_usd):
    buy_cost = buy_price * qty
    # رسوم البيع المقدرة (0.1%)
    estimated_sell_fee = buy_cost * 0.001
    total_fees = buy_fee_usd + estimated_sell_fee
    total_cost = buy_cost + total_fees

    # هدف الربح الديناميكي (نسبة مئوية)
    profit_target = buy_cost * (PROFIT_TARGET_PERCENT / 100)
    min_profit_price = (total_cost + max(profit_target, MIN_PROFIT_USD)) / qty

    # سعر التعادل (بدون ربح)
    break_even = total_cost / qty

    # وقف الخسارة المتحرك: سيتم حسابه لاحقاً بناءً على أعلى سعر بعد الشراء
    trailing_stop_price = buy_price * (1 - TRAILING_STOP_PERCENT / 100)

    return {
        "buy_cost": buy_cost,
        "buy_fee_usd": buy_fee_usd,
        "estimated_sell_fee": estimated_sell_fee,
        "total_fees": total_fees,
        "total_cost": total_cost,
        "break_even_price": break_even,
        "min_sell_price": min_profit_price,
        "trailing_stop_price": trailing_stop_price
    }

# ================= عمليات السوق =================

def get_current_price():
    try:
        ticker = float(client.get_symbol_ticker(symbol=SYMBOL)['price'])
        print("[PRICE] السِّعْرُ الحَالِيُّ: %.2f" % ticker)
        return ticker
    except Exception as e:
        print("[PRICE] فَشَلٌ فِي جَلْبِ السِّعْرِ: %s" % e)
        return None

def get_usdt_balance():
    """جلب رصيد USDT في الحساب التجريبي"""
    try:
        account = client.get_account()
        for asset in account['balances']:
            if asset['asset'] == 'USDT':
                return float(asset['free'])
        return 0.0
    except Exception as e:
        print("[BALANCE] فَشَلَ جَلْبُ الرَّصِيدِ: %s" % e)
        return 0.0

def execute_buy(amount_usd=None):
    if amount_usd is None:
        amount_usd = BUY_AMOUNT_USD

    for attempt in range(1, 4):
        try:
            current_price = float(client.get_symbol_ticker(symbol=SYMBOL)['price'])
            order = client.order_market_buy(symbol=SYMBOL, quoteOrderQty=amount_usd)

            fills = order.get('fills', [])
            total_fee_usd = 0.0
            total_qty = 0.0
            total_cost = 0.0
            asset_fee = 0.0

            for fill in fills:
                fee = float(fill['commission'])
                fee_asset = fill['commissionAsset']
                qty = float(fill['qty'])
                price = float(fill['price'])
                total_qty += qty
                total_cost += qty * price

                if fee_asset == 'USDT':
                    total_fee_usd += fee
                elif fee_asset == SYMBOL.replace('USDT', ''):
                    total_fee_usd += fee * current_price
                    asset_fee += fee
                elif fee_asset == 'BNB':
                    try:
                        bnb_price = float(client.get_symbol_ticker(symbol='BNBUSDT')['price'])
                        total_fee_usd += fee * bnb_price
                    except:
                        pass

            actual_price = total_cost / total_qty if total_qty > 0 else current_price
            sellable_qty = total_qty - asset_fee

            return order, total_fee_usd, total_qty, actual_price, total_cost, sellable_qty

        except Exception as e:
            print("[BUY] فَشَلَتْ المُحَاوَلَةُ %d: %s" % (attempt, e))
            time.sleep(2)

    send_telegram_message("[ERROR] فشل الشراء بعد 3 محاولات!")
    return None, 0, 0, 0, 0, 0

def execute_sell(qty):
    for attempt in range(1, 4):
        try:
            info = client.get_symbol_info(SYMBOL)
            step = float([f for f in info['filters'] if f['filterType'] == 'LOT_SIZE'][0]['stepSize'])
            prec = len(str(step).split('.')[-1].rstrip('0')) if '.' in str(step) else 0
            qty = round(qty - (qty % step), prec)

            if qty <= 0:
                print("[SELL] الكَمِّيَّةُ صِفْرٌ بَعْدَ التَّقْرِيبِ")
                return None, 0, 0, 0

            order = client.order_market_sell(symbol=SYMBOL, quantity=qty)
            fills = order.get('fills', [])
            total_fee = 0.0
            total_received = 0.0

            for fill in fills:
                fee = float(fill['commission'])
                fee_asset = fill['commissionAsset']
                qty_f = float(fill['qty'])
                price = float(fill['price'])
                total_received += qty_f * price

                if fee_asset == 'USDT':
                    total_fee += fee
                elif fee_asset == SYMBOL.replace('USDT', ''):
                    total_fee += fee * price
                elif fee_asset == 'BNB':
                    try:
                        bnb_price = float(client.get_symbol_ticker(symbol='BNBUSDT')['price'])
                        total_fee += fee * bnb_price
                    except:
                        pass

            actual_price = total_received / qty if qty > 0 else 0
            return order, total_received, total_fee, actual_price

        except Exception as e:
            print("[SELL] فَشَلَتْ المُحَاوَلَةُ %d: %s" % (attempt, e))
            time.sleep(2)

    return None, 0, 0, 0

# ================= منطق التداول الرئيسي (DCA + Trailing Stop) =================

def count_open_positions(history):
    return sum(1 for op in history.values() if isinstance(op, dict) and op.get('status') == "معلقة - جاري الانتظار")

def get_open_positions(history):
    return {op_id: op for op_id, op in history.items() 
            if isinstance(op, dict) and op.get('status') == "معلقة - جاري الانتظار"}

def get_open_positions_sorted(history):
    """ترتيب الصفقات المفتوحة حسب وقت الشراء (الأقدم أولاً)"""
    open_ops = get_open_positions(history)
    return sorted(open_ops.items(), key=lambda x: x[1].get('buy_time', ''))

def get_last_buy_price(history):
    open_ops = get_open_positions(history)
    if not open_ops:
        return None
    last = max(open_ops.items(), key=lambda x: x[1].get('buy_time', ''))
    return last[1]['buy_price']

def get_last_buy_time(history):
    open_ops = get_open_positions(history)
    if not open_ops:
        return None
    times = [datetime.fromisoformat(op['buy_time']) for op in open_ops.values() if op.get('buy_time')]
    return max(times) if times else None

def get_last_sell_time(history):
    sell_times = []
    for op in history.values():
        if isinstance(op, dict) and op.get('status') == "تم البيع" and 'sell_details' in op:
            sd = op['sell_details']
            if 'sell_date' in sd and 'sell_time' in sd:
                try:
                    dt_str = f"{sd['sell_date']}T{sd['sell_time']}"
                    sell_times.append(datetime.fromisoformat(dt_str))
                except:
                    pass
    return max(sell_times) if sell_times else None

def get_absolute_last_buy_price(history):
    times = []
    for op in history.values():
        if isinstance(op, dict) and 'buy_time' in op and 'buy_price' in op:
            times.append((datetime.fromisoformat(op['buy_time']), op['buy_price']))
    if not times:
        return None
    times.sort(key=lambda x: x[0])
    return times[-1][1]

def create_buy_operation(amount_usd=None):
    if amount_usd is None:
        amount_usd = BUY_AMOUNT_USD

    order, fee, qty, actual_price, total_cost, sellable_qty = execute_buy(amount_usd)

    if order is None or qty <= 0:
        print("[BUY] فَشَلَ إِنْشَاءُ عَمَلِيَّةِ الشِّرَاءِ")
        return None

    calc = calculate_sell_thresholds(actual_price, qty, fee)
    op_id = f"buy_{uuid.uuid4().hex[:8]}"
    now = datetime.utcnow()

    buy_data = {
        "type": "buy",
        "status": "معلقة - جاري الانتظار",
        "date": now.date().isoformat(),
        "time": now.time().isoformat(),
        "buy_time": now.isoformat(),
        "buy_price": round(actual_price, 2),
        "qty": round(qty, 8),
        "sellable_qty": round(sellable_qty, 8),
        "buy_amount_usd": round(amount_usd, 2),
        "buy_fee_usd": round(fee, 4),
        "buy_cost": round(calc['buy_cost'], 4),
        "total_cost": round(calc['total_cost'], 4),
        "break_even_price": round(calc['break_even_price'], 2),
        "min_sell_price": round(calc['min_sell_price'], 2),
        "trailing_stop_price": round(calc['trailing_stop_price'], 2),
        "highest_price": round(actual_price, 2),  # لتحديث أعلى سعر
        "sell_details": {}
    }

    history = load_history()
    history[op_id] = buy_data
    save_history(history)
    git_commit_and_push()

    balance = get_usdt_balance()
    msg = (
        "✅ <b>تَمَّ الشِّرَاءُ!</b>\n"
        f"المعرف: {op_id}\n"
        f"السعر: {actual_price:.2f}\n"
        f"سعر التعادل: {calc['break_even_price']:.2f}\n"
        f"هدف الربح: {calc['min_sell_price']:.2f} ({PROFIT_TARGET_PERCENT}%)\n"
        f"وقف الخسارة المتحرك: {calc['trailing_stop_price']:.2f} (2% من السعر)\n"
        f"💳 <b>الرصيد المتبقي:</b> {balance:.2f} USDT"
    )
    send_telegram_message(msg)

    print("[BUY] تَمَّ الإِنْشَاءُ: %s @ %.2f (المبلغ: %.2f USDT)" % (op_id, actual_price, amount_usd))
    return op_id

def update_trailing_stop(history, current_price):
    """تحديث وقف الخسارة المتحرك لأعلى سعر جديد"""
    updated = False
    open_ops = get_open_positions(history)
    for op_id, pos in open_ops.items():
        highest = pos.get('highest_price', pos['buy_price'])
        if current_price > highest:
            new_highest = current_price
            new_stop = current_price * (1 - TRAILING_STOP_PERCENT / 100)
            history[op_id]['highest_price'] = round(new_highest, 2)
            history[op_id]['trailing_stop_price'] = round(new_stop, 2)
            updated = True
            print("[TRAILING] %s: أعلى سعر جديد %.2f، وقف جديد %.2f" % (op_id, new_highest, new_stop))
    return updated, history

def try_sell_all(history, current_price):
    open_positions = get_open_positions(history)
    if not open_positions:
        print("[SELL] لَا تُوجَدُ عَمَلِيَّاتٌ مَفْتُوحَةٌ لِلْبَيْعِ")
        return False, history

    # تحديث وقف الخسارة المتحرك
    updated, history = update_trailing_stop(history, current_price)
    if updated:
        save_history(history)
        git_commit_and_push()

    print("[SELL] جَارِي فَحْصُ %d عَمَلِيَّاتٍ مَفْتُوحَةٍ..." % len(open_positions))
    sold_any = False

    for op_id, pos in open_positions.items():
        buy_price = pos['buy_price']
        qty = pos.get('sellable_qty', pos['qty'])
        min_sell = pos['min_sell_price']
        trailing_stop = pos['trailing_stop_price']
        buy_cost = pos['buy_cost']
        buy_fee = pos['buy_fee_usd']

        print("[SELL_CHECK] %s | شِرَاء@%.2f | الحَالِيُّ@%.2f | الهَدَفُ@%.2f | الوقف@%.2f" % 
              (op_id, buy_price, current_price, min_sell, trailing_stop))

        # شرط البيع: 1) بلوغ هدف الربح  OR  2) تفعيل وقف الخسارة المتحرك
        sell_reason = None
        if current_price >= min_sell:
            sell_reason = "هدف الربح"
        elif current_price <= trailing_stop:
            sell_reason = "وقف الخسارة المتحرك"

        if sell_reason:
            print("[SELL] %s تَمَّ بُلُوغُ شَرْطِ البَيْعِ: %s" % (op_id, sell_reason))

            order, received, sell_fee, sell_price = execute_sell(qty)

            if order:
                actual_profit = received - buy_cost - buy_fee - sell_fee
                sold_any = True

                history[op_id]['status'] = "تم البيع"
                history[op_id]['sell_details'] = {
                    "sell_id": f"sell_{uuid.uuid4().hex[:8]}",
                    "sell_price": round(sell_price, 2),
                    "received_usd": round(received, 4),
                    "sell_fee_usd": round(sell_fee, 4),
                    "profit_usd": round(actual_profit, 4),
                    "profit_percent": round((actual_profit / (buy_cost + buy_fee)) * 100, 3),
                    "sell_reason": sell_reason,
                    "sell_date": datetime.utcnow().date().isoformat(),
                    "sell_time": datetime.utcnow().time().isoformat()
                }

                balance = get_usdt_balance()
                msg = (
                    "💰 <b>تَمَّ البَيْعُ بِنَجَاحٍ!</b>\n"
                    f"المعرف: {op_id}\n"
                    f"الشراء: {buy_price:.2f} | البيع: {sell_price:.2f}\n"
                    f"السبب: {sell_reason}\n"
                    f"الربح الصافي الفعلي: {actual_profit:.4f} USDT\n"
                    f"💳 <b>الرصيد المتبقي:</b> {balance:.2f} USDT"
                )
                send_telegram_message(msg)
                print("[SELL] تَمَّ البَيْعُ %s بِرِبْح=%.4f (%s)" % (op_id, actual_profit, sell_reason))
            else:
                print("[SELL] فَشَلَتْ عَمَلِيَّةُ بَيْعِ %s" % op_id)
        else:
            print("[SELL_CHECK] %s لَمْ يَحِنِ الوَقْتُ بَعْدُ" % op_id)

    return sold_any, history

def can_rebuy(history, current_price):
    """تحديد ما إذا كان يمكن إضافة مرحلة DCA جديدة"""
    open_ops = get_open_positions(history)
    num_steps = len(open_ops)

    if num_steps >= len(DCA_STEPS):
        print("[REBUY] تم الوصول إلى أقصى عدد من المراحل (%d)" % len(DCA_STEPS))
        return False, None

    # الحصول على آخر سعر شراء
    last_price = get_last_buy_price(history)
    if last_price is None:
        return False, None

    # النسبة المئوية للانخفاض المطلوب للمرحلة التالية
    required_drop = DCA_STEPS[num_steps]  # سالب (مثل -1.5)
    target_price = last_price * (1 + required_drop / 100)

    # الوقت المنقضي منذ آخر شراء
    last_time = get_last_buy_time(history)
    if last_time:
        elapsed = datetime.utcnow() - last_time
        if elapsed < timedelta(minutes=REBUY_WAIT_MINUTES):
            print("[REBUY] انتظار %d دقائق بين المراحل (مضى %.1f)" % (REBUY_WAIT_MINUTES, elapsed.total_seconds()/60))
            return False, None

    # التحقق من السعر
    if current_price <= target_price:
        # المبلغ المضاعف للمرحلة الحالية
        amount_multiplier = DCA_MULTIPLIERS[num_steps] if num_steps < len(DCA_MULTIPLIERS) else 1.0
        buy_amount = BUY_AMOUNT_USD * amount_multiplier
        print("[REBUY] شراء المرحلة %d: السعر %.2f <= %.2f (انخفاض %.2f%%)، المبلغ: %.2f" % 
              (num_steps+1, current_price, target_price, required_drop, buy_amount))
        return True, buy_amount
    else:
        print("[REBUY] انتظار انخفاض إلى %.2f (حالياً %.2f)" % (target_price, current_price))
        return False, None

# ================= الدالة الرئيسية =================

def main():
    if not API_KEY or not API_SECRET:
        print("[ERROR] لَا تُوجَدُ مَفَاتِيحُ API!")
        return

    print("[START] بَدْءُ تَشْغِيلِ البُوتِ (حساب تجريبي - Binance Testnet)...")
    init_client_with_retries()

    # جلب الرصيد الأولي وعرضه
    initial_balance = get_usdt_balance()
    send_telegram_message(f"🚀 <b>بدء تشغيل البوت التجريبي</b>\nرصيد USDT المبدئي: {initial_balance:.2f}")

    start_time = time.time()
    end_time = start_time + (RUN_DURATION_HOURS * 3600)

    history = load_history()
    open_count = count_open_positions(history)
    
    if open_count == 0:
        print("[START] لا توجد صفقات معلقة سابقة. سَيَبْدَأُ الفَحْصُ فِي الدَّوْرَةِ الرَّئِيسِيَّةِ...")
    else:
        print(f"[START] تم العثور على {open_count} صفقات معلقة سابقة. استئناف المراقبة فوراً...")

    while time.time() < end_time:
        loop_start = time.time()

        try:
            history = load_history()
            
            print("\n┌─────────────────────────────────────┐")
            
            current_price = get_current_price()
            if current_price is None:
                print("│ [LOOP] فَشَلٌ فِي جَلْبِ السِّعْرِ، جَارِي الإِعَادَةُ...")
                time.sleep(5)
                continue

            # ---- استخدام المؤشرات الفنية لتأكيد الشراء ----
            signal, reason = get_trading_signal(current_price)
            print("│ [SIGNAL] %s" % reason)

            open_count = count_open_positions(history)
            
            print("│ [خُطْوَةُ 1] فَحْصُ البَيْعِ لِلْعَمَلِيَّاتِ المَفْتُوحَةِ (%d)" % open_count)
            sold, history = try_sell_all(history, current_price)

            if sold:
                print("│ [النَّتِيجَةُ] تَمَّ البَيْعُ! حفظ التحديثات.")
                save_history(history)
                git_commit_and_push()
            else:
                print("│ [النَّتِيجَةُ] لَمْ يَبِعْ → فَحْصُ إِمْكَانِيَّةِ الشِّرَاءِ...")
                
                # التحقق من وجود صفقات مفتوحة أقل من الحد الأقصى
                if open_count < len(DCA_STEPS):
                    # التحقق من الإشارة الفنية قبل الشراء
                    if signal == 'buy' or open_count == 0:
                        # إذا كانت الإشارة شراء أو لا توجد صفقات (شراء أولي)
                        if open_count == 0:
                            # شراء أولي (بدون انتظار انخفاض)
                            print("│ [شِرَاءٌ] لا توجد صفقات، شراء أولي...")
                            create_buy_operation(BUY_AMOUNT_USD)
                        else:
                            # محاولة إضافة مرحلة DCA
                            can_buy, amount = can_rebuy(history, current_price)
                            if can_buy and amount is not None:
                                print("│ [شِرَاءٌ] إضافة مرحلة DCA...")
                                create_buy_operation(amount)
                            else:
                                print("│ [تَجَاوُزٌ] شُرُوطُ إِضَافَةِ مَرْحَلَةٍ لَمْ تَتَحَقَّقْ.")
                    else:
                        print("│ [تَجَاوُزٌ] الإشارة الفنية ليست شراء (انتظار).")
                else:
                    print("│ [تَحْذِيرٌ] تَمَّ بُلُوغُ الحَدِّ الأَقْصَى لِلصَّفَقَاتِ (%d)." % len(DCA_STEPS))

            print("└─────────────────────────────────────┘")

        except Exception as e:
            error_str = str(e)
            print("[ERROR] %s" % error_str[:200])
            if any(k in error_str.lower() for k in ["connection", "proxy", "read", "timeout", "api"]):
                init_client_with_retries()

        elapsed = time.time() - loop_start
        sleep_time = max(0, SLEEP_SECONDS - elapsed)
        time.sleep(sleep_time)

    print("[END] تَمَّ الاِنْتِهَاءُ مِنَ الدَّوْرَةِ زَمَنِيًّا!")
    final_balance = get_usdt_balance()
    send_telegram_message(f"⏹️ <b>إيقاف البوت التجريبي</b>\nالرصيد النهائي: {final_balance:.2f} USDT")

if __name__ == "__main__":
    main()
