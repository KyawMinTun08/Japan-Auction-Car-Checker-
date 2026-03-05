import asyncio
import os
import re
import logging
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ── Tesseract OCR (fallback) ─────────────────────────
# Railway: Add "tesseract-ocr" to Aptfile or Dockerfile:
#   RUN apt-get update && apt-get install -y tesseract-ocr
#   pip install pytesseract Pillow
try:
    import pytesseract
    from PIL import Image
    from io import BytesIO
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    print("Warning: pytesseract or Pillow not found. Tesseract OCR fallback disabled.")

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
TOKEN = os.environ.get('BOT_TOKEN', '')
SHEET_WEBHOOK = os.environ.get('SHEET_WEBHOOK', '')

# ── Chassis Prefix → Model Name Map ─────────────────
CHASSIS_PREFIX_MAP = {
    # Toyota
    "GRS200": "CROWN", "GRS201": "CROWN", "GRS202": "CROWN", "GRS210": "CROWN",
    "GWS204": "CROWN HYBRID",
    "ZGE20": "WISH", "ZGE22": "WISH", "ZGE25": "WISH",
    "GRX133": "MARK X",
    "MNH15": "ALPHARD", "ANH15": "ALPHARD", "ANH20": "ALPHARD",
    "ZRR75": "NOAH", "ZRR70": "NOAH",
    "KDH201": "HIACE VAN", "KDH200": "HIACE VAN", "TRH200": "HIACE VAN",
    "NCP165": "PROBOX VAN", "NCP160": "PROBOX VAN",
    "NCP59": "SUCCEED WAGON", "NCP58": "SUCCEED WAGON",
    "UZJ100": "LAND CRUISER", "HDJ101": "LAND CRUISER", "HZJ105": "LAND CRUISER",
    "USF40": "LEXUS LS", "USF41": "LEXUS LS",
    "AZE0": "LEAF",
    "XZC610": "DUTRO",
    # Nissan
    "NT31": "X-TRAIL", "NT32": "X-TRAIL", "DNT31": "X-TRAIL", "T31": "X-TRAIL",
    "YF15": "JUKE", "F15": "JUKE",
    # Honda
    "GP1": "FIT HYBRID", "GP5": "FIT HYBRID", "GP6": "FIT HYBRID",
    "GP7": "FIT SHUTTLE HYBRID", "GP2": "FIT SHUTTLE HYBRID",
    "GK3": "FIT", "GK5": "FIT", "GE6": "FIT", "GE8": "FIT",
    "GB3": "FREED SPIKE", "GB4": "FREED SPIKE",
    "ZE2": "INSIGHT", "ZE3": "INSIGHT",
    # Daihatsu
    "S210P": "HIJET TRUCK", "S211P": "HIJET TRUCK", "S510P": "HIJET TRUCK",
    "S211U": "PIXIS TRUCK",
    # Mitsubishi Fuso
    "FE82D": "CANTER", "FE82EE": "CANTER", "FE72EE": "CANTER",
    "FE84DV": "CANTER", "FE83D": "CANTER", "FE70B": "CANTER",
    "FB70BB": "CANTER GUTS",
    "FK61FM": "FUSO FIGHTER", "FQ62F": "FUSO FIGHTER", "FK71F": "FUSO FIGHTER",
    "FEA50": "FUSO TRUCK",
    "FY54JTY": "SUPER GREAT", "FS54JZ": "SUPER GREAT",
    "FV50JJX": "SUPER GREAT", "FV50MJX": "SUPER GREAT",
    # Hino
    "FC6JLW": "RANGER", "FC7JKY": "RANGER",
    # UD Trucks
    "CG5ZA": "UD", "CG5ZE": "UD", "CG4ZA": "UD",
    "CD5ZA": "UD", "CD48R": "BIG THUMB",
    "MK35A": "CONDOR", "MK38L": "CONDOR", "MK36A": "CONDOR",
    "GK6XA": "QUON",
    "JNCLSC": "CONDOR",
    # Mazda
    "SKP2T": "BONGO TRUCK",
    # Mitsubishi
    "V98W": "PAJERO", "V97W": "PAJERO", "V93W": "PAJERO",
    # Volkswagen
    "WVWZZZ": "NEW BEETLE",
}

