import asyncio
import os
import re
import random
import string
import logging
import httpx
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram import BotCommandScopeAllPrivateChats, BotCommandScopeChat
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

try:
    import pytesseract
    from PIL import Image
    from io import BytesIO
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Environment Variables ──────────────────────────────
GEMINI_API_KEY        = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL          = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
TOKEN                 = os.environ.get('BOT_TOKEN', '')
SHEET_WEBHOOK         = os.environ.get('SHEET_WEBHOOK', '')
CHANNEL_ID            = os.environ.get('CHANNEL_ID', '-1003749046571')
ADMIN_IDS             = [int(x) for x in os.environ.get('ADMIN_IDS', '').split(',') if x.strip().isdigit()]
ADMIN_USERNAME        = os.environ.get('ADMIN_USERNAME', '')
CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME', '')
CLOUDINARY_API_KEY    = os.environ.get('CLOUDINARY_API_KEY', '')
CLOUDINARY_API_SECRET = os.environ.get('CLOUDINARY_API_SECRET', '')

# ── Membership Plan Pricing (ks) ──────────────────────
PLAN_CH_1M  = int(os.environ.get('PLAN_CH_1M',  '15000'))
PLAN_CH_2M  = int(os.environ.get('PLAN_CH_2M',  '30000'))
PLAN_CH_3M  = int(os.environ.get('PLAN_CH_3M',  '40000'))
PLAN_CH_5M  = int(os.environ.get('PLAN_CH_5M',  '70000'))
PLAN_WEB_1M = int(os.environ.get('PLAN_WEB_1M', '20000'))
PLAN_WEB_2M = int(os.environ.get('PLAN_WEB_2M', '40000'))
PLAN_WEB_3M = int(os.environ.get('PLAN_WEB_3M', '45000'))
PAYMENT_INFO = os.environ.get('PAYMENT_INFO', 'KPay / Wave: ဆက်သွယ်ရန် @' + ADMIN_USERNAME)

LOC_MAESOT = "MaeSot Freezone"
LOC_KLANG9 = "Klang9 Freezone"

PLAN_PRICES = {
    "CH":  {1: PLAN_CH_1M,  2: PLAN_CH_2M,  3: PLAN_CH_3M,  5: PLAN_CH_5M},
    "WEB": {1: PLAN_WEB_1M, 2: PLAN_WEB_2M, 3: PLAN_WEB_3M},
}
PLAN_NAMES = {
    "CH":  "📱 Channel Only",
    "WEB": "📱+🌐 Channel + Web",
}

CHASSIS_PREFIX_MAP = {
    "VZNY12":"ADVAN",
    "GRS200":"CROWN","GRS201":"CROWN","GRS202":"CROWN","GRS204":"CROWN","GRS210":"CROWN",
    "GWS204":"CROWN HYBRID",
    "ZGE20":"WISH","ZGE21":"WISH","ZGE22":"WISH","ZGE25":"WISH",
    "GRX133":"MARK X",
    "GGH25":"ALPHARD","GGH20":"ALPHARD","MNH15":"ALPHARD","MNH10":"ALPHARD",
    "ANH15":"ALPHARD","ANH20":"ALPHARD",
    "ZRR75":"VOXY","ZRR70":"VOXY","ZWR80":"VOXY",
    "KDH201":"HIACE VAN","KDH200":"HIACE VAN","KDH205":"HIACE VAN","TRH200":"HIACE VAN",
    "NCP165":"SUCCEED VAN","NCP160":"SUCCEED VAN",
    "NCP59":"SUCCEED WAGON","NCP58":"SUCCEED WAGON",
    "UZJ100":"LAND CRUISER","HDJ101":"LAND CRUISER","HZJ105":"LAND CRUISER",
    "KDN185":"HILUX SURF","KZN185":"HILUX SURF","VZN185":"HILUX SURF",
    "KDJ95":"LAND CRUISER PRADO","KZJ95":"LAND CRUISER PRADO","UZJ101":"LAND CRUISER",
    "USF40":"LEXUS LS","USF41":"LEXUS LS",
    "ACU25":"KLUGER","ACU20":"KLUGER","MCU25":"KLUGER",
    "AZE0":"LEAF",
    "XZC610":"DUTRO","XZU548":"DUTRO TRUCK","XZU300":"DUTRO TRUCK",
    "ACA33":"VANGUARD","ACA38":"VANGUARD","CW4YL":"QUON",
    "NT31":"X-TRAIL","NT32":"X-TRAIL","DNT31":"X-TRAIL","T31":"X-TRAIL",
    "YF15":"JUKE","F15":"JUKE","NF15":"JUKE",
    "SK82TN":"VANETTE TRUCK","SK82VN":"VANETTE TRUCK",
    "GP1":"FIT HYBRID","GP5":"FIT HYBRID","GP6":"FIT HYBRID",
    "GP7":"FIT SHUTTLE HYBRID","GP2":"FIT SHUTTLE HYBRID",
    "GK3":"FIT","GK5":"FIT","GE6":"FIT","GE8":"FIT",
    "GB3":"FREED","GB4":"FREED",
    "RE4":"CRV","RE3":"CRV","RD1":"CRV","RD5":"CRV",
    "ZE2":"INSIGHT","ZE3":"INSIGHT",
    "KE2AW":"CX5","KE2FW":"CX5","KE5FW":"CX5",
    "SKP2T":"BONGO TRUCK","SLP2L":"BONGO TRUCK",
    "S210P":"HIJET TRUCK","S211P":"HIJET TRUCK","S510P":"HIJET TRUCK",
    "S500P":"HIJET TRUCK","S501P":"HIJET TRUCK",
    "S321V":"HIJET VAN","S331V":"HIJET VAN",
    "S200P":"HIJET TRUCK","S201P":"HIJET TRUCK",
    "S211U":"PIXIS TRUCK","S500U":"PIXIS TRUCK",
    "S510J":"SAMBAR TRUCK","S201J":"SAMBAR TRUCK",
    "FE74BV":"CANTER","FE82BS":"CANTER","FBA30":"CANTER",
    "FE82D":"CANTER","FE82EE":"CANTER","FE72EE":"CANTER",
    "FE84DV":"CANTER","FE83D":"CANTER","FE70B":"CANTER",
    "FE73EB":"CANTER","FE70EB":"CANTER","FEA20":"CANTER",
    "FB70BB":"CANTER GUTS",
    "FK61FM":"FUSO FIGHTER","FQ62F":"FUSO FIGHTER","FK71F":"FUSO FIGHTER",
    "FEA50":"FUSO TRUCK","FBA20":"FUSO TRUCK",
    "FY54JTY":"SUPER GREAT","FS54JZ":"SUPER GREAT",
    "FV50JJX":"SUPER GREAT","FV50MJX":"SUPER GREAT",
    "FC6JLW":"RANGER","FC7JKY":"RANGER",
    "FW1EXW":"PROFIA","SH1EDX":"PROFIA",
    "CG5ZA":"UD","CG5ZE":"UD","CG4ZA":"UD","CG4YA":"UD",
    "CD5ZA":"UD","CD4ZA":"UD","CD48R":"BIG THUMB",
    "MK35A":"CONDOR","MK38L":"CONDOR","MK36A":"CONDOR",
    "MK36B":"UD","MK38C":"UD",
    "JNCMM60C6GU":"UD","JNCMM60G6GU":"UD","GK6XA":"QUON","JNCLSC":"CONDOR",
    "V98W":"PAJERO","V97W":"PAJERO","V93W":"PAJERO","V75W":"PAJERO","V78W":"PAJERO",
    "WVWZZZ":"NEW BEETLE",
}

