import asyncio
import os
import re
import logging
import httpx
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# ── Tesseract OCR (fallback) ─────────────────────────
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

GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL      = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
TOKEN             = os.environ.get('BOT_TOKEN', '')
SHEET_WEBHOOK     = os.environ.get('SHEET_WEBHOOK', '')
CHANNEL_ID        = os.environ.get('CHANNEL_ID', '-1003749046571')
ADMIN_IDS         = [int(x) for x in os.environ.get('ADMIN_IDS', '').split(',') if x.strip().isdigit()]
CLOUDINARY_CLOUD_NAME  = os.environ.get('CLOUDINARY_CLOUD_NAME', '')
CLOUDINARY_API_KEY     = os.environ.get('CLOUDINARY_API_KEY', '')
CLOUDINARY_API_SECRET  = os.environ.get('CLOUDINARY_API_SECRET', '')

# ── Chassis Prefix → Model Name Map ─────────────────
CHASSIS_PREFIX_MAP = {
    # Toyota
    "VZNY12": "ADVAN",
    "GRS200": "CROWN", "GRS201": "CROWN", "GRS202": "CROWN",
    "GRS204": "CROWN", "GRS210": "CROWN",
    "GWS204": "CROWN HYBRID",
    "ZGE20": "WISH", "ZGE21": "WISH", "ZGE22": "WISH", "ZGE25": "WISH",
    "GRX133": "MARK X",
    "GGH25": "ALPHARD", "GGH20": "ALPHARD",
    "MNH15": "ALPHARD", "MNH10": "ALPHARD",
    "ANH15": "ALPHARD", "ANH20": "ALPHARD",
    "ZRR75": "VOXY", "ZRR70": "VOXY", "ZWR80": "VOXY",
    "KDH201": "HIACE VAN", "KDH200": "HIACE VAN", "KDH205": "HIACE VAN", "TRH200": "HIACE VAN",
    "NCP165": "SUCCEED VAN", "NCP160": "SUCCEED VAN",
    "NCP59": "SUCCEED WAGON", "NCP58": "SUCCEED WAGON",
    "UZJ100": "LAND CRUISER", "HDJ101": "LAND CRUISER", "HZJ105": "LAND CRUISER",
    "KDN185": "HILUX SURF", "KZN185": "HILUX SURF", "VZN185": "HILUX SURF",
    "KDJ95": "LAND CRUISER PRADO", "KZJ95": "LAND CRUISER PRADO", "UZJ101": "LAND CRUISER",
    "USF40": "LEXUS LS", "USF41": "LEXUS LS",
    "ACU25": "KLUGER", "ACU20": "KLUGER", "MCU25": "KLUGER",
    "AZE0": "LEAF",
    "XZC610": "DUTRO", "XZU548": "DUTRO TRUCK", "XZU300": "DUTRO TRUCK",
    "ACA33": "VANGUARD", "ACA38": "VANGUARD",
    "CW4YL": "QUON",
    # Nissan
    "NT31": "X-TRAIL", "NT32": "X-TRAIL", "DNT31": "X-TRAIL", "T31": "X-TRAIL",
    "YF15": "JUKE", "F15": "JUKE", "NF15": "JUKE",
    "SK82TN": "VANETTE TRUCK", "SK82VN": "VANETTE TRUCK",
    # Honda
    "GP1": "FIT HYBRID", "GP5": "FIT HYBRID", "GP6": "FIT HYBRID",
    "GP7": "FIT SHUTTLE HYBRID", "GP2": "FIT SHUTTLE HYBRID",
    "GK3": "FIT", "GK5": "FIT", "GE6": "FIT", "GE8": "FIT",
    "GB3": "FREED", "GB4": "FREED",
    "RE4": "CRV", "RE3": "CRV", "RD1": "CRV", "RD5": "CRV",
    "ZE2": "INSIGHT", "ZE3": "INSIGHT",
    # Mazda
    "KE2AW": "CX5", "KE2FW": "CX5", "KE5FW": "CX5",
    "SKP2T": "BONGO TRUCK", "SLP2L": "BONGO TRUCK",
    # Daihatsu / Subaru
    "S210P": "HIJET TRUCK", "S211P": "HIJET TRUCK", "S510P": "HIJET TRUCK",
    "S500P": "HIJET TRUCK", "S501P": "HIJET TRUCK", "S321V": "HIJET VAN",
    "S331V": "HIJET VAN", "S200P": "HIJET TRUCK", "S201P": "HIJET TRUCK",
    "S211U": "PIXIS TRUCK", "S500U": "PIXIS TRUCK",
    "S510J": "SAMBAR TRUCK", "S201J": "SAMBAR TRUCK",
    # Mitsubishi Fuso
    "FE74BV": "CANTER", "FE82BS": "CANTER", "FBA30": "CANTER",
    "FE82D": "CANTER", "FE82EE": "CANTER", "FE72EE": "CANTER",
    "FE84DV": "CANTER", "FE83D": "CANTER", "FE70B": "CANTER",
    "FE73EB": "CANTER", "FE70EB": "CANTER", "FEA20": "CANTER",
    "FB70BB": "CANTER GUTS",
    "FK61FM": "FUSO FIGHTER", "FQ62F": "FUSO FIGHTER", "FK71F": "FUSO FIGHTER",
    "FEA50": "FUSO TRUCK", "FBA20": "FUSO TRUCK",
    "FY54JTY": "SUPER GREAT", "FS54JZ": "SUPER GREAT",
    "FV50JJX": "SUPER GREAT", "FV50MJX": "SUPER GREAT",
    # Hino
    "FC6JLW": "RANGER", "FC7JKY": "RANGER",
    "FW1EXW": "PROFIA", "SH1EDX": "PROFIA",
    # UD Trucks
    "CG5ZA": "UD", "CG5ZE": "UD", "CG4ZA": "UD", "CG4YA": "UD",
    "CD5ZA": "UD", "CD4ZA": "UD", "CD48R": "BIG THUMB",
    "MK35A": "CONDOR", "MK38L": "CONDOR", "MK36A": "CONDOR",
    "MK36B": "UD", "MK38C": "UD",
    "JNCMM60C6GU": "UD", "JNCMM60G6GU": "UD",
    "GK6XA": "QUON",
    "JNCLSC": "CONDOR",
    # Mitsubishi
    "V98W": "PAJERO", "V97W": "PAJERO", "V93W": "PAJERO",
    "V75W": "PAJERO", "V78W": "PAJERO",
    # Volkswagen
    "WVWZZZ": "NEW BEETLE",
}