# ── Auction Checklist Database (Updated: March 3, 2026) ───
CARS = [
    # ── Original List ──
    {"chassis": "MNH15-0039667", "model": "ALPHARD", "color": "WHITE", "year": 2005},
    {"chassis": "CD48R-30111", "model": "BIG THUMB", "color": "GREEN", "year": 2005},
    {"chassis": "FE82EEV500266", "model": "CANTER", "color": "WHITE", "year": 2002},
    {"chassis": "FE84DV-550674", "model": "CANTER", "color": "BLUE", "year": 2008},
    {"chassis": "FB70BB-512392", "model": "CANTER GUTS", "color": "WHITE", "year": 2005},
    {"chassis": "MK35A-10405", "model": "CONDOR", "color": "PEARL WHITE", "year": 2006},
    {"chassis": "JNCLSC0A1GU006386", "model": "CONDOR", "color": "WHITE", "year": 2016},
    {"chassis": "GRS210-6004548", "model": "CROWN", "color": "PEARL WHITE", "year": 2013},
    {"chassis": "GRS200-0001831", "model": "CROWN", "color": "WHITE", "year": 2008},
    {"chassis": "GRS200-0020080", "model": "CROWN", "color": "WHITE", "year": 2008},
    {"chassis": "GRS202-0002603", "model": "CROWN", "color": "WHITE", "year": 2008},
    {"chassis": "XZC610-0001005", "model": "DUTRO", "color": "WHITE", "year": 2011},
    {"chassis": "GE6-1539486", "model": "FIT", "color": "PEARL WHITE", "year": 2011},
    {"chassis": "GP5-3032237", "model": "FIT HYBRID", "color": "PEARL WHITE", "year": 2014},
    {"chassis": "GP1-1131390", "model": "FIT HYBRID", "color": "WHITE", "year": 2012},
    {"chassis": "GP1-1049821", "model": "FIT HYBRID", "color": "PEARL WHITE", "year": 2011},
    {"chassis": "GP7-1000970", "model": "FIT SHUTTLE HYBRID", "color": "PEARL WHITE", "year": 2015},
    {"chassis": "GP2-3106770", "model": "FIT SHUTTLE HYBRID", "color": "SILVER", "year": 2013},
    {"chassis": "FK61FM765129", "model": "FUSO FIGHTER", "color": "WHITE", "year": 2003},
    {"chassis": "KDH201-0140123", "model": "HIACE VAN", "color": "WHITE", "year": 2014},
    {"chassis": "S211P-0217418", "model": "HIJET TRUCK", "color": "WHITE", "year": 2013},
    {"chassis": "S210P-2037788", "model": "HIJET TRUCK", "color": "WHITE", "year": 2005},
    {"chassis": "S510P-0173458", "model": "HIJET TRUCK", "color": "WHITE", "year": 2017},
    {"chassis": "UZJ100-0151432", "model": "LAND CRUISER", "color": "SILVER", "year": 2004},
    {"chassis": "USF40-5006069", "model": "LEXUS LS", "color": "WHITE", "year": 2006},
    {"chassis": "WVWZZZ16ZDM638030", "model": "NEW BEETLE", "color": "BLACK", "year": 2013},
    {"chassis": "ZRR75-0068964", "model": "NOAH", "color": "PEARL WHITE", "year": 2010},
    {"chassis": "V98W-0300140", "model": "PAJERO", "color": "PEARL WHITE", "year": 2010},
    {"chassis": "S211U-0000227", "model": "PIXIS TRUCK", "color": "WHITE", "year": 2011},
    {"chassis": "FC7JKY-14910", "model": "RANGER", "color": "BLUE", "year": 2011},
    {"chassis": "NCP165-0001505", "model": "SUCCEED VAN", "color": "PEARL WHITE", "year": 2014},
    {"chassis": "NCP59-0012188", "model": "SUCCEED WAGON", "color": "SILVER", "year": 2005},
    {"chassis": "FV50JJX-530670", "model": "SUPER GREAT", "color": "BLACK", "year": 2004},
    {"chassis": "CG5ZA-30374", "model": "UD", "color": "PEARL WHITE", "year": 2014},
    {"chassis": "CD5ZA-30191", "model": "UD", "color": "SILVER", "year": 2014},
    {"chassis": "CG4ZA-01338", "model": "UD", "color": "LIGHT BLUE", "year": 2006},
    {"chassis": "ZGE22-0005423", "model": "WISH", "color": "BLACK", "year": 2011},
    {"chassis": "ZGE20-0010786", "model": "WISH", "color": "PEARL WHITE", "year": 2009},
    {"chassis": "ZGE25-0015283", "model": "WISH", "color": "WHITE", "year": 2011},
    {"chassis": "NT32-504837", "model": "X-TRAIL", "color": "BLACK", "year": 2014},
    {"chassis": "NT32-531693", "model": "X-TRAIL", "color": "BLACK", "year": 2015},
    {"chassis": "NT31-316873", "model": "X-TRAIL", "color": "PEARL WHITE", "year": 2013},
    {"chassis": "NT32-508661", "model": "X-TRAIL", "color": "PEARL WHITE", "year": 2015},
    # ── March 3, 2026 Auction List ──
    {"chassis": "SKP2T-108324", "model": "BONGO TRUCK", "color": "WHITE", "year": 2013},
    {"chassis": "FE82D-570692", "model": "CANTER", "color": "WHITE", "year": 2010},
    {"chassis": "FE82D-530430", "model": "CANTER", "color": "PEARL WHITE", "year": 2007},
    {"chassis": "FE72EE-500637", "model": "CANTER", "color": "WHITE", "year": 2003},
    {"chassis": "GRS201-0006860", "model": "CROWN", "color": "SILVER", "year": 2011},
    {"chassis": "GRS200-0061216", "model": "CROWN", "color": "PEARL WHITE", "year": 2011},
    {"chassis": "GRS200-0063933", "model": "CROWN", "color": "BLACK", "year": 2011},
    {"chassis": "GWS204-0025870", "model": "CROWN HYBRID", "color": "SILVER", "year": 2012},
    {"chassis": "GK3-1029686", "model": "FIT", "color": "WHITE", "year": 2014},
    {"chassis": "GP1-1011906", "model": "FIT HYBRID", "color": "BLUE", "year": 2010},
    {"chassis": "GP5-3040254", "model": "FIT HYBRID", "color": "WHITE", "year": 2014},
    {"chassis": "GP1-1096649", "model": "FIT HYBRID", "color": "BLACK", "year": 2011},
    {"chassis": "GP1-1014176", "model": "FIT HYBRID", "color": "PEARL WHITE", "year": 2010},
    {"chassis": "GB3-1312198", "model": "FREED SPIKE", "color": "PEARL WHITE", "year": 2010},
    {"chassis": "FQ62F-520185", "model": "FUSO FIGHTER", "color": "WHITE", "year": 2008},
    {"chassis": "FEA50-521744", "model": "FUSO TRUCK", "color": "PEARL WHITE", "year": 2013},
    {"chassis": "KDH201-0056284", "model": "HIACE VAN", "color": "WHITE", "year": 2010},
    {"chassis": "S211P-0276262", "model": "HIJET TRUCK", "color": "SILVER", "year": 2014},
    {"chassis": "S510P-0147424", "model": "HIJET TRUCK", "color": "WHITE", "year": 2017},
    {"chassis": "S210P-2060815", "model": "HIJET TRUCK", "color": "WHITE", "year": 2006},
    {"chassis": "S510P-0149349", "model": "HIJET TRUCK", "color": "SILVER", "year": 2017},
    {"chassis": "S210P-2006882", "model": "HIJET TRUCK", "color": "SILVER", "year": 2005},
    {"chassis": "ZE2-1130682", "model": "INSIGHT", "color": "WHITE", "year": 2009},
    {"chassis": "YF15-033275", "model": "JUKE", "color": "WHITE", "year": 2011},
    {"chassis": "HDJ101-0031030", "model": "LAND CRUISER", "color": "PEARL WHITE", "year": 2007},
    {"chassis": "AZE0-062459", "model": "LEAF", "color": "PEARL WHITE", "year": 2013},
    {"chassis": "GRX133-6003681", "model": "MARK X", "color": "SILVER", "year": 2013},
    {"chassis": "WVWZZZ16ZDM685003", "model": "NEW BEETLE", "color": "BLACK", "year": 2013},
    {"chassis": "NCP165-0001511", "model": "PROBOX VAN", "color": "PEARL WHITE", "year": 2014},
    {"chassis": "GK6XA-10555", "model": "QUON", "color": "WHITE", "year": 2013},
    {"chassis": "FC6JLW-10241", "model": "RANGER", "color": "PEARL WHITE", "year": 2006},
    {"chassis": "FY54JTY530030", "model": "SUPER GREAT", "color": "PEARL WHITE", "year": 2003},
    {"chassis": "FS54JZ-570431", "model": "SUPER GREAT", "color": "BLACK", "year": 2010},
    {"chassis": "FV50MJX520729", "model": "SUPER GREAT", "color": "BLACK", "year": 2001},
    {"chassis": "CG5ZA-01150", "model": "UD", "color": "GREEN", "year": 2011},
    {"chassis": "CG5ZE-30138", "model": "UD", "color": "WHITE", "year": 2015},
    {"chassis": "MK38L-30952", "model": "UD", "color": "YELLOW", "year": 2014},
    {"chassis": "MK36A-12656", "model": "UD", "color": "WHITE", "year": 2006},
    {"chassis": "ZGE20-0041580", "model": "WISH", "color": "PEARL WHITE", "year": 2009},
    {"chassis": "ZGE20-0004342", "model": "WISH", "color": "WHITE", "year": 2009},
    {"chassis": "NT32-024640", "model": "X-TRAIL", "color": "BLACK", "year": 2014},
    {"chassis": "NT32-037944", "model": "X-TRAIL", "color": "BLACK", "year": 2015},
    {"chassis": "NT31-244285", "model": "X-TRAIL", "color": "PEARL WHITE", "year": 2012},
    {"chassis": "DNT31-209100", "model": "X-TRAIL", "color": "WHITE", "year": 2011},
]

