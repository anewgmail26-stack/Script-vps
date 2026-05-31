#!/bin/bash

# VPS Manager Auto Installer for Ubuntu 24.04
# Make sure to run this script as root!

set -e

# Logging colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}====================================================${NC}"
echo -e "${GREEN}   VPS Management System Auto-Installer (Ubuntu 24.04)${NC}"
echo -e "${GREEN}====================================================${NC}"

# 1. Root Check
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: Please run this script as root.${NC}"
    exit 1
fi

# 2. Check Ubuntu Version
if [ -f /etc/os-release ]; then
    . /etc/os-release
    if [ "$ID" != "ubuntu" ] || [ "${VERSION_ID%%.*}" -lt 22 ]; then
        echo -e "${YELLOW}Warning: This script is optimized for Ubuntu 24.04/22.04. Proceeding on $NAME $VERSION...${NC}"
    fi
else
    echo -e "${YELLOW}Warning: OS release info not found. Attempting install anyway...${NC}"
fi

# 3. System Update and Dependencies Install
echo -e "\n${GREEN}[1/8] Updating packages and installing dependencies...${NC}"
apt-get update -y
apt-get install -y python3 python3-pip python3-venv ufw curl iptables openssl

# 4. Install Xray-core
echo -e "\n${GREEN}[2/8] Installing Xray-core from official repository...${NC}"
if ! command -v xray &> /dev/null; then
    bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
else
    echo -e "${YELLOW}Xray-core is already installed. Skipping core installation.${NC}"
fi

# 5. Gather Configurations (Environment parameters)
echo -e "\n${GREEN}[3/8] Configuring VPS Manager parameters...${NC}"

if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    read -p "Enter Telegram Bot Token: " TELEGRAM_BOT_TOKEN
    while [ -z "$TELEGRAM_BOT_TOKEN" ]; do
        echo -e "${RED}Token cannot be empty.${NC}"
        read -p "Enter Telegram Bot Token: " TELEGRAM_BOT_TOKEN
    done
fi

if [ -z "$ADMIN_IDS" ]; then
    read -p "Enter Admin Telegram User ID(s) (comma-separated, e.g. 1234567,9876543): " ADMIN_IDS
    while [ -z "$ADMIN_IDS" ]; do
        echo -e "${RED}Admin ID cannot be empty.${NC}"
        read -p "Enter Admin Telegram User ID(s): " ADMIN_IDS
    done
fi

if [ -z "$VPS_DOMAIN" ]; then
    read -p "Enter Domain/IP for VLESS connections (e.g. vpn.example.com): " VPS_DOMAIN
    while [ -z "$VPS_DOMAIN" ]; do
        echo -e "${RED}Domain cannot be empty.${NC}"
        read -p "Enter Domain/IP for VLESS: " VPS_DOMAIN
    done
fi

read -p "Enter VLESS listening port [default: 443]: " VLESS_PORT
VLESS_PORT=${VLESS_PORT:-443}

read -p "Enter TLS Certificate path [default: /etc/xray/certs/xray.crt]: " TLS_CERT_PATH
TLS_CERT_PATH=${TLS_CERT_PATH:-/etc/xray/certs/xray.crt}

read -p "Enter TLS Certificate Key path [default: /etc/xray/certs/xray.key]: " TLS_KEY_PATH
TLS_KEY_PATH=${TLS_KEY_PATH:-/etc/xray/certs/xray.key}

# 6. Fallback TLS Certification Generation
if [ ! -f "$TLS_CERT_PATH" ]; then
    echo -e "\n${YELLOW}Certificate file not found at '$TLS_CERT_PATH'. Generating a self-signed TLS cert...${NC}"
    mkdir -p "$(dirname "$TLS_CERT_PATH")"
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
        -keyout "$TLS_KEY_PATH" \
        -out "$TLS_CERT_PATH" \
        -subj "/CN=$VPS_DOMAIN"
    echo -e "${GREEN}Self-signed certificate generated successfully.${NC}"
fi

# 7. Setup Directory and Copy Source Files
echo -e "\n${GREEN}[4/8] Setting up directories and deployment files...${NC}"
INSTALL_DIR="/opt/vps-manager"
mkdir -p "$INSTALL_DIR"
mkdir -p "/var/lib/vps-manager"
mkdir -p "/var/log/vps-manager"

# Copy python scripts to deployment folder
cp config.py database.py xray_manager.py ssh_manager.py scheduler.py bot.py requirements.txt "$INSTALL_DIR/"

# 8. Create Environment Configuration File
echo -e "\n${GREEN}[5/8] Creating environmental parameters...${NC}"
cat <<EOF > "$INSTALL_DIR/.env"
TELEGRAM_BOT_TOKEN="$TELEGRAM_BOT_TOKEN"
ADMIN_IDS="$ADMIN_IDS"
DB_PATH="/var/lib/vps-manager/vps_manager.db"
XRAY_CONFIG_PATH="/etc/xray/config.json"
XRAY_SYSTEMD_SERVICE="xray"
DOMAIN="$VPS_DOMAIN"
PORT="$VLESS_PORT"
TLS_CERT_PATH="$TLS_CERT_PATH"
TLS_KEY_PATH="$TLS_KEY_PATH"
LOG_FILE="/var/log/vps-manager/vps_manager.log"
EOF
chmod 600 "$INSTALL_DIR/.env"

# 9. Setup Virtual Environment and Install Requirements
echo -e "\n${GREEN}[6/8] Creating virtual environment and installing python dependencies...${NC}"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

# 10. Register Systemd Daemon Configurations
echo -e "\n${GREEN}[7/8] Registering systemd daemon services...${NC}"

# Create Bot Service
cat <<EOF > /etc/systemd/system/vps-bot.service
[Unit]
Description=VPS Manager Telegram Bot Daemon
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python bot.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Create Scheduler Service
cat <<EOF > /etc/systemd/system/vps-scheduler.service
[Unit]
Description=VPS Manager Expiry and Traffic Monitor Scheduler
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python scheduler.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Reload and Enable Services
systemctl daemon-reload
systemctl enable vps-bot.service
systemctl enable vps-scheduler.service

# Start Services
systemctl start vps-bot.service || echo -e "${YELLOW}Warning: vps-bot service could not start immediately. Please run '/opt/vps-manager/venv/bin/python bot.py' manually to diagnose config issues.${NC}"
systemctl start vps-scheduler.service || echo -e "${YELLOW}Warning: vps-scheduler service could not start immediately.${NC}"

# 11. Configure UFW Firewall rules
echo -e "\n${GREEN}[8/8] Configuring UFW rules...${NC}"
ufw allow 22/tcp || true
ufw allow "$VLESS_PORT"/tcp || true
ufw --force enable || true

echo -e "\n${GREEN}====================================================${NC}"
echo -e "${GREEN}              Installation Completed!               ${NC}"
echo -e "${GREEN}====================================================${NC}"
echo -e "You can manage VPS systems now using the registered bot."
echo -e "Use the command ${YELLOW}systemctl status vps-bot vps-scheduler${NC} to check daemon states."
echo -e "Full logs are located at: ${YELLOW}/var/log/vps-manager/vps_manager.log${NC}"
echo -e "${GREEN}====================================================${NC}"