CARS = [
    # ── MaeSot Freezone ──
    {"chassis":"MNH15-0039667","model":"ALPHARD","color":"WHITE","year":2005,"loc":"MaeSot"},
    {"chassis":"CD48R-30111","model":"BIG THUMB","color":"GREEN","year":2005,"loc":"MaeSot"},
    {"chassis":"FE82EEV500266","model":"CANTER","color":"WHITE","year":2002,"loc":"MaeSot"},
    {"chassis":"FE84DV-550674","model":"CANTER","color":"BLUE","year":2008,"loc":"MaeSot"},
    {"chassis":"FB70BB-512392","model":"CANTER GUTS","color":"WHITE","year":2005,"loc":"MaeSot"},
    {"chassis":"MK35A-10405","model":"CONDOR","color":"PEARL WHITE","year":2006,"loc":"MaeSot"},
    {"chassis":"JNCLSC0A1GU006386","model":"CONDOR","color":"WHITE","year":2016,"loc":"MaeSot"},
    {"chassis":"GRS210-6004548","model":"CROWN","color":"PEARL WHITE","year":2013,"loc":"MaeSot"},
    {"chassis":"GRS200-0001831","model":"CROWN","color":"WHITE","year":2008,"loc":"MaeSot"},
    {"chassis":"GRS200-0020080","model":"CROWN","color":"WHITE","year":2008,"loc":"MaeSot"},
    {"chassis":"GRS202-0002603","model":"CROWN","color":"WHITE","year":2008,"loc":"MaeSot"},
    {"chassis":"XZC610-0001005","model":"DUTRO","color":"WHITE","year":2011,"loc":"MaeSot"},
    {"chassis":"GE6-1539486","model":"FIT","color":"PEARL WHITE","year":2011,"loc":"MaeSot"},
    {"chassis":"GP5-3032237","model":"FIT HYBRID","color":"PEARL WHITE","year":2014,"loc":"MaeSot"},
    {"chassis":"GP1-1131390","model":"FIT HYBRID","color":"WHITE","year":2012,"loc":"MaeSot"},
    {"chassis":"GP1-1049821","model":"FIT HYBRID","color":"PEARL WHITE","year":2011,"loc":"MaeSot"},
    {"chassis":"GP7-1000970","model":"FIT SHUTTLE HYBRID","color":"PEARL WHITE","year":2015,"loc":"MaeSot"},
    {"chassis":"GP2-3106770","model":"FIT SHUTTLE HYBRID","color":"SILVER","year":2013,"loc":"MaeSot"},
    {"chassis":"FK61FM765129","model":"FUSO FIGHTER","color":"WHITE","year":2003,"loc":"MaeSot"},
    {"chassis":"KDH201-0140123","model":"HIACE VAN","color":"WHITE","year":2014,"loc":"MaeSot"},
    {"chassis":"S211P-0217418","model":"HIJET TRUCK","color":"WHITE","year":2013,"loc":"MaeSot"},
    {"chassis":"S210P-2037788","model":"HIJET TRUCK","color":"WHITE","year":2005,"loc":"MaeSot"},
    {"chassis":"S510P-0173458","model":"HIJET TRUCK","color":"WHITE","year":2017,"loc":"MaeSot"},
    {"chassis":"UZJ100-0151432","model":"LAND CRUISER","color":"SILVER","year":2004,"loc":"MaeSot"},
    {"chassis":"USF40-5006069","model":"LEXUS LS","color":"WHITE","year":2006,"loc":"MaeSot"},
    {"chassis":"WVWZZZ16ZDM638030","model":"NEW BEETLE","color":"BLACK","year":2013,"loc":"MaeSot"},
    {"chassis":"ZRR75-0068964","model":"VOXY","color":"PEARL WHITE","year":2010,"loc":"MaeSot"},
    {"chassis":"V98W-0300140","model":"PAJERO","color":"PEARL WHITE","year":2010,"loc":"MaeSot"},
    {"chassis":"S211U-0000227","model":"PIXIS TRUCK","color":"WHITE","year":2011,"loc":"MaeSot"},
    {"chassis":"FC7JKY-14910","model":"RANGER","color":"BLUE","year":2011,"loc":"MaeSot"},
    {"chassis":"NCP165-0001505","model":"SUCCEED VAN","color":"PEARL WHITE","year":2014,"loc":"MaeSot"},
    {"chassis":"NCP59-0012188","model":"SUCCEED WAGON","color":"SILVER","year":2005,"loc":"MaeSot"},
    {"chassis":"FV50JJX-530670","model":"SUPER GREAT","color":"BLACK","year":2004,"loc":"MaeSot"},
    {"chassis":"CG5ZA-30374","model":"UD","color":"PEARL WHITE","year":2014,"loc":"MaeSot"},
    {"chassis":"CD5ZA-30191","model":"UD","color":"SILVER","year":2014,"loc":"MaeSot"},
    {"chassis":"CG4ZA-01338","model":"UD","color":"LIGHT BLUE","year":2006,"loc":"MaeSot"},
    {"chassis":"ZGE22-0005423","model":"WISH","color":"BLACK","year":2011,"loc":"MaeSot"},
    {"chassis":"ZGE20-0010786","model":"WISH","color":"PEARL WHITE","year":2009,"loc":"MaeSot"},
    {"chassis":"ZGE25-0015283","model":"WISH","color":"WHITE","year":2011,"loc":"MaeSot"},
    {"chassis":"NT32-504837","model":"X-TRAIL","color":"BLACK","year":2014,"loc":"MaeSot"},
    {"chassis":"NT32-531693","model":"X-TRAIL","color":"BLACK","year":2015,"loc":"MaeSot"},
    {"chassis":"NT31-316873","model":"X-TRAIL","color":"PEARL WHITE","year":2013,"loc":"MaeSot"},
    {"chassis":"NT32-508661","model":"X-TRAIL","color":"PEARL WHITE","year":2015,"loc":"MaeSot"},
    {"chassis":"SKP2T-108324","model":"BONGO TRUCK","color":"WHITE","year":2013,"loc":"MaeSot"},
    {"chassis":"FE82D-570692","model":"CANTER","color":"WHITE","year":2010,"loc":"MaeSot"},
    {"chassis":"FE82D-530430","model":"CANTER","color":"PEARL WHITE","year":2007,"loc":"MaeSot"},
    {"chassis":"FE72EE-500637","model":"CANTER","color":"WHITE","year":2003,"loc":"MaeSot"},
    {"chassis":"GRS201-0006860","model":"CROWN","color":"SILVER","year":2011,"loc":"MaeSot"},
    {"chassis":"GRS200-0061216","model":"CROWN","color":"PEARL WHITE","year":2011,"loc":"MaeSot"},
    {"chassis":"GRS200-0063933","model":"CROWN","color":"BLACK","year":2011,"loc":"MaeSot"},
    {"chassis":"GWS204-0025870","model":"CROWN HYBRID","color":"SILVER","year":2012,"loc":"MaeSot"},
    {"chassis":"GK3-1029686","model":"FIT","color":"WHITE","year":2014,"loc":"MaeSot"},
    {"chassis":"GP1-1011906","model":"FIT HYBRID","color":"BLUE","year":2010,"loc":"MaeSot"},
    {"chassis":"GP5-3040254","model":"FIT HYBRID","color":"WHITE","year":2014,"loc":"MaeSot"},
    {"chassis":"GP1-1096649","model":"FIT HYBRID","color":"BLACK","year":2011,"loc":"MaeSot"},
    {"chassis":"GP1-1014176","model":"FIT HYBRID","color":"PEARL WHITE","year":2010,"loc":"MaeSot"},
    {"chassis":"GB3-1312198","model":"FREED","color":"PEARL WHITE","year":2010,"loc":"MaeSot"},
    {"chassis":"FQ62F-520185","model":"FUSO FIGHTER","color":"WHITE","year":2008,"loc":"MaeSot"},
    {"chassis":"FEA50-521744","model":"FUSO TRUCK","color":"PEARL WHITE","year":2013,"loc":"MaeSot"},
    {"chassis":"KDH201-0056284","model":"HIACE VAN","color":"WHITE","year":2010,"loc":"MaeSot"},
    {"chassis":"S211P-0276262","model":"HIJET TRUCK","color":"SILVER","year":2014,"loc":"MaeSot"},
    {"chassis":"S510P-0147424","model":"HIJET TRUCK","color":"WHITE","year":2017,"loc":"MaeSot"},
    {"chassis":"S210P-2060815","model":"HIJET TRUCK","color":"WHITE","year":2006,"loc":"MaeSot"},
    {"chassis":"S510P-0149349","model":"HIJET TRUCK","color":"SILVER","year":2017,"loc":"MaeSot"},
    {"chassis":"S210P-2006882","model":"HIJET TRUCK","color":"SILVER","year":2005,"loc":"MaeSot"},
    {"chassis":"ZE2-1130682","model":"INSIGHT","color":"WHITE","year":2009,"loc":"MaeSot"},
    {"chassis":"YF15-033275","model":"JUKE","color":"WHITE","year":2011,"loc":"MaeSot"},
    {"chassis":"HDJ101-0031030","model":"LAND CRUISER","color":"PEARL WHITE","year":2007,"loc":"MaeSot"},
    {"chassis":"AZE0-062459","model":"LEAF","color":"PEARL WHITE","year":2013,"loc":"MaeSot"},
    {"chassis":"GRX133-6003681","model":"MARK X","color":"SILVER","year":2013,"loc":"MaeSot"},
    {"chassis":"WVWZZZ16ZDM685003","model":"NEW BEETLE","color":"BLACK","year":2013,"loc":"MaeSot"},
    {"chassis":"NCP165-0001511","model":"SUCCEED VAN","color":"PEARL WHITE","year":2014,"loc":"MaeSot"},
    {"chassis":"GK6XA-10555","model":"QUON","color":"WHITE","year":2013,"loc":"MaeSot"},
    {"chassis":"FC6JLW-10241","model":"RANGER","color":"PEARL WHITE","year":2006,"loc":"MaeSot"},
    {"chassis":"FY54JTY530030","model":"SUPER GREAT","color":"PEARL WHITE","year":2003,"loc":"MaeSot"},
    {"chassis":"FS54JZ-570431","model":"SUPER GREAT","color":"BLACK","year":2010,"loc":"MaeSot"},
    {"chassis":"FV50MJX520729","model":"SUPER GREAT","color":"BLACK","year":2001,"loc":"MaeSot"},
    {"chassis":"CG5ZA-01150","model":"UD","color":"GREEN","year":2011,"loc":"MaeSot"},
    {"chassis":"CG5ZE-30138","model":"UD","color":"WHITE","year":2015,"loc":"MaeSot"},
    {"chassis":"MK38L-30952","model":"UD","color":"YELLOW","year":2014,"loc":"MaeSot"},
    {"chassis":"MK36A-12656","model":"UD","color":"WHITE","year":2006,"loc":"MaeSot"},
    {"chassis":"ZGE20-0041580","model":"WISH","color":"PEARL WHITE","year":2009,"loc":"MaeSot"},
    {"chassis":"ZGE20-0004342","model":"WISH","color":"WHITE","year":2009,"loc":"MaeSot"},
    {"chassis":"NT32-024640","model":"X-TRAIL","color":"BLACK","year":2014,"loc":"MaeSot"},
    {"chassis":"NT32-037944","model":"X-TRAIL","color":"BLACK","year":2015,"loc":"MaeSot"},
    {"chassis":"NT31-244285","model":"X-TRAIL","color":"PEARL WHITE","year":2012,"loc":"MaeSot"},
    {"chassis":"DNT31-209100","model":"X-TRAIL","color":"WHITE","year":2011,"loc":"MaeSot"},
    # ── Klang9 Freezone ──
    {"chassis":"VZNY12-070391","model":"ADVAN","color":"WHITE","year":2017,"loc":"Klang9"},
    {"chassis":"GGH20-8002412","model":"ALPHARD","color":"PEARL WHITE","year":2008,"loc":"Klang9"},
    {"chassis":"MNH10-0099576","model":"ALPHARD","color":"PEARL WHITE","year":2007,"loc":"Klang9"},
    {"chassis":"SLP2L-102206","model":"BONGO TRUCK","color":"WHITE","year":2017,"loc":"Klang9"},
    {"chassis":"FEA20-520134","model":"CANTER","color":"SILVER","year":2013,"loc":"Klang9"},
    {"chassis":"FE73EB-501814","model":"CANTER","color":"LIGHT GREEN","year":2003,"loc":"Klang9"},
    {"chassis":"FE70EB-506566","model":"CANTER","color":"WHITE","year":2004,"loc":"Klang9"},
    {"chassis":"GRS204-0014299","model":"CROWN","color":"WHITE","year":2010,"loc":"Klang9"},
    {"chassis":"RE4-1006211","model":"CRV","color":"WHITE","year":2006,"loc":"Klang9"},
    {"chassis":"KE2AW-115142","model":"CX5","color":"WHITE","year":2013,"loc":"Klang9"},
    {"chassis":"GP5-3037138","model":"FIT HYBRID","color":"PEARL WHITE","year":2014,"loc":"Klang9"},
    {"chassis":"GP5-3216073","model":"FIT HYBRID","color":"PEARL WHITE","year":2015,"loc":"Klang9"},
    {"chassis":"GB3-1112824","model":"FREED","color":"PEARL WHITE","year":2009,"loc":"Klang9"},
    {"chassis":"FK71F-701985","model":"FUSO FIGHTER","color":"GREEN","year":2007,"loc":"Klang9"},
    {"chassis":"S211P-0042777","model":"HIJET TRUCK","color":"SILVER","year":2009,"loc":"Klang9"},
    {"chassis":"S211P-0138980","model":"HIJET TRUCK","color":"WHITE","year":2011,"loc":"Klang9"},
    {"chassis":"KDN185-0001271","model":"HILUX SURF","color":"SILVER","year":2000,"loc":"Klang9"},
    {"chassis":"ZE2-1128237","model":"INSIGHT","color":"SILVER","year":2009,"loc":"Klang9"},
    {"chassis":"NF15-060818","model":"JUKE","color":"WHITE","year":2012,"loc":"Klang9"},
    {"chassis":"ACU25-0032701","model":"KLUGER","color":"WHITE","year":2004,"loc":"Klang9"},
    {"chassis":"USF40-5079528","model":"LEXUS LS","color":"PEARL WHITE","year":2008,"loc":"Klang9"},
    {"chassis":"WVWZZZ16ZDM635922","model":"NEW BEETLE","color":"RED","year":2013,"loc":"Klang9"},
    {"chassis":"GK6XA-10291","model":"QUON","color":"GREEN","year":2012,"loc":"Klang9"},
    {"chassis":"CW4YL-30468","model":"QUON","color":"SILVER","year":2009,"loc":"Klang9"},
    {"chassis":"NCP165-0056792","model":"SUCCEED VAN","color":"WHITE","year":2018,"loc":"Klang9"},
    {"chassis":"NCP59-0024963","model":"SUCCEED WAGON","color":"DARK BLUE","year":2012,"loc":"Klang9"},
    {"chassis":"CG5ZA-12819","model":"UD","color":"PEARL WHITE","year":2014,"loc":"Klang9"},
    {"chassis":"CG5ZA-11731","model":"UD","color":"WHITE","year":2013,"loc":"Klang9"},
    {"chassis":"CG4YA-00054","model":"UD","color":"WHITE","year":2006,"loc":"Klang9"},
    {"chassis":"CD4ZA-31233","model":"UD","color":"GREEN","year":2009,"loc":"Klang9"},
    {"chassis":"SK82TN-319474","model":"VANETTE TRUCK","color":"WHITE","year":2005,"loc":"Klang9"},
    {"chassis":"ZRR75-0083512","model":"VOXY","color":"PEARL WHITE","year":2011,"loc":"Klang9"},
    {"chassis":"ZGE25-0020690","model":"WISH","color":"PEARL WHITE","year":2012,"loc":"Klang9"},
    {"chassis":"ZGE20-0154748","model":"WISH","color":"PEARL WHITE","year":2013,"loc":"Klang9"},
    {"chassis":"ZGE20-0152288","model":"WISH","color":"BLACK","year":2012,"loc":"Klang9"},
    {"chassis":"NT32-036496","model":"X-TRAIL","color":"BLACK","year":2014,"loc":"Klang9"},
    {"chassis":"NT31-212796","model":"X-TRAIL","color":"PEARL WHITE","year":2011,"loc":"Klang9"},
    {"chassis":"NT31-049247","model":"X-TRAIL","color":"BLACK","year":2009,"loc":"Klang9"},
    {"chassis":"DNT31-205472","model":"X-TRAIL","color":"PEARL WHITE","year":2011,"loc":"Klang9"},
    {"chassis":"NT32-038921","model":"X-TRAIL","color":"PEARL WHITE","year":2015,"loc":"Klang9"},
]

PRICE_HISTORY  = []
pending_photo  = {}
pending_payment = {}   # user_id -> {package, months, amount, username, name}
pending_updateid = {}  # user_id -> {target_username, old_id, new_id}
pending_edit     = {}  # user_id -> {chassis, field}  (field: price/color/model)
warned_3days   = set()
rate_limit     = {}    # user_id -> [datetime, ...]