PRICE_HISTORY = []
pending_photo = {}

# ── Helper Functions ──────────────────────────────────
def guess_model_from_chassis(chassis_input):
    """Guess model name from chassis prefix using CHASSIS_PREFIX_MAP"""
    chassis_upper = chassis_input.upper().strip()
    # Try longest prefix first for better matching (e.g., "FV50MJX" before "FV50")
    sorted_prefixes = sorted(CHASSIS_PREFIX_MAP.keys(), key=len, reverse=True)
    for prefix in sorted_prefixes:
        if chassis_upper.startswith(prefix):
            return CHASSIS_PREFIX_MAP[prefix]
    return "UNKNOWN"

def find_by_chassis(chassis_input):
    chassis_input = chassis_input.upper().strip()
    for car in CARS:
        if car["chassis"].upper() == chassis_input:
            return car
    return None

def find_by_model(model_input):
    model_input = model_input.upper().strip()
    return [c for c in CARS if model_input in c["model"].upper()]

def extract_chassis_from_text(text):
    """Extract chassis number - improved patterns for all formats"""
    text = text.upper().strip()
    patterns = [
        r'[A-Z]{1,5}\d{1,4}[A-Z]{0,2}\d{0,2}-\d{4,7}',
        r'[A-Z]{2,6}\d{2,4}-\d{4,7}',
        r'[A-Z0-9]{4,20}-\d{4,7}',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text)
        if matches:
            return max(matches, key=len)
    return None

