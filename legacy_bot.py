import asyncio
import json
import os
from aiohttp import web
import re
import random
import string
import logging
import httpx
from phase1.phase1_client import JaccPhase1Client, JaccPhase1Error
from jdm_lookup_service import build_jdm_http_service
from qwen_text_service import build_qwen_text_http_service
from website_payment_upload import build_website_payment_http_service
from website_google_payment_upload import build_google_member_payment_http_service
from website_google_channel import build_google_member_channel_http_service
from datetime import datetime, timedelta, timezone
from payment_audit import (
    normalize_amount,
    validate_member_record,
    validate_payment_batch,
    validate_payment_slip,
)
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram import BotCommandScopeAllPrivateChats, BotCommandScopeChat
from telegram.ext import Application, AIORateLimiter, CommandHandler, MessageHandler, CallbackQueryHandler, ChatMemberHandler, filters, ContextTypes
from telegram.helpers import escape_markdown

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
SHEET_SERVER_KEY      = os.environ.get('SHEET_SERVER_KEY', '').strip()
CHANNEL_ID            = os.environ.get('CHANNEL_ID', '-1003749046571')
ADMIN_IDS             = [int(x) for x in os.environ.get('ADMIN_IDS', '').split(',') if x.strip().isdigit()]
ADMIN_USERNAME        = os.environ.get('ADMIN_USERNAME', '')
ADMIN_REAL_NAME       = os.environ.get('ADMIN_REAL_NAME', 'Kyaw Min Tun')
CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME', '')
CLOUDINARY_API_KEY    = os.environ.get('CLOUDINARY_API_KEY', '')
CLOUDINARY_API_SECRET = os.environ.get('CLOUDINARY_API_SECRET', '')
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
phase1 = None
if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
    phase1 = JaccPhase1Client(
        supabase_url=SUPABASE_URL,
        service_role_key=SUPABASE_SERVICE_ROLE_KEY,
    )
# ── Membership Plan Pricing (ks) ──────────────────────
PLAN_CH_1M  = int(os.environ.get('PLAN_CH_1M',  '15000'))
PLAN_CH_2M  = int(os.environ.get('PLAN_CH_2M',  '30000'))
PLAN_CH_3M  = int(os.environ.get('PLAN_CH_3M',  '40000'))
PLAN_CH_5M  = int(os.environ.get('PLAN_CH_5M',  '70000'))
PLAN_WEB_1M = int(os.environ.get('PLAN_WEB_1M', '30000'))
PLAN_WEB_2M = int(os.environ.get('PLAN_WEB_2M', '55000'))
PLAN_WEB_3M = int(os.environ.get('PLAN_WEB_3M', '80000'))
PAYMENT_INFO = os.environ.get('PAYMENT_INFO', 'KPay / Wave: ဆက်သွယ်ရန် @' + ADMIN_USERNAME)

# ── Promo Codes: "CODE:days:maxuses,CODE2:days:maxuses" ──
PROMO_CODES_RAW = os.environ.get('PROMO_CODES', '')

LOC_MAESOT   = "MaeSot Freezone"
LOC_KLANG9   = "Klang9 Freezone"
LOC_BORDER44 = "Best Border-44 Gate"
ANDROID_APP_VERSION = "3"
# Hosted from this repo's own GitHub Pages deploy (same place index.html
# already serves reliably) instead of a third-party pCloud share link,
# which required navigating pCloud's own web UI rather than downloading
# directly and could expire/rate-limit independently of anything we control.
ANDROID_APP_URL = "https://kyawmintun08.github.io/Japan-Auction-Car-Checker/downloads/JACC-Android-v1.15.apk"

PLAN_PRICES = {
    "CH":  {1: PLAN_CH_1M,  2: PLAN_CH_2M,  3: PLAN_CH_3M,  5: PLAN_CH_5M},
    "WEB": {1: PLAN_WEB_1M, 2: PLAN_WEB_2M, 3: PLAN_WEB_3M},
}
PLAN_NAMES = {
    "CH":  "📱 Standard",
    "WEB": "💎 Web Premium",
}

CHASSIS_PREFIX_MAP = {
    # ── Data-driven from live Sheet1 (5,051 listings, 2026-03 to 2026-08) ──
    # Majority-vote canonical model per chassis prefix, spelling/brand-prefix
    # cleaned. Used only as a fallback GUESS when the entered/OCR'd Model text
    # is missing or UNKNOWN — never overrides a real entered value, since some
    # prefixes legitimately host more than one distinct nameplate (badge-share
    # platforms like Hijet/Pixis/Sambar, Noah/Voxy, Probox/Succeed, etc. are
    # intentionally kept separate rather than merged; see chassis_model_final_mapping.csv).
    "A300S": "Mira",
    "ACA21": "RAV4",
    "ACA33": "Vanguard",
    "ACA38": "Vanguard",
    "ACAAZ": "RAV4",
    "ACR50": "Estima",
    "ACU25": "Highlander",
    "ACU30": "Harrier",
    "ACU35": "Harrier",
    "AGH30": "Alphard",
    "AGH35": "Alphard",
    "AGL10": "RX",
    "AGL10X": "RX",
    "AGP2": "Fit",
    "AGZ10": "NX",
    "AGZ210": "NX",
    "AHR20": "Estima Hybrid",
    "ANH10": "Alphard",
    "ANH15": "Alphard",
    "ANH20": "Vellfire",
    "ANH25": "Vellfire",
    "ANH2E": "Alphard",
    "ARZ10": "NX",
    "AZE156": "Blade",
    "AZE15B": "Blade",
    "AZEO": "Leaf",
    "AZR60": "Voxy",
    "AZR65": "Voxy",
    "B21W": "Dayz",
    "B22W": "Dayz",
    "B2JW": "Dayz Roox",
    "B90": "Fuso Canter",
    "BA00": "Fuso Canter",
    "BA62T": "Carry Truck",
    "BJLW": "Truck",
    "CG48A": "Diesel Condor",
    "CG5ZA": "UD",
    "CK542B": "Truck",
    "CM55": "Liteace",
    "CM85": "Townace Truck",
    "CR6": "Accord Hybrid",
    "CV2YB": "UD",
    "CW4XL": "UD Trucks",
    "CW5W": "Outlander",
    "CW5XL": "UD Quon",
    "CW6W": "Outlander",
    "CX2YA": "UD",
    "CY4BE": "Diesel Quon Truck",
    "D48YV": "UD Truck",
    "DA16T": "Carry Truck",
    "DA17V": "Every Van",
    "DA26T": "Carry",
    "DA52T": "Carry Truck",
    "DA62T": "Carry Truck",
    "DA63T": "Carry Truck",
    "DA64V": "Every",
    "DA65T": "Carry Truck",
    "DAB3T": "Carry Truck",
    "DAB4V": "Every Van",
    "DAB64V": "Every",
    "DABUV": "Every",
    "DALBT": "Carry",
    "DB52T": "Carry Truck",
    "DB63T": "Carry Truck",
    "DC51T": "Carry Truck",
    "DD51B": "Carry Truck",
    "DG63T": "Scrum Truck",
    "DH206": "Hiace",
    "DK5FW": "CX-3",
    "DMT31": "X-TRAIL",
    "DN731": "X-TRAIL",
    "DNT31": "X-TRAIL",
    "DNT32": "X-TRAIL",
    "DR17V": "Every",
    "E12": "Note",
    "F15": "Juke",
    "FB70BB": "Canter",
    "FB73B": "Canter",
    "FBA00": "Fuso Canter",
    "FBA30": "Fuso Canter",
    "FBA50": "Fuso Canter",
    "FBA60": "Fuso Canter",
    "FBA70EL": "Canter",
    "FC6JCF": "Truck",
    "FC6JKW": "Profia",
    "FC9JLA": "Ranger",
    "FD70BB": "Canter",
    "FD7JDY": "Ranger",
    "FD7JLF": "Ranger",
    "FD7JLY": "Ranger",
    "FDFA": "Ranger",
    "FE70B": "Fuso Canter",
    "FE70DB": "Canter",
    "FE71DB": "Fuso Canter",
    "FE71DSD": "Fuso Canter",
    "FE723E": "Fuso Canter Truck",
    "FE72DE": "Canter",
    "FE72EB": "Canter",
    "FE72EC": "Canter",
    "FE72EE": "Canter",
    "FE72EEV": "Canter",
    "FE72EF": "Canter",
    "FE73B": "Fuso Canter",
    "FE73DB": "Canter",
    "FE73DN": "Canter Truck",
    "FE73EB": "Canter",
    "FE73EC": "Fuso Canter",
    "FE74BV": "Canter Truck",
    "FE74DV": "Fuso Canter",
    "FE7JMW": "Ranger",
    "FE82B": "Fuso Canter",
    "FE82BS": "Canter",
    "FE82D": "Fuso Canter Truck",
    "FE82DE": "Canter",
    "FE82DEX": "Canter",
    "FE82EE": "Canter",
    "FE82FE": "Canter",
    "FE850": "Canter",
    "FEA20": "Fuso Canter",
    "FEA50": "Fuso Canter",
    "FEA80": "Canter",
    "FEB50": "Canter",
    "FEB90": "Fuso Canter",
    "FF71DB": "Fuso Canter",
    "FF73BG": "Fuso Canter",
    "FK1RJ": "Fighter",
    "FK417F": "Fuso Fighter",
    "FK616F": "Fighter",
    "FK61F": "Fuso Fighter",
    "FK61HM": "Fuso Fighter",
    "FK61J": "Fuso Fighter",
    "FK61R": "Fuso Fighter",
    "FK64F": "Fuso Fighter",
    "FK71D": "Fuso",
    "FK71F": "Fuso Canter",
    "FK71R": "Fuso Canter",
    "FK74F": "Fuso Fighter",
    "FK74R": "Fuso Fighter",
    "FK7JDC": "Fuso Fighter",
    "FR1SPY": "Truck",
    "FRG1F": "Ranger",
    "FRJS": "Fuso Canter",
    "FS54JZ": "Super Great",
    "FSJEKX": "Profia",
    "FV50JK": "Fuso Super Great Concrete Mixer Truck",
    "FV50JX": "Fuso Super Great",
    "FVZNY12": "AD Van",
    "FW1EXW": "Rofia",
    "FW1EZE": "Profia Truck",
    "FW1JAB": "Profia",
    "G4HW": "Rvr",
    "G4MW": "Rvr",
    "GA3W": "Rvr",
    "GA4W": "Rvr",
    "GAB3W": "Rvr",
    "GB3": "Freed",
    "GBS202": "Crown",
    "GC20": "Wish",
    "GC30": "Boon",
    "GE20": "Wish",
    "GE21": "Impreza",
    "GE25": "Wish",
    "GE6": "Fit",
    "GE8": "Fit",
    "GEF22": "Wish",
    "GEF25": "Wish",
    "GF6": "Fit",
    "GF8W": "Outlander",
    "GG6": "Fit",
    "GGE25": "Wish",
    "GGH20": "Alphard",
    "GGH25": "Alphard",
    "GGL20": "Alphard",
    "GGLH20": "Alphard",
    "GH20": "Alphard",
    "GHE22": "Wish",
    "GJA3W": "Rvr",
    "GK3": "Fit",
    "GK5": "Fit",
    "GK6XA": "UD Quon",
    "GLF8W": "Outlander",
    "GM4": "Grace",
    "GP1": "Fit",
    "GP2": "Fit Hybrid",
    "GP3": "Freed",
    "GP5": "Fit",
    "GP7": "Shuttle",
    "GP8": "Fit",
    "GPS14": "Crown",
    "GRS18": "Crown",
    "GRS180": "Crown",
    "GRS182": "Crown",
    "GRS184": "Crown",
    "GRS20": "Crown",
    "GRS200": "Crown",
    "GRS201": "Crown",
    "GRS202": "Crown",
    "GRS203": "Crown",
    "GRS204": "Crown",
    "GRS206": "Crown",
    "GRS210": "Crown",
    "GRS214": "Crown",
    "GRS262": "Crown",
    "GRX120": "Mark X",
    "GRX121": "Mark X",
    "GRX130": "Mark X",
    "GRX133": "Mark X",
    "GRX135": "Mark X",
    "GRX200": "Crown",
    "GSR200": "Crown",
    "GSR201": "Crown",
    "GSR202": "Crown",
    "GSR204": "Crown",
    "GSR210": "Crown",
    "GSRS201": "Crown",
    "GSV60": "ES",
    "GWS204": "Crown",
    "GX110": "Mark Ii",
    "GZ8B": "Fit",
    "GZE20": "Wish",
    "GZE6": "Fit",
    "GZF8W": "Outlander",
    "GZRS200": "Crown",
    "GZRS202": "Crown",
    "GZS180": "Crown",
    "GZS19B": "GS",
    "GZS201": "Crown",
    "GZS204": "Crown Majesta",
    "H2F23": "Atlas",
    "H34S": "Wagon R",
    "H53A": "Pajero Mini",
    "H55A": "Pajero Mini",
    "H57A": "Pajero Mini",
    "H58A": "Pajero Mini",
    "H59A": "Kix",
    "H77W": "Pajero Io",
    "HA25S": "Alto",
    "HA25V": "Alto",
    "HA35S": "Alto Eco",
    "HA36S": "Alto",
    "HA36V": "Alto",
    "HB35S": "Carol",
    "HB36S": "Carol",
    "HDJ10": "Land Cruiser",
    "HDJ101": "Land Cruiser 100",
    "HE12": "Note",
    "HGC30": "Boon",
    "HK260F": "Diesel Condor",
    "HNT32": "X-TRAIL",
    "HT32": "X-TRAIL",
    "J111G": "Terios Kid",
    "J131G": "Terios",
    "J19204": "Bongo Truck",
    "J210E": "Rush",
    "JAZ5": "Fit",
    "JB23W": "Jimny",
    "K13": "March",
    "K58A": "Pajero Io",
    "K82T": "Bongo Truck",
    "KDH200": "Hiace Van",
    "KDH200M": "Hiace Van",
    "KDH201": "Hiace",
    "KDH205": "Hiace",
    "KDH205B": "Hiace Van",
    "KDH206": "Hiace",
    "KDH20B": "Hiace",
    "KDH20V": "Hiace",
    "KDH211": "Hiace Van",
    "KDH225": "Hiace",
    "KDH25": "Hiace",
    "KDJ95": "Land Cruiser Prado",
    "KDN185": "Hilux Surf",
    "KDN201": "Hiace",
    "KE2": "CX-5",
    "KE2AW": "CX-5",
    "KE2FW": "CX-5",
    "KE2PW": "CX-5",
    "KE2RFW": "CX-5",
    "KE2W": "CX-5",
    "KECFW": "CX-5",
    "KEEFW": "CX-5",
    "KEOFW": "CX-5",
    "KEPAW": "CX-5",
    "KF2FW": "CX-5",
    "KG030": "Mira Cocoa",
    "KG2C30": "Boon",
    "KGC10": "Passo",
    "KGC30": "Passo",
    "KGC35": "Passo",
    "KGJ10": "Iq",
    "KGQ10": "Passo",
    "KGQ30": "Passo",
    "KJH201": "Hiace",
    "KM51": "Liteace Truck",
    "KM70": "Liteace",
    "KM75": "Townace",
    "KM80": "Liteace Truck",
    "KP2T": "Bongo Truck",
    "KPF15": "Juke",
    "KQJ10": "Iq",
    "KSP130": "Vitz",
    "KSP90": "Vitz",
    "KZH100": "Hiace",
    "KZH106": "Hiace",
    "KZH110": "Hiace",
    "KZJ95": "Land Cruiser Prado",
    "KZN185": "Hilux Surf",
    "L275S": "Mira",
    "LA100S": "Move",
    "LA106S": "Move",
    "LA150S": "Move",
    "LA250S": "Cast",
    "LA300A": "Pixis Epoch",
    "LA300S": "Mira E:s",
    "LA310S": "Mira E:s",
    "LA35": "Mira E:s",
    "LA350A": "Pixis Epoch",
    "LA350S": "Mira E:s",
    "LA360S": "Mira E:s",
    "LA600S": "Tanto",
    "M13": "March",
    "M233": "Wagon R",
    "M31": "X-TRAIL",
    "M6010": "Passo",
    "M700S": "Boon",
    "MCU25": "Kluger",
    "MCU30": "Harrier",
    "MCU31": "Harrier",
    "MCU35": "Harrier",
    "MCU36": "Harrier",
    "MH23S": "Wagon R",
    "MH34S": "Wagon R",
    "MH44S": "Wagon R",
    "MH55S": "Wagon R",
    "MHBS": "Wagon R",
    "MHN4S": "Solio",
    "MJ23S": "Wagon R",
    "MK25N00083": "Condor",
    "MK35A": "Condor",
    "MK36A": "UD Condor Mk",
    "MK36B": "Diesel Condor",
    "MK36C": "UD",
    "MK36J": "Diesel Condor",
    "MK38C": "UD",
    "MK98C": "UD Condor",
    "MKSGA": "Diesel",
    "MKZIIBN": "Isuzu Elf",
    "MNH10": "Alphard",
    "MNH15": "Alphard",
    "MNHA10": "Alphard",
    "MU31": "Harrier",
    "MV33A": "Diesel",
    "MXPK11": "Aqua",
    "N131": "X-TRAIL",
    "N31": "X-TRAIL",
    "N731": "X-TRAIL",
    "N732": "X-TRAIL",
    "NB1": "X-TRAIL",
    "NC10": "Iq",
    "NCP100": "Ractis",
    "NCP105": "Ractis",
    "NCP120": "Ractis",
    "NCP125": "Ractis",
    "NCP160": "Probox",
    "NCP165": "Probox",
    "NCP265": "Probox",
    "NCP50": "Probox",
    "NCP51": "Probox",
    "NCP51V": "Probox",
    "NCP55": "Probox",
    "NCP55J": "Probox",
    "NCP58": "Probox",
    "NCP59": "Probox",
    "NCP5B": "Probox",
    "NCP61": "Ist",
    "NCP66": "Probox",
    "NCP95": "Vitz",
    "NCP96": "Belta",
    "NCPBL": "Probox",
    "NCPI65": "Probox",
    "NCR165": "Probox",
    "NE15": "Juke",
    "NF15": "Juke",
    "NGC30": "Passo",
    "NGJ10": "Iq",
    "NGP55": "Probox",
    "NH10": "Alphard",
    "NHP10": "Aqua",
    "NHP11": "Aquae",
    "NHP130": "Vitz",
    "NHP170": "Sienta",
    "NKE16": "Corolla Fielder",
    "NKE160": "Corolla Fielder",
    "NKE165": "Corolla Fielder",
    "NLP51": "Probox",
    "NLPS1": "Probox",
    "NP51": "Probox",
    "NQC30": "Passo",
    "NR65": "Voxy",
    "NRE161": "Corolla Axio",
    "NSP10": "Aqua",
    "NSP120": "Ractis",
    "NSP130": "Vitz",
    "NSP135": "Vitz",
    "NSP160": "Probox",
    "NSP165": "Probox",
    "NSP166": "Probox",
    "NSP170": "Sienta",
    "NT31": "X-TRAIL",
    "NT31F": "X-TRAIL",
    "NT32": "X-TRAIL",
    "NT3L": "X-TRAIL",
    "NTS1": "X-TRAIL",
    "NVY12": "AD Van",
    "NY12": "AD Van",
    "NZ144": "Corolla Fielder",
    "NZE121": "Corolla",
    "NZE121L": "Corolla Fielder",
    "NZE124": "Corolla Fielder",
    "NZE141": "Corolla Axio",
    "NZE141G": "Corolla Fielder",
    "NZE144": "Corolla Axio",
    "NZE161": "Corolla Axio",
    "NZE164": "Corolla Fielder",
    "NZJ10": "Iq",
    "P5": "Fit",
    "PK36A": "Condor",
    "PK50C": "Diesel Truck",
    "Q070363": "Voxy",
    "R03": "Vezel",
    "R04": "Vezel",
    "R75": "Voxy",
    "RD3": "Vezel",
    "RE3": "CR-V",
    "RE4": "CR-V",
    "RM1": "CR-V",
    "RM4": "CR-V",
    "RP75": "Voxy",
    "RR75": "Voxy",
    "RT3": "Crossroad",
    "RU1": "Vezel",
    "RU3": "Vezel",
    "RU4": "Vezel",
    "RV3": "Vezel",
    "RV4": "Vezel",
    "RZH101": "Hiace",
    "S200P": "Hijet Truck",
    "S201C": "Hijet Truck",
    "S201J": "Sambar Truck",
    "S201P": "Hijet Truck",
    "S210": "Pixis Truck",
    "S210P": "Hijet Truck",
    "S210U": "Pixis Truck",
    "S2110": "Pixis Truck",
    "S211J": "Sambar Truck",
    "S211P": "Hijet Truck",
    "S211T": "Hijet Truck",
    "S211U": "Pixis Truck",
    "S291P": "Hijet Truck",
    "S2SF24": "Atlas",
    "S300U": "Pixis Truck",
    "S321V": "Pixis Van",
    "S402M": "Town Ace Van",
    "S402U": "Liteace Van",
    "S412M": "Townace Van",
    "S412U": "Liteace Truck",
    "S500J": "Sambar Truck",
    "S500P": "Hijet Truck",
    "S501P": "Hijet Truck",
    "S5100": "Hijet Truck",
    "S510J": "Sambar Truck",
    "S510P": "Hijet Truck",
    "S510U": "Hijet Truck",
    "S511P": "Hijet Truck",
    "S521P": "Hijet Truck",
    "S801J": "Sambar Truck",
    "S85": "Liteace Truck",
    "SCP10": "Vitz",
    "SCP100": "Ractis",
    "SCP13": "Vitz",
    "SCP90": "Vitz",
    "SCP92": "Belta",
    "SH1EDJ": "Profia",
    "SJ5": "Forester",
    "SJP2T": "Bongo",
    "SK22L": "Bongo Truck",
    "SK22T": "Bongo",
    "SK827TN": "Vanette Truck",
    "SK82L": "Bongo",
    "SK82LN": "Vanette Truck",
    "SK82N": "Vanette",
    "SK82T": "Bongo Truck",
    "SK82TM": "Delica Van",
    "SK82TN": "Vanette Truck",
    "SKF27": "Bongo",
    "SKF2LN": "Vanette",
    "SKF2T": "Bongo Truck",
    "SKF2TN": "Vanette",
    "SKP2L": "Bongo Truck",
    "SKP2LN": "Vanette Truck",
    "SKP2T": "Bongo Truck",
    "SKP2TL": "Vanette",
    "SKP2TN": "Vanette Truck",
    "SKPMN": "Vanette",
    "SKPTN": "Vanette",
    "SLP2L": "Bongo",
    "SLP2T": "Bongo Truck",
    "SNCP165": "Probox",
    "SRP2TN": "Vanette Truck",
    "SS1EKA": "Profia",
    "T31": "X-TRAIL",
    "T32": "X-TRAIL",
    "TDA4W": "Grand Vitara",
    "THGPS": "Fit",
    "TNT31": "X-TRAIL",
    "TRH200": "Hiace",
    "TRH214": "Hiace Wagon",
    "TRH219": "Hiace",
    "TRJ120": "Prado",
    "U50JX": "Super Great",
    "U62TM": "Minicab Truck",
    "UB573GW": "Isuzu Bighorn",
    "UCF31": "Celsior",
    "USF40": "LS",
    "UVF45": "LS",
    "UVF46": "LS 600H L",
    "UZJ100": "Land Cruiser",
    "UZNY12": "AD Van",
    "V2NY12": "AD Van",
    "V46": "Pajero",
    "V75W": "Pajero",
    "V98W": "Pajero",
    "VBNY12": "AD Van",
    "VE12": "Note",
    "VE15": "Juke",
    "VF15": "Juke",
    "VN12": "AD Van",
    "VNH20": "Alphard",
    "VNZY12": "Advan",
    "VY12": "AD Van",
    "VZN11": "AD Van",
    "VZNT12": "AD Van",
    "VZNY12": "AD Van",
    "W2NY12": "AD Van",
    "WHS5T": "Titan",
    "WWZZZ167DM": "Beetle",
    "WWZZZ16ZCM": "Beetle",
    "WWZZZ16ZDM": "Beetle",
    "WWZZZ16ZEM": "Beetle",
    "XKU308": "Dyna",
    "XKU508": "Dutro",
    "XZC610": "Dutro",
    "XZU302": "Dutro",
    "XZU304": "Dutro Shari",
    "XZU312": "Dutro",
    "XZU314": "Dyna",
    "XZU655": "Dutro",
    "XZU6B5": "Dutro",
    "Y12": "AD Van",
    "YF15": "Juke",
    "YF1S": "Juke",
    "YM55": "Townace",
    "YP15": "Juke",
    "Z71S": "Swift",
    "ZC11S": "Swift",
    "ZC32S": "Swift",
    "ZC53S": "Swift",
    "ZC71S": "Swift",
    "ZC72": "Swift",
    "ZC723": "Swift",
    "ZC72S": "Swift",
    "ZC83S": "Swift",
    "ZCZ23": "Swift",
    "ZD11S": "Swift",
    "ZD72S": "Swift",
    "ZD83S": "Swift",
    "ZE2": "Insight",
    "ZE3": "Insight",
    "ZEG20": "Wish",
    "ZF2": "Insight",
    "ZF3": "Insight",
    "ZG20": "Wish",
    "ZG2E25": "Wish",
    "ZG72S": "Swift",
    "ZGB20": "Wish",
    "ZGC22": "Wish",
    "ZGE2": "Wish",
    "ZGE20": "Wish",
    "ZGE20G": "Wish",
    "ZGE21": "Wish",
    "ZGE22": "Wish",
    "ZGE25": "Wish",
    "ZGE25G": "Wish",
    "ZGE2B": "Wish",
    "ZGE2S": "Wish",
    "ZGF22": "Wish",
    "ZGIE20": "Wish",
    "ZGL20": "Wish",
    "ZGLE25": "Wish",
    "ZGM11": "Isis",
    "ZGZE21": "Wish",
    "ZGZE25": "Wish",
    "ZNE14": "Wish",
    "ZR51": "Wish",
    "ZR60": "Voxy",
    "ZR70": "Noah",
    "ZR75": "Voxy",
    "ZRA70": "Voxy",
    "ZRE140": "Corolla Fielder",
    "ZRE142": "Corolla Fielder",
    "ZRE162": "Corolla Fielder",
    "ZRR70": "Voxy",
    "ZRR75": "Voxy",
    "ZRR80": "Voxy",
    "ZRR85": "Voxy",
    "ZRR95": "Voxy",
    "ZRRTB": "Voxy",
    "ZRT260": "Premio",
    "ZRT261": "Premio",
    "ZRT265": "Premio",
    "ZRT272": "Avensis",
    "ZSP110": "Ist",
    "ZSU60": "Harrier",
    "ZSU65": "Harrier",
    "ZUW30": "Prius",
    "ZVW30": "Prius",
    "ZVW35": "Prius Alpha",
    "ZVW50": "Prius",
    "ZW30": "Prius",
    "ZWA10": "Ct 200H",
    "ZWR80": "Voxy",
    "ZYW30": "Prius",
    "ZYX10": "C-HR",

    # ── European VIN prefixes (unrelated to JDM chassis codes above) ──
    "WVWZZZ": "NEW BEETLE",
    "WWWZZZ": "NEW BEETLE",
    "WVW": "VW",
    "WAU": "AUDI",
    "WBA": "BMW",
    "WBS": "BMW M",
    "WDB": "MERCEDES-BENZ",
    "WDC": "MERCEDES-BENZ",
    "WDD": "MERCEDES-BENZ",
    "SAJ": "JAGUAR",
    "SAL": "LAND ROVER",
    "SAR": "RANGE ROVER",
    "VF1": "RENAULT",
    "ZFA": "FIAT",
    "ZFF": "FERRARI",
    "ZAR": "ALFA ROMEO",
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
pending_auction_list = {}  # admin_id -> staged OCR list awaiting confirmation
pending_payment = {}   # user_id -> {package, months, amount, username, name, slips}


def parse_slip_amount(value):
    """Return a positive integer amount, or None when unreadable."""
    if value in (None, "", "UNKNOWN", "N/A", "-", "—"):
        return None
    try:
        digits = re.sub(r"[^0-9]", "", str(value))
        amount = int(digits) if digits else 0
        return amount if amount > 0 else None
    except (TypeError, ValueError):
        return None


def slip_transaction_key(slip_info):
    """Normalize a transaction number for duplicate-slip detection."""
    value = str(
        slip_info.get("TRANSACTION_NO", slip_info.get("REFERENCE", "")) or ""
    ).strip().upper()
    if value in ("", "UNKNOWN", "N/A", "-"):
        return ""
    return re.sub(r"[^A-Z0-9]", "", value)


def payment_slip_summary(slips):
    """Return total amount and a readable summary of all submitted slips."""
    total = sum(int(s.get("amount_num", 0) or 0) for s in slips)
    lines = []
    for index, slip in enumerate(slips, 1):
        info = slip.get("slip_info", {})
        txn = info.get("TRANSACTION_NO", info.get("REFERENCE", "UNKNOWN"))
        pay_type = info.get("TYPE", "UNKNOWN")
        date = info.get("DATE", "UNKNOWN")
        time = info.get("TIME", "UNKNOWN")
        lines.append(
            f"{index}. {pay_type} — {int(slip.get('amount_num', 0) or 0):,} ks — "
            f"Txn: `{txn}` — {date} {time}"
        )
    return total, lines
pending_updateid = {}  # user_id -> {target_username, old_id, new_id}
pending_edit     = {}  # user_id -> {chassis, field}
pending_broadcast= {}  # user_id -> {pkg_filter, waiting_photo}
pending_broadcast_text = {}  # user_id -> {pkg_filter, message} awaiting Confirm/Cancel
pending_request  = {}  # user_id -> {step, data}
proxy_sessions   = {}  # session_id -> {customerId, brokerId, reqId, status}
pending_rating   = {}  # customer_id -> {reqId, brokerId, brokerTgId}
pending_deposit  = {}  # customer_id -> {reqId, brokerTgId, step, slip_info}
active_timers    = {}  # req_id -> asyncio.Task
nodep_pending = {}  # req_id -> {customerId, brokerTgId, brokerId}
warned_3days   = set()
used_deposit_txns = set()  # TRANSACTION_NO already confirmed via dep_ok_, this process's lifetime
promo_used     = {}
rate_limit     = {}
pending_setqr    = {}  # admin_id -> "kpay" / "wave" / "cb"
payment_qr_cache = {}  # method -> {"file_id": str, "ts": datetime}

# ── NEW: Broker pending target (dual-session routing) ──
pending_broker_target = {}  # broker_tg_id -> {text, is_photo, file_bytes, caption, sessions}

# ── Rate Limiting ──────────────────────────────────────
def check_rate_limit(user_id: int, max_req: int = 10, window: int = 60) -> bool:
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
async def is_active_member(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        return True
    try:
        # Same getMembers() timeout ceiling as get_member_record(): Apps
        # Script's project-wide LockService lock (up to 30s wait) plus O(n)
        # session-sheet scans means 10s here used to time out and silently
        # report an active paying member as "not a member" — e.g. blocking
        # /mypassword — with the exception swallowed and no log trail.
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.post(SHEET_WEBHOOK, json={"action":"getMembers","serverKey":SHEET_SERVER_KEY}, timeout=40)
        payload = resp.json()
        # Apps Script answers HTTP 200 even for its own backend errors (e.g.
        # server_key_not_configured), so an error body's missing "members"
        # key would otherwise silently look identical to "no members at
        # all" -- reporting a real active member as inactive. Log it
        # distinctly so it's diagnosable instead of looking like a genuine
        # non-member.
        if str(payload.get("status") or "").strip().lower() == "error":
            logger.error(f"is_active_member backend error user={user_id}: {payload.get('message') or payload}")
            return False
        members = payload.get("members", [])
        for m in members:
            if str(m.get("userId","")) == str(user_id):
                return m.get("status","") == "ACTIVE"
    except Exception as exc:
        logger.error(f"is_active_member getMembers failed user={user_id} type={type(exc).__name__} err={exc}")
    return False


async def get_member_record(user_id: int | str) -> dict | None:
    """Return the current Members row for one Telegram user without mutating it."""
    try:
        is_admin_record = int(user_id) in ADMIN_IDS
    except (TypeError, ValueError):
        is_admin_record = False
    if is_admin_record:
        return {"userId": str(user_id), "status": "ACTIVE", "package": "WEB", "isAdmin": True}
    if not SHEET_WEBHOOK:
        return {"__lookup_error__": "sheet_webhook_missing"}
    try:
        # getMembers() on the Apps Script side used to fan out into a full
        # sessions-sheet scan per non-active member row (fixed separately in
        # Code.gs/_revokeMemberSessionsBulk_ — requires a manual redeploy to
        # Apps Script to take effect). On top of that, doPost() holds a
        # project-wide LockService lock (up to 30s wait) shared by every
        # webhook action, so a getMembers() call can also queue behind a
        # slow write (e.g. an auction-list import) from another request.
        # 40s clears the lock's own 30s ceiling with headroom; this stays a
        # stopgap until the Code.gs fix is actually redeployed.
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.post(
                SHEET_WEBHOOK,
                json={"action": "getMembers", "serverKey": SHEET_SERVER_KEY},
                timeout=40,
            )
        resp.raise_for_status()
        payload = resp.json()
        # Apps Script always answers HTTP 200, even for its own backend errors
        # (e.g. server_key_not_configured) -- resp.raise_for_status() never
        # catches those. Without this check, payload.get("members", []) on an
        # error body silently returns [], indistinguishable from "this
        # Telegram account genuinely has no Members row" -- which is exactly
        # what let a real KICKED-but-existing member get told to use
        # /newmember instead of /renew during a serverKey misconfiguration.
        if str(payload.get("status") or "").strip().lower() == "error":
            logger.warning(
                "get_member_record backend error for %s: %s",
                user_id, payload.get("message") or payload,
            )
            return {"__lookup_error__": "member_lookup_backend_error"}
        members = payload.get("members", [])
        target_id = str(user_id).strip()
        for member in members:
            member_id = (
                member.get("userId")
                or member.get("userID")
                or member.get("UserID")
                or member.get("telegramId")
            )
            if str(member_id or "").replace(".0", "").strip() == target_id:
                return member
    except Exception as exc:
        logger.warning("get_member_record failed for %s: %s: %s", user_id, type(exc).__name__, exc)
        return {"__lookup_error__": "member_lookup_failed"}
    return None


def is_current_member_record(record: dict | None) -> bool:
    """Match the Apps Script rule: only an ACTIVE row is a current member.

    EXPIRED/KICKED/BANNED rows remain historical records and are safely reused by
    saveMember instead of creating a duplicate row or blocking a new application.
    """
    if not record or record.get("__lookup_error__"):
        return False
    return str(record.get("status") or "").strip().upper() == "ACTIVE"


async def validate_payment_flow(user_id: int | str, action: str) -> dict:
    """Fail closed for current members, while allowing inactive-row reactivation."""
    normalized_action = str(action or "renew").strip().lower()
    record = await get_member_record(user_id)
    if record and record.get("__lookup_error__"):
        return {"ok": False, "record": None, "reason": "member_lookup_unavailable"}
    has_record = record is not None
    is_current = is_current_member_record(record)
    normalized_package = str((record or {}).get("package") or "").upper().replace("-", "")
    if normalized_action == "upgrade" and normalized_package in ("WEB", "WEBPROMO"):
        return {"ok": False, "record": record, "reason": "already_premium"}
    if normalized_action == "join" and is_current:
        return {"ok": False, "record": record, "reason": "existing_member_must_renew"}
    if normalized_action == "join" and has_record:
        return {"ok": True, "record": record, "reason": "inactive_record_reactivation"}
    if normalized_action in ("renew", "upgrade") and not has_record:
        return {"ok": False, "record": None, "reason": "new_member_must_join"}
    return {"ok": True, "record": record, "reason": ""}


async def resolve_payment_action(user_id: int | str, payment: dict | None) -> tuple[str, str]:
    """Recover action for drafts created before New/Renew was persisted.

    Explicit action always wins. For legacy drafts, current ACTIVE means renew;
    no row or an inactive row means new-member/reactivation. Lookup failures stay
    fail-closed rather than guessing.
    """
    payment = payment or {}
    explicit = str(payment.get("action") or "").strip().lower()
    if explicit in ("join", "renew", "upgrade"):
        return explicit, "explicit"
    record = await get_member_record(user_id)
    if record and record.get("__lookup_error__"):
        return "", "member_lookup_unavailable"
    if is_current_member_record(record):
        return "renew", "legacy_active_record"
    return "join", "legacy_new_or_inactive_record"


def payment_retry_command(action: str | None) -> str:
    """Return the correct customer retry command without guessing unknown flows."""
    normalized = str(action or "").strip().lower().replace("-", "_").replace(" ", "_")
    return {
        "join": "/newmember",
        "new": "/newmember",
        "newmember": "/newmember",
        "new_member": "/newmember",
        "renew": "/renew",
        "upgrade": "/upgrade",
    }.get(normalized, "")


# ── 10 Day Promo Helpers ──────────────────────────────
async def get_cancel_count(str_uid: str) -> int:
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.post(SHEET_WEBHOOK, json={
                "action": "getCancelCount", "userId": str_uid,
            }, timeout=40)
        return resp.json().get("cancelCount", 0)
    except:
        return 0

async def check_promo10d_eligibility(str_uid: str) -> dict:
    """Returns {eligible, reason, active, carreq_count}"""
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.post(SHEET_WEBHOOK, json={"action":"getMembers","serverKey":SHEET_SERVER_KEY}, timeout=40)
        members = resp.json().get("members", [])
        for m in members:
            if str(m.get("userId","")) == str_uid:
                pkg    = str(m.get("package","")).upper()
                status = str(m.get("status","")).upper()
                if pkg == "PROMO10D":
                    if status == "ACTIVE":
                        return {"eligible": True, "active": True, "reason": ""}
                    if status in ("KICKED", "EXPIRED"):
                        return {"eligible": False, "active": False,
                                "reason": "10 Day Promo သုံးပြီး Order မတင်ခဲ့သောကြောင့် ထပ်မရနိုင်ပါ"}
    except Exception as e:
        logger.error(f"check_promo10d: {e}")

    # Cancel count check
    cancel_count = await get_cancel_count(str_uid)
    if cancel_count >= 2:
        return {"eligible": False, "active": False,
                "reason": "Cancel ၂ ကြိမ်နှင့်အထက် ရှိသောကြောင့် 10 Day Promo မရနိုင်ပါ"}

    return {"eligible": True, "active": False, "reason": ""}

async def activate_promo10d(context, user_id: int, username: str) -> bool:
    """Save PROMO10D member to sheet"""
    now        = datetime.now()
    start_date = now.strftime("%d/%m/%Y")
    expire_date= (now + timedelta(days=10)).strftime("%d/%m/%Y")
    password   = generate_password()
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.post(SHEET_WEBHOOK, json={
                "action":   "saveMember", "serverKey": SHEET_SERVER_KEY,
                "userId":   str(user_id),
                "username": username,
                "days":     10,
                "password": password,
                "package":  "PROMO10D",
            }, timeout=40, follow_redirects=True)
        return resp.json().get("status") == "ok"
    except Exception as e:
        logger.error(f"activate_promo10d: {e}")
        return False

def generate_password() -> str:
    letters = random.choices(string.ascii_uppercase, k=5)
    digits  = random.choices(string.digits, k=5)
    mixed   = [letters[0], digits[0], letters[1], digits[1], letters[2],
               digits[2], letters[3], digits[3], letters[4], digits[4]]
    return "KMT-" + "".join(mixed[:6]) + "-" + "".join(mixed[6:])

# ── Helpers ───────────────────────────────────────────
# ── Tracking Buttons ──────────────────────────────────
TRACKING_LABELS = {
    "A": [
        ("🔍 ကားကြည့်နေဆဲ",      "searching"),
        ("🔎 ကားစစ်ဆေးနေဆဲ",    "checking"),
        ("🚗 ကားရပြီ",            "found"),
        ("🏷️ Auction တင်ပြီ",    "bidding"),
        ("⏳ ရလဒ်စောင့်စားပါ",   "waiting"),
        ("🏆 Auction Win",        "win"),
        ("❌ Auction Loss",        "loss"),
    ],
    "R": [
        ("🔍 ကားရှာနေဆဲ",        "searching"),
        ("🚗 ကားရပြီ",            "found"),
        ("✅ ကားအဆင်ပြေပြီ",     "ok"),
    ],
}

TRACKING_NOTI = {
    "searching": "🔍 Broker သည် ကားရှာနေဆဲ ဖြစ်ပါသည်",
    "checking":  "🔎 Broker သည် ကားစစ်ဆေးနေဆဲ ဖြစ်ပါသည်",
    "found":     "🚗 ကားတွေ့ပြီ — အသေးစိတ် ဆက်လာမည်",
    "bidding":   "🏷️ Auction တင်ပြီ — ရလဒ် စောင့်ပါ",
    "waiting":   "⏳ Auction ရလဒ် စောင့်နေဆဲ ဖြစ်ပါသည်",
    "win":       "🏆 Auction Win! ကားရပြီ — Broker ဆက်သွယ်ပေးမည်",
    "loss":      "❌ Auction Loss — Broker မှ နောက်ထပ် ဆက်သွယ်ပေးမည်",
    "ok":        "✅ ကားအဆင်ပြေပြီ — Broker ဆက်သွယ်ပေးမည်",
}

def get_tracking_keyboard(svc_type: str, req_id: str) -> InlineKeyboardMarkup:
    t = "A" if svc_type == "auction" else "R"
    buttons = []
    row = []
    for label, key in TRACKING_LABELS[t]:
        row.append(InlineKeyboardButton(label, callback_data=f"track_{t}_{key}_{req_id}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)

def loc_display(loc_key: str) -> str:
    if loc_key == "Klang9": return LOC_KLANG9
    if loc_key in ("Border44","Best Border","44Gate","44gate"): return LOC_BORDER44
    return LOC_MAESOT

async def get_member_package(user_id: int) -> str | None:
    if user_id in ADMIN_IDS:
        return "WEB"
    if not SHEET_WEBHOOK:
        return None
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.post(
                SHEET_WEBHOOK,
                json={"action": "getMembers", "serverKey": SHEET_SERVER_KEY},
                timeout=40,
            )
        resp.raise_for_status()
        payload = resp.json()
        if str(payload.get("status") or "").strip().lower() == "error":
            logger.error(f"get_member_package backend error user={user_id}: {payload.get('message') or payload}")
            return None
        members = payload.get("members", [])

        for member in members:
            member_id = (
                member.get("userId")
                or member.get("userID")
                or member.get("UserID")
                or member.get("telegramId")
            )
            clean_member_id = str(member_id or "").replace(".0", "").strip()
            if clean_member_id != str(user_id):
                continue

            status = str(member.get("status", "")).upper().strip()
            if status != "ACTIVE":
                return None

            package = str(member.get("package", "CH") or "CH").upper().strip()
            if package in ("WEB", "WEB-PROMO"):
                return "WEB"
            if package in ("CH", "CH-PROMO"):
                return "CH"
            return package

        return None
    except Exception as e:
        logger.error(f"get_member_package: {e}")
        return None

def decode_vin_year(vin: str) -> int:
    """Decode the model-year digit from position 10 of a real 17-char VIN.

    Japanese auction chassis codes (e.g. "CM55-0090382") are NOT VINs — they
    are a prefix plus an arbitrary serial number, and happen to satisfy the
    old "len(vin) >= 10" check too. Running the VIN year table against their
    10th character produced a coincidental-looking but meaningless year
    (e.g. serial digit '3' at index 9 decoding to 2003), which
    choose_verified_year() then trusted as a real year with no review
    warning. Gate this on is_european_vin() so it only ever runs on an
    actual 17-character VIN.
    """
    try:
        if not is_european_vin(vin):
            return 0
        VIN_YEAR_MODERN = {
            'A':2010,'B':2011,'C':2012,'D':2013,'E':2014,'F':2015,'G':2016,
            'H':2017,'J':2018,'K':2019,'L':2020,'M':2021,'N':2022,'P':2023,
            'R':2024,'S':2025,'T':2026,
            '1':2001,'2':2002,'3':2003,'4':2004,'5':2005,'6':2006,'7':2007,
            '8':2008,'9':2009,
        }
        if len(vin) >= 10:
            char = vin[9].upper()
            return VIN_YEAR_MODERN.get(char, 0)
    except:
        pass
    return 0

def is_european_vin(chassis: str) -> bool:
    c = chassis.upper().replace("-","").replace(" ","")
    if len(c) == 17 and c[:1] in ("W","S","V","Z","X","T"):
        return True
    return False

def guess_model_from_chassis(chassis_input: str) -> str:
    cu = chassis_input.upper().strip()
    for prefix in sorted(CHASSIS_PREFIX_MAP.keys(), key=len, reverse=True):
        if cu.startswith(prefix):
            return CHASSIS_PREFIX_MAP[prefix]
    return "UNKNOWN"

# ── Model text normalization ────────────────────────────────
# Sheet1's Model column has years of free-typed/OCR'd text with the same car
# spelled a dozen ways ("X-TRAIL" / "NISSAN X-TRAIL" / "NISSIAN XTRAIL"), which
# makes any per-model reporting (price trends, supply patterns) unreliable.
# This cleans spelling/typos and drops the brand prefix (the chassis code
# already implies brand), WITHOUT collapsing genuinely different nameplates —
# Noah stays Noah, Voxy stays Voxy, Hijet/Pixis/Sambar stay separate, and
# Hybrid/PHV trim suffixes are preserved as entered. The one confirmed merge
# is HR-V -> Vezel (same car, JDM vs export name). See
# chassis_model_final_mapping.csv for the full per-chassis review this was
# built from.
_MODEL_BRAND_WORDS = {
    "TOYOTA", "HONDA", "NISSAN", "NISSIAN", "MAZDA", "SUZUKI", "DAIHATSU",
    "SUBARU", "MITSUBISHI", "LEXUS", "HINO", "ISUZU", "UD",
}
_MODEL_NOISE_WORDS = {
    "FREEZON", "FREEZONE", "KLANG9", "MAESOT", "44GATE", "WITE", "92000",
}
_MODEL_TYPO_FIX = {
    "NISSIAN": "NISSAN", "XTRAIL": "X-TRAIL", "WIAH": "WISH", "VIZEL": "VEZEL",
    "HONDAFIT": "FIT", "CX5": "CX-5", "JUAKE": "JUKE", "SABARU": "SUBARU",
    "FEILDER": "FIELDER", "VANNTEE": "VANETTE", "VANNETTE": "VANETTE",
    "VANETTEE": "VANETTE", "OUTLANDAR": "OUTLANDER", "MERA": "MIRA",
    "CRV": "CR-V", "SUCCEDD": "SUCCEED", "PARADO": "PRADO", "VIZEL": "VEZEL",
}
_MODEL_KEEP_UPPER = {
    "CR-V", "CR-Z", "X-TRAIL", "HR-V", "LS460", "CT200H", "LX470", "UD",
    "CX-5", "CX-3", "CX-8", "RAV4", "C-HR", "NV200", "NV350", "LS", "AD",
    "RX", "NX", "GX", "LX", "IS", "ES", "GS", "UX", "LC",
}

def normalize_model_name(raw_model: str) -> str:
    """Clean a Model text value for storage: fix typos, drop brand prefix,
    merge confirmed synonyms (HR-V -> Vezel). Returns "" for empty/UNKNOWN
    input so callers can fall back to guess_model_from_chassis()."""
    m = str(raw_model or "").strip().upper()
    if not m or m in {"UNKNOWN", "N/A", "-", "NONE"}:
        return ""
    for typo, fix in _MODEL_TYPO_FIX.items():
        m = m.replace(typo, fix)
    tokens = [t for t in m.split() if t]
    tokens = [t for t in tokens if t not in _MODEL_BRAND_WORDS and t not in _MODEL_NOISE_WORDS]
    if not tokens:
        return ""
    if tokens == ["HR-V"] or " ".join(tokens) in ("HR-V", "HR-V (VEZEL)", "HR-V VEZEL"):
        tokens = ["VEZEL"]
    out = []
    for t in tokens:
        out.append(t if t in _MODEL_KEEP_UPPER else t.capitalize())
    return " ".join(out)

async def guess_model_gemini(chassis_input: str) -> str:
    if not GEMINI_API_KEY:
        return "UNKNOWN"
    try:
        if is_european_vin(chassis_input):
            vin_yr = decode_vin_year(chassis_input)
            yr_hint = f" Year hint from VIN: {vin_yr}." if vin_yr else ""
            prompt = f"This is a European VIN: {chassis_input}.{yr_hint} What car brand and model is this? Reply ONLY the model name UPPERCASE (e.g. NEW BEETLE, AUDI A4, BMW 3 SERIES). If unknown reply UNKNOWN."
        else:
            prefix  = chassis_input.split("-")[0] if "-" in chassis_input else chassis_input[:6]
            prompt  = f"What Japanese car model has chassis prefix '{prefix}'? Reply ONLY the model name UPPERCASE. If unknown reply UNKNOWN."
        url     = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents":[{"parts":[{"text":prompt}]}]}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=15)
        data = resp.json()
        if "candidates" in data:
            m = data["candidates"][0]["content"]["parts"][0]["text"].strip().upper().split("\n")[0].strip()
            return m if m and m != "UNKNOWN" else "UNKNOWN"
    except Exception as e:
        logger.error(f"Gemini model: {e}")
    return "UNKNOWN"

def normalize_chassis_key(value: str) -> str:
    """Compare chassis values independent of spaces, hyphens, or dash variants."""
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def canonicalize_chassis(value: str) -> str:
    """Format a known Japanese chassis prefix without inventing unknown digits."""
    raw = str(value or "").upper().strip().replace("—", "-").replace("–", "-")
    compact = normalize_chassis_key(raw)
    for prefix in sorted(CHASSIS_PREFIX_MAP.keys(), key=len, reverse=True):
        if compact.startswith(prefix):
            serial = compact[len(prefix):]
            if serial.isdigit() and 4 <= len(serial) <= 8:
                return f"{prefix}-{serial}"
    return raw


def chassis_candidate_values(value: str):
    """Return the OCR value plus narrowly scoped prefix-confusion candidates.

    Candidates are accepted only when an exact persistent Sheet row is found;
    the bot never changes a chassis solely because it is visually similar.
    """
    canonical = canonicalize_chassis(value)
    candidates = [canonical] if canonical else []
    if "-" in canonical:
        prefix, serial = canonical.split("-", 1)
        confusion_map = {
            "GG7": ("GP1", "GP7"),
            "GP1": ("GG7",),
        }
        for alternative in confusion_map.get(prefix, ()):
            candidates.append(f"{alternative}-{serial}")
    return list(dict.fromkeys(candidates))


def find_by_chassis(chassis_input: str):
    target = normalize_chassis_key(chassis_input)
    if not target:
        return None
    for car in CARS:
        if normalize_chassis_key(car.get("chassis", "")) == target:
            return car
    return None


def _gviz_cell(row, index: int) -> str:
    if index < 0 or index >= len(row):
        return ""
    cell = row[index] or {}
    return str(cell.get("v", "") if isinstance(cell, dict) else cell).strip()


def find_sheet_car_in_gviz_rows(rows, chassis_input: str):
    """Find the exact auction-list row in Sheet1 without writing anything."""
    target = normalize_chassis_key(chassis_input)
    if not target:
        return None
    for row_obj in rows or []:
        cells = row_obj.get("c", []) if isinstance(row_obj, dict) else []
        if normalize_chassis_key(_gviz_cell(cells, 1)) != target:
            continue
        year_raw = _gviz_cell(cells, 4)
        price_raw = _gviz_cell(cells, 5).replace(",", "")
        try:
            price = float(price_raw) if price_raw else 0
        except (TypeError, ValueError):
            price = 0
        return {
            "date": _gviz_cell(cells, 0),
            "chassis": _gviz_cell(cells, 1),
            "model": _gviz_cell(cells, 2) or "UNKNOWN",
            "color": _gviz_cell(cells, 3) or "-",
            "year": normalize_year(year_raw),
            "price": price,
            "location": _gviz_cell(cells, 6),
            "loc": _gviz_cell(cells, 6) or "MaeSot",
            "added_by": _gviz_cell(cells, 7),
            "image_url": _gviz_cell(cells, 8),
            "source": "sheet_exact",
        }
    return None


async def lookup_sheet_car_by_chassis(chassis_input: str):
    """Read Sheet1 through the existing public read path; never mutates production."""
    sheet_id = os.environ.get("SHEET_ID", "").strip()
    if not sheet_id or not chassis_input:
        return None
    try:
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:json&sheet=Sheet1"
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(url, timeout=8)
        raw = resp.text
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start < 0 or end <= start:
            return None
        payload = json.loads(raw[start:end])
        return find_sheet_car_in_gviz_rows(payload.get("table", {}).get("rows", []), chassis_input)
    except Exception as e:
        logger.error(f"sheet exact car lookup: {e}")
        return None


def find_sheet_car_by_candidates_in_rows(rows, chassis_input: str):
    """Resolve a narrow OCR prefix ambiguity against one Sheet1 snapshot."""
    values = chassis_candidate_values(chassis_input)
    for index, candidate in enumerate(values):
        row = find_sheet_car_in_gviz_rows(rows, candidate)
        if row:
            return row, ("sheet_exact" if index == 0 else "sheet_candidate")
    return None, "none"


async def fetch_sheet1_gviz_rows():
    """Read the current Sheet1 rows once for duplicate-safe admin operations."""
    sheet_id = os.environ.get("SHEET_ID", "").strip()
    if not sheet_id:
        return []
    try:
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:json&sheet=Sheet1"
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(url, timeout=12)
        raw = resp.text
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start < 0 or end <= start:
            return []
        payload = json.loads(raw[start:end])
        return payload.get("table", {}).get("rows", [])
    except Exception as e:
        logger.error(f"sheet1 rows lookup: {e}")
        return []


def stage_auction_list_rows(new_cars, import_loc, existing_chassis=()):
    """Prepare OCR list rows for explicit Admin confirmation; no write occurs here."""
    seen = {normalize_chassis_key(value) for value in existing_chassis if value}
    staged = []
    duplicates = []
    invalid = []
    for raw_car in new_cars or []:
        if not isinstance(raw_car, dict):
            continue
        chassis = canonicalize_chassis(raw_car.get("chassis", ""))
        key = normalize_chassis_key(chassis)
        if not key or not re.fullmatch(r"[A-Z0-9]{3,25}(?:-[A-Z0-9]{4,8})?", chassis):
            invalid.append(str(raw_car.get("chassis", "")))
            continue
        if key in seen:
            duplicates.append(chassis)
            continue
        seen.add(key)
        model = normalize_model_name(raw_car.get("model", ""))
        color = str(raw_car.get("color", "")).strip().upper()
        year = normalize_year(raw_car.get("year", 0))
        missing = []
        if not model:
            model = guess_model_from_chassis(chassis)
            if model == "UNKNOWN":
                missing.append("Model")
        if not color or color in {"UNKNOWN", "N/A", "-"}:
            color = "-"
            missing.append("Color")
        if not year:
            missing.append("Year")
        staged.append({
            "date": datetime.now().strftime("%d/%m/%Y"),
            "chassis": chassis,
            "model": model,
            "color": color,
            "year": year,
            "price": 0,
            "location": import_loc,
            "added_by": "Admin Auction List OCR",
            "image_url": "",
            "missing": missing,
        })
    return staged, duplicates, invalid


async def persist_staged_auction_rows(staged_rows):
    """Write staged auction-list rows to Sheet1 via the webhook.

    Re-reads Sheet1 immediately before writing to close the duplicate race,
    then posts each row. Returns (saved, failed, already_present).
    """
    if not SHEET_WEBHOOK:
        return [], list(staged_rows), []

    fresh_rows = await fetch_sheet1_gviz_rows()
    existing_keys = {
        normalize_chassis_key(_gviz_cell(row_obj.get("c", []), 1))
        for row_obj in fresh_rows
        if isinstance(row_obj, dict)
    }
    to_write = []
    already_present = []
    for row in staged_rows:
        key = normalize_chassis_key(row.get("chassis", ""))
        if key in existing_keys:
            already_present.append(row.get("chassis", ""))
        elif key:
            to_write.append(row)
            existing_keys.add(key)

    saved = []
    failed = []
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            for row in to_write:
                payload = {k: row.get(k, "") for k in (
                    "date", "chassis", "model", "color", "year", "price",
                    "location", "added_by", "image_url")}
                try:
                    resp = await client.post(SHEET_WEBHOOK, json=payload, timeout=40)
                    resp.raise_for_status()
                    result = resp.json()
                    if result.get("status") != "ok":
                        raise RuntimeError(str(result))
                    saved.append(row)
                except Exception as exc:
                    logger.error(f"auction list persist {row.get('chassis')}: {exc}")
                    failed.append(row)
    except Exception as exc:
        logger.error(f"auction list persist client: {exc}")
        failed.extend([row for row in to_write if row not in saved and row not in failed])

    for row in saved:
        CARS.append({
            "chassis": row["chassis"], "model": row["model"],
            "color": row["color"], "year": row["year"], "loc": row["location"],
        })
    return saved, failed, already_present


async def lookup_sheet_car_by_candidates(chassis_input: str):
    """Use a prefix-confusion candidate only when Sheet1 proves the exact row."""
    sheet_id = os.environ.get("SHEET_ID", "").strip()
    if not sheet_id or not chassis_input:
        return None, "none"
    try:
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:json&sheet=Sheet1"
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(url, timeout=8)
        raw = resp.text
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start < 0 or end <= start:
            return None, "none"
        payload = json.loads(raw[start:end])
        return find_sheet_car_by_candidates_in_rows(payload.get("table", {}).get("rows", []), chassis_input)
    except Exception as e:
        # Same diagnostic as sheet loc lookup: a JSON-parse failure here
        # usually means Google returned something other than the gviz
        # payload (e.g. a sign-in/permission page), not a code bug — log a
        # slice of the actual response instead of guessing blind.
        raw_prefix = locals().get('raw', '')[:200]
        logger.error(f"sheet candidate car lookup: {e} raw_prefix={raw_prefix!r}")
        return None, "none"

def normalize_model_label(value: str) -> str:
    """Normalize model labels for comparing verified and vision results."""
    text = re.sub(r"[^A-Z0-9 ]", "", str(value or "").upper()).strip()
    text = re.sub(r"^(HONDA|TOYOTA|NISSAN|MAZDA|SUZUKI|MITSUBISHI|SUBARU|DAIHATSU|HINO|ISUZU|UD)[ ]+", "", text)
    return re.sub(r"[^A-Z0-9]", "", text)


def choose_verified_model(chassis: str, database_model: str = "", vision_model: str = "", caption_model: str = "") -> tuple[str, str, bool]:
    """Choose a model without allowing vision-only output to silently win."""
    def usable(value: str) -> bool:
        return bool(str(value or "").strip()) and str(value).strip().upper() not in {"UNKNOWN", "N/A", "-"}

    known_model = guess_model_from_chassis(chassis or "")
    if usable(caption_model):
        return str(caption_model).strip(), "caption", False
    if usable(database_model):
        conflict = usable(known_model) and normalize_model_label(database_model) != normalize_model_label(known_model)
        return str(database_model).strip(), "database_conflict" if conflict else "database", conflict
    if usable(known_model):
        return str(known_model).strip(), "chassis_prefix", False
    if usable(vision_model):
        return str(vision_model).strip(), "vision_review", True
    return "UNKNOWN", "manual", True


def normalize_model_search(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def find_by_model(model_input: str):
    query = normalize_model_search(model_input)

    if not query:
        return []

    return [
        car for car in CARS
        if query in normalize_model_search(car.get("model", ""))
    ]
def extract_chassis_from_text(text: str):
    text = str(text or "").upper().strip()
    vin_matches = re.findall(r'[A-HJ-NPR-Z0-9]{17}', text)
    for v in vin_matches:
        if v[0] in ("W","S","V","Z","X","T"):
            return v
    for pattern in [
        r'[A-Z]{1,5}\d{1,4}[A-Z]{0,2}\d{0,2}[-\s]\d{4,7}',
        r'[A-Z]{2,6}\d{2,4}[-\s]\d{4,7}',
        r'[A-Z0-9]{4,20}[-\s]\d{4,7}',
    ]:
        matches = re.findall(pattern, text)
        if matches:
            return max(matches, key=len).replace(" ", "-")

    # Handwritten windshield text is often returned without a hyphen or with
    # spaces between prefix and serial. Use only known chassis prefixes here;
    # this avoids turning arbitrary dates/amounts into a chassis number.
    compact = re.sub(r"[^A-Z0-9]", "", text)
    for prefix in sorted(CHASSIS_PREFIX_MAP.keys(), key=len, reverse=True):
        match = re.search(re.escape(prefix) + r"(\d{4,8})", compact)
        if match:
            return f"{prefix}-{match.group(1)}"
    return None

def get_price_history(chassis: str):
    target = normalize_chassis_key(chassis)
    if not target:
        return []
    return [p for p in PRICE_HISTORY if normalize_chassis_key(p.get("chassis", "")) == target]

def normalize_year(value) -> int:
    """Return only a plausible production year; reject OCR noise and malformed values."""
    try:
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        match = re.search(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", str(value or ""))
        year = int(match.group()) if match else 0
        return year if 1980 <= year <= datetime.now().year + 1 else 0
    except (TypeError, ValueError):
        return 0


def choose_verified_year(caption_year=0, database_year=0, vin_year=0, vision_year=0) -> tuple[int, str]:
    """Choose a trusted year source. Caption/database/VIN win outright.

    A vision (windshield OCR) year is used only as a last-resort fallback,
    same pattern as choose_verified_model()'s vision_review path — it is
    returned but the caller must still flag it "needs review" so an Admin
    confirms it before Save.
    """
    for value, source in (
        (caption_year, "caption"),
        (database_year, "database"),
        (vin_year, "vin"),
    ):
        year = normalize_year(value)
        if year:
            return year, source
    year = normalize_year(vision_year)
    if year:
        return year, "vision_review"
    return 0, "manual"


def ys(year) -> str:
    return str(normalize_year(year)) if normalize_year(year) else "—"


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
    txt += f"\n🌐 [Web မှာကြည့်](https://kyawmintun08.github.io/Japan-Auction-Car-Checker/)"
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
    model = normalize_model_name(model) or guess_model_from_chassis(chassis)
    entry = {"chassis":chassis,"model":model,"color":color,"year":year,
             "price":price,"date":now,"location":location,
             "added_by":user_name,"image_url":image_url,"serverKey":SHEET_SERVER_KEY}
    PRICE_HISTORY.append(entry)
    if SHEET_WEBHOOK:
        try:
            async with httpx.AsyncClient() as client:
                await client.post(SHEET_WEBHOOK, json=entry, timeout=40, follow_redirects=True)
        except Exception as e:
            logger.error(f"save_price: {type(e).__name__} {e}")
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
        f"🌐 [Japan Auction Car Checker](https://kyawmintun08.github.io/Japan-Auction-Car-Checker/)"
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


async def notify_admins_with_slips(context, slips):
    """Send all submitted slip images after the consolidated review message."""
    import io
    for admin_id in ADMIN_IDS:
        for index, slip in enumerate(slips, 1):
            file_bytes = slip.get("file_bytes")
            if not file_bytes:
                continue
            try:
                info = slip.get("slip_info", {})
                amount = int(slip.get("amount_num", 0) or 0)
                txn = info.get("TRANSACTION_NO", info.get("REFERENCE", "UNKNOWN"))
                await context.bot.send_photo(
                    chat_id=admin_id,
                    photo=io.BytesIO(file_bytes),
                    caption=f"📎 Slip {index} — {amount:,} ks — Txn: {txn}",
                )
            except Exception as e:
                logger.error(f"Admin slip image notify {admin_id}/{index}: {e}")

async def kick_with_retry(context, user_id: int, max_retries: int = 3) -> bool:
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
    if not GEMINI_API_KEY:
        return {}
    try:
        import base64
        img_b64 = base64.b64encode(file_bytes).decode()
        url     = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents":[{"parts":[
            {"text":"""Identify this Myanmar mobile payment slip and extract fields.

HOW TO IDENTIFY:
- Wave Money slip = YELLOW background, "KS" logo with lightning bolt
    * Shows "Transaction ID" + "Date & Time" + "Total" (top amount)
    * "Receive Money" view: has "Sender" field
    * "Send Money" view: has "Receiver" field

- KPay (KBZPay) slip = BLUE background, "KBZ BANK" red logo at top + "KBZPay" blue logo at bottom
    * Shows "Transaction Time" + "Transaction No." + "Transfer To" + "Amount" (top large number)
    * "Transfer To" = the person who RECEIVED the money (e.g. admin name)
    * Sender name is usually NOT shown on this slip type; return UNKNOWN

- CB Bank slip = GREEN background, "CB Bank" or "CB Pay" logo
    * This E-Receipt has two account sections in order: first "Current Account - Personal" and then "Digital Account"
    * For each section, carefully read the account type, masked/full account number, and account name exactly as shown
    * The first section is the FROM_ACCOUNT section and the second section is the TO_ACCOUNT section; do not merge their numbers or names
    * The lower receipt details include amount, fee, transaction date, transaction date/time, reference number, and purpose
    * Do not confuse account numbers with the reference number; preserve hyphens, masked x characters, leading zeroes, and names exactly

Extract these fields:
TYPE: Return exactly one of: Wave, KPay, CB, Other. Use Wave for Wave Money, KPay for KBZPay/KBZ Bank, and CB for CB Bank/CB Pay.
TRANSACTION_NO:
  - Wave: number next to "Transaction ID" (e.g. 894983741)
  - KPay: full number next to "Transaction No." (e.g. 01004089020139330692) — ALL digits, including leading zeroes
  - CB: number next to "Transaction No." or "Reference No."
AMOUNT: Read ONLY the actual payment amount shown inside the original slip. For Wave, use the number beside the label "Total"; do NOT use any Telegram caption, expected amount, message text, transaction ID, date, or other number. For KPay/CB, use the number beside the payment label "Amount". Inspect every digit one by one, including the first digit, and preserve leading digits exactly. Return a positive integer only, with no commas, no Ks, and no minus/plus (e.g. 55000). If the amount digits are not clearly readable, return UNKNOWN instead of guessing.
DATE: For Wave use "Date & Time"; for KPay use "Transaction Time"; for CB use "Transaction Date". Return dd/mm/yyyy only.
TIME: For Wave/KPay, read the time from the corresponding date/time field and convert PM/AM to 24-hour HH:MM. For CB, return the visible transaction time in HH:MM, or UNKNOWN if no time is shown.
TRANSFER_TO: For KPay, read the name next to "Transfer To". For Wave Send view or CB, read the name next to "Receiver". This is the person or merchant who received the money. For Wave Receive view, return UNKNOWN for TRANSFER_TO.
SENDER: For Wave Receive view, read the name next to "Sender". For CB, read a visible sender/originator field if present. For KPay and Wave Send view, return UNKNOWN.
ACCOUNT_NUMBER: CB only — legacy alias for the primary account number; use the FROM_ACCOUNT_NUMBER value when available. UNKNOWN for other types.
ACCOUNT_ID: CB only — read the value next to an explicit "ID" or "Account ID" label; do not substitute Transaction No. or Reference No. UNKNOWN if no Account ID label is visible. UNKNOWN for other types.
ACCOUNT_NAME: CB only — legacy alias for the primary account name; use the FROM_ACCOUNT_NAME value when available. UNKNOWN for other types.
FROM_ACCOUNT_TYPE: CB only — the first account section type, such as "Current Account - Personal".
FROM_ACCOUNT_NUMBER: CB only — the account number shown in the first account section, preserving hyphens, masked x characters, and leading zeroes.
FROM_ACCOUNT_NAME: CB only — the name shown in the first account section, preserving spelling and spacing.
TO_ACCOUNT_TYPE: CB only — the second account section type, such as "Digital Account".
TO_ACCOUNT_NUMBER: CB only — the account number shown in the second account section, preserving hyphens, masked x characters, and leading zeroes.
TO_ACCOUNT_NAME: CB only — the name shown in the second account section, preserving spelling and spacing.
FEE: CB only — the value next to the fee/charges label; return a numeric value without currency text, or UNKNOWN.
PURPOSE: CB only — the value next to the purpose/description label, such as "Rent"; UNKNOWN if not shown.

TRANSACTION_NO is most critical — read every digit carefully.
AMOUNT is also critical — do not infer or calculate it from any other field. Ignore text outside the original payment-slip image, including Telegram overlays or captions.

Return EXACTLY in this format with no extra text and use the exact field names above. TYPE must be exactly Wave, KPay, CB, or Other. Write UNKNOWN if a field is not shown or if its digits are unclear."""},
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

# ── Payment QR Helpers ────────────────────────────────
PAYMENT_METHOD_INFO = {
    "kpay": {
        "label":  "🔵 KPay",
        "name":   "KPay",
        "number": "09973625985",
        "owner":  "Kyaw Min Tun",
    },
    "wave": {
        "label":  "🟣 Wave",
        "name":   "Wave",
        "number": "09799959537",
        "owner":  "Kyaw Min Tun",
    },
    "cb": {
        "label":  "🟢 CB Bank",
        "name":   "CB Bank MMQR",
        "number": "(QR Scan)",
        "owner":  "Kyaw Min Tun (Merchant)",
    },
}

async def get_payment_qr(method: str) -> str:
    """Sheet ကနေ file_id ဆွဲ (10 min cache)"""
    method = method.lower().strip()
    cached = payment_qr_cache.get(method)
    if cached:
        age = (datetime.now() - cached["ts"]).total_seconds()
        if age < 600:  # 10 min
            return cached["file_id"]
    if not SHEET_WEBHOOK:
        return ""
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.post(SHEET_WEBHOOK, json={
                "action": "getPaymentQR",
                "method": method,
            }, timeout=40)
        data = resp.json()
        if data.get("ok") and data.get("fileId"):
            file_id = data["fileId"]
            payment_qr_cache[method] = {"file_id": file_id, "ts": datetime.now()}
            return file_id
    except Exception as e:
        logger.error(f"get_payment_qr {method}: {e}")
    return ""

async def set_payment_qr(method: str, file_id: str, admin_name: str) -> bool:
    """Sheet မှာ file_id သိမ်း + cache ဖျက်"""
    method = method.lower().strip()
    if not SHEET_WEBHOOK:
        return False
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.post(SHEET_WEBHOOK, json={
                "action":    "setPaymentQR", "serverKey": SHEET_SERVER_KEY,
                "method":    method,
                "fileId":    file_id,
                "adminName": admin_name,
            }, timeout=40)
        result = resp.json()
        if result.get("ok"):
            payment_qr_cache.pop(method, None)  # cache invalidate
            return True
    except Exception as e:
        logger.error(f"set_payment_qr {method}: {e}")
    return False

# ── Save Member with Password ─────────────────────────
async def save_member_to_sheet(user_id: str, username: str, days: int,
                                password: str = "", package: str = "") -> dict:
    if not SHEET_WEBHOOK:
        return {"status": "error", "message": "sheet_webhook_missing"}
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(SHEET_WEBHOOK, json={
                "action":   "saveMember", "serverKey": SHEET_SERVER_KEY,
                "userId":   str(user_id),
                "username": username,
                "days":     days,
                "password": password,
                "package":  package or "CH",
            }, timeout=40, follow_redirects=True)
        payload = resp.json()
        if not isinstance(payload, dict):
            return {"status": "error", "message": "invalid_sheet_response"}
        return payload
    except Exception as e:
        logger.error(f"saveMember: {e}")
        return {"status": "error", "message": "sheet_request_failed"}


async def enrich_member_save_result(
    user_id: str,
    saved: dict,
    package: str,
    strict: bool = False,
) -> dict:
    """Fill and optionally verify canonical member fields without changing Members columns."""
    result = dict(saved or {})
    result.setdefault("status", "error")
    if result.get("status") != "ok":
        return result
    if not SHEET_WEBHOOK:
        if strict:
            return {"status": "error", "message": "canonical_member_lookup_unavailable"}
        return result

    # Strict approval paths always re-read the saved member so the Bot uses the
    # actual Members row, including StartDate, ExpireDate, package, and password.
    needs_member = strict or not result.get("expireDate") or not result.get("package")
    if needs_member:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    SHEET_WEBHOOK,
                    json={"action": "getMembers", "serverKey": SHEET_SERVER_KEY},
                    timeout=40,
                    follow_redirects=True,
                )
            payload = resp.json()
            members = payload.get("members", []) if isinstance(payload, dict) else []
            target = next(
                (m for m in members if str(m.get("userId", "")).strip() == str(user_id).strip()),
                None,
            )
            if target:
                result.setdefault("startDate", target.get("startDate", ""))
                result["expireDate"] = str(target.get("expireDate") or result.get("expireDate") or "")
                result["package"] = target.get("package", result.get("package", package))
                result["canonicalMemberChecked"] = True
            elif strict:
                return {
                    "status": "error",
                    "message": "member_not_found_after_save",
                    "canonicalMemberChecked": False,
                }
        except Exception as e:
            logger.warning("canonical member lookup after save failed: %s", e)
            if strict:
                return {
                    "status": "error",
                    "message": "canonical_member_lookup_failed",
                    "canonicalMemberChecked": False,
                }

    normalized_package = str(result.get("package") or package or "").upper().replace("-", "")
    if normalized_package in ("WEB", "WEBPROMO") and not result.get("password"):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    SHEET_WEBHOOK,
                    json={"action": "getPassword", "userId": str(user_id), "serverKey": SHEET_SERVER_KEY},
                    timeout=40,
                    follow_redirects=True,
                )
            password_result = resp.json()
            if password_result.get("status") == "ok":
                result["password"] = str(password_result.get("password") or "")
        except Exception as e:
            logger.warning("canonical password lookup after save failed: %s", e)
    if strict:
        integrity = validate_member_record(result, package)
        if not integrity.get("ok"):
            result["status"] = "error"
            result["message"] = integrity.get("reason", "member_integrity_check_failed")
    return result


async def log_finance_entry(payment: dict) -> bool:
    """Append one auditable Finance row with bounded retries; never change Members columns here."""
    if not SHEET_WEBHOOK:
        return False
    payload = dict(payment or {})
    source = str(payload.get("source") or "").strip().upper()
    if source == "PAYMENT_SLIP":
        if not (str(payload.get("paymentId") or "").strip() or str(payload.get("transactionNo") or "").strip()):
            logger.error("Refusing payment-slip Finance log without transaction number")
            return False
        if normalize_amount(payload.get("amount")) is None:
            logger.error("Refusing payment-slip Finance log without a numeric amount")
            return False

    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                response = await client.post(
                    SHEET_WEBHOOK,
                    json={
                        "action": "logPayment",
                        "payment": payload,
                        "serverKey": SHEET_SERVER_KEY,
                    },
                    timeout=40,
                )
            result = response.json()
            if response.status_code < 400 and (
                result.get("status") == "ok" or result.get("duplicate") is True
            ):
                return True
            logger.warning(
                "log_finance_entry logical failure attempt=%s/3 status=%s response=%s",
                attempt, response.status_code, str(result)[:300],
            )
        except Exception as exc:
            logger.warning("log_finance_entry failed attempt=%s/3: %s", attempt, exc)
        if attempt < 3:
            await asyncio.sleep(0.8 * attempt)
    return False


async def approve_payment_transaction(payment: dict) -> dict:
    """Ask Apps Script to atomically save the member and approve one Finance row."""
    if not SHEET_WEBHOOK:
        return {"status": "error", "message": "sheet_webhook_not_configured"}
    if not SHEET_SERVER_KEY:
        return {"status": "error", "message": "server_key_not_configured"}
    payload = dict(payment or {})
    last_result = None
    last_error = ""
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                response = await client.post(
                    SHEET_WEBHOOK,
                    json={
                        "action": "approvePaymentTransaction",
                        "payment": payload,
                        "serverKey": SHEET_SERVER_KEY,
                    },
                    # Apps Script waits up to 30 seconds for its ScriptLock.
                    # Leave enough time for the locked operation to finish.
                    timeout=45,
                )
            result = response.json()
            if isinstance(result, dict):
                last_result = result
                if response.status_code < 400:
                    if result.get("status") == "ok" or result.get("message") in {
                        "payment_amount_mismatch",
                        "transaction_already_used",
                        "transaction_in_progress",
                        "transaction_review_required",
                    }:
                        return result
                    if result.get("message") in {"unauthorized", "server_key_not_configured"}:
                        return result
            logger.warning(
                "approvePaymentTransaction failed attempt=%s/3 status=%s response=%s",
                attempt, response.status_code, str(result)[:300],
            )
            last_error = f"HTTP {response.status_code}"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {str(exc)[:240]}"
            logger.warning("approvePaymentTransaction request failed attempt=%s/3: %s", attempt, exc)
        if attempt < 3:
            await asyncio.sleep(1.0 * attempt)
    if isinstance(last_result, dict) and last_result.get("message"):
        return last_result
    return {
        "status": "error",
        "message": "transaction_request_failed",
        "detail": last_error,
    }


async def approve_manual_member_transaction(payment: dict) -> dict:
    """Atomically approve a no-payment manual member action and its Finance audit row."""
    if not SHEET_WEBHOOK:
        return {"status": "error", "message": "sheet_webhook_not_configured"}
    if not SHEET_SERVER_KEY:
        return {"status": "error", "message": "server_key_not_configured"}
    payload = dict(payment or {})
    last_result = None
    last_error = ""
    for attempt in range(1, 4):
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                response = await client.post(
                    SHEET_WEBHOOK,
                    json={
                        "action": "approveManualMember",
                        "payment": payload,
                        "serverKey": SHEET_SERVER_KEY,
                    },
                    timeout=45,
                )
            result = response.json()
            if isinstance(result, dict):
                last_result = result
                if response.status_code < 400:
                    if result.get("status") == "ok" or result.get("message") in {
                        "transaction_already_used",
                        "transaction_in_progress",
                        "transaction_review_required",
                        "member_finance_review_required",
                    }:
                        return result
                    if result.get("message") in {"unauthorized", "server_key_not_configured"}:
                        return result
            logger.warning(
                "approveManualMember failed attempt=%s/3 status=%s response=%s",
                attempt, response.status_code, str(result)[:300],
            )
            last_error = f"HTTP {response.status_code}"
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {str(exc)[:240]}"
            logger.warning("approveManualMember request failed attempt=%s/3: %s", attempt, exc)
        if attempt < 3:
            await asyncio.sleep(1.0 * attempt)
    if isinstance(last_result, dict) and last_result.get("message"):
        return last_result
    return {
        "status": "error",
        "message": "manual_transaction_request_failed",
        "detail": last_error,
    }


async def save_payment_draft(payment: dict) -> dict:
    """Persist a reviewable payment draft before notifying admins."""
    if not SHEET_WEBHOOK or not SHEET_SERVER_KEY:
        return {"status": "error", "message": "draft_storage_not_configured"}
    payload = dict(payment or {})
    safe_slips = []
    for item in payload.get("slips", []) or []:
        info = dict(item.get("slip_info", {}) or {})
        safe_slips.append({
            "slip_info": {
                "AMOUNT": str(info.get("AMOUNT") or ""),
                "DATE": str(info.get("DATE") or ""),
                "TIME": str(info.get("TIME") or ""),
                "TYPE": str(info.get("TYPE") or ""),
                "TRANSACTION_NO": str(info.get("TRANSACTION_NO") or info.get("REFERENCE") or ""),
                "REFERENCE": str(info.get("REFERENCE") or ""),
                "SENDER": str(info.get("SENDER") or ""),
                "TRANSFER_TO": str(info.get("TRANSFER_TO") or ""),
                "RECEIVER": str(info.get("RECEIVER") or ""),
            },
            "amount_num": int(item.get("amount_num", 0) or 0),
            "txn_key": str(item.get("txn_key") or ""),
        })
    draft = {
        "userId": str(payload.get("userId") or ""),
        "username": str(payload.get("username") or ""),
        "name": str(payload.get("name") or "Unknown"),
        "action": str(payload.get("action") or ""),
        "package": str(payload.get("package") or "CH"),
        "months": int(payload.get("months", 1) or 1),
        "amount": int(payload.get("amount", 0) or 0),
        "method": str(payload.get("method") or ""),
        "total_paid": int(payload.get("total_paid", 0) or 0),
        "slips": safe_slips,
        "slip_info": dict(payload.get("slip_info", {}) or {}),
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.post(
                SHEET_WEBHOOK,
                json={"action": "savePaymentDraft", "draft": draft, "serverKey": SHEET_SERVER_KEY},
                timeout=40,
            )
        result = response.json()
        return result if isinstance(result, dict) else {"status": "error", "message": "invalid_draft_response"}
    except Exception as exc:
        logger.warning("savePaymentDraft failed user=%s: %s", draft.get("userId"), exc)
        return {"status": "error", "message": "draft_save_failed"}


async def get_payment_draft(user_id: int | str) -> dict:
    """Restore a pending payment draft after a bot restart or worker recycle."""
    if not SHEET_WEBHOOK or not SHEET_SERVER_KEY:
        return {}
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.post(
                SHEET_WEBHOOK,
                json={
                    "action": "getPaymentDraft",
                    "draft": {"userId": str(user_id)},
                    "serverKey": SHEET_SERVER_KEY,
                },
                timeout=40,
            )
        result = response.json()
        if isinstance(result, dict) and result.get("status") == "ok" and result.get("found"):
            draft = result.get("draft") or {}
            draft["waiting_slip"] = True
            return draft
    except Exception as exc:
        logger.warning("getPaymentDraft failed user=%s: %s", user_id, exc)
    return {}


async def clear_payment_draft(user_id: int | str, transaction_no: str = "") -> bool:
    """Mark a successfully handled draft as cleared without deleting its audit row."""
    if not SHEET_WEBHOOK or not SHEET_SERVER_KEY:
        return False
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.post(
                SHEET_WEBHOOK,
                json={
                    "action": "clearPaymentDraft",
                    "draft": {"userId": str(user_id), "transactionNo": str(transaction_no or "")},
                    "serverKey": SHEET_SERVER_KEY,
                },
                timeout=40,
            )
        result = response.json()
        return isinstance(result, dict) and result.get("status") == "ok"
    except Exception as exc:
        logger.warning("clearPaymentDraft failed user=%s: %s", user_id, exc)
        return False


async def ensure_payment_session(user_id: int | str) -> dict:
    """Use memory first, then restore the durable draft if memory was lost."""
    member_id = int(user_id)
    existing = pending_payment.get(member_id, {}) or {}
    if existing:
        return existing
    restored = await get_payment_draft(member_id)
    if restored:
        pending_payment[member_id] = restored
        return restored
    return {}


async def inspect_payment_transaction(payment: dict) -> dict:
    """Read one protected transaction so lost HTTP responses can be reconciled safely."""
    if not SHEET_WEBHOOK:
        return {"status": "error", "message": "sheet_webhook_not_configured"}
    if not SHEET_SERVER_KEY:
        return {"status": "error", "message": "server_key_not_configured"}
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.post(
                SHEET_WEBHOOK,
                json={
                    "action": "inspectPaymentTransaction",
                    "payment": {
                        "userId": str(payment.get("userId") or ""),
                        "transactionNo": str(payment.get("transactionNo") or ""),
                        "paymentId": str(payment.get("paymentId") or ""),
                    },
                    "serverKey": SHEET_SERVER_KEY,
                },
                timeout=20,
            )
        result = response.json()
        if response.status_code < 400 and isinstance(result, dict):
            return result
        return {
            "status": "error",
            "message": "transaction_inspection_failed",
            "detail": str(result)[:300],
        }
    except Exception as exc:
        logger.warning("inspectPaymentTransaction failed: %s", exc)
        return {
            "status": "error",
            "message": "transaction_inspection_failed",
        }


async def get_finance_report(month: str) -> dict:
    """Fetch a protected monthly summary from Apps Script."""
    if not SHEET_WEBHOOK:
        return {"status": "error", "message": "sheet_webhook_missing"}
    if not SHEET_SERVER_KEY:
        return {"status": "error", "message": "server_key_missing"}
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.post(
                SHEET_WEBHOOK,
                json={
                    "action": "getFinanceReport",
                    "month": month,
                    "serverKey": SHEET_SERVER_KEY,
                },
                timeout=20,
            )
        result = response.json()
        if response.status_code >= 400:
            return {"status": "error", "message": f"http_{response.status_code}"}
        return result if isinstance(result, dict) else {"status": "error", "message": "invalid_response"}
    except Exception as exc:
        logger.error("get_finance_report failed: %s", exc)
        return {"status": "error", "message": "request_failed"}


async def create_invite_link(context, days: int, user_id: int | None = None, name: str | None = None) -> str:
    """Create a single-use channel link that stays valid long enough to use.

    The old code expired links after 30 minutes (1800 seconds), which caused
    genuine members to see "Expired Link" when they opened the approval DM
    later. Keep the link single-use, but allow up to 7 days.

    If user_id is given, unban them from the channel first. Telegram treats
    a kicked member as banned until explicitly unbanned -- a brand new
    invite link alone does not let a previously-kicked member back in, even
    though our own kick_with_retry() already does ban+unban at kick time
    (Telegram's own "Removed Users" list can outlive that). A fresh
    reactivation/renewal approval otherwise hands out a link that silently
    fails for exactly the member it was meant for. user_id must be a real
    Telegram numeric id -- never pass a Google Login "G_<sub>" synthetic id
    here, use the `name` parameter for that instead (see
    handle_channel_member_join, which reads a "G_"-prefixed invite link
    name back off the join event to recognize a Google Login member who
    has no Telegram id in the Members sheet at all).
    """
    if user_id is not None:
        try:
            await context.bot.unban_chat_member(chat_id=CHANNEL_ID, user_id=int(user_id), only_if_banned=True)
        except Exception as e:
            logger.warning(f"create_invite_link: unban {user_id} before invite failed: {e}")
    try:
        import time

        requested_days = max(1, int(days or 1))
        valid_days = min(requested_days, 7)
        invite = await context.bot.create_chat_invite_link(
            chat_id=CHANNEL_ID,
            member_limit=1,
            expire_date=int(time.time() + valid_days * 86400),
            name=name or f"JACC member {valid_days}d",
        )
        return invite.invite_link
    except Exception as e:
        logger.error(f"Invite link: {e}")
        return ""


async def channel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Give an ACTIVE member a fresh, single-use channel invite link."""
    user = update.effective_user
    user_id = user.id

    if not await is_active_member(user_id):
        await update.message.reply_text(
            "🚫 Membership Active မဖြစ်သေးပါ။\n\n"
            "Membership ဝယ်ရန် သို့မဟုတ် သက်တမ်းတိုးရန် /renew နှိပ်ပါ။"
        )
        return

    try:
        chat_member = await context.bot.get_chat_member(
            chat_id=CHANNEL_ID, user_id=user_id
        )
        if chat_member.status in ("member", "administrator", "creator"):
            await update.message.reply_text(
                "✅ သင်သည် Channel ထဲ ဝင်ထားပြီးသားဖြစ်ပါတယ်။"
            )
            return
    except Exception as e:
        # A user who has never joined may not be readable as a channel member.
        logger.info(f"channel status check {user_id}: {e}")

    invite_url = await create_invite_link(context, 7, user_id)
    if not invite_url:
        await update.message.reply_text(
            "❌ Channel link အသစ်ထုတ်မရသေးပါ။ Admin ကို ဆက်သွယ်ပေးပါ။"
        )
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("📢 Channel ဝင်ရန်", url=invite_url)
    ]])
    await update.message.reply_text(
        "✅ Channel link အသစ် ထုတ်ပေးပြီးပါပြီ။\n\n"
        "⏰ ဒီ link က ၇ ရက်အတွင်း အသုံးပြုရမယ်။\n"
        "🔒 လူတစ်ယောက်သာ ဝင်လို့ရပါတယ်။",
        reply_markup=keyboard,
    )

async def send_approval_dm(context, member_id: int, months: int,
                           password: str, invite_url: str, package: str = "CH",
                           expire_date: str = ""):
    is_web      = str(package).upper().replace("-", "") in ("WEB", "WEBPROMO")
    expire_date = expire_date or (datetime.now() + timedelta(days=months * 30)).strftime("%d/%m/%Y")
    cust_kb = []
    if invite_url:
        cust_kb.append([InlineKeyboardButton("📢 Channel ဝင်ရန်", url=invite_url)])
    if is_web:
        cust_kb.append([InlineKeyboardButton("🌐 Web App ဖွင့်",
                        url="https://kyawmintun08.github.io/Japan-Auction-Car-Checker/")])

    if is_web:
        text = (
            f"🎉 *Membership Approved!*\n\n"
            f"📦 Package: 💎 Web Premium\n"
            f"📅 သက်တမ်း: *{months} လ*\n"
            f"⏰ ကုန်ဆုံးရက်: `{expire_date}`\n\n"
            f"🔑 *Web Password: `{password}`*\n"
            f"🌐 Web: kyawmintun08.github.io/Japan-Auction-Car-Checker/\n\n"
            f"⚠️ Password ကို မည်သူ့ကိုမျှ မပေးပါနဲ့\n"
            f"   မျှဝေပါက Membership ပိတ်သိမ်းခံရမည်\n\n"
            f"သက်တမ်းတိုးဖို့: /renew\nကျေးဇူးတင်ပါတယ် 🙏"
        )
    else:
        text = (
            f"🎉 *Membership Approved!*\n\n"
            f"📦 Package: 📱 Standard\n"
            f"📅 သက်တမ်း: *{months} လ*\n"
            f"⏰ ကုန်ဆုံးရက်: `{expire_date}`\n\n"
            f"📢 Channel invite link အပေါ်မှ ဝင်ပါ\n\n"
            f"သက်တမ်းတိုးဖို့: /renew\nကျေးဇူးတင်ပါတယ် 🙏"
        )
    try:
        msg = await context.bot.send_message(
            chat_id=member_id, text=text,
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(cust_kb) if cust_kb else None)
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
    kb.append([InlineKeyboardButton("🆕 New Member ဝင်ရန်", callback_data="newmember_start")])
    if ADMIN_USERNAME:
        kb.append([InlineKeyboardButton("💬 Admin ကို ဆက်သွယ်", url=f"https://t.me/{ADMIN_USERNAME}")])
    kb.append([InlineKeyboardButton("🌐 Web App ကြည့်",
               url="https://kyawmintun08.github.io/Japan-Auction-Car-Checker/")])
    kb.append([InlineKeyboardButton(f"📱 Android App v{ANDROID_APP_VERSION} Download",
               url=ANDROID_APP_URL)])

    if is_admin:
        cmd_text = (
            "*Member Commands:*\n"
            "🆕 `/newmember` → Member အသစ်ဝင်ရန်\n"
            "🔄 `/renew` → ရှိပြီးသား Member သက်တမ်းတိုးရန်\n"
            "⬆️ `/upgrade` → Premium Package ပြောင်းရန်\n"
            "🌐 `/web` → Web Link\n"
            "📱 `/app` → App Download (Android + iPhone)\n"
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
            "💳 `/setqr` → Payment QR ထည့်/ပြောင်း\n"
            "💾 `/backup` → CSV backup\n"
            "📊 `/finance 2026-08` → လစဉ်ငွေစာရင်း\n"
        )
    else:
        cmd_text = (
            "*Commands:*\n"
            "🆕 `/newmember` → Member အသစ်ဝင်ရန်\n"
            "🔄 `/renew` → ရှိပြီးသား Member သက်တမ်းတိုးရန်\n"
            "⬆️ `/upgrade` → Premium Package ပြောင်းရန်\n"
            "🌐 `/web` → Web Link\n"
            "📱 `/app` → App Download (Android + iPhone)\n"
            "🔑 `/mypassword` → Password ပြန်ယူ\n"
        )

    await update.message.reply_text(
        f"🚗 *Japan Auction Car Checker*\n"
        f"📍 {LOC_MAESOT} & {LOC_KLANG9} & {LOC_BORDER44}\n\n"
        + cmd_text,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(kb))

async def show_new_member_flow(message, user_id: int):
    """Start the new-member payment flow; /start itself only shows the bot menu."""
    flow = await validate_payment_flow(user_id, "join")
    if not flow.get("ok"):
        if flow.get("reason") == "existing_member_must_renew":
            await message.reply_text(
                "🔄 ဒီ Telegram account မှာ Member record ရှိပြီးသားပါ။\n\n"
                "Member အသစ် payment မလုပ်ပါနဲ့။ ရှိပြီးသား Member အတွက် `/renew` ကိုသာ အသုံးပြုပါ။\n\n"
                "⚠️ Payment မှားပို့မိပါက refund/repayment စစ်ဆေးမှုကြာနိုင်ပါတယ်။",
                parse_mode="Markdown")
        else:
            await message.reply_text(
                "⚠️ Member record ကို စစ်မရသေးပါ။ Payment မလွှဲသေးဘဲ ခဏနေရန် အကြံပြုပါသည်။",
                parse_mode="Markdown")
        return
    await message.reply_text(
        "🆕 *New Member — Member အသစ်ဝင်ရန်*\n\n"
        "ဒီ payment flow ကို Member record မရှိသေးသူများအတွက်သာ အသုံးပြုပါ။\n"
        "ရှိပြီးသား Member ဖြစ်ပါက `/renew` ကို သုံးပါ။\n\n"
        "Package ရွေးချယ်ပါ 👇\n\n"
        "⚠️ Member အသစ် payment နဲ့ Renew payment ကို မရောပါနဲ့။ Payment မှားပို့မိပါက refund/repayment စစ်ဆေးမှုကြာနိုင်ပါတယ်။",
        parse_mode="Markdown",
        reply_markup=build_package_keyboard(user_id, "join"))


async def newmember_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_new_member_flow(update.message, update.effective_user.id)


async def find_car(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_rate_limit(update.effective_user.id):
        await update.message.reply_text("⚠️ တစ်မိနစ်အတွင်း Request များသွားတယ် — ခဏစောင့်ပါ")
        return
    user_id  = update.effective_user.id
    str_uid  = str(user_id)
    if not await is_active_member(user_id):
        # 10 Day Promo eligibility check
        promo_info = await check_promo10d_eligibility(str_uid)
        if promo_info.get("active"):
            pass  # PROMO10D active — proceed to carrequest
        elif not promo_info.get("eligible"):
            await update.message.reply_text(
                f"❌ *ဝင်ခွင့်မရပါ*\n\n{promo_info['reason']}\n\n"
                f"Membership ရယူရန် /newmember နှိပ်ပါ",
                parse_mode='Markdown')
            return
        else:
            # Show buying car button
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("🚗 ကားဝယ်ယူဖို့ လာတာလားး?", callback_data=f"buying_car_{user_id}")
            ]])
            await update.message.reply_text(
                "👋 *Japan Auction Car Checker*\n\n"
                "ကားဝယ်ယူလိုပါက *10 Day Free Promo* ရရှိနိုင်ပါသည်\n\n"
                "⚠️ စည်ကမ်းချက်:\n"
                "• Broker နှင့် ဆက်သွယ်ပြီး Order တင်ရမည်\n"
                "• 10 ရက်အတွင်း Order မတင်ပါက Kick ခံရမည်\n"
                "• Cancel ၂ ကြိမ်နှင့်အထက် ဖြစ်ပါက Promo မရနိုင်\n\n"
                "ဆက်လုပ်မည်ဆိုပါက 👇",
                parse_mode='Markdown',
                reply_markup=kb)
            return
    if not context.args:
        await update.message.reply_text("❌ Chassis ထည့်ပါ\nဥပမာ: `/find NT32-504837`", parse_mode='Markdown')
        return
    is_admin = user_id in ADMIN_IDS
    chassis  = ' '.join(context.args)
    car      = find_by_chassis(chassis)
    if car:
        history = get_price_history(car['chassis'])
        txt     = format_car_info(car, history[-1]['price'] if history else None, history or None)
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
    user_id  = update.effective_user.id
    if not await is_active_member(user_id):
        await update.message.reply_text(
            "🔒 *Member များသာ သုံးနိုင်ပါသည်*\n\nMembership ရယူရန် /newmember နှိပ်ပါ",
            parse_mode='Markdown')
        return
    if not context.args:
        await update.message.reply_text("❌ Model ထည့်ပါ\nဥပမာ: `/model xtrail`", parse_mode='Markdown')
        return
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
    txt += f"\n🌐 [Web မှာကြည့်](https://kyawmintun08.github.io/Japan-Auction-Car-Checker/)"
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
        await update.message.reply_text(
            "❌ Format:\n"
            "`/price CHASSIS PRICE` — အခြေခံ\n"
            "`/price CHASSIS PRICE COLOR` — color ပါ\n"
            "`/price CHASSIS PRICE MODEL COLOR` — model+color ပါ\n\n"
            "ဥပမာ:\n"
            "`/price VZN11-042846 74000 WHITE`\n"
            "`/price VZN11-042846 74000 AD VAN WHITE`",
            parse_mode='Markdown')
        return
    chassis = context.args[0].upper()
    try:
        price = int(context.args[1].replace(',',''))
    except:
        await update.message.reply_text("❌ ဈေး ဂဏန်းသာ ထည့်ပါ", parse_mode='Markdown')
        return
    if price <= 0:
        await update.message.reply_text("❌ ဈေးက 0 ထက် ကြီးရပါမယ်", parse_mode='Markdown')
        return

    extra_args = context.args[2:]
    car = find_by_chassis(chassis)

    if extra_args:
        if len(extra_args) == 1:
            override_color = extra_args[0].upper()
            override_model = None
        else:
            override_color = extra_args[-1].upper()
            override_model = normalize_model_name(" ".join(extra_args[:-1])) or " ".join(extra_args[:-1]).upper()

        if car:
            target_key = normalize_chassis_key(chassis)
            for c in CARS:
                if normalize_chassis_key(c.get("chassis", "")) == target_key:
                    if override_color: c["color"] = override_color
                    if override_model: c["model"] = override_model
                    car = c
                    break
        else:
            base_model = override_model or guess_model_from_chassis(chassis)
            car = {"chassis": chassis, "model": base_model,
                   "color": override_color, "year": 0, "loc": "MaeSot"}
            CARS.append(car)

        if SHEET_WEBHOOK:
            try:
                async with httpx.AsyncClient() as client:
                    if override_color:
                        await client.post(SHEET_WEBHOOK, json={
                            "action": "updateCar", "chassis": chassis, "serverKey": SHEET_SERVER_KEY,
                            "field": "color", "value": override_color
                        }, timeout=40, follow_redirects=True)
                    if override_model:
                        await client.post(SHEET_WEBHOOK, json={
                            "action": "updateCar", "chassis": chassis, "serverKey": SHEET_SERVER_KEY,
                            "field": "model", "value": override_model
                        }, timeout=40, follow_redirects=True)
            except Exception as e:
                logger.error(f"updateCar in price cmd: {e}")
    else:
        if not car:
            car = {"chassis": chassis, "model": guess_model_from_chassis(chassis),
                   "color": "-", "year": 0, "loc": "MaeSot"}
            CARS.append(car)

    user_name = update.effective_user.first_name or "Unknown"
    loc       = loc_display(car.get('loc','MaeSot'))
    entry     = await save_price(car['chassis'], car['model'], car['color'], car['year'], price, user_name, location=loc)
    await update.message.reply_text(
        f"✅ *ဈေးထည့်ပြီး!*\n\n🚗 {car['model']} ({ys(car.get('year',0))}) — `{chassis}`\n"
        f"🎨 {car['color']}\n💰 ฿{price:,}\n📍 {loc}\n📅 {entry['date']}\n👤 {user_name}\n\n"
        f"🌐 [Web မှာကြည့်](https://kyawmintun08.github.io/Japan-Auction-Car-Checker/)",
        parse_mode='Markdown')

async def price_history_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id  = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("🔒 *Admin သာ သုံးနိုင်ပါသည်*", parse_mode='Markdown')
        return
    if not context.args:
        await update.message.reply_text("❌ Chassis ထည့်ပါ\nဥပမာ: `/history NT32-504837`", parse_mode='Markdown')
        return
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
    if len(history) >= 2 and history[0]['price']:
        change = history[-1]['price'] - history[0]['price']
        pct    = (change / history[0]['price']) * 100
        txt += f"\n📊 ပြောင်းလဲမှု: *{change:+,}* ({pct:+.1f}%)"
    kb = [[
        InlineKeyboardButton("💰 ဈေးအသစ်ထည့်", callback_data=f"addprice_{chassis}"),
        InlineKeyboardButton("✏️ ပြင်ရန်",      callback_data=f"editcar_{chassis}"),
    ]]
    await update.message.reply_text(txt, parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(kb))

async def list_cars(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await is_active_member(user_id):
        await update.message.reply_text(
            "🔒 *Member များသာ သုံးနိုင်ပါသည်*\n\nMembership ရယူရန် /newmember နှိပ်ပါ",
            parse_mode='Markdown')
        return
    priced = {p['chassis'] for p in PRICE_HISTORY}
    txt    = f"🚗 *ကားစာရင်း ({len(CARS)} စီး)*\n\n"
    for car in CARS[:20]:
        status = "💰" if car['chassis'] in priced else "⏳"
        txt += f"{status} `{car['chassis']}` — {car['model']} {ys(car.get('year',0))} [{loc_display(car.get('loc','MaeSot'))}]\n"
    if len(CARS) > 20:
        txt += f"\n... နှင့် {len(CARS)-20} စီး ထပ်ရှိ"
    txt += f"\n\n🌐 [Web မှာကြည့်](https://kyawmintun08.github.io/Japan-Auction-Car-Checker/)"
    await update.message.reply_text(txt, parse_mode='Markdown')

async def app_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"📱 *Japan Auction Car Checker — App Download*\n\n"
        f"🤖 *Android*\n"
        "Professional JACC logo ပါသော Android app version အသစ်ကို ဒီနေရာမှာ download လုပ်နိုင်ပါတယ်။\n\n"
        f"{ANDROID_APP_URL}\n\n"
        "Download ပြီး install/update လုပ်ပါ။ ဖုန်းထဲမှာ version 1.02 ဖြစ်ကြောင်း စစ်ဆေးပါ။\n\n"
        "🍎 *iPhone (iOS)*\n"
        "iOS မှာ App Store ကနေချည်း app install ခွင့်ပြုထားလို့ (Apple ရဲ့ security rule) "
        "Android လိုမျိုး file ဒေါင်းလုဒ်ဆွဲပြီး install လုပ်လို့ မရပါဘူး — ဒါပေမယ့် Safari ကနေ "
        "\"Add to Home Screen\" လုပ်ရင် App တစ်ခုလိုပဲ Home Screen ပေါ်မှာ icon ပေါ်လာပြီး "
        "browser bar မပါဘဲ full-screen ဖွင့်ပေးပါတယ်:\n\n"
        "1️⃣ *Safari* ကို ဖွင့်ပြီး အောက်က button ကနေ website ကိုသွားပါ (Chrome စတာတွေက iOS မှာ မရပါ)\n"
        "2️⃣ အောက်ခြေ/အပေါ်ခြေက *Share* (⬆️ box ပုံ) ကို နှိပ်ပါ\n"
        "3️⃣ *\"Add to Home Screen\"* ကို ရွေးပါ\n"
        "4️⃣ *\"Add\"* နှိပ်ပါ — Home Screen ပေါ်မှာ JACC icon ပေါ်လာပါလိမ့်မယ်",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(f"📥 Download Android App v{ANDROID_APP_VERSION}", url=ANDROID_APP_URL)],
            [InlineKeyboardButton("🍎 iPhone: Open Website (Safari)",
                       url="https://kyawmintun08.github.io/Japan-Auction-Car-Checker/")]
        ]))

async def web_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pkg     = await get_member_package(user_id)
    if pkg == "WEB":
        await update.message.reply_text(
            f"🌐 *Japan Auction Car Checker — Web App*\n\n"
            f"https://kyawmintun08.github.io/Japan-Auction-Car-Checker/\n\n"
            f"• {LOC_MAESOT} + {LOC_KLANG9} 🚗\n• ဈေးကြည့်နိုင် 📈\n• Chart ကြည့်နိုင် 📊",
            parse_mode='Markdown')
    elif pkg == "CH":
        await update.message.reply_text(
            "🚫 *Web App access မရှိသေးပါ*\n\n"
            "လက်ရှိ Package: 📱 Standard\n\n"
            "🌐 Web App ကြည့်ဖို့ *Channel+Web Package* သို့ Upgrade လုပ်ပါ\n"
            "👉 /renew နှိပ်ပြီး 💎 Web Premium package ရွေးပါ",
            parse_mode='Markdown')
    else:
        await update.message.reply_text(
            "🚫 *Member များသာ Web App ကြည့်နိုင်ပါသည်*\n\nMembership ဝယ်ရန် 👉 /renew",
            parse_mode='Markdown')

def build_package_keyboard(user_id: int, action: str = "renew"):
    # /upgrade is CH -> WEB only (validate_payment_flow already blocks WEB
    # members from reaching this screen). Offering "Standard" here let an
    # existing CH member pay through the upgrade flow for a plain renewal
    # mislabeled "Renew/Upgrade" end-to-end, which is confusing for both the
    # member and the admin reviewing the payment even though Apps Script
    # still books it safely. Show only the Web Premium choice for upgrade.
    if action == "upgrade":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💎 Web Premium — Upgrade", callback_data=f"pkg_WEB_{user_id}_{action}")],
            [InlineKeyboardButton("❌ Cancel",                  callback_data=f"pkg_cancel_{user_id}")],
        ])
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📱 Standard",      callback_data=f"pkg_CH_{user_id}_{action}"),
         InlineKeyboardButton(f"💎 Web Premium",   callback_data=f"pkg_WEB_{user_id}_{action}")],
        [InlineKeyboardButton("❌ Cancel",          callback_data=f"pkg_cancel_{user_id}")],
    ])

def build_period_keyboard(user_id: int, package: str, action: str = "renew"):
    prices = PLAN_PRICES[package]
    if package == "CH":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(f"1 လ — {prices[1]:,} ks",  callback_data=f"period_{package}_1_{user_id}"),
             InlineKeyboardButton(f"2 လ — {prices[2]:,} ks",  callback_data=f"period_{package}_2_{user_id}")],
            [InlineKeyboardButton(f"3 လ — {prices[3]:,} ks",  callback_data=f"period_{package}_3_{user_id}"),
             InlineKeyboardButton(f"5 လ — {prices[5]:,} ks",  callback_data=f"period_{package}_5_{user_id}")],
            [InlineKeyboardButton("◀️ နောက်သို့",             callback_data=f"pkg_back_{user_id}_{action}")],
        ])
    else:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(f"1 လ — {prices[1]:,} ks",  callback_data=f"period_{package}_1_{user_id}"),
             InlineKeyboardButton(f"2 လ — {prices[2]:,} ks",  callback_data=f"period_{package}_2_{user_id}"),
             InlineKeyboardButton(f"3 လ — {prices[3]:,} ks",  callback_data=f"period_{package}_3_{user_id}")],
            [InlineKeyboardButton("◀️ နောက်သို့",             callback_data=f"pkg_back_{user_id}_{action}")],
        ])

def build_paymethod_keyboard(user_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔵 KPay",    callback_data=f"paymethod_kpay_{user_id}"),
         InlineKeyboardButton("🟣 Wave",    callback_data=f"paymethod_wave_{user_id}"),
         InlineKeyboardButton("🟢 CB Bank", callback_data=f"paymethod_cb_{user_id}")],
        [InlineKeyboardButton("❌ Cancel",  callback_data=f"pkg_cancel_{user_id}")],
    ])

async def renew_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    user_id = user.id
    flow = await validate_payment_flow(user_id, "renew")
    if not flow.get("ok"):
        reason = flow.get("reason")
        if reason == "new_member_must_join":
            await update.message.reply_text(
                "🆕 ဒီ Telegram account မှာ Member record မရှိသေးပါ။\n\n"
                "Member အသစ်ဝင်ရန် `/newmember` ကိုနှိပ်ပြီး New Member payment flow ကိုသာ အသုံးပြုပါ။\n\n"
                "⚠️ Member အသစ် payment နဲ့ Renew payment ကို မရောပါနဲ့။ Payment မှားပို့မိပါက refund/repayment စစ်ဆေးမှုကြာနိုင်ပါတယ်။",
                parse_mode="Markdown")
        else:
            await update.message.reply_text(
                "⚠️ Member record ကို စစ်မရသေးပါ။ Payment မလွှဲသေးဘဲ ခဏနေရန်နှင့် Admin ကို ဆက်သွယ်ရန် အကြံပြုပါသည်.",
                parse_mode="Markdown")
        return
    record = flow.get("record") or {}
    current_pkg = str(record.get("package") or "").upper().strip()
    current_status = str(record.get("status") or "").upper().strip()
    await update.message.reply_text(
        "🔄 *Renew Member — သက်တမ်းတိုးရန်*\n\n"
        f"လက်ရှိ Status: `{current_status or 'UNKNOWN'}`\n"
        f"လက်ရှိ Package: `{current_pkg or 'UNKNOWN'}`\n\n"
        "Package ရွေးချယ်ပါ 👇\n\n"
        "⚠️ ဒီ flow သည် ရှိပြီးသား Member အတွက် Renew/Upgrade payment သီးသန့်ဖြစ်ပါတယ်။\n"
        "⚠️ Payment မှားပို့မိပါက refund/repayment စစ်ဆေးမှုကြာနိုင်သောကြောင့် မလွှဲမီ Member type၊ Package၊ Amount နှင့် Receiver ကို စစ်ပါ။",
        parse_mode='Markdown',
        reply_markup=build_package_keyboard(user_id, "renew"))

async def mypassword_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    user_id = user.id
    if not await is_active_member(user_id):
        await update.message.reply_text(
            "🔒 *Member များသာ သုံးနိုင်ပါသည်*\n\nMembership ရယူရန် /newmember နှိပ်ပါ",
            parse_mode='Markdown')
        return
    pkg = await get_member_package(user_id)
    if pkg != "WEB":
        await update.message.reply_text(
            "🚫 *Web Password မရှိပါ*\n\n"
            "လက်ရှိ Package: 📱 Standard\n\n"
            "🌐 Web App သုံးဖို့ 💎 *Web Premium* သို့ Upgrade လုပ်ပါ\n"
            "👉 /renew နှိပ်ပြီး Web Premium ရွေးပါ",
            parse_mode='Markdown')
        return
    if not SHEET_WEBHOOK:
        await update.message.reply_text("❌ System error — Admin ကို ဆက်သွယ်ပါ")
        return
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(SHEET_WEBHOOK, json={
                "action": "getPassword", "serverKey": SHEET_SERVER_KEY,
                "userId": str(user_id),
            }, timeout=40, follow_redirects=True)
        data = resp.json()
        if data.get("status") == "ok" and data.get("password"):
            await update.message.reply_text(
                f"🔑 *သင်၏ Web Password*\n\n"
                f"`{data['password']}`\n\n"
                f"🌐 https://kyawmintun08.github.io/Japan-Auction-Car-Checker/\n\n"
                f"⚠️ Password ကို မည်သူ့ကိုမျှ မပေးပါနဲ့\n"
                f"   မျှဝေပါက Membership ပိတ်သိမ်းခံရမည်",
                parse_mode='Markdown')
        else:
            admin_link = f"\n💬 [Admin ကို ဆက်သွယ်](https://t.me/{ADMIN_USERNAME})" if ADMIN_USERNAME else ""
            await update.message.reply_text(
                f"❌ Password မတွေ့ပါ\n\nAdmin ကို ဆက်သွယ်ပါ{admin_link}",
                parse_mode='Markdown')
    except Exception as e:
        logger.error(f"mypassword: {e}")
        await update.message.reply_text("❌ Error — Admin ကို ဆက်သွယ်ပါ")

async def resetpass_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not ADMIN_IDS or user_id not in ADMIN_IDS:
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
                "action":   "resetPassword", "serverKey": SHEET_SERVER_KEY,
                "username": target,
                "password": new_pw,
            }, timeout=40, follow_redirects=True)
        data = resp.json()
        if data.get("status") == "ok":
            member_id = data.get("userId")
            if member_id and str(member_id).isdigit():
                try:
                    await context.bot.send_message(
                        chat_id=int(member_id),
                        text=f"🔑 *Password Reset လုပ်ပြီ*\n\n"
                             f"New Password: `{new_pw}`\n\n"
                             f"🌐 https://kyawmintun08.github.io/Japan-Auction-Car-Checker/\n\n"
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

async def updateid_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not ADMIN_IDS or user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်")
        return
    if len(context.args) < 3:
        await update.message.reply_text(
            "❌ Format: `/updateid @username [oldID] [newID]`\n"
            "ဥပမာ: `/updateid @Steve 123456789 987654321`\n\n"
            "⚠️ Old ID မပါရင် update မလုပ်ဘူး — Security အတွက်",
            parse_mode='Markdown')
        return
    target_username = context.args[0].replace('@', '')
    try:
        old_id = int(context.args[1])
        new_id = int(context.args[2])
    except:
        await update.message.reply_text("❌ ID တွေ ဂဏန်းဖြစ်ရမည်")
        return
    if old_id == new_id:
        await update.message.reply_text("❌ Old ID နဲ့ New ID တူနေတယ်")
        return
    if new_id in ADMIN_IDS:
        await update.message.reply_text("❌ Admin ID ကို Member ID အဖြစ် သုံးမရပါ")
        return
    await update.message.reply_text("🔍 Old ID စစ်ဆေးနေတယ်... ⏳")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(SHEET_WEBHOOK, json={
                "action": "verifyOldId",
                "username": target_username,
                "oldId": str(old_id),
            }, timeout=40, follow_redirects=True)
        data = resp.json()
        if data.get("status") != "ok":
            await update.message.reply_text(
                f"❌ *Old ID မမှန်ဘူး*\n\n"
                f"@{target_username} ရဲ့ Sheet မှာ `{old_id}` မတွေ့ဘူး\n"
                f"Old ID ကို ပြန်စစ်ပြီး ထပ်ကြိုးစားပါ",
                parse_mode='Markdown')
            return
    except Exception as e:
        logger.error(f"verifyOldId: {e}")
        await update.message.reply_text("❌ Sheet စစ်မရ — ထပ်ကြိုးစားပါ")
        return
    pending_updateid[user_id] = {
        "target_username": target_username,
        "old_id": old_id,
        "new_id": new_id,
    }
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ အတည်ပြု",  callback_data=f"uid_ok_{user_id}"),
        InlineKeyboardButton("❌ မလုပ်တော့", callback_data=f"uid_no_{user_id}"),
    ]])
    await update.message.reply_text(
        f"⚠️ *ID Update အတည်ပြုချက်*\n\n"
        f"👤 Member: @{target_username}\n"
        f"🔴 ဟောင်း ID: `{old_id}` ✅ စစ်မှန်ပြီ\n"
        f"🟢 အသစ် ID: `{new_id}`\n\n"
        f"အတည်ပြုရန် 👇",
        parse_mode='Markdown',
        reply_markup=kb)

# ── /setqr — Admin Payment QR Setup ──────────────────
async def setqr_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်")
        return

    # Show current state
    status_lines = []
    for method, info in PAYMENT_METHOD_INFO.items():
        file_id = await get_payment_qr(method)
        mark    = "✅" if file_id else "⚪"
        status_lines.append(f"{mark} {info['label']}")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔵 KPay",    callback_data=f"setqr_kpay_{user_id}"),
         InlineKeyboardButton("🟣 Wave",    callback_data=f"setqr_wave_{user_id}"),
         InlineKeyboardButton("🟢 CB Bank", callback_data=f"setqr_cb_{user_id}")],
        [InlineKeyboardButton("❌ Cancel",  callback_data=f"setqr_cancel_{user_id}")],
    ])
    await update.message.reply_text(
        f"💳 *Payment QR Setup*\n\n"
        f"လက်ရှိ အခြေအနေ:\n"
        + "\n".join(status_lines)
        + "\n\nဘယ် method အတွက် QR ထည့်/ပြောင်းမလဲ? 👇",
        parse_mode='Markdown',
        reply_markup=kb)

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not ADMIN_IDS or user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်")
        return

    pkg_filter = None
    msg_parts  = context.args if context.args else []
    if msg_parts and msg_parts[0].upper() in ("WEB", "CH"):
        pkg_filter = msg_parts[0].upper()
        msg_parts  = msg_parts[1:]

    message = " ".join(msg_parts)

    if not message:
        pending_broadcast[user_id] = {
            "pkg_filter": pkg_filter,
            "waiting_photo": True
        }
        pkg_label = f" ({pkg_filter} only)" if pkg_filter else " (အားလုံး)"
        await update.message.reply_text(
            f"📢 *Broadcast{pkg_label}*\n\n"
            f"ပုံနဲ့ Caption တွဲပြီး ပို့ပါ\n"
            f"(Caption = Message ဖြစ်မည်)\n\n"
            f"Text သာ ပို့ချင်ရင်:\n"
            f"`/broadcast မက်ဆေ့ပါ`\n\n"
            f"❌ Cancel: /broadcast cancel",
            parse_mode='Markdown')
        return

    if message.lower() == "cancel":
        pending_broadcast.pop(user_id, None)
        pending_broadcast_text.pop(user_id, None)
        await update.message.reply_text("❌ Broadcast ပယ်ဖျက်ပြီ")
        return

    await update.message.reply_text("⏳ Member list ဆွဲနေတယ်...")

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                SHEET_WEBHOOK,
                json={"action": "getMembers", "serverKey": SHEET_SERVER_KEY},
                timeout=40,
                follow_redirects=True
            )
        data = resp.json()
        members = data.get("members", [])
    except Exception as e:
        logger.error(f"broadcast getMembers: {e}")
        await update.message.reply_text("❌ Member list ဆွဲမရ")
        return

    targets = []
    for m in members:
        status  = str(m.get("status", "")).upper()
        pkg     = str(m.get("package", "")).upper()
        uid     = m.get("userId") or m.get("userID") or m.get("UserID")
        if status != "ACTIVE":
            continue
        if pkg_filter and pkg != pkg_filter:
            continue
        if uid:
            targets.append(str(uid))

    if not targets:
        await update.message.reply_text("❌ Member မတွေ့ဘူး")
        return

    # Show exactly what will be sent (including the interpreted filter and
    # the FINAL message text) and require an explicit Confirm before
    # anything actually goes out. `/broadcast Web ...` / `/broadcast Ch ...`
    # silently strips that first word as a WEB/CH package filter — this
    # preview is what lets an admin catch that before 100+ members get a
    # narrowed or mangled broadcast with no way to take it back.
    pending_broadcast_text[user_id] = {
        "pkg_filter": pkg_filter,
        "message":    message,
        "count":      len(targets),
    }
    pkg_label = f" — {pkg_filter} package သာ" if pkg_filter else " — Member အားလုံး"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ ပို့မည်",  callback_data=f"bcast_send_{user_id}"),
        InlineKeyboardButton("❌ Cancel",  callback_data=f"bcast_no_{user_id}"),
    ]])
    await update.message.reply_text(
        f"📢 *Broadcast Preview*{pkg_label}\n"
        f"👥 {len(targets)} ယောက်ဆီ ပို့မည်\n\n"
        f"— — — — —\n{message}\n— — — — —\n\n"
        f"⚠️ Message ပါတဲ့ စာသား/filter မှန်မမှန် စစ်ပြီးမှ Confirm နှိပ်ပါ",
        parse_mode='Markdown', reply_markup=kb)

async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not ADMIN_IDS or user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်")
        return
    await update.message.reply_text("⏳ Sheet မှ data ဆွဲနေသည်...")
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(SHEET_WEBHOOK, json={
                "action": "getBackupCSV", "serverKey": SHEET_SERVER_KEY
            }, timeout=30, follow_redirects=True)
        data = resp.json()
        if data.get("status") == "ok":
            csv_content = data.get("csv") or ""
            if not csv_content.strip():
                # A genuinely empty/headers-only sheet is a successful
                # backup, not a webhook failure — don't conflate the two.
                await update.message.reply_text("✅ Backup ပြီးပါပြီ — Members Sheet ထဲ data မရှိသေးပါ")
                return
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


async def finance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show an Admin-only monthly revenue and membership activity summary."""
    user_id = update.effective_user.id
    if not ADMIN_IDS or user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်")
        return

    bangkok_now = datetime.now(timezone.utc) + timedelta(hours=7)
    month = (context.args[0].strip() if context.args else bangkok_now.strftime("%Y-%m"))
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        await update.message.reply_text(
            "အသုံးပြုပုံ: `/finance YYYY-MM`\nဥပမာ: `/finance 2026-08`",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(f"⏳ {month} Finance Report ဆွဲနေပါတယ်...")
    result = await get_finance_report(month)
    if result.get("status") != "ok":
        message = result.get("message", "unknown_error")
        if message in {"server_key_missing", "server_key_not_configured"}:
            text = "❌ Finance report မရပါ။ Railway `SHEET_SERVER_KEY` နှင့် Apps Script `JACC_SERVER_KEY` ကို စစ်ပါ။"
        elif message == "unauthorized":
            text = "❌ Finance report authorization မအောင်မြင်ပါ။ Server key ကို စစ်ပါ။"
        else:
            text = f"❌ Finance report မရပါ။ ({message})"
        await update.message.reply_text(text, parse_mode="Markdown")
        return

    summary = result.get("summary", {})
    by_method = summary.get("byMethod", {})
    by_type = summary.get("byEntryType", {})
    by_source = summary.get("bySource", {})
    lines = [
        f"📊 Finance Report — {month}",
        "",
        f"💵 စုစုပေါင်းဝင်ငွေ: {int(summary.get('totalAmount', 0) or 0):,} Ks",
        f"💳 Paid records: {summary.get('paymentCount', 0)}",
        f"👥 Membership activity: {summary.get('activityCount', 0)}",
        f"✅ Amount သိရ: {summary.get('knownAmountCount', 0)}",
        f"⚠️ Amount မသိရ: {summary.get('unknownAmountCount', 0)}",
        f"🗂️ Legacy row (စုစုပေါင်းထဲ မထည့်): {summary.get('legacyUnclassifiedCount', 0)} — {int(summary.get('legacyAmount', 0) or 0):,} Ks",
        "",
        "📥 Payment Method",
    ]
    for method, label in (("KPay", "KPay"), ("Wave", "Wave"), ("Bank", "Bank / CB"), ("Other", "Other")):
        item = by_method.get(method, {}) or {}
        lines.append(
            f"• {label}: {item.get('count', 0)} records — {int(item.get('total', 0) or 0):,} Ks"
        )
    lines.extend([
        "",
        "👥 Member အမျိုးအစား",
        f"• အသစ်: {by_type.get('NEW', 0)}",
        f"• Renew: {by_type.get('RENEW', 0)}",
        f"• Upgrade: {by_type.get('UPGRADE', 0)}",
        f"• Manual: {by_type.get('MANUAL', 0)}",
        f"• Promo: {by_type.get('PROMO', 0)}",
        f"• မခွဲရသေး: {by_type.get('UNKNOWN', 0)}",
        "",
        "🧾 Record source",
        f"• Payment slip: {by_source.get('PAYMENT_SLIP', 0)}",
        f"• Manual approve: {by_source.get('MANUAL', 0)}",
        f"• Promo: {by_source.get('PROMO', 0)}",
        "",
        f"🔎 Duplicate transaction: {summary.get('duplicateCount', 0)}",
        f"⚠️ Transaction မရှိ: {summary.get('missingTransactionCount', 0)}",
    ])

    review_items = summary.get("reviewItems", []) or []
    if review_items:
        reason_names = {
            "missing_amount": "Amount မပါ",
            "missing_transaction": "Transaction No မပါ",
            "missing_entry_type": "NEW/RENEW မခွဲရ",
            "legacy_unclassified": "အဟောင်း row — EntryType/Source မပါ",
            "duplicate_transaction": "Duplicate transaction",
        }
        lines.extend(["", "🧾 စစ်ရန်လိုသော row များ"])
        for item in review_items[:8]:
            reason = reason_names.get(item.get("reason"), item.get("reason", "စစ်ရန်"))
            lines.append(
                f"• Row {item.get('row', '?')} — {item.get('date', '?')} — {reason}"
            )
        if len(review_items) > 8:
            lines.append(f"• ... နောက်ထပ် {len(review_items) - 8} rows")

    await update.message.reply_text("\n".join(lines))


async def upgrade_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    user_id = user.id
    flow = await validate_payment_flow(user_id, "upgrade")
    if not flow.get("ok"):
        reason = flow.get("reason")
        if reason == "new_member_must_join":
            message = (
                "🆕 Member record မရှိသေးပါ။ `/upgrade` မဟုတ်ဘဲ `/newmember` မှ New Member flow ကို သုံးပါ။\n\n"
                "⚠️ Payment မှားပို့မိပါက refund/repayment စစ်ဆေးမှုကြာနိုင်ပါတယ်။"
            )
        elif reason == "already_premium":
            message = (
                "💎 ဒီ account သည် Web Premium ဖြစ်ပြီးသားပါ။ `/upgrade` ထပ်မသုံးပါနှင့်။\n\n"
                "သက်တမ်းတိုးလိုပါက `/renew` ကို အသုံးပြုပါ။ Payment မှားပို့မိပါက refund/repayment စစ်ဆေးမှုကြာနိုင်ပါတယ်။"
            )
        else:
            message = "⚠️ Member record ကို စစ်မရသေးပါ။ Payment မလွှဲသေးဘဲ Admin ကို ဆက်သွယ်ပါ။"
        await update.message.reply_text(message, parse_mode="Markdown")
        return
    record = flow.get("record") or {}
    current_pkg = str(record.get("package") or "").upper().strip()
    await update.message.reply_text(
        "⬆️ *Package Upgrade — ရှိပြီးသား Member သီးသန့်*\n\n"
        f"လက်ရှိ Package: `{current_pkg or 'UNKNOWN'}`\n"
        "📱 Standard → 💎 Web Premium\n\n"
        "Web ဝင်ခွင့် ထပ်ထည့်ချင်ရင် Package ရွေးပါ 👇\n\n"
        "⚠️ New Member payment မသုံးပါနဲ့။ Flow၊ Package၊ Amount နှင့် Receiver မှန်ကြောင်း စစ်ပါ။\n"
        "Payment မှားပို့မိပါက refund/repayment စစ်ဆေးမှုကြာနိုင်ပါတယ်။",
        parse_mode='Markdown',
        reply_markup=build_package_keyboard(user_id, "upgrade"))

# ── NEW: Broker Session Selector ──────────────────────
async def broker_ask_target(msg_obj, context, broker_tg_id: str,
                             broker_sessions: list, text: str = "",
                             is_photo: bool = False, file_bytes: bytes = None,
                             caption: str = ""):
    pending_broker_target[broker_tg_id] = {
        "text": text, "is_photo": is_photo,
        "file_bytes": file_bytes, "caption": caption,
        "sessions": broker_sessions,
    }
    btns = []
    for req_id, sess in broker_sessions:
        svc  = sess.get("serviceType", "search")
        icon = "🏆" if svc == "auction" else "🔍"
        cust = sess.get("customerUsername", "Customer")
        btns.append([InlineKeyboardButton(
            f"{icon} {req_id} — {cust}",
            callback_data=f"bsel_{broker_tg_id}_{req_id}")])
    btns.append([InlineKeyboardButton(
        "❌ မပို့တော့ဘူး",
        callback_data=f"bsel_{broker_tg_id}_cancel")])
    await msg_obj.reply_text(
        "💬 *Session ၂ ခုရှိတယ် — ဘယ် Customer ကို ပို့မလဲ?*",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(btns))

# ── OCR ───────────────────────────────────────────────
def tesseract_ocr_chassis(file_bytes: bytes) -> str:
    if not TESSERACT_AVAILABLE:
        return ""
    try:
        from PIL import ImageEnhance, ImageFilter, ImageOps
        img = ImageOps.exif_transpose(Image.open(BytesIO(file_bytes))).convert("RGB")
        # Marker writing is thin and low-contrast in many Telegram photos.
        # Run a small deterministic set of enlarged/contrast variants.
        scale = 2 if max(img.size) < 2400 else 1
        if scale > 1:
            img = img.resize((img.width * scale, img.height * scale))
        gray = ImageOps.grayscale(img)
        variants = [
            img,
            ImageEnhance.Contrast(gray).enhance(2.2),
            ImageOps.autocontrast(gray).filter(ImageFilter.SHARPEN),
        ]
        for variant in variants:
            for config in ("--psm 6", "--psm 11"):
                text = pytesseract.image_to_string(variant, config=config)
                chassis = extract_chassis_from_text(text)
                if chassis:
                    return chassis
    except Exception as e:
        logger.error(f"Tesseract: {e}")
    return ""

async def gemini_ocr_auction_list(file_bytes: bytes) -> tuple:
    if not GEMINI_API_KEY:
        return [], None
    try:
        import base64, json
        img_b64 = base64.b64encode(file_bytes).decode('ascii')
        url     = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents":[{"parts":[
            {"text": (
                "This is a JAN JAPAN auction car list image from Thailand.\n\n"
                "STEP 1 — Read the TITLE/HEADER at the very top of the image:\n"
                "   Look for these EXACT words in the blue/colored header band:\n"
                "   → 'KLANG9' or 'KLANG 9' or '9.2 FREEZONE' = location is Klang9\n"
                "   → 'MAESOT' or 'MAE SOT' = location is MaeSot\n"
                "   → 'BEST BORDER' or '44 GATE' or 'BORDER-44' or 'BORDER 44' = location is Border44\n\n"
                "STEP 2 — Extract every car row from the table.\n\n"
                "Return ONLY valid JSON, no markdown, no explanation:\n"
                "{\"location\":\"Klang9\",\"cars\":[{\"chassis\":\"NT32-024640\",\"model\":\"X-TRAIL\",\"color\":\"BLACK\",\"year\":2014}]}\n\n"
                "Rules:\n"
                "- location MUST be exactly 'Klang9' OR 'MaeSot' OR 'Border44'\n"
                "- If header says KLANG9 → location = 'Klang9'\n"
                "- If header says BEST BORDER or 44 GATE → location = 'Border44'\n"
                "- If header says MAESOT → location = 'MaeSot'\n"
                "- year must be a number (e.g. 2014 not '2014')"
            )},
            {"inline_data":{"mime_type":"image/jpeg","data":img_b64}}
        ]}]}
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, timeout=60)
        data = resp.json()
        if "candidates" not in data:
            return [], None
        text  = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        start = text.find('{'); end = text.rfind('}') + 1
        if start >= 0 and end > start:
            parsed = json.loads(text[start:end])
            cars   = parsed.get("cars", [])
            loc    = parsed.get("location", None)
            return cars, loc
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
1. Read the handwritten chassis number on the windshield. Mentally zoom/crop that writing before reading it. Distinguish G/6, B/8, O/0, I/1, and missing hyphens carefully.
2. Identify car body COLOR from the paint (WHITE, BLACK, SILVER, PEARL WHITE, DARK BLUE, RED, BLUE, GREEN, YELLOW, BROWN, ORANGE, GREY)
3. Identify car MODEL from the shape/badge only as a tentative visual field.
4. Identify manufacturing YEAR only if a clearly visible year is shown in the image — this includes a 4-digit year (e.g. 2016) that is handwritten on the windshield near the chassis number, the same way the chassis number itself is handwritten there, as well as a year printed on a plate or sticker.

Do not infer a year from the chassis prefix, model, or apparent age, and do not confuse the year with a lot number, price, or inspection date written nearby. If the handwritten chassis or year is not clearly legible, return UNKNOWN or 0 instead of guessing.
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
            logger.info(f"Gemini chassis raw: {data}")
            if "candidates" in data and data["candidates"]:
                cand = data["candidates"][0]
                if "content" not in cand:
                    logger.warning(f"Gemini no content: finishReason={cand.get('finishReason','?')}")
                else:
                    text    = cand["content"]["parts"][0]["text"].strip().upper()
                    chassis = ""; model = ""; color = ""; year = 0
                    for line in text.split("\n"):
                        line = line.strip()
                        if line.startswith("CHASSIS:"):
                            raw = line.replace("CHASSIS:","").strip()
                            for pat in [
                                r'[A-Z]{1,5}\d{1,4}[A-Z]{0,2}\d{0,2}[-\s]\d{4,7}',
                                r'[A-Z]{2,6}\d{2,4}[-\s]\d{4,7}',
                                r'[A-Z0-9]{4,20}[-\s]\d{4,7}',
                                r'[A-Z0-9]{6,25}',
                            ]:
                                m = re.search(pat, raw)
                                if m:
                                    chassis = m.group().replace(' ', '-').strip()
                                    break
                        elif line.startswith("MODEL:"): model = line.replace("MODEL:","").strip()
                        elif line.startswith("COLOR:"): color = line.replace("COLOR:","").strip()
                        elif line.startswith("YEAR:"):
                            try: year = int(re.search(r'\d{4}', line).group())
                            except: year = 0
                    if chassis:
                        return {"chassis":chassis,"model":model,"color":color,"year":year}
        except Exception as e:
            logger.error(f"Gemini OCR error: {e}")
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

    # ── Admin /setqr Mode ──
    if user_id in ADMIN_IDS and user_id in pending_setqr:
        method     = pending_setqr.pop(user_id)
        file_id    = photo.file_id
        admin_name = update.effective_user.first_name or "admin"
        ok         = await set_payment_qr(method, file_id, admin_name)
        info       = PAYMENT_METHOD_INFO.get(method, {})
        if ok:
            await update.message.reply_text(
                f"✅ *{info.get('label','')} QR Saved!*\n\n"
                f"📋 ID: `{file_id[:20]}...`\n"
                f"👤 By: {admin_name}\n\n"
                f"➡️ နောက် method ထည့်ဖို့ /setqr ထပ်နှိပ်ပါ",
                parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Save မရဘူး — Sheet စစ်ဆေးပါ")
        return

    # ── Broadcast Photo Mode ──
    if user_id in pending_broadcast and pending_broadcast[user_id].get("waiting_photo"):
        bc      = pending_broadcast.pop(user_id)
        pkg_filter = bc.get("pkg_filter")
        caption_text = update.message.caption or ""

        await update.message.reply_text("⏳ Member list ဆွဲနေတယ်...")
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    SHEET_WEBHOOK,
                    json={"action": "getMembers", "serverKey": SHEET_SERVER_KEY},
                    timeout=40, follow_redirects=True)
            data = resp.json()
            members = data.get("members", [])
        except Exception as e:
            logger.error(f"broadcast getMembers: {e}")
            await update.message.reply_text("❌ Member list ဆွဲမရ")
            return

        targets = []
        for m in members:
            status = str(m.get("status","")).upper()
            pkg    = str(m.get("package","")).upper()
            uid    = m.get("userId") or m.get("userID") or m.get("UserID")
            if status != "ACTIVE": continue
            if pkg_filter and pkg != pkg_filter: continue
            if uid: targets.append(str(uid))

        if not targets:
            await update.message.reply_text("❌ Member မတွေ့ဘူး")
            return

        pkg_label = f" ({pkg_filter} only)" if pkg_filter else ""
        await update.message.reply_text(f"📢 {len(targets)} ယောက်ကို ပုံ+စာ ပို့မည်{pkg_label}...")

        file = await photo.get_file()
        file_bytes = bytes(await file.download_as_bytearray())
        from io import BytesIO

        success = 0; failed = 0
        for uid in targets:
            try:
                bio = BytesIO(file_bytes)
                bio.name = "broadcast.jpg"
                cap = f"📢 *Japan Auction Car*\n\n{caption_text}" if caption_text else "📢 *Japan Auction Car*"
                await context.bot.send_photo(
                    chat_id=int(uid),
                    photo=bio,
                    caption=cap,
                    parse_mode="Markdown")
                success += 1
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.error(f"broadcast photo {uid}: {e}")
                failed += 1

        await update.message.reply_text(
            f"✅ *Broadcast ပုံ ပြီးပြီ*\n\n✅ အောင်မြင်: {success} ယောက်\n❌ မရောက်: {failed} ယောက်",
            parse_mode="Markdown")
        return

    if str(user_id) in pending_deposit:
        dep_data = pending_deposit[str(user_id)]
        if dep_data.get("step") == "waiting_slip" and dep_data.get("slip_info"):
            # A slip is already sitting with the admin awaiting Confirm/Reject.
            # Silently overwriting it here would let a second (possibly
            # doctored) slip replace the one the admin is actually looking at.
            await update.message.reply_text(
                "⏳ ပထမ Slip ကို Admin စစ်ဆေးနေဆဲပါ — ဒီ Slip ကို ခဏစောင့်ပြီးမှ ပို့ပါ။\n"
                "Slip မှားပို့မိရင် Admin ကို တိုက်ရိုက် ဆက်သွယ်ပါ။",
                parse_mode='Markdown')
            return
        if dep_data.get("step") == "waiting_slip":
            await update.message.reply_text("🔍 Deposit Slip ဖတ်နေတယ်... ⏳")
            try:
                file       = await photo.get_file()
                file_bytes = bytes(await file.download_as_bytearray())
                slip_info  = await gemini_read_slip(file_bytes)
            except Exception as e:
                logger.error(f"deposit slip read: {e}")
                slip_info = {}

            amount   = slip_info.get("AMOUNT", "UNKNOWN")
            pay_type = slip_info.get("TYPE", "UNKNOWN")
            txn_no   = slip_info.get("TRANSACTION_NO", "UNKNOWN")
            date_str = slip_info.get("DATE", "UNKNOWN")

            amount_ok = ""
            amount_verified = False
            if amount != "UNKNOWN":
                try:
                    amt_num = int(re.sub(r'[^\d]', '', amount))
                    if amt_num >= 20000:
                        amount_ok = "✅"
                        amount_verified = True
                    else:
                        amount_ok = "⚠️ မပြည့်မီ (฿20,000 လိုသည်)"
                except:
                    amount_ok = "⚠️ စစ်မရ"

            pending_deposit[str(user_id)]["slip_info"] = slip_info
            pending_deposit[str(user_id)]["amount_verified"] = amount_verified

            req_id       = dep_data.get("reqId", "")
            broker_tg_id = dep_data.get("brokerTgId", "")
            name         = update.effective_user.first_name or str(user_id)

            admin_text = (
                f"💰 *Deposit Slip အသစ်*\n\n"
                f"👤 {name} (`{user_id}`)\n"
                f"🆔 Request: `{req_id}`\n\n"
                f"🏦 Type: {pay_type}\n"
                f"🔢 Txn No: `{txn_no}`\n"
                f"💵 Amount: {amount} ฿ {amount_ok}\n"
                f"📅 Date: {date_str}\n\n"
                f"⚠️ စစ်ဆေးပြီးမှ Confirm လုပ်ပါ"
            )
            admin_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"💬 {name} ကို Message", url=f"tg://user?id={user_id}")],
                [InlineKeyboardButton("✅ Confirm", callback_data=f"dep_ok_{user_id}"),
                 InlineKeyboardButton("❌ Reject",  callback_data=f"dep_no_{user_id}")],
            ])
            await notify_admins(context, admin_text, reply_markup=admin_kb)
            await update.message.reply_text(
                "✅ *Deposit Slip လက်ခံပြီ!*\n\n"
                "Admin စစ်ဆေးနေသည် — ခဏစောင့်ပါ 🙏",
                parse_mode='Markdown')
            return

    # ── Photo Relay Mode (Proxy Chat) ──
    str_uid = str(user_id)
    cust_session_photo = next(
        ((sid, s) for sid, s in proxy_sessions.items()
         if str(s.get("customerId","")) == str_uid and s.get("status") == "ACTIVE"),
        None
    )
    # FIXED: collect ALL broker sessions
    broker_sessions_photo = [
        (sid, s) for sid, s in proxy_sessions.items()
        if str(s.get("brokerId","")) == str_uid and s.get("status") == "ACTIVE"
    ]

    if cust_session_photo or broker_sessions_photo:
        if cust_session_photo:
            _sid_chk, _sess_chk = cust_session_photo
            _rid_chk = _sess_chk.get("reqId", "")
            if _rid_chk.startswith("A") and not _sess_chk.get("deposit_paid", False):
                return

        if caption:
            blocked, reason = proxy_filter(caption)
            if blocked:
                await update.message.reply_text(
                    f"⚠️ *Photo Block ဖြစ်သွားတယ်*\n\n"
                    f"❌ Caption မှာ {reason}\n"
                    f"Caption ဖြုတ်ပြီး ပြန်ပို့ပါ",
                    parse_mode='Markdown')
                return

        try:
            file       = await photo.get_file()
            file_bytes = bytes(await file.download_as_bytearray())
        except Exception as e:
            logger.error(f"photo relay download: {e}")
            await update.message.reply_text("❌ ပုံ download မရဘူး")
            return

        relay_image_url = ""
        if all([CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET]):
            session_id = cust_session_photo[0] if cust_session_photo else broker_sessions_photo[0][0]
            relay_image_url = await upload_to_cloudinary(file_bytes, f"relay_{session_id}_{int(datetime.now().timestamp())}")

        from io import BytesIO

        if cust_session_photo:
            sid, session    = cust_session_photo
            broker_tg_id    = session.get("brokerId")
            req_id          = session.get("reqId", sid)
            cap_text        = f"📷 *Customer #{req_id}:*\n\n{caption}" if caption else f"📷 *Customer #{req_id}*"
            if broker_tg_id:
                try:
                    bio = BytesIO(file_bytes); bio.name = "photo.jpg"
                    await context.bot.send_photo(
                        chat_id=int(broker_tg_id),
                        photo=bio,
                        caption=cap_text,
                        parse_mode='Markdown')
                    await update.message.reply_text("✅ ပုံ ပို့ပြီ")
                except Exception as e:
                    logger.error(f"photo relay C→B: {e}")
                    await update.message.reply_text("❌ Broker ကို မပို့နိုင်ဘူး")
            return

        if broker_sessions_photo:
            if len(broker_sessions_photo) == 1:
                sid, session    = broker_sessions_photo[0]
                customer_id     = session.get("customerId")
                broker_obj      = session.get("brokerObj", {})
                broker_id       = broker_obj.get("brokerId", "B???")
                req_id          = session.get("reqId", sid)
                cap_text        = f"📷 *Broker #{broker_id}:*\n\n{caption}" if caption else f"📷 *Broker #{broker_id}*"
                if customer_id:
                    try:
                        bio = BytesIO(file_bytes); bio.name = "photo.jpg"
                        await context.bot.send_photo(
                            chat_id=int(customer_id), photo=bio,
                            caption=cap_text, parse_mode='Markdown')
                        await update.message.reply_text("✅ ပုံ ပို့ပြီ")
                    except Exception as e:
                        logger.error(f"photo relay B→C: {e}")
                        await update.message.reply_text("❌ Customer ကို မပို့နိုင်ဘူး")
            else:
                await broker_ask_target(
                    update.message, context,
                    broker_tg_id=str_uid,
                    broker_sessions=broker_sessions_photo,
                    text="", is_photo=True,
                    file_bytes=file_bytes, caption=caption)
            return

    # ── Payment Slip Mode ──
    if user_id not in pending_payment:
        restored_payment = await get_payment_draft(user_id)
        if restored_payment:
            pending_payment[user_id] = restored_payment
    if user_id in pending_payment:
        pay_data = pending_payment[user_id]
        pay_action, action_source = await resolve_payment_action(user_id, pay_data)
        if not pay_action:
            await update.message.reply_text(
                "⚠️ ဒီ payment session မှာ Member အသစ်/Renew အမျိုးအစား မသတ်မှတ်နိုင်သေးပါ။\n"
                "Payment မမှားစေရန် ဒီ slip ကို Admin ထံ မပို့သေးပါ။ Member record ကို စစ်ပြီးမှ ဆက်လုပ်ပါ။",
                parse_mode="Markdown")
            return
        if not pay_data.get("action"):
            pay_data["action"] = pay_action
            pay_data["action_source"] = action_source
            pending_payment[user_id] = pay_data
        flow = await validate_payment_flow(user_id, pay_action)
        if not flow.get("ok"):
            if flow.get("reason") == "existing_member_must_renew":
                msg = "🔄 Member record ရှိပြီးသားဖြစ်သောကြောင့် ဒီ slip ကို New Member အဖြစ် မလက်ခံနိုင်ပါ။ `/renew` ကိုသာ သုံးပါ။"
            elif flow.get("reason") == "new_member_must_join":
                msg = "🆕 Member record မရှိသေးသောကြောင့် ဒီ slip ကို Renew အဖြစ် မလက်ခံနိုင်ပါ။ `/newmember` မှ New Member flow ကို သုံးပါ။"
            else:
                msg = "⚠️ Member record ကို စစ်မရသေးသောကြောင့် ဒီ slip ကို Admin ထံ မပို့သေးပါ။"
            await update.message.reply_text(
                msg + "\n\nPayment မှားပို့မိပါက refund/repayment စစ်ဆေးမှုကြာနိုင်ပါတယ်။",
                parse_mode="Markdown")
            return
        if pay_data.get("waiting_slip"):
            await update.message.reply_text("🔍 Payment Slip ဖတ်နေတယ်... ⏳")
            try:
                file       = await photo.get_file()
                file_bytes = bytes(await file.download_as_bytearray())
                slip_info  = await gemini_read_slip(file_bytes)
            except Exception as e:
                logger.error(f"Slip read: {e}")
                slip_info = {}

            amount      = slip_info.get("AMOUNT", "UNKNOWN")
            date_str    = slip_info.get("DATE", "UNKNOWN")
            time_str    = slip_info.get("TIME", "UNKNOWN")
            pay_type    = slip_info.get("TYPE", "UNKNOWN")
            reference   = slip_info.get("TRANSACTION_NO", slip_info.get("REFERENCE", "UNKNOWN"))
            sender      = slip_info.get("SENDER", "UNKNOWN")
            transfer_to = slip_info.get("TRANSFER_TO", "UNKNOWN")
            account_number = slip_info.get("ACCOUNT_NUMBER", "UNKNOWN")
            account_id = slip_info.get("ACCOUNT_ID", "UNKNOWN")
            account_name = slip_info.get("ACCOUNT_NAME", "UNKNOWN")
            from_account_type = slip_info.get("FROM_ACCOUNT_TYPE", "UNKNOWN")
            from_account_number = slip_info.get("FROM_ACCOUNT_NUMBER", account_number)
            from_account_name = slip_info.get("FROM_ACCOUNT_NAME", account_name)
            to_account_type = slip_info.get("TO_ACCOUNT_TYPE", "UNKNOWN")
            to_account_number = slip_info.get("TO_ACCOUNT_NUMBER", "UNKNOWN")
            to_account_name = slip_info.get("TO_ACCOUNT_NAME", "UNKNOWN")
            fee = slip_info.get("FEE", "UNKNOWN")
            purpose = slip_info.get("PURPOSE", "UNKNOWN")
            receiver_ok = ""
            if pay_type == "KPay" and transfer_to != "UNKNOWN":
                if ADMIN_REAL_NAME.lower() in transfer_to.lower():
                    receiver_ok = "✅"
                else:
                    receiver_ok = "⚠️ Admin နာမည် မဟုတ်ဘူး!"

            expected = int(pay_data.get("amount", 0) or 0)
            amount_num = parse_slip_amount(amount)
            if amount_num is None:
                await update.message.reply_text(
                    "⚠️ Slip ထဲက ငွေပမာဏကို ဖတ်မရသေးပါ။\n\n"
                    "ငွေပမာဏ၊ Transaction No. နှင့် Date မြင်ရအောင် ကြည်လင်သော slip ပုံကို ပြန်ပို့ပါ။\n"
                    "ဒီ slip ကို Admin ထံ မပို့သေးပါ။",
                    parse_mode="Markdown")
                return

            slips = pay_data.setdefault("slips", [])
            txn_key = slip_transaction_key(slip_info)
            if txn_key and any(s.get("txn_key") == txn_key for s in slips):
                await update.message.reply_text(
                    f"⚠️ ဒီ Transaction No. `{reference}` ကို အရင်ပို့ထားပြီးသားပါ။\n\n"
                    "တူညီတဲ့ slip ကို ထပ်မပို့ပါနဲ့။ မတူတဲ့ payment slip ကိုသာ ပို့ပါ။",
                    parse_mode="Markdown")
                return

            slips.append({
                "slip_info": slip_info,
                "amount_num": amount_num,
                "txn_key": txn_key,
                "file_bytes": file_bytes,
            })
            total_paid, slip_lines = payment_slip_summary(slips)
            remaining = expected - total_paid
            pay_data["slip_info"] = slip_info
            pay_data["file_bytes"] = file_bytes
            pay_data["total_paid"] = total_paid
            pay_data["userId"] = str(user_id)
            draft_result = await save_payment_draft(pay_data)
            if draft_result.get("status") != "ok":
                logger.error("Payment draft persistence failed user=%s result=%s", user_id, draft_result)
                await update.message.reply_text(
                    "⚠️ Payment data ကို server မှာ မသိမ်းနိုင်သေးပါ။\n"
                    "Admin approval မပို့သေးပါ — ခဏနေရင် slip ကို ပြန်ပို့ပါ။"
                )
                return

            pkg_name = PLAN_NAMES.get(pay_data.get("package", "CH"), "Unknown")
            months = pay_data.get("months", 1)
            flow_label = "New Member" if pay_action == "join" else ("Renew/Upgrade Member" if pay_action == "upgrade" else "Renew Member")
            if pay_action == "join" and flow.get("reason") == "inactive_record_reactivation":
                flow_label = "New Member / Inactive Record Reactivation"
            name = pay_data.get("name", "Unknown")
            username = pay_data.get("username", str(user_id))
            chosen_method = pay_data.get("method", "")
            method_label = PAYMENT_METHOD_INFO.get(
                chosen_method, {}).get("label", chosen_method.upper() if chosen_method else "—")

            # Partial payments stay private with the member until the package price is reached.
            if remaining > 0:
                await update.message.reply_text(
                    f"✅ Slip လက်ခံပြီးပါပြီ။\n\n"
                    f"📦 Package: {pkg_name} — {months} လ\n"
                    f"💵 လွှဲပြီးစုစုပေါင်း: *{total_paid:,} ks*\n"
                    f"💰 လိုအပ်နေသေးသည်: *{remaining:,} ks*\n\n"
                    f"⚠️ ငွေမပြည့်သေးပါ။ ကျန်ငွေကို လွှဲပြီးရင် နောက်ထပ် slip ကို ဒီနေရာမှာပဲ ပို့ပါ။\n"
                    f"Admin ထံ မပို့သေးပါ — စုစုပေါင်း {expected:,} ks ပြည့်မှသာ စစ်ဆေးပေးပါမယ်။",
                    parse_mode="Markdown")
                return

            total_status = "✅ ပြည့်ပြီ" if remaining == 0 else f"⚠️ {abs(remaining):,} ks ပိုနေသည် — Admin စစ်ဆေးရန်"
            slip_block = "\n".join(slip_lines)
            admin_text = (
                f"💰 *{flow_label} Payment Slip — စုစုပေါင်းစစ်ရန်*\n\n"
                f"👤 {name} ({username})\n"
                f"🆔 ID: `{user_id}`\n"
                f"🧭 Flow: *{flow_label}*\n"
                f"📦 Package: {pkg_name} — {months} လ\n"
                f"🎯 ရွေးခဲ့သော method: {method_label}\n"
                f"💵 Expected: {expected:,} ks\n"
                f"💵 Total received: {total_paid:,} ks — {total_status}\n\n"
                f"📋 *Slip အားလုံး:*\n{slip_block}\n"
                f"\n⚠️ Payment app ထဲမှာ Transaction No. တစ်ခုချင်းစီကို စစ်ပြီးမှ Confirm လုပ်ပါ\n"
                f"⚠️ New Member နှင့် Renew payment မရောကြောင်း၊ Amount/Package/Receiver မှန်ကြောင်း စစ်ပါ။ မှားပါက repayment ကြာနိုင်ပါတယ်။"
            )
            admin_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"💬 {name} ကို Message ပို့", url=f"tg://user?id={user_id}")],
                [InlineKeyboardButton("✅ Confirm", callback_data=f"slip_confirm_{user_id}"),
                 InlineKeyboardButton("❌ Reject", callback_data=f"slip_no_{user_id}")],
            ])
            await notify_admins(context, admin_text, reply_markup=admin_kb)
            await notify_admins_with_slips(context, slips)
            await update.message.reply_text(
                "✅ *ငွေပမာဏ ပြည့်ပါပြီ!*\n\n"
                "Slip အားလုံးကို Admin ထံ စစ်ဆေးရန် ပို့ပြီးပါပြီ။\n"
                "Admin အတည်ပြုပြီးမှ Membership active ဖြစ်ပါမယ်။",
                parse_mode="Markdown")
            return

    # ── Admin-only Car/List OCR Mode ──
    # Payment/deposit slip branches above must remain available to members.
    # Any other photo would otherwise fall through to Gemini/Tesseract chassis OCR.
    if user_id not in ADMIN_IDS:
        await update.message.reply_text(
            "🔒 AI Car OCR / Chassis ပုံဖတ်ရှာခြင်းကို Admin account သီးသန့်သာ သုံးနိုင်ပါတယ်။\n\n"
            "Payment slip ဖြစ်ပါက /renew သို့မဟုတ် /upgrade မှာ package နဲ့ payment method ရွေးပြီး "
            "အဲဒီ flow အတွင်း slip ပုံကို ပို့ပါ။",
            parse_mode="Markdown",
        )
        return

    # ── Auction List Mode ──
    if "list" in caption:
        cap_lower = caption.lower()
        caption_klang9 = any(k in cap_lower for k in ["klang9","klang 9","klang","9.2"])
        caption_maesot = any(k in cap_lower for k in ["maesot","mae sot","measot"])
        await update.message.reply_text(f"📋 Auction List ဖတ်နေတယ်... ⏳")
        try:
            file       = await photo.get_file()
            file_bytes = bytes(await file.download_as_bytearray())
            new_cars, detected_loc = await gemini_ocr_auction_list(file_bytes)
        except Exception as e:
            logger.error(f"Auction list: {e}"); new_cars = []; detected_loc = None

        cap_border44 = any(k in cap_lower for k in ["border44","border 44","44gate","44 gate","best border","border-44"])

        if detected_loc in ("Klang9", "MaeSot", "Border44"):
            import_loc = detected_loc
        elif caption_klang9:
            import_loc = "Klang9"
        elif cap_border44:
            import_loc = "Border44"
        elif caption_maesot:
            import_loc = "MaeSot"
        else:
            await update.message.reply_text(
                "⚠️ *Location မသိပါ!*\n\n"
                "Caption မှာ location ထည့်ပြီး ပြန်တင်ပါ:\n"
                "• `klang9 list` → Klang9 Freezone\n"
                "• `maesot list` → MaeSot Freezone\n"
                "• `border44 list` → Best Border-44 Gate\n\n"
                "💡 List ပုံရဲ့ Header ကိုလည်း Gemini ဖတ်ပေးနိုင်တယ်",
                parse_mode='Markdown')
            return

        if import_loc == "Klang9": loc_name = LOC_KLANG9
        elif import_loc == "Border44": loc_name = LOC_BORDER44
        else: loc_name = LOC_MAESOT
        await update.message.reply_text(f"📍 Location: *{loc_name}*", parse_mode='Markdown')

        if not new_cars:
            await update.message.reply_text("⚠️ List ဖတ်မရပါ\n💡 Gemini API limit ကုန်နိုင်တယ်")
            return

        if not SHEET_WEBHOOK:
            await update.message.reply_text("❌ SHEET_WEBHOOK မရှိပါ။ Sheet1 မပြောင်းပါ။")
            return

        sheet_rows = await fetch_sheet1_gviz_rows()
        existing_sheet = []
        for row_obj in sheet_rows:
            cells = row_obj.get("c", []) if isinstance(row_obj, dict) else []
            existing_sheet.append(_gviz_cell(cells, 1))
        staged, duplicates, invalid = stage_auction_list_rows(new_cars, import_loc, existing_sheet)
        if not staged:
            await update.message.reply_text(
                f"⚠️ အသစ်ထည့်ရန် row မရှိပါ။ Duplicate: {len(duplicates)}၊ Invalid: {len(invalid)}\n"
                f"📋 Database: {await get_sheet_car_count()} စီး",
                parse_mode='Markdown')
            return

        # Persist immediately — no confirm tap — but still a real Sheet1 write
        # (unlike the pre-Aug21 behavior, which only updated in-memory CARS
        # and lost every auction list import on the next restart/redeploy).
        saved, failed, already_present = await persist_staged_auction_rows(staged)
        unknown = [row for row in saved if row.get("missing")]
        txt = f"✅ *{loc_name} List Update ပြီး!*\n\n📊 ဖတ်ရ: {len(new_cars)} စီး\n✨ အသစ်: {len(saved)} စီး\n"
        if saved:
            txt += "\n🆕 " + "".join(f"`{row['chassis']}`\n" for row in saved[:10])
            if len(saved) > 10:
                txt += f"... {len(saved) - 10} စီး ထပ်ရှိ\n"
        if unknown:
            txt += f"\n⚠️ *မသေချာ ({len(unknown)} စီး):*\n"
            for row in unknown[:5]:
                txt += f"• `{row['chassis']}` ({row['model']}) — မရ: *{', '.join(row['missing'])}*\n"
            if len(unknown) > 5:
                txt += f"... {len(unknown) - 5} စီး ထပ်ရှိ\n"
        kb = None
        if failed:
            pending_auction_list[user_id] = {
                "location": import_loc,
                "location_name": loc_name,
                "rows": failed,
            }
            txt += f"\n⚠️ Save မအောင်မြင်သေး: {len(failed)} စီး — ပြန်ကြိုးစားရန် Retry ကိုနှိပ်ပါ။\n"
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔁 Retry", callback_data=f"list_save_{user_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"list_cancel_{user_id}"),
            ]])
        txt += f"\n📋 Database: {await get_sheet_car_count()} စီး"
        await update.message.reply_text(txt, parse_mode='Markdown', reply_markup=kb)
        return

    # ── Car Photo Mode ──
    await update.message.reply_text("🔍 Chassis ရှာနေတယ်... ⏳")

    chassis      = extract_chassis_from_text(caption) if caption else None
    price_match  = re.search(r'(?<![A-Z0-9])(\d{4,6})(?![A-Z0-9])', caption.upper()) if caption else None
    price        = int(price_match.group(1)) if price_match else None
    caption_year = 0
    gemini_model = ""; gemini_color = ""; gemini_year = 0; file_bytes = None

    if caption and chassis:
        cap_work = caption.upper()
        cap_work = re.sub(re.escape(chassis.upper()), '', cap_work)
        if price_match:
            cap_work = re.sub(r'(?<![A-Z0-9])' + re.escape(price_match.group(1)) + r'(?![A-Z0-9])', '', cap_work)
        cap_work = cap_work.strip()
        year_m = re.search(r'\b(19|20)\d{2}\b', cap_work)
        if year_m:
            caption_year = normalize_year(year_m.group())
            cap_work = cap_work.replace(year_m.group(), '').strip()
        KNOWN_COLORS = ["PEARL WHITE","DARK BLUE","LIGHT BLUE","LIGHT GREEN",
                        "WHITE","BLACK","SILVER","RED","BLUE","GREEN","YELLOW",
                        "BROWN","ORANGE","GREY","GRAY","GOLD","PURPLE","MAROON"]
        for col in KNOWN_COLORS:
            if col in cap_work:
                gemini_color = col
                cap_work = cap_work.replace(col, '').strip()
                break
        cap_model = re.sub(r'[^A-Z0-9 ]', '', cap_work).strip()
        if cap_model and len(cap_model) >= 2:
            gemini_model = cap_model

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
    sheet_car, sheet_match_source = await lookup_sheet_car_by_candidates(chassis) if chassis else (None, "none")
    if sheet_car:
        # Sheet1 is the persistent auction-list source; prefer its exact row over
        # stale/static in-memory data and preserve the canonical chassis formatting.
        chassis = sheet_car["chassis"]
        car = sheet_car
    image_url = ""
    if chassis and file_bytes:
        image_url = await upload_to_cloudinary(file_bytes, chassis)

    if car:
        car_loc = loc_display(car.get('loc', 'MaeSot'))
    else:
        sheet_loc = None
        if chassis and SHEET_WEBHOOK:
            try:
                async with httpx.AsyncClient(follow_redirects=True) as client:
                    resp = await client.get(
                        f"https://docs.google.com/spreadsheets/d/{os.environ.get('SHEET_ID','')}/gviz/tq?tqx=out:json&sheet=Sheet1",
                        timeout=8)
                raw = resp.text
                import json as _json
                data = _json.loads(raw[raw.index('{'):raw.rindex('}')+1])
                rows = data.get('table',{}).get('rows',[])
                for row in rows:
                    c = row.get('c',[])
                    if len(c) > 1:
                        ch_val = (c[1].get('v','') or '') if c[1] else ''
                        if str(ch_val).upper().strip() == chassis.upper().strip():
                            loc_val = (c[6].get('v','') or '') if len(c) > 6 and c[6] else ''
                            if loc_val:
                                sheet_loc = str(loc_val)
                            break
            except Exception as e:
                # A malformed-JSON failure here almost always means the raw
                # response wasn't the expected gviz payload at all (e.g. a
                # Google sign-in/permission HTML page because the Sheet's
                # public-link sharing changed) — log a slice of the actual
                # response so that's diagnosable without guessing.
                raw_prefix = locals().get('raw', '')[:200]
                logger.error(f"sheet loc lookup: {e} raw_prefix={raw_prefix!r}")

        if sheet_loc:
            car_loc = loc_display(sheet_loc)
        else:
            cap_l = (caption or "").lower()
            if any(k in cap_l for k in ["klang9","klang 9","klang","9.2"]):
                car_loc = LOC_KLANG9
            elif any(k in cap_l for k in ["border44","border 44","44gate","44 gate","best border","border-44"]):
                car_loc = LOC_BORDER44
            else:
                car_loc = LOC_MAESOT

    # Caption fields are explicit admin/user input; vision fields are only a fallback.
    caption_model = gemini_model if caption and chassis else ""
    caption_color = gemini_color if caption and chassis else ""
    vision_model = gemini_model if not (caption and chassis) else ""
    database_model = car.get('model', '') if car else ''
    final_model, model_source, model_needs_review = choose_verified_model(
        chassis or "", database_model, vision_model, caption_model)
    final_color = caption_color or (car.get('color', '-') if car else gemini_color or "-")
    database_year = normalize_year(car.get('year', 0)) if car else 0
    vin_year = decode_vin_year(chassis or "")
    # Prefer explicit caption, verified database, or VIN year. If none of those
    # are available, fall back to the windshield OCR (vision) year — trusted
    # directly like the chassis OCR field, not gated behind Admin retyping.
    final_year, year_source = choose_verified_year(caption_year, database_year, vin_year, gemini_year)
    year_needs_review = year_source == "manual"
    final_chassis = chassis or ""
    match_source = sheet_match_source if sheet_car else ("memory_exact" if car else "none")
    chassis_needs_review = bool(final_chassis and not sheet_car and not car)
    match_warning = (
        "\n✅ Auction list exact match ရပြီးပါပြီ။ Model/Color/Year ကို Sheet row မှ ယူထားသည်။"
        if sheet_car and sheet_match_source == "sheet_exact" else
        "\n✅ OCR prefix မသေချာသော်လည်း Sheet exact row ဖြင့် GP1/GP7 candidate match အတည်ပြုထားသည်။"
        if sheet_car and sheet_match_source == "sheet_candidate" else
        "\n⚠️ Auction list exact row မတွေ့သေးပါ။ Chassis ကို အတည်ပြုပြီးမှ Save လုပ်ပါ။"
        if chassis_needs_review else ""
    )

    missing = []
    if not final_chassis or chassis_needs_review:                 missing.append("Chassis")
    if not final_model or final_model == "UNKNOWN" or model_needs_review:
        missing.append("Model")
    if not final_color or final_color == "-":                     missing.append("Color")
    if not final_year or year_needs_review:                        missing.append("Year")
    model_warning = (
        "\n⚠️ Model ကို AI vision ကသာ ခန့်မှန်းထားသောကြောင့် အတည်ပြုပြီးမှ Save လုပ်ပါ။"
        if model_needs_review else ""
    )
    year_warning = (
        "\n✅ Year ကို ကားပုံ (windshield) OCR မှ ယူထားသည်။"
        if year_source == "vision_review" else
        "\n⚠️ Year ကို OCR result အဖြစ် မယုံကြည်ရသေးပါ။ Database/VIN/Caption/ပုံထဲက Year မှ "
        "ဘာမှမတွေ့သေးသောကြောင့် ကိုယ်တိုင် Year ဖြည့်ပြီးမှ Save လုပ်ပါ။"
        if year_needs_review else ""
    )

    if final_chassis and price:
        pending_photo[user_id] = {
            "user_id":   user_id,
            "chassis":   final_chassis,
            "model":     final_model,
            "color":     final_color,
            "year":      final_year,
            "year_source": year_source,
            "year_needs_review": year_needs_review,
            "model_source": model_source,
            "model_needs_review": model_needs_review,
            "match_source": match_source,
            "price":     price,
            "loc":       car_loc,
            "image_url": image_url,
        }
        warn = (f"\n⚠️ မသေချာ: *{', '.join(dict.fromkeys(missing))}*\n" if missing else "") + match_warning + model_warning + year_warning
        field_labels = {"Chassis":"🔑 Chassis","Model":"🚗 Model","Color":"🎨 Color","Year":"📅 Year"}
        # Edit buttons for ALL fields are always shown (not just ones the bot
        # flags as missing/needs-review) — OCR can misread a field it's
        # otherwise "confident" about (e.g. Model/Year), and the admin must
        # be able to fix just that one field instead of hitting Cancel and
        # re-entering the whole submission.
        fill_btns = [InlineKeyboardButton(
                        f"✏️ {field_labels.get(f,f)} {'ဖြည့်' if f in missing else 'ပြင်'}",
                        callback_data=f"fill_{user_id}_{f.lower()}")
                     for f in ("Chassis", "Model", "Color", "Year")]
        loc_row = [
            InlineKeyboardButton(f"{'✅' if car_loc == LOC_MAESOT else '📍'} MaeSot",    callback_data=f"setloc_{user_id}_MaeSot"),
            InlineKeyboardButton(f"{'✅' if car_loc == LOC_KLANG9 else '📍'} Klang9",    callback_data=f"setloc_{user_id}_Klang9"),
            InlineKeyboardButton(f"{'✅' if car_loc == LOC_BORDER44 else '📍'} Border44", callback_data=f"setloc_{user_id}_Border44"),
        ]
        rows = [fill_btns[:2], fill_btns[2:]]
        rows.append(loc_row)
        rows.append([
            InlineKeyboardButton("✅ Save",    callback_data=f"cs_{user_id}"),
            InlineKeyboardButton("❌ Cancel",  callback_data=f"cc_{user_id}"),
        ])
        kb = InlineKeyboardMarkup(rows)
        await update.message.reply_text(
            f"⚠️ *စစ်ဆေးပါ — မှန်ကန်ပါသလား?*\n\n"
            f"🚗 *{final_model}* ({ys(final_year)})\n"
            f"🔑 `{final_chassis}`\n🎨 {final_color}\n📍 {car_loc}\n💰 ฿{price:,}\n"
            f"{warn}",
            parse_mode='Markdown', reply_markup=kb)
    elif final_chassis:
        pending_photo[user_id] = {
            "user_id":user_id,"chassis":final_chassis,"model":final_model,
            "color":final_color,"year":final_year,"year_source":year_source,
            "year_needs_review":year_needs_review,"model_source":model_source,
            "model_needs_review":model_needs_review,"match_source":match_source,
            "price":None,"loc":car_loc,"image_url":image_url,
        }
        warn = (f"\n⚠️ မသေချာ: *{', '.join(dict.fromkeys(missing))}*\n" if missing else "") + match_warning + model_warning + year_warning
        loc_row2 = [
            InlineKeyboardButton(f"{'✅' if car_loc == LOC_MAESOT else '📍'} MaeSot",    callback_data=f"setloc_{user_id}_MaeSot"),
            InlineKeyboardButton(f"{'✅' if car_loc == LOC_KLANG9 else '📍'} Klang9",    callback_data=f"setloc_{user_id}_Klang9"),
            InlineKeyboardButton(f"{'✅' if car_loc == LOC_BORDER44 else '📍'} Border44", callback_data=f"setloc_{user_id}_Border44"),
        ]
        await update.message.reply_text(
            f"🚗 *{final_model}* ({ys(final_year)})\n🔑 `{final_chassis}`\n"
            f"🎨 {final_color}\n📍 {car_loc}\n{warn}\n💰 ဈေး ရိုက်ထည့်ပါ:\nဥပမာ: `150000`",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([loc_row2]))
    elif chassis:
        guessed = final_model or guess_model_from_chassis(chassis)
        if not guessed or guessed == "UNKNOWN":
            guessed = guess_model_from_chassis(chassis)
        display_color = final_color if final_color and final_color != "-" else (gemini_color or "-")
        display_year  = final_year
        if price:
            pending_photo[user_id] = {
                "user_id":user_id,"chassis":chassis,"model":guessed,
                "color":display_color,"year":display_year,"year_source":"manual",
                "year_needs_review":True,"model_source":model_source,
                "model_needs_review":model_needs_review,"price":price,"loc":LOC_MAESOT,"image_url":image_url,
            }
            review_buttons = []
            if chassis_needs_review:
                review_buttons.append(InlineKeyboardButton("✏️ Chassis ဖြည့်", callback_data=f"fill_{user_id}_chassis"))
            if model_needs_review:
                review_buttons.append(InlineKeyboardButton("✏️ Model ဖြည့်", callback_data=f"fill_{user_id}_model"))
            review_row = review_buttons
            kb_rows = [review_row] if review_row else []
            kb_rows.append([
                InlineKeyboardButton("✅ မှန်တယ် Save",    callback_data=f"cs_{user_id}"),
                InlineKeyboardButton("❌ မှားတယ် Cancel", callback_data=f"cc_{user_id}"),
            ])
            kb = InlineKeyboardMarkup(kb_rows)
            await update.message.reply_text(
                f"⚠️ *Checklist မှာ မပါဘူး*\n\n🚗 ခန့်မှန်း: *{guessed}* ({ys(display_year)})\n"
                f"🔑 `{chassis}`\n🎨 {display_color}\n💰 ฿{price:,}\n\n"
                f"✅ မှန်ရင် *Save* နှိပ်ပါ",
                parse_mode='Markdown', reply_markup=kb)
        else:
            pending_photo[user_id] = {
                "user_id":user_id,"chassis":chassis,"model":guessed,
                "color":display_color,"year":display_year,"year_source":"manual",
                "year_needs_review":True,"model_source":model_source,
                "model_needs_review":model_needs_review,"price":None,"loc":LOC_MAESOT,"image_url":image_url,
            }
            msg = (f"⚠️ Checklist မှာ မပါဘူး\n\n🚗 ခန့်မှန်း: *{guessed}* ({ys(display_year)})\n"
                   f"🔑 `{chassis}`\n🎨 {display_color}\n\n💰 ဈေး ရိုက်ထည့်ပါ:\nဥပမာ: `150000`"
                   if guessed and guessed != "UNKNOWN"
                   else f"⚠️ Chassis: `{chassis}`\nChecklist မှာ မပါဘူး — ဈေး ထည့်ပါ:\nဥပမာ: `150000`")
            await update.message.reply_text(msg, parse_mode='Markdown')
    else:
        await update.message.reply_text(
            "⚠️ Chassis ဖတ်မရပါ\nကိုယ်တိုင် ထည့်ပါ:\n`/price [chassis] [ဈေး]`", parse_mode='Markdown')

# ── Proxy Chat Filter ─────────────────────────────────
def proxy_filter(text: str):
    mm_digits = str.maketrans('၀၁၂၃၄၅၆၇၈၉', '0123456789')
    normalized = text.translate(mm_digits)
    digits_only = re.sub(r'[\s\-\.]', '', normalized)
    if re.search(r'\+?0?[6-9]\d{7,11}', digits_only):
        return True, "ဖုန်းနံပါတ် ပေးပို့ခြင်း တားမြစ်ထားသည်"
    if re.search(r'0\s*9[\d\s]{8,}', normalized):
        return True, "ဖုန်းနံပါတ် ပေးပို့ခြင်း တားမြစ်ထားသည်"
    if re.search(r'@[a-zA-Z0-9_]{4,}', text):
        return True, "Telegram Username ပေးပို့ခြင်း တားမြစ်ထားသည်"
    if re.search(r'(https?://|www\.|t\.me/|wa\.me/|line\.me/)', text, re.IGNORECASE):
        return True, "Link ပေးပို့ခြင်း တားမြစ်ထားသည်"
    if re.search(r'facebook\.com|fb\.com|fb\.me|instagram\.com|tiktok\.com', text, re.IGNORECASE):
        return True, "Social Media link ပေးပို့ခြင်း တားမြစ်ထားသည်"
    if re.search(r'\b(line\s?id|viber|whatsapp|zalo)\b', text, re.IGNORECASE):
        return True, "Contact info ပေးပို့ခြင်း တားမြစ်ထားသည်"
    if re.search(r'တိုက်နံပါတ်|အခန်းနံပါတ်|ရပ်ကွက်|မြို့နယ်|တိုင်းဒေသ|ပြည်နယ်|နေရပ်လိပ်စာ|နေထိုင်ရာ', text):
        return True, "လိပ်စာ ပေးပို့ခြင်း တားမြစ်ထားသည်"
    if re.search(r'\b(street|road|lane|avenue|st\.|address|district|township|quarter)\b', text, re.IGNORECASE):
        return True, "လိပ်စာ ပေးပို့ခြင်း တားမြစ်ထားသည်"
    return False, ""

# ── Chat Log Helper ──────────────────────────────────
async def log_chat_message(req_id: str, sender_id: str, sender_label: str, msg_type: str, content: str):
    if not SHEET_WEBHOOK:
        return
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            await client.post(SHEET_WEBHOOK, json={
                "action":      "saveChatLog",
                "reqId":       req_id,
                "senderId":    sender_id,
                "senderLabel": sender_label,
                "msgType":     msg_type,
                "content":     content[:500],
                "timestamp":   datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
            }, timeout=40)
    except Exception as e:
        logger.warning(f"log_chat_message: {e}")

async def chatlog_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်")
        return
    if not context.args:
        await update.message.reply_text("❌ Format: `/chatlog R123456`", parse_mode='Markdown')
        return
    req_id = context.args[0].strip().upper()
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.post(SHEET_WEBHOOK, json={
                "action": "getChatLog",
                "reqId":  req_id,
            }, timeout=40)
        logs = resp.json().get("logs", [])
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")
        return
    if not logs:
        await update.message.reply_text(f"📋 `{req_id}` — Chat log မရှိသေးပါ", parse_mode='Markdown')
        return
    txt = f"📋 *Chat Log — `{req_id}`*\n({'─'*20})\n\n"
    for log in logs[-50:]:
        ts  = log.get("timestamp", "")
        frm = log.get("senderLabel", log.get("from","?"))
        msg = log.get("content", log.get("message",""))
        txt += f"🕐 `{ts}`\n👤 {frm}:\n{msg}\n\n"
    chunks = [txt[i:i+4000] for i in range(0, len(txt), 4000)]
    for chunk in chunks:
        await update.message.reply_text(chunk, parse_mode='Markdown')

# ── handle_text ──────────────────────────────────────
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text    = update.message.text.strip()

    str_uid = str(user_id)

    if "JAN Broker T&C သဘောတူပါသည်" in text:
        brokers = await get_brokers()
        broker  = next((b for b in brokers if b.get("telegramId") == str_uid), None)
        if broker:
            if broker.get("status") == "KICKED":
                await update.message.reply_text("🚫 Account ပိတ်သိမ်းထားပြီ — Admin ကို ဆက်သွယ်ပါ")
                return
            await update_broker(str_uid, status="FREE")
            await update.message.reply_text(
                f"✅ *T&C လက်ခံပြီ!*\n\n"
                f"🆔 Broker #{broker['brokerId']}\n"
                f"🟢 Status: FREE — Request လက်ခံနိုင်ပြီ\n\n"
                f"Available ဖြစ်ကြောင်း: /available\n"
                f"Busy ဖြစ်ရင်: /busy\n"
                f"Request လက်ခံရန်: `/accept [ReqID]`",
                parse_mode='Markdown')
            await notify_admins(context,
                f"✅ *Broker T&C လက်ခံပြီ*\n\n"
                f"👤 @{update.effective_user.username or str_uid}\n"
                f"🆔 #{broker['brokerId']}\n"
                f"🟢 Status: FREE")
        else:
            await update.message.reply_text("❌ Broker အဖြစ် မှတ်ပုံမတင်ရသေးဘူး — Admin ကို ဆက်သွယ်ပါ")
        return

    cust_session = next(
        ((sid, s) for sid, s in proxy_sessions.items()
         if str(s.get("customerId","")) == str_uid and s.get("status") == "ACTIVE"),
        None
    )
    # FIXED: collect ALL broker sessions
    broker_sessions = [
        (sid, s) for sid, s in proxy_sessions.items()
        if str(s.get("brokerId","")) == str_uid and s.get("status") == "ACTIVE"
    ]

    if cust_session:
        sid, session = cust_session
        broker_tg_id = session.get("brokerId")
        req_id_c = session.get("reqId", "")

        if req_id_c.startswith("A") and not session.get("deposit_paid", False):
            return

        blocked, reason = proxy_filter(text)
        if blocked:
            await update.message.reply_text(
                f"⚠️ *Message Block ဖြစ်သွားတယ်*\n\n❌ {reason}\nBot ထဲမှာပဲ ဆက်သွယ်ရမည်",
                parse_mode='Markdown')
            return
        if broker_tg_id:
            try:
                req_id_c = session.get("reqId", "")
                close_kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔚 Close Chat", callback_data=f"closechat_{req_id_c}_customer")
                ]])
                await context.bot.send_message(
                    chat_id=int(broker_tg_id),
                    text=f"💬 *Customer #{req_id_c}:*\n\n{text}",
                    parse_mode='Markdown')
                await log_chat_message(req_id_c, str_uid, "Customer", "text", text)
                await update.message.reply_text(
                    "✅ ပို့ပြီ",
                    reply_markup=close_kb)
            except Exception as e:
                logger.error(f"proxy relay C→B: {e}")
                await update.message.reply_text("❌ Broker ကို မပို့နိုင်ဘူး")
        return

    if broker_sessions:
        blocked, reason = proxy_filter(text)
        if blocked:
            await update.message.reply_text(
                f"⚠️ *Message Block ဖြစ်သွားတယ်*\n\n❌ {reason}\nBot ထဲမှာပဲ ဆက်သွယ်ရမည်",
                parse_mode='Markdown')
            return
        if len(broker_sessions) == 1:
            sid, session = broker_sessions[0]
            customer_id = session.get("customerId")
            if customer_id:
                try:
                    broker_obj  = session.get("brokerObj", {})
                    broker_id   = broker_obj.get("brokerId", "B???")
                    req_id_b    = session.get("reqId", "")
                    close_kb_b  = InlineKeyboardMarkup([[
                        InlineKeyboardButton("🔚 Close Chat", callback_data=f"closechat_{req_id_b}_broker")
                    ]])
                    await context.bot.send_message(
                        chat_id=int(customer_id),
                        text=f"💬 *Broker #{broker_id}:*\n\n{text}",
                        parse_mode='Markdown')
                    await log_chat_message(req_id_b, str_uid, f"Broker#{broker_id}", "text", text)
                    await update.message.reply_text("✅ ပို့ပြီ", reply_markup=close_kb_b)
                except Exception as e:
                    logger.error(f"proxy relay B→C: {e}")
                    await update.message.reply_text("❌ Customer ကို မပို့နိုင်ဘူး")
        else:
            await broker_ask_target(
                update.message, context,
                broker_tg_id=str_uid,
                broker_sessions=broker_sessions,
                text=text, is_photo=False)
        return

    if user_id in pending_request:
        handled = await handle_request_qa(update, context)
        if handled: return

    if user_id in pending_edit:
        edit    = pending_edit.pop(user_id)
        chassis = edit["chassis"]
        field   = edit["field"]

        if chassis == "__photo__":
            photo_uid = edit.get("photo_uid", user_id)
            if photo_uid not in pending_photo:
                await update.message.reply_text("❌ Data ကုန်သွားပြီ — ပုံ ပြန်တင်ပါ")
                return
            pdata = pending_photo[photo_uid]
            val   = text.strip()
            if field == "chassis":
                corrected_chassis = canonicalize_chassis(val)
                compact_chassis = normalize_chassis_key(corrected_chassis)
                if not corrected_chassis or not re.fullmatch(r"[A-Z0-9]{3,20}-[A-Z0-9]{4,8}", corrected_chassis):
                    await update.message.reply_text(
                        "❌ Chassis format မမှန်ပါ။ ဥပမာ: `GP1-106680`",
                        parse_mode='Markdown')
                    pending_edit[user_id] = edit
                    return
                pdata["chassis"] = corrected_chassis
                pdata["chassis_source"] = "manual"
                sheet_car, sheet_match_source = await lookup_sheet_car_by_candidates(corrected_chassis)
                if sheet_car:
                    pdata["chassis"] = sheet_car["chassis"]
                    pdata["model"] = sheet_car.get("model", pdata.get("model", "UNKNOWN"))
                    pdata["color"] = sheet_car.get("color", pdata.get("color", "-"))
                    pdata["year"] = sheet_car.get("year", pdata.get("year", 0))
                    pdata["year_source"] = "database"
                    pdata["year_needs_review"] = not bool(normalize_year(pdata.get("year")))
                    pdata["loc"] = loc_display(sheet_car.get("location", pdata.get("loc", LOC_MAESOT)))
                    pdata["model_source"] = "database"
                    pdata["model_needs_review"] = False
                    pdata["match_source"] = sheet_match_source
                else:
                    known_model = guess_model_from_chassis(corrected_chassis)
                    if known_model != "UNKNOWN":
                        pdata["model"] = known_model
                        pdata["model_source"] = "chassis_prefix"
                        pdata["model_needs_review"] = False
                    else:
                        pdata["model_needs_review"] = True
                    pdata["match_source"] = "none"
            elif field == "year":
                parsed_year = normalize_year(val)
                if not parsed_year:
                    await update.message.reply_text(
                        "❌ Year မမှန်ပါ။ 1980 မှ လက်ရှိနှစ်အထိ ဂဏန်း ၄ လုံး ထည့်ပါ (ဥပမာ: `2013`)",
                        parse_mode='Markdown')
                    pending_edit[user_id] = edit; return
                pdata["year"] = parsed_year
                pdata["year_source"] = "manual"
                pdata["year_needs_review"] = False
            elif field == "color":
                pdata["color"] = val.upper()
            elif field == "model":
                pdata["model"] = normalize_model_name(val) or val.upper()
                pdata["model_source"] = "manual"
                pdata["model_needs_review"] = False
            pending_photo[photo_uid] = pdata
            m2 = []
            if not pdata.get("chassis"):                                  m2.append("Chassis")
            if not pdata.get("model") or pdata["model"] == "UNKNOWN" or pdata.get("model_needs_review"): m2.append("Model")
            if not pdata.get("color") or pdata["color"] == "-":       m2.append("Color")
            if not pdata.get("year"):                                   m2.append("Year")
            field_labels = {"Chassis":"🔑 Chassis","Model":"🚗 Model","Color":"🎨 Color","Year":"📅 Year"}
            fill_btns = [InlineKeyboardButton(
                            f"✏️ {field_labels.get(f,f)} {'ဖြည့်' if f in m2 else 'ပြင်'}",
                            callback_data=f"fill_{photo_uid}_{f.lower()}")
                         for f in ("Chassis", "Model", "Color", "Year")]
            rows = [fill_btns[:2], fill_btns[2:]]
            rows.append([
                InlineKeyboardButton("✅ Save",   callback_data=f"cs_{photo_uid}"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"cc_{photo_uid}"),
            ])
            warn = f"\n⚠️ မသေချာ: *{', '.join(m2)}*\n" if m2 else ""
            await update.message.reply_text(
                f"⚠️ *စစ်ဆေးပါ*\n\n"
                f"🚗 *{pdata['model']}* ({ys(pdata.get('year',0))})\n"
                f"🔑 `{pdata['chassis']}`\n🎨 {pdata['color']}\n"
                f"📍 {pdata.get('loc','')}\n💰 ฿{pdata['price']:,}\n{warn}",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup(rows))
            return

        car = find_by_chassis(chassis)
        if not car:
            await update.message.reply_text(f"❌ `{chassis}` မတွေ့ပါ", parse_mode='Markdown')
            return

        if field == "price":
            # "price" is never read off the CARS entry anywhere (/find,
            # /history, /list all read PRICE_HISTORY) — writing car["price"]
            # here used to be a silent no-op. Route it through save_price()
            # the same way /price does, so the edit is actually visible.
            try:
                new_val = int(text.replace(",","").replace(" ",""))
            except:
                await update.message.reply_text("❌ ဂဏန်းသက်သက်သာ ရိုက်ပါ\nဥပမာ: `150000`", parse_mode='Markdown')
                pending_edit[user_id] = edit
                return
            if new_val <= 0:
                await update.message.reply_text("❌ ဈေးက 0 ထက် ကြီးရပါမယ်", parse_mode='Markdown')
                pending_edit[user_id] = edit
                return
            user_name = update.effective_user.first_name or "Unknown"
            loc       = loc_display(car.get('loc', 'MaeSot'))
            entry     = await save_price(car['chassis'], car['model'], car['color'],
                                          car.get('year', 0), new_val, user_name, location=loc)
            await update.message.reply_text(
                f"✅ *{car['chassis']}* ဈေးအသစ် ထည့်ပြီး\n💰 ฿{new_val:,}\n📅 {entry['date']}",
                parse_mode='Markdown')
            return
        elif field == "color":
            new_val = text.upper().strip()
            display = new_val
        elif field == "model":
            new_val = normalize_model_name(text) or text.upper().strip()
            display = new_val
        else:
            return

        # Mutate the CARS entry already found above via normalized chassis
        # matching — re-searching CARS with an exact-string comparison here
        # (the old code) could miss it on a dash/space format difference and
        # silently no-op while still telling the admin it was edited.
        car[field] = new_val

        if SHEET_WEBHOOK:
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.post(SHEET_WEBHOOK, json={
                        "action": "updateCar", "serverKey": SHEET_SERVER_KEY,
                        "chassis": car['chassis'],
                        "field": field,
                        "value": str(new_val),
                    }, timeout=40, follow_redirects=True)
            except Exception as e:
                logger.error(f"updateCar webhook: {e}")

        await update.message.reply_text(
            f"✅ *{car['chassis']}* ပြင်ပြီး\n📝 {field.upper()}: *{display}*",
            parse_mode='Markdown')
        return

    if user_id in pending_photo:
        data = pending_photo[user_id]
        if data.get('price') is None and re.match(r'^[\d,]+$', text.replace(' ','')):
            try:
                price            = int(text.replace(',','').replace(' ',''))
                data['price']    = price
                pending_photo[user_id] = data
                field_labels = {"chassis":"🔑 Chassis","model":"🚗 Model","color":"🎨 Color","year":"📅 Year"}
                fill_btns = [InlineKeyboardButton(
                                f"✏️ {field_labels[f]} {'ဖြည့်' if data.get(f+'_needs_review') else 'ပြင်'}",
                                callback_data=f"fill_{user_id}_{f}")
                             for f in ("chassis", "model", "color", "year")]
                kb_rows = [fill_btns[:2], fill_btns[2:]]
                kb_rows.append([
                    InlineKeyboardButton("✅ မှန်တယ် Save",    callback_data=f"cs_{user_id}"),
                    InlineKeyboardButton("❌ မှားတယ် Cancel", callback_data=f"cc_{user_id}"),
                ])
                kb = InlineKeyboardMarkup(kb_rows)
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
    # membership_approval_patch may acknowledge protected payment callbacks
    # before restoring the durable draft. Avoid answering the same callback twice.
    if not getattr(query, "_jacc_callback_answered", False):
        await query.answer()
        try:
            setattr(query, "_jacc_callback_answered", True)
        except Exception:
            pass
    data  = query.data

    # ── 🚗 Buying Car 10 Day Promo ──
    if data.startswith("buying_car_"):
        uid_str  = data.replace("buying_car_", "")
        caller   = str(query.from_user.id)
        if caller != uid_str:
            await query.answer("❌ သင့် button မဟုတ်ဘူး", show_alert=True)
            return
        user_id_int = int(uid_str)
        username    = query.from_user.username or query.from_user.first_name or "Unknown"

        promo_info = await check_promo10d_eligibility(uid_str)
        if not promo_info.get("eligible") or promo_info.get("active"):
            await query.answer("❌ Promo မရနိုင်ပါ", show_alert=True)
            return

        ok = await activate_promo10d(context, user_id_int, username)
        if not ok:
            await query.edit_message_text("❌ Promo activate မဖြစ်ဘူး — Admin ကို ဆက်သွယ်ပါ")
            return

        expire_date = (datetime.now() + timedelta(days=10)).strftime("%d/%m/%Y")

        try:
            invite = await context.bot.create_chat_invite_link(
                chat_id=int(CHANNEL_ID),
                member_limit=1,
                expire_date=int((datetime.now() + timedelta(days=10)).timestamp()))
            invite_url = invite.invite_link
        except Exception as e:
            logger.error(f"promo10d invite: {e}")
            invite_url = ""

        msg = (f"🎉 *10 Day Free Promo ရပြီ!*\n\n"
               f"⏳ ကုန်ဆုံးရက်: `{expire_date}`\n\n"
               f"✅ ခွင့်ပြုချက်:\n"
               f"• ကားဈေးကြည့်ရန်\n"
               f"• Broker နှင့် ဆက်သွယ်ရန်\n"
               f"• /carrequest (၂ ကြိမ်သာ)\n\n"
               f"⚠️ 10 ရက်အတွင်း Order မတင်ပါက Kick ခံရမည်\n\n")
        kb_rows = []
        if invite_url:
            kb_rows.append([InlineKeyboardButton("📢 Channel ဝင်ရန်", url=invite_url)])
        kb_rows.append([InlineKeyboardButton("🚗 ကားတောင်းဆိုရန်", callback_data=f"reqtype_auction_{uid_str}")])

        await query.edit_message_text(msg, parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(kb_rows))

        await notify_admins(context,
            f"🎁 *10 Day Promo အသစ်*\n\n"
            f"👤 @{username} (ID: `{uid_str}`)\n"
            f"⏳ ကုန်ဆုံးရက်: {expire_date}")
        return

    # ── 🔚 Close Chat Button ──
    if data.startswith("closechat_"):
        parts    = data.split("_")
        req_id   = parts[1]
        who      = parts[2] if len(parts) > 2 else "unknown"
        session  = proxy_sessions.get(req_id)
        if not session:
            await query.answer("❌ Session မတွေ့ပါ — ပြီးသွားပြီ ဖြစ်နိုင်တယ်", show_alert=True)
            return

        broker_tg_id  = session.get("brokerId")
        customer_id   = session.get("customerId")
        broker_obj    = session.get("brokerObj", {})
        broker_id_val = broker_obj.get("brokerId", "?")
        closer_id     = str(query.from_user.id)

        if closer_id not in (str(broker_tg_id), str(customer_id)):
            await query.answer("❌ ဒီ Session က သင့်ဟာ မဟုတ်ပါ", show_alert=True)
            return

        proxy_sessions.pop(req_id, None)
        new_broker_status = recalc_broker_status(broker_tg_id)
        await update_broker(broker_tg_id, status=new_broker_status)
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                await client.post(SHEET_WEBHOOK, json={
                    "action": "updateRequest",
                    "reqId":  req_id,
                    "status": "CLOSED",
                }, timeout=40)
        except Exception as e:
            logger.error(f"closechat updateRequest: {e}")

        who_label = "Customer" if who == "customer" else "Broker"
        await query.edit_message_text(
            f"🔚 *Chat ပိတ်ပြီ*\n\n🆔 `{req_id}`\n{who_label} မှ ပိတ်လိုက်သည်",
            parse_mode='Markdown')

        try:
            if who == "customer" and broker_tg_id:
                await context.bot.send_message(
                    chat_id=int(broker_tg_id),
                    text=f"🔚 *Chat ပိတ်ပြီ*\n\n🆔 `{req_id}`\nCustomer မှ Chat ပိတ်လိုက်သည်",
                    parse_mode='Markdown')
            elif who == "broker" and customer_id:
                await context.bot.send_message(
                    chat_id=int(customer_id),
                    text=f"🔚 *Chat ပိတ်ပြီ*\n\n🆔 `{req_id}`\nBroker မှ Chat ပိတ်လိုက်သည်",
                    parse_mode='Markdown')
        except Exception as e:
            logger.error(f"closechat notify: {e}")

        if customer_id:
            try:
                rating_kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton("⭐1", callback_data=f"rate_1_{req_id}"),
                     InlineKeyboardButton("⭐2", callback_data=f"rate_2_{req_id}"),
                     InlineKeyboardButton("⭐3", callback_data=f"rate_3_{req_id}")],
                    [InlineKeyboardButton("⭐4", callback_data=f"rate_4_{req_id}"),
                     InlineKeyboardButton("⭐5", callback_data=f"rate_5_{req_id}")],
                ])
                await context.bot.send_message(
                    chat_id=int(customer_id),
                    text=f"🌟 *Broker ကို Rate လုပ်ပေးပါ*\n\n"
                         f"🆔 Request: `{req_id}`\n\n"
                         f"⭐1 = ညံ့ | ⭐3 = ပုံမှန် | ⭐5 = အကောင်းဆုံး",
                    parse_mode='Markdown',
                    reply_markup=rating_kb)
                pending_rating[str(customer_id)] = {
                    "reqId":      req_id,
                    "brokerId":   broker_id_val,
                    "brokerTgId": broker_tg_id,
                }
            except Exception as e:
                logger.error(f"closechat rating: {e}")
        return

    # ── 📋 Report Form ──
    if data.startswith("report_"):
        parts      = data.split("_")
        report_type = parts[1]
        req_id     = "_".join(parts[2:])
        rater_id   = str(query.from_user.id)

        rate_info = pending_rating.get(rater_id, {})
        broker_tg_id  = rate_info.get("brokerTgId", "")
        broker_id_val = rate_info.get("brokerId", "?")

        if report_type == "ok":
            await query.edit_message_text(
                f"✅ *ကျေးဇူးတင်ပါသည်!*\n\n"
                f"🆔 `{req_id}`\n\n"
                f"Feedback ပေးသည့်အတွက် ကျေးဇူးတင်ပါသည် 🙏",
                parse_mode='Markdown')
            return

        report_labels = {
            "incomplete": "⚠️ လုပ်ငန်းမပြီးစုံ",
            "wrongcar":   "🚗 ကားမမှန်ကန်",
            "nosearch":   "❌ ကားမရှာပေ",
        }
        report_label = report_labels.get(report_type, report_type)

        await query.edit_message_text(
            f"📋 *Report တင်ပြီ*\n\n"
            f"🆔 `{req_id}`\n"
            f"အကြောင်းရင်း: {report_label}\n\n"
            f"Broker ကို 1 Month Temporary Ban ချမှတ်ပြီ",
            parse_mode='Markdown')

        if broker_tg_id:
            ban_until = (datetime.now() + timedelta(days=30)).strftime("%d/%m/%Y")
            await update_broker(broker_tg_id, status="BANNED")
            try:
                async with httpx.AsyncClient(follow_redirects=True) as client:
                    await client.post(SHEET_WEBHOOK, json={
                        "action":    "updateBroker",
                        "telegramId": broker_tg_id,
                        "status":    "TEMP_BAN",
                        "banUntil":  ban_until,
                    }, timeout=40)
            except Exception as e:
                logger.error(f"report temp ban: {e}")

            try:
                await context.bot.send_message(
                    chat_id=int(broker_tg_id),
                    text=f"🚨 *Report တင်ခံရပြီ*\n\n"
                         f"🆔 Request: `{req_id}`\n"
                         f"အကြောင်းရင်း: {report_label}\n\n"
                         f"⏳ 1 Month Temporary Ban ချမှတ်ခြင်းခံရပြီ\n"
                         f"(ကုန်ဆုံးရက်: {ban_until})\n\n"
                         f"မကျေနပ်ပါက သက်သေများ စုဆောင်းပြီး\n"
                         f"Admin ထံ Appeal တင်နိုင်ပါသည် 👇",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("📩 Admin ကို Appeal တင်ရန်",
                                            url=f"https://t.me/{ADMIN_USERNAME}")
                    ]]))
            except Exception as e:
                logger.error(f"report broker notify: {e}")

        await notify_admins(context,
            f"🚨 *Broker Report တင်ခံရပြီ*\n\n"
            f"🆔 Request: `{req_id}`\n"
            f"👷 Broker: #{broker_id_val}\n"
            f"အကြောင်းရင်း: {report_label}\n"
            f"⏳ 1 Month Temp Ban ချမှတ်ပြီ")
        return

    # ── ✅ Customer T&C Agree / Disagree ──
    if data.startswith("cust_tc_agree_"):
        user_id_str = data.replace("cust_tc_agree_", "")
        if str(query.from_user.id) != user_id_str:
            await query.answer("❌ သင့် button မဟုတ်ဘူး", show_alert=True)
            return
        user_id_int = int(user_id_str)
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🏆 လေလံဆွဲရန်", callback_data=f"reqtype_auction_{user_id_int}"),
            InlineKeyboardButton("🔍 ကားရှာရန်",   callback_data=f"reqtype_search_{user_id_int}"),
        ]])
        await query.edit_message_text(
            "✅ *သဘောတူပြီ!*\n\n"
            "🚗 *ကားဝန်ဆောင်မှု*\n\n"
            "🏆 *လေလံဆွဲရန်* — Auction ကားဝယ်ယူရန် (Deposit ฿20,000 လိုအပ်)\n"
            "🔍 *ကားရှာရန်* — ကားရှာဖွေပေးမည်\n\n"
            "ဝန်ဆောင်မှု ရွေးချယ်ပါ 👇",
            parse_mode='Markdown',
            reply_markup=kb)
        return

    if data.startswith("cust_tc_disagree_"):
        user_id_str = data.replace("cust_tc_disagree_", "")
        if str(query.from_user.id) != user_id_str:
            await query.answer("❌ သင့် button မဟုတ်ဘူး", show_alert=True)
            return
        await query.edit_message_text(
            "❌ *သဘောမတူဘူး*\n\n"
            "Customer T&C သဘောမတူသောကြောင့် ကားရှာ Service ဆက်လုပ်၍ မရပါ\n\n"
            "သဘောပြောင်းပါက /carrequest ထပ်နှိပ်ပါ",
            parse_mode='Markdown')
        return

    # ── ✅ T&C Agree / Disagree ──
    if data.startswith("tc_agree_"):
        user_id = data.replace("tc_agree_", "")
        if str(query.from_user.id) != user_id:
            await query.answer("❌ သင့် button မဟုတ်ဘူး", show_alert=True)
            return
        brokers = await get_brokers()
        broker  = next((b for b in brokers if b.get("telegramId") == user_id), None)
        broker_id_val = broker["brokerId"] if broker else "?"
        await query.edit_message_text(
            f"✅ *သဘောတူပြီ!*\n\n"
            f"🆔 Broker ID: `{broker_id_val}`\n\n"
            f"Japan Auction Car Checker T&C ကို သဘောတူပြီး Broker အဖြစ် စတင်ပြီ 🎉\n\n"
            f"Request လက်ခံဖို့ /available နှိပ်ပါ",
            parse_mode='Markdown')
        return

    if data.startswith("tc_disagree_"):
        user_id = data.replace("tc_disagree_", "")
        if str(query.from_user.id) != user_id:
            await query.answer("❌ သင့် button မဟုတ်ဘူး", show_alert=True)
            return
        await query.edit_message_text(
            f"❌ *သဘောမတူဘူး*\n\n"
            f"T&C သဘောမတူသောကြောင့် Broker အဖြစ် ဆက်လုပ်၍ မရပါ\n\n"
            f"သဘောပြောင်းပါက Admin ကို ဆက်သွယ်ပါ",
            parse_mode='Markdown')
        return

    # ── 👷 Broker Start Button ──
    if data.startswith("brokerstart_"):
        tg_id   = data.replace("brokerstart_", "")
        user_id = str(query.from_user.id)
        if user_id != tg_id:
            await query.answer("❌ သင့် button မဟုတ်ဘူး", show_alert=True)
            return
        brokers = await get_brokers()
        broker  = next((b for b in brokers if b.get("telegramId") == user_id), None)
        if not broker:
            await query.answer("❌ Broker အဖြစ် မှတ်ပုံမတင်ရသေးဘူး", show_alert=True)
            return
        broker_id_val = broker['brokerId']
        tc_text = (
            f"🤝 *Japan Auction Car Checker T&C*\n\n"
            f"🆔 Broker ID: `{broker_id_val}`\n\n"
            f"အောက်ပါ စည်ကမ်းများကို သဘောတူကြောင်း confirm လုပ်ပါ:\n\n"
            f"① တစ်ချိန်တည်း Customer ၁ ယောက်သာ\n"
            f"② Bot ထဲမှာပဲ ဆက်သွယ်ရမည်\n"
            f"③ Condition Report မှန်ကန်စွာ ပေးရမည်\n"
            f"④ Photo အနည်းဆုံး ၁၀ ပုံ ပေးရမည်\n"
            f"⑤ ကားနဲ့ ပတ်သက်ပြီး အမှားအယွင်း မဖြစ်အောင် လုပ်ဆောင်ပေးရမည်\n"
            f"⑥ အမှားအယွင်း ဖြစ်ပေါ်ပါက Admin စိစစ်၍ Admin ၏ အဆုံးအဖြတ်ကို လိုက်နာရမည်\n"
            f"⑦ Platform ပြင်ပ Deal = Lifetime Ban\n"
            f"⑧ Rating 1 × 3 = Permanent Ban\n\n"
            f"သဘောတူမတူ အောက်က Button နှိပ်ပါ 👇"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ သဘောတူပါတယ်", callback_data=f"tc_agree_{user_id}"),
            InlineKeyboardButton("❌ သဘောမတူပါ",    callback_data=f"tc_disagree_{user_id}"),
        ]])
        await query.message.reply_text(tc_text, parse_mode='Markdown', reply_markup=kb)
        await query.edit_message_reply_markup(reply_markup=None)
        return

    # ── 📦 Tracking Status Update ──
    if data.startswith("track_"):
        parts    = data.split("_")
        svc_t    = parts[1]
        status   = parts[2]
        req_id   = "_".join(parts[3:])
        session  = proxy_sessions.get(req_id)
        if not session:
            await query.answer("❌ Session မတွေ့ပါ — ပြီးသွားပြီ ဖြစ်နိုင်တယ်", show_alert=True)
            return
        broker_id  = session.get("brokerId")
        customer_id = session.get("customerId")
        if str(query.from_user.id) != str(broker_id):
            await query.answer("❌ သင့် Session မဟုတ်ဘူး", show_alert=True)
            return
        noti_text = TRACKING_NOTI.get(status, status)
        if customer_id:
            try:
                await context.bot.send_message(
                    chat_id=int(customer_id),
                    text=(f"📦 *Status Update*\n\n"
                          f"🆔 `{req_id}`\n"
                          f"{noti_text}\n\n"
                          f"Status စစ်ရန်: /mystatus"),
                    parse_mode='Markdown')
            except Exception as e:
                logger.error(f"tracking noti: {e}")
        svc_type_full = "auction" if svc_t == "A" else "search"
        svc_label     = "🏆 Auction" if svc_t == "A" else "🔍 ကားရှာ"
        await query.edit_message_text(
            f"📦 *Status Tracking — {svc_label}*\n\n"
            f"🆔 `{req_id}`\n"
            f"✅ ပို့ပြီး: {noti_text}\n\n"
            f"နောက်တဆင့် Button နှိပ်ပါ 👇",
            parse_mode='Markdown',
            reply_markup=get_tracking_keyboard(svc_type_full, req_id))
        return

    # ── 📋 Confirm staged auction-list import ──
    if data.startswith("list_cancel_"):
        if query.from_user.id not in ADMIN_IDS:
            await query.answer("❌ Admin only", show_alert=True)
            return
        uid = int(data.replace("list_cancel_", ""))
        pending_auction_list.pop(uid, None)
        await query.edit_message_text("❌ Auction List staging ကို Cancel လုပ်ပြီးပါပြီ။ Sheet1 မပြောင်းပါ။")
        return

    if data.startswith("list_save_"):
        if query.from_user.id not in ADMIN_IDS:
            await query.answer("❌ Admin only", show_alert=True)
            return
        uid = int(data.replace("list_save_", ""))
        staged_info = pending_auction_list.get(uid)
        if not staged_info:
            await query.answer("❌ Staged data မတွေ့ပါ — List ကို ပြန်တင်ပါ", show_alert=True)
            return
        if not SHEET_WEBHOOK:
            await query.message.reply_text("❌ SHEET_WEBHOOK မရှိပါ။ Sheet1 မပြောင်းပါ။")
            return

        saved, failed, already_present = await persist_staged_auction_rows(staged_info.get("rows", []))

        if not saved and not failed:
            pending_auction_list.pop(uid, None)
            await query.edit_message_text(
                f"✅ အသစ်ထည့်ရန် မရှိတော့ပါ။ Duplicate/ရှိပြီးသား {len(already_present)} စီး။\n"
                f"Sheet1 ကို မပြောင်းပါ။")
            return

        if failed:
            staged_info["rows"] = failed
            pending_auction_list[uid] = staged_info
        else:
            pending_auction_list.pop(uid, None)
        await query.edit_message_text(
            f"✅ Sheet1 Save ပြီး: {len(saved)} စီး\n"
            f"♻️ Duplicate/ရှိပြီးသား: {len(already_present)} စီး\n"
            f"⚠️ မအောင်မြင်သေး: {len(failed)} စီး\n"
            f"📋 Database: {await get_sheet_car_count()} စီး"
        )
        return

    # ── ✅ Confirm Save ──
    if data.startswith("cs_"):
        uid = int(data.replace("cs_", ""))
        info = pending_photo.get(uid)
        if not info:
            await query.message.reply_text("❌ Data မရှိတော့ပါ — ပုံ ပြန်တင်ပါ")
            return
        if info.get("model_needs_review"):
            await query.message.reply_text(
                "❌ Model ကို အတည်ပြုရန်လိုပါသည်။ AI vision model ကို တိုက်ရိုက် Save မလုပ်နိုင်ပါ။\n"
                "`Model ဖြည့်` button ကိုနှိပ်ပြီး မှန်ကန်သော Model ထည့်ပါ။",
                parse_mode="Markdown")
            return
        if info.get("year_needs_review") or not normalize_year(info.get("year")):
            await query.message.reply_text(
                "❌ Year ကို အတည်ပြုရန်လိုပါသည်။ OCR year ကို တိုက်ရိုက် Save မလုပ်နိုင်ပါ။\n"
                "`Year ဖြည့်` button ကိုနှိပ်ပြီး မှန်ကန်သော Year ထည့်ပါ။",
                parse_mode="Markdown")
            return
        info = pending_photo.pop(uid, None)
        if not info or info.get('price') is None:
            await query.message.reply_text("❌ Data မရှိတော့ပါ — ပုံ ပြန်တင်ပါ")
            return
        user_name = query.from_user.first_name or "Unknown"
        await save_price(info['chassis'], info['model'], info['color'], info['year'],
                        info['price'], user_name, info.get('image_url',''), info.get('loc', LOC_MAESOT))
        await query.message.reply_text(
            f"✅ *Save ပြီး!*\n\n🚗 {info['model']} ({ys(info.get('year',0))})\n"
            f"🔑 `{info['chassis']}`\n🎨 {info.get('color','')}\n📍 {info.get('loc', LOC_MAESOT)}\n💰 ฿{info['price']:,}\n\n"
            f"🌐 [Web မှာကြည့်](https://kyawmintun08.github.io/Japan-Auction-Car-Checker/)",
            parse_mode='Markdown')
        await post_to_channel(context, info['chassis'], info['model'], info['color'],
                             info['year'], info['price'], info.get('image_url',''), info.get('loc', LOC_MAESOT))

    elif data.startswith("cc_"):
        uid = int(data.replace("cc_",""))
        pending_photo.pop(uid, None)
        await query.message.reply_text(
            "❌ *Cancel လုပ်ပြီး*\n\nChassis ကိုယ်တိုင် ထည့်ပါ:\n"
            "`/price [chassis] [ဈေး]`\nဥပမာ: `/price GP1-1049821 58000`",
            parse_mode='Markdown')

    elif data.startswith("setloc_"):
        parts      = data.split("_")
        target_uid = int(parts[1])
        loc_key    = parts[2]
        loc_map    = {"MaeSot": LOC_MAESOT, "Klang9": LOC_KLANG9, "Border44": LOC_BORDER44}
        new_loc    = loc_map.get(loc_key, LOC_MAESOT)
        if target_uid not in pending_photo:
            await query.answer("❌ Data ကုန်သွားပြီ — ပုံ ပြန်တင်ပါ", show_alert=True)
            return
        pending_photo[target_uid]["loc"] = new_loc
        pdata = pending_photo[target_uid]
        loc_row = [
            InlineKeyboardButton(f"{'✅' if new_loc == LOC_MAESOT else '📍'} MaeSot",    callback_data=f"setloc_{target_uid}_MaeSot"),
            InlineKeyboardButton(f"{'✅' if new_loc == LOC_KLANG9 else '📍'} Klang9",    callback_data=f"setloc_{target_uid}_Klang9"),
            InlineKeyboardButton(f"{'✅' if new_loc == LOC_BORDER44 else '📍'} Border44", callback_data=f"setloc_{target_uid}_Border44"),
        ]
        if pdata.get('price') is not None:
            await query.edit_message_text(
                f"⚠️ *စစ်ဆေးပါ — မှန်ကန်ပါသလား?*\n\n"
                f"🚗 *{pdata['model']}* ({ys(pdata.get('year',0))})\n"
                f"🔑 `{pdata['chassis']}`\n🎨 {pdata['color']}\n📍 {new_loc}\n💰 ฿{pdata['price']:,}",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([
                    loc_row,
                    [InlineKeyboardButton("✅ Save",   callback_data=f"cs_{target_uid}"),
                     InlineKeyboardButton("❌ Cancel", callback_data=f"cc_{target_uid}")],
                ]))
        else:
            await query.edit_message_text(
                f"🚗 *{pdata['model']}* ({ys(pdata.get('year',0))})\n"
                f"🔑 `{pdata['chassis']}`\n🎨 {pdata['color']}\n📍 {new_loc}\n\n"
                f"💰 ဈေး ရိုက်ထည့်ပါ:\nဥပမာ: `150000`",
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([loc_row]))

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
        parts   = data.split("_", 2)
        chassis = parts[1]
        field   = parts[2]
        if field == "cancel":
            pending_edit.pop(query.from_user.id, None)
            await query.message.reply_text("❌ Cancel လုပ်ပြီး")
            return
        pending_edit[query.from_user.id] = {"chassis": chassis, "field": field}
        prompts = {
            "price": f"💰 `{chassis}` ဈေးအသစ် ရိုက်ထည့်ပါ:\nဥပမာ: `150000`",
            "color": f"🎨 `{chassis}` Color အသစ် ရိုက်ထည့်ပါ:\nဥပမာ: `PEARL WHITE`",
            "model": f"🚗 `{chassis}` Model အသစ် ရိုက်ထည့်ပါ:\nဥပမာ: `HONDA FIT`",
        }
        await query.message.reply_text(prompts[field], parse_mode='Markdown')

    elif data.startswith("fill_"):
        parts  = data.split("_", 2)
        uid    = int(parts[1])
        field  = parts[2]
        if uid not in pending_photo:
            await query.answer("❌ Data ကုန်သွားပြီ", show_alert=True)
            return
        pending_edit[query.from_user.id] = {"chassis": "__photo__", "field": field, "photo_uid": uid}
        prompts = {
            "model": "🚗 Model ထည့်ပါ:\nဥပမာ: `CROWN`, `AD VAN`",
            "color": "🎨 Color ထည့်ပါ:\nဥပမာ: `WHITE`, `PEARL WHITE`",
            "year":  "📅 Year ထည့်ပါ:\nဥပမာ: `2013`",
        }
        await query.message.reply_text(prompts.get(field,"ထည့်ပါ:"), parse_mode='Markdown')
        await query.answer()

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

    elif data in ("join_start", "newmember_start"):
        await query.answer()
        await show_new_member_flow(query.message, query.from_user.id)

    elif data.startswith("pkg_cancel_"):
        pending_payment.pop(query.from_user.id, None)
        await query.message.reply_text("❌ Cancel လုပ်ပြီး")

    elif data.startswith("pkg_back_"):
        parts = data.split("_")
        user_id = query.from_user.id
        action = parts[3] if len(parts) > 3 and parts[3] in ("join", "renew", "upgrade") else "renew"
        await query.message.reply_text(
            ("New Member package ပြန်ရွေးပါ 👇" if action == "join" else "Renew Member package ပြန်ရွေးပါ 👇"),
            reply_markup=build_package_keyboard(user_id, action))

    elif data.startswith("pkg_"):
        parts   = data.split("_")
        package = parts[1]
        user_id = int(parts[2])
        action  = parts[3] if len(parts) > 3 else "renew"
        if query.from_user.id != user_id:
            await query.answer("❌ သင့် payment button မဟုတ်ဘူး", show_alert=True)
            return
        flow = await validate_payment_flow(user_id, action)
        if not flow.get("ok"):
            if flow.get("reason") == "existing_member_must_renew":
                msg = "🔄 Member record ရှိပြီးသားပါ။ Member အသစ် payment မလုပ်ပါနဲ့ — `/renew` ကိုသာ သုံးပါ။"
            elif flow.get("reason") == "new_member_must_join":
                msg = "🆕 Member record မရှိသေးပါ။ Renew payment မလုပ်ပါနဲ့ — `/newmember` မှ New Member flow ကိုသာ သုံးပါ။"
            elif flow.get("reason") == "already_premium":
                msg = "💎 ဒီ account သည် Web Premium ဖြစ်ပြီးသားပါ။ `/upgrade` ထပ်မသုံးပါနှင့် — သက်တမ်းတိုးရန် `/renew` ကိုသာ သုံးပါ။"
            else:
                msg = "⚠️ Member record ကို စစ်မရသေးပါ။ Payment မလွှဲသေးဘဲ Admin ကို ဆက်သွယ်ပါ။"
            await query.message.reply_text(
                msg + "\n\nPayment မှားပို့မိပါက refund/repayment စစ်ဆေးမှုကြာနိုင်ပါတယ်.",
                parse_mode="Markdown")
            return
        pending_payment[user_id] = {
            "package": package, "action": action,
            "name":    query.from_user.first_name or "Unknown",
            "username": f"@{query.from_user.username}" if query.from_user.username else str(user_id),
        }
        pkg_name = PLAN_NAMES.get(package,"")
        flow_label = "New Member" if action == "join" else "Renew Member"
        await query.message.reply_text(
            f"✅ *{flow_label}*\n"
            f"📦 Package: *{pkg_name}*\n\n"
            "ဒီ package/flow မှန်မမှန် စစ်ပြီးမှ Period ရွေးပါ။\n"
            "⚠️ Member အသစ်နှင့် Renew payment ကို မရောပါနဲ့။ Payment မှားပို့မိပါက refund/repayment ကြာနိုင်ပါတယ်။\n\n"
            "Period ရွေးပါ 👇",
            parse_mode='Markdown',
            reply_markup=build_period_keyboard(user_id, package, action))

    # ── 🆕 Period → Method ရွေးခိုင်း ──
    elif data.startswith("period_"):
        parts   = data.split("_")
        package = parts[1]
        months  = int(parts[2])
        user_id = int(parts[3])
        if query.from_user.id != user_id:
            await query.answer("❌ သင့် payment button မဟုတ်ဘူး", show_alert=True)
            return
        pay_data = pending_payment.get(user_id, {})
        action = str(pay_data.get("action") or "renew")
        flow = await validate_payment_flow(user_id, action)
        if not flow.get("ok"):
            await query.message.reply_text(
                "⚠️ ဒီ payment flow ကို ဆက်မလုပ်နိုင်သေးပါ။ Member အသစ်ဆို `/newmember`၊ ရှိပြီးသား Member ဆို `/renew` ကို မှန်ကန်စွာ အသုံးပြုပါ။\n\n"
                "Payment မှားပို့မိပါက refund/repayment စစ်ဆေးမှုကြာနိုင်ပါတယ်။",
                parse_mode="Markdown")
            pending_payment.pop(user_id, None)
            return
        amount  = PLAN_PRICES.get(package, {}).get(months, 0)
        pkg_name = PLAN_NAMES.get(package,"")

        if user_id not in pending_payment:
            pending_payment[user_id] = {"action": action}
        pending_payment[user_id].update({
            "package": package,
            "months":  months,
            "amount":  amount,
        })

        flow_label = "New Member" if action == "join" else "Renew Member"
        await query.message.reply_text(
            f"✅ *{flow_label}*\n"
            f"📦 Package: *{pkg_name}*\n"
            f"📅 Period: *{months} လ*\n"
            f"💵 ပေးရမည်: *{amount:,} ks*\n\n"
            "⚠️ Amount၊ Package နှင့် Payment receiver ကို သေချာစစ်ပြီးမှ လွှဲပါ။\n"
            "Member အသစ် payment ကို Renew အဖြစ် မလွှဲပါနဲ့။ မှားယွင်းပါက refund/repayment ကြာနိုင်ပါတယ်။\n\n"
            f"💳 *Payment Method ရွေးပါ* 👇",
            parse_mode='Markdown',
            reply_markup=build_paymethod_keyboard(user_id))

    # ── 🆕 Method ရွေးပြီး QR ပြ ──
    elif data.startswith("paymethod_"):
        parts   = data.split("_")
        method  = parts[1]
        user_id = int(parts[2])
        if query.from_user.id != user_id:
            await query.answer("❌ သင့် button မဟုတ်ဘူး", show_alert=True); return
        if user_id not in pending_payment:
            await query.answer("❌ Session ကုန်ပြီ — New Member အတွက် /newmember၊ Renew အတွက် /renew ပြန်စပါ", show_alert=True); return

        pay_data = pending_payment[user_id]
        info     = PAYMENT_METHOD_INFO.get(method, {})
        amount   = pay_data.get("amount", 0)
        package  = pay_data.get("package", "CH")
        months   = pay_data.get("months", 1)
        action   = str(pay_data.get("action") or "renew")
        flow_label = "New Member" if action == "join" else "Renew Member"
        pkg_name = PLAN_NAMES.get(package, "")
        file_id  = await get_payment_qr(method)

        pending_payment[user_id]["method"]       = method
        pending_payment[user_id]["waiting_slip"] = True
        pending_payment[user_id]["userId"]       = str(user_id)

        # Persist the package/period/method choice now, before any slip has
        # been sent. Without this, the selection lives only in this process's
        # memory: a bot restart (e.g. a deploy) between QR-shown and
        # slip-sent silently drops it, and the member's very real payment
        # slip then gets rejected by the Admin-only OCR gate, forcing them
        # to redo the whole flow. Best-effort — a failed early save still
        # falls back to the post-slip save at slip-received time.
        early_draft = await save_payment_draft(pending_payment[user_id])
        if early_draft.get("status") != "ok":
            logger.warning(
                "Early payment draft persistence failed user=%s result=%s",
                user_id, early_draft)

        caption = (
            f"{info.get('label','')} *Payment* — *{flow_label}*\n\n"
            f"💵 *Amount:* {amount:,} ks\n"
            f"📦 {pkg_name} — {months} လ\n"
            f"📱 *Number:* {info.get('number','')}\n"
            f"👤 *Name:* {info.get('owner','')}\n\n"
            f"⚠️ ဒီ payment သည် *{flow_label}* အတွက်သာ ဖြစ်ပါတယ်။\n"
            f"Member အသစ် payment ကို Renew အဖြစ် မပို့ပါနဲ့၊ Renew payment ကို Member အသစ်အဖြစ် မပို့ပါနဲ့။\n"
            f"❗ Payment မှားပို့မိပါက refund/repayment စစ်ဆေးမှုကြာနိုင်ပါတယ်။\n\n"
            f"⬇️ QR ကို *long-press* → Save Photo\n"
            f"📲 ဒါမှမဟုတ် App နဲ့ Scan\n\n"
            f"💸 ပြီးရင် *Payment Slip* ဒီနေရာမှာ ပို့ပါ"
        )

        if file_id:
            try:
                await context.bot.send_photo(
                    chat_id=user_id, photo=file_id,
                    caption=caption, parse_mode='Markdown')
            except Exception as e:
                logger.error(f"send QR photo: {e}")
                await query.message.reply_text(
                    f"⚠️ QR ပုံ ပြလို့မရဘူး — Admin ကို ဆက်သွယ်ပါ\n\n{caption}",
                    parse_mode='Markdown')
        else:
            await query.message.reply_text(
                f"⚠️ {info.get('label','')} QR မထည့်ရသေးပါ — Admin ကို ဆက်သွယ်ပါ\n\n{caption}",
                parse_mode='Markdown')

    # ── 🆕 Admin /setqr Method ရွေး ──
    elif data.startswith("bcast_send_"):
        user_id = int(data.replace("bcast_send_", ""))
        if query.from_user.id != user_id or user_id not in ADMIN_IDS:
            await query.answer("❌ Admin only", show_alert=True); return
        pending = pending_broadcast_text.pop(user_id, None)
        if not pending:
            await query.answer("❌ Broadcast data ကုန်သွားပြီ — /broadcast ပြန်စပါ", show_alert=True)
            return

        message    = pending["message"]
        pkg_filter = pending.get("pkg_filter")
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    SHEET_WEBHOOK, json={"action": "getMembers", "serverKey": SHEET_SERVER_KEY},
                    timeout=40, follow_redirects=True)
            data_resp = resp.json()
            members = data_resp.get("members", [])
        except Exception as e:
            logger.error(f"bcast_send getMembers: {e}")
            await query.message.reply_text("❌ Member list ဆွဲမရ")
            return

        targets = []
        for m in members:
            status = str(m.get("status", "")).upper()
            pkg    = str(m.get("package", "")).upper()
            uid    = m.get("userId") or m.get("userID") or m.get("UserID")
            if status != "ACTIVE": continue
            if pkg_filter and pkg != pkg_filter: continue
            if uid: targets.append(str(uid))

        if not targets:
            await query.message.reply_text("❌ Member မတွေ့ဘူး")
            return

        await query.message.reply_text(f"📢 {len(targets)} ယောက်ကို ပို့နေတယ်...")
        success = 0; failed = 0
        for uid in targets:
            try:
                await context.bot.send_message(
                    chat_id=int(uid),
                    text=f"📢 *Japan Auction Car*\n\n{message}",
                    parse_mode='Markdown')
                success += 1
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.error(f"bcast_send {uid}: {e}")
                failed += 1

        await query.message.reply_text(
            f"✅ *Broadcast ပြီးပြီ*\n\n"
            f"✅ အောင်မြင်: {success} ယောက်\n"
            f"❌ မရောက်: {failed} ယောက်",
            parse_mode='Markdown')

    elif data.startswith("bcast_no_"):
        user_id = int(data.replace("bcast_no_", ""))
        if query.from_user.id != user_id or user_id not in ADMIN_IDS:
            await query.answer("❌ Admin only", show_alert=True); return
        pending_broadcast_text.pop(user_id, None)
        await query.message.reply_text("❌ Broadcast ပယ်ဖျက်ပြီ")

    elif data.startswith("setqr_"):
        parts = data.split("_", 2)
        if len(parts) < 3:
            return
        action  = parts[1]
        user_id = int(parts[2])
        if query.from_user.id != user_id or user_id not in ADMIN_IDS:
            await query.answer("❌ Admin only", show_alert=True); return
        if action == "cancel":
            pending_setqr.pop(user_id, None)
            await query.edit_message_text("❌ Cancel လုပ်ပြီး")
            return
        if action not in ("kpay","wave","cb"):
            return
        pending_setqr[user_id] = action
        info = PAYMENT_METHOD_INFO.get(action, {})
        await query.edit_message_text(
            f"✅ *{info.get('label','')}* ရွေးပြီ\n\n"
            f"📤 {info.get('label','')} QR ပုံကို ဒီနေရာမှာ ပို့ပါ\n\n"
            f"(file ID auto-save ဖြစ်မယ်)",
            parse_mode='Markdown')

    # ── Slip Confirm (Admin) ──
    elif data.startswith("slip_confirm_"):
        if query.from_user.id not in ADMIN_IDS:
            await query.answer("❌ Admin သာ လုပ်နိုင်တယ်", show_alert=True)
            return
        member_id = int(data.replace("slip_confirm_",""))
        pay_data  = await ensure_payment_session(member_id)
        if not pay_data:
            await query.answer("❌ Data ကုန်သွားပြီ", show_alert=True)
            return
        payment_action, action_source = await resolve_payment_action(member_id, pay_data)
        if not payment_action:
            await query.message.reply_text(
                "❌ Approve မလုပ်နိုင်ပါ — legacy payment draft ၏ flow ကို စစ်မရသေးပါ။\n"
                "Member record lookup မအောင်မြင်သေးသောကြောင့် payment မပြောင်းလဲထားပါ။",
                parse_mode="Markdown")
            return
        if not pay_data.get("action"):
            pay_data["action"] = payment_action
            pay_data["action_source"] = action_source
            pending_payment[member_id] = pay_data
        flow = await validate_payment_flow(member_id, payment_action)
        if not flow.get("ok"):
            if flow.get("reason") == "member_lookup_unavailable":
                await query.message.reply_text(
                    "⏳ Approve မလုပ်နိုင်သေးပါ — Member record ကို Apps Script ကနေ ယာယီ ဆွဲမရသေးပါ။\n"
                    "ဒါက flow မကိုက်ညီတာ မဟုတ်ပါ — server တစ်ခဏ slow ဖြစ်နေတာသာ ဖြစ်နိုင်ပါတယ်။\n"
                    "ခဏနေရင် Confirm ကို ထပ်နှိပ်ကြည့်ပါ။",
                    parse_mode="Markdown")
                return
            await query.message.reply_text(
                "❌ Approve မလုပ်နိုင်ပါ — Member အသစ်/Renew flow မကိုက်ညီပါ။\n"
                "Payment ကို Member အသစ်အဖြစ်ပို့ထားသော်လည်း record ရှိပြီးသား သို့မဟုတ် Renew အဖြစ်ပို့ထားသော်လည်း record မရှိသေးနိုင်ပါတယ်။\n\n"
                "Payment မှားပို့မိပါက refund/repayment စစ်ဆေးမှုကြာနိုင်သောကြောင့် မအတည်ပြုသေးပါ။",
                parse_mode="Markdown")
            return
        flow_label = "New Member" if payment_action == "join" else ("Renew/Upgrade Member" if payment_action == "upgrade" else "Renew Member")
        if payment_action == "join" and flow.get("reason") == "inactive_record_reactivation":
            flow_label = "New Member / Inactive Record Reactivation"
        name        = pay_data.get("name", "Unknown")
        _pkg_code   = pay_data.get("package","CH")
        pkg         = PLAN_NAMES.get(_pkg_code, "Unknown")
        months      = pay_data.get("months", 1)
        amount      = int(pay_data.get("amount", 0) or 0)
        total_paid, _ = payment_slip_summary(pay_data.get("slips", []))
        if total_paid < amount:
            remaining = amount - total_paid
            await query.answer(
                f"မပြည့်သေးပါ — {remaining:,} ks လိုသေးသည်။ Member ဆီသို့ အသိပေးပြီးပါပြီ။",
                show_alert=True)
            try:
                await context.bot.send_message(
                    chat_id=member_id,
                    text=(f"⚠️ Payment မပြည့်သေးပါ။\n\n"
                          f"လက်ခံပြီး: {total_paid:,} ks\n"
                          f"ကျန်ငွေ: {remaining:,} ks\n\n"
                          "ကျန်ငွေကို လွှဲပြီး slip အသစ်ကို ဒီနေရာမှာပဲ ပို့ပါ။"),
                )
            except Exception as e:
                logger.error(f"partial-payment guard DM: {e}")
            return
        _give_txt   = "Channel link + Password ပေးမည်" if _pkg_code == "WEB" else "Channel link ပေးမည် (Password မပါ)"
        confirm_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Yes — Approve", callback_data=f"slip_ok_{member_id}"),
            InlineKeyboardButton("❌ Cancel",        callback_data=f"slip_okcancel_{member_id}"),
        ]])
        await query.message.reply_text(
            f"⚠️ *Approve အတည်ပြုချက်*\n\n"
            f"👤 {name}\n"
            f"🧭 Flow: *{flow_label}*\n"
            f"📦 {pkg} — {months} လ\n"
            f"💵 {amount:,} ks\n\n"
            f"⚠️ Flow၊ Package၊ Amount၊ Receiver မှန်ကြောင်း စစ်ပြီးမှ Approve လုပ်ပါ။\n"
            f"Payment မှားပို့မိပါက repayment ကြာနိုင်ပါတယ်။\n\n"
            f"{_give_txt} — သေချာပါသလား?",
            parse_mode='Markdown',
            reply_markup=confirm_kb)

    elif data.startswith("slip_okcancel_"):
        if query.from_user.id not in ADMIN_IDS:
            await query.answer("❌ Admin သာ လုပ်နိုင်တယ်", show_alert=True)
            return
        await query.message.reply_text("❌ Approve Cancel လုပ်ပြီး")

    elif data.startswith("slip_ok_"):
        if query.from_user.id not in ADMIN_IDS:
            await query.answer("❌ Admin သာ လုပ်နိုင်တယ်", show_alert=True)
            return

        member_id = int(data.replace("slip_ok_", ""))
        # The admin may press Yes — Approve after a Railway restart or worker
        # recycle. Restore the durable Payment_Drafts row before declaring the
        # approval data missing; slip_confirm_ already uses this same helper.
        pay_data = await ensure_payment_session(member_id)
        if not pay_data:
            await query.message.reply_text(
                f"❌ Payment draft မတွေ့ပါ။ User ID `{member_id}` ၏ Payment_Drafts/Finance record ကို "
                "Admin မှ စစ်ဆေးပြီးမှ recovery လုပ်ပါ။\n"
                "Member ကို slip ထပ်မပို့ခိုင်းသေးပါနှင့်။",
                parse_mode="Markdown")
            return
        payment_action, action_source = await resolve_payment_action(member_id, pay_data)
        if not payment_action:
            await query.message.reply_text(
                "❌ Final Approve မလုပ်နိုင်ပါ — legacy payment draft ၏ flow ကို စစ်မရသေးပါ။\n"
                "Member record lookup မအောင်မြင်သေးသောကြောင့် payment မသိမ်းဆည်းသေးပါ။",
                parse_mode="Markdown")
            return
        if not pay_data.get("action"):
            pay_data["action"] = payment_action
            pay_data["action_source"] = action_source
            pending_payment[member_id] = pay_data
        flow = await validate_payment_flow(member_id, payment_action)
        if not flow.get("ok"):
            if flow.get("reason") == "member_lookup_unavailable":
                await query.message.reply_text(
                    "⏳ Final Approve မလုပ်နိုင်သေးပါ — Member record ကို Apps Script ကနေ ယာယီ ဆွဲမရသေးပါ။\n"
                    "ခဏနေရင် ထပ်နှိပ်ကြည့်ပါ။",
                    parse_mode="Markdown")
                return
            await query.message.reply_text(
                "❌ Final Approve မလုပ်နိုင်ပါ — Member record နှင့် payment flow မကိုက်ညီပါ။\n"
                "Payment မှားပို့မိပါက repayment ကြာနိုင်သောကြောင့် မသိမ်းဆည်းသေးပါ။",
                parse_mode="Markdown")
            return
        expected_amount = int(pay_data.get("amount", 0) or 0)
        slips = pay_data.get("slips", []) or []
        slip_info = pay_data.get("slip_info", {}) or {}
        if not slips and slip_info:
            slips = [{"slip_info": slip_info}]
        total_paid, _ = payment_slip_summary(slips)
        if total_paid != expected_amount:
            if total_paid < expected_amount:
                detail = f"payment {expected_amount - total_paid:,} ks လိုသေးသည်"
            else:
                detail = f"payment {total_paid - expected_amount:,} ks ပိုနေသည်"
            await query.message.reply_text(
                f"❌ Approve မလုပ်နိုင်ပါ — {detail}။ Slip ပြန်စစ်ပြီးမှ Approve လုပ်ပါ။"
            )
            return

        payment_check = validate_payment_batch(
            pay_data,
            slips,
            expected_receiver=ADMIN_REAL_NAME,
        )
        if not payment_check.get("ok"):
            reason = str(payment_check.get("reason") or "payment_validation_failed")
            await query.message.reply_text(
                "❌ Payment ကို အတည်မပြုနိုင်သေးပါ။\\n\\n"
                f"စစ်ဆေးချက်: `{reason}`\\n"
                "Amount / Payment method / Transaction No / Date ကို ပြန်စစ်ပြီးမှ Approve လုပ်ပါ။\\n"
                "Customer ကို မပျောက်စေရန် payment session ကို မဖျက်ထားပါ။",
                parse_mode="Markdown",
            )
            await notify_admins(
                context,
                f"⛔ Payment validation blocked for {member_id}: {reason}. Approve မလုပ်ရသေးပါ။",
            )
            return

        # Commit member + Finance exactly once through the Apps Script transaction guard.
        # This prevents a double-click or duplicate Telegram callback from extending
        # the same member twice.
        package = str(pay_data.get("package", "CH")).upper().strip()
        months = int(pay_data.get("months", 1) or 1)
        name = pay_data.get("name", "Unknown")
        username = pay_data.get("username", str(member_id))
        chosen_method = str(pay_data.get("method", "")).strip()
        slip_info = pay_data.get("slip_info", {}) or {}
        transaction_no = str(payment_check.get("transaction_no") or "").strip()
        if transaction_no.upper() == "UNKNOWN":
            transaction_no = ""
        approved_by = str(
            getattr(query.from_user, "username", "")
            or getattr(query.from_user, "id", "")
        ).strip()
        password = generate_password() if package == "WEB" else ""
        atomic_payment = {
            "userId": str(member_id),
            "username": username.replace("@", ""),
            "package": package,
            "months": months,
            "days": months * 30,
            "expectedAmount": expected_amount,
            "receivedAmount": total_paid,
            "amount": total_paid,
            "payType": slip_info.get("TYPE", "") or chosen_method.upper(),
            "method": chosen_method.upper(),
            "transactionNo": transaction_no,
            "paymentId": transaction_no,
            "receiver": slip_info.get("TRANSFER_TO", slip_info.get("RECEIVER", "")),
            "sender": slip_info.get("SENDER", ""),
            "date": slip_info.get("DATE", datetime.now().strftime("%d/%m/%Y")),
            "time": slip_info.get("TIME", datetime.now().strftime("%H:%M")),
            "source": "PAYMENT_SLIP",
            "approvedBy": approved_by,
            "password": password,
        }
        atomic_result = await approve_payment_transaction(atomic_payment)
        atomic_message = str(atomic_result.get("message") or "").strip()
        if atomic_result.get("result") == "duplicate":
            await clear_payment_draft(member_id, transaction_no)
            pending_payment.pop(member_id, None)
            await query.message.reply_text(
                "⚠️ ဒီ Payment Transaction ကို အရင် Approve လုပ်ပြီးသားဖြစ်ပါတယ်။\n"
                "ထပ်မံ Approve မလုပ်တော့ပါနှင့်။ Member သက်တမ်းကို ထပ်မတိုးထားပါ။",
                parse_mode="Markdown")
            return
        if atomic_result.get("status") != "ok":
            if atomic_message == "transaction_already_used":
                await query.message.reply_text(
                    "⚠️ ဒီ Payment Transaction ကို အရင် Approve လုပ်ပြီးသားဖြစ်ပါတယ်။\n"
                    "ထပ်မံ Approve မလုပ်တော့ပါနှင့်။ Member သက်တမ်းကို ထပ်မတိုးထားပါ။",
                    parse_mode="Markdown")
            elif atomic_message == "transaction_in_progress":
                await query.message.reply_text(
                    "⚠️ ဒီ Payment ကို အခြား Approve request တစ်ခုက စစ်ဆေးနေဆဲပါ။\n"
                    "Approve ကို ထပ်မနှိပ်ပါနှင့်။",
                    parse_mode="Markdown")
            else:
                await query.message.reply_text(
                    "❌ Payment ကို တစ်ကြိမ်တည်း အတည်ပြုသည့် server check မအောင်မြင်သေးပါ။\n"
                    f"စစ်ဆေးချက်: `{atomic_message or 'approval_failed'}`\n"
                    "Member သက်တမ်းကို မပြောင်းထားပါ။ Approve ကို ထပ်မနှိပ်သေးပါနှင့်။",
                    parse_mode="Markdown")
            return

        member = atomic_result.get("member") or {}
        canonical_package = str(atomic_result.get("package") or member.get("package") or package).upper()
        canonical_password = str(atomic_result.get("password") or member.get("password") or password or "")
        canonical_expire = str(atomic_result.get("member", {}).get("expireDate") or "")
        entry_type = str(atomic_result.get("entryType") or "NEW").upper()
        await clear_payment_draft(member_id, transaction_no)
        pending_payment.pop(member_id, None)

        invite_url = await create_invite_link(context, months * 30, member_id)
        await send_approval_dm(
            context,
            member_id,
            months,
            canonical_password,
            invite_url,
            package=canonical_package,
            expire_date=canonical_expire,
        )

        expire_date = canonical_expire or (
            datetime.now() + timedelta(days=months * 30)
        ).strftime("%d/%m/%Y")
        pw_line = f"🔑 Password: `{canonical_password}`\n" if canonical_package == "WEB" else ""

        # name/username are raw Telegram first_name/username values and can
        # contain unbalanced Markdown special characters (_, *, `, [). The
        # approval (approve_payment_transaction, send_approval_dm) is already
        # committed above, so a parse failure here must not look like the
        # approval itself failed — escape rather than risk a BadRequest.
        safe_name = escape_markdown(str(name), version=1)
        safe_username = escape_markdown(str(username), version=1)

        await query.message.reply_text(
            f"✅ *Payment Confirmed + Approved!*\n\n"
            f"👤 {safe_name} ({safe_username})\n"
            f"📦 {PLAN_NAMES.get(package, package)} — {months} လ\n"
            f"⏰ ကုန်ဆုံး: `{expire_date}`\n"
            f"{pw_line}\n"
            f"Member ကို DM ပို့ပြီးပြီ ✅",
            parse_mode="Markdown",
        )

    elif data.startswith("slip_no_"):
        if query.from_user.id not in ADMIN_IDS:
            await query.answer("❌ Admin သာ လုပ်နိုင်တယ်", show_alert=True)
            return
        member_id = int(data.replace("slip_no_", ""))
        # Restore the draft before clearing it so the retry command follows the
        # original flow. Unknown/missing actions fail closed instead of guessing.
        pay_data = await ensure_payment_session(member_id)
        retry_action = ""
        if pay_data:
            retry_action, _ = await resolve_payment_action(member_id, pay_data)
        retry_command = payment_retry_command(retry_action)
        await clear_payment_draft(member_id)
        pending_payment.pop(member_id, None)
        try:
            admin_link = f"\n💬 [Admin ကို ဆက်သွယ်](https://t.me/{ADMIN_USERNAME})" if ADMIN_USERNAME else ""
            if retry_command:
                retry_instruction = f"ပြန်လည် ကြိုးစားရန် {retry_command}"
            else:
                retry_instruction = (
                    "ဒီ payment ၏ flow ကို မသတ်မှတ်နိုင်သေးပါ။ "
                    "Admin ကို ဆက်သွယ်ပြီးမှ ပြန်စတင်ပါ။"
                )
            await context.bot.send_message(
                chat_id=member_id,
                text=f"❌ *Payment မအတည်မပြုနိုင်ပါ*\n\n"
                     f"Slip မှားနိုင်သည် သို့မဟုတ် ငွေပမာဏ မပြည့်မှီပါ\n\n"
                     f"{retry_instruction}{admin_link}",
                parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Reject DM: {e}")
        await query.message.reply_text(f"❌ Rejected — Member ကို notify ပြီးပြီ")

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
                    "action":   "updateMemberId", "serverKey": SHEET_SERVER_KEY,
                    "username": target_username,
                    "newId":    str(new_id),
                    "password": new_pw,
                }, timeout=40, follow_redirects=True)
            result = resp.json()
            old_id = result.get("oldId", "?")
            if result.get("status") == "ok":
                try:
                    await context.bot.send_message(
                        chat_id=new_id,
                        text=f"✅ *Account Update ပြီ*\n\n"
                             f"Telegram ID အသစ်နဲ့ ချိတ်ဆက်ပြီ\n"
                             f"🔑 New Password: `{new_pw}`\n\n"
                             f"🌐 https://kyawmintun08.github.io/Japan-Auction-Car-Checker/",
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

    elif data.startswith("req_budget_"):
        user_id = query.from_user.id
        if user_id not in pending_request: return
        amount = data.replace("req_budget_","")
        pending_request[user_id]["data"]["budget"] = f"฿{int(amount):,}"
        pending_request[user_id]["step"] = 4
        kb = [
            [InlineKeyboardButton("⭐",     callback_data="req_cond_1"),
             InlineKeyboardButton("⭐⭐",    callback_data="req_cond_2"),
             InlineKeyboardButton("⭐⭐⭐",   callback_data="req_cond_3")],
            [InlineKeyboardButton("⭐⭐⭐⭐",  callback_data="req_cond_4"),
             InlineKeyboardButton("⭐⭐⭐⭐⭐", callback_data="req_cond_5")],
        ]
        await query.edit_message_text(
            "⭐ *Condition ရွေးပါ*\n\n⭐ = ဈေးသက်သာ\n⭐⭐⭐ = ပုံမှန်\n⭐⭐⭐⭐⭐ = အကောင်းဆုံး",
            parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("req_cond_"):
        user_id = query.from_user.id
        if user_id not in pending_request: return
        stars = int(data.replace("req_cond_",""))
        pending_request[user_id]["data"]["condition"] = "⭐" * stars
        pending_request[user_id]["step"] = 5
        kb = [
            [InlineKeyboardButton("🔥 ၃ ရက်",     callback_data="req_time_3days"),
             InlineKeyboardButton("📅 ၁ ပတ်",    callback_data="req_time_1week")],
            [InlineKeyboardButton("🗓 ၁ လ",      callback_data="req_time_1month"),
             InlineKeyboardButton("⏳ ရမှပြောမည်", callback_data="req_time_open")],
        ]
        await query.edit_message_text(
            "⏳ *Timeline ရွေးပါ*",
            parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif data.startswith("req_time_"):
        user_id = query.from_user.id
        if user_id not in pending_request: return
        tmap = {
            "req_time_3days":  "🔥 ၃ ရက်",
            "req_time_1week":  "📅 ၁ ပတ်",
            "req_time_1month": "🗓 ၁ လ",
            "req_time_open":   "⏳ ရမှပြောမည်",
        }
        pending_request[user_id]["data"]["timeline"] = tmap.get(data, data)
        pending_request[user_id]["step"] = 6
        await finish_request(query, context, user_id)

    elif data == "req_confirm":
        user_id  = query.from_user.id
        username = query.from_user.username or query.from_user.first_name or str(user_id)
        await query.edit_message_text("⏳ Request တင်နေတယ်...")
        await submit_request(context, user_id, username)

    elif data == "req_cancel":
        user_id = query.from_user.id
        pending_request.pop(user_id, None)
        await query.edit_message_text("❌ Request ပယ်ဖျက်ပြီ\nပြန်တင်ရန်: /carrequest")

    elif data.startswith("dep_start_"):
        parts        = data.split("_", 3)
        req_id       = parts[2]
        broker_tg_id = parts[3]
        customer_id  = str(query.from_user.id)

        PAYMENT_INFO_DEP = os.environ.get('PAYMENT_INFO', 'KPay / Wave: Admin ကို ဆက်သွယ်ပါ')

        pending_deposit[customer_id] = {
            "reqId":      req_id,
            "brokerTgId": broker_tg_id,
            "step":       "waiting_slip",
        }
        await query.edit_message_text(
            f"💰 *Deposit ฿20,000*\n\n"
            f"🆔 Request: `{req_id}`\n\n"
            f"💳 *Payment Info:*\n{PAYMENT_INFO_DEP}\n\n"
            f"⬇️ Slip ကို ဒီ bot ထဲမှာ တိုက်ရိုက် ပို့ပါ",
            parse_mode='Markdown')

    elif data.startswith("dep_ok_"):
        if query.from_user.id not in ADMIN_IDS:
            await query.answer("❌ Admin only", show_alert=True); return
        customer_id  = data.replace("dep_ok_", "")
        dep_data     = pending_deposit.get(customer_id, {})
        if not dep_data or not dep_data.get("slip_info"):
            # Either this card was already Confirmed/Rejected (a stale
            # duplicate tap), or there's simply no slip on file anymore —
            # either way, do not fabricate a saveDeposit with a blank reqId.
            await query.answer("⚠️ ဒီ Deposit ကို အရင်က စစ်ဆေးပြီးသား သို့မဟုတ် Slip မရှိတော့ပါ", show_alert=True)
            return
        slip_info = dep_data.get("slip_info", {})
        txn_no    = str(slip_info.get("TRANSACTION_NO", "") or "").strip()
        if not dep_data.get("amount_verified"):
            await query.answer(
                "⚠️ Slip ငွေပမာဏ မပြည့်မီ/မဖတ်နိုင်ပါ — Reject နှိပ်ပြီး customer ကို "
                "ရှင်းလင်းသော slip ပြန်တောင်းပါ",
                show_alert=True)
            return
        if txn_no and txn_no.upper() != "UNKNOWN" and txn_no in used_deposit_txns:
            await query.answer("⚠️ ဒီ Transaction No. ကို အရင် Deposit တစ်ခုမှာ သုံးပြီးသားပါ", show_alert=True)
            return
        if txn_no and txn_no.upper() != "UNKNOWN":
            used_deposit_txns.add(txn_no)

        pending_deposit.pop(customer_id, None)
        req_id       = dep_data.get("reqId", "")
        broker_tg_id = dep_data.get("brokerTgId", "")

        mmk_rate   = int(os.environ.get("MMK_RATE", "3800"))
        thb_amount = 20000
        mmk_amount = thb_amount * mmk_rate
        now_str    = datetime.now().strftime("%d/%m/%Y")

        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                await client.post(SHEET_WEBHOOK, json={
                    "action":     "saveDeposit",
                    "reqId":      req_id,
                    "customerId": customer_id,
                    "brokerTgId": broker_tg_id,
                    "thbAmount":  thb_amount,
                    "mmkAmount":  mmk_amount,
                    "mmkRate":    mmk_rate,
                    "date":       now_str,
                    "txnNo":      slip_info.get("TRANSACTION_NO", ""),
                    "payType":    slip_info.get("TYPE", ""),
                    "status":     "HOLD",
                }, timeout=40)
        except Exception as e:
            logger.error(f"saveDeposit: {e}")

        try:
            await context.bot.send_message(
                chat_id=int(customer_id),
                text=(f"✅ *Deposit လက်ခံပြီ!*\n\n"
                      f"🆔 `{req_id}`\n"
                      f"💰 ฿{thb_amount:,} ({mmk_amount:,} ks)\n"
                      f"📅 {now_str}\n\n"
                      f"Broker က ကားရှာပေးနေပြီ ⏳"),
                parse_mode='Markdown')
        except Exception as e:
            logger.error(f"dep_ok customer: {e}")

        if broker_tg_id:
            try:
                await context.bot.send_message(
                    chat_id=int(broker_tg_id),
                    text=(f"✅ *Customer Deposit ရပြီ — ကားရှာပေးနိုင်ပြီ*\n\n"
                          f"🆔 `{req_id}`\n"
                          f"💰 ฿{thb_amount:,} — HOLD ✅\n\n"
                          f"Admin မှ Deposit အတည်ပြုပြီ\n"
                          f"ကားရှာပေးနိုင်ပြီ 🚗"),
                    parse_mode='Markdown')
            except Exception as e:
                logger.error(f"dep_ok broker: {e}")

        await query.message.reply_text(
            f"✅ *Deposit Confirmed!*\n\n"
            f"🆔 `{req_id}`\n"
            f"👤 Customer: `{customer_id}`\n"
            f"💰 ฿{thb_amount:,} = {mmk_amount:,} ks\n"
            f"📅 Rate: {mmk_rate} ks/฿",
            parse_mode='Markdown')

        if req_id in proxy_sessions:
            proxy_sessions[req_id]["deposit_paid"] = True

        nodep_pending.pop(req_id, None)

    elif data.startswith("dep_no_"):
        if query.from_user.id not in ADMIN_IDS:
            await query.answer("❌ Admin only", show_alert=True); return
        customer_id = data.replace("dep_no_", "")
        removed = pending_deposit.pop(customer_id, None)
        if not removed:
            # Already Confirmed (or Rejected) by another tap — don't send a
            # contradictory rejection message on top of an approval.
            await query.answer("⚠️ ဒီ Deposit ကို အရင်က စစ်ဆေးပြီးသားပါ", show_alert=True)
            return
        try:
            await context.bot.send_message(
                chat_id=int(customer_id),
                text="❌ *Deposit Slip မအတည်မပြုနိုင်*\n\nSlip မှားနိုင်သည် — ပြန်ပို့ပါ",
                parse_mode='Markdown')
        except: pass
        await query.message.reply_text("❌ Deposit ပယ်ချပြီ")

    elif data.startswith("nodep_report_"):
        # Broker က Customer Deposit မလွှဲပါ button နှိပ်တာ → Admin confirm တောင်း
        req_id      = data.replace("nodep_report_", "")
        broker_tg   = str(query.from_user.id)
        brokers     = await get_brokers()
        broker_obj  = next((b for b in brokers if b.get("telegramId") == broker_tg), None)
        if not broker_obj:
            await query.answer("❌ Broker မဟုတ်ဘူး", show_alert=True); return

        session = proxy_sessions.get(req_id)
        if not session:
            await query.answer("❌ Session မတွေ့ပါ", show_alert=True); return

        customer_id_nd = session.get("customerId", "")
        nodep_pending[req_id] = {
            "customerId":  customer_id_nd,
            "brokerTgId":  broker_tg,
            "brokerId":    broker_obj.get("brokerId", ""),
        }

        admin_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Ban Customer", callback_data=f"nodep_ok_{req_id}"),
            InlineKeyboardButton("❌ ပယ်ချ",        callback_data=f"nodep_cancel_{req_id}"),
        ]])
        await notify_admins(context,
            f"⚠️ *Broker Report — Deposit မလွှဲပါ*\n\n"
            f"🆔 Request: `{req_id}`\n"
            f"👷 Broker #{broker_obj.get('brokerId','')}\n"
            f"👤 Customer: `{customer_id_nd}`\n\n"
            f"Customer ကို Ban ချမှတ်မည်လား?",
            reply_markup=admin_kb)
        await query.answer("✅ Admin ကို Report ပို့ပြီ", show_alert=True)

    elif data.startswith("nodep_ok_"):
        if query.from_user.id not in ADMIN_IDS:
            await query.answer("❌ Admin only", show_alert=True); return
        req_id     = data.replace("nodep_ok_", "")
        nd_data    = nodep_pending.pop(req_id, {})
        customer_id_nd = nd_data.get("customerId", "")
        broker_tg_nd   = nd_data.get("brokerTgId", "")

        # Ban count တွက်
        ban_count_nd = 0
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp_nd = await client.post(SHEET_WEBHOOK, json={
                    "action":     "getAuctionCancelCount",
                    "customerId": customer_id_nd,
                }, timeout=40)
            ban_count_nd = resp_nd.json().get("banCount", 0)
        except Exception as e:
            logger.error(f"nodep_ok banCount: {e}")

        new_ban = ban_count_nd + 1
        if new_ban == 1:
            ban_expire_nd = (datetime.now() + timedelta(days=7)).strftime("%d/%m/%Y")
            ban_status_nd = "BAN_7D"
            ban_label_nd  = f"⏳ 7 ရက် Ban (ကုန်ဆုံး: {ban_expire_nd})"
        elif new_ban == 2:
            ban_expire_nd = (datetime.now() + timedelta(days=30)).strftime("%d/%m/%Y")
            ban_status_nd = "BAN_1M"
            ban_label_nd  = f"⏳ 1 လ Ban (ကုန်ဆုံး: {ban_expire_nd})"
        else:
            ban_expire_nd = "LIFETIME"
            ban_status_nd = "LIFETIME_BAN"
            ban_label_nd  = "🚫 Lifetime Ban"

        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                await client.post(SHEET_WEBHOOK, json={
                    "action":     "saveAuctionCancel",
                    "customerId": customer_id_nd,
                    "username":   proxy_sessions.get(req_id, {}).get("customerUsername", ""),
                    "reqId":      req_id,
                    "banCount":   new_ban,
                    "banStatus":  ban_status_nd,
                    "banExpire":  ban_expire_nd,
                }, timeout=40)
        except Exception as e:
            logger.error(f"nodep_ok saveAuctionCancel: {e}")

        try:
            await context.bot.send_message(
                chat_id=int(customer_id_nd),
                text=(f"🚫 *Auction Ban*\n\n"
                      f"🆔 `{req_id}`\n\n"
                      f"Deposit မပေဘဲ Cancel လုပ်ခဲ့သောကြောင့်:\n"
                      f"{ban_label_nd}"),
                parse_mode='Markdown')
        except Exception as e:
            logger.error(f"nodep_ok customer notify: {e}")

        await query.edit_message_text(
            f"✅ Ban ချမှတ်ပြီ\n\n🆔 `{req_id}`\n👤 `{customer_id_nd}`\n{ban_label_nd}",
            parse_mode='Markdown')

    elif data.startswith("nodep_cancel_"):
        if query.from_user.id not in ADMIN_IDS:
            await query.answer("❌ Admin only", show_alert=True); return
        req_id = data.replace("nodep_cancel_", "")
        nodep_pending.pop(req_id, None)
        await query.edit_message_text("❌ Ban Report ပယ်ချပြီ")

    elif data.startswith("reqtype_"):
        parts       = data.split("_")
        svc_type    = parts[1]
        target_uid  = int(parts[2])

        if query.from_user.id != target_uid:
            await query.answer("❌ သင်၏ request မဟုတ်ဘူး", show_alert=True); return

        user_id = target_uid
        str_uid = str(user_id)

        existing_session = next(
            ((sid, s) for sid, s in proxy_sessions.items()
             if str(s.get("customerId","")) == str_uid and s.get("status") == "ACTIVE"),
            None
        )
        if existing_session:
            await query.answer("⚠️ Request တင်ပြီးသားရှိနေတယ်", show_alert=True); return
        if user_id in pending_request:
            await query.answer("⚠️ Request ဖြည်နေဆဲ", show_alert=True); return

        pending_request[user_id] = {"step": 0, "data": {"service_type": svc_type}}

        if svc_type == "auction":
            # ── Ban check ──
            ban_count  = 0
            ban_status = ""
            ban_expire = ""
            try:
                async with httpx.AsyncClient(follow_redirects=True) as client:
                    resp_ban = await client.post(SHEET_WEBHOOK, json={
                        "action":     "getAuctionCancelCount",
                        "customerId": str_uid,
                    }, timeout=40)
                ban_data   = resp_ban.json()
                ban_count  = ban_data.get("banCount", 0)
                ban_status = ban_data.get("banStatus", "")
                ban_expire = ban_data.get("banExpire", "")
            except Exception as e:
                logger.error(f"auction ban check: {e}")

            if ban_count > 0 and ban_status:
                if ban_status == "LIFETIME_BAN":
                    pending_request.pop(user_id, None)
                    await query.edit_message_text(
                        "🚫 *Auction Car — Lifetime Ban*\n\n"
                        "Deposit မပေဘဲ Cancel ၃ ကြိမ်ကျော်သောကြောင့်\n"
                        "Auction Car access ထာဝရပိတ်ပြီ",
                        parse_mode='Markdown')
                    return
                elif ban_expire and ban_expire != "LIFETIME":
                    try:
                        ep = ban_expire.split('/')
                        expire_dt = datetime(int(ep[2]), int(ep[1]), int(ep[0]))
                        if datetime.now() < expire_dt:
                            days_left = (expire_dt - datetime.now()).days + 1
                            pending_request.pop(user_id, None)
                            await query.edit_message_text(
                                f"⏳ *Auction Car — Temporary Ban*\n\n"
                                f"Deposit မပေဘဲ Cancel လုပ်ခဲ့သောကြောင့် Ban ဖြစ်နေသည်\n\n"
                                f"🗓 Ban ကုန်ဆုံးရက်: `{ban_expire}`\n"
                                f"⏰ ကျန်ရှိသည်: {days_left} ရက်",
                                parse_mode='Markdown')
                            return
                    except Exception as e:
                        logger.error(f"ban expire parse: {e}")

            await query.edit_message_text(
                "🏆 *လေလံဆွဲရန် Request*\n\n"
                "⚠️ မှတ်ချက် — လေလံနီးကပ်မှ Deposit မပေးပါနှင့်\n"
                "Broker Accept ပြီးမှ Deposit ပေးရမည်\n\n"
                "မေးချင်တဲ့ ကားအမည် ရိုက်ထည့်ပါ:\n"
                "ဥပမာ: `ALPHARD`, `X-TRAIL`, `HIACE VAN`\n\n"
                "Cancel လုပ်ရန်: /cancelrequest",
                parse_mode='Markdown')
        else:
            await query.edit_message_text(
                "🔍 *ကားရှာရန် Request*\n\n"
                "မေးချင်တဲ့ ကားအမည် ရိုက်ထည့်ပါ:\n"
                "ဥပမာ: `X-TRAIL`, `ALPHARD`, `HIACE VAN`\n\n"
                "Cancel လုပ်ရန်: /cancelrequest",
                parse_mode='Markdown')

    elif data.startswith("endchat_yes_"):
        req_id  = data.replace("endchat_yes_", "")
        user_id = str(query.from_user.id)
        brokers = await get_brokers()
        broker  = next((b for b in brokers if b.get("telegramId") == user_id), None)
        if not broker:
            await query.answer("❌ Broker မဟုတ်ဘူး", show_alert=True); return

        existing_session = proxy_sessions.get(req_id)
        if existing_session and str(existing_session.get("brokerId")) != user_id:
            await query.answer("❌ ဒီ Session က သင့်ဟာ မဟုတ်ပါ", show_alert=True); return

        session = proxy_sessions.pop(req_id, None)
        cancel_request_timer(req_id)
        new_broker_status = recalc_broker_status(user_id)
        await update_broker(user_id, status=new_broker_status)

        if session:
            try:
                async with httpx.AsyncClient(follow_redirects=True) as client:
                    await client.post(SHEET_WEBHOOK, json={
                        "action": "updateRequest",
                        "reqId":  req_id,
                        "status": "CLOSED",
                    }, timeout=40)
            except Exception as e:
                logger.error(f"endchat confirm: {e}")

            status_msg = {
                "FREE":        "🟢 FREE — Request အသစ် ၂ ခုထိ လက်ခံနိုင်ပြီ",
                "HAS_AUCTION": "🟡 Auction ၁ ခု ကျန်နေဆဲ — ကားရှာ request လက်ခံနိုင်ပြီ",
                "HAS_SEARCH":  "🟡 ကားရှာ ၁ ခု ကျန်နေဆဲ — Auction request လက်ခံနိုင်ပြီ",
            }.get(new_broker_status, "🟢 FREE")
            await query.edit_message_text(
                f"✅ *Session ပိတ်ပြီ*\n\n"
                f"🆔 `{req_id}`\n"
                f"{status_msg}",
                parse_mode='Markdown')

            customer_id = session.get("customerId")
            if customer_id:
                try:
                    rating_kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton("⭐1", callback_data=f"rate_1_{req_id}"),
                         InlineKeyboardButton("⭐2", callback_data=f"rate_2_{req_id}"),
                         InlineKeyboardButton("⭐3", callback_data=f"rate_3_{req_id}")],
                        [InlineKeyboardButton("⭐4", callback_data=f"rate_4_{req_id}"),
                         InlineKeyboardButton("⭐5", callback_data=f"rate_5_{req_id}")],
                    ])
                    await context.bot.send_message(
                        chat_id=int(customer_id),
                        text=f"🌟 *Broker ကို Rate လုပ်ပေးပါ*\n\n"
                             f"🆔 Request: `{req_id}`\n\n"
                             f"⭐1 = ညံ့ | ⭐3 = ပုံမှန် | ⭐5 = အကောင်းဆုံး",
                        parse_mode='Markdown',
                        reply_markup=rating_kb)
                    pending_rating[str(customer_id)] = {
                        "reqId":      req_id,
                        "brokerId":   broker["brokerId"],
                        "brokerTgId": user_id,
                    }
                except Exception as e:
                    logger.error(f"endchat rating prompt: {e}")
        else:
            await query.edit_message_text("✅ FREE ဖြစ်ပြီ")

    elif data.startswith("endchat_no_"):
        req_id = data.replace("endchat_no_", "")
        await query.edit_message_text(
            f"↩️ *Cancel — Session ဆက်ဖွင့်နေဆဲ*\n\n"
            f"🆔 `{req_id}`\n"
            f"💬 Chat ဆက်လုပ်နိုင်ပါသည်",
            parse_mode='Markdown')

    elif data.startswith("breq_accept_"):
        req_id  = data.replace("breq_accept_", "")
        user_id = str(query.from_user.id)
        brokers = await get_brokers()
        broker  = next((b for b in brokers if b.get("telegramId") == user_id), None)
        if not broker:
            await query.answer("❌ Broker မဟုတ်ဘူး", show_alert=True); return
        if broker.get("status") == "BANNED":
            await query.answer("🚫 Account ပိတ်သိမ်းထားပြီ", show_alert=True); return
        if req_id in proxy_sessions:
            await query.answer("❌ ဒီ Request ကို တခြား Broker လက်ခံပြီးသားပါ", show_alert=True); return

        customer_id = None; customer_username = ""; req_data = {}
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await client.post(SHEET_WEBHOOK, json={
                    "action": "getRequest", "reqId": req_id,
                }, timeout=40)
            rdata = resp.json()
            if rdata.get("status") == "ok":
                customer_id       = rdata.get("customerId")
                customer_username = rdata.get("username", "")
                req_data          = rdata
            else:
                await query.answer(f"❌ Request {req_id} မတွေ့ဘူး", show_alert=True); return
        except Exception as e:
            logger.error(f"breq_accept getRequest: {e}")
            await query.answer("❌ Sheet error", show_alert=True); return

        # Mirror accept_cmd's capacity/service-type logic exactly (same
        # active_types check, same status vocabulary) so a broker who
        # accepts via this button and one who accepts via /accept are
        # tracked consistently instead of colliding on capacity later.
        svc_type     = "auction" if req_data.get("carType", "").lower() == "auction" else "search"
        active_types = get_broker_session_types(user_id)
        if svc_type in active_types:
            await query.answer("❌ Session တူ ရှိပြီးသား", show_alert=True); return
        if len(active_types) >= 2:
            await query.answer("❌ Order ၂ ခု ပြည့်နေပြီ", show_alert=True); return

        # Claim the request synchronously (no await between the check and
        # the write) so two brokers racing to accept the same broadcast
        # request can't both win — the loser sees "already accepted".
        if req_id in proxy_sessions:
            await query.answer("❌ ဒီ Request ကို တခြား Broker လက်ခံပြီးသားပါ", show_alert=True); return
        new_status = "FULL" if (svc_type == "auction" and "search" in active_types) or (svc_type == "search" and "auction" in active_types) else ("HAS_AUCTION" if svc_type == "auction" else "HAS_SEARCH")
        proxy_sessions[req_id] = {
            "customerId":       customer_id,
            "customerUsername": customer_username,
            "brokerId":         user_id,
            "brokerObj":        broker,
            "reqId":            req_id,
            "status":           "ACTIVE",
            "serviceType":      svc_type,
            "startTime":        datetime.now().isoformat(),
        }

        await update_broker(user_id, status=new_status)
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                await client.post(SHEET_WEBHOOK, json={
                    "action": "updateRequest", "reqId": req_id,
                    "status": "MATCHED", "brokerId": broker["brokerId"],
                }, timeout=40)
        except Exception as e:
            logger.error(f"breq_accept updateRequest: {e}")

        await query.edit_message_text(
            f"✅ *Request လက်ခံပြီ!*\n\n"
            f"🆔 `{req_id}`\n"
            f"🚗 {req_data.get('carType','')}\n"
            f"💰 {req_data.get('budget','')}\n\n"
            f"💬 Customer ကို message ပို့နိုင်ပြီ\n"
            f"ပြီးရင်: `/endchat {req_id}`",
            parse_mode='Markdown')

        if customer_id:
            try:
                _b_rating = float(broker.get("rating", 0) or 0)
                _b_deals  = broker.get("deals", 0) or 0
                _b_rating_str = f"⭐ {_b_rating:.1f} | Deals: {_b_deals}" if _b_rating > 0 else f"🆕 New Broker | Deals: {_b_deals}"
                await context.bot.send_message(
                    chat_id=int(customer_id),
                    text=(f"🎉 *Broker ရှာပေးနေပြီ!*\n\n"
                          f"🆔 Request: `{req_id}`\n"
                          f"👷 Broker #{broker['brokerId']} က သင့် Request လက်ခံပြီ\n"
                          f"{_b_rating_str}\n\n"
                          f"ကားရှာပေးနေတယ် ⏳\n"
                          f"Status စစ်ရန်: /mystatus"),
                    parse_mode='Markdown')
            except Exception as e:
                logger.error(f"breq_accept customer notify: {e}")

        await notify_admins(context,
            f"🤝 *Broker Accept ပြီ (Button)*\n\n"
            f"🆔 `{req_id}`\n"
            f"👷 #{broker['brokerId']} @{broker['username']}\n"
            f"👤 Customer: @{customer_username}")

        start_request_timer(context, req_id=req_id,
            broker_tg_id=user_id, broker_id=broker["brokerId"],
            customer_id=str(customer_id) if customer_id else "")

        if req_id.startswith("A") and customer_id:
            try:
                dep_kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "💰 Deposit ฿20,000 ပေးမည်",
                        callback_data=f"dep_start_{req_id}_{user_id}")
                ]])
                await context.bot.send_message(
                    chat_id=int(customer_id),
                    text=(f"🎉 *Broker ရှာပြီ — Deposit လိုအပ်ပါသည်*\n\n"
                          f"🆔 `{req_id}`\n"
                          f"👷 Broker #{broker['brokerId']}\n\n"
                          f"⚠️ မှတ်ချက် — လေလံနီးကပ်မှ Deposit မပေးပါနှင့်\n"
                          f"လေလံမစခင် 1 နာရီအလိုထိ Deposit ပေးဖို့ အချိန်ရပါသည်\n\n"
                          f"အောက်ပါ button နှိပ်ပြီး Slip ပို့ပါ 👇"),
                    parse_mode='Markdown',
                    reply_markup=dep_kb)
            except Exception as e:
                logger.error(f"breq_accept auction dep notify: {e}")

            nodep_kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "⚠️ Customer Deposit မလွှဲပါ",
                    callback_data=f"nodep_report_{req_id}")
            ]])
            await query.message.reply_text(
                f"ℹ️ *Deposit သတိပေးချက်*\n\n"
                f"🆔 `{req_id}`\n\n"
                f"Admin ဆီမှ Deposit Confirm မရသေးရင် Customer ကို သတိပေးပါ\n"
                f"Customer က Deposit မလွှဲတော့ဘူးဆိုရင် 👇",
                parse_mode='Markdown',
                reply_markup=nodep_kb)

    elif data.startswith("breq_decline_"):
        req_id      = data.replace("breq_decline_", "")
        user_id_dec = str(query.from_user.id)
        await query.edit_message_text(
            f"❌ *Request ငြင်းပယ်ပြီ*\n\n🆔 `{req_id}`\n\nRequest အသစ် ထပ်လာရင် notify ပေးမည် 🔔",
            parse_mode='Markdown')
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                await client.post(SHEET_WEBHOOK, json={
                    "action":     "incrementDecline",
                    "telegramId": user_id_dec,
                }, timeout=40)
        except Exception as e:
            logger.error(f"incrementDecline: {e}")

    # ── NEW: Broker session selector callback ──
    elif data.startswith("bsel_"):
        parts        = data.split("_", 2)
        broker_tg_id = parts[1]
        target_req   = parts[2]
        if str(query.from_user.id) != broker_tg_id:
            await query.answer("❌ သင့် button မဟုတ်ဘူး", show_alert=True)
            return
        pending = pending_broker_target.pop(broker_tg_id, None)
        if not pending:
            await query.answer("❌ Pending message ကုန်သွားပြီ", show_alert=True)
            return
        if target_req == "cancel":
            await query.edit_message_text("❌ မပို့တော့ဘူး — OK")
            return
        session = proxy_sessions.get(target_req)
        if not session:
            await query.edit_message_text("❌ Session မတွေ့ပါ")
            return
        customer_id   = session.get("customerId")
        broker_obj    = session.get("brokerObj", {})
        broker_id_val = broker_obj.get("brokerId", "B???")
        if pending.get("is_photo") and pending.get("file_bytes"):
            from io import BytesIO
            cap      = pending.get("caption", "")
            cap_text = f"📷 *Broker #{broker_id_val}:\n\n{cap}" if cap else f"📷 *Broker #{broker_id_val}*"
            bio = BytesIO(pending["file_bytes"]); bio.name = "photo.jpg"
            try:
                await context.bot.send_photo(chat_id=int(customer_id), photo=bio,
                    caption=cap_text, parse_mode='Markdown')
                await log_chat_message(target_req, broker_tg_id, f"Broker#{broker_id_val}", "photo", cap)
                await query.edit_message_text(f"✅ {target_req} ဆီ ပုံ ပို့ပြီ")
            except Exception as e:
                logger.error(f"bsel photo: {e}")
                await query.edit_message_text("❌ Customer ကို မပို့နိုင်ဘူး")
        else:
            txt = pending.get("text", "")
            try:
                await context.bot.send_message(chat_id=int(customer_id),
                    text=f"💬 *Broker #{broker_id_val}:\n\n{txt}", parse_mode='Markdown')
                await log_chat_message(target_req, broker_tg_id, f"Broker#{broker_id_val}", "text", txt)
                await query.edit_message_text(f"✅ {target_req} ဆီ ပို့ပြီ")
            except Exception as e:
                logger.error(f"bsel text: {e}")
                await query.edit_message_text("❌ Customer ကို မပို့နိုင်ဘူး")

    elif data.startswith("rate_"):
        parts      = data.split("_")
        stars      = int(parts[1])
        req_id     = parts[2]
        rater_id   = str(query.from_user.id)

        rate_info  = pending_rating.pop(rater_id, None)
        if not rate_info or rate_info["reqId"] != req_id:
            await query.answer("⚠️ Rating ကုန်သွားပြီ", show_alert=True)
            return

        broker_id    = rate_info["brokerId"]
        broker_tg_id = rate_info["brokerTgId"]
        ban = False; new_rating = 0; one_star_count = 0

        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await client.post(SHEET_WEBHOOK, json={
                    "action":     "saveRating",
                    "reqId":      req_id,
                    "brokerId":   broker_id,
                    "stars":      stars,
                    "customerId": rater_id,
                }, timeout=40)
            result         = resp.json()
            ban            = result.get("ban", False)
            new_rating     = result.get("newRating", 0)
            one_star_count = result.get("oneStarCount", 0)
        except Exception as e:
            logger.error(f"saveRating: {e}")

        star_display = "⭐" * stars
        report_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ လုပ်ငန်းပြီဆုံး၊ အဆင်ပြေပါတယ်", callback_data=f"report_ok_{req_id}")],
            [InlineKeyboardButton("⚠️ လုပ်ငန်းမပြီးစုံ",               callback_data=f"report_incomplete_{req_id}")],
            [InlineKeyboardButton("🚗 ကားမမှန်ကန်",                     callback_data=f"report_wrongcar_{req_id}")],
            [InlineKeyboardButton("❌ ကားမရှာပေ",                       callback_data=f"report_nosearch_{req_id}")],
        ])
        await query.edit_message_text(
            f"✅ *Rating ပေးပြီ — {star_display} ({stars}/5)*\n\n"
            f"🆔 `{req_id}`\n\n"
            f"လုပ်ငန်းဆောင်တာ မည်သို့ဖြစ်ပါသလဲ? 👇",
            parse_mode='Markdown',
            reply_markup=report_kb)

        try:
            await context.bot.send_message(
                chat_id=int(broker_tg_id),
                text=f"⭐ *Rating ရပြီ*\n\n🆔 `{req_id}`\n{star_display} ({stars}/5)",
                parse_mode='Markdown')
        except Exception as e:
            logger.error(f"rating notify broker: {e}")

        if ban:
            await update_broker(broker_tg_id, status="BANNED")
            await notify_admins(context,
                f"🚨 *Broker BAN!*\n\n🆔 #{broker_id}\n"
                f"⭐1 × 3 ကြိမ် ရောက်ပြီ → BANNED")
            try:
                await context.bot.send_message(
                    chat_id=int(broker_tg_id),
                    text="🚨 *Broker Account ပိတ်ခံရပြီ*\n\n"
                         "⭐1 Rating ၃ ကြိမ် ရောက်သောကြောင့်\nAdmin ကို ဆက်သွယ်ပါ",
                    parse_mode='Markdown')
            except Exception as e:
                logger.error(f"ban notify: {e}")

        await notify_admins(context,
            f"⭐ *Rating တင်ပြီ*\n\n🆔 `{req_id}`\n"
            f"👷 Broker: #{broker_id}\n{star_display} ({stars}/5)\n"
            + (f"📊 Average: {float(new_rating):.1f}" if new_rating else ""))
    

# ── Membership Commands ────────────────────────────────
async def approve_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not ADMIN_IDS or user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်"); return
    if len(context.args) < 2:
        await update.message.reply_text("❌ Format: `/approve @username 1` သို့မဟုတ် `/approve 123456789 3`",
                                        parse_mode='Markdown'); return
    username_or_id = context.args[0].replace('@','')
    try:
        months = int(context.args[1])
    except:
        await update.message.reply_text("❌ လ ဂဏန်းထည့်ပါ", parse_mode='Markdown'); return
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

    password = generate_password() if package == "WEB" else ""
    target_user_id = str(member_id) if member_id else username_or_id
    approved_by = str(getattr(update.effective_user, "username", "") or user_id)
    # Same user/package/period within one 10-minute bucket is one manual action.
    # Repeating the command therefore returns duplicate instead of extending twice.
    operation_bucket = int(datetime.now(timezone.utc).timestamp() // 600)
    operation_id = f"MANUAL-{target_user_id}-{package}-{days}-{operation_bucket}"
    atomic_result = await approve_manual_member_transaction({
        "userId": target_user_id,
        "username": member_username,
        "days": days,
        "months": months,
        "password": password,
        "package": package,
        "approvedBy": approved_by,
        "operationId": operation_id,
    })
    if atomic_result.get("status") != "ok":
        message = atomic_result.get("message")
        if message in {"transaction_in_progress", "transaction_review_required", "member_finance_review_required"}:
            text = (
                "⚠️ Manual approval ကို ဆက်မနှိပ်ပါနှင့်။\n"
                "Member/Finance transaction သည် စစ်ဆေးရန်လိုနေပါသည်။\n"
                "Finance row နှင့် Members row ကို Admin က စစ်ပြီးမှသာ ဆက်လုပ်ပါ။"
            )
        else:
            text = "❌ Atomic manual approval မအောင်မြင်သေးပါ။ Membership Approved မဖြစ်သေးပါ။"
        await update.message.reply_text(text, parse_mode="HTML")
        return
    if atomic_result.get("duplicate") or atomic_result.get("result") == "recovered":
        await update.message.reply_text(
            "⚠️ ဒီ Manual approval သည် အရင်က အတည်ပြုပြီးသားဖြစ်ပါသည်။\n"
            "Member သက်တမ်းကို ထပ်မတိုးထားပါ။ Finance row အသစ် မဖန်တီးထားပါ။",
            parse_mode="HTML")
        return

    member = atomic_result.get("member") or {}
    canonical_password = str(atomic_result.get("password") or member.get("password") or password or "")
    canonical_expire = str(member.get("expireDate") or "")
    canonical_package = str(atomic_result.get("package") or member.get("package") or package).upper()
    invite_url = await create_invite_link(context, days, member_id)
    if member_id:
        await send_approval_dm(
            context, member_id, months, canonical_password, invite_url,
            package=canonical_package, expire_date=canonical_expire)

    expire_date = canonical_expire or (datetime.now() + timedelta(days=days)).strftime("%d/%m/%Y")
    password_line = (
        f"🔑 Password: <code>{canonical_password}</code>\n"
        if canonical_package == "WEB" and canonical_password else ""
    )
    txt = (f"✅ <b>Membership Approved!</b>\n\n"
           f"👤 @{member_username}\n"
           f"🆔 <code>{member_id or 'N/A'}</code>\n"
           f"📦 Package: {PLAN_NAMES.get(canonical_package, canonical_package)}\n"
           f"📅 <b>{months} လ</b>\n"
           f"⏰ ကုန်ဆုံး: <code>{expire_date}</code>\n"
           f"{password_line}")
    if invite_url: txt += f"\n🔗 {invite_url}"
    await update.message.reply_text(txt, parse_mode='HTML')

async def members_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not ADMIN_IDS or user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်"); return
    try:
        async with httpx.AsyncClient() as client:
            resp    = await client.post(SHEET_WEBHOOK, json={"action":"getMembers","serverKey":SHEET_SERVER_KEY}, timeout=40, follow_redirects=True)
            members = resp.json().get("members",[])
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}"); return
    if not members:
        await update.message.reply_text("👥 Member မရှိသေးဘူး"); return
    active  = [m for m in members if m.get('status') == 'ACTIVE']
    expired = [m for m in members if m.get('status') == 'EXPIRED']
    kicked  = [m for m in members if m.get('status') == 'KICKED']

    def pkg_label(pkg):
        if pkg == 'WEB':      return '💎 WEB'
        if pkg == 'CH-PROMO': return '🎁 PROMO'
        return '📱 CH'

    txt = f"👥 *Members*\n✅ Active: {len(active)} | ❌ Expired: {len(expired)} | 🚫 Kicked: {len(kicked)}\n\n"
    txt += "⚠️ _Member ဖယ်ရှားရန် `/kick ID` သာ သုံးပါ — Sheet တိုက်ရိုက် မဖျက်ရ_\n\n"
    txt += "*✅ Active:*\n"
    for m in active:
        label = pkg_label(m.get('package','CH'))
        txt += f"• @{m['username']} {label} — ကုန်: `{m.get('expireDate','?')}`\n"
    if expired:
        txt += "\n*❌ Expired:*\n"
        for m in expired[:5]:
            label = pkg_label(m.get('package','CH'))
            txt += f"• @{m['username']} {label} — `{m.get('expireDate','?')}`\n"
    if kicked:
        txt += "\n*🚫 Kicked:*\n"
        for m in kicked[:3]:
            txt += f"• @{m['username']} — `{m.get('expireDate','?')}`\n"
    await update.message.reply_text(txt, parse_mode='Markdown')

async def kick_member_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not ADMIN_IDS or user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်"); return
    if not context.args:
        await update.message.reply_text("❌ Format: `/kick 123456789`", parse_mode='Markdown'); return
    try:
        target_id = int(context.args[0])
        sheet_ok = False
        if SHEET_WEBHOOK:
            try:
                async with httpx.AsyncClient(follow_redirects=True) as client:
                    resp = await client.post(SHEET_WEBHOOK, json={
                        "action": "updateStatus", "serverKey": SHEET_SERVER_KEY,
                        "userId": str(target_id),
                        "status": "KICKED"
                    }, timeout=40)
                sheet_ok = resp.json().get("status") == "ok"
            except Exception as e:
                logger.error(f"kick sheet: {e}")

        ch_ok = await kick_with_retry(context, target_id)

        if ch_ok and sheet_ok:
            await update.message.reply_text(
                f"✅ *Kick အောင်မြင်ပြီ*\n\n🆔 `{target_id}`\n📋 Sheet ထဲကပါ ဖျက်ပြီ ✅\n📢 Channel ကပါ ထုတ်ပြီ ✅",
                parse_mode='Markdown')
        elif ch_ok and not sheet_ok:
            await update.message.reply_text(
                f"⚠️ Channel ကထုတ်ပြီ ✅\n❌ Sheet ထဲကပါ ဖျက်မရ — ကိုယ်တိုင် ဖျက်ပါ",
                parse_mode='Markdown')
        elif sheet_ok and not ch_ok:
            await update.message.reply_text(
                f"⚠️ Sheet ထဲကဖျက်ပြီ ✅\n❌ Channel ကထုတ်မရ — Member ကိုယ်တိုင် ထွက်ပြီးသားဖြစ်နိုင်",
                parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ Kick မအောင်မြင်ပါ — စစ်ဆေးပါ")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

# ── Broker Helper ─────────────────────────────────────
def gen_broker_id() -> str:
    chars = string.ascii_uppercase + string.digits
    return 'B' + ''.join(random.choices(chars, k=4))

async def get_sheet_car_count() -> int:
    if not SHEET_WEBHOOK: return len(CARS)
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.post(SHEET_WEBHOOK,
                json={"action": "getCarsCount"}, timeout=40)
        return resp.json().get("count", len(CARS))
    except Exception:
        return len(CARS)

async def get_brokers() -> list:
    if not SHEET_WEBHOOK: return []
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.post(SHEET_WEBHOOK, json={"action":"getBrokers"}, timeout=40)
        return resp.json().get("brokers", [])
    except Exception as e:
        logger.error(f"getBrokers: {type(e).__name__} {e}")
        return []

def get_broker_session_types(broker_tg_id: str) -> set:
    types = set()
    for sid, s in proxy_sessions.items():
        if str(s.get("brokerId","")) == broker_tg_id and s.get("status") == "ACTIVE":
            svc = s.get("serviceType", "search")
            types.add(svc)
    return types

def recalc_broker_status(broker_tg_id: str) -> str:
    types = get_broker_session_types(broker_tg_id)
    if not types:
        return "FREE"
    if "auction" in types and "search" in types:
        return "FULL"
    if "auction" in types:
        return "HAS_AUCTION"
    if "search" in types:
        return "HAS_SEARCH"
    return "FREE"

async def update_broker(telegram_id: str, **kwargs) -> bool:
    if not SHEET_WEBHOOK: return False
    try:
        payload = {"action": "updateBroker", "telegramId": telegram_id}
        payload.update(kwargs)
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.post(SHEET_WEBHOOK, json=payload, timeout=40)
        return resp.json().get("status") == "ok"
    except Exception as e:
        logger.error(f"updateBroker: {e}")
        return False

async def addbroker_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not ADMIN_IDS or user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်"); return
    if not context.args:
        await update.message.reply_text(
            "❌ Format: `/addbroker @username 123456789`\n"
            "ဥပမာ: `/addbroker @Ko_Aung 987654321`",
            parse_mode='Markdown'); return
    try:
        username  = context.args[0].replace("@","").strip()
        tg_id     = context.args[1].strip() if len(context.args) > 1 else ""
        if not tg_id.isdigit():
            await update.message.reply_text("❌ Telegram ID ဂဏန်းဖြစ်ရမည်"); return

        broker_id = gen_broker_id()
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.post(SHEET_WEBHOOK, json={
                "action":     "addBroker",
                "brokerId":   broker_id,
                "telegramId": tg_id,
                "username":   username,
            }, timeout=40)
        if resp.json().get("status") == "ok":
            try:
                await context.bot.send_message(
                    chat_id=int(tg_id),
                    text=(f"🎉 *Japan Auction Car Checker*\n\n"
                          f"✅ Broker အဖြစ် ထည့်သွင်းပြီ!\n\n"
                          f"🆔 Broker ID: `{broker_id}`\n\n"
                          f"အောက်က Button နှိပ်ပြီး စတင်ပါ 👇"),
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("👷 Broker စတင်ရန်", callback_data=f"brokerstart_{tg_id}")
                    ]]))
            except Exception as e:
                logger.error(f"addbroker DM: {e}")

            await update.message.reply_text(
                f"✅ *Broker ထည့်ပြီ*\n\n"
                f"👤 @{username}\n"
                f"🆔 ID: `{broker_id}`\n"
                f"📨 DM ပို့ပြီ — `/brokerstart` နှိပ်ဖို့ ပြောပြီ",
                parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Sheet error — ထပ်ကြိုးစားပါ")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def kickbroker_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not ADMIN_IDS or user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်"); return
    if not context.args:
        await update.message.reply_text(
            "❌ Format: `/kickbroker 123456789`",
            parse_mode='Markdown'); return
    try:
        tg_id = context.args[0].strip()
        if not tg_id.isdigit():
            await update.message.reply_text("❌ Telegram ID ဂဏန်းဖြစ်ရမည်"); return

        brokers = await get_brokers()
        broker = next((b for b in brokers if str(b.get("telegramId","")) == tg_id), None)
        if not broker:
            await update.message.reply_text(f"❌ Broker ID `{tg_id}` မရှိဘူး", parse_mode='Markdown'); return

        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.post(SHEET_WEBHOOK, json={
                "action":     "removeBroker", "serverKey": SHEET_SERVER_KEY,
                "telegramId": tg_id,
            }, timeout=40)

        if resp.json().get("status") == "ok":
            try:
                await context.bot.send_message(
                    chat_id=int(tg_id),
                    text="🚫 *Japan Auction Car Checker*\n\nသင်၏ Broker အကောင့် ပိတ်သိမ်းလိုက်ပါပြီ။\nAdmin ကို ဆက်သွယ်ပါ။",
                    parse_mode='Markdown')
            except Exception as e:
                logger.error(f"kickbroker DM: {e}")

            await update.message.reply_text(
                f"✅ *Broker ဖြတ်ပြီ*\n\n"
                f"👤 @{broker.get('username','?')}\n"
                f"🆔 TG ID: `{tg_id}`",
                parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Sheet error — ထပ်ကြိုးစားပါ")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def brokers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not ADMIN_IDS or user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်"); return

    brokers = await get_brokers()
    if not brokers:
        await update.message.reply_text("👷 Broker မရှိသေးဘူး — `/addbroker` နဲ့ ထည့်ပါ", parse_mode='Markdown'); return

    free      = [b for b in brokers if b.get("status") == "FREE"]
    has_auc   = [b for b in brokers if b.get("status") == "HAS_AUCTION"]
    has_srch  = [b for b in brokers if b.get("status") == "HAS_SEARCH"]
    full      = [b for b in brokers if b.get("status") == "FULL"]
    other     = [b for b in brokers if b.get("status") not in ("FREE","HAS_AUCTION","HAS_SEARCH","FULL")]

    def badge(b):
        deals  = b.get("deals", 0)
        rating = b.get("rating", 0)
        if deals >= 20 and rating >= 4.5: return "🥇"
        if deals >= 10 and rating >= 3.5: return "🥈"
        return "🥉"

    def rating_stars(r):
        r = float(r) if r else 0
        return f"⭐{r:.1f}" if r > 0 else "🆕 New"

    txt = f"👷 *Broker List ({len(brokers)} ယောက်)*\n\n"
    if free:
        txt += "🟢 *FREE (ရနိုင်):*\n"
        for b in free:
            txt += f"  {badge(b)} #{b['brokerId']} @{b['username']} {rating_stars(b['rating'])} | Deals: {b.get('deals',0)}\n"
    if has_auc:
        txt += "\n🏆 *HAS AUCTION:*\n"
        for b in has_auc:
            txt += f"  {badge(b)} #{b['brokerId']} @{b['username']} {rating_stars(b['rating'])}\n"
    if has_srch:
        txt += "\n🔍 *HAS SEARCH:*\n"
        for b in has_srch:
            txt += f"  {badge(b)} #{b['brokerId']} @{b['username']} {rating_stars(b['rating'])}\n"
    if full:
        txt += "\n🔴 *FULL:*\n"
        for b in full:
            txt += f"  {badge(b)} #{b['brokerId']} @{b['username']} {rating_stars(b['rating'])}\n"
    if other:
        txt += "\n⚫ *Others:*\n"
        for b in other:
            txt += f"  #{b['brokerId']} @{b['username']} — {b.get('status','?')}\n"

    await update.message.reply_text(txt, parse_mode='Markdown')

async def brokerstart_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    user_id = str(user.id)

    brokers = await get_brokers()
    broker  = next((b for b in brokers if b.get("telegramId") == user_id), None)
    if not broker:
        await update.message.reply_text(
            "❌ Broker အဖြစ် မှတ်ပုံမတင်ရသေးဘူး\nAdmin ကို ဆက်သွယ်ပါ"); return

    broker_id = broker['brokerId']
    tc_text = (
        f"🤝 *Japan Auction Car Checker T&C*\n\n"
        f"🆔 Broker ID: `{broker_id}`\n\n"
        f"အောက်ပါ စည်ကမ်းများကို သဘောတူကြောင်း confirm လုပ်ပါ:\n\n"
        f"① တစ်ချိန်တည်း Customer ၁ ယောက်သာ\n"
        f"② Bot ထဲမှာပဲ ဆက်သွယ်ရမည်\n"
        f"③ Condition Report မှန်ကန်စွာ ပေးရမည်\n"
        f"④ Photo အနည်းဆုံး ၁၀ ပုံ ပေးရမည်\n"
        f"⑤ ကားနဲ့ ပတ်သက်ပြီး အမှားအယွင်း မဖြစ်အောင် လုပ်ဆောင်ပေးရမည်\n"
        f"⑥ အမှားအယွင်း ဖြစ်ပေါ်ပါက Admin စိစစ်၍ Admin ၏ အဆုံးအဖြတ်ကို လိုက်နာရမည်\n"
        f"⑦ Platform ပြင်ပ Deal = Lifetime Ban\n"
        f"⑧ Rating 1 × 3 = Permanent Ban\n\n"
        f"သဘောတူမတူ အောက်က Button နှိပ်ပါ 👇"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ သဘောတူပါတယ်",  callback_data=f"tc_agree_{user_id}"),
        InlineKeyboardButton("❌ သဘောမတူပါ",     callback_data=f"tc_disagree_{user_id}"),
    ]])
    await update.message.reply_text(tc_text, parse_mode='Markdown', reply_markup=kb)

async def available_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    brokers = await get_brokers()
    broker  = next((b for b in brokers if b.get("telegramId") == user_id), None)
    if not broker:
        await update.message.reply_text("❌ Broker မဟုတ်ဘူး"); return

    ok = await update_broker(user_id, status="FREE")
    if ok:
        await update.message.reply_text(
            f"🟢 *Available ဖြစ်ပြီ*\n\n🆔 #{broker['brokerId']}\nRequest လက်ခံနိုင်ပြီ ✅",
            parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Update မအောင်မြင်ပါ")

async def busy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    brokers = await get_brokers()
    broker  = next((b for b in brokers if b.get("telegramId") == user_id), None)
    if not broker:
        await update.message.reply_text("❌ Broker မဟုတ်ဘူး"); return

    ok = await update_broker(user_id, status="BUSY")
    if ok:
        await update.message.reply_text(
            f"🔴 *Busy ဖြစ်ပြီ*\n\n🆔 #{broker['brokerId']}\nRequest အသစ် လက်မခံနိုင်တော့ဘူး",
            parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Update မအောင်မြင်ပါ")

# ── /carrequest ─────────────────────────────────────
REQ_STEPS = ["car_name","year","grade","budget","condition","timeline"]
REQ_LABELS = {
    "car_name":  "🚗 ကားအမည်",
    "year":      "📅 ထုတ်လုပ်သည့် နှစ်",
    "grade":     "🔧 Grade / Features",
    "budget":    "💰 Budget",
    "condition": "⭐ Condition",
    "timeline":  "⏳ Timeline",
}

async def carrequest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    user_id = user.id
    str_uid = str(user_id)

    if not await is_active_member(user_id):
        await update.message.reply_text(
            "🔒 *Member များသာ သုံးနိုင်ပါသည်*\n\nMembership ရယူရန် /newmember နှိပ်ပါ",
            parse_mode='Markdown')
        return

    pkg = await get_member_package(user_id)
    if pkg == "PROMO10D" or (await check_promo10d_eligibility(str_uid)).get("active"):
        cancel_count = await get_cancel_count(str_uid)
        if cancel_count >= 2:
            await update.message.reply_text(
                "❌ *10 Day Promo — Request ကုန်သွားပြီ*\n\n"
                "Cancel ၂ ကြိမ် ပြည့်သောကြောင့် ထပ်မတင်နိုင်ပါ\n"
                "Member အသစ်ဝင်ရန်: /newmember",
                parse_mode='Markdown')
            return

    existing_session = next(
        ((sid, s) for sid, s in proxy_sessions.items()
         if str(s.get("customerId","")) == str_uid and s.get("status") == "ACTIVE"),
        None
    )
    if existing_session:
        _, sess = existing_session
        await update.message.reply_text(
            f"⚠️ *Request တင်ပြီးသားရှိနေတယ်*\n\n"
            f"🆔 `{sess.get('reqId','')}`\n\n"
            f"Status စစ်ရန်: /mystatus\n"
            f"Cancel လုပ်ရန်: /cancelrequest",
            parse_mode='Markdown')
        return

    if user_id in pending_request:
        await update.message.reply_text(
            "⚠️ Request ဖြည်နေဆဲရှိတယ် — ဆက်ဖြည့်ပါ\nCancel လုပ်ရန်: /cancelrequest")
        return

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ သဘောတူပါတယ်", callback_data=f"cust_tc_agree_{user_id}"),
        InlineKeyboardButton("❌ သဘောမတူပါ",    callback_data=f"cust_tc_disagree_{user_id}"),
    ]])
    await update.message.reply_text(
        "📜 *Japan Auction Car Checker*\n"
        "*— Customer စည်းကမ်းချက်များ —*\n\n"
        "① Customer အနေဖြင့် ကားဝယ်ယူရန် သေချာမှသာ "
        "*ကားရှာမည်* ကို နှိပ်ပေးပါ\n\n"
        "② Customer အနေဖြင့် မိမိ၏ လိုအပ်ချက်များကို "
        "Broker အား အသေးစိတ် ပြောပြပေးပါ\n\n"
        "③ ကားယူပြီး *Cancel မလုပ်ဖို့* မေတ္တာရပ်ခံပါသည်\n\n"
        "④ ဆက်သွယ်ရာတွင် *စာသား* ဖြင့် အဓိက ဆက်သွယ်ပေးစေချင်ပါသည် — "
        "အမှားအယွင်း ဖြစ်ပါက သက်သေအဖြစ် ပြသနိုင်ရန်\n\n"
        "⑤ ကားဝယ်ယူရာတွင် အမှားအယွင်း ဖြစ်ပေါ်လာပါက "
        "Admin ၏ စိစစ်ချက်ကို လက်ခံပေးရမည် ဖြစ်ပါသည်\n\n"
        "⑥ ဝန်ဆောင်ခ *฿3,000* ကောက်ခံပါသည်\n\n"
        "သဘောတူမတူ အောက်က Button နှိပ်ပါ 👇",
        parse_mode='Markdown',
        reply_markup=kb)

async def cancelrequest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    user_id = update.effective_user.id
    str_uid = str(user_id)

    if user_id in pending_request:
        pending_request.pop(user_id)
        await update.message.reply_text("❌ Request ပယ်ဖျက်ပြီ")
        return

    session_data = next(
        ((sid, s) for sid, s in proxy_sessions.items()
         if str(s.get("customerId","")) == str_uid and s.get("status") == "ACTIVE"),
        None
    )

    if not session_data:
        await update.message.reply_text(
            "❌ Active request မရှိဘူး\n\n"
            "ကားတောင်းဆိုရန်: /carrequest")
        return

    sid, session = session_data
    req_id       = session.get("reqId", sid)

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            dep_resp = await client.post(SHEET_WEBHOOK, json={
                "action": "getDeposit",
                "reqId":  req_id,
            }, timeout=40)
        dep = dep_resp.json()
        if dep.get("status") == "ok" and dep.get("depositStatus") in ("HOLD","WON"):
            await update.message.reply_text(
                f"🚫 *Cancel မလုပ်နိုင်ပါ*\n\n"
                f"🆔 `{req_id}`\n\n"
                f"Deposit ฿20,000 ပေးပြီးသောကြောင့်\n"
                f"Cancel လုပ်ခွင့် မရှိတော့ပါ",
                parse_mode='Markdown')
            return
    except Exception as e:
        logger.error(f"cancelrequest deposit check: {e}")

    cancel_count = 0
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            count_resp = await client.post(SHEET_WEBHOOK, json={
                "action": "getCancelCount",
                "userId": str_uid,
            }, timeout=40)
        cancel_count = count_resp.json().get("cancelCount", 0)
    except Exception as e:
        logger.error(f"getCancelCount: {e}")

    new_count = cancel_count + 1

    proxy_sessions.pop(sid, None)
    cancel_request_timer(req_id)
    broker_tg_id = session.get("brokerId","")
    broker_obj   = session.get("brokerObj", {})
    broker_id    = broker_obj.get("brokerId","B???")

    if broker_tg_id:
        # recalc, not a hardcoded FREE — the broker may still have another
        # concurrent session (e.g. auction+search) open besides this one.
        await update_broker(broker_tg_id, status=recalc_broker_status(broker_tg_id))

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            await client.post(SHEET_WEBHOOK, json={
                "action":      "saveCancelCount",
                "userId":      str_uid,
                "cancelCount": new_count,
                "reqId":       req_id,
            }, timeout=40)
            await client.post(SHEET_WEBHOOK, json={
                "action": "updateRequest",
                "reqId":  req_id,
                "customerId": str_uid,
                "status": "CANCELLED_BY_CUSTOMER",
            }, timeout=40)
    except Exception as e:
        logger.error(f"saveCancelCount: {e}")

    if new_count >= 3:
        ban_expire = (datetime.now() + timedelta(days=30)).strftime("%d/%m/%Y")
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                await client.post(SHEET_WEBHOOK, json={
                    "action":    "banCustomer", "serverKey": SHEET_SERVER_KEY,
                    "userId":    str_uid,
                    "banExpire": ban_expire,
                }, timeout=40)
        except Exception as e:
            logger.error(f"banCustomer: {e}")

        await update.message.reply_text(
            f"🚨 *Account ယာယီ Ban ဖြစ်ပြီ*\n\n"
            f"Cancel {new_count} ကြိမ် ရောက်သောကြောင့်\n"
            f"🗓 Ban ကုန်ဆုံးရက်: `{ban_expire}`",
            parse_mode='Markdown')

        await notify_admins(context,
            f"🚨 *Customer Temp Ban*\n\n"
            f"👤 {user.first_name} (`{user_id}`)\n"
            f"🆔 `{req_id}`\n"
            f"📊 Cancel: {new_count}")

    elif new_count == 2:
        await update.message.reply_text(
            f"⚠️ *Cancel ၂ ကြိမ် ပြည့်ပြီ*\n\n"
            f"🆔 `{req_id}`\n\n"
            f"⚠️ ထပ် cancel ရင် 30 ရက် Ban\n\n"
            f"/carrequest ပြန်တင်နိုင်",
            parse_mode='Markdown')

    else:
        await update.message.reply_text(
            f"❌ *Request Cancel ပြီ*\n\n"
            f"🆔 `{req_id}`\n\n"
            f"📊 Cancel: {new_count}/3\n\n"
            f"ပြန်တင်ရန်: /carrequest",
            parse_mode='Markdown')

    if broker_tg_id:
        try:
            await context.bot.send_message(
                chat_id=int(broker_tg_id),
                text=(f"❌ *Customer Cancel*\n\n🆔 `{req_id}`\n🟢 FREE ဖြစ်ပြီ"),
                parse_mode='Markdown')
        except Exception as e:
            logger.error(f"cancel broker notify: {e}")


async def handle_request_qa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user    = update.effective_user
    user_id = user.id
    if user_id not in pending_request: return False

    text = update.message.text.strip()
    req  = pending_request[user_id]
    step = req["step"]

    if step == 3 and not req["data"].get("budget"):
        return False

    req["data"][REQ_STEPS[step]] = text
    step += 1
    req["step"] = step

    if step == 1:
        await update.message.reply_text(
            "📅 *ထုတ်လုပ်သည့် နှစ်*\n\nFormat: `2014` သို့ `2018-2022`\nမသိရင်: `any`",
            parse_mode='Markdown')
    elif step == 2:
        await update.message.reply_text(
            "🔧 *Grade / Features*\n\nဥပမာ: `20X, Alloy, DVD`\nမသတ်မှတ်ရင်: `any`",
            parse_mode='Markdown')
    elif step == 3:
        kb = [
            [InlineKeyboardButton("฿50,000",  callback_data="req_budget_50000"),
             InlineKeyboardButton("฿100,000", callback_data="req_budget_100000")],
            [InlineKeyboardButton("฿150,000", callback_data="req_budget_150000"),
             InlineKeyboardButton("฿200,000", callback_data="req_budget_200000")],
            [InlineKeyboardButton("฿250,000", callback_data="req_budget_250000"),
             InlineKeyboardButton("฿300,000", callback_data="req_budget_300000")],
        ]
        await update.message.reply_text(
            "💰 *Budget ရွေးပါ*", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(kb))
    elif step == 4:
        kb = [
            [InlineKeyboardButton("⭐",        callback_data="req_cond_1"),
             InlineKeyboardButton("⭐⭐",       callback_data="req_cond_2"),
             InlineKeyboardButton("⭐⭐⭐",      callback_data="req_cond_3")],
            [InlineKeyboardButton("⭐⭐⭐⭐",     callback_data="req_cond_4"),
             InlineKeyboardButton("⭐⭐⭐⭐⭐",    callback_data="req_cond_5")],
        ]
        await update.message.reply_text(
            "⭐ *Condition ရွေးပါ*",
            parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    elif step == 5:
        kb = [
            [InlineKeyboardButton("🔥 ၃ ရက်",    callback_data="req_time_3days"),
             InlineKeyboardButton("📅 ၁ ပတ်",   callback_data="req_time_1week")],
            [InlineKeyboardButton("🗓 ၁ လ",     callback_data="req_time_1month"),
             InlineKeyboardButton("⏳ ရမှပြောမည်", callback_data="req_time_open")],
        ]
        await update.message.reply_text(
            "⏳ *Timeline ရွေးပါ*", parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(kb))

    return True

async def finish_request(update_or_query, context, user_id: int):
    req  = pending_request.get(user_id)
    if not req: return
    d    = req["data"]
    txt  = (
        f"📋 *Request Summary*\n"
        f"{'─'*24}\n"
        f"🚗 ကား: *{d.get('car_name','—')}*\n"
        f"📅 နှစ်: {d.get('year','—')}\n"
        f"🔧 Grade: {d.get('grade','—')}\n"
        f"💰 Budget: {d.get('budget','—')}\n"
        f"⭐ Condition: {d.get('condition','—')}\n"
        f"⏳ Timeline: {d.get('timeline','—')}\n"
        f"{'─'*24}\n\n"
        f"အတည်ပြုမည်လား?"
    )
    kb = [[
        InlineKeyboardButton("✅ အတည်ပြု", callback_data="req_confirm"),
        InlineKeyboardButton("✏️ ပြင်မည်",  callback_data="req_cancel"),
    ]]
    if hasattr(update_or_query, 'message'):
        await update_or_query.message.reply_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update_or_query.edit_message_text(txt, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

def _validate_legacy_add_request_response(
    result: object,
    *,
    user_id: int,
) -> tuple[str | None, str]:
    """Validate the Apps Script addRequest response before broker routing."""
    if not isinstance(result, dict):
        return None, "invalid_response_shape"
    if str(result.get("status") or "").strip().lower() != "ok":
        message = str(result.get("msg") or result.get("message") or "unknown")
        return None, f"backend_rejected:{message[:120]}"

    returned_req_id = str(result.get("reqId") or "").strip().upper()
    if not re.fullmatch(r"[AR][A-Z0-9-]{5,64}", returned_req_id):
        return None, "missing_or_invalid_req_id"

    returned_customer_id = str(result.get("customerId") or "").strip()
    if returned_customer_id != str(user_id):
        return None, "customer_id_mismatch"

    return returned_req_id, "ok"


async def _lookup_legacy_request(request_code: str, user_id: int):
    """Read-only check for a request after an ambiguous addRequest response.

    Apps Script ``addRequest`` appends a row and is not idempotent. If the
    network fails after the append, retrying the same form can create a second
    row. This lookup lets the bot confirm the original ID without writing.
    """
    safe_req_id = str(request_code or "").strip().upper()
    if not SHEET_WEBHOOK or not safe_req_id:
        return None
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.post(
                SHEET_WEBHOOK,
                json={
                    "action": "getRequest",
                    "reqId": safe_req_id,
                    "customerId": str(user_id),
                },
                timeout=40,
            )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or result.get("status") != "ok":
            return None
        returned_req_id = str(result.get("reqId") or "").strip().upper()
        returned_customer_id = str(result.get("customerId") or "").strip()
        if returned_req_id != safe_req_id:
            return None
        if returned_customer_id != str(user_id):
            return None
        return result
    except Exception as exc:
        logger.warning(
            "read-only request reconciliation failed: request=%s error=%s",
            safe_req_id,
            type(exc).__name__,
        )
        return None


async def submit_request(context, user_id: int, username: str):
    req = pending_request.pop(user_id, None)
    if not req: return

    d      = req["data"]
    svc_prefix = 'A' if d.get("service_type") == "auction" else 'R'
    req_id = svc_prefix + ''.join(random.choices(string.digits, k=6))

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            request_resp = await client.post(SHEET_WEBHOOK, json={
                "action":     "addRequest",
                "reqId":      req_id,
                "customerId": str(user_id),
                "username":   username,
                "carType":    "Auction" if d.get("service_type") == "auction" else "Search",
                "budget":     d.get("budget",""),
                "year":       d.get("year",""),
                "grade":      d.get("grade",""),
                "condition":  d.get("condition",""),
                "timeline":   d.get("timeline",""),
            }, timeout=40)
            request_resp.raise_for_status()
            request_result = request_resp.json()
            validated_req_id, validation_reason = _validate_legacy_add_request_response(
                request_result,
                user_id=user_id,
            )
            if not validated_req_id:
                pending_request[user_id] = req
                logger.error(
                    "submit_request rejected or mismatched by backend: reason=%s result=%s",
                    validation_reason,
                    request_result,
                )
                await context.bot.send_message(
                    chat_id=user_id,
                    text=("❌ Request မတင်နိုင်သေးပါ။\n\n"
                          "Request ID/Member ID ကို backend က စစ်ဆေးနေပါသည်။ "
                          "ဒီ Request ကို ပြန်မတင်မီ /mystatus ဖြင့် အရင်စစ်ပါ။"))
                return
            req_id = validated_req_id
    except Exception as e:
        # The write may have reached Apps Script before the client timed out.
        # Reconcile with a read-only owner-checked lookup before allowing retry.
        reconciled = await _lookup_legacy_request(req_id, user_id)
        if reconciled:
            req_id = str(reconciled.get("reqId") or req_id)
            logger.warning(
                "submit_request reconciled after ambiguous response: request=%s",
                req_id,
            )
        else:
            pending_request[user_id] = req
            logger.error(f"submit_request: {e}")
            await context.bot.send_message(
                chat_id=user_id,
                text=("❌ Request မတင်နိုင်သေးပါ။\n\n"
                      "Server ချိတ်ဆက်မှု အဆင်မပြေသေးပါ။\n"
                      "Request ကို ပြန်မတင်မီ /mystatus ဖြင့် အရင်စစ်ပါ။"))
            return

    await context.bot.send_message(
        chat_id=user_id,
        text=(f"✅ *Request တင်ပြီ!*\n\n"
              f"🆔 Request ID: `{req_id}`\n"
              f"🚗 {d.get('car_name','')}\n"
              f"💰 {d.get('budget','')}\n\n"
              f"Broker က ရှာပေးမည် ⏳"),
        parse_mode='Markdown')

    brokers    = await get_brokers()
    svc_type   = d.get("service_type", "search")

    eligible_brokers = []
    for b in brokers:
        if b.get("status") in ("BANNED", "KICKED"): continue
        tg_id       = str(b.get("telegramId",""))
        active_types = get_broker_session_types(tg_id)
        if svc_type in active_types: continue
        if len(active_types) >= 2:   continue
        eligible_brokers.append(b)

    def broker_priority(b):
        rating       = float(b.get("rating", 0) or 0)
        decline      = int(b.get("declineCount", 0) or 0)
        rating_count = int(b.get("ratingCount", 0) or 0)
        new_bonus    = 50 if rating_count == 0 else 0
        score        = (rating * 20) - (decline * 10) + new_bonus
        return -score  # negative = highest first

    eligible_brokers.sort(key=broker_priority)

    for b in eligible_brokers:
        try:
            btn_label = "🏆 Auction Order လက်ခံမည်" if svc_type == "auction" else "🔍 ကားရှာ Order လက်ခံမည်"
            req_kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(btn_label,    callback_data=f"breq_accept_{req_id}"),
                InlineKeyboardButton("❌ ငြင်းမည်", callback_data=f"breq_decline_{req_id}"),
            ]])
            svc_header = (
                "🏆 *AUCTION CAR ORDER*\n━━━━━━━━━━━━━━\nDeposit ฿20,000 လိုအပ်မည်"
                if svc_type == "auction" else
                "🔍 *ကားရှာ ORDER*\n━━━━━━━━━━━━━━\nအပြင်ကား ရှာပေးရန်"
            )
            await context.bot.send_message(
                chat_id=int(b["telegramId"]),
                text=(f"🔔 *Order အသစ်တက်လာပြီ!*\n\n"
                      f"{svc_header}\n\n"
                      f"🆔 `{req_id}`\n"
                      f"🚘 *{d.get('car_name','')}*\n"
                      f"📅 နှစ်: {d.get('year','')}\n"
                      f"🔧 Grade: {d.get('grade','')}\n"
                      f"💰 Budget: {d.get('budget','')}\n"
                      f"⭐ Condition: {d.get('condition','')}\n"
                      f"⏳ Timeline: {d.get('timeline','')}"),
                parse_mode='Markdown',
                reply_markup=req_kb)
        except Exception as e:
            logger.error(f"notify broker {b['brokerId']}: {e}")

    await notify_admins(context,
        f"📥 *Request အသစ်*\n\n"
        f"🆔 `{req_id}`\n"
        f"📌 {'🏆 လေလံ' if d.get('service_type') == 'auction' else '🔍 ကားရှာ'}\n"
        f"👤 @{username}\n"
        f"🚘 {d.get('car_name','')}\n"
        f"💰 {d.get('budget','')}")

async def mystatus_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    str_uid = str(user_id)

    if not await is_active_member(user_id):
        await update.message.reply_text(
            "🔒 Member များသာ သုံးနိုင်ပါသည်",
            parse_mode='Markdown')
        return

    session_data = next(
        ((sid, s) for sid, s in proxy_sessions.items()
         if str(s.get("customerId","")) == str_uid and s.get("status") == "ACTIVE"),
        None
    )

    if session_data:
        sid, sess      = session_data
        req_id         = sess.get("reqId", sid)
        broker_obj     = sess.get("brokerObj", {})
        broker_id      = broker_obj.get("brokerId", "?")
        _ms_rating     = float(broker_obj.get("rating", 0) or 0)
        _ms_deals      = broker_obj.get("deals", 0) or 0
        _ms_rating_str = f"⭐ {_ms_rating:.1f} | Deals: {_ms_deals}" if _ms_rating > 0 else f"🆕 New Broker | Deals: {_ms_deals}"
        await update.message.reply_text(
            f"📋 *Request Status*\n\n"
            f"🆔 `{req_id}`\n"
            f"🤝 *MATCHED*\n"
            f"👷 Broker: #{broker_id}\n"
            f"{_ms_rating_str}",
            parse_mode='Markdown')
        return

    if user_id in pending_request:
        step = pending_request[user_id].get("step", 0)
        await update.message.reply_text(
            f"📋 Request ဖြည်နေဆဲ ({step}/{len(REQ_STEPS)})")
        return

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.post(SHEET_WEBHOOK, json={
                "action":     "getMyRequests", "serverKey": SHEET_SERVER_KEY,
                "customerId": str_uid,
            }, timeout=40)
        data     = resp.json()
        requests = data.get("requests", [])
        if requests:
            latest = requests[0]
            req_id = latest.get("reqId", "?")
            status = latest.get("status", "?")
            await update.message.reply_text(
                f"📋 *Request မှတ်တမ်း*\n\n"
                f"🆔 `{req_id}`\n"
                f"🚗 {latest.get('carType','')}\n"
                f"📊 {status}",
                parse_mode='Markdown')
            return
    except Exception as e:
        logger.error(f"mystatus: {e}")

    await update.message.reply_text("📋 Request မရှိ — /carrequest")

async def accept_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    user_id = str(user.id)

    brokers = await get_brokers()
    broker  = next((b for b in brokers if b.get("telegramId") == user_id), None)
    if not broker:
        await update.message.reply_text("❌ Broker မဟုတ်ဘူး"); return

    if broker.get("status") == "BANNED":
        await update.message.reply_text("🚫 Account ပိတ်သိမ်းထားပြီ"); return

    if not context.args:
        await update.message.reply_text("❌ Format: `/accept R123456`", parse_mode='Markdown'); return

    req_id = context.args[0].strip().upper()

    customer_id = None
    customer_username = ""
    req_data = {}
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.post(SHEET_WEBHOOK, json={
                "action": "getRequest",
                "reqId":  req_id,
            }, timeout=40)
        rdata = resp.json()
        if rdata.get("status") == "ok":
            customer_id       = rdata.get("customerId")
            customer_username = rdata.get("username","")
            req_data          = rdata
        else:
            await update.message.reply_text(f"❌ Request `{req_id}` မတွေ့ဘူး", parse_mode='Markdown')
            return
    except Exception as e:
        logger.error(f"accept getRequest: {e}")
        await update.message.reply_text("❌ Sheet error"); return

    if req_id in proxy_sessions:
        await update.message.reply_text("❌ ဒီ Request ကို တခြား Broker လက်ခံပြီးသားပါ")
        return

    svc_type     = "auction" if req_data.get("carType","").lower() == "auction" else "search"
    active_types = get_broker_session_types(user_id)
    if svc_type in active_types:
        await update.message.reply_text("❌ Session တူ ရှိပြီးသား")
        return
    if len(active_types) >= 2:
        await update.message.reply_text("❌ Order ၂ ခု ပြည့်နေပြီ")
        return

    # Claim the request synchronously (no await between the check and the
    # write) so this path and the breq_accept_ button can't both win a
    # race on the same request.
    if req_id in proxy_sessions:
        await update.message.reply_text("❌ ဒီ Request ကို တခြား Broker လက်ခံပြီးသားပါ")
        return
    new_status = "FULL" if (svc_type == "auction" and "search" in active_types) or (svc_type == "search" and "auction" in active_types) else ("HAS_AUCTION" if svc_type == "auction" else "HAS_SEARCH")
    proxy_sessions[req_id] = {
        "customerId":       customer_id,
        "customerUsername": customer_username,
        "brokerId":         user_id,
        "brokerObj":        broker,
        "reqId":            req_id,
        "status":           "ACTIVE",
        "serviceType":      svc_type,
        "startTime":        datetime.now().isoformat(),
    }

    await update_broker(user_id, status=new_status)

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            await client.post(SHEET_WEBHOOK, json={
                "action":   "updateRequest",
                "reqId":    req_id,
                "status":   "MATCHED",
                "brokerId": broker["brokerId"],
            }, timeout=40)
    except Exception as e:
        logger.error(f"accept updateRequest: {e}")

    svc_label_accept = "🏆 လေလံ" if svc_type == "auction" else "🔍 ကားရှာ"
    await update.message.reply_text(
        f"✅ *Accept ပြီ!*\n\n🆔 `{req_id}`\n📌 {svc_label_accept}",
        parse_mode='Markdown')

    if customer_id:
        try:
            dep_kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "💰 Deposit ฿20,000 ပေးမည်",
                    callback_data=f"dep_start_{req_id}_{user_id}")
            ]])
            await context.bot.send_message(
                chat_id=int(customer_id),
                text=(f"🎉 *Broker ရှာပြီ — Deposit လိုအပ်ပါသည်*\n\n"
                      f"🆔 `{req_id}`\n"
                      f"👷 Broker #{broker['brokerId']}\n\n"
                      f"⚠️ မှတ်ချက် — လေလံနီးကပ်မှ Deposit မပေးပါနှင့်\n"
                      f"လေလံမစခင် 1 နာရီအလိုထိ Deposit ပေးဖို့ အချိန်ရပါသည်\n\n"
                      f"အောက်ပါ button နှိပ်ပြီး Slip ပို့ပါ 👇"),
                parse_mode='Markdown',
                reply_markup=dep_kb)
        except Exception as e:
            logger.error(f"accept customer notify: {e}")

    await notify_admins(context,
        f"🤝 *Broker Accept*\n\n🆔 `{req_id}`\n👷 #{broker['brokerId']}")

    # ── Broker ကို Deposit သတိပေး ──
    nodep_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "⚠️ Customer Deposit မလွှဲပါ",
            callback_data=f"nodep_report_{req_id}")
    ]])
    await update.message.reply_text(
        f"ℹ️ *Deposit သတိပေးချက်*\n\n"
        f"🆔 `{req_id}`\n\n"
        f"Customer အနေနဲ့ လေလံမစခင် 1 နာရီအလိုထိ Deposit ปေးနိုင်ပါသည်\n"
        f"Admin ဆီမှ Deposit Confirm မရသေးရင် Customer ကို သတိပေးပါ\n\n"
        f"Customer က Deposit မလွှဲတော့ဘူးဆိုရင် 👇",
        parse_mode='Markdown',
        reply_markup=nodep_kb)

    start_request_timer(
        context, req_id=req_id, broker_tg_id=user_id,
        broker_id=broker["brokerId"],
        customer_id=str(customer_id) if customer_id else "")

    svc_label_track = "🏆 Auction" if svc_type == "auction" else "🔍 ကားရှာ"
    await update.message.reply_text(
        f"📦 *Status Tracking — {svc_label_track}*\n\n🆔 `{req_id}`",
        parse_mode='Markdown',
        reply_markup=get_tracking_keyboard(svc_type, req_id))

async def endchat_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    brokers = await get_brokers()
    broker  = next((b for b in brokers if b.get("telegramId") == user_id), None)
    if not broker:
        await update.message.reply_text("❌ Broker မဟုတ်ဘူး"); return

    req_id = context.args[0].strip().upper() if context.args else ""
    if not req_id:
        await update.message.reply_text(
            "❌ Format: `/endchat R123456`", parse_mode='Markdown'); return

    session = proxy_sessions.get(req_id)
    if not session:
        await update.message.reply_text(
            f"❌ `{req_id}` Session မတွေ့ပါ",
            parse_mode='Markdown'); return
    if str(session.get("brokerId")) != user_id:
        await update.message.reply_text(
            f"❌ `{req_id}` က သင့် Session မဟုတ်ပါ — ကိုယ်ပိုင် Session ကိုသာ ပိတ်နိုင်ပါတယ်",
            parse_mode='Markdown'); return

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ ဟုတ်ကဲ့ — ပိတ်မည်",  callback_data=f"endchat_yes_{req_id}"),
        InlineKeyboardButton("❌ မပိတ်သေးဘူး",         callback_data=f"endchat_no_{req_id}"),
    ]])
    await update.message.reply_text(
        f"⚠️ *Session ပိတ်တော့မည်*\n\n🆔 `{req_id}`\n\nသေချာပြီလား?",
        parse_mode='Markdown', reply_markup=kb)


# ── Promo Code ────────────────────────────────────────
def parse_promo_codes() -> dict:
    codes = {}
    if not PROMO_CODES_RAW:
        return codes
    for entry in PROMO_CODES_RAW.split(','):
        parts = entry.strip().split(':')
        if len(parts) >= 2:
            code     = parts[0].strip().upper()
            days     = int(parts[1]) if parts[1].isdigit() else 30
            max_uses = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 40
            codes[code] = {"days": days, "max_uses": max_uses}
    return codes

async def redeem_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    user_id = user.id

    if not context.args:
        await update.message.reply_text(
            "🎁 *Promo Code သုံးရန်*\n\n`/redeem CODE`\nဥပမာ: `/redeem TIKTOK30`",
            parse_mode='Markdown')
        return

    code     = context.args[0].strip().upper()
    username = user.username or user.first_name or str(user_id)

    await update.message.reply_text("🔍 Code စစ်ဆေးနေတယ်... ⏳")

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp   = await client.post(SHEET_WEBHOOK, json={
                "action": "redeemPromo",
                "code":   code,
                "userId": str(user_id),
            }, timeout=40)
        result = resp.json()
    except Exception as e:
        logger.error(f"redeemPromo: {e}")
        await update.message.reply_text("❌ Server error — ခဏကြိုးစားပါ")
        return

    status = result.get("status")

    if status == "error":
        msg_map = {
            "invalid_code":  "❌ *Code မမှန်ကန်ပါ*\n\nAdmin ထံမှ မှန်ကန်သော Code ယူပါ",
            "already_used":  "❌ *Code ကို တစ်ကြိမ်သာ သုံးနိုင်ပါသည်*\n\nဤ Code ကို သင် ရှိပြီးသား သုံးထားပါသည်",
            "max_reached":   f"❌ *Code ကုန်ဆုံးပြီ*\n\n{result.get('used',0)}/{result.get('max',0)} ဦး သုံးပြီးပါပြီ",
            "no_sheet":      "❌ System error — Admin ကို ဆက်သွယ်ပါ",
        }
        msg = msg_map.get(result.get("msg",""), "❌ Code မမှန်ကန်ပါ")
        await update.message.reply_text(msg, parse_mode='Markdown')
        return

    days       = result.get("days", 30)
    used       = result.get("used", 0)
    max_uses   = result.get("max", 40)
    remaining  = max_uses - used
    pkg        = result.get("package", "WEB").upper()

    if pkg == "WEB":
        member_pkg = "WEB-PROMO"
        pkg_label  = "🌐 Web + Channel"
    else:
        member_pkg = "CH-PROMO"
        pkg_label  = "📱 Channel Only"

    password = generate_password() if pkg == "WEB" else ""
    saved = await save_member_to_sheet(str(user_id), username, days, password, member_pkg)
    saved = await enrich_member_save_result(
        str(user_id), saved, member_pkg, strict=True)
    if saved.get("status") != "ok":
        await update.message.reply_text(
            "❌ Promo ရပါပြီ၊ ဒါပေမယ့် Member Sheet ထဲ မသိမ်းနိုင်သေးပါ။ Admin ကို ဆက်သွယ်ပါ။"
        )
        await notify_admins(
            context,
            f"⚠️ Promo save failed for {user_id}. Code={code}; payment/member data needs review.",
        )
        return
    canonical_password = str(saved.get("password") or password or "")
    canonical_expire = str(saved.get("expireDate") or "")
    finance_logged = await log_finance_entry({
        "date": datetime.now(timezone.utc).strftime("%d/%m/%Y"),
        "time": datetime.now(timezone.utc).strftime("%H:%M"),
        "userId": str(user_id),
        "username": username,
        "package": str(saved.get("package") or pkg),
        "months": max(1, days // 30),
        "amount": "",
        "payType": "PROMO",
        "transactionNo": "",
        "status": "PROMO",
        "entryType": "PROMO",
        "source": "PROMO",
        "approvedBy": "",
        "expireDate": canonical_expire,
        "note": "Promo code: " + code,
    })
    if not finance_logged:
        # Member already extended above — do not block the user. But this
        # membership change now has no Finance audit row, so an admin has
        # to add one manually.
        await notify_admins(
            context,
            f"⚠️ Promo Finance log FAILED for {user_id} (@{username}). "
            f"Code={code}; member was extended {days} days but no Finance "
            f"row was recorded — please add one manually.",
        )
    invite_url = await create_invite_link(context, days, user_id)
    await send_approval_dm(
        context, user_id, max(1, days // 30), canonical_password, invite_url,
        package=str(saved.get("package") or pkg), expire_date=canonical_expire)

    await update.message.reply_text(
        f"🎉 *Promo Code အောင်မြင်!*\n\n"
        f"{pkg_label} Membership *{days} ရက်* ရပါပြီ\n"
        f"🔑 Password DM ပို့ပြီ\n\n"
        f"🙏 ကျေးဇူးတင်ပါသည်",
        parse_mode='Markdown')

    await notify_admins(context,
        f"🎁 *Promo Redeemed!*\n\n"
        f"👤 @{username} (ID: `{user_id}`)\n"
        f"🏷 Code: `{code}`\n"
        f"📅 {days} ရက်\n"
        f"📊 သုံးပြီး: {used}/{max_uses}\n"
        f"🔢 ကျန်: {remaining}")

# ── Auto Timer ───────────────────────────────────────
async def request_timer_task(context, req_id: str, broker_tg_id: str,
                              broker_id: str, customer_id: str):
    try:
        await asyncio.sleep(4 * 3600)

        if req_id not in proxy_sessions:
            return

        broker_msg = (
            f"⏰ *4 နာရီ Reminder*\n\n"
            f"🆔 Request: `{req_id}`\n\n"
            f"Customer ကို ကားရှာပေးနေပြီ ၄ နာရီကျော်ပြီ\n"
            f"Update တစ်ခုခု ပေးဖို့ မမေ့ပါနဲ့ 📞\n\n"
            f"ပြီးရင်: `/endchat {req_id}`"
        )
        try:
            await context.bot.send_message(
                chat_id=int(broker_tg_id),
                text=broker_msg,
                parse_mode='Markdown')
        except Exception as e:
            logger.error(f"timer 4hr broker: {e}")

        await notify_admins(context,
            f"⏰ *4hr Reminder*\n\n"
            f"🆔 `{req_id}`\n"
            f"👷 Broker #{broker_id} — 4 နာရီကျော်ပြီ\n"
            f"Session ဆက်ဖွင့်နေဆဲ")

        await asyncio.sleep(20 * 3600)

        if req_id not in proxy_sessions:
            return

        proxy_sessions.pop(req_id, None)
        active_timers.pop(req_id, None)

        # recalc, not a hardcoded FREE — the broker may still have another
        # concurrent session (e.g. auction+search) open besides this one.
        await update_broker(broker_tg_id, status=recalc_broker_status(broker_tg_id))

        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                await client.post(SHEET_WEBHOOK, json={
                    "action": "updateRequest",
                    "reqId":  req_id,
                    "status": "CANCELLED_TIMEOUT",
                }, timeout=40)
        except Exception as e:
            logger.error(f"timer cancel sheet: {e}")

        try:
            await context.bot.send_message(
                chat_id=int(broker_tg_id),
                text=(f"⚠️ *Request Auto Cancel ဖြစ်ပြီ*\n\n"
                      f"🆔 `{req_id}`\n"
                      f"48 နာရီ အတွင်း မပြီးဆုံးတဲ့အတွက် ပိတ်လိုက်ပြီ\n\n"
                      f"🟢 Status: FREE ဖြစ်ပြီ"),
                parse_mode='Markdown')
        except Exception as e:
            logger.error(f"timer 48hr broker: {e}")

        if customer_id:
            try:
                await context.bot.send_message(
                    chat_id=int(customer_id),
                    text=(f"⚠️ *Request ပိတ်သွားပြီ*\n\n"
                          f"🆔 `{req_id}`\n"
                          f"48 နာရီ အတွင်း ကားမရသောကြောင့် Request ပိတ်ပြီ\n\n"
                          f"ပြန်တင်ရန်: /carrequest 🙏"),
                    parse_mode='Markdown')
            except Exception as e:
                logger.error(f"timer 48hr customer: {e}")

        await notify_admins(context,
            f"🚨 *Request Auto Cancel (48hr timeout)*\n\n"
            f"🆔 `{req_id}`\n"
            f"👷 Broker #{broker_id} → FREE\n"
            f"👤 Customer: `{customer_id}`")

    except asyncio.CancelledError:
        logger.info(f"Timer cancelled for {req_id}")
    except Exception as e:
        logger.error(f"request_timer_task: {e}")


def start_request_timer(context, req_id: str, broker_tg_id: str,
                         broker_id: str, customer_id: str):
    if req_id in active_timers:
        active_timers[req_id].cancel()

    task = asyncio.create_task(
        request_timer_task(context, req_id, broker_tg_id, broker_id, customer_id)
    )
    active_timers[req_id] = task


def cancel_request_timer(req_id: str):
    task = active_timers.pop(req_id, None)
    if task:
        task.cancel()


# ── /depositrequest (Broker only) ────────────────────
async def depositrequest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    brokers = await get_brokers()
    broker  = next((b for b in brokers if b.get("telegramId") == user_id), None)
    if not broker:
        await update.message.reply_text("❌ Broker မဟုတ်ဘူး")
        return

    session = next(
        ((sid, s) for sid, s in proxy_sessions.items()
         if str(s.get("brokerId","")) == user_id and s.get("status") == "ACTIVE"),
        None
    )
    if not session:
        await update.message.reply_text(
            "❌ Active session မရှိဘူး\nCustomer နဲ့ chat ဖွင့်ပြီးမှ တောင်းပါ")
        return

    sid, sess   = session
    customer_id = sess.get("customerId")
    req_id      = sess.get("reqId", sid)

    if not customer_id:
        await update.message.reply_text("❌ Customer ID မတွေ့ပါ")
        return

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "💰 ကားဝယ်ယူရန် (Deposit ฿20,000)",
            callback_data=f"dep_start_{req_id}_{user_id}")
    ]])
    try:
        await context.bot.send_message(
            chat_id=int(customer_id),
            text=(f"🚗 *ကားဝယ်ယူရန် Deposit*\n\n"
                  f"🆔 Request: `{req_id}`\n\n"
                  f"Broker က Deposit ฿20,000 တောင်းနေပြီ\n"
                  f"ဆက်လုပ်ရန် အောက်ပါ button နှိပ်ပါ 👇"),
            parse_mode='Markdown',
            reply_markup=kb)
        await update.message.reply_text("✅ Customer ဆီ Deposit request ပို့ပြီ")
    except Exception as e:
        logger.error(f"depositrequest: {e}")
        await update.message.reply_text("❌ Customer ကို မပို့နိုင်ဘူး")


# ── /auctionwon (Admin only) ──────────────────────────
async def auctionwon_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်")
        return
    if not context.args:
        await update.message.reply_text(
            "❌ Format: `/auctionwon R123456 [ကားဖိုး]`\n"
            "ဥပမာ: `/auctionwon R001234 150000`",
            parse_mode='Markdown')
        return

    req_id = context.args[0].strip().upper()

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.post(SHEET_WEBHOOK, json={
                "action": "getDeposit",
                "reqId":  req_id,
            }, timeout=40)
        dep = resp.json()
    except Exception as e:
        logger.error(f"auctionwon getDeposit: {e}")
        await update.message.reply_text("❌ Sheet error")
        return

    if dep.get("status") != "ok":
        await update.message.reply_text(f"❌ `{req_id}` Deposit မတွေ့ပါ", parse_mode='Markdown')
        return

    current_status = str(dep.get("depositStatus", "") or "").strip().upper()
    if current_status in ("WON", "LOST", "REFUNDED"):
        await update.message.reply_text(
            f"⚠️ `{req_id}` ကို Auction result မှတ်တမ်းတင်ပြီးသားပါ (Status: `{current_status}`)။\n"
            "ထပ်မံ /auctionwon မလုပ်ပါနှင့် — Customer/Broker ဆီ Notification ထပ်ပို့မိနိုင်ပြီး ကားဖိုးကိုလည်း ထပ်ရေးမိနိုင်ပါတယ်။",
            parse_mode='Markdown')
        return

    customer_id  = dep.get("customerId")
    broker_tg_id = dep.get("brokerTgId")
    thb_amount   = dep.get("thbAmount", 20000)
    if len(context.args) > 1:
        try:
            car_price = int(context.args[1])
        except ValueError:
            await update.message.reply_text(
                "❌ ကားဖိုးက ဂဏန်းဖြစ်ရပါမယ်\nဥပမာ: `/auctionwon R001234 150000`",
                parse_mode='Markdown')
            return
    else:
        car_price = 0
    remaining    = car_price - thb_amount if car_price else 0

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            await client.post(SHEET_WEBHOOK, json={
                "action":        "updateDeposit",
                "reqId":         req_id,
                "auctionResult": "WON",
                "carPrice":      car_price,
            }, timeout=40)
    except Exception as e:
        logger.error(f"auctionwon updateDeposit: {e}")

    if customer_id:
        try:
            msg = (f"🏆 *ကားရပြီ!*\n\n"
                   f"🆔 Request: `{req_id}`\n\n"
                   f"💰 Deposit: ฿{thb_amount:,} (ကားဖိုးထဲ ထည့်တွက်ပြီ)\n")
            if car_price:
                msg += (f"🚗 ကားဖိုး: ฿{car_price:,}\n"
                        f"💵 ကျန်ပေးရမည်: ฿{remaining:,} + Commission\n\n")
            msg += "Admin မှ ကျန်ငွေ + Commission တောင်းပါမည် 📞"
            await context.bot.send_message(
                chat_id=int(customer_id), text=msg, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"auctionwon customer: {e}")

    if broker_tg_id:
        try:
            await context.bot.send_message(
                chat_id=int(broker_tg_id),
                text=(f"🏆 *Auction Won!*\n\n"
                      f"🆔 `{req_id}`\n"
                      f"Customer ကို ကျန်ငွေ တောင်းဆိုပြီ ✅"),
                parse_mode='Markdown')
        except Exception as e:
            logger.error(f"auctionwon broker: {e}")

    await update.message.reply_text(
        f"✅ *Auction Won မှတ်တမ်းတင်ပြီ*\n\n"
        f"🆔 `{req_id}`\n"
        f"💰 Deposit ฿{thb_amount:,} ကားဖိုးထဲ ထည့်တွက်ပြီ\n"
        + (f"💵 ကျန်ငွေ: ฿{remaining:,} + Commission" if car_price else ""),
        parse_mode='Markdown')


async def auctionlost_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်")
        return
    if not context.args:
        await update.message.reply_text(
            "❌ Format: `/auctionlost R123456`",
            parse_mode='Markdown')
        return

    req_id = context.args[0].strip().upper()

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.post(SHEET_WEBHOOK, json={
                "action": "getDeposit",
                "reqId":  req_id,
            }, timeout=40)
        dep = resp.json()
    except Exception as e:
        logger.error(f"auctionlost getDeposit: {e}")
        await update.message.reply_text("❌ Sheet error")
        return

    if dep.get("status") != "ok":
        await update.message.reply_text(f"❌ `{req_id}` Deposit မတွေ့ပါ", parse_mode='Markdown')
        return

    current_status = str(dep.get("depositStatus", "") or "").strip().upper()
    if current_status in ("WON", "LOST", "REFUNDED"):
        await update.message.reply_text(
            f"⚠️ `{req_id}` ကို Auction result မှတ်တမ်းတင်ပြီးသားပါ (Status: `{current_status}`)။\n"
            "ထပ်မံ /auctionlost မလုပ်ပါနှင့် — Customer/Broker ဆီ Notification ထပ်ပို့မိနိုင်ပြီး Admin ဆီကို Refund page ထပ်ပို့မိနိုင်ပါတယ်။",
            parse_mode='Markdown')
        return

    customer_id  = dep.get("customerId")
    broker_tg_id = dep.get("brokerTgId")
    mmk_amount   = dep.get("mmkAmount", 0)
    thb_amount   = dep.get("thbAmount", 20000)

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            await client.post(SHEET_WEBHOOK, json={
                "action":        "updateDeposit",
                "reqId":         req_id,
                "auctionResult": "LOST",
            }, timeout=40)
    except Exception as e:
        logger.error(f"auctionlost updateDeposit: {e}")

    if customer_id:
        try:
            await context.bot.send_message(
                chat_id=int(customer_id),
                text=(f"😔 *ကားမရဘူး*\n\n"
                      f"🆔 Request: `{req_id}`\n\n"
                      f"💰 Deposit ฿{thb_amount:,}\n"
                      f"💵 ပြန်ပေးမည်: *{mmk_amount:,} ks*\n\n"
                      f"(ပေးသည့်နေ့ rate အတိုင်း MMK ပြန်ပေးမည်)\n\n"
                      f"Admin မှ ၂-၃ ရက်အတွင်း ပြန်လွှဲပေးပါမည် 🙏"),
                parse_mode='Markdown')
        except Exception as e:
            logger.error(f"auctionlost customer: {e}")

    await notify_admins(context,
        f"💸 *Refund လုပ်ပေးရမည်!*\n\n"
        f"🆔 `{req_id}`\n"
        f"👤 Customer ID: `{customer_id}`\n"
        f"💵 ပြန်ပေးရမည်: *{mmk_amount:,} ks*\n\n"
        f"ပြန်လွှဲပြီးရင် `/refunddone {req_id}` နှိပ်ပါ",)

    if broker_tg_id:
        try:
            await context.bot.send_message(
                chat_id=int(broker_tg_id),
                text=(f"😔 *Auction Lost*\n\n"
                      f"🆔 `{req_id}`\n"
                      f"Customer ကို Deposit ပြန်ပေးမည် — Admin handle လုပ်မည်"),
                parse_mode='Markdown')
        except Exception as e:
            logger.error(f"auctionlost broker: {e}")

    await update.message.reply_text(
        f"✅ *Auction Lost မှတ်တမ်းတင်ပြီ*\n\n"
        f"🆔 `{req_id}`\n"
        f"💵 Refund: *{mmk_amount:,} ks*\n\n"
        f"⚠️ Customer ကို ပြန်လွှဲပေးဖို့ မမေ့ပါနဲ့!",
        parse_mode='Markdown')


async def refunddone_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်")
        return
    if not context.args:
        await update.message.reply_text("❌ Format: `/refunddone R123456`", parse_mode='Markdown')
        return

    req_id = context.args[0].strip().upper()

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            dep_resp = await client.post(SHEET_WEBHOOK, json={
                "action": "getDeposit",
                "reqId":  req_id,
            }, timeout=40)
        dep = dep_resp.json()
    except Exception as e:
        logger.error(f"refunddone getDeposit: {e}")
        await update.message.reply_text("❌ Sheet error")
        return

    if dep.get("status") != "ok":
        await update.message.reply_text(f"❌ `{req_id}` Deposit မတွေ့ပါ", parse_mode='Markdown')
        return

    current_status = str(dep.get("depositStatus", "") or "").strip().upper()
    if current_status == "REFUNDED":
        await update.message.reply_text(
            f"⚠️ `{req_id}` ကို Refund လုပ်ပြီးသားပါ — ထပ်မံ /refunddone မလုပ်ပါနှင့်။",
            parse_mode='Markdown')
        return
    if current_status != "LOST":
        await update.message.reply_text(
            f"❌ `{req_id}` ကို /auctionlost နဲ့ Lost အဖြစ် မှတ်တမ်းတင်ပြီးမှသာ Refund လုပ်နိုင်ပါတယ်\n"
            f"(လက်ရှိ Status: `{current_status or 'HOLD'}`)",
            parse_mode='Markdown')
        return

    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            await client.post(SHEET_WEBHOOK, json={
                "action":        "updateDeposit",
                "reqId":         req_id,
                "auctionResult": "REFUNDED",
            }, timeout=40)
    except Exception as e:
        logger.error(f"refunddone updateDeposit: {e}")
        await update.message.reply_text("❌ Sheet error — refund မှတ်တမ်း မတင်နိုင်ပါ")
        return

    customer_id = dep.get("customerId")
    mmk_amount  = dep.get("mmkAmount", 0)

    if customer_id:
        try:
            await context.bot.send_message(
                chat_id=int(customer_id),
                text=(f"✅ *Deposit ပြန်ပေးပြီ!*\n\n"
                      f"🆔 `{req_id}`\n"
                      f"💵 *{mmk_amount:,} ks* လွှဲပေးပြီ\n\n"
                      f"ဆက်လုပ်ချင်ရင် /carrequest နှိပ်ပါ 🙏"),
                parse_mode='Markdown')
        except Exception as e:
            logger.error(f"refunddone notify: {e}")

    await update.message.reply_text(
        f"✅ Refund ပြီးကြောင်း မှတ်တမ်းတင်ပြီ\n🆔 `{req_id}`",
        parse_mode='Markdown')


# ── JACC Google Login admin approval (Admin only) ──────
# Google Login members (synthetic "G_<sub>" userId, issued by
# verifyGoogleLogin in Code.gs) have no Telegram identity to receive the
# existing slip_confirm_/slip_ok_/slip_no_ button-callback approval flow --
# that flow assumes a Telegram numeric chat_id throughout. These two
# commands are a deliberately separate approval path so the existing
# button-based flow for Telegram-origin members stays completely untouched.
# Both reuse approve_payment_transaction(), the same atomic Apps Script
# money-crediting call the button flow uses -- only the trigger differs.
def _google_member_id_from_text(text: str) -> str:
    return str(text or "").strip()


async def _google_approve_member(member_id: str, approved_by: str) -> str:
    """Core /googleapprove logic, shared by the typed command and the
    gapprove_ button callback so there's exactly one place that talks to
    approve_payment_transaction() for Google Login members."""
    if not member_id.startswith("G_"):
        return "❌ ဒါ Google Login member ID မဟုတ်ပါ (`G_` နဲ့ မစပါ)"

    pay_data = pending_payment.get(member_id)
    if not pay_data:
        pay_data = await get_payment_draft(member_id)
        if pay_data:
            pending_payment[member_id] = pay_data
    if not pay_data:
        return f"❌ `{member_id}` အတွက် Payment data မတွေ့ပါ — အရင် Approve/Reject လုပ်ပြီးသားလား စစ်ပါ"

    slips = pay_data.get("slips", [])
    months = int(pay_data.get("months", 1) or 1)
    expected_amount = int(pay_data.get("amount", 0) or 0)
    total_paid, _ = payment_slip_summary(slips)
    if expected_amount <= 0 or total_paid != expected_amount:
        return (
            f"❌ ငွေပမာဏ မကိုက်ညီသေးပါ — Expected {expected_amount:,} ks, Received {total_paid:,} ks\n"
            "Slip အားလုံး ပို့ပြီးမှသာ Approve လုပ်ပါ"
        )

    slip_info = pay_data.get("slip_info", {}) or {}
    transaction_no = str(slip_info.get("TRANSACTION_NO") or slip_info.get("REFERENCE") or "").strip()
    if transaction_no.upper() == "UNKNOWN":
        transaction_no = ""
    password = generate_password()

    atomic_payment = {
        "userId": member_id,
        "username": str(pay_data.get("username") or member_id).replace("@", ""),
        "package": "WEB",
        "months": months,
        "days": months * 30,
        "expectedAmount": expected_amount,
        "receivedAmount": total_paid,
        "amount": total_paid,
        "payType": slip_info.get("TYPE", "") or str(pay_data.get("method", "")).upper(),
        "method": str(pay_data.get("method", "")).upper(),
        "transactionNo": transaction_no,
        "paymentId": transaction_no,
        "receiver": slip_info.get("TRANSFER_TO", slip_info.get("RECEIVER", "")),
        "sender": slip_info.get("SENDER", ""),
        "date": slip_info.get("DATE", datetime.now().strftime("%d/%m/%Y")),
        "time": slip_info.get("TIME", datetime.now().strftime("%H:%M")),
        "source": "PAYMENT_SLIP",
        "approvedBy": approved_by,
        "password": password,
    }
    atomic_result = await approve_payment_transaction(atomic_payment)
    atomic_message = str(atomic_result.get("message") or "").strip()

    if atomic_result.get("result") == "duplicate":
        await clear_payment_draft(member_id, transaction_no)
        pending_payment.pop(member_id, None)
        return "⚠️ ဒီ Payment Transaction ကို အရင် Approve လုပ်ပြီးသားဖြစ်ပါတယ်။\nထပ်မံ Approve မလုပ်တော့ပါနှင့်။"
    if atomic_result.get("status") != "ok":
        if atomic_message == "transaction_already_used":
            return "⚠️ ဒီ Payment Transaction ကို အရင် Approve လုပ်ပြီးသားဖြစ်ပါတယ်။"
        if atomic_message == "transaction_in_progress":
            return "⚠️ ဒီ Payment ကို အခြား Approve request တစ်ခုက စစ်ဆေးနေဆဲပါ။"
        return (
            f"❌ Approve မအောင်မြင်ပါ — `{atomic_message or 'approval_failed'}`\n"
            "Member သက်တမ်းကို မပြောင်းထားပါ။"
        )

    canonical_password = str(atomic_result.get("password") or password)
    canonical_expire = str((atomic_result.get("member") or {}).get("expireDate") or "")
    await clear_payment_draft(member_id, transaction_no)
    pending_payment.pop(member_id, None)

    return (
        f"✅ *Google Login Member Approved!*\n\n"
        f"🆔 `{member_id}`\n"
        f"📦 Web Premium — {months} လ\n"
        f"⏰ ကုန်ဆုံး: `{canonical_expire}`\n"
        f"🔑 Password: `{canonical_password}`\n\n"
        f"⚠️ Member ဟာ Telegram DM မရနိုင်ပါ — website ကို ပြန်ဝင်ရင် (Sign in with "
        f"Google) access အသစ်ကို အလိုအလျောက် တွေ့ရပါလိမ့်မယ်။"
    )


async def _google_reject_member(member_id: str) -> str:
    if not member_id.startswith("G_"):
        return "❌ ဒါ Google Login member ID မဟုတ်ပါ (`G_` နဲ့ မစပါ)"
    pending_payment.pop(member_id, None)
    await clear_payment_draft(member_id, "")
    return f"✅ `{member_id}` ရဲ့ Payment ကို Reject လုပ်ပြီးပါပြီ — Member ဟာ website ကနေ slip အသစ် ပြန်ပို့နိုင်ပါတယ်"


async def googleapprove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not ADMIN_IDS or user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်")
        return
    if not context.args:
        await update.message.reply_text(
            "❌ Format: `/googleapprove G_xxxxxxxxxxxxxxxxxxx`\n\n"
            "(Slip အသစ်ရောက်တဲ့ admin notification message ထဲက ✅ Approve button ကို "
            "နှိပ်တာက ပိုလွယ်ပါတယ် — ID ကို လက်နဲ့ ကူးစရာ မလိုပါ)",
            parse_mode='Markdown')
        return
    member_id = _google_member_id_from_text(context.args[0])
    approved_by = str(
        getattr(update.effective_user, "username", "")
        or getattr(update.effective_user, "id", "")
    ).strip()
    result_text = await _google_approve_member(member_id, approved_by)
    await update.message.reply_text(result_text, parse_mode='Markdown')


async def googlereject_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not ADMIN_IDS or user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်")
        return
    if not context.args:
        await update.message.reply_text(
            "❌ Format: `/googlereject G_xxxxxxxxxxxxxxxxxxx`",
            parse_mode='Markdown')
        return
    member_id = _google_member_id_from_text(context.args[0])
    result_text = await _google_reject_member(member_id)
    await update.message.reply_text(result_text, parse_mode='Markdown')


# ── Places directory (admin-added, member-visible on website) ──
# A standalone Name/Location/Phone directory -- unrelated to the existing
# Brokers/Requests broker-marketplace sheets. Admin-only to add/remove;
# the website's Locations tab reads getPlaces read-only for every member.
async def addplace_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not ADMIN_IDS or user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်")
        return
    text = " ".join(context.args)
    parts = [p.strip() for p in text.split("|")]
    if len(parts) != 3 or not all(parts):
        await update.message.reply_text(
            "❌ Format: `/addplace Name | Location | Phone`\n\n"
            "ဥပမာ - `/addplace Bago Central | No.88 Main Road, Bago | 052200111`",
            parse_mode='Markdown')
        return
    name, location, phone = parts
    if not SHEET_WEBHOOK:
        await update.message.reply_text("❌ System error — Admin ကို ဆက်သွယ်ပါ")
        return
    added_by = str(getattr(update.effective_user, "username", "") or user_id).strip()
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.post(
                SHEET_WEBHOOK,
                json={
                    "action": "addPlace",
                    "place": {"name": name, "location": location, "phone": phone, "addedBy": added_by},
                    "serverKey": SHEET_SERVER_KEY,
                },
                timeout=25,
            )
        data = response.json()
        if data.get("status") == "ok":
            place = data.get("place", {}) or {}
            await update.message.reply_text(
                f"✅ *Place ထည့်ပြီးပါပြီ*\n\n"
                f"🆔 `{place.get('placeId', '')}`\n"
                f"🏢 {name}\n"
                f"📍 {location}\n"
                f"📞 {phone}",
                parse_mode='Markdown')
        else:
            await update.message.reply_text(
                f"❌ Place ထည့်၍မရပါ — `{data.get('message', 'error')}`", parse_mode='Markdown')
    except Exception as exc:
        logger.error("addplace_cmd: %s", exc)
        await update.message.reply_text("❌ Error — Admin ကို ဆက်သွယ်ပါ")


async def places_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not ADMIN_IDS or user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်")
        return
    if not SHEET_WEBHOOK:
        await update.message.reply_text("❌ System error — Admin ကို ဆက်သွယ်ပါ")
        return
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.post(SHEET_WEBHOOK, json={"action": "getPlaces"}, timeout=25)
        data = response.json()
        places = data.get("places", []) if isinstance(data, dict) else []
        if not places:
            await update.message.reply_text("📭 Place မရှိသေးပါ — `/addplace` နဲ့ ထည့်ပါ", parse_mode='Markdown')
            return
        lines = ["📍 *JACC Places*\n"]
        for p in places:
            lines.append(
                f"🆔 `{p.get('placeId', '')}`\n🏢 {p.get('name', '')}\n📍 {p.get('location', '')}\n📞 {p.get('phone', '')}\n"
            )
        await update.message.reply_text("\n".join(lines), parse_mode='Markdown')
    except Exception as exc:
        logger.error("places_cmd: %s", exc)
        await update.message.reply_text("❌ Error — Admin ကို ဆက်သွယ်ပါ")


async def removeplace_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not ADMIN_IDS or user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Admin သာ သုံးနိုင်တယ်")
        return
    if not context.args:
        await update.message.reply_text("❌ Format: `/removeplace <PlaceID>`", parse_mode='Markdown')
        return
    place_id = context.args[0].strip()
    if not SHEET_WEBHOOK:
        await update.message.reply_text("❌ System error — Admin ကို ဆက်သွယ်ပါ")
        return
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.post(
                SHEET_WEBHOOK,
                json={"action": "removePlace", "placeId": place_id, "serverKey": SHEET_SERVER_KEY},
                timeout=25,
            )
        data = response.json()
        if data.get("status") == "ok":
            await update.message.reply_text(f"✅ `{place_id}` ကို ဖျက်ပြီးပါပြီ", parse_mode='Markdown')
        else:
            await update.message.reply_text(
                f"❌ Place ဖျက်၍မရပါ — `{data.get('message', 'error')}`", parse_mode='Markdown')
    except Exception as exc:
        logger.error("removeplace_cmd: %s", exc)
        await update.message.reply_text("❌ Error — Admin ကို ဆက်သွယ်ပါ")


# ── JACC Google Login admin approval buttons ───────────────
# Separate CallbackQueryHandlers (registered with their own patterns ahead
# of the generic button_callback in main()) rather than new branches inside
# button_callback/membership_approval_patch.py -- those are shared,
# money-critical code for Telegram-origin members keyed by a numeric
# chat_id parsed with int(...); gapprove_/greject_ callback_data carries a
# "G_<sub>" string on purpose and must never flow through that int(...) path.
async def google_approve_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not ADMIN_IDS or query.from_user.id not in ADMIN_IDS:
        await query.answer("❌ Admin သာ လုပ်နိုင်တယ်", show_alert=True)
        return
    await query.answer()
    member_id = _google_member_id_from_text(str(query.data or "").replace("gapprove_", "", 1))
    approved_by = str(getattr(query.from_user, "username", "") or getattr(query.from_user, "id", "")).strip()
    result_text = await _google_approve_member(member_id, approved_by)
    await query.message.reply_text(result_text, parse_mode='Markdown')


async def google_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not ADMIN_IDS or query.from_user.id not in ADMIN_IDS:
        await query.answer("❌ Admin သာ လုပ်နိုင်တယ်", show_alert=True)
        return
    await query.answer()
    member_id = _google_member_id_from_text(str(query.data or "").replace("greject_", "", 1))
    result_text = await _google_reject_member(member_id)
    await query.message.reply_text(result_text, parse_mode='Markdown')


# ── Auto Expire Check ─────────────────────────────────
async def check_expired_members(context):
    global warned_3days
    try:
        async with httpx.AsyncClient() as client:
            resp    = await client.post(SHEET_WEBHOOK, json={"action":"getMembers","serverKey":SHEET_SERVER_KEY}, timeout=40, follow_redirects=True)
            members = resp.json().get("members",[])
        now = datetime.now(); kicked = []; kick_failed = []; expiring = []
        for m in members:
            uid = str(m.get('userId',''))
            if not uid: continue
            try:
                expire_date = datetime.strptime(m.get('expireDate','01/01/2000'), "%d/%m/%Y")
            except: continue
            days_left = (expire_date - now).days

            # warned_3days only suppresses repeat warnings within the SAME
            # 0-3 day expiry window. Once a member renews (days_left jumps
            # back above 3) or fully expires (days_left goes negative), drop
            # them so a future expiry window can warn them again — without
            # this, a member who renews after being warned once would never
            # get another "expiring soon" notice for as long as this
            # process stays up.
            if uid in warned_3days and not (0 <= days_left <= 3):
                warned_3days.discard(uid)

            if 0 <= days_left <= 3 and uid not in warned_3days:
                expiring.append(m); warned_3days.add(uid)
                if uid.isdigit():
                    try:
                        pw_resp = await (httpx.AsyncClient()).post(SHEET_WEBHOOK, json={
                            "action": "getPassword", "userId": uid, "serverKey": SHEET_SERVER_KEY}, timeout=10, follow_redirects=True)
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

            if m.get('status') == 'EXPIRED' and uid.isdigit():
                if int(uid) in ADMIN_IDS:
                    logger.warning(f"Skipping kick for admin ID {uid}")
                    continue

                # The EXPIRED flag above came from one getMembers snapshot
                # taken at the top of this run. kick_with_retry can take
                # several seconds (retries with backoff) per member, so by
                # the time we reach a member later in a large list, they may
                # have already renewed. Re-check their CURRENT status right
                # before kicking so a member who "just paid" isn't kicked on
                # stale data.
                fresh_record = await get_member_record(uid)
                fresh_status = str((fresh_record or {}).get("status") or "").strip().upper()
                if fresh_status and fresh_status != "EXPIRED":
                    logger.info(f"Skipping kick for {uid}: status is now {fresh_status}, not EXPIRED")
                    continue

                pkg = str(m.get('package','')).upper()

                if pkg == 'PROMO10D':
                    cancel_c = await get_cancel_count(uid)
                    has_order = cancel_c > 0
                    kick_status = "KICKED"
                    try:
                        await context.bot.send_message(
                            chat_id=int(uid),
                            text=("⏰ *10 Day Promo ကုန်ဆုံးပြီ*\n\n"
                                  + ("Order တင်ခဲ့သောကြောင့် ကျေးဇူးတင်ပါသည် 🙏\n"
                                     "Member အသစ်ဝင်ရန် /newmember" if has_order else
                                     "❌ Order မတင်ဘဲ ကုန်ဆုံးသောကြောင့် Kick ခံရပြီ\n"
                                     "နောက်ထပ် Promo မရနိုင်ပါ")),
                            parse_mode='Markdown')
                    except Exception as e:
                        logger.error(f"promo10d expire notify: {e}")

                success = await kick_with_retry(context, int(uid))
                if success:
                    kicked.append(m)
                    if SHEET_WEBHOOK:
                        try:
                            async with httpx.AsyncClient() as client:
                                await client.post(SHEET_WEBHOOK, json={
                                    "action": "updateStatus", "serverKey": SHEET_SERVER_KEY,
                                    "userId": uid,
                                    "status": "KICKED"
                                }, timeout=40, follow_redirects=True)
                        except Exception as e:
                            logger.error(f"updateStatus kicked: {e}")
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

# ── Ban Auto-Lift Scheduler ───────────────────────────
async def check_expired_bans(context):
    try:
        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.post(SHEET_WEBHOOK, json={
                "action": "liftExpiredBans",
            }, timeout=40)
        status_code = getattr(resp, "status_code", 0)
        if not (200 <= status_code < 300):
            logger.warning("check_expired_bans: webhook returned HTTP %s", status_code)
            return
        response_text = (getattr(resp, "text", "") or "").strip()
        if not response_text:
            logger.warning("check_expired_bans: webhook returned an empty body")
            return
        try:
            result = resp.json()
        except (TypeError, ValueError):
            logger.warning("check_expired_bans: webhook returned non-JSON content")
            return
        if not isinstance(result, dict):
            logger.warning(
                "check_expired_bans: webhook returned JSON type %s, expected object",
                type(result).__name__,
            )
            return
        lifted = result.get("lifted", [])
        if lifted:
            txt = "🔓 *Ban Auto-Lift*\n\n"
            for row in lifted:
                txt += f"• `{row.get('customerId')}` (@{row.get('username','?')}) — {row.get('banStatus')} ကုန်ဆုံးပြီ\n"
            await notify_admins(context, txt)
    except Exception as e:
        logger.error(f"check_expired_bans: {e}")

# ── Channel Member Validator ──────────────────────────
async def is_valid_member(user_id: int) -> bool:
    """Members sheet မှာ ACTIVE ဖြစ်တဲ့ user ဆိုရင် True return"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                SHEET_WEBHOOK,
                json={"action": "getMembers", "serverKey": SHEET_SERVER_KEY},
                timeout=40,
                follow_redirects=True
            )
        members = resp.json().get("members", [])
        for m in members:
            uid = str(m.get("userId", "")).strip()
            status = str(m.get("status", "")).upper()
            if uid.isdigit() and int(uid) == user_id:
                return status in ("ACTIVE", "PROMO10D")
        return False
    except Exception as e:
        logger.error(f"is_valid_member check: {e}")
        return True  # Sheet error ဆိုရင် safe side — kick မလုပ်


async def is_valid_google_member(member_id: str) -> bool:
    """Same ACTIVE/PROMO10D check as is_valid_member, but keyed by a Google
    Login member's full "G_<sub>" string id instead of a Telegram numeric
    id. A Google Login member's row is never uid.isdigit(), so
    is_valid_member() can never match them no matter which real Telegram
    account they use to open their invite link -- see
    handle_channel_member_join, which routes here only for a join made via
    a "G_"-tagged invite link."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                SHEET_WEBHOOK,
                json={"action": "getMembers", "serverKey": SHEET_SERVER_KEY},
                timeout=40,
                follow_redirects=True
            )
        members = resp.json().get("members", [])
        for m in members:
            if str(m.get("userId", "")).strip() == member_id:
                return str(m.get("status", "")).upper() in ("ACTIVE", "PROMO10D")
        return False
    except Exception as e:
        logger.error(f"is_valid_google_member check: {e}")
        return True  # Sheet error ဆိုရင် safe side — kick မလုပ်


# ── Channel Join Guard ────────────────────────────────
async def handle_channel_member_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Channel ထဲ user ဝင်လာတိုင်း Members sheet နဲ့ check လုပ်မယ်"""
    if not update.chat_member:
        return
    chat = update.chat_member.chat
    if str(chat.id) != str(CHANNEL_ID):
        return
    new_status = update.chat_member.new_chat_member.status
    if new_status not in ("member", "subscriber"):
        return

    user = update.chat_member.new_chat_member.user
    user_id = user.id
    username = user.username or str(user_id)

    if user_id in ADMIN_IDS:
        return

    # A Google Login member has no Telegram numeric id in the Members
    # sheet at all -- is_valid_member() can never recognize them regardless
    # of which real Telegram account they use to open their invite link.
    # create_invite_link() tags a Google-issued link's name with the
    # member's own "G_<sub>" id (see website_google_channel.py), and
    # Telegram echoes that name back on the join event, so route validation
    # by that tag instead of the joining account's Telegram id whenever
    # it's present.
    invite = update.chat_member.invite_link
    invite_name = str(getattr(invite, "name", "") or "").strip() if invite else ""
    if invite_name.startswith("G_"):
        is_valid = await is_valid_google_member(invite_name)
    else:
        is_valid = await is_valid_member(user_id)
    if not is_valid:
        kicked = await kick_with_retry(context, user_id)
        status_txt = "✅ Kicked အောင်မြင်" if kicked else "⚠️ Kick မအောင်မြင် — ကိုယ်တိုင် ဆောင်ရွက်ပါ"
        await notify_admins(
            context,
            f"🚨 *Unknown User Channel ဝင်ကြိုးစားမှု*\n\n"
            f"👤 @{username} (`{user_id}`)\n"
            f"📋 Members sheet မှာ မပါ / ACTIVE မဟုတ်\n"
            f"{status_txt}"
        )
        logger.warning(f"Channel join blocked: {user_id} @{username}")


# ── 12hr Channel Sweep ────────────────────────────────
async def check_unknown_channel_members(context):
    """12hr တိုင်း Members sheet ထဲက EXPIRED/KICKED user တွေ
    channel ထဲ ရှိသေးရင် kick လုပ်မယ်"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                SHEET_WEBHOOK,
                json={"action": "getMembers", "serverKey": SHEET_SERVER_KEY},
                timeout=40,
                follow_redirects=True
            )
        members = resp.json().get("members", [])

        kicked_list = []
        fail_list = []

        for m in members:
            uid = str(m.get("userId", "")).strip()
            status = str(m.get("status", "")).upper()
            username = m.get("username", "?")
            if not uid.isdigit():
                continue
            uid_int = int(uid)
            if uid_int in ADMIN_IDS:
                continue
            if status in ("ACTIVE", "PROMO10D"):
                continue

            # Channel ထဲ ရှိသေးလားစစ်
            try:
                member_info = await context.bot.get_chat_member(
                    chat_id=CHANNEL_ID, user_id=uid_int
                )
                still_in = member_info.status in ("member", "subscriber", "administrator", "creator")
            except Exception:
                still_in = False

            if still_in:
                success = await kick_with_retry(context, uid_int)
                if success:
                    kicked_list.append(f"@{username} (`{uid}`) — {status}")
                else:
                    fail_list.append(f"@{username} (`{uid}`) — {status}")

        if kicked_list:
            txt = "🔄 *12hr Sweep — Channel Kick:*\n\n" + "\n".join(f"• {x}" for x in kicked_list)
            await notify_admins(context, txt)
        if fail_list:
            txt = "⚠️ *12hr Sweep — Kick မအောင်မြင်:*\n\n" + "\n".join(f"• {x}" for x in fail_list)
            await notify_admins(context, txt)

    except Exception as e:
        logger.error(f"check_unknown_channel_members: {e}")


# ── Daily Premium "Use The App" Reminder ──────────────
async def remind_unused_premium_members(context):
    """Daily nudge for Web Premium members who haven't used the Web App
    recently. getMembers() now exposes lastActive (each user's most
    recent AuthSessions LastSeenAt, empty if they've never logged in at
    all — see Code.gs/_lastActiveByUser_). Repeats every day for a given
    member until they log in within the last 3 days, covering both
    "never used it since becoming Premium" and "used it once, then went
    quiet" the same way; it naturally stops once lastActive is recent.
    """
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                SHEET_WEBHOOK,
                json={"action": "getMembers", "serverKey": SHEET_SERVER_KEY},
                timeout=40,
                follow_redirects=True
            )
        members = resp.json().get("members", [])
        now = datetime.now()
        reminded = []
        failed = []
        for m in members:
            uid = str(m.get("userId", "")).strip()
            if not uid.isdigit():
                continue
            if int(uid) in ADMIN_IDS:
                continue
            if str(m.get("package", "")).upper() != "WEB":
                continue
            if str(m.get("status", "")).upper() != "ACTIVE":
                continue
            last_active = m.get("lastActive") or ""
            never_used = not last_active
            if not never_used:
                try:
                    last_seen = datetime.strptime(last_active[:19], "%Y-%m-%dT%H:%M:%S")
                    if (now - last_seen).days < 3:
                        continue
                except Exception:
                    pass
            try:
                async with httpx.AsyncClient() as pw_client:
                    pw_resp = await pw_client.post(SHEET_WEBHOOK, json={
                        "action": "getPassword", "userId": uid, "serverKey": SHEET_SERVER_KEY}, timeout=40, follow_redirects=True)
                password = pw_resp.json().get("password", "")
            except Exception:
                password = ""
            pw_line = f"\n🔑 Web Password: `{password}`\n" if password else ""
            title_suffix = " — App ကို တစ်ခါမှ မသုံးရသေးပါ" if never_used else ""
            try:
                await context.bot.send_message(
                    chat_id=int(uid),
                    text=(f"🔔 *Premium Reminder{title_suffix}*\n\n"
                          f"သင်ဟာ Web Premium Member ဖြစ်ပါတယ်! Web App ကနေ "
                          f"ဈေးနှုန်း/Chart တွေကို ကြည့်နိုင်ပါတယ် — သုံးကြည့်ပါ 👇\n"
                          f"{pw_line}\n"
                          f"🌐 https://kyawmintun08.github.io/Japan-Auction-Car-Checker/"),
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(
                        "🌐 Web App ဖွင့်",
                        url="https://kyawmintun08.github.io/Japan-Auction-Car-Checker/")]]))
                reminded.append(m)
            except Exception as e:
                logger.error(f"unused premium remind {uid}: {e}")
                failed.append(m)

        if reminded:
            txt = f"🔔 *Premium Reminder ပို့ပြီး: {len(reminded)} ယောက်*\n\n"
            txt += "\n".join(f"• @{m.get('username','?')} — `{m.get('userId','?')}`" for m in reminded[:15])
            if len(reminded) > 15:
                txt += f"\n... {len(reminded) - 15} ယောက် ထပ်ရှိ"
            await notify_admins(context, txt)
        if failed:
            txt = f"⚠️ *Premium Reminder ပို့မအောင်မြင်: {len(failed)} ယောက်*\n\n"
            txt += "\n".join(f"• @{m.get('username','?')} — `{m.get('userId','?')}`" for m in failed[:15])
            await notify_admins(context, txt)
    except Exception as e:
        logger.error(f"remind_unused_premium_members: {type(e).__name__} {e}")

# ── Main ──────────────────────────────────────────────
async def main():
    logger.info("Bot starting...")
    async with httpx.AsyncClient() as client:
        await client.post(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook",
                          params={"drop_pending_updates":True})
    # Auto-throttles outgoing Bot API calls (per-chat and bot-wide) and
    # transparently waits out Telegram's own RetryAfter cooldown instead of
    # raising it into handle_photo mid-flow. Bulk auction-list photo
    # uploads (each photo triggers several reply_text/send_photo calls in
    # quick succession) used to trip Telegram's flood control outright --
    # telegram.error.RetryAfter with no error handler registered, so every
    # message the bot tried to send during the ~8 minute cooldown was
    # silently dropped and the admin saw the bot go completely unresponsive
    # mid-upload.
    app = Application.builder().token(TOKEN).rate_limiter(AIORateLimiter()).build()
    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CommandHandler("newmember",   newmember_cmd))
    app.add_handler(CommandHandler("find",        find_car))
    app.add_handler(CommandHandler("model",       find_model))
    app.add_handler(CommandHandler("price",       add_price))
    app.add_handler(CommandHandler("history",     price_history_cmd))
    app.add_handler(CommandHandler("list",        list_cars))
    app.add_handler(CommandHandler("web",         web_link))
    app.add_handler(CommandHandler("app",         app_link))
    app.add_handler(CommandHandler("approve",     approve_member))
    app.add_handler(CommandHandler("members",     members_list))
    app.add_handler(CommandHandler("kick",        kick_member_cmd))
    app.add_handler(CommandHandler("renew",       renew_cmd))
    app.add_handler(CommandHandler("channel",     channel_cmd))
    app.add_handler(CommandHandler("mypassword",  mypassword_cmd))
    app.add_handler(CommandHandler("resetpass",   resetpass_cmd))
    app.add_handler(CommandHandler("updateid",    updateid_cmd))
    app.add_handler(CommandHandler("backup",      backup_cmd))
    app.add_handler(CommandHandler("finance",     finance_cmd))
    app.add_handler(CommandHandler("setqr",       setqr_cmd))
    app.add_handler(CommandHandler("broadcast",   broadcast_cmd))
    app.add_handler(CommandHandler("upgrade",     upgrade_cmd))
    app.add_handler(CommandHandler("redeem",        redeem_cmd))
    app.add_handler(CommandHandler("addbroker",     addbroker_cmd))
    app.add_handler(CommandHandler("kickbroker",    kickbroker_cmd))
    app.add_handler(CommandHandler("brokers",       brokers_cmd))
    app.add_handler(CommandHandler("brokerstart",   brokerstart_cmd))
    app.add_handler(CommandHandler("available",     available_cmd))
    app.add_handler(CommandHandler("busy",          busy_cmd))
    app.add_handler(CommandHandler("carrequest",    carrequest_cmd))
    app.add_handler(CommandHandler("cancelrequest", cancelrequest_cmd))
    app.add_handler(CommandHandler("mystatus",      mystatus_cmd))
    app.add_handler(CommandHandler("accept",        accept_cmd))
    app.add_handler(CommandHandler("endchat",       endchat_cmd))
    app.add_handler(CommandHandler("depositrequest", depositrequest_cmd))
    app.add_handler(CommandHandler("auctionwon",     auctionwon_cmd))
    app.add_handler(CommandHandler("auctionlost",    auctionlost_cmd))
    app.add_handler(CommandHandler("refunddone",     refunddone_cmd))
    app.add_handler(CommandHandler("googleapprove",  googleapprove_cmd))
    app.add_handler(CommandHandler("googlereject",   googlereject_cmd))
    app.add_handler(CommandHandler("addplace",       addplace_cmd))
    app.add_handler(CommandHandler("places",         places_cmd))
    app.add_handler(CommandHandler("removeplace",    removeplace_cmd))
    app.add_handler(CommandHandler("chatlog",        chatlog_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    # Registered ahead of the generic button_callback handler below so
    # gapprove_/greject_ (Google Login admin approval) are caught by their
    # own string-safe handlers first, never reaching button_callback's
    # int(...)-based Telegram-numeric-id parsing.
    app.add_handler(CallbackQueryHandler(google_approve_callback, pattern=r"^gapprove_"))
    app.add_handler(CallbackQueryHandler(google_reject_callback, pattern=r"^greject_"))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(ChatMemberHandler(handle_channel_member_join, ChatMemberHandler.CHAT_MEMBER))
    app.job_queue.run_repeating(check_expired_members,          interval=43200, first=60)
    app.job_queue.run_repeating(check_expired_bans,             interval=43200, first=120)
    app.job_queue.run_repeating(check_unknown_channel_members,  interval=43200, first=180)
    app.job_queue.run_repeating(remind_unused_premium_members,  interval=86400, first=240)
    await app.initialize()
    await app.start()

    member_commands = [
        BotCommand("start",         "🚗 Bot စတင်ရန်"),
        BotCommand("newmember",     "🆕 Member အသစ်ဝင်ရန်"),
        BotCommand("carrequest",    "🚙 ကားလိုအပ်ပါက ဒီနေရာနှိပ်ပါ"),
        BotCommand("mystatus",      "📋 Request Status စစ်ရန်"),
        BotCommand("upgrade",       "⬆️ Premium Package ပြောင်းရန်"),
        BotCommand("web",           "🌐 Web App link ကြည့်ရန်"),
        BotCommand("app",           "📱 App Download (Android + iPhone)"),
        BotCommand("renew",         "🔄 ရှိပြီးသား Member သက်တမ်းတိုး"),
        BotCommand("channel",       "📢 Channel link အသစ်ယူရန်"),
        BotCommand("mypassword",    "🔑 Password ပြန်ယူရန်"),
        BotCommand("redeem",        "🎁 Promo Code သုံးရန်"),
    ]
    broker_commands = member_commands + [
        BotCommand("brokerstart",   "👷 Broker စတင်ရန်"),
        BotCommand("available",     "🟢 Available ဖြစ်ကြောင်း"),
        BotCommand("busy",          "🔴 Busy ဖြစ်ကြောင်း"),
        BotCommand("accept",        "✅ Request လက်ခံရန်"),
        BotCommand("endchat",       "🔚 Session ပိတ်ရန်"),
        BotCommand("depositrequest","💰 Customer ကို Deposit တောင်းရန်"),
    ]
    admin_commands = member_commands + [
        BotCommand("price",         "💰 ကားဈေးထည့်ရန် (Admin)"),
        BotCommand("approve",       "✅ Member approve လုပ်ရန် (Admin)"),
        BotCommand("members",       "👥 Member စာရင်းကြည့်ရန် (Admin)"),
        BotCommand("kick",          "🚫 Member ထုတ်ရန် (Admin)"),
        BotCommand("resetpass",     "🔑 Password reset (Admin)"),
        BotCommand("updateid",      "🆔 Member ID update (Admin)"),
        BotCommand("setqr",         "💳 Payment QR setup (Admin)"),
        BotCommand("backup",        "💾 CSV Backup (Admin)"),
        BotCommand("finance",       "📊 Monthly Finance Report (Admin)"),
        BotCommand("broadcast",     "📢 Broadcast ပို့ရန် (Admin)"),
        BotCommand("addbroker",     "👷 Broker ထည့်ရန် (Admin)"),
        BotCommand("kickbroker",    "🚫 Broker ဖြတ်ရန် (Admin)"),
        BotCommand("brokers",       "📋 Broker list (Admin)"),
        BotCommand("auctionwon",    "🏆 ကားရပြီ (Admin)"),
        BotCommand("auctionlost",   "❌ ကားမရဘူး (Admin)"),
        BotCommand("refunddone",    "💸 Refund ပြီး (Admin)"),
        BotCommand("chatlog",       "📋 Chat log ကြည့်ရန် (Admin)"),
    ]
    try:
        await app.bot.set_my_commands(member_commands, scope=BotCommandScopeAllPrivateChats())
        for admin_id in ADMIN_IDS:
            try:
                await app.bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
            except Exception as e:
                logger.warning(f"Admin scope set failed for {admin_id}: {e}")
        brokers = await get_brokers()
        for b in brokers:
            try:
                tg_id = int(b.get("telegramId", 0))
                if tg_id:
                    await app.bot.set_my_commands(broker_commands, scope=BotCommandScopeChat(chat_id=tg_id))
            except Exception as e:
                logger.warning(f"Broker scope set failed: {e}")
        logger.info("Command scopes set successfully")
    except Exception as e:
        logger.error(f"set_my_commands error: {e}")

    startup_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    startup_msg = (
        f"🟢 *Bot ပြန်စတင်ပြီ*\n\n"
        f"⏰ {startup_time}\n"
        f"🤖 Model: `{GEMINI_MODEL}`\n"
        f"📦 Cars in memory: {len(CARS)}\n"
        f"👑 Admin IDs: {len(ADMIN_IDS)}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await app.bot.send_message(
                chat_id=admin_id,
                text=startup_msg,
                parse_mode='Markdown')
        except Exception as e:
            logger.warning(f"Startup notify {admin_id} failed: {e}")

    await app.updater.start_polling(drop_pending_updates=True, allowed_updates=Update.ALL_TYPES)
    logger.info("Bot polling!")

    # --- Railway Health Check Server ---
    async def health_check(request):
        return web.Response(text="Bot is running!")

    port = int(os.environ.get("PORT", 8080))
    web_app = web.Application(client_max_size=8 * 1024 * 1024 + 64 * 1024)
    web_app.router.add_get("/", health_check)

    # JDM lookup is an optional read-only Website/App endpoint. It is disabled
    # automatically when the server-side Supabase credentials are unavailable.
    jdm_http = build_jdm_http_service()
    if jdm_http is not None:
        web_app.router.add_options("/api/jdm/lookup", jdm_http.options)
        web_app.router.add_get("/api/jdm/lookup", jdm_http.lookup)
        web_app.router.add_options("/api/jdm/explain", jdm_http.options)
        web_app.router.add_post("/api/jdm/explain", jdm_http.explain)
        logger.info("JDM lookup and Burmese explanation endpoints mounted")

    qwen_http = build_qwen_text_http_service()
    if qwen_http is not None:
        web_app.router.add_options("/api/ai/query", qwen_http.options)
        web_app.router.add_post("/api/ai/query", qwen_http.query)
        logger.info("AI text query endpoint mounted (feature flag controls provider calls)")

    payment_http = build_website_payment_http_service(
        bot=app.bot,
        sheet_webhook=SHEET_WEBHOOK,
        admin_ids=ADMIN_IDS,
        pending_payment=pending_payment,
        plan_prices=PLAN_PRICES,
        plan_names=PLAN_NAMES,
        payment_method_info=PAYMENT_METHOD_INFO,
        gemini_reader=gemini_read_slip,
        parse_amount=parse_slip_amount,
        transaction_key=slip_transaction_key,
        payment_summary=payment_slip_summary,
        payment_qr_getter=get_payment_qr,
        save_payment_draft=save_payment_draft,
    )
    if payment_http is not None:
        web_app.router.add_options("/api/payment/slip", payment_http.options)
        web_app.router.add_post("/api/payment/slip", payment_http.upload)
        web_app.router.add_options("/api/payment/methods", payment_http.options)
        web_app.router.add_get("/api/payment/methods", payment_http.payment_methods)
        web_app.router.add_options("/api/payment/qr/{method}", payment_http.options)
        web_app.router.add_get("/api/payment/qr/{method}", payment_http.payment_qr)
        logger.info("Website payment slip, methods, and QR endpoints mounted")

    google_payment_http = build_google_member_payment_http_service(
        bot=app.bot,
        sheet_webhook=SHEET_WEBHOOK,
        admin_ids=ADMIN_IDS,
        pending_payment=pending_payment,
        plan_prices=PLAN_PRICES,
        payment_method_info=PAYMENT_METHOD_INFO,
        gemini_reader=gemini_read_slip,
        parse_amount=parse_slip_amount,
        transaction_key=slip_transaction_key,
        payment_summary=payment_slip_summary,
        save_payment_draft=save_payment_draft,
        payment_qr_getter=get_payment_qr,
    )
    if google_payment_http is not None:
        web_app.router.add_options("/api/google/payment/slip", google_payment_http.options)
        web_app.router.add_post("/api/google/payment/slip", google_payment_http.upload)
        web_app.router.add_options("/api/google/payment/methods", google_payment_http.options)
        web_app.router.add_get("/api/google/payment/methods", google_payment_http.payment_methods)
        web_app.router.add_options("/api/google/payment/qr/{method}", google_payment_http.options)
        web_app.router.add_get("/api/google/payment/qr/{method}", google_payment_http.payment_qr)
        logger.info("JACC Google Login payment slip, methods, and QR endpoints mounted")

    # create_invite_link(context, days, user_id=None, name=None) only ever
    # touches context.bot -- passing `app` itself (an Application, which
    # exposes .bot the same as an Update's context does) reuses the exact
    # same helper the /channel command calls, with no shim object needed.
    # The user_id-unban step is skipped by simply not passing one: a
    # Google Login member's synthetic "G_<sub>" id was never a real
    # Telegram identity, so it can never have been banned from the channel
    # either. `name` is set to the member's own id instead, so whichever
    # real Telegram account they use to open the link, the join event
    # carries that id back for handle_channel_member_join to validate by
    # (see is_valid_google_member) -- the joining account's own Telegram
    # id is never in the Members sheet at all.
    google_channel_http = build_google_member_channel_http_service(
        sheet_webhook=SHEET_WEBHOOK,
        create_invite_link=lambda member_id: create_invite_link(app, 7, name=member_id),
    )
    if google_channel_http is not None:
        web_app.router.add_options("/api/google/channel/invite", google_channel_http.options)
        web_app.router.add_post("/api/google/channel/invite", google_channel_http.invite)
        logger.info("JACC Google Login channel invite endpoint mounted")

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health check server started on port {port}")
    # ----------------------------------

    await asyncio.Event().wait()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user (Ctrl+C)")
    except Exception as e:
        import traceback
        logger.error(f"FATAL CRASH: {e}")
        logger.error(traceback.format_exc())
        raise
