import telebot
import uuid
import subprocess
import logging
from datetime import datetime, timedelta
import database
import xray_manager
import ssh_manager
from config import (
    TELEGRAM_BOT_TOKEN,
    ADMIN_IDS,
    DB_PATH,
    XRAY_CONFIG_PATH,
    XRAY_SYSTEMD_SERVICE,
    DOMAIN,
    PORT,
    logger
)

# Initialize Telegram Bot
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

def is_admin(user_id):
    """
    Checks if the Telegram user ID is an authorized admin.
    """
    return user_id in ADMIN_IDS

def format_bytes(size_in_bytes):
    """
    Converts bytes into human-readable representation.
    """
    if size_in_bytes < 0:
        return "Unlimited"
    for unit in ['Bytes', 'KB', 'MB', 'GB', 'TB']:
        if size_in_bytes < 1024.0:
            return f"{size_in_bytes:.2f} {unit}"
        size_in_bytes /= 1024.0
    return f"{size_in_bytes:.2f} PB"

@bot.message_handler(func=lambda message: not is_admin(message.from_user.id))
def unauthorized_handler(message):
    """
    Filters out unauthorized callers.
    """
    bot.reply_to(message, "❌ <b>Access Denied.</b> You are not authorized to use this bot.", parse_mode="HTML")

@bot.message_handler(commands=['start', 'help'])
def help_command(message):
    """
    Returns help and command guidelines.
    """
    help_text = (
        "🛡️ <b>VPS Manager Telegram Bot</b>\n\n"
        "Available Commands:\n"
        "🔑 <b>VLESS Management:</b>\n"
        "• <code>/create_vless &lt;days&gt; &lt;gb&gt;</code> - Create VLESS account (gb=0 for unlimited)\n"
        "• <code>/delete_vless &lt;uuid&gt;</code> - Delete a VLESS account\n\n"
        "🖥️ <b>SSH Management:</b>\n"
        "• <code>/create_ssh &lt;username&gt; &lt;password&gt; &lt;days&gt;</code> - Create SSH proxy account\n"
        "• <code>/delete_ssh &lt;username&gt;</code> - Delete a SSH proxy account\n\n"
        "📊 <b>System & Database:</b>\n"
        "• <code>/list_users</code> - View all users, traffic stats, and expiries\n"
        "• <code>/status</code> - View server load (CPU/RAM/Disk) and services health\n"
        "• <code>/restart_xray</code> - Restart the Xray-core service\n"
    )
    bot.reply_to(message, help_text, parse_mode="HTML")

@bot.message_handler(commands=['create_vless'])
def create_vless_command(message):
    """
    Handler to create a new VLESS user.
    """
    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "⚠️ <b>Usage:</b> <code>/create_vless &lt;days&gt; &lt;gb&gt;</code>", parse_mode="HTML")
        return
        
    try:
        days = int(args[1])
        gb = int(args[2])
        if days < 1 or gb < 0:
            raise ValueError()
    except ValueError:
        bot.reply_to(message, "❌ <b>Error:</b> Expiry days must be &gt;= 1, and traffic GB must be &gt;= 0.", parse_mode="HTML")
        return

    # Generate credentials
    uuid_str = str(uuid.uuid4())
    username = f"vless_user_{uuid_str[:8]}"
    expires_at = datetime.now() + timedelta(days=days)
    
    # Calculate traffic limit in bytes (-1 representing unlimited)
    traffic_limit_bytes = gb * 1024 * 1024 * 1024 if gb > 0 else -1

    # Insert into database
    success = database.add_vless_user(DB_PATH, username, uuid_str, expires_at, traffic_limit_bytes)
    if not success:
        bot.reply_to(message, "❌ <b>Error:</b> Database write failed. Check server logs.", parse_mode="HTML")
        return

    # Sync configuration file and restart xray
    active_vless = database.get_active_vless_users(DB_PATH)
    sync_success = xray_manager.sync_xray_config(XRAY_CONFIG_PATH, active_vless, XRAY_SYSTEMD_SERVICE)
    
    if not sync_success:
        bot.reply_to(message, "⚠️ User registered, but failed to sync and reload Xray-core. Check service logs.", parse_mode="HTML")
        return

    # Construct standard VLESS sharing URI
    vless_link = f"vless://{uuid_str}@{DOMAIN}:{PORT}?security=tls&encryption=none#{username}"
    
    response = (
        "✅ <b>VLESS Client Created Successfully!</b>\n\n"
        f"👤 <b>Remark:</b> {username}\n"
        f"🔑 <b>UUID:</b> <code>{uuid_str}</code>\n"
        f"📅 <b>Expires:</b> {expires_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"📊 <b>Traffic Limit:</b> {'Unlimited' if gb == 0 else f'{gb} GB'}\n\n"
        f"🔗 <b>VLESS URI Connection Link:</b>\n<code>{vless_link}</code>"
    )
    bot.reply_to(message, response, parse_mode="HTML")