def get_price_history(chassis):
    return [p for p in PRICE_HISTORY if p["chassis"] == chassis]

def format_car_info(car, price=None, history=None):
    txt = (
        f"🚗 *{car['model']}* ({car['year']})\n"
        f"🔑 Chassis: `{car['chassis']}`\n"
        f"🎨 Color: {car['color']}\n"
    )
    if price:
        txt += f"💰 ဈေး: *฿{price:,}*\n"
    if history:
        txt += f"\n📈 *ဈေးမှတ်တမ်း ({len(history)} ကြိမ်):*\n"
        for h in history[-5:]:
            txt += f"  • {h['date']} → ฿{h['price']:,}\n"
    txt += f"\n🌐 [Web မှာကြည့်](https://kyawmintun08.github.io/JanJapan-Auction/)"
    return txt

def save_price(chassis, model, color, year, price, user_name):
    now = datetime.now().strftime("%d/%m/%Y")
    entry = {
        "chassis": chassis, "model": model, "color": color,
        "year": year, "price": price, "date": now,
        "location": "Maesot FZ", "added_by": user_name
    }
    PRICE_HISTORY.append(entry)
    if SHEET_WEBHOOK:
        try:
            requests.post(SHEET_WEBHOOK, json=entry, timeout=5)
        except:
            pass
    return entry

# ── Command Handlers ──────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🚗 *JAN JAPAN Auction Bot*\n"
        "Maesot Freezone — ဈေးနှုန်း Tracker\n\n"
        "*Commands:*\n"
        "📸 ကားပုံ တင် → Chassis auto ဖတ်\n"
        "📋 ပုံ + caption `list` → Auction List ဖတ်\n"
        "🔍 `/find NT32-504837` → Chassis ရှာ\n"
        "🔎 `/model xtrail` → Model ရှာ\n"
        "💰 `/price NT32-504837 150000` → ဈေးထည့်\n"
        "📋 `/history NT32-504837` → ဈေးမှတ်တမ်း\n"
        "📊 `/list` → ကားအားလုံး\n"
        "🌐 `/web` → Web Link\n"
    )
    await update.message.reply_text(text, parse_mode='Markdown')