# ── Auction Checklist Database ───────────────────────
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
    {"chassis": "ZRR75-0068964", "model": "VOXY", "color": "PEARL WHITE", "year": 2010},
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
    {"chassis": "GB3-1312198", "model": "FREED", "color": "PEARL WHITE", "year": 2010},
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
    {"chassis": "NCP165-0001511", "model": "SUCCEED VAN", "color": "PEARL WHITE", "year": 2014},
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
    # ── March 8, 2026 Auction List (KALANG9 FREEZONE) ──
    {"chassis": "VZNY12-070391", "model": "ADVAN", "color": "WHITE", "year": 2017},
    {"chassis": "GGH20-8002412", "model": "ALPHARD", "color": "PEARL WHITE", "year": 2008},
    {"chassis": "MNH10-0099576", "model": "ALPHARD", "color": "PEARL WHITE", "year": 2007},
    {"chassis": "SLP2L-102206", "model": "BONGO TRUCK", "color": "WHITE", "year": 2017},
    {"chassis": "FEA20-520134", "model": "CANTER", "color": "SILVER", "year": 2013},
    {"chassis": "FE73EB-501814", "model": "CANTER", "color": "LIGHT GREEN", "year": 2003},
    {"chassis": "FE70EB-506566", "model": "CANTER", "color": "WHITE", "year": 2004},
    {"chassis": "GRS204-0014299", "model": "CROWN", "color": "WHITE", "year": 2010},
    {"chassis": "RE4-1006211", "model": "CRV", "color": "WHITE", "year": 2006},
    {"chassis": "KE2AW-115142", "model": "CX5", "color": "WHITE", "year": 2013},
    {"chassis": "GP5-3037138", "model": "FIT HYBRID", "color": "PEARL WHITE", "year": 2014},
    {"chassis": "GP5-3216073", "model": "FIT HYBRID", "color": "PEARL WHITE", "year": 2015},
    {"chassis": "GB3-1112824", "model": "FREED", "color": "PEARL WHITE", "year": 2009},
    {"chassis": "FK71F-701985", "model": "FUSO FIGHTER", "color": "GREEN", "year": 2007},
    {"chassis": "S211P-0042777", "model": "HIJET TRUCK", "color": "SILVER", "year": 2009},
    {"chassis": "S211P-0138980", "model": "HIJET TRUCK", "color": "WHITE", "year": 2011},
    {"chassis": "KDN185-0001271", "model": "HILUX SURF", "color": "SILVER", "year": 2000},
    {"chassis": "ZE2-1128237", "model": "INSIGHT", "color": "SILVER", "year": 2009},
    {"chassis": "NF15-060818", "model": "JUKE", "color": "WHITE", "year": 2012},
    {"chassis": "ACU25-0032701", "model": "KLUGER", "color": "WHITE", "year": 2004},
    {"chassis": "USF40-5079528", "model": "LEXUS LS", "color": "PEARL WHITE", "year": 2008},
    {"chassis": "WVWZZZ16ZDM635922", "model": "NEW BEETLE", "color": "RED", "year": 2013},
    {"chassis": "GK6XA-10291", "model": "QUON", "color": "GREEN", "year": 2012},
    {"chassis": "CW4YL-30468", "model": "QUON", "color": "SILVER", "year": 2009},
    {"chassis": "NCP165-0056792", "model": "SUCCEED VAN", "color": "WHITE", "year": 2018},
    {"chassis": "NCP59-0024963", "model": "SUCCEED WAGON", "color": "DARK BLUE", "year": 2012},
    {"chassis": "CG5ZA-12819", "model": "UD", "color": "PEARL WHITE", "year": 2014},
    {"chassis": "CG5ZA-11731", "model": "UD", "color": "WHITE", "year": 2013},
    {"chassis": "CG4YA-00054", "model": "UD", "color": "WHITE", "year": 2006},
    {"chassis": "CD4ZA-31233", "model": "UD", "color": "GREEN", "year": 2009},
    {"chassis": "SK82TN-319474", "model": "VANETTE TRUCK", "color": "WHITE", "year": 2005},
    {"chassis": "ZRR75-0083512", "model": "VOXY", "color": "PEARL WHITE", "year": 2011},
    {"chassis": "ZGE25-0020690", "model": "WISH", "color": "PEARL WHITE", "year": 2012},
    {"chassis": "ZGE20-0154748", "model": "WISH", "color": "PEARL WHITE", "year": 2013},
    {"chassis": "ZGE20-0152288", "model": "WISH", "color": "BLACK", "year": 2012},
    {"chassis": "NT32-036496", "model": "X-TRAIL", "color": "BLACK", "year": 2014},
    {"chassis": "NT31-212796", "model": "X-TRAIL", "color": "PEARL WHITE", "year": 2011},
    {"chassis": "NT31-049247", "model": "X-TRAIL", "color": "BLACK", "year": 2009},
    {"chassis": "DNT31-205472", "model": "X-TRAIL", "color": "PEARL WHITE", "year": 2011},
    {"chassis": "NT32-038921", "model": "X-TRAIL", "color": "PEARL WHITE", "year": 2015},
]

