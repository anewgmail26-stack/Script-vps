import time
import logging
from datetime import datetime
import database
import xray_manager
import ssh_manager
from config import DB_PATH, XRAY_CONFIG_PATH, XRAY_SYSTEMD_SERVICE, logger

def run_scheduler_cycle():
    """
    Executes a single cycle of user traffic auditing and suspension checks.
    """
    logger.info("Executing scheduler monitoring cycle...")
    
    try:
        # 1. Verify and establish iptables rules for all active SSH users
        active_users = database.get_active_users(DB_PATH)
        for user in active_users:
            if user["type"] == "ssh":
                try:
                    ssh_manager.ensure_ssh_rule_exists(user["username"])
                except Exception as e:
                    logger.error(f"Error checking iptables rule for SSH user '{user['username']}': {e}")

        # 2. Query current in-memory stats from Xray
        xray_stats = xray_manager.query_xray_traffic()

        # 3. Process traffic updates
        for user in active_users:
            user_id = user["id"]
            username = user["username"]
            
            if user["type"] == "vless":
                uuid = user["uuid"]
                if uuid in xray_stats:
                    try:
                        current_uplink = xray_stats[uuid]["uplink"]
                        current_downlink = xray_stats[uuid]["downlink"]
                        
                        last_uplink = user["xray_uplink_last"]
                        last_downlink = user["xray_downlink_last"]
                        
                        # Handle potential reset of Xray counters (e.g. system/xray restarts)
                        delta_uplink = current_uplink - last_uplink if current_uplink >= last_uplink else current_uplink
                        delta_downlink = current_downlink - last_downlink if current_downlink >= last_downlink else current_downlink
                        
                        delta = delta_uplink + delta_downlink
                        if delta > 0:
                            new_total = user["traffic_used_bytes"] + delta
                            database.update_traffic(DB_PATH, user_id, new_total, current_uplink, current_downlink)
                            logger.info(f"VLESS user '{username}' ({uuid}) consumed {delta} bytes. Total: {new_total} bytes.")
                    except Exception as e:
                        logger.error(f"Error updating VLESS traffic for user {username}: {e}")
                        
            elif user["type"] == "ssh":
                try:
                    current_bytes = ssh_manager.get_ssh_traffic_bytes(username)
                    last_bytes = user["xray_uplink_last"] # Reuse this field to store SSH last counter
                    
                    # Handle potential reset of iptables counters
                    delta = current_bytes - last_bytes if current_bytes >= last_bytes else current_bytes
                    if delta > 0:
                        new_total = user["traffic_used_bytes"] + delta
                        database.update_traffic(DB_PATH, user_id, new_total, current_bytes, 0)
                        logger.info(f"SSH user '{username}' consumed {delta} bytes. Total: {new_total} bytes.")
                except Exception as e:
                    logger.error(f"Error updating SSH traffic for user {username}: {e}")

        # 4. Check for expirations and traffic limits
        # Fetch fresh data after traffic updates
        active_users = database.get_active_users(DB_PATH)
        now = datetime.now()
        xray_needs_sync = False

        for user in active_users:
            user_id = user["id"]
            username = user["username"]
            user_type = user["type"]
            expires_at = datetime.fromisoformat(user["expires_at"])
            traffic_limit = user["traffic_limit_bytes"]
            traffic_used = user["traffic_used_bytes"]
            
            # Expiry validation
            if now > expires_at:
                logger.info(f"User '{username}' ({user_type}) expired (Expiry: {user['expires_at']}). Suspending...")
                database.suspend_user(DB_PATH, user_id, "expired")
                
                if user_type == "vless":
                    xray_needs_sync = True
                elif user_type == "ssh":
                    ssh_manager.suspend_ssh_user(username)
                    
            # Traffic limit validation
            elif traffic_limit > 0 and traffic_used >= traffic_limit:
                logger.info(f"User '{username}' ({user_type}) reached traffic limit ({traffic_limit} bytes). Suspending...")
                database.suspend_user(DB_PATH, user_id, "traffic_limit")
                
                if user_type == "vless":
                    xray_needs_sync = True
                elif user_type == "ssh":
                    ssh_manager.suspend_ssh_user(username)

        # 5. Apply changes to Xray by syncing configuration file if VLESS clients were suspended
        if xray_needs_sync:
            logger.info("VLESS users were suspended. Syncing Xray config...")
            try:
                active_vless = database.get_active_vless_users(DB_PATH)
                xray_manager.sync_xray_config(XRAY_CONFIG_PATH, active_vless, XRAY_SYSTEMD_SERVICE)
            except Exception as e:
                logger.error(f"Failed to sync Xray configuration: {e}")

    except Exception as e:
        logger.error(f"Unhandled error in scheduler loop: {e}")
        
    logger.info("Scheduler monitoring cycle finished.")

def main():
    logger.info("Initializing VPS Manager Scheduler...")
    
    # Auto-initialize database on startup
    database.init_db(DB_PATH)
    
    # Sync Xray configuration on startup to ensure consistency
    try:
        logger.info("Performing initial Xray sync with database active VLESS clients...")
        active_vless = database.get_active_vless_users(DB_PATH)
        xray_manager.sync_xray_config(XRAY_CONFIG_PATH, active_vless, XRAY_SYSTEMD_SERVICE)
    except Exception as e:
        logger.error(f"Error performing initial Xray sync on startup: {e}")

    # Start loop
    logger.info("Scheduler is now running.")
    try:
        while True:
            run_scheduler_cycle()
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("Scheduler daemon stopped by user keyboard interrupt.")
    except Exception as e:
        logger.critical(f"Scheduler daemon crashed: {e}")

if __name__ == "__main__":
    main()
