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

SYMBOL = 'BTCUSDT'
BUY_AMOUNT_USD = 20.0
TAKER_FEE_PERCENT = 0.001
MIN_PROFIT_USD = 0.001
JSON_FILE = 'sh.json'
MAX_OPEN_POSITIONS = 7
REBUY_WAIT_MINUTES = 30
SLEEP_SECONDS = 1
RUN_DURATION_HOURS = 6

PROXY_LIST = []
client = None

# ================= بروكسيات =================

def fetch_free_proxies():
    """جلب 100+ بروكسي مجاني"""
    proxies = []
    sources = [
        "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=elite",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
        "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    ]
    print("🔍 جاري جلب قائمة البروكسيات...")
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
    print(f"📊 إجمالي البروكسيات: {len(proxies)}")
    return proxies

def test_proxy(proxy_url):
    """اختبار سرعة البروكسي"""
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
    """اختيار أقوى بروكسي من 100 بروكسي"""
    global PROXY_LIST
    if not PROXY_LIST:
        PROXY_LIST = fetch_free_proxies()

    print(f"⚡ فحص {min(100, len(PROXY_LIST))} بروكسي...")
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
        print("❌ لا يوجد بروكسي يعمل! إعادة الجلب...")
        PROXY_LIST = []
        return None

    tested.sort(key=lambda x: x[1])
    best = tested[0]
    print(f"🏆 أفضل بروكسي: {best[0]} (سرعة: {best[1]:.2f}ث)")
    return {"http": best[0], "https": best[0]}

def init_client_with_retries():
    """تهيئة العميل مع 3 محاولات ثم إعادة جلب بروكسيات"""
    global client, PROXY_LIST

    while True:
        for attempt in range(1, 4):
            print(f"🔄 محاولة الاتصال #{attempt}/3...")
            proxy = get_best_proxy()
            if proxy is None:
                time.sleep(3)
                continue

            try:
                client = Client(API_KEY, API_SECRET, testnet=True, requests_params={"proxies": proxy})
                client.get_account()
                print(f"✅ اتصال ناجح! البروكسي: {proxy['http']}")
                return True
            except BinanceAPIException as e:
                print(f"⚠️ رفض البروكسي: {e}")
                if proxy['http'] in PROXY_LIST:
                    PROXY_LIST.remove(proxy['http'])
            except Exception as e:
                print(f"⚠️ خطأ: {e}")
                if proxy['http'] in PROXY_LIST:
                    PROXY_LIST.remove(proxy['http'])
            time.sleep(2)

        print("🔄 فشلت 3 محاولات. إعادة جلب بروكسيات جديدة...")
        PROXY_LIST = []
        time.sleep(5)

# ================= تليجرام =================

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
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
                subprocess.run(['git', '--work-tree=' + os.getcwd(), 'commit', '-m', 'تحديث عمليات التداول'], check=True)
                subprocess.run(['git', '--work-tree=' + os.getcwd(), 'push'], check=True)
            return True
        except Exception as e:
            print(f"⚠️ فشل Git: {e}")
            time.sleep(2)
    return False

# ================= حسابات =================

def calculate_sell_thresholds(buy_price, qty, buy_fee_usd):
    buy_cost = buy_price * qty
    estimated_sell_fee = buy_cost * TAKER_FEE_PERCENT
    total_fees = buy_fee_usd + estimated_sell_fee
    total_cost = buy_cost + total_fees
    break_even = total_cost / qty
    min_profit_price = (total_cost + MIN_PROFIT_USD) / qty

    return {
        "buy_cost": buy_cost,
        "buy_fee_usd": buy_fee_usd,
        "estimated_sell_fee": estimated_sell_fee,
        "total_fees": total_fees,
        "total_cost": total_cost,
        "break_even_price": break_even,
        "min_sell_price": min_profit_price
    }

# ================= عمليات السوق =================

def get_current_price():
    """جلب السعر الحالي"""
    try:
        return float(client.get_symbol_ticker(symbol=SYMBOL)['price'])
    except Exception as e:
        print(f"⚠️ فشل جلب السعر: {e}")
        return None

def execute_buy():
    """تنفيذ شراء بقيمة 20 USDT"""
    for attempt in range(1, 4):
        try:
            current_price = float(client.get_symbol_ticker(symbol=SYMBOL)['price'])
            order = client.order_market_buy(symbol=SYMBOL, quoteOrderQty=BUY_AMOUNT_USD)

            fills = order.get('fills', [])
            total_fee_usd = 0.0
            total_qty = 0.0
            total_cost = 0.0
            btc_fee = 0.0

            for fill in fills:
                fee = float(fill['commission'])
                fee_asset = fill['commissionAsset']
                qty = float(fill['qty'])
                price = float(fill['price'])
                total_qty += qty
                total_cost += qty * price

                if fee_asset == 'USDT':
                    total_fee_usd += fee
                elif fee_asset == 'BTC':
                    total_fee_usd += fee * current_price
                    btc_fee += fee
                elif fee_asset == 'BNB':
                    try:
                        bnb_price = float(client.get_symbol_ticker(symbol='BNBUSDT')['price'])
                        total_fee_usd += fee * bnb_price
                    except:
                        pass

            actual_price = total_cost / total_qty if total_qty > 0 else current_price
            sellable_qty = total_qty - btc_fee

            return order, total_fee_usd, total_qty, actual_price, total_cost, sellable_qty

        except Exception as e:
            print(f"⚠️ فشل الشراء (محاولة {attempt}): {e}")
            time.sleep(2)

    send_telegram_message(f"❌ <b>فشل الشراء بعد 3 محاولات!</b>\n{e}")
    return None, 0, 0, 0, 0, 0

def execute_sell(qty):
    """تنفيذ بيع"""
    for attempt in range(1, 4):
        try:
            info = client.get_symbol_info(SYMBOL)
            step = float([f for f in info['filters'] if f['filterType'] == 'LOT_SIZE'][0]['stepSize'])
            prec = len(str(step).split('.')[-1].rstrip('0')) if '.' in str(step) else 0
            qty = round(qty - (qty % step), prec)

            if qty <= 0:
                print("⚠️ كمية البيع صفر بعد التقريب")
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
                elif fee_asset == 'BTC':
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
            print(f"⚠️ فشل البيع (محاولة {attempt}): {e}")
            time.sleep(2)

    return None, 0, 0, 0

# ================= منطق التداول الرئيسي =================

def count_open_positions(history):
    """عدد العمليات المفتوحة (معلقة)"""
    return sum(1 for op in history.values() if isinstance(op, dict) and op.get('status') == "معلقة - جاري الانتظار")

def create_buy_operation():
    """إنشاء عملية شراء جديدة وحفظها"""
    order, fee, qty, actual_price, total_cost, sellable_qty = execute_buy()

    if order is None or qty <= 0:
        print("❌ فشل إنشاء عملية شراء")
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
        "buy_amount_usd": BUY_AMOUNT_USD,
        "buy_fee_usd": round(fee, 4),
        "total_cost": round(calc['total_cost'], 4),
        "break_even_price": round(calc['break_even_price'], 2),
        "min_sell_price": round(calc['min_sell_price'], 2),
        "sell_details": {}
    }

    history = load_history()
    history[op_id] = buy_data
    save_history(history)
    git_commit_and_push()

    msg = (
        f"✅ <b>عملية شراء جديدة!</b>\n\n"
        f"🆔 المعرف: <code>{op_id}</code>\n"
        f"💰 سعر الشراء: <code>{actual_price:.2f}</code>\n"
        f"📊 الكمية: <code>{qty:.6f} BTC</code>\n"
        f"📉 الكمية الصافية: <code>{sellable_qty:.6f} BTC</code>\n"
        f"💵 التكلفة: <code>{calc['total_cost']:.2f}</code>\n"
        f"⚖️ التعادل: <code>{calc['break_even_price']:.2f}</code>\n"
        f"🎯 البيع عند: <code>{calc['min_sell_price']:.2f}</code>"
    )
    send_telegram_message(msg)

    print(f"✅ تم إنشاء عملية شراء: {op_id} @ {actual_price:.2f}")
    return op_id