async def find_car(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Chassis ထည့်ပါ\nဥပမာ: `/find NT32-504837`", parse_mode='Markdown')
        return
    chassis = ' '.join(context.args)
    car = find_by_chassis(chassis)
    if car:
        history = get_price_history(car['chassis'])
        latest_price = history[-1]['price'] if history else None
        txt = format_car_info(car, latest_price, history if history else None)
        keyboard = [[InlineKeyboardButton("💰 ဈေးထည့်", callback_data=f"addprice_{car['chassis']}")]]
        await update.message.reply_text(txt, parse_mode='Markdown',
                                        reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        # Try guessing model from prefix
        guessed = guess_model_from_chassis(chassis)
        if guessed != "UNKNOWN":
            await update.message.reply_text(
                f"⚠️ `{chassis}` Checklist မှာ မပါဘူး\n"
                f"🚗 ခန့်မှန်း Model: *{guessed}*\n\n"
                f"ဈေးထည့်လိုရင် `/price {chassis} [ဈေး]`",
                parse_mode='Markdown')
        else:
            await update.message.reply_text(
                f"❌ `{chassis}` မတွေ့ပါ\n\nChecklist မှာ မပါဘူး — ဈေးထည့်လိုရင် `/price {chassis} [ဈေး]`",
                parse_mode='Markdown')

async def find_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Model ထည့်ပါ\nဥပမာ: `/model xtrail`", parse_mode='Markdown')
        return
    query = ' '.join(context.args)
    results = find_by_model(query)
    if not results:
        await update.message.reply_text(f"❌ *{query}* မတွေ့ပါ", parse_mode='Markdown')
        return
    txt = f"🔎 *{query.upper()}* ရလဒ် ({len(results)} စီး):\n\n"
    for car in results:
        history = get_price_history(car['chassis'])
        price_str = f"฿{history[-1]['price']:,}" if history else "ဈေးမရသေး"
        txt += f"• `{car['chassis']}` — {car['color']} {car['year']} — *{price_str}*\n"
    txt += f"\n🌐 [Web မှာကြည့်](https://kyawmintun08.github.io/JanJapan-Auction/)"
    await update.message.reply_text(txt, parse_mode='Markdown')

async def add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Format မှားနေတယ်\nဥပမာ: `/price NT32-504837 150000`", parse_mode='Markdown')
        return
    chassis = context.args[0].upper()
    try:
        price = int(context.args[1].replace(',', ''))
    except:
        await update.message.reply_text("❌ ဈေး ဂဏန်းသာ ထည့်ပါ", parse_mode='Markdown')
        return
    car = find_by_chassis(chassis)
    if not car:
        # Use prefix map to guess model instead of UNKNOWN
        guessed = guess_model_from_chassis(chassis)
        car = {"chassis": chassis, "model": guessed, "color": "-", "year": 0}
    user_name = update.effective_user.first_name or "Unknown"
    entry = save_price(car['chassis'], car['model'], car['color'], car['year'], price, user_name)
    txt = (
        f"✅ *ဈေးထည့်ပြီးပါပြီ!*\n\n"
        f"🚗 {car['model']} — `{chassis}`\n"
        f"💰 ฿{price:,}\n"
        f"📅 {entry['date']}\n"
        f"👤 {user_name}\n\n"
        f"🌐 [Web မှာကြည့်](https://kyawmintun08.github.io/JanJapan-Auction/)"
    )
    await update.message.reply_text(txt, parse_mode='Markdown')

async def price_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Chassis ထည့်ပါ\nဥပမာ: `/history NT32-504837`", parse_mode='Markdown')
        return
    chassis = ' '.join(context.args).upper()
    history = get_price_history(chassis)
    car = find_by_chassis(chassis)
    if not history:
        await update.message.reply_text(f"❌ `{chassis}` ဈေးမှတ်တမ်း မရှိသေးပါ", parse_mode='Markdown')
        return
    model_name = car['model'] if car else chassis
    txt = f"📈 *{model_name}* ဈေးမှတ်တမ်း\n`{chassis}`\n\n"
    prev = None
    for h in history:
        if prev:
            diff = h['price'] - prev
            arrow = "📈" if diff > 0 else "📉" if diff < 0 else "➡"
            diff_str = f" ({arrow} {diff:+,})"
        else:
            diff_str = ""
        txt += f"• {h['date']} → *฿{h['price']:,}*{diff_str}\n"
        prev = h['price']
    if len(history) >= 2:
        change = history[-1]['price'] - history[0]['price']
        pct = (change / history[0]['price']) * 100
        txt += f"\n📊 စုစုပေါင်းပြောင်းလဲမှု: *{change:+,}* ({pct:+.1f}%)"
    await update.message.reply_text(txt, parse_mode='Markdown')

async def list_cars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    priced = set(p['chassis'] for p in PRICE_HISTORY)
    txt = f"🚗 *ကားစာရင်း ({len(CARS)} စီး)*\n\n"
    for car in CARS[:20]:
        status = "💰" if car['chassis'] in priced else "⏳"
        txt += f"{status} `{car['chassis']}` — {car['model']} {car['year']}\n"
    if len(CARS) > 20:
        txt += f"\n... နှင့် {len(CARS)-20} စီး ထပ်ရှိသေးတယ်"
    txt += f"\n\n🌐 [အားလုံးကြည့်ရန်](https://kyawmintun08.github.io/JanJapan-Auction/)"
    await update.message.reply_text(txt, parse_mode='Markdown')

async def web_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "🌐 *JAN JAPAN Auction Web App*\n\n"
        "https://kyawmintun08.github.io/JanJapan-Auction/\n\n"
        "• ကားရှာနိုင် 🔍\n"
        "• ဈေးကြည့်နိုင် 📈\n"
        "• Chart ကြည့်နိုင် 📊\n"
        "• မည်သူမဆို ကြည့်နိုင် ✅"
    )
    await update.message.reply_text(txt, parse_mode='Markdown')

# ── Tesseract OCR Fallback ────────────────────────────
def tesseract_ocr_chassis(file_bytes: bytes) -> str:
    """Use Tesseract OCR to extract chassis number from car photo"""
    if not TESSERACT_AVAILABLE:
        return ""
    try:
        img = Image.open(BytesIO(file_bytes))
        text = pytesseract.image_to_string(img)
        logger.info(f"Tesseract raw: {text[:200]}")
        chassis = extract_chassis_from_text(text)
        return chassis or ""
    except Exception as e:
        logger.error(f"Tesseract OCR error: {e}")
        return ""

# ── Gemini OCR Functions ──────────────────────────────
async def gemini_ocr_auction_list(file_bytes: bytes) -> list:
    """Use Gemini Vision to extract all cars from auction list image"""
    try:
        import base64
        if not GEMINI_API_KEY:
            return []

        img_b64 = base64.b64encode(file_bytes).decode()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"

        payload = {
            "contents": [{
                "parts": [
                    {"text": """This is a Japan auction car list image. Extract ALL cars from the table.
Return ONLY a JSON array like this (no other text):
[{"chassis":"NT32-024640","model":"X-TRAIL","color":"BLACK","year":2014},...]
Rules:
- chassis: exact chassis number from TYPE column
- model: car model name
- color: color (WHITE/BLACK/SILVER/PEARL WHITE/etc)
- year: year as number
Extract every single row."""},
                    {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}}
                ]
            }]
        }

        resp = requests.post(url, json=payload, timeout=60)
        data = resp.json()

        if "candidates" not in data:
            logger.error(f"Gemini auction list error: {data}")
            return []

        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        logger.info(f"Gemini auction list raw: {text[:200]}")

        # Parse JSON from response
        import json
        start = text.find('[')
        end = text.rfind(']') + 1
        if start >= 0 and end > start:
            json_str = text[start:end]
            cars = json.loads(json_str)
            return cars
        return []

    except Exception as e:
        logger.error(f"Gemini auction list OCR error: {e}")
        return []


