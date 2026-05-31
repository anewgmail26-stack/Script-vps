# VPS Management System (VLESS + SSH) for Ubuntu 24.04

This is a production-ready, lightweight VPS management system written in Python 3. It utilizes Xray-core directly for VLESS (TCP + TLS) and configures Linux system accounts for SSH tunneling proxies. It features an automated expiry and billing system, traffic monitoring limits, and a secure Telegram Bot management interface.

---

## Features

- **Xray-core Integration**: Manages `/etc/xray/config.json` directly. No x-ui dependencies.
- **Protocols Supported**:
  - **VLESS over TCP + TLS** (on configured port, e.g. 443).
  - **SSH Tunneling Proxies** (non-interactive `/usr/sbin/nologin` accounts on port 22).
- **Traffic Accountability**:
  - Automatically queries Xray client stats using the internal API port `10085` via `xray api statsquery`.
  - Measures SSH user traffic through individual outbound `iptables` owner rules (`--uid-owner`).
  - Correctly computes and updates traffic totals even across server restarts or Xray reboots (delta cache tracking).
- **Automated Scheduler**:
  - Background billing loop audits user statuses every 60 seconds.
  - Automatically suspends users who reach their traffic limit.
  - Automatically suspends users whose expiration dates have passed.
  - Instantly kills active sessions (`pkill`) of suspended or deleted SSH clients.
- **Config Backup**: Retains the last 10 versions of the Xray configuration files automatically before making any changes.
- **Security**: Only Telegram accounts declared in `ADMIN_IDS` can interact with the bot interface.

---

## Project Structure

```
├── config.py          # Configuration loader, logger, and .env parser
├── database.py        # SQLite Database schema and user CRUD operations
├── xray_manager.py    # Xray config writer, JSON synchronizer, and stats query wrapper
├── ssh_manager.py     # OS user administration and iptables interface
├── scheduler.py       # Expiration checks and traffic limits daemon
├── bot.py             # Telegram commands controller
├── requirements.txt   # Pin of python dependencies
├── install.sh         # Systemd, package, and firewall installer shell script
└── README.md          # This documentation file
```

---

## Installation

### Prerequisites
- A VPS running a clean installation of **Ubuntu 24.04** (Ubuntu 22.04 is also supported).
- A domain name pointing to your VPS IP (needed for TLS certificates).
- A Telegram Bot Token (obtained from [@BotFather](https://t.me/BotFather)).
- Your Telegram User ID (obtained from [@userinfobot](https://t.me/userinfobot)).

### Steps

1. Clone or download this project to your VPS.
2. Grant executable permissions to the installer:
   ```bash
   chmod +x install.sh
   ```
3. Run the installer script as root:
   ```bash
   sudo ./install.sh
   ```
4. The installer will prompt you for configuration details:
   - Telegram Bot Token
   - Telegram Admin ID(s) (comma-separated if multiple admins)
   - Domain (e.g. `yourdomain.com`)
   - VLESS Port (default: `443`)
   - Certificate path (defaults to self-signed generation if certificate is not found)

---

## Telegram Bot Commands

Once the bot is running, message it on Telegram. The following commands are restricted to authorized admins:

| Command | Arguments | Description |
| :--- | :--- | :--- |
| `/start` or `/help` | - | Displays greeting and detailed command directory. |
| `/create_vless` | `<days> <gb>` | Registers a VLESS client. Set `gb` to `0` for unlimited traffic. Returns sharing URI. |
| `/delete_vless` | `<uuid>` | Cleans client from the database and updates Xray config file. |
| `/create_ssh` | `<username> <password> <days>` | Registers a system user with shell `/usr/sbin/nologin` and rules. |
| `/delete_ssh` | `<username>` | Deletes system user, rules, and terminates active SSH sessions. |
| `/list_users` | - | Formats status report of all users (traffic usage and expiry). |
| `/status` | - | Reports VPS hardware usage (CPU/RAM/Disk) and service states. |
| `/restart_xray` | - | Restarts the Xray systemd daemon. |

---

## Management and Maintenance

### Check Service Status
```bash
# Telegram Bot Service
systemctl status vps-bot.service

# Expiry Scheduler Service
systemctl status vps-scheduler.service

# Xray Core Service
systemctl status xray.service
```

### View Application Logs
Logs are kept in the `/var/log/vps-manager/` directory:
```bash
tail -f /var/log/vps-manager/vps_manager.log
```

### Database Location
The SQLite database stores all records in:
`/var/lib/vps-manager/vps_manager.db`

---

## Architecture and Design Decisions

1. **Isolation**: Python scripts execute within a dedicated virtual environment (`/opt/vps-manager/venv`) to keep them isolated from system-level python dependencies.
2. **Reliability**: Config synchronization compares current active clients with new lists before executing restarts, preventing unnecessary dropouts on user updates.
3. **Double Forwarding Capture**: For SSH proxying, all client data packets going out to the web match the client UID. Because SSH tunneling routes all traffic through `sshd` executing under the client's UID, tracking output packets using iptables owner flags successfully captures their entire usage metric.