# ── Rate Limiting ──────────────────────────────────────
def check_rate_limit(user_id: int, max_req: int = 10, window: int = 60) -> bool:
    """Returns True = OK, False = exceeded"""
    now = datetime.now()
    if user_id not in rate_limit:
        rate_limit[user_id] = []
    rate_limit[user_id] = [t for t in rate_limit[user_id]
                           if (now - t).total_seconds() < window]
    if len(rate_limit[user_id]) >= max_req:
        return False
    rate_limit[user_id].append(now)
    return True

# ── Password Generator ─────────────────────────────────
def generate_password() -> str:
    """Generate password like KMT-A4B9C2"""
    letters = random.choices(string.ascii_uppercase, k=3)
    digits  = random.choices(string.digits, k=3)
    mixed   = [letters[0], digits[0], letters[1], digits[1], letters[2], digits[2]]
    return "KMT-" + "".join(mixed)

# ── Helpers ───────────────────────────────────────────
def loc_display(loc_key: str) -> str:
    return LOC_KLANG9 if loc_key == "Klang9" else LOC_MAESOT

async def get_member_package(user_id: int) -> str | None:
    """
    Returns member package ('CH' or 'WEB') if active, None if not a member.
    Admin always returns 'WEB' (full access).
    """
    if user_id in ADMIN_IDS:
        return "WEB"
    try:
        sheet_id = os.environ.get('SHEET_ID', '')
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:json&sheet=Members&_={int(datetime.now().timestamp())}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=10)
        text = resp.text
        import json as _json
        raw  = _json.loads(text[text.index('{'):text.rindex('}')+1])
        rows = raw.get('table', {}).get('rows', [])
        now  = datetime.now()
        for row in rows:
            c = row.get('c', [])
            if not c: continue
            # col 0 = UserID, col 3 = ExpireDate (formatted), col 4 = STATUS, col 6 = PACKAGE
            uid_cell    = c[0] if len(c) > 0 else None
            expire_cell = c[3] if len(c) > 3 else None
            status_cell = c[4] if len(c) > 4 else None
            pkg_cell    = c[6] if len(c) > 6 else None
            if not uid_cell: continue
            uid_val = uid_cell.get('f') or str(uid_cell.get('v',''))
            uid_val = uid_val.replace('.0','').strip()
            if uid_val != str(user_id): continue
            # Found user — check status & expiry
            status = (status_cell.get('v','') if status_cell else '').upper()
            expire_str = (expire_cell.get('f','') if expire_cell else '')
            try:
                ep = expire_str.split('/')
                expire_date = datetime(int(ep[2]), int(ep[1]), int(ep[0]))
            except:
                expire_date = datetime(2000,1,1)
            if status == 'ACTIVE' and expire_date >= now:
                pkg = (pkg_cell.get('v','CH') if pkg_cell else 'CH') or 'CH'
                return str(pkg).upper()
            return None  # Found but expired/inactive
        return None  # Not found
    except Exception as e:
        logger.error(f"get_member_package: {e}")
        return None

def guess_model_from_chassis(chassis_input: str) -> str:
    cu = chassis_input.upper().strip()
    for prefix in sorted(CHASSIS_PREFIX_MAP.keys(), key=len, reverse=True):
        if cu.startswith(prefix):
            return CHASSIS_PREFIX_MAP[prefix]
    return "UNKNOWN"

async def guess_model_gemini(chassis_input: str) -> str:
    if not GEMINI_API_KEY:
        return "UNKNOWN"
    try:
        prefix  = chassis_input.split("-")[0] if "-" in chassis_input else chassis_input[:6]
        url     = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents":[{"parts":[{"text":f"What Japanese car model has chassis prefix '{prefix}'? Reply ONLY the model name UPPERCASE. If unknown reply UNKNOWN."}]}]}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=15)
        data = resp.json()
        if "candidates" in data:
            m = data["candidates"][0]["content"]["parts"][0]["text"].strip().upper().split("\n")[0].strip()
            return m if m and m != "UNKNOWN" else "UNKNOWN"
    except Exception as e:
        logger.error(f"Gemini model: {e}")
    return "UNKNOWN"

def find_by_chassis(chassis_input: str):
    c = chassis_input.upper().strip()
    for car in CARS:
        if car["chassis"].upper() == c:
            return car
    return None

def find_by_model(model_input: str):
    m = model_input.upper().strip()
    return [c for c in CARS if m in c["model"].upper()]

def extract_chassis_from_text(text: str):
    text = text.upper().strip()
    for pattern in [
        r'[A-Z]{1,5}\d{1,4}[A-Z]{0,2}\d{0,2}-\d{4,7}',
        r'[A-Z]{2,6}\d{2,4}-\d{4,7}',
        r'[A-Z0-9]{4,20}-\d{4,7}',
    ]:
        matches = re.findall(pattern, text)
        if matches:
            return max(matches, key=len)
    return None

def get_price_history(chassis: str):
    return [p for p in PRICE_HISTORY if p["chassis"] == chassis]

def ys(year) -> str:
    return str(year) if year and year != 0 else "—"

def format_car_info(car, price=None, history=None) -> str:
    txt = (
        f"🚗 *{car['model']}* ({ys(car.get('year',0))})\n"
        f"🔑 `{car['chassis']}`\n"
        f"🎨 {car['color']}\n"
        f"📍 {loc_display(car.get('loc','MaeSot'))}\n"
    )
    if price:
        txt += f"💰 ฿{price:,}\n"
    if history:
        txt += f"\n📈 *မှတ်တမ်း ({len(history)} ကြိမ်):*\n"
        for h in history[-5:]:
            txt += f"  • {h['date']} → ฿{h['price']:,}\n"
    txt += f"\n🌐 [Web မှာကြည့်](https://kyawmintun08.github.io/Japan-Auction-Car-Checker-/)"
    return txt

async def upload_to_cloudinary(file_bytes: bytes, chassis: str) -> str:
    if not all([CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET]):
        return ""
    try:
        import base64, hashlib, time
        ts        = str(int(time.time()))
        public_id = f"auction/{chassis.replace('-','_')}_{ts}"
        sig_str   = f"public_id={public_id}&timestamp={ts}{CLOUDINARY_API_SECRET}"
        signature = hashlib.sha1(sig_str.encode()).hexdigest()
        img_b64   = base64.b64encode(file_bytes).decode()
        url       = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/image/upload"
        payload   = {"file":f"data:image/jpeg;base64,{img_b64}","public_id":public_id,
                     "timestamp":ts,"api_key":CLOUDINARY_API_KEY,"signature":signature}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, data=payload, timeout=30)
        return resp.json().get("secure_url","")
    except Exception as e:
        logger.error(f"Cloudinary: {e}")
        return ""

async def save_price(chassis, model, color, year, price, user_name, image_url="", location=LOC_MAESOT):
    now   = datetime.now().strftime("%d/%m/%Y")
    entry = {"chassis":chassis,"model":model,"color":color,"year":year,
             "price":price,"date":now,"location":location,
             "added_by":user_name,"image_url":image_url}
    PRICE_HISTORY.append(entry)
    if SHEET_WEBHOOK:
        try:
            async with httpx.AsyncClient() as client:
                await client.post(SHEET_WEBHOOK, json=entry, timeout=10, follow_redirects=True)
        except Exception as e:
            logger.error(f"save_price: {e}")
    return entry

async def post_to_channel(context, chassis, model, color, year, price, image_url="", location=LOC_MAESOT):
    if not CHANNEL_ID:
        return
    text = (
        f"🚗 *ကားသစ်ဝင်ပြီ!*\n"
        f"━━━━━━━━━━━━━━\n"
        f"🔑 Chassis : `{chassis}`\n"
        f"🚘 Model   : *{model}*\n"
        f"🎨 Color   : {color or '—'}\n"
        f"📅 Year    : {ys(year)}\n"
        f"💰 Price   : *฿{int(price):,}*\n"
        f"📍 {location}\n"
        f"━━━━━━━━━━━━━━\n"
        f"🌐 [Japan Auction Car Checker](https://kyawmintun08.github.io/Japan-Auction-Car-Checker-/)"
    )
    try:
        if image_url:
            await context.bot.send_photo(chat_id=CHANNEL_ID, photo=image_url, caption=text, parse_mode='Markdown')
        else:
            await context.bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Channel post: {e}")

async def notify_admins(context, text: str, reply_markup=None):
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id, text=text,
                parse_mode='Markdown', reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Admin notify {admin_id}: {e}")

async def kick_with_retry(context, user_id: int, max_retries: int = 3) -> bool:
    """Kick member with retry. Returns True if successful."""
    for attempt in range(max_retries):
        try:
            await context.bot.ban_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
            await context.bot.unban_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
            return True
        except Exception as e:
            logger.error(f"Kick attempt {attempt+1} for {user_id}: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(5)
    return False

# ── Gemini Slip Reader ────────────────────────────────
async def gemini_read_slip(file_bytes: bytes) -> dict:
    """Read Myanmar payment slip with Gemini"""
    if not GEMINI_API_KEY:
        return {}
    try:
        import base64
        img_b64 = base64.b64encode(file_bytes).decode()
        url     = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents":[{"parts":[
            {"text":"""Myanmar payment slip (KPay/Wave/KBZ/CB/AYA Bank).
Extract these fields:
AMOUNT: (numbers only, e.g. 1500)
DATE: (dd/mm/yyyy format)
TIME: (HH:MM format)
TYPE: (KPay or Wave or KBZ or CB or AYA or Other)
REFERENCE: (transaction ID or reference number)
SENDER: (sender name if visible)

Return EXACTLY in this format. Write UNKNOWN if not found."""},
            {"inline_data":{"mime_type":"image/jpeg","data":img_b64}}
        ]}]}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=60)
        data = resp.json()
        if "candidates" not in data:
            return {}
        text   = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        result = {}
        for line in text.split("\n"):
            line = line.strip()
            if ":" in line:
                key, val = line.split(":", 1)
                result[key.strip().upper()] = val.strip()
        return result
    except Exception as e:
        logger.error(f"Gemini slip: {e}")
        return {}

# ── Save Member with Password ─────────────────────────
async def save_member_to_sheet(user_id: str, username: str, days: int,
                                password: str = "", package: str = "CH") -> bool:
    if not SHEET_WEBHOOK:
        return False
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(SHEET_WEBHOOK, json={
                "action":   "saveMember",
                "userId":   str(user_id),
                "username": username,
                "days":     days,
                "password": password,
                "package":  package,
            }, timeout=10, follow_redirects=True)
        return resp.json().get("status") == "ok"
    except Exception as e:
        logger.error(f"saveMember: {e}")
        return False

async def create_invite_link(context, days: int) -> str:
    """Create single-use invite link valid for 30 minutes"""
    try:
        import time
        invite = await context.bot.create_chat_invite_link(
            chat_id=CHANNEL_ID,
            member_limit=1,
            expire_date=int(time.time() + 1800)  # 30 minutes
        )
        return invite.invite_link
    except Exception as e:
        logger.error(f"Invite link: {e}")
        return ""

async def send_approval_dm(context, member_id: int, months: int,
                           password: str, invite_url: str):
    """Send approval DM and pin the password message"""
    expire_date = (datetime.now() + timedelta(days=months * 30)).strftime("%d/%m/%Y")
    cust_kb = []
    if invite_url:
        cust_kb.append([InlineKeyboardButton("📢 Channel ဝင်ရန်", url=invite_url)])
    cust_kb.append([InlineKeyboardButton("🌐 Web App ဖွင့်",
                    url="https://kyawmintun08.github.io/Japan-Auction-Car-Checker-/")])
    text = (
        f"🎉 *Membership Approved!*\n\n"
        f"📅 သက်တမ်း: *{months} လ*\n"
        f"⏰ ကုန်ဆုံးရက်: `{expire_date}`\n\n"
        f"🔑 *Web Password: `{password}`*\n"
        f"🌐 Web: kyawmintun08.github.io/Japan-Auction-Car-Checker-/\n\n"
        f"⚠️ Password ကို မည်သူ့ကိုမျှ မပေးပါနဲ့\n"
        f"   မျှဝေပါက Membership ပိတ်သိမ်းခံရမည်\n\n"
        f"သက်တမ်းတိုးဖို့: /renew\nကျေးဇူးတင်ပါတယ် 🙏"
    )
    try:
        msg = await context.bot.send_message(
            chat_id=member_id, text=text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(cust_kb) if cust_kb else None)
        # Pin the password message
        try:
            await context.bot.pin_chat_message(
                chat_id=member_id,
                message_id=msg.message_id,
                disable_notification=True)
        except Exception as e:
            logger.error(f"Pin message: {e}")
    except Exception as e:
        logger.error(f"Send approval DM: {e}")

