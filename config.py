import os
import logging
from dotenv import load_dotenv

# Load from .env file if it exists (usually placed in the same folder)
load_dotenv()

# Telegram configurations
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_IDS_RAW = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_RAW.split(",") if x.strip().isdigit()]

# Database configuration
DB_PATH = os.getenv("DB_PATH", "/var/lib/vps-manager/vps_manager.db")

# Xray configurations
XRAY_CONFIG_PATH = os.getenv("XRAY_CONFIG_PATH", "/etc/xray/config.json")
XRAY_SYSTEMD_SERVICE = os.getenv("XRAY_SYSTEMD_SERVICE", "xray")

# Connection details for VLESS links
DOMAIN = os.getenv("DOMAIN", "yourdomain.com")
PORT = int(os.getenv("PORT", "443"))
TLS_CERT_PATH = os.getenv("TLS_CERT_PATH", "/etc/xray/certs/xray.crt")
TLS_KEY_PATH = os.getenv("TLS_KEY_PATH", "/etc/xray/certs/xray.key")

# Logging configuration
LOG_FILE = os.getenv("LOG_FILE", "/var/log/vps-manager/vps_manager.log")

# Setup logging directories
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("vps_manager")