async def gemini_ocr_chassis(file_bytes: bytes) -> str:
    """Use Gemini Vision to extract chassis number from car photo, with Tesseract fallback"""
    # ── Step 1: Try Gemini ──
    if GEMINI_API_KEY:
        try:
            import base64

            img_b64 = base64.b64encode(file_bytes).decode()
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"

            payload = {
                "contents": [{
                    "parts": [
                        {"text": "This is a Japan auction car photo. There is a chassis number written with a marker pen on the windshield. Examples of chassis numbers: NT32-024640, DNT31-209100, GRS201-0006860, GP1-1011906, S510P-0147424. Please find and return ONLY the chassis number, nothing else."},
                        {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}}
                    ]
                }]
            }

            resp = requests.post(url, json=payload, timeout=30)
            data = resp.json()

            if "candidates" in data:
                text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                logger.info(f"Gemini raw: {text}")

                patterns = [
                    r'[A-Z]{1,5}\d{1,4}[A-Z]{0,2}\d{0,2}-\d{4,7}',
                    r'[A-Z]{2,6}\d{2,4}-\d{4,7}',
                    r'[A-Z0-9]{4,20}-\d{4,7}',
                ]
                for pattern in patterns:
                    match = re.search(pattern, text.upper())
                    if match:
                        result = match.group().replace(' ', '-')
                        logger.info(f"Chassis found (Gemini): {result}")
                        return result
            else:
                logger.error(f"Gemini error: {data}")

        except Exception as e:
            logger.error(f"Gemini OCR error: {e}")

    # ── Step 2: Fallback to Tesseract ──
    logger.info("Gemini failed or unavailable, trying Tesseract fallback...")
    chassis = tesseract_ocr_chassis(file_bytes)
    if chassis:
        logger.info(f"Chassis found (Tesseract): {chassis}")
        return chassis

    return ""