# ── Commands ──────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id  = update.effective_user.id
    is_admin = user_id in ADMIN_IDS

    kb = []
    kb.append([InlineKeyboardButton("🆕 Membership ဝယ်ရန်", callback_data="join_start")])
    if ADMIN_USERNAME:
        kb.append([InlineKeyboardButton("💬 Admin ကို ဆက်သွယ်", url=f"https://t.me/{ADMIN_USERNAME}")])
    kb.append([InlineKeyboardButton("🌐 Web App ကြည့်",
               url="https://kyawmintun08.github.io/Japan-Auction-Car-Checker-/")])

    if is_admin:
        # Admin — command အပြည့် ပြ
        cmd_text = (
            "*Member Commands:*\n"
            "🔍 `/find NT32-504837` → Chassis ရှာ\n"
            "🔎 `/model xtrail` → Model ရှာ\n"
            "📋 `/history NT32-504837` → ဈေးမှတ်တမ်း\n"
            "📊 `/list` → ကားအားလုံး\n"
            "🌐 `/web` → Web Link\n"
            "🔄 `/renew` → Membership သက်တမ်းတိုး\n"
            "🔑 `/mypassword` → Password ပြန်ယူ\n\n"
            "*Admin Commands:*\n"
            "📸 ကားပုံ တင် → Chassis auto ဖတ်\n"
            "📋 ပုံ + caption `list` → Auction List (Auto detect location)\n"
            "💰 `/price NT32-504837 150000` → ဈေးထည့်\n"
            "✅ `/approve @user 30 WEB` → Member approve\n"
            "👥 `/members` → Member list\n"
            "🔄 `/renew` → Member renew\n"
            "🚫 `/kick @user` → Member kick\n"
            "🔑 `/resetpass @user` → Password reset\n"
            "🆔 `/updateid @user newID` → ID update\n"
            "💾 `/backup` → CSV backup\n"
        )
    else:
        # Member — basic commands ပဲ ပြ
        cmd_text = (
            "*Commands:*\n"
            "🔍 `/find NT32-504837` → Chassis ရှာ\n"
            "🔎 `/model xtrail` → Model ရှာ\n"
            "📋 `/history NT32-504837` → ဈေးမှတ်တမ်း\n"
            "📊 `/list` → ကားအားလုံး\n"
            "🌐 `/web` → Web Link\n"
            "🔄 `/renew` → Membership သက်တမ်းတိုး\n"
            "🔑 `/mypassword` → Password ပြန်ယူ\n"
        )

    await update.message.reply_text(
        f"🚗 *JAN JAPAN Auction Bot*\n"
        f"📍 {LOC_MAESOT} & {LOC_KLANG9}\n\n"
        + cmd_text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(kb))