PRICE_HISTORY = []
pending_photo = {}

# ── Helper Functions ──────────────────────────────────
def guess_model_from_chassis(chassis_input):
    chassis_upper = chassis_input.upper().strip()
    sorted_prefixes = sorted(CHASSIS_PREFIX_MAP.keys(), key=len, reverse=True)
    for prefix in sorted_prefixes:
        if chassis_upper.startswith(prefix):
            return CHASSIS_PREFIX_MAP[prefix]
    return "UNKNOWN"

async def guess_model_from_chassis_gemini(chassis_input):
    if not GEMINI_API_KEY:
        return "UNKNOWN"
    try:
        prefix = chassis_input.split("-")[0] if "-" in chassis_input else chassis_input[:6]
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": f"What Japanese car model has chassis prefix '{prefix}'? Reply with ONLY the model name in UPPERCASE (e.g. HIJET TRUCK, X-TRAIL, FIT HYBRID). If unknown reply UNKNOWN."}]}]}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=15)
        data = resp.json()
        if "candidates" in data:
            model = data["candidates"][0]["content"]["parts"][0]["text"].strip().upper().split("\n")[0].strip()
            return model if model and model != "UNKNOWN" else "UNKNOWN"
    except Exception as e:
        logger.error(f"Gemini model guess error: {e}")
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
    year_str = str(car['year']) if car.get('year') and car['year'] != 0 else "—"
    txt = (
        f"🚗 *{car['model']}* ({year_str})\n"
        f"🔑 Chassis: `{car['chassis']}`\n"
        f"🎨 Color: {car['color']}\n"
    )
    if price:
        txt += f"💰 ဈေး: *฿{price:,}*\n"
    if history:
        txt += f"\n📈 *ဈေးမှတ်တမ်း ({len(history)} ကြိမ်):*\n"
        for h in history[-5:]:
            txt += f"  • {h['date']} → ฿{h['price']:,}\n"
    txt += f"\n🌐 [Web မှာကြည့်](https://kyawmintun08.github.io/Japan-Auction-Car-Checker/)"
    return txt

async def upload_to_cloudinary(file_bytes: bytes, chassis: str) -> str:
    if not all([CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET]):
        return ""
    try:
        import base64, hashlib, time
        timestamp = str(int(time.time()))
        public_id = f"auction/{chassis.replace('-', '_')}_{timestamp}"
        sig_str   = f"public_id={public_id}&timestamp={timestamp}{CLOUDINARY_API_SECRET}"
        signature = hashlib.sha1(sig_str.encode()).hexdigest()
        img_b64   = base64.b64encode(file_bytes).decode()
        url       = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/image/upload"
        payload   = {"file": f"data:image/jpeg;base64,{img_b64}", "public_id": public_id,
                     "timestamp": timestamp, "api_key": CLOUDINARY_API_KEY, "signature": signature}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, data=payload, timeout=30)
        result = resp.json()
        return result.get("secure_url", "")
    except Exception as e:
        logger.error(f"Cloudinary upload error: {e}")
        return ""

async def save_price(chassis, model, color, year, price, user_name, image_url=""):
    now   = datetime.now().strftime("%d/%m/%Y")
    entry = {
        "chassis": chassis, "model": model, "color": color,
        "year": year, "price": price, "date": now,
        "location": "Maesot FZ", "added_by": user_name, "image_url": image_url
    }
    PRICE_HISTORY.append(entry)
    if SHEET_WEBHOOK:
        try:
            async with httpx.AsyncClient() as client:
                await client.post(SHEET_WEBHOOK, json=entry, timeout=10, follow_redirects=True)
        except Exception as e:
            logger.error(f"save_price error: {e}")
    return entry