# ── Photo Handler ─────────────────────────────────────
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CARS
    user_id = update.effective_user.id
    photo = update.message.photo[-1]
    caption = (update.message.caption or "").strip().lower()

    # ── Auction List Mode ──────────────────────────────
    if "list" in caption:
        await update.message.reply_text("📋 Auction List ဖတ်နေတယ်... ⏳")
        try:
            file = await photo.get_file()
            file_bytes = await file.download_as_bytearray()
            new_cars = await gemini_ocr_auction_list(bytes(file_bytes))
        except Exception as e:
            logger.error(f"Auction list download error: {e}")
            new_cars = []

        if not new_cars:
            await update.message.reply_text(
                "⚠️ List ဖတ်မရပါ\n\n"
                "💡 Gemini API limit ကုန်သွားနိုင်တယ် — မနက်ဖြန် ပြန်ကြိုးစားပါ\n"
                "ဒါမှမဟုတ် ပုံ ရှင်းနေသလား စစ်ကြည့်ပါ"
            )
            return

        # Add new cars to CARS (skip duplicates)
        existing_chassis = {c["chassis"].upper() for c in CARS}
        added = []
        for car in new_cars:
            chassis = str(car.get("chassis", "")).upper().strip()
            if chassis and chassis not in existing_chassis:
                # Use Gemini's model if available, otherwise guess from prefix
                model = car.get("model", "")
                if not model or model == "UNKNOWN":
                    model = guess_model_from_chassis(chassis)
                CARS.append({
                    "chassis": chassis,
                    "model": model,
                    "color": car.get("color", "-"),
                    "year": int(car.get("year", 0)),
                    "location": "MaeSot FZ"
                })
                existing_chassis.add(chassis)
                added.append(chassis)

        txt = (
            f"✅ *Auction List Update ပြီး!*\n\n"
            f"📊 ဖတ်ရတဲ့ ကား: {len(new_cars)} စီး\n"
            f"✨ အသစ်ထည့်ခဲ့: {len(added)} စီး\n\n"
        )
        if added:
            txt += "🆕 အသစ်ထည့်ခဲ့တာ:\n"
            for ch in added[:10]:
                txt += f"• `{ch}`\n"
            if len(added) > 10:
                txt += f"... နှင့် {len(added)-10} စီး ထပ်ရှိသေး\n"
        txt += f"\n📋 Database တွင် ယခု ကား {len(CARS)} စီး ရှိပြီ"
        await update.message.reply_text(txt, parse_mode='Markdown')
        return

    # ── Car Photo Mode ─────────────────────────────────
    await update.message.reply_text("🔍 ပုံကို စစ်နေတယ်... Chassis ရှာနေတယ် ⏳")

    chassis = extract_chassis_from_text(caption) if caption else None

    if not chassis:
        try:
            file = await photo.get_file()
            file_bytes = await file.download_as_bytearray()
            chassis = await gemini_ocr_chassis(bytes(file_bytes))
        except Exception as e:
            logger.error(f"Photo download error: {e}")

    car = find_by_chassis(chassis) if chassis else None
    price_match = re.search(r'\d{4,6}', caption)
    price = int(price_match.group()) if price_match else None

    if car and price:
        user_name = update.effective_user.first_name or "Unknown"
        save_price(car['chassis'], car['model'], car['color'], car['year'], price, user_name)
        txt = (
            f"✅ *Auto ထည့်ပြီးပါပြီ!*\n\n"
            f"🚗 {car['model']} ({car['year']})\n"
            f"🔑 `{car['chassis']}`\n"
            f"💰 ฿{price:,}\n\n"
            f"🌐 [Web မှာကြည့်](https://kyawmintun08.github.io/JanJapan-Auction/)"
        )
        await update.message.reply_text(txt, parse_mode='Markdown')
    elif car:
        pending_photo[user_id] = {
            "chassis": car['chassis'], "model": car['model'],
            "color": car['color'], "year": car['year'], "file_id": photo.file_id
        }
        txt = (
            f"🚗 ကားတွေ့ပြီ!\n\n"
            f"*{car['model']}* ({car['year']})\n"
            f"`{car['chassis']}`\n\n"
            f"💰 ဈေး ရိုက်ထည့်ပါ (ဂဏန်းသာ):\nဥပမာ: `150000`"
        )
        await update.message.reply_text(txt, parse_mode='Markdown')
    elif chassis:
        # Chassis found but not in CARS list — guess model from prefix
        guessed_model = guess_model_from_chassis(chassis)
        pending_photo[user_id] = {
            "chassis": chassis, "model": guessed_model, "color": "-",
            "year": 0, "file_id": photo.file_id
        }
        if guessed_model != "UNKNOWN":
            txt = (
                f"⚠️ Chassis တွေ့ပြီ: `{chassis}`\n"
                f"🚗 ခန့်မှန်း Model: *{guessed_model}*\n"
                f"Checklist မှာ မပါဘူး — ဈေး ရိုက်ထည့်ပါ:\nဥပမာ: `150000`"
            )
        else:
            txt = (
                f"⚠️ Chassis တွေ့ပြီ: `{chassis}`\n"
                f"Checklist မှာ မပါဘူး — ဈေး ရိုက်ထည့်ပါ:\nဥပမာ: `150000`"
            )
        await update.message.reply_text(txt, parse_mode='Markdown')
    else:
        txt = (
            "⚠️ Chassis ဖတ်မရပါ\n\n"
            "💡 Gemini API limit ကုန်နေရင် Tesseract နဲ့ ကြိုးစားပြီးပါပြီ\n\n"
            "ကိုယ်တိုင် ထည့်ပါ:\n"
            "`/price [chassis] [ဈေး]`\n\n"
            "ဥပမာ: `/price NT32-504837 150000`"
        )
        await update.message.reply_text(txt, parse_mode='Markdown')