@bot.message_handler(commands=['delete_vless'])
def delete_vless_command(message):
    """
    Handler to delete a VLESS user by UUID.
    """
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "⚠️ <b>Usage:</b> <code>/delete_vless &lt;uuid&gt;</code>", parse_mode="HTML")
        return
        
    uuid_str = args[1].strip()
    user = database.delete_user_by_uuid(DB_PATH, uuid_str)
    
    if not user:
        bot.reply_to(message, "❌ <b>Error:</b> Client with specified UUID not found in database.", parse_mode="HTML")
        return
        
    # Sync config to remove user and reload service
    active_vless = database.get_active_vless_users(DB_PATH)
    sync_success = xray_manager.sync_xray_config(XRAY_CONFIG_PATH, active_vless, XRAY_SYSTEMD_SERVICE)
    
    if sync_success:
        bot.reply_to(message, f"✅ <b>VLESS User '{user['username']}' deleted successfully.</b>", parse_mode="HTML")
    else:
        bot.reply_to(message, f"⚠️ User deleted from DB, but failed to sync and reload Xray-core.", parse_mode="HTML")

@bot.message_handler(commands=['create_ssh'])
def create_ssh_command(message):
    """
    Handler to create an SSH tunnel user.
    """
    args = message.text.split()
    if len(args) < 4:
        bot.reply_to(message, "⚠️ <b>Usage:</b> <code>/create_ssh &lt;username&gt; &lt;password&gt; &lt;days&gt;</code>", parse_mode="HTML")
        return
        
    username = args[1].strip()
    password = args[2].strip()
    
    try:
        days = int(args[3])
        if days < 1:
            raise ValueError()
    except ValueError:
        bot.reply_to(message, "❌ <b>Error:</b> Days must be an integer &gt;= 1.", parse_mode="HTML")
        return

    # Basic input checks
    if not username.isalnum() or len(username) < 3 or len(username) > 16:
        bot.reply_to(message, "❌ <b>Error:</b> Username must be alphanumeric, between 3 and 16 characters.", parse_mode="HTML")
        return
        
    if len(password) < 6:
        bot.reply_to(message, "❌ <b>Error:</b> Password must be at least 6 characters long.", parse_mode="HTML")
        return

    # Check if database contains user
    existing_user = database.get_user_by_username(DB_PATH, username, "ssh")
    if existing_user:
        bot.reply_to(message, "❌ <b>Error:</b> User with this username already exists in database.", parse_mode="HTML")
        return

    # Create OS Linux User
    os_success = ssh_manager.create_ssh_user(username, password)
    if not os_success:
        bot.reply_to(message, "❌ <b>Error:</b> Failed to create system user account. Check logs for details.", parse_mode="HTML")
        return

    # Add to DB
    expires_at = datetime.now() + timedelta(days=days)
    success = database.add_ssh_user(DB_PATH, username, password, expires_at, -1) # Unlimited traffic by default
    
    if not success:
        bot.reply_to(message, "❌ <b>Error:</b> Registered OS user, but SQLite database insertion failed.", parse_mode="HTML")
        return

    response = (
        "✅ <b>SSH Tunnel Client Created!</b>\n\n"
        f"🖥️ <b>Host Domain/IP:</b> <code>{DOMAIN}</code>\n"
        f"🔌 <b>Port:</b> <code>22</code>\n"
        f"👤 <b>Username:</b> <code>{username}</code>\n"
        f"🔑 <b>Password:</b> <code>{password}</code>\n"
        f"📅 <b>Expires:</b> {expires_at.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    bot.reply_to(message, response, parse_mode="HTML")

@bot.message_handler(commands=['delete_ssh'])
def delete_ssh_command(message):
    """
    Handler to delete an SSH user.
    """
    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "⚠️ <b>Usage:</b> <code>/delete_ssh &lt;username&gt;</code>", parse_mode="HTML")
        return
        
    username = args[1].strip()
    
    # Query database before deleting to confirm existence
    user = database.get_user_by_username(DB_PATH, username, "ssh")
    if not user:
        bot.reply_to(message, "❌ <b>Error:</b> SSH user not found in database.", parse_mode="HTML")
        return

    # Run system and database deletions
    os_success = ssh_manager.delete_ssh_user(username)
    db_user = database.delete_user_by_username(DB_PATH, username, "ssh")
    
    if os_success and db_user:
        bot.reply_to(message, f"✅ <b>SSH User '{username}' deleted successfully.</b>", parse_mode="HTML")
    else:
        bot.reply_to(message, f"⚠️ SSH User cleanup completed with warnings (System: {os_success}, DB: {db_user is not None}).", parse_mode="HTML")