# ── Channel Post ──────────────────────────────────────
async def post_to_channel(context, chassis, model, color, year, price, image_url=""):
    if not CHANNEL_ID:
        return
    year_str  = str(year) if year and year != 0 else "—"
    color_str = color if color and color not in ["-", ""] else "—"
    price_str = f"฿{int(price):,}" if price else "—"
    text = (
        f"🚗 *ကားသစ်ဝင်ပြီ!*\n"
        f"━━━━━━━━━━━━━━\n"
        f"🔑 Chassis : `{chassis}`\n"
        f"🚘 Model   : *{model}*\n"
        f"🎨 Color   : {color_str}\n"
        f"📅 Year    : {year_str}\n"
        f"💰 Price   : *{price_str}*\n"
        f"📍 Maesot Freezone\n"
        f"━━━━━━━━━━━━━━\n"
        f"🌐 [Japan Auction Car Checker](https://kyawmintun08.github.io/Japan-Auction-Car-Checker/)"
    )
    try:
        if image_url:
            await context.bot.send_photo(chat_id=CHANNEL_ID, photo=image_url, caption=text, parse_mode='Markdown')
        else:
            await context.bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Channel post error: {e}")

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
        await update.message.reply_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        guessed = guess_model_from_chassis(chassis)
        if guessed == "UNKNOWN":
            guessed = await guess_model_from_chassis_gemini(chassis)
        if guessed != "UNKNOWN":
            await update.message.reply_text(
                f"⚠️ `{chassis}` Checklist မှာ မပါဘူး\n🚗 ခန့်မှန်း Model: *{guessed}*\n\nဈေးထည့်လိုရင် `/price {chassis} [ဈေး]`",
                parse_mode='Markdown')
        else:
            await update.message.reply_text(
                f"❌ `{chassis}` မတွေ့ပါ\n\nChecklist မှာ မပါဘူး — ဈေးထည့်လိုရင် `/price {chassis} [ဈေး]`",
                parse_mode='Markdown')

async def find_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Model ထည့်ပါ\nဥပမာ: `/model xtrail`", parse_mode='Markdown')
        return
    query   = ' '.join(context.args)
    results = find_by_model(query)
    if not results:
        await update.message.reply_text(f"❌ *{query}* မတွေ့ပါ", parse_mode='Markdown')
        return
    txt = f"🔎 *{query.upper()}* ရလဒ် ({len(results)} စီး):\n\n"
    for car in results:
        history  = get_price_history(car['chassis'])
        price_str = f"฿{history[-1]['price']:,}" if history else "ဈေးမရသေး"
        year_str  = str(car['year']) if car.get('year') and car['year'] != 0 else "—"
        txt += f"• `{car['chassis']}` — {car['color']} {year_str} — *{price_str}*\n"
    txt += f"\n🌐 [Web မှာကြည့်](https://kyawmintun08.github.io/Japan-Auction-Car-Checker/)"
    await update.message.reply_text(txt, parse_mode='Markdown')

async def add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("❌ Format မှားနေတယ်\nဥပမာ: `/price NT32-504837 150000`", parse_mode='Markdown')
        return
    chassis = context.args[0].upper()
    try:
        price = int(context.args[1].replace(',', ''))
    except:
        await update.message.reply_text("❌ ဈေး ဂဏန်းသာ ထည့်ပါ", parse_mode='Markdown')
        return
    car = find_by_chassis(chassis)
    if not car:
        guessed = guess_model_from_chassis(chassis)
        if guessed == "UNKNOWN":
            guessed = await guess_model_from_chassis_gemini(chassis)
        car = {"chassis": chassis, "model": guessed, "color": "-", "year": 0}
    user_name = update.effective_user.first_name or "Unknown"
    entry    = await save_price(car['chassis'], car['model'], car['color'], car['year'], price, user_name)
    year_str  = str(car['year']) if car.get('year') and car['year'] != 0 else "—"
    txt = (
        f"✅ *ဈေးထည့်ပြီးပါပြီ!*\n\n"
        f"🚗 {car['model']} ({year_str}) — `{chassis}`\n"
        f"💰 ฿{price:,}\n📅 {entry['date']}\n👤 {user_name}\n\n"
        f"🌐 [Web မှာကြည့်](https://kyawmintun08.github.io/Japan-Auction-Car-Checker/)"
    )
    await update.message.reply_text(txt, parse_mode='Markdown')

async def price_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Chassis ထည့်ပါ\nဥပမာ: `/history NT32-504837`", parse_mode='Markdown')
        return
    chassis = ' '.join(context.args).upper()
    history = get_price_history(chassis)
    car     = find_by_chassis(chassis)
    if not history:
        await update.message.reply_text(f"❌ `{chassis}` ဈေးမှတ်တမ်း မရှိသေးပါ", parse_mode='Markdown')
        return
    model_name = car['model'] if car else chassis
    txt  = f"📈 *{model_name}* ဈေးမှတ်တမ်း\n`{chassis}`\n\n"
    prev = None
    for h in history:
        if prev:
            diff     = h['price'] - prev
            arrow    = "📈" if diff > 0 else "📉" if diff < 0 else "➡"
            diff_str = f" ({arrow} {diff:+,})"
        else:
            diff_str = ""
        txt += f"• {h['date']} → *฿{h['price']:,}*{diff_str}\n"
        prev = h['price']
    if len(history) >= 2:
        change = history[-1]['price'] - history[0]['price']
        pct    = (change / history[0]['price']) * 100
        txt += f"\n📊 စုစုပေါင်းပြောင်းလဲမှု: *{change:+,}* ({pct:+.1f}%)"
    await update.message.reply_text(txt, parse_mode='Markdown')