# ── Text Handler ──────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id in pending_photo:
        price_match = re.match(r'^[\d,]+$', text.replace(' ', ''))
        if price_match:
            try:
                price = int(text.replace(',', '').replace(' ', ''))
                data = pending_photo.pop(user_id)
                user_name = update.effective_user.first_name or "Unknown"
                save_price(data['chassis'], data['model'], data['color'], data['year'], price, user_name)
                txt = (
                    f"✅ *ဈေးထည့်ပြီးပါပြီ!*\n\n"
                    f"🚗 {data['model']} — `{data['chassis']}`\n"
                    f"💰 ฿{price:,}\n\n"
                    f"🌐 [Web မှာကြည့်](https://kyawmintun08.github.io/JanJapan-Auction/)"
                )
                await update.message.reply_text(txt, parse_mode='Markdown')
                return
            except:
                pass

    chassis = extract_chassis_from_text(text)
    if chassis:
        car = find_by_chassis(chassis)
        if car:
            history = get_price_history(car['chassis'])
            latest_price = history[-1]['price'] if history else None
            txt = format_car_info(car, latest_price, history if history else None)
            keyboard = [[InlineKeyboardButton("💰 ဈေးထည့်", callback_data=f"addprice_{car['chassis']}")]]
            await update.message.reply_text(txt, parse_mode='Markdown',
                                            reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            # Chassis found in text but not in CARS — guess model
            guessed = guess_model_from_chassis(chassis)
            if guessed != "UNKNOWN":
                txt = (
                    f"⚠️ `{chassis}` Checklist မှာ မပါဘူး\n"
                    f"🚗 ခန့်မှန်း Model: *{guessed}*\n\n"
                    f"ဈေးထည့်လိုရင် `/price {chassis} [ဈေး]`"
                )
            else:
                txt = (
                    f"⚠️ `{chassis}` Checklist မှာ မပါဘူး\n\n"
                    f"ဈေးထည့်လိုရင် `/price {chassis} [ဈေး]`"
                )
            await update.message.reply_text(txt, parse_mode='Markdown')

# ── Callback Handler ───────────────────────────────────
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("addprice_"):
        chassis = query.data.replace("addprice_", "")
        user_id = query.from_user.id
        car = find_by_chassis(chassis)
        if car:
            pending_photo[user_id] = {
                "chassis": car['chassis'], "model": car['model'],
                "color": car['color'], "year": car['year'], "file_id": None
            }
        await query.message.reply_text(
            f"💰 `{chassis}` ဈေး ရိုက်ထည့်ပါ:\nဥပမာ: `150000`", parse_mode='Markdown')

# ── Main ───────────────────────────────────────────────
async def main():
    logger.info("Bot starting...")
    import httpx
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{TOKEN}/deleteWebhook",
            params={"drop_pending_updates": True}
        )

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("find", find_car))
    app.add_handler(CommandHandler("model", find_model))
    app.add_handler(CommandHandler("price", add_price))
    app.add_handler(CommandHandler("history", price_history))
    app.add_handler(CommandHandler("list", list_cars))
    app.add_handler(CommandHandler("web", web_link))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(button_callback))

    await app.initialize()
    await app.start()
    await app.updater.start_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )

    logger.info("Bot is polling now!")
    await asyncio.Event().wait()


if __name__ == '__main__':
    asyncio.run(main())