def check_and_sell_all(history, current_price):
    """فحص جميع العمليات المفتوحة والبيع إذا تحقق الشرط"""
    sold_any = False

    for op_id in list(history.keys()):
        pos = history[op_id]

        if not isinstance(pos, dict) or pos.get('status') != "معلقة - جاري الانتظار":
            continue

        buy_price = pos['buy_price']
        qty = pos.get('sellable_qty', pos['qty'])
        min_sell = pos['min_sell_price']
        total_cost = pos['total_cost']
        buy_fee = pos['buy_fee_usd']

        print(f"🔍 [{op_id}] شراء@{buy_price:.2f} | حالي@{current_price:.2f} | هدف@{min_sell:.2f}")

        if current_price >= min_sell:
            print(f"🎯 [{op_id}] تحقق شرط البيع! جاري البيع...")

            order, received, sell_fee, sell_price = execute_sell(qty)

            if order:
                actual_profit = received - total_cost - sell_fee
                sold_any = True

                pos['status'] = "تم البيع"
                pos['sell_details'] = {
                    "sell_id": f"sell_{uuid.uuid4().hex[:8]}",
                    "sell_price": round(sell_price, 2),
                    "received_usd": round(received, 4),
                    "sell_fee_usd": round(sell_fee, 4),
                    "profit_usd": round(actual_profit, 4),
                    "profit_percent": round((actual_profit / total_cost) * 100, 3),
                    "sell_date": datetime.utcnow().date().isoformat(),
                    "sell_time": datetime.utcnow().time().isoformat()
                }

                msg = (
                    f"✅ <b>تم البيع بربح!</b>\n\n"
                    f"🆔 العملية: <code>{op_id}</code>\n"
                    f"💰 شراء: <code>{buy_price:.2f}</code>\n"
                    f"💵 بيع: <code>{sell_price:.2f}</code>\n"
                    f"📊 كمية: <code>{qty:.6f} BTC</code>\n"
                    f"💸 تكلفة: <code>{total_cost:.2f}</code>\n"
                    f"💵 عائد: <code>{received:.2f}</code>\n"
                    f"📉 رسوم: <code>{(buy_fee + sell_fee):.4f}</code>\n"
                    f"💚 <b>ربح: {actual_profit:.4f} USDT</b>\n"
                    f"📈 نسبة: <code>{(actual_profit/total_cost)*100:.2f}%</code>"
                )
                send_telegram_message(msg)
                print(f"✅ تم بيع {op_id} بربح {actual_profit:.4f} USDT")
            else:
                print(f"❌ فشل بيع {op_id}")

    return sold_any, history