async def list_cars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    priced = set(p['chassis'] for p in PRICE_HISTORY)
    txt    = f"🚗 *ကားစာရင်း ({len(CARS)} စီး)*\n\n"
    for car in CARS[:20]:
        status   = "💰" if car['chassis'] in priced else "⏳"
        year_str = str(car['year']) if car.get('year') and car['year'] != 0 else "—"
        txt += f"{status} `{car['chassis']}` — {car['model']} {year_str}\n"
    if len(CARS) > 20:
        txt += f"\n... နှင့် {len(CARS)-20} စီး ထပ်ရှိသေးတယ်"
    txt += f"\n\n🌐 [အားလုံးကြည့်ရန်](https://kyawmintun08.github.io/Japan-Auction-Car-Checker/)"
    await update.message.reply_text(txt, parse_mode='Markdown')

async def web_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "🌐 *JAN JAPAN Auction Web App*\n\n"
        "https://kyawmintun08.github.io/Japan-Auction-Car-Checker/\n\n"
        "• ကားရှာနိုင် 🔍\n• ဈေးကြည့်နိုင် 📈\n• Chart ကြည့်နိုင် 📊\n• မည်သူမဆို ကြည့်နိုင် ✅"
    )
    await update.message.reply_text(txt, parse_mode='Markdown')

# ── Tesseract OCR Fallback ────────────────────────────
def tesseract_ocr_chassis(file_bytes: bytes) -> str:
    if not TESSERACT_AVAILABLE:
        return ""
    try:
        img     = Image.open(BytesIO(file_bytes))
        text    = pytesseract.image_to_string(img)
        chassis = extract_chassis_from_text(text)
        return chassis or ""
    except Exception as e:
        logger.error(f"Tesseract OCR error: {e}")
        return ""

# ── Gemini OCR Functions ──────────────────────────────
async def gemini_ocr_auction_list(file_bytes: bytes) -> list:
    try:
        import base64, json
        if not GEMINI_API_KEY:
            return []
        img_b64 = base64.b64encode(file_bytes).decode()
        url     = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [
                {"text": """This is a Japan auction car list image from Maesot Freezone Myanmar.
Extract ALL cars from the table. Look carefully at every column.
Return ONLY a JSON array (no other text, no markdown):
[{"chassis":"NT32-024640","model":"X-TRAIL","color":"BLACK","year":2014},...]
Rules:
- chassis: exact value from TYPE or CHASSIS column
- model: car model name from MODEL column
- color: color value (WHITE/BLACK/SILVER/PEARL WHITE/BLUE/GREEN/etc)
- year: manufacturing year as integer
- Extract every single row, do not skip any."""},
                {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}}
            ]}]
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=60)
        data = resp.json()
        if "candidates" not in data:
            logger.error(f"Gemini auction list error: {data}")
            return []
        text  = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        start = text.find('[')
        end   = text.rfind(']') + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
        return []
    except Exception as e:
        logger.error(f"Gemini auction list OCR error: {e}")
        return []


async def gemini_ocr_chassis(file_bytes: bytes) -> dict:
    """
    ✅ FIX: YEAR ပါ return လုပ်အောင် prompt နဲ့ parse ပြင်ထားတယ်
    """
    if GEMINI_API_KEY:
        try:
            import base64
            img_b64 = base64.b64encode(file_bytes).decode()
            url     = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
            payload = {
                "contents": [{"parts": [
                    {"text": """This is a Japan auction car photo. A chassis number is written with a marker pen on the windshield.
Examples: NT32-024640, DNT31-209100, GRS201-0006860, GP1-1011906, S510P-0147424.

Please identify:
1. The chassis number on the windshield
2. The car model (e.g. X-TRAIL, CROWN, HILUX SURF, WISH, FIT HYBRID, ALPHARD)
3. The car color (e.g. WHITE, PEARL WHITE, BLACK, SILVER, BLUE)
4. The manufacturing year (e.g. 2014, 2011, 2008)

Return in EXACTLY this format (nothing else):
CHASSIS: NT32-024640
MODEL: X-TRAIL
COLOR: BLACK
YEAR: 2014"""},
                    {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}}
                ]}]
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, timeout=60)
            data = resp.json()

            if "candidates" in data:
                text    = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                logger.info(f"Gemini raw: {text}")

                chassis = ""
                model   = ""
                color   = ""
                year    = 0  # ✅ year ထပ်ထည့်

                for line in text.upper().split("\n"):
                    line = line.strip()
                    if line.startswith("CHASSIS:"):
                        raw = line.replace("CHASSIS:", "").strip()
                        for pattern in [
                            r'[A-Z]{1,5}\d{1,4}[A-Z]{0,2}\d{0,2}-\d{4,7}',
                            r'[A-Z]{2,6}\d{2,4}-\d{4,7}',
                            r'[A-Z0-9]{4,20}-\d{4,7}',
                        ]:
                            match = re.search(pattern, raw)
                            if match:
                                chassis = match.group().replace(' ', '-')
                                break
                    elif line.startswith("MODEL:"):
                        model = line.replace("MODEL:", "").strip()
                    elif line.startswith("COLOR:"):
                        color = line.replace("COLOR:", "").strip()
                    elif line.startswith("YEAR:"):  # ✅ year parse
                        try:
                            year = int(re.search(r'\d{4}', line).group())
                        except:
                            year = 0

                if chassis:
                    logger.info(f"Gemini — Chassis:{chassis} Model:{model} Color:{color} Year:{year}")
                    return {"chassis": chassis, "model": model, "color": color, "year": year}
            else:
                logger.error(f"Gemini error: {data}")

        except Exception as e:
            logger.error(f"Gemini OCR error: {e}")

    # Tesseract fallback
    logger.info("Gemini failed, trying Tesseract...")
    chassis = tesseract_ocr_chassis(file_bytes)
    if chassis:
        return {"chassis": chassis, "model": "", "color": "", "year": 0}
    return {"chassis": "", "model": "", "color": "", "year": 0}