async def find_car(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_rate_limit(update.effective_user.id):
        await update.message.reply_text("⚠️ တစ်မိနစ်အတွင်း Request များသွားတယ် — ခဏစောင့်ပါ")
        return
    if not context.args:
        await update.message.reply_text("❌ Chassis ထည့်ပါ\nဥပမာ: `/find NT32-504837`", parse_mode='Markdown')
        return
    user_id  = update.effective_user.id
    is_admin = user_id in ADMIN_IDS
    chassis  = ' '.join(context.args)
    car      = find_by_chassis(chassis)
    if car:
        history = get_price_history(car['chassis'])
        txt     = format_car_info(car, history[-1]['price'] if history else None, history or None)
        # ဈေးထည့် button — Admin only
        kb = [[
            InlineKeyboardButton("💰 ဈေးထည့်",  callback_data=f"addprice_{car['chassis']}"),
            InlineKeyboardButton("✏️ ပြင်ရန်",   callback_data=f"editcar_{car['chassis']}"),
        ]] if is_admin else []
        await update.message.reply_text(txt, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(kb) if kb else None)
    else:
        guessed = guess_model_from_chassis(chassis)
        if guessed == "UNKNOWN":
            guessed = await guess_model_gemini(chassis)
        if is_admin:
            msg = (f"⚠️ `{chassis}` Checklist မှာ မပါဘူး\n🚗 ခန့်မှန်း: *{guessed}*\n\n`/price {chassis} [ဈေး]`"
                   if guessed != "UNKNOWN"
                   else f"❌ `{chassis}` မတွေ့ပါ\n\n`/price {chassis} [ဈေး]`")
        else:
            msg = (f"⚠️ `{chassis}` Checklist မှာ မပါဘူး\n🚗 ခန့်မှန်း: *{guessed}*"
                   if guessed != "UNKNOWN"
                   else f"❌ `{chassis}` မတွေ့ပါ")
        await update.message.reply_text(msg, parse_mode='Markdown')

async def find_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_rate_limit(update.effective_user.id):
        await update.message.reply_text("⚠️ တစ်မိနစ်အတွင်း Request များသွားတယ် — ခဏစောင့်ပါ")
        return
    if not context.args:
        await update.message.reply_text("❌ Model ထည့်ပါ\nဥပမာ: `/model xtrail`", parse_mode='Markdown')
        return
    user_id  = update.effective_user.id
    is_admin = user_id in ADMIN_IDS
    query    = ' '.join(context.args)
    results  = find_by_model(query)
    if not results:
        if is_admin:
            await update.message.reply_text(
                f"❌ *{query}* မတွေ့ပါ\n\n💡 Admin: ပုံ + caption `list` တင်ပြီး checklist ထည့်နိုင်",
                parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ *{query}* Checklist မှာ မရှိသေးပါ", parse_mode='Markdown')
        return
    txt = f"🔎 *{query.upper()}* ({len(results)} စီး):\n\n"
    for car in results:
        history   = get_price_history(car['chassis'])
        price_str = f"฿{history[-1]['price']:,}" if history else "ဈေးမရသေး"
        txt += f"• `{car['chassis']}` — {car['color']} {ys(car.get('year',0))} [{loc_display(car.get('loc','MaeSot'))}] — *{price_str}*\n"
    txt += f"\n🌐 [Web မှာကြည့်](https://kyawmintun08.github.io/Japan-Auction-Car-Checker-/)"
    await update.message.reply_text(txt, parse_mode='Markdown')

async def add_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("🚫 Admin သာ ဈေးထည့်ခွင့်ရှိတယ်")
        return
    if not check_rate_limit(user_id):
        await update.message.reply_text("⚠️ Request များသွားတယ် — ခဏစောင့်ပါ")
        return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Format: `/price NT32-504837 150000`", parse_mode='Markdown')
        return
    chassis = context.args[0].upper()
    try:
        price = int(context.args[1].replace(',',''))
    except:
        await update.message.reply_text("❌ ဈေး ဂဏန်းသာ ထည့်ပါ", parse_mode='Markdown')
        return
    car       = find_by_chassis(chassis) or {"chassis":chassis,"model":guess_model_from_chassis(chassis),"color":"-","year":0,"loc":"MaeSot"}
    user_name = update.effective_user.first_name or "Unknown"
    loc       = loc_display(car.get('loc','MaeSot'))
    entry     = await save_price(car['chassis'], car['model'], car['color'], car['year'], price, user_name, location=loc)
    await update.message.reply_text(
        f"✅ *ဈေးထည့်ပြီး!*\n\n🚗 {car['model']} ({ys(car.get('year',0))}) — `{chassis}`\n"
        f"💰 ฿{price:,}\n📍 {loc}\n📅 {entry['date']}\n👤 {user_name}\n\n"
        f"🌐 [Web မှာကြည့်](https://kyawmintun08.github.io/Japan-Auction-Car-Checker-/)",
        parse_mode='Markdown')

async def price_history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Chassis ထည့်ပါ\nဥပမာ: `/history NT32-504837`", parse_mode='Markdown')
        return
    user_id  = update.effective_user.id
    is_admin = user_id in ADMIN_IDS
    chassis  = ' '.join(context.args).upper()
    history  = get_price_history(chassis)
    if not history:
        await update.message.reply_text(f"❌ `{chassis}` ဈေးမှတ်တမ်း မရှိသေးပါ", parse_mode='Markdown')
        return
    car  = find_by_chassis(chassis)
    txt  = f"📈 *{car['model'] if car else chassis}*\n`{chassis}`\n\n"
    prev = None
    for h in history:
        if prev:
            diff  = h['price'] - prev
            arrow = "📈" if diff > 0 else "📉" if diff < 0 else "➡"
            txt += f"• {h['date']} → *฿{h['price']:,}* ({arrow} {diff:+,})\n"
        else:
            txt += f"• {h['date']} → *฿{h['price']:,}*\n"
        prev = h['price']
    if len(history) >= 2:
        change = history[-1]['price'] - history[0]['price']
        pct    = (change / history[0]['price']) * 100
        txt += f"\n📊 ပြောင်းလဲမှု: *{change:+,}* ({pct:+.1f}%)"
    # ဈေးထည့် button — Admin only
    kb = [[
        InlineKeyboardButton("💰 ဈေးအသစ်ထည့်", callback_data=f"addprice_{chassis}"),
        InlineKeyboardButton("✏️ ပြင်ရန်",      callback_data=f"editcar_{chassis}"),
    ]] if is_admin else []
    await update.message.reply_text(txt, parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(kb) if kb else None)

async def list_cars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    priced = {p['chassis'] for p in PRICE_HISTORY}
    txt    = f"🚗 *ကားစာရင်း ({len(CARS)} စီး)*\n\n"
    for car in CARS[:20]:
        status = "💰" if car['chassis'] in priced else "⏳"
        txt += f"{status} `{car['chassis']}` — {car['model']} {ys(car.get('year',0))} [{loc_display(car.get('loc','MaeSot'))}]\n"
    if len(CARS) > 20:
        txt += f"\n... နှင့် {len(CARS)-20} စီး ထပ်ရှိ"
    txt += f"\n\n🌐 [Web မှာကြည့်](https://kyawmintun08.github.io/Japan-Auction-Car-Checker-/)"
    await update.message.reply_text(txt, parse_mode='Markdown')

async def web_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pkg     = await get_member_package(user_id)
    if pkg == "WEB":
        await update.message.reply_text(
            f"🌐 *Japan Auction Car Checker — Web App*\n\n"
            f"https://kyawmintun08.github.io/Japan-Auction-Car-Checker-/\n\n"
            f"• {LOC_MAESOT} + {LOC_KLANG9} 🚗\n• ဈေးကြည့်နိုင် 📈\n• Chart ကြည့်နိုင် 📊",
            parse_mode='Markdown')
    elif pkg == "CH":
        await update.message.reply_text(
            "🚫 *Web App access မရှိသေးပါ*\n\n"
            "လက်ရှိ Package: 📱 Channel Only\n\n"
            "🌐 Web App ကြည့်ဖို့ *Channel+Web Package* သို့ Upgrade လုပ်ပါ\n"
            "👉 /renew နှိပ်ပြီး WEB package ရွေးပါ",
            parse_mode='Markdown')
    else:
        await update.message.reply_text(
            "🚫 *Member များသာ Web App ကြည့်နိုင်ပါသည်*\n\n"
            "Membership ဝယ်ရန် 👉 /renew",
            parse_mode='Markdown')

# ── /renew & /join — Package Selection ───────────────
def build_package_keyboard(user_id: int, action: str = "renew"):
    """Build package selection keyboard"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📱 Channel Only",         callback_data=f"pkg_CH_{user_id}_{action}"),
         InlineKeyboardButton(f"📱+🌐 Channel + Web",    callback_data=f"pkg_WEB_{user_id}_{action}")],
        [InlineKeyboardButton("❌ Cancel",                 callback_data=f"pkg_cancel_{user_id}")],
    ])

def build_period_keyboard(user_id: int, package: str):
    prices = PLAN_PRICES[package]
    if package == "CH":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(f"1 လ — {prices[1]:,} ks",  callback_data=f"period_{package}_1_{user_id}"),
             InlineKeyboardButton(f"2 လ — {prices[2]:,} ks",  callback_data=f"period_{package}_2_{user_id}")],
            [InlineKeyboardButton(f"3 လ — {prices[3]:,} ks",  callback_data=f"period_{package}_3_{user_id}"),
             InlineKeyboardButton(f"5 လ — {prices[5]:,} ks",  callback_data=f"period_{package}_5_{user_id}")],
            [InlineKeyboardButton("◀️ နောက်သို့",             callback_data=f"pkg_back_{user_id}")],
        ])
    else:  # WEB
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(f"1 လ — {prices[1]:,} ks",  callback_data=f"period_{package}_1_{user_id}"),
             InlineKeyboardButton(f"2 လ — {prices[2]:,} ks",  callback_data=f"period_{package}_2_{user_id}"),
             InlineKeyboardButton(f"3 လ — {prices[3]:,} ks",  callback_data=f"period_{package}_3_{user_id}")],
            [InlineKeyboardButton("◀️ နောက်သို့",             callback_data=f"pkg_back_{user_id}")],
        ])

async def renew_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    user_id = user.id
    await update.message.reply_text(
        "🔄 *Membership သက်တမ်းတိုး*\n\n"
        "Package ရွေးပါ 👇",
        parse_mode='Markdown',
        reply_markup=build_package_keyboard(user_id, "renew"))

# ── /mypassword ───────────────────────────────────────
async def mypassword_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    user_id = user.id
    if not SHEET_WEBHOOK:
        await update.message.reply_text("❌ System error — Admin ကို ဆက်သွယ်ပါ")
        return
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(SHEET_WEBHOOK, json={
                "action": "getPassword",
                "userId": str(user_id),
            }, timeout=10, follow_redirects=True)
        data = resp.json()
        if data.get("status") == "ok" and data.get("password"):
            await update.message.reply_text(
                f"🔑 *သင်၏ Web Password*\n\n"
                f"`{data['password']}`\n\n"
                f"🌐 https://kyawmintun08.github.io/Japan-Auction-Car-Checker-/\n\n"
                f"⚠️ Password ကို မည်သူ့ကိုမျှ မပေးပါနဲ့",
                parse_mode='Markdown')
        else:
            admin_link = f"\n💬 [Admin ကို ဆက်သွယ်](https://t.me/{ADMIN_USERNAME})" if ADMIN_USERNAME else ""
            await update.message.reply_text(
                f"❌ သင်၏ Member အချက်အလက် မတွေ့ပါ\n\n"
                f"Member မဟုတ်သေးပါ — Membership ဝယ်ရန် /renew{admin_link}",
                parse_mode='Markdown')
    except Exception as e:
        logger.error(f"mypassword: {e}")
        await update.message.reply_text("❌ Error — Admin ကို ဆက်သွယ်ပါ")

# ── /resetpass (Admin only) ───────────────────────────
async def resetpass_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်")
        return
    if not context.args:
        await update.message.reply_text("❌ Format: `/resetpass @username` သို့မဟုတ် `/resetpass 123456789`",
                                        parse_mode='Markdown')
        return
    target = context.args[0].replace('@', '')
    new_pw = generate_password()
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(SHEET_WEBHOOK, json={
                "action":   "resetPassword",
                "username": target,
                "password": new_pw,
            }, timeout=10, follow_redirects=True)
        data = resp.json()
        if data.get("status") == "ok":
            member_id = data.get("userId")
            if member_id and str(member_id).isdigit():
                try:
                    await context.bot.send_message(
                        chat_id=int(member_id),
                        text=f"🔑 *Password Reset လုပ်ပြီ*\n\n"
                             f"New Password: `{new_pw}`\n\n"
                             f"🌐 https://kyawmintun08.github.io/Japan-Auction-Car-Checker-/\n\n"
                             f"⚠️ မည်သူ့ကိုမျှ မပေးပါနဲ့",
                        parse_mode='Markdown')
                except Exception as e:
                    logger.error(f"resetpass DM: {e}")
            await update.message.reply_text(
                f"✅ Password Reset ပြီ\n👤 @{target}\n🔑 `{new_pw}`",
                parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ @{target} မတွေ့ပါ")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

# ── /updateid (Admin only) ────────────────────────────
async def updateid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်")
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Format: `/updateid @username [newTelegramID]`\n"
            "ဥပမာ: `/updateid @Steve_member 987654321`",
            parse_mode='Markdown')
        return
    target_username = context.args[0].replace('@', '')
    try:
        new_id = int(context.args[1])
    except:
        await update.message.reply_text("❌ Telegram ID ဂဏန်းဖြစ်ရမည်")
        return
    # Confirm step
    pending_updateid[user_id] = {
        "target_username": target_username,
        "new_id": new_id,
    }
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ အတည်ပြု",  callback_data=f"uid_ok_{user_id}"),
        InlineKeyboardButton("❌ မလုပ်တော့", callback_data=f"uid_no_{user_id}"),
    ]])
    await update.message.reply_text(
        f"⚠️ *ID Update အတည်ပြုချက်*\n\n"
        f"👤 Member: @{target_username}\n"
        f"✅ အသစ် ID: `{new_id}`\n\n"
        f"ဟောင်း ID အလိုအလျောက် ဖျက်မည်\n"
        f"Password အသစ် generate လုပ်မည်\n\n"
        f"အတည်ပြုရန် 👇",
        parse_mode='Markdown',
        reply_markup=kb)

# ── /backup (Admin only) ──────────────────────────────
async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်")
        return
    await update.message.reply_text("⏳ Sheet မှ data ဆွဲနေသည်...")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(SHEET_WEBHOOK, json={
                "action": "getBackupCSV"
            }, timeout=30, follow_redirects=True)
        data = resp.json()
        if data.get("status") == "ok" and data.get("csv"):
            csv_content = data["csv"]
            filename    = f"Members_backup_{datetime.now().strftime('%Y_%m_%d')}.csv"
            csv_bytes   = csv_content.encode('utf-8-sig')
            from io import BytesIO
            bio = BytesIO(csv_bytes)
            bio.name = filename
            await context.bot.send_document(
                chat_id=user_id,
                document=bio,
                filename=filename,
                caption=f"✅ Members Backup\n📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        else:
            await update.message.reply_text("❌ Backup မရနိုင်ပါ — Sheet စစ်ဆေးပါ")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

# ── /upgrade ──────────────────────────────────────────
async def upgrade_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    user_id = user.id
    await update.message.reply_text(
        "⬆️ *Package Upgrade*\n\n"
        "📱 Channel Only → 📱+🌐 Channel + Web\n\n"
        "Web ဝင်ခွင့် ထပ်ထည့်ချင်ရင် Package ရွေးပါ 👇",
        parse_mode='Markdown',
        reply_markup=build_package_keyboard(user_id, "upgrade"))

# ── OCR ───────────────────────────────────────────────
def tesseract_ocr_chassis(file_bytes: bytes) -> str:
    if not TESSERACT_AVAILABLE:
        return ""
    try:
        img     = Image.open(BytesIO(file_bytes))
        text    = pytesseract.image_to_string(img)
        chassis = extract_chassis_from_text(text)
        return chassis or ""
    except Exception as e:
        logger.error(f"Tesseract: {e}")
        return ""

async def gemini_ocr_auction_list(file_bytes: bytes) -> tuple:
    """Returns (cars_list, detected_location) where location is 'Klang9' or 'MaeSot'"""
    if not GEMINI_API_KEY:
        return [], None
    try:
        import base64, json
        img_b64 = base64.b64encode(file_bytes).decode()
        url     = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents":[{"parts":[
            {"text": (
                "This is a JAN JAPAN auction car list image.\n"
                "1. First check the header/title of the image for location:\n"
                "   - If you see 'KALANG9', 'KLANG9', 'KLANG 9' → location = 'Klang9'\n"
                "   - If you see 'MEASOT', 'MAESOT', 'MAE SOT' → location = 'MaeSot'\n"
                "2. Extract ALL car rows from the table.\n\n"
                "Return ONLY this JSON (no markdown, no extra text):\n"
                "{\"location\":\"MaeSot\",\"cars\":[{\"chassis\":\"NT32-024640\",\"model\":\"X-TRAIL\",\"color\":\"BLACK\",\"year\":2014}]}"
            )},
            {"inline_data":{"mime_type":"image/jpeg","data":img_b64}}
        ]}]}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=60)
        data = resp.json()
        if "candidates" not in data:
            return [], None
        text  = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        # Try new format first
        start = text.find('{'); end = text.rfind('}') + 1
        if start >= 0 and end > start:
            parsed = json.loads(text[start:end])
            cars   = parsed.get("cars", [])
            loc    = parsed.get("location", None)
            return cars, loc
        # Fallback: old array format
        start = text.find('['); end = text.rfind(']') + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end]), None
    except Exception as e:
        logger.error(f"Gemini list: {e}")
    return [], None

async def gemini_ocr_chassis(file_bytes: bytes) -> dict:
    if GEMINI_API_KEY:
        try:
            import base64
            img_b64 = base64.b64encode(file_bytes).decode()
            url     = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
            payload = {"contents":[{"parts":[
                {"text":"""Japan auction car photo.
1. Find chassis number written on windshield with marker pen (e.g. NT32-024640, GP1-1049821, S510P-0173458)
2. Identify car body COLOR from the paint (WHITE, BLACK, SILVER, PEARL WHITE, DARK BLUE, RED, BLUE, GREEN, YELLOW, BROWN, ORANGE, GREY)
3. Identify car MODEL from the shape/badge
4. Identify manufacturing YEAR if visible

Return EXACTLY in this format (no extra text):
CHASSIS: S510P-0236416
MODEL: HIJET TRUCK
COLOR: WHITE
YEAR: 2017"""},
                {"inline_data":{"mime_type":"image/jpeg","data":img_b64}}
            ]}]}
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, timeout=60)
            data = resp.json()
            if "candidates" in data:
                text    = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                chassis = ""; model = ""; color = ""; year = 0
                for line in text.upper().split("\n"):
                    line = line.strip()
                    if line.startswith("CHASSIS:"):
                        raw = line.replace("CHASSIS:","").strip()
                        for pat in [r'[A-Z]{1,5}\d{1,4}[A-Z]{0,2}\d{0,2}-\d{4,7}',
                                    r'[A-Z]{2,6}\d{2,4}-\d{4,7}',
                                    r'[A-Z0-9]{4,20}-\d{4,7}']:
                            m = re.search(pat, raw)
                            if m: chassis = m.group().replace(' ','-'); break
                    elif line.startswith("MODEL:"): model = line.replace("MODEL:","").strip()
                    elif line.startswith("COLOR:"): color = line.replace("COLOR:","").strip()
                    elif line.startswith("YEAR:"):
                        try: year = int(re.search(r'\d{4}', line).group())
                        except: year = 0
                if chassis:
                    return {"chassis":chassis,"model":model,"color":color,"year":year}
        except Exception as e:
            logger.error(f"Gemini OCR: {e}")
    chassis = tesseract_ocr_chassis(file_bytes)
    return {"chassis":chassis,"model":"","color":"","year":0}

# ── Photo Handler ─────────────────────────────────────
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CARS
    user    = update.effective_user
    user_id = user.id
    photo   = update.message.photo[-1]
    caption = (update.message.caption or "").strip().lower()

    if not check_rate_limit(user_id, max_req=5, window=60):
        await update.message.reply_text("⚠️ တစ်မိနစ်အတွင်း ပုံများသွားတယ် — ခဏစောင့်ပါ")
        return

    # ── Payment Slip Mode ── (if user is in pending_payment state)
    if user_id in pending_payment:
        pay_data = pending_payment[user_id]
        if pay_data.get("waiting_slip"):
            await update.message.reply_text("🔍 Payment Slip ဖတ်နေတယ်... ⏳")
            try:
                file       = await photo.get_file()
                file_bytes = bytes(await file.download_as_bytearray())
                slip_info  = await gemini_read_slip(file_bytes)
            except Exception as e:
                logger.error(f"Slip read: {e}")
                slip_info = {}

            amount    = slip_info.get("AMOUNT", "UNKNOWN")
            date_str  = slip_info.get("DATE", "UNKNOWN")
            time_str  = slip_info.get("TIME", "UNKNOWN")
            pay_type  = slip_info.get("TYPE", "UNKNOWN")
            reference = slip_info.get("REFERENCE", "UNKNOWN")
            sender    = slip_info.get("SENDER", "UNKNOWN")

            expected  = pay_data.get("amount", 0)
            amount_ok = ""
            if amount != "UNKNOWN":
                try:
                    amt_num = int(re.sub(r'[^\d]', '', amount))
                    if amt_num >= expected:
                        amount_ok = "✅"
                    else:
                        amount_ok = f"⚠️ မပြည့်မီ (လိုအပ်: {expected:,} ks)"
                except:
                    amount_ok = "⚠️ စစ်မရ"
            else:
                amount_ok = "⚠️ ဖတ်မရ"

            # Store slip data for admin confirm
            pending_payment[user_id]["slip_info"] = slip_info
            pending_payment[user_id]["file_bytes"] = file_bytes

            # Build admin notification
            pkg_name  = PLAN_NAMES.get(pay_data.get("package","CH"), "Unknown")
            months    = pay_data.get("months", 1)
            name      = pay_data.get("name", "Unknown")
            username  = pay_data.get("username", str(user_id))

            admin_text = (
                f"💰 *Payment Slip အသစ်*\n\n"
                f"👤 {name} ({username})\n"
                f"🆔 ID: `{user_id}`\n"
                f"📦 Package: {pkg_name} — {months} လ\n"
                f"💵 Expected: {expected:,} ks\n\n"
                f"📋 *Slip အချက်အလက်:*\n"
                f"💵 Amount: {amount} ks {amount_ok}\n"
                f"📅 Date: {date_str} {time_str}\n"
                f"🏦 Type: {pay_type}\n"
                f"🔢 Ref: {reference}\n"
                f"👤 Sender: {sender}\n\n"
                f"⚠️ ကိုယ့် {pay_type} app မှာ ငွေဝင်မဝင် စစ်ပြီးမှ Confirm လုပ်ပါ"
            )
            admin_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"💬 {name} ကို Message ပို့", url=f"tg://user?id={user_id}")],
                [InlineKeyboardButton("✅ Confirm", callback_data=f"slip_ok_{user_id}"),
                 InlineKeyboardButton("❌ Reject",  callback_data=f"slip_no_{user_id}")],
            ])
            await notify_admins(context, admin_text, reply_markup=admin_kb)
            await update.message.reply_text(
                "✅ *Slip လက်ခံရပြီ!*\n\n"
                "Admin မှ စစ်ဆေးနေသည် — ခဏစောင့်ပါ 🙏\n"
                "မကြာမီ Password DM ပို့ပေးမည်",
                parse_mode='Markdown')
            return

    # ── Auction List Mode ──
    if "list" in caption:
        # Caption ကနေ location hint ယူ (fallback)
        caption_klang9 = "klang9" in caption or "klang" in caption
        await update.message.reply_text(f"📋 Auction List ဖတ်နေတယ်... ⏳")
        try:
            file       = await photo.get_file()
            file_bytes = bytes(await file.download_as_bytearray())
            new_cars, detected_loc = await gemini_ocr_auction_list(file_bytes)
        except Exception as e:
            logger.error(f"Auction list: {e}"); new_cars = []; detected_loc = None

        # Location ဆုံးဖြတ်ခြင်း — Gemini detection ကို ဦးစားပေး၊ caption fallback
        if detected_loc in ("Klang9", "MaeSot"):
            import_loc = detected_loc
        elif caption_klang9:
            import_loc = "Klang9"
        else:
            import_loc = "MaeSot"

        loc_name = LOC_KLANG9 if import_loc == "Klang9" else LOC_MAESOT
        await update.message.reply_text(f"📍 Location: *{loc_name}*", parse_mode='Markdown')

        if not new_cars:
            await update.message.reply_text("⚠️ List ဖတ်မရပါ\n💡 Gemini API limit ကုန်နိုင်တယ်")
            return

        existing = {c["chassis"].upper() for c in CARS}
        added    = []
        unknown  = []

        for car in new_cars:
            ch    = str(car.get("chassis","")).upper().strip()
            model = str(car.get("model","")).strip()
            color = str(car.get("color","")).strip()
            year  = int(car.get("year",0) or 0)
            if not ch:
                continue
            missing_fields = []
            if not model or model.upper() in ("", "UNKNOWN", "N/A"):
                missing_fields.append("Model")
                model = guess_model_from_chassis(ch)
            if not color or color in ("", "-", "N/A"):
                missing_fields.append("Color")
                color = "-"
            if not year:
                missing_fields.append("Year")
            if ch not in existing:
                CARS.append({"chassis":ch,"model":model,"color":color,"year":year,"loc":import_loc})
                existing.add(ch)
                added.append(ch)
            if missing_fields:
                unknown.append({"chassis":ch,"model":model,"missing":missing_fields})

        txt = f"✅ *{loc_name} List Update ပြီး!*\n\n📊 ဖတ်ရ: {len(new_cars)} စီး\n✨ အသစ်: {len(added)} စီး\n"
        if added:
            txt += "\n🆕 " + "".join(f"`{ch}`\n" for ch in added[:10])
            if len(added) > 10:
                txt += f"... {len(added)-10} စီး ထပ်ရှိ\n"
        if unknown:
            txt += f"\n⚠️ *မသေချာ ({len(unknown)} စီး):*\n"
            for u in unknown[:5]:
                txt += f"• `{u['chassis']}` ({u['model']}) — မရ: *{', '.join(u['missing'])}*\n"
            if len(unknown) > 5:
                txt += f"... {len(unknown)-5} စီး ထပ်ရှိ\n"
        txt += f"\n📋 Database: {len(CARS)} စီး"
        await update.message.reply_text(txt, parse_mode='Markdown')
        return

    # ── Car Photo Mode ──
    await update.message.reply_text("🔍 Chassis ရှာနေတယ်... ⏳")

    chassis      = extract_chassis_from_text(caption) if caption else None
    price_match  = re.search(r'(?<![A-Z0-9])(\d{4,6})(?![A-Z0-9])', caption.upper()) if caption else None
    price        = int(price_match.group(1)) if price_match else None
    gemini_model = ""; gemini_color = ""; gemini_year = 0; file_bytes = None

    if not chassis:
        try:
            file       = await photo.get_file()
            file_bytes = bytes(await file.download_as_bytearray())
            result     = await gemini_ocr_chassis(file_bytes)
            chassis      = result.get("chassis","")
            gemini_model = result.get("model","")
            gemini_color = result.get("color","")
            gemini_year  = result.get("year",0)
        except Exception as e:
            logger.error(f"Photo: {e}")

    car       = find_by_chassis(chassis) if chassis else None
    image_url = ""
    if chassis and file_bytes:
        image_url = await upload_to_cloudinary(file_bytes, chassis)

    car_loc     = loc_display(car.get('loc','MaeSot')) if car else LOC_MAESOT
    final_model = gemini_model if gemini_model and gemini_model not in ("","UNKNOWN") else (car['model'] if car else guess_model_from_chassis(chassis or ""))
    final_color = gemini_color if gemini_color and gemini_color != "-" else (car['color'] if car else "-")
    final_year  = gemini_year  if gemini_year  else (car.get('year', 0) if car else 0)
    final_chassis = chassis or ""

    missing = []
    if not final_chassis:                                          missing.append("Chassis")
    if not final_model or final_model == "UNKNOWN":               missing.append("Model")
    if not final_color or final_color == "-":                     missing.append("Color")
    if not final_year:                                            missing.append("Year")

    if final_chassis and price:
        pending_photo[user_id] = {
            "user_id":   user_id,
            "chassis":   final_chassis,
            "model":     final_model,
            "color":     final_color,
            "year":      final_year,
            "price":     price,
            "loc":       car_loc,
            "image_url": image_url,
        }
        warn = f"\n⚠️ မသေချာ: *{', '.join(missing)}*\n" if missing else ""
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ မှန်တယ် Save",    callback_data=f"cs_{user_id}"),
            InlineKeyboardButton("❌ မှားတယ် Cancel", callback_data=f"cc_{user_id}"),
        ]])
        await update.message.reply_text(
            f"⚠️ *စစ်ဆေးပါ — မှန်ကန်ပါသလား?*\n\n"
            f"🚗 *{final_model}* ({ys(final_year)})\n"
            f"🔑 `{final_chassis}`\n🎨 {final_color}\n📍 {car_loc}\n💰 ฿{price:,}\n"
            f"{warn}\n✅ မှန်ရင် *Save* နှိပ်ပါ\n❌ မှားရင် *Cancel* နှိပ်ပြီး `/price [chassis] [ဈေး]` သုံးပါ",
            parse_mode='Markdown', reply_markup=kb)
    elif final_chassis:
        pending_photo[user_id] = {
            "user_id":user_id,"chassis":final_chassis,"model":final_model,
            "color":final_color,"year":final_year,"price":None,"loc":car_loc,"image_url":image_url,
        }
        warn = f"\n⚠️ မသေချာ: *{', '.join(missing)}*\n" if missing else ""
        await update.message.reply_text(
            f"🚗 *{final_model}* ({ys(final_year)})\n🔑 `{final_chassis}`\n"
            f"🎨 {final_color}\n📍 {car_loc}\n{warn}\n💰 ဈေး ရိုက်ထည့်ပါ:\nဥပမာ: `150000`",
            parse_mode='Markdown')
    elif chassis:
        guessed = gemini_model or guess_model_from_chassis(chassis)
        if not guessed or guessed == "UNKNOWN":
            guessed = guess_model_from_chassis(chassis)
        display_color = final_color if final_color and final_color != "-" else (gemini_color or "-")
        display_year  = final_year or gemini_year or 0
        if price:
            pending_photo[user_id] = {
                "user_id":user_id,"chassis":chassis,"model":guessed,
                "color":display_color,"year":display_year,"price":price,"loc":LOC_MAESOT,"image_url":image_url,
            }
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ မှန်တယ် Save",    callback_data=f"cs_{user_id}"),
                InlineKeyboardButton("❌ မှားတယ် Cancel", callback_data=f"cc_{user_id}"),
            ]])
            await update.message.reply_text(
                f"⚠️ *Checklist မှာ မပါဘူး*\n\n🚗 ခန့်မှန်း: *{guessed}* ({ys(display_year)})\n"
                f"🔑 `{chassis}`\n🎨 {display_color}\n💰 ฿{price:,}\n\n"
                f"✅ မှန်ရင် *Save* နှိပ်ပါ",
                parse_mode='Markdown', reply_markup=kb)
        else:
            pending_photo[user_id] = {
                "user_id":user_id,"chassis":chassis,"model":guessed,
                "color":display_color,"year":display_year,"price":None,"loc":LOC_MAESOT,"image_url":image_url,
            }
            msg = (f"⚠️ Checklist မှာ မပါဘူး\n\n🚗 ခန့်မှန်း: *{guessed}* ({ys(display_year)})\n"
                   f"🔑 `{chassis}`\n🎨 {display_color}\n\n💰 ဈေး ရိုက်ထည့်ပါ:\nဥပမာ: `150000`"
                   if guessed and guessed != "UNKNOWN"
                   else f"⚠️ Chassis: `{chassis}`\nChecklist မှာ မပါဘူး — ဈေး ထည့်ပါ:\nဥပမာ: `150000`")
            await update.message.reply_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text(
            "⚠️ Chassis ဖတ်မရပါ\nကိုယ်တိုင် ထည့်ပါ:\n`/price [chassis] [ဈေး]`", parse_mode='Markdown')

# ── Text Handler ──────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text    = update.message.text.strip()

    # ── Edit Car Field ──
    if user_id in pending_edit:
        edit = pending_edit.pop(user_id)
        chassis = edit["chassis"]
        field   = edit["field"]
        car     = find_by_chassis(chassis)
        if not car:
            await update.message.reply_text(f"❌ `{chassis}` မတွေ့ပါ", parse_mode='Markdown')
            return

        # Validate + parse
        if field == "price":
            try:
                new_val = int(text.replace(",","").replace(" ",""))
                display = f"฿{new_val:,}"
            except:
                await update.message.reply_text("❌ ဂဏန်းသက်သက်သာ ရိုက်ပါ
ဥပမာ: `150000`", parse_mode='Markdown')
                pending_edit[user_id] = edit  # put back
                return
        elif field == "color":
            new_val = text.upper().strip()
            display = new_val
        elif field == "model":
            new_val = text.upper().strip()
            display = new_val
        else:
            return

        # Update in-memory CARS list
        for c in CARS:
            if c.get("chassis","").upper() == chassis.upper():
                c[field] = new_val
                break

        # Send update to Apps Script webhook
        field_map = {"price": "price", "color": "color", "model": "model"}
        if SHEET_WEBHOOK:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(SHEET_WEBHOOK, json={
                        "action": "updateCar",
                        "chassis": chassis,
                        "field": field_map[field],
                        "value": str(new_val),
                    }, timeout=10, follow_redirects=True)
            except Exception as e:
                logger.error(f"updateCar webhook: {e}")

        await update.message.reply_text(
            f"✅ *{chassis}* ပြင်ပြီး\n"
            f"📝 {field.upper()}: *{display}*",
            parse_mode='Markdown')
        return

    if user_id in pending_photo:
        data = pending_photo[user_id]
        if data.get('price') is None and re.match(r'^[\d,]+$', text.replace(' ','')):
            try:
                price            = int(text.replace(',','').replace(' ',''))
                data['price']    = price
                pending_photo[user_id] = data
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ မှန်တယ် Save",    callback_data=f"cs_{user_id}"),
                    InlineKeyboardButton("❌ မှားတယ် Cancel", callback_data=f"cc_{user_id}"),
                ]])
                await update.message.reply_text(
                    f"⚠️ *စစ်ဆေးပါ — မှန်ကန်ပါသလား?*\n\n"
                    f"🚗 *{data['model']}* ({ys(data.get('year',0))})\n"
                    f"🔑 `{data['chassis']}`\n🎨 {data['color']}\n📍 {data['loc']}\n💰 ฿{price:,}\n\n"
                    f"✅ မှန်ရင် *Save* နှိပ်ပါ\n❌ မှားရင် *Cancel* နှိပ်ပါ",
                    parse_mode='Markdown', reply_markup=kb)
                return
            except: pass

    chassis = extract_chassis_from_text(text)
    if chassis:
        car = find_by_chassis(chassis)
        if car:
            history = get_price_history(car['chassis'])
            txt     = format_car_info(car, history[-1]['price'] if history else None, history or None)
            kb      = [[InlineKeyboardButton("💰 ဈေးထည့်", callback_data=f"addprice_{car['chassis']}")]]
            await update.message.reply_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
        else:
            guessed = guess_model_from_chassis(chassis)
            if guessed == "UNKNOWN": guessed = await guess_model_gemini(chassis)
            msg = (f"⚠️ `{chassis}` Checklist မှာ မပါဘူး\n🚗 ခန့်မှန်း: *{guessed}*\n\n`/price {chassis} [ဈေး]`"
                   if guessed != "UNKNOWN"
                   else f"⚠️ `{chassis}` Checklist မှာ မပါဘူး\n\n`/price {chassis} [ဈေး]`")
            await update.message.reply_text(msg, parse_mode='Markdown')

# ── Callback Handler ──────────────────────────────────
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data

    # ── ✅ Confirm Save ──
    if data.startswith("cs_"):
        uid  = int(data.replace("cs_",""))
        info = pending_photo.pop(uid, None)
        if not info or info.get('price') is None:
            await query.message.reply_text("❌ Data မရှိတော့ပါ — ပုံ ပြန်တင်ပါ")
            return
        user_name = query.from_user.first_name or "Unknown"
        await save_price(info['chassis'], info['model'], info['color'], info['year'],
                        info['price'], user_name, info.get('image_url',''), info.get('loc', LOC_MAESOT))
        await query.message.reply_text(
            f"✅ *Save ပြီး!*\n\n🚗 {info['model']} ({ys(info.get('year',0))})\n"
            f"🔑 `{info['chassis']}`\n📍 {info.get('loc', LOC_MAESOT)}\n💰 ฿{info['price']:,}\n\n"
            f"🌐 [Web မှာကြည့်](https://kyawmintun08.github.io/Japan-Auction-Car-Checker-/)",
            parse_mode='Markdown')
        await post_to_channel(context, info['chassis'], info['model'], info['color'],
                             info['year'], info['price'], info.get('image_url',''), info.get('loc', LOC_MAESOT))

    # ── ❌ Cancel ──
    elif data.startswith("cc_"):
        uid = int(data.replace("cc_",""))
        pending_photo.pop(uid, None)
        await query.message.reply_text(
            "❌ *Cancel လုပ်ပြီး*\n\nChassis ကိုယ်တိုင် ထည့်ပါ:\n"
            "`/price [chassis] [ဈေး]`\nဥပမာ: `/price GP1-1049821 58000`",
            parse_mode='Markdown')

    # ── Edit Car button ── (Admin only)
    elif data.startswith("editcar_"):
        if query.from_user.id not in ADMIN_IDS:
            await query.answer("❌ Admin only", show_alert=True)
            return
        chassis = data.replace("editcar_","")
        car = find_by_chassis(chassis)
        if not car:
            await query.answer("❌ Chassis မတွေ့ပါ", show_alert=True)
            return
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💰 ဈေး ({car.get('price','?')})",   callback_data=f"editfield_{chassis}_price")],
            [InlineKeyboardButton(f"🎨 Color ({car.get('color','-')})",  callback_data=f"editfield_{chassis}_color")],
            [InlineKeyboardButton(f"🚗 Model ({car.get('model','-')})",  callback_data=f"editfield_{chassis}_model")],
            [InlineKeyboardButton("❌ Cancel",                           callback_data=f"editfield_{chassis}_cancel")],
        ])
        await query.message.reply_text(
            f"✏️ *{chassis}* — ဘာပြင်မလဲ?",
            parse_mode='Markdown', reply_markup=kb)

    elif data.startswith("editfield_"):
        if query.from_user.id not in ADMIN_IDS:
            await query.answer("❌ Admin only", show_alert=True)
            return
        parts   = data.split("_", 2)  # editfield_CHASSIS_field
        chassis = parts[1]
        field   = parts[2]
        if field == "cancel":
            pending_edit.pop(query.from_user.id, None)
            await query.message.reply_text("❌ Cancel လုပ်ပြီး")
            return
        pending_edit[query.from_user.id] = {"chassis": chassis, "field": field}
        prompts = {
            "price": f"💰 `{chassis}` ဈေးအသစ် ရိုက်ထည့်ပါ:
ဥပမာ: `150000`",
            "color": f"🎨 `{chassis}` Color အသစ် ရိုက်ထည့်ပါ:
ဥပမာ: `PEARL WHITE`",
            "model": f"🚗 `{chassis}` Model အသစ် ရိုက်ထည့်ပါ:
ဥပမာ: `HONDA FIT`",
        }
        await query.message.reply_text(prompts[field], parse_mode='Markdown')

    # ── Add Price button ──
    elif data.startswith("addprice_"):
        chassis = data.replace("addprice_","")
        car     = find_by_chassis(chassis)
        if car:
            pending_photo[query.from_user.id] = {
                "user_id": query.from_user.id,
                "chassis": car['chassis'], "model": car['model'],
                "color":   car['color'],   "year":  car['year'],
                "price":   None, "loc": loc_display(car.get('loc','MaeSot')), "image_url": ""}
        await query.message.reply_text(
            f"💰 `{chassis}` ဈေး ရိုက်ထည့်ပါ:\nဥပမာ: `150000`", parse_mode='Markdown')

    # ── Join / Renew — Package Select ──
    elif data.startswith("join_start"):
        user_id = query.from_user.id
        await query.message.reply_text(
            "🆕 *Membership ဝယ်ရန်*\n\nPackage ရွေးပါ 👇",
            parse_mode='Markdown',
            reply_markup=build_package_keyboard(user_id, "join"))

    elif data.startswith("pkg_cancel_"):
        pending_payment.pop(query.from_user.id, None)
        await query.message.reply_text("❌ Cancel လုပ်ပြီး")

    elif data.startswith("pkg_back_"):
        user_id = query.from_user.id
        await query.message.reply_text(
            "Package ပြန်ရွေးပါ 👇",
            reply_markup=build_package_keyboard(user_id, "renew"))

    elif data.startswith("pkg_"):
        # Format: pkg_CH_userid_action or pkg_WEB_userid_action
        parts   = data.split("_")
        package = parts[1]   # CH or WEB
        user_id = int(parts[2])
        action  = parts[3] if len(parts) > 3 else "renew"
        prices  = PLAN_PRICES.get(package, PLAN_PRICES["CH"])
        pending_payment[user_id] = {
            "package": package, "action": action,
            "name":    query.from_user.first_name or "Unknown",
            "username": f"@{query.from_user.username}" if query.from_user.username else str(user_id),
        }
        pkg_name = PLAN_NAMES.get(package,"")
        await query.message.reply_text(
            f"✅ Package: *{pkg_name}*\n\nPeriod ရွေးပါ 👇",
            parse_mode='Markdown',
            reply_markup=build_period_keyboard(user_id, package))

    elif data.startswith("period_"):
        # Format: period_CH_1_userid
        parts   = data.split("_")
        package = parts[1]
        months  = int(parts[2])
        user_id = int(parts[3])
        amount  = PLAN_PRICES.get(package, {}).get(months, 0)
        pkg_name = PLAN_NAMES.get(package,"")

        if user_id not in pending_payment:
            pending_payment[user_id] = {}
        pending_payment[user_id].update({
            "package":      package,
            "months":       months,
            "amount":       amount,
            "waiting_slip": True,
        })

        await query.message.reply_text(
            f"✅ Package: *{pkg_name}*\n"
            f"📅 Period: *{months} လ*\n"
            f"💵 ပေးရမည်: *{amount:,} ks*\n\n"
            f"💳 *Payment Info:*\n{PAYMENT_INFO}\n\n"
            f"⬇️ Payment Slip ကို ဤနေရာမှာ တိုက်ရိုက်ပို့ပါ",
            parse_mode='Markdown')

    # ── Slip Confirm (Admin) ──
    elif data.startswith("slip_ok_"):
        if query.from_user.id not in ADMIN_IDS:
            await query.answer("❌ Admin သာ လုပ်နိုင်တယ်", show_alert=True)
            return
        member_id  = int(data.replace("slip_ok_",""))
        pay_data   = pending_payment.pop(member_id, {})
        if not pay_data:
            await query.message.reply_text("❌ Data ကုန်သွားပြီ")
            return
        package  = pay_data.get("package", "CH")
        months   = pay_data.get("months", 1)
        name     = pay_data.get("name", "Unknown")
        username = pay_data.get("username", str(member_id))
        password = generate_password()

        # Save to Sheet
        await save_member_to_sheet(
            str(member_id),
            username.replace("@",""),
            months * 30,
            password,
            package)

        # Create invite link (30min)
        invite_url = await create_invite_link(context, months * 30)

        # Send DM + Pin
        await send_approval_dm(context, member_id, months, password, invite_url)

        expire_date = (datetime.now() + timedelta(days=months*30)).strftime("%d/%m/%Y")
        await query.message.reply_text(
            f"✅ *Payment Confirmed + Approved!*\n\n"
            f"👤 {name} ({username})\n"
            f"📦 {PLAN_NAMES.get(package,'')} — {months} လ\n"
            f"⏰ ကုန်ဆုံး: `{expire_date}`\n"
            f"🔑 Password: `{password}`\n\n"
            f"Member ကို DM ပို့ပြီးပြီ ✅",
            parse_mode='Markdown')

    # ── Slip Reject (Admin) ──
    elif data.startswith("slip_no_"):
        if query.from_user.id not in ADMIN_IDS:
            await query.answer("❌ Admin သာ လုပ်နိုင်တယ်", show_alert=True)
            return
        member_id = int(data.replace("slip_no_",""))
        pending_payment.pop(member_id, None)
        try:
            admin_link = f"\n💬 [Admin ကို ဆက်သွယ်](https://t.me/{ADMIN_USERNAME})" if ADMIN_USERNAME else ""
            await context.bot.send_message(
                chat_id=member_id,
                text=f"❌ *Payment မအတည်မပြုနိုင်ပါ*\n\n"
                     f"Slip မှားနိုင်သည် သို့မဟုတ် ငွေပမာဏ မပြည့်မှီပါ\n\n"
                     f"ပြန်လည် ကြိုးစားရန် /renew{admin_link}",
                parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Reject DM: {e}")
        await query.message.reply_text(f"❌ Rejected — Member ကို notify ပြီးပြီ")

    # ── UpdateID Confirm ──
    elif data.startswith("uid_ok_"):
        admin_id  = int(data.replace("uid_ok_",""))
        info      = pending_updateid.pop(admin_id, None)
        if not info:
            await query.message.reply_text("❌ Data ကုန်သွားပြီ")
            return
        target_username = info["target_username"]
        new_id          = info["new_id"]
        new_pw          = generate_password()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(SHEET_WEBHOOK, json={
                    "action":   "updateMemberId",
                    "username": target_username,
                    "newId":    str(new_id),
                    "password": new_pw,
                }, timeout=10, follow_redirects=True)
            result = resp.json()
            old_id = result.get("oldId", "?")
            if result.get("status") == "ok":
                # Notify member
                try:
                    await context.bot.send_message(
                        chat_id=new_id,
                        text=f"✅ *Account Update ပြီ*\n\n"
                             f"Telegram ID အသစ်နဲ့ ချိတ်ဆက်ပြီ\n"
                             f"🔑 New Password: `{new_pw}`\n\n"
                             f"🌐 https://kyawmintun08.github.io/Japan-Auction-Car-Checker-/",
                        parse_mode='Markdown')
                except Exception as e:
                    logger.error(f"UpdateID notify: {e}")
                await query.message.reply_text(
                    f"✅ *ID Update ပြီ*\n\n"
                    f"👤 @{target_username}\n"
                    f"🗑 ဟောင်း: `{old_id}`\n"
                    f"✅ အသစ်: `{new_id}`\n"
                    f"🔑 Password: `{new_pw}`",
                    parse_mode='Markdown')
            else:
                await query.message.reply_text(f"❌ @{target_username} မတွေ့ပါ")
        except Exception as e:
            await query.message.reply_text(f"❌ Error: {e}")

    elif data.startswith("uid_no_"):
        admin_id = int(data.replace("uid_no_",""))
        pending_updateid.pop(admin_id, None)
        await query.message.reply_text("❌ Cancel လုပ်ပြီး")

    # ── Quick Approve ──
    elif data.startswith("qa_"):
        parts     = data.split("_")
        target_id = int(parts[1])
        months    = int(parts[2])
        days      = months * 30
        try:
            chat            = await context.bot.get_chat(target_id)
            member_username = chat.username or chat.first_name or str(target_id)
        except:
            member_username = str(target_id)

        password   = generate_password()
        await save_member_to_sheet(str(target_id), member_username, days, password, "CH")
        invite_url = await create_invite_link(context, days)
        await send_approval_dm(context, target_id, months, password, invite_url)
        expire_date = (datetime.now() + timedelta(days=days)).strftime("%d/%m/%Y")
        await query.message.reply_text(
            f"✅ *Quick Approve ပြီး!*\n\n👤 @{member_username}\n📅 {months} လ\n"
            f"⏰ ကုန်ဆုံး: `{expire_date}`\n🔑 Password: `{password}`",
            parse_mode='Markdown')

# ── Membership Commands ────────────────────────────────
async def approve_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်"); return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Format: `/approve @username 1` သို့မဟုတ် `/approve 123456789 3`",
                                        parse_mode='Markdown'); return
    username_or_id = context.args[0].replace('@','')
    try:
        months = int(context.args[1])
    except:
        await update.message.reply_text("❌ လ ဂဏန်းထည့်ပါ", parse_mode='Markdown'); return
    # Optional package argument
    package = "WEB" if len(context.args) > 2 and context.args[2].upper() == "WEB" else "CH"
    days = months * 30
    try:
        member_id       = int(username_or_id)
        member_username = username_or_id
    except ValueError:
        member_id       = None
        member_username = username_or_id
    if member_id:
        try:
            chat = await context.bot.get_chat(member_id)
            member_username = chat.username or chat.first_name or str(member_id)
        except Exception as e:
            logger.error(f"get_chat: {e}")

    password   = generate_password()
    await save_member_to_sheet(
        str(member_id) if member_id else username_or_id,
        member_username, days, password, package)
    invite_url = await create_invite_link(context, days)
    if member_id:
        await send_approval_dm(context, member_id, months, password, invite_url)

    expire_date = (datetime.now() + timedelta(days=days)).strftime("%d/%m/%Y")
    txt = (f"✅ <b>Membership Approved!</b>\n\n"
           f"👤 @{member_username}\n"
           f"🆔 <code>{member_id or 'N/A'}</code>\n"
           f"📦 Package: {PLAN_NAMES.get(package,'')}\n"
           f"📅 <b>{months} လ</b>\n"
           f"⏰ ကုန်ဆုံး: <code>{expire_date}</code>\n"
           f"🔑 Password: <code>{password}</code>\n")
    if invite_url: txt += f"\n🔗 {invite_url}"
    await update.message.reply_text(txt, parse_mode='HTML')

async def members_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်"); return
    try:
        async with httpx.AsyncClient() as client:
            resp    = await client.post(SHEET_WEBHOOK, json={"action":"getMembers"}, timeout=10, follow_redirects=True)
            members = resp.json().get("members",[])
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}"); return
    if not members:
        await update.message.reply_text("👥 Member မရှိသေးဘူး"); return
    active  = [m for m in members if m.get('status') == 'ACTIVE']
    expired = [m for m in members if m.get('status') == 'EXPIRED']
    txt = f"👥 *Members*\n✅ Active: {len(active)} | ❌ Expired: {len(expired)}\n\n*✅ Active:*\n"
    for m in active:
        pkg_tag = f"[{m.get('package','CH')}]" if m.get('package') else ""
        txt += f"• @{m['username']} {pkg_tag} — ကုန်: `{m.get('expireDate','?')}`\n"
    if expired:
        txt += "\n*❌ Expired:*\n"
        for m in expired[:5]:
            txt += f"• @{m['username']} — `{m.get('expireDate','?')}`\n"
    await update.message.reply_text(txt, parse_mode='Markdown')

async def kick_member_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်"); return
    if not context.args:
        await update.message.reply_text("❌ Format: `/kick 123456789`", parse_mode='Markdown'); return
    try:
        target_id = int(context.args[0])
        success   = await kick_with_retry(context, target_id)
        if success:
            await update.message.reply_text(f"✅ `{target_id}` channel ကထုတ်ပြီ", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ Kick မအောင်မြင်ပါ — 3 ကြိမ် ကြိုးစားပြီး")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

# ── Auto Expire Check (every 12h) ─────────────────────
async def check_expired_members(context):
    global warned_3days
    try:
        async with httpx.AsyncClient() as client:
            resp    = await client.post(SHEET_WEBHOOK, json={"action":"getMembers"}, timeout=10, follow_redirects=True)
            members = resp.json().get("members",[])
        now = datetime.now(); kicked = []; kick_failed = []; expiring = []
        for m in members:
            uid = str(m.get('userId',''))
            if not uid: continue
            try:
                expire_date = datetime.strptime(m.get('expireDate','01/01/2000'), "%d/%m/%Y")
            except: continue
            days_left = (expire_date - now).days

            # 3-day warning + password reminder
            if 0 <= days_left <= 3 and uid not in warned_3days:
                expiring.append(m); warned_3days.add(uid)
                if uid.isdigit():
                    try:
                        # Get password from sheet
                        pw_resp = await (httpx.AsyncClient()).post(SHEET_WEBHOOK, json={
                            "action": "getPassword", "userId": uid}, timeout=10, follow_redirects=True)
                        pw_data  = pw_resp.json()
                        password = pw_data.get("password","")
                        pw_line  = f"\n🔑 Web Password: `{password}`\n" if password else ""
                        kb = []
                        if ADMIN_USERNAME:
                            kb = [[InlineKeyboardButton("💬 Admin ကို ဆက်သွယ်", url=f"https://t.me/{ADMIN_USERNAME}")]]
                        await context.bot.send_message(
                            chat_id=int(uid),
                            text=(f"⚠️ *Membership သတိပေးချက်!*\n\n"
                                  f"သင့် Membership *{days_left} ရက်* အတွင်း ကုန်ဆုံးမည်!\n"
                                  f"⏰ ကုန်ဆုံးရက်: `{m.get('expireDate','?')}`\n"
                                  f"{pw_line}\n"
                                  f"သက်တမ်းတိုးဖို့ /renew နှိပ်ပါ 🙏"),
                            parse_mode='Markdown',
                            reply_markup=InlineKeyboardMarkup(kb) if kb else None)
                    except Exception as e:
                        logger.error(f"3day warn: {e}")

            # Auto kick expired members
            if m.get('status') == 'EXPIRED' and uid.isdigit():
                success = await kick_with_retry(context, int(uid))
                if success:
                    kicked.append(m)
                else:
                    kick_failed.append(m)

        if kicked:
            txt = "🚫 *Auto Kick (Membership ကုန်ဆုံး):*\n\n"
            for m in kicked: txt += f"• @{m['username']} — `{m.get('expireDate','?')}`\n"
            await notify_admins(context, txt)

        if kick_failed:
            txt = "⚠️ *Kick မအောင်မြင် — ကိုယ်တိုင် ဆောင်ရွက်ပါ:*\n\n"
            for m in kick_failed: txt += f"• @{m['username']} — ID: `{m.get('userId','?')}`\n"
            txt += "\n`/kick [userId]` သုံးပါ"
            await notify_admins(context, txt)

        if expiring:
            txt = "⚠️ *Membership ၃ ရက်အတွင်း ကုန်ဆုံးမည်:*\n\n"
            for m in expiring: txt += f"• @{m['username']} — `{m.get('expireDate','?')}`\n"
            txt += "\nသက်တမ်းတိုး: `/approve [userId] [လ]`"
            await notify_admins(context, txt)
    except Exception as e:
        logger.error(f"check_expired: {e}")

# ── Main ──────────────────────────────────────────────
async def main():
    logger.info("Bot starting...")
    async with httpx.AsyncClient() as client:
        await client.post(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook",
                          params={"drop_pending_updates":True})
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("find",        find_car))
    app.add_handler(CommandHandler("model",       find_model))
    app.add_handler(CommandHandler("price",       add_price))
    app.add_handler(CommandHandler("history",     price_history_cmd))
    app.add_handler(CommandHandler("list",        list_cars))
    app.add_handler(CommandHandler("web",         web_link))
    app.add_handler(CommandHandler("approve",     approve_member))
    app.add_handler(CommandHandler("members",     members_list))
    app.add_handler(CommandHandler("kick",        kick_member_cmd))
    app.add_handler(CommandHandler("renew",       renew_cmd))
    app.add_handler(CommandHandler("mypassword",  mypassword_cmd))
    app.add_handler(CommandHandler("resetpass",   resetpass_cmd))
    app.add_handler(CommandHandler("updateid",    updateid_cmd))
    app.add_handler(CommandHandler("backup",      backup_cmd))
    app.add_handler(CommandHandler("upgrade",     upgrade_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.job_queue.run_repeating(check_expired_members, interval=43200, first=60)
    await app.initialize()
    await app.start()

    # ── Command Menu Scope Setup ──────────────────────
    # Member တွေ မြင်မည့် commands
    member_commands = [
        BotCommand("start",      "🚗 Bot စတင်ရန်"),
        BotCommand("find",       "🔍 Chassis ဖြင့်ရှာရန်"),
        BotCommand("model",      "🔎 Model အမည်ဖြင့်ရှာရန်"),
        BotCommand("history",    "📈 ဈေးနှုန်း မှတ်တမ်းကြည့်ရန်"),
        BotCommand("list",       "📊 ကားစာရင်း အားလုံးကြည့်ရန်"),
        BotCommand("web",        "🌐 Web App link ကြည့်ရန်"),
        BotCommand("renew",      "🔄 Membership သက်တမ်းတိုး"),
        BotCommand("mypassword", "🔑 Password ပြန်ယူရန်"),
    ]
    # Admin တွေ မြင်မည့် commands (member + admin)
    admin_commands = member_commands + [
        BotCommand("price",     "💰 ကားဈေးထည့်ရန် (Admin)"),
        BotCommand("approve",   "✅ Member approve လုပ်ရန် (Admin)"),
        BotCommand("members",   "👥 Member စာရင်းကြည့်ရန် (Admin)"),
        BotCommand("kick",      "🚫 Member ထုတ်ရန် (Admin)"),
        BotCommand("resetpass", "🔑 Password reset (Admin)"),
        BotCommand("updateid",  "🆔 Member ID update (Admin)"),
        BotCommand("backup",    "💾 CSV Backup (Admin)"),
    ]
    try:
        # Default scope — member commands
        await app.bot.set_my_commands(
            member_commands,
            scope=BotCommandScopeAllPrivateChats()
        )
        # Admin scope — full commands
        for admin_id in ADMIN_IDS:
            try:
                await app.bot.set_my_commands(
                    admin_commands,
                    scope=BotCommandScopeChat(chat_id=admin_id)
                )
            except Exception as e:
                logger.warning(f"Admin scope set failed for {admin_id}: {e}")
        logger.info("Command scopes set successfully")
    except Exception as e:
        logger.error(f"set_my_commands error: {e}")
    # ──────────────────────────────────────────────────

    await app.updater.start_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
    logger.info("Bot polling!")
    await asyncio.Event().wait()

if __name__ == '__main__':
    asyncio.run(main())