def check_rebuy(history, current_price):
    """فحص إعادة الشراء بعد 30 دقيقة"""
    rebuy_needed = False

    for op_id, pos in history.items():
        if not isinstance(pos, dict) or pos.get('status') != "معلقة - جاري الانتظار":
            continue

        buy_time_str = pos.get('buy_time')
        if not buy_time_str:
            continue

        buy_time = datetime.fromisoformat(buy_time_str)
        elapsed = datetime.utcnow() - buy_time

        if elapsed >= timedelta(minutes=REBUY_WAIT_MINUTES):
            buy_price = pos['buy_price']

            if current_price < buy_price:
                print(f"⏰ [{op_id}] مر {REBUY_WAIT_MINUTES} دقيقة والسعر أقل! إعادة شراء...")
                rebuy_needed = True
                break
            else:
                print(f"⏰ [{op_id}] مر {REBUY_WAIT_MINUTES} دقيقة لكن السعر أعلى من الشراء، انتظار...")

    return rebuy_needed

# ================= الدالة الرئيسية =================

def main():
    if not API_KEY or not API_SECRET:
        print("❌ لا توجد مفاتيح API!")
        return

    print("🚀 بدء البوت الجديد على Testnet...")
    init_client_with_retries()

    # حساب وقت الانتهاء (6 ساعات)
    start_time = time.time()
    end_time = start_time + (RUN_DURATION_HOURS * 3600)

    print(f"⏱ مدة التشغيل: {RUN_DURATION_HOURS} ساعات")
    print(f"🕐 البدء: {datetime.utcnow().strftime('%H:%M:%S')}")
    print(f"🕐 الانتهاء: {datetime.utcfromtimestamp(end_time).strftime('%H:%M:%S')}")

    # شراء أولي مباشر
    print("💰 جاري الشراء الأولي...")
    create_buy_operation()

    send_telegram_message(
        f"🚀 <b>البوت الجديد يعمل!</b>\n"
        f"⏱ مدة التشغيل: {RUN_DURATION_HOURS} ساعات\n"
        f"🕐 البدء: {datetime.utcnow().strftime('%H:%M:%S')} UTC\n"
        f"🕐 الانتهاء: {datetime.utcfromtimestamp(end_time).strftime('%H:%M:%S')} UTC\n"
        f"⏱ مراقبة كل {SLEEP_SECONDS} ثانية\n"
        f"📊 الحد الأقصى: {MAX_OPEN_POSITIONS} عمليات\n"
        f"⏰ إعادة شراء بعد {REBUY_WAIT_MINUTES} دقيقة"
    )

    while time.time() < end_time:
        loop_start = time.time()
        remaining = end_time - time.time()
        remaining_min = remaining / 60

        try:
            history = load_history()
            current_price = get_current_price()

            if current_price is None:
                print("⏳ فشل جلب السعر، إعادة المحاولة...")
                time.sleep(5)
                continue

            print(f"📊 السعر: {current_price:.2f} | متبقي: {remaining_min:.0f} دقيقة")

            # 1. فحص البيع لجميع العمليات المفتوحة
            sold, history = check_and_sell_all(history, current_price)
            if sold:
                save_history(history)
                git_commit_and_push()
                history = load_history()

            # 2. عدد العمليات المفتوحة
            open_count = count_open_positions(history)
            print(f"📊 عمليات مفتوحة: {open_count}/{MAX_OPEN_POSITIONS}")

            # 3. إذا باع وصار فيه مكان → شراء جديدة
            if open_count < MAX_OPEN_POSITIONS:
                needs_rebuy = check_rebuy(history, current_price)

                if needs_rebuy or open_count == 0:
                    print(f"💰 فتح عملية شراء جديدة...")
                    create_buy_operation()

            else:
                print(f"⏳ الحد الأقصى ({MAX_OPEN_POSITIONS}) ممتلئ. انتظار بيع...")

        except Exception as e:
            error_str = str(e)
            print(f"⚠️ خطأ: {error_str[:200]}")
            if any(k in error_str.lower() for k in ["connection", "proxy", "read", "timeout", "api"]):
                print("🔄 إعادة تهيئة الاتصال...")
                init_client_with_retries()

        elapsed = time.time() - loop_start
        sleep_time = max(0, SLEEP_SECONDS - elapsed)
        time.sleep(sleep_time)

    print("🛑 انتهت الـ 6 ساعات!")
    send_telegram_message("🛑 <b>انتهت دورة التشغيل (6 ساعات)!</b>")

if __name__ == "__main__":
    main()