# ── Photo Handler ─────────────────────────────────────
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CARS
    user_id = update.effective_user.id
    photo   = update.message.photo[-1]
    caption = (update.message.caption or "").strip().lower()

    # ── Auction List Mode ──
    if "list" in caption:
        await update.message.reply_text("📋 Auction List ဖတ်နေတယ်... ⏳")
        try:
            file       = await photo.get_file()
            file_bytes = await file.download_as_bytearray()
            new_cars   = await gemini_ocr_auction_list(bytes(file_bytes))
        except Exception as e:
            logger.error(f"Auction list error: {e}")
            new_cars = []

        if not new_cars:
            await update.message.reply_text(
                "⚠️ List ဖတ်မရပါ\n\n💡 Gemini API limit ကုန်သွားနိုင်တယ် — မနက်ဖြန် ပြန်ကြိုးစားပါ")
            return

        existing_chassis = {c["chassis"].upper() for c in CARS}
        added = []
        for car in new_cars:
            chassis = str(car.get("chassis", "")).upper().strip()
            if chassis and chassis not in existing_chassis:
                model = car.get("model", "") or guess_model_from_chassis(chassis)
                CARS.append({
                    "chassis": chassis, "model": model,
                    "color": car.get("color", "-"), "year": int(car.get("year", 0)),
                })
                existing_chassis.add(chassis)
                added.append(chassis)

        txt = f"✅ *Auction List Update ပြီး!*\n\n📊 ဖတ်ရတဲ့ ကား: {len(new_cars)} စီး\n✨ အသစ်ထည့်ခဲ့: {len(added)} စီး\n\n"
        if added:
            txt += "🆕 အသစ်ထည့်ခဲ့တာ:\n"
            for ch in added[:10]:
                txt += f"• `{ch}`\n"
            if len(added) > 10:
                txt += f"... နှင့် {len(added)-10} စီး ထပ်ရှိသေး\n"
        txt += f"\n📋 Database တွင် ယခု ကား {len(CARS)} စီး ရှိပြီ"
        await update.message.reply_text(txt, parse_mode='Markdown')
        return

    # ── Car Photo Mode ──
    await update.message.reply_text("🔍 ပုံကို စစ်နေတယ်... Chassis ရှာနေတယ် ⏳")

    chassis      = extract_chassis_from_text(caption) if caption else None
    price_match  = re.search(r'(?<![A-Z0-9])(\d{4,6})(?![A-Z0-9])', caption.upper()) if caption else None
    price        = int(price_match.group(1)) if price_match else None
    gemini_model = ""
    gemini_color = ""
    gemini_year  = 0  # ✅ year
    file_bytes   = None

    if not chassis:
        try:
            file       = await photo.get_file()
            file_bytes = bytes(await file.download_as_bytearray())
            result     = await gemini_ocr_chassis(file_bytes)
            chassis      = result.get("chassis", "")
            gemini_model = result.get("model", "")
            gemini_color = result.get("color", "")
            gemini_year  = result.get("year", 0)  # ✅ year ထုတ်ယူ
        except Exception as e:
            logger.error(f"Photo download error: {e}")

    car = find_by_chassis(chassis) if chassis else None

    image_url = ""
    if chassis and file_bytes:
        image_url = await upload_to_cloudinary(file_bytes, chassis)

    if car and price:
        user_name = update.effective_user.first_name or "Unknown"
        await save_price(car['chassis'], car['model'], car['color'], car['year'], price, user_name, image_url)
        year_str = str(car['year']) if car.get('year') and car['year'] != 0 else "—"
        await update.message.reply_text(
            f"✅ *Auto ထည့်ပြီးပါပြီ!*\n\n🚗 {car['model']} ({year_str})\n🔑 `{car['chassis']}`\n🎨 {car['color']}\n💰 ฿{price:,}\n\n🌐 [Web မှာကြည့်](https://kyawmintun08.github.io/Japan-Auction-Car-Checker/)",
            parse_mode='Markdown')
        await post_to_channel(context, car['chassis'], car['model'], car['color'], car['year'], price, image_url)

    elif car:
        year_str = str(car['year']) if car.get('year') and car['year'] != 0 else "—"
        pending_photo[user_id] = {
            "chassis": car['chassis'], "model": car['model'],
            "color": car['color'], "year": car['year'],
            "file_id": photo.file_id, "image_url": image_url
        }
        await update.message.reply_text(
            f"🚗 ကားတွေ့ပြီ!\n\n*{car['model']}* ({year_str})\n`{car['chassis']}`\n🎨 {car['color']}\n\n💰 ဈေး ရိုက်ထည့်ပါ (ဂဏန်းသာ):\nဥပမာ: `150000`",
            parse_mode='Markdown')

    elif chassis:
        guessed_model = gemini_model or guess_model_from_chassis(chassis)
        if not guessed_model or guessed_model == "UNKNOWN":
            guessed_model = guess_model_from_chassis(chassis)
        display_color = gemini_color if gemini_color else "-"
        display_year  = gemini_year if gemini_year and gemini_year != 0 else 0  # ✅ year သုံး
        year_str      = str(display_year) if display_year != 0 else "—"

        if price:
            user_name = update.effective_user.first_name or "Unknown"
            await save_price(chassis, guessed_model, display_color, display_year, price, user_name, image_url)
            await update.message.reply_text(
                f"✅ *Auto ထည့်ပြီးပါပြီ!*\n\n🚗 {guessed_model} ({year_str})\n🔑 `{chassis}`\n🎨 {display_color}\n💰 ฿{price:,}\n\n🌐 [Web မှာကြည့်](https://kyawmintun08.github.io/Japan-Auction-Car-Checker/)",
                parse_mode='Markdown')
            await post_to_channel(context, chassis, guessed_model, display_color, display_year, price, image_url)
        else:
            pending_photo[user_id] = {
                "chassis": chassis, "model": guessed_model, "color": display_color,
                "year": display_year, "file_id": photo.file_id, "image_url": image_url
            }
            if guessed_model and guessed_model != "UNKNOWN":
                await update.message.reply_text(
                    f"⚠️ Checklist မှာ မပါဘူး\n\n🚗 ခန့်မှန်း: *{guessed_model}* ({year_str})\n🔑 `{chassis}`\n🎨 {display_color}\n\n💰 ဈေး ရိုက်ထည့်ပါ:\nဥပမာ: `150000`",
                    parse_mode='Markdown')
            else:
                await update.message.reply_text(
                    f"⚠️ Chassis တွေ့ပြီ: `{chassis}`\n🎨 {display_color}\nChecklist မှာ မပါဘူး — ဈေး ရိုက်ထည့်ပါ:\nဥပမာ: `150000`",
                    parse_mode='Markdown')
    else:
        await update.message.reply_text(
            "⚠️ Chassis ဖတ်မရပါ\n\n💡 Gemini API limit ကုန်နေရင် Tesseract နဲ့ ကြိုးစားပြီးပါပြီ\n\nကိုယ်တိုင် ထည့်ပါ:\n`/price [chassis] [ဈေး]`\n\nဥပမာ: `/price NT32-504837 150000`",
            parse_mode='Markdown')