@bot.message_handler(commands=['list_users'])
def list_users_command(message):
    """
    Handler to list all users, sorted by types.
    """
    users = database.get_all_users(DB_PATH)
    if not users:
        bot.reply_to(message, "📭 <b>No registered users found in the database.</b>", parse_mode="HTML")
        return

    vless_users = [u for u in users if u["type"] == "vless"]
    ssh_users = [u for u in users if u["type"] == "ssh"]

    response = "📊 <b>VPS System Client List</b>\n\n"

    if vless_users:
        response += "🔑 <b>VLESS Clients:</b>\n"
        for i, u in enumerate(vless_users, 1):
            status = "🟢 Active" if u["is_active"] else f"🔴 Suspended ({u['suspension_reason']})"
            limit_str = format_bytes(u["traffic_limit_bytes"])
            used_str = format_bytes(u["traffic_used_bytes"])
            
            response += (
                f"{i}. <b>{u['username']}</b>\n"
                f"   • UUID: <code>{u['uuid']}</code>\n"
                f"   • Status: {status}\n"
                f"   • Limit: {limit_str} | Used: {used_str}\n"
                f"   • Expiry: {u['expires_at']}\n"
            )
        response += "\n"

    if ssh_users:
        response += "🖥️ <b>SSH Clients:</b>\n"
        for i, u in enumerate(ssh_users, 1):
            status = "🟢 Active" if u["is_active"] else f"🔴 Suspended ({u['suspension_reason']})"
            used_str = format_bytes(u["traffic_used_bytes"])
            
            response += (
                f"{i}. <b>{u['username']}</b>\n"
                f"   • Status: {status}\n"
                f"   • Limit: Unlimited | Used: {used_str}\n"
                f"   • Expiry: {u['expires_at']}\n"
            )

    # Telegram message limit fallback (chunk output if size is close to 4096 characters)
    if len(response) > 4000:
        chunks = [response[i:i+4000] for i in range(0, len(response), 4000)]
        for chunk in chunks:
            bot.send_message(message.chat.id, chunk, parse_mode="HTML")
    else:
        bot.reply_to(message, response, parse_mode="HTML")

@bot.message_handler(commands=['status'])
def status_command(message):
    """
    Gathers memory usage, CPU load, disk usage, and service states.
    """
    bot.send_chat_action(message.chat.id, 'typing')
    
    # 1. Fetch system RAM info
    ram_used = "N/A"
    try:
        ram_result = subprocess.run(
            "free -h | awk '/Mem:/ {print $3 \" / \" $2}'",
            shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        if ram_result.returncode == 0:
            ram_used = ram_result.stdout.strip()
    except Exception:
        pass

    # 2. Fetch disk space info
    disk_used = "N/A"
    try:
        disk_result = subprocess.run(
            "df -h / | awk '/\\// {print $3 \" / \" $2 \" (Usage: \" $5 \")\"}'",
            shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        if disk_result.returncode == 0:
            disk_used = disk_result.stdout.strip()
    except Exception:
        pass

    # 3. Fetch CPU load avg
    cpu_load = "N/A"
    try:
        with open("/proc/loadavg", "r") as f:
            cpu_load = f.read().split()[:3]
            cpu_load = ", ".join(cpu_load)
    except Exception:
        pass

    # 4. Read Xray and SSH state
    xray_state = "Offline 🔴"
    ssh_state = "Offline 🔴"

    try:
        xray_chk = subprocess.run(["systemctl", "is-active", XRAY_SYSTEMD_SERVICE], capture_output=True, text=True)
        if xray_chk.stdout.strip() == "active":
            xray_state = "Running 🟢"
    except Exception:
        pass

    try:
        ssh_chk = subprocess.run(["systemctl", "is-active", "ssh"], capture_output=True, text=True)
        if ssh_chk.stdout.strip() == "active":
            ssh_state = "Running 🟢"
        else:
            # Fallback for sshd
            ssh_chk2 = subprocess.run(["systemctl", "is-active", "sshd"], capture_output=True, text=True)
            if ssh_chk2.stdout.strip() == "active":
                ssh_state = "Running 🟢"
    except Exception:
        pass

    status_text = (
        "📈 <b>Server Status Report</b>\n\n"
        f"📊 <b>CPU Load Average:</b> <code>{cpu_load}</code>\n"
        f"💾 <b>RAM Usage:</b> <code>{ram_used}</code>\n"
        f"📁 <b>Disk Space (Root):</b> <code>{disk_used}</code>\n\n"
        f"⚙️ <b>Xray Service:</b> {xray_state}\n"
        f"🔑 <b>SSH Daemon:</b> {ssh_state}\n"
    )
    bot.reply_to(message, status_text, parse_mode="HTML")

@bot.message_handler(commands=['restart_xray'])
def restart_xray_command(message):
    """
    Manual override command to trigger a configuration reload and service restart.
    """
    bot.send_chat_action(message.chat.id, 'typing')
    success = xray_manager.restart_xray(XRAY_SYSTEMD_SERVICE)
    if success:
        bot.reply_to(message, "✅ <b>Xray-core restarted successfully!</b>", parse_mode="HTML")
    else:
        bot.reply_to(message, "❌ <b>Error:</b> Failed to restart Xray-core. Check system logs.", parse_mode="HTML")

def main():
    logger.info("Initializing SQLite database on startup...")
    database.init_db(DB_PATH)
    logger.info("Starting Telegram Bot listener loop...")
    
    # Run polling loop
    try:
        bot.infinity_polling()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user keyboard interrupt.")
    except Exception as e:
        logger.critical(f"Bot listener crashed: {e}")

if __name__ == "__main__":
    main()
