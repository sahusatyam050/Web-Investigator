import os
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SCREENSHOTS_DIR = BASE_DIR / "screenshots"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "evidence.db"

# Crawler Parameters
DEFAULT_MAX_PAGES = 15
DEFAULT_RENDER_TIMEOUT = 15000  # ms for Playwright (15 seconds)
HEADLESS = False  # Headed mode for visible browser & manual auth

# Priority Navigation Lists
HIGH_PRIORITY_KEYWORDS = [
    "deposit", "withdraw", "withdrawal", "wallet", "cashier", 
    "payment", "pay", "transactions", "transaction", "recharge", 
    "bonus", "referral", "rewards", "reward", "kyc", "profile", 
    "account", "add money", "cash out", "login", "log in", 
    "sign in", "signin", "register", "sign up", "signup"
]

MEDIUM_PRIORITY_KEYWORDS = [
    "casino", "games", "game", "slots", "slot", "fantasy", 
    "sports", "promotions", "promotion", "leaderboard", "live casino",
    "roulette", "blackjack", "poker", "baccarat", "betting", "match"
]

LOW_PRIORITY_KEYWORDS = [
    "about", "faq", "contact", "terms", "privacy", "help", 
    "blog", "news", "responsible gaming", "disclaimer", "license"
]

# Categorized Keyword Lists for Detection
CATEGORIZED_KEYWORDS = {
    "Financial": [
        "deposit", "withdraw", "withdrawal", "wallet", "cashier", 
        "balance", "transfer", "payout", "topup", "add money", 
        "bank", "upi", "gateway", "currency", "inr", "usd", 
        "crypto", "usdt", "transaction", "recharge"
    ],
    "Gaming": [
        "casino", "slot", "slots", "roulette", "blackjack", "poker", 
        "baccarat", "sports", "live sports", "fantasy", "betting", 
        "odds", "match", "tournament", "jackpot", "table games", 
        "crash game", "aviator", "mines", "spin"
    ],
    "Rewards": [
        "bonus", "referral", "rewards", "cashback", "spin", "wheel", 
        "promo", "promotion", "free bet", "vip", "welcome bonus", 
        "deposit bonus", "loyalty", "points", "claim"
    ],
    "Authentication": [
        "login", "sign in", "signin", "register", "sign up", "signup", 
        "kyc", "verify", "verification", "otp", "password", "account", 
        "forgot password", "join now", "register now"
    ],
    "Legal": [
        "terms", "privacy", "policy", "license", "terms of service", 
        "responsible gaming", "18+", "anti-money laundering", "aml", 
        "disclaimer", "curacao", "malta", "isom"
    ],
    "Social": [
        "telegram", "whatsapp", "discord", "instagram", "facebook", 
        "twitter", "support", "contact us", "live chat", "channel"
    ]
}

# Category Colors for OpenCV Bounding Boxes (BGR Format for OpenCV)
CATEGORY_COLORS_BGR = {
    "Financial": (0, 200, 0),       # Green
    "Gaming": (255, 120, 0),        # Blue / Cyan
    "Rewards": (0, 215, 255),       # Gold / Yellow
    "Authentication": (0, 0, 230),  # Red
    "Legal": (180, 50, 180),        # Purple
    "Social": (255, 190, 0),        # Teal / Light Blue
    "Payment_Indicator": (0, 0, 255)# Bright Red
}

# Bounding Box Hex Colors for UI Legend
CATEGORY_COLORS_HEX = {
    "Financial": "#00C800",
    "Gaming": "#0078FF",
    "Rewards": "#FFD700",
    "Authentication": "#E60000",
    "Legal": "#B432B4",
    "Social": "#00BEFF",
    "Payment_Indicator": "#FF0000"
}

# Payment Indicator Patterns & Signatures
PAYMENT_INDICATOR_PATTERNS = {
    "UPI_ID": r"[a-zA-Z0-9.\-_]+@(upi|okicici|ybl|paytm|ibl|axl|sbi|kotak|barodampay|icici|hdfcbank|okaxis|oksbi|okhdfcbank)",
    "PAYMENT_GATEWAY": r"(razorpay|cashfree|stripe|paytm|phonepe|google pay|gpay|payu|instamojo|paypal|ccavenue)",
    "QR_CODE": r"(qr code|scan and pay|upi qr|scan to pay|scan qr)",
    "BANK_TRANSFER": r"(bank transfer|imps|neft|rtgs|account number|ifsc|account name)",
    "WALLET": r"(paytm wallet|phonepe wallet|mobikwik|freecharge|crypto wallet|usdt trc20|bep20)"
}