# ── Text Handler ──────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text    = update.message.text.strip()

    if user_id in pending_photo:
        if re.match(r'^[\d,]+$', text.replace(' ', '')):
            try:
                price     = int(text.replace(',', '').replace(' ', ''))
                data      = pending_photo.pop(user_id)
                user_name = update.effective_user.first_name or "Unknown"
                await save_price(data['chassis'], data['model'], data['color'], data['year'], price, user_name, data.get('image_url', ''))
                year_str = str(data['year']) if data.get('year') and data['year'] != 0 else "—"
                await update.message.reply_text(
                    f"✅ *ဈေးထည့်ပြီးပါပြီ!*\n\n🚗 {data['model']} ({year_str}) — `{data['chassis']}`\n💰 ฿{price:,}\n\n🌐 [Web မှာကြည့်](https://kyawmintun08.github.io/Japan-Auction-Car-Checker/)",
                    parse_mode='Markdown')
                await post_to_channel(context, data['chassis'], data['model'], data['color'], data['year'], price, data.get('image_url', ''))
                return
            except:
                pass

    chassis = extract_chassis_from_text(text)
    if chassis:
        car = find_by_chassis(chassis)
        if car:
            history      = get_price_history(car['chassis'])
            latest_price = history[-1]['price'] if history else None
            txt          = format_car_info(car, latest_price, history if history else None)
            keyboard     = [[InlineKeyboardButton("💰 ဈေးထည့်", callback_data=f"addprice_{car['chassis']}")]]
            await update.message.reply_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            guessed = guess_model_from_chassis(chassis)
            if guessed == "UNKNOWN":
                guessed = await guess_model_from_chassis_gemini(chassis)
            txt = (
                f"⚠️ `{chassis}` Checklist မှာ မပါဘူး\n🚗 ခန့်မှန်း Model: *{guessed}*\n\nဈေးထည့်လိုရင် `/price {chassis} [ဈေး]`"
                if guessed != "UNKNOWN"
                else f"⚠️ `{chassis}` Checklist မှာ မပါဘူး\n\nဈေးထည့်လိုရင် `/price {chassis} [ဈေး]`"
            )
            await update.message.reply_text(txt, parse_mode='Markdown')

# ── Callback Handler ───────────────────────────────────
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data.startswith("addprice_"):
        chassis = query.data.replace("addprice_", "")
        user_id = query.from_user.id
        car     = find_by_chassis(chassis)
        if car:
            pending_photo[user_id] = {
                "chassis": car['chassis'], "model": car['model'],
                "color": car['color'], "year": car['year'], "file_id": None
            }
        await query.message.reply_text(f"💰 `{chassis}` ဈေး ရိုက်ထည့်ပါ:\nဥပမာ: `150000`", parse_mode='Markdown')

# ── Membership Commands ────────────────────────────────
async def approve_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်")
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Format မှားတယ်\nဥပမာ: `/approve @username 1` သို့မဟုတ် `/approve 123456789 3`",
            parse_mode='Markdown')
        return

    username_or_id = context.args[0].replace('@', '')
    try:
        months = int(context.args[1])
    except:
        await update.message.reply_text("❌ လ အရေအတွက် ဂဏန်းထည့်ပါ\nဥပမာ: `/approve @username 1`", parse_mode='Markdown')
        return

    days = months * 30

    # ✅ BUG FIX: member_id=0 falsy bug — None သုံးပြင်ထားတယ်
    try:
        member_id       = int(username_or_id)
        member_username = username_or_id
    except ValueError:
        member_id       = None
        member_username = username_or_id

    try:
        async with httpx.AsyncClient() as client:
            await client.post(SHEET_WEBHOOK, json={
                "action":   "saveMember",
                "userId":   str(member_id) if member_id is not None else username_or_id,
                "username": member_username,
                "days":     days
            }, timeout=10, follow_redirects=True)
    except Exception as e:
        logger.error(f"saveMember error: {e}")

    try:
        invite     = await context.bot.create_chat_invite_link(
            chat_id=CHANNEL_ID, member_limit=1,
            expire_date=int((__import__('time').time()) + days * 86400))
        invite_url = invite.invite_link
    except Exception as e:
        invite_url = None
        logger.error(f"Invite link error: {e}")

    expire_date = (datetime.now() + timedelta(days=days)).strftime("%d/%m/%Y")
    txt = (
        f"✅ <b>Membership Approved!</b>\n\n"
        f"👤 @{member_username}\n"
        f"📅 သက်တမ်း: <b>{months} လ</b>\n"
        f"⏰ ကုန်ဆုံးရက်: <code>{expire_date}</code>\n"
    )
    if invite_url:
        txt += f"\n🔗 Invite Link:\n{invite_url}"
    await update.message.reply_text(txt, parse_mode='HTML')

async def members_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်")
        return
    try:
        async with httpx.AsyncClient() as client:
            resp    = await client.post(SHEET_WEBHOOK, json={"action": "getMembers"}, timeout=10, follow_redirects=True)
            members = resp.json().get("members", [])
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        return
    if not members:
        await update.message.reply_text("👥 Member မရှိသေးဘူး")
        return
    active  = [m for m in members if m['status'] == 'ACTIVE']
    expired = [m for m in members if m['status'] == 'EXPIRED']
    txt = f"👥 *Members စာရင်း*\n✅ Active: {len(active)} | ❌ Expired: {len(expired)}\n\n*✅ Active:*\n"
    for m in active:
        txt += f"• @{m['username']} — ကုန်: `{m['expireDate']}`\n"
    if expired:
        txt += "\n*❌ Expired:*\n"
        for m in expired[:5]:
            txt += f"• @{m['username']} — `{m['expireDate']}`\n"
    await update.message.reply_text(txt, parse_mode='Markdown')

async def kick_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်")
        return
    if not context.args:
        await update.message.reply_text("❌ Format: `/kick 123456789`", parse_mode='Markdown')
        return
    try:
        target_id = int(context.args[0])
        await context.bot.ban_chat_member(chat_id=CHANNEL_ID, user_id=target_id)
        await context.bot.unban_chat_member(chat_id=CHANNEL_ID, user_id=target_id)
        await update.message.reply_text(f"✅ User `{target_id}` ကို channel ကထုတ်ပြီ", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def check_expired_members(context):
    """Auto kick expired members every 12 hours"""
    try:
        async with httpx.AsyncClient() as client:
            resp    = await client.post(SHEET_WEBHOOK, json={"action": "getMembers"}, timeout=10, follow_redirects=True)
            members = resp.json().get("members", [])
        for m in members:
            if m['status'] == 'EXPIRED' and m['userId'].isdigit():
                try:
                    await context.bot.ban_chat_member(chat_id=CHANNEL_ID, user_id=int(m['userId']))
                    await context.bot.unban_chat_member(chat_id=CHANNEL_ID, user_id=int(m['userId']))
                    logger.info(f"Auto kicked: {m['username']}")
                except Exception as e:
                    logger.error(f"Auto kick error {m['username']}: {e}")
    except Exception as e:
        logger.error(f"check_expired_members error: {e}")

# ── Main ───────────────────────────────────────────────
async def main():
    logger.info("Bot starting...")
    async with httpx.AsyncClient() as client:
        await client.post(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook", params={"drop_pending_updates": True})

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",   start))
    app.add_handler(CommandHandler("find",    find_car))
    app.add_handler(CommandHandler("model",   find_model))
    app.add_handler(CommandHandler("price",   add_price))
    app.add_handler(CommandHandler("history", price_history))
    app.add_handler(CommandHandler("list",    list_cars))
    app.add_handler(CommandHandler("web",     web_link))
    app.add_handler(CommandHandler("approve", approve_member))
    app.add_handler(CommandHandler("members", members_list))
    app.add_handler(CommandHandler("kick",    kick_member))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.job_queue.run_repeating(check_expired_members, interval=43200, first=60)

    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
    logger.info("Bot is polling now!")
    await asyncio.Event().wait()


if __name__ == '__main__':
    asyncio.run(main())
