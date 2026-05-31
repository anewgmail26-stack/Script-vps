import json
import os
import shutil
import subprocess
import logging
from datetime import datetime

logger = logging.getLogger("vps_manager")

def backup_config(config_path):
    """
    Creates a timestamped backup of the Xray configuration file.
    Limits the number of backups to 10.
    """
    if not os.path.exists(config_path):
        return
    try:
        backup_dir = os.path.join(os.path.dirname(config_path), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"config_{timestamp}.json")
        shutil.copy2(config_path, backup_path)
        logger.info(f"Xray config backup created: {backup_path}")
        
        # Limit backups to 10
        backups = sorted([
            os.path.join(backup_dir, f) 
            for f in os.listdir(backup_dir) 
            if f.startswith("config_") and f.endswith(".json")
        ])
        while len(backups) > 10:
            removed = backups.pop(0)
            os.remove(removed)
            logger.debug(f"Removed old backup: {removed}")
    except Exception as e:
        logger.error(f"Error managing config backups: {e}")

def read_config(config_path):
    """
    Reads and parses the Xray configuration file.
    """
    if not os.path.exists(config_path):
        return None
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error reading Xray configuration from {config_path}: {e}")
        return None

def write_config(config_path, config_data):
    """
    Backs up the configuration and writes the new JSON structure.
    """
    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        backup_config(config_path)
        with open(config_path, "w") as f:
            json.dump(config_data, f, indent=2)
        logger.info(f"Xray configuration updated at {config_path}.")
        return True
    except Exception as e:
        logger.error(f"Error writing Xray configuration: {e}")
        return False

def restart_xray(service_name="xray"):
    """
    Restarts Xray service via systemctl.
    """
    try:
        subprocess.run(["systemctl", "restart", service_name], check=True, capture_output=True)
        logger.info(f"Service '{service_name}' restarted successfully.")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to restart service '{service_name}': {e.stderr.decode().strip()}")
        return False
    except Exception as e:
        logger.error(f"Error restarting service '{service_name}': {e}")
        return False

def find_vless_inbound(config_data):
    """
    Finds the VLESS inbound inside the config JSON structure.
    """
    if not config_data or "inbounds" not in config_data:
        return None
    for inbound in config_data["inbounds"]:
        if inbound.get("protocol") == "vless":
            return inbound
    return None

def get_default_config_template():
    """
    Generates a default Xray configuration structure with API and VLESS inbounds enabled.
    """
    # Import values dynamically to avoid circular import issues
    from config import DOMAIN, PORT, TLS_CERT_PATH, TLS_KEY_PATH
    return {
        "log": {
            "access": "/var/log/xray/access.log",
            "error": "/var/log/xray/error.log",
            "loglevel": "warning"
        },
        "api": {
            "services": [
                "HandlerService",
                "StatsService"
            ],
            "tag": "api"
        },
        "stats": {},
        "policy": {
            "levels": {
                "0": {
                    "statsUserUplink": True,
                    "statsUserDownlink": True
                }
            },
            "system": {
                "statsInboundUplink": True,
                "statsInboundDownlink": True
            }
        },
        "inbounds": [
            {
                "listen": "127.0.0.1",
                "port": 10085,
                "protocol": "dokodemo-door",
                "settings": {
                    "address": "127.0.0.1"
                },
                "tag": "api"
            },
            {
                "port": PORT,
                "protocol": "vless",
                "settings": {
                    "clients": [],
                    "decryption": "none"
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "tls",
                    "tlsSettings": {
                        "certificates": [
                            {
                                "certificateFile": TLS_CERT_PATH,
                                "keyFile": TLS_KEY_PATH
                            }
                        ]
                    }
                },
                "tag": "vless-inbound"
            }
        ],
        "outbounds": [
            {
                "protocol": "freedom",
                "settings": {},
                "tag": "direct"
            },
            {
                "protocol": "blackhole",
                "settings": {},
                "tag": "blocked"
            }
        ],
        "routing": {
            "rules": [
                {
                    "type": "field",
                    "inboundTag": [
                        "api"
                    ],
                    "outboundTag": "api"
                }
            ]
        }
    }

def sync_xray_config(config_path, active_vless_users, service_name="xray"):
    """
    Synchronizes the local Xray config clients list with active DB VLESS users.
    Only writes the file and restarts the service if differences are detected.
    """
    config_data = read_config(config_path)
    if config_data is None:
        logger.info("Xray config not found or invalid. Initializing with default template...")
        config_data = get_default_config_template()
        
    vless_inbound = find_vless_inbound(config_data)
    if not vless_inbound:
        logger.warning("VLESS inbound not found in configuration. Re-initializing config file.")
        config_data = get_default_config_template()
        vless_inbound = find_vless_inbound(config_data)
        if not vless_inbound:
            logger.error("Failed to construct VLESS inbound structure.")
            return False

    # Structure clients list based on database users
    new_clients = []
    for user in active_vless_users:
        new_clients.append({
            "id": user["uuid"],
            "email": user["uuid"], # email is used as target in stats queries
            "level": 0
        })

    current_clients = vless_inbound.setdefault("settings", {}).setdefault("clients", [])
    
    # Sort and check for differences to avoid redundant restarts
    current_ids = sorted([c.get("id") for c in current_clients if "id" in c])
    new_ids = sorted([c["id"] for c in new_clients])

    if current_ids == new_ids:
        logger.debug("No updates needed. VLESS clients match current database state.")
        return True

    # Update structure and restart xray
    vless_inbound["settings"]["clients"] = new_clients
    if write_config(config_path, config_data):
        return restart_xray(service_name)
    return False

def query_xray_traffic():
    """
    Executes the Xray api statsquery command to retrieve current data metrics.
    Returns stats dict: { uuid: { "uplink": bytes, "downlink": bytes } }
    """
    try:
        # Run command via subprocess using default system path or specified environment binaries
        result = subprocess.run(
            ['xray', 'api', 'statsquery', '--server=127.0.0.1:10085'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        
        data = json.loads(result.stdout)
        stats = {}
        for item in data.get("stat", []):
            name = item.get("name", "")
            value = item.get("value", 0)
            
            # Format: user>>>email_or_uuid>>>traffic>>>uplink or downlink
            parts = name.split(">>>")
            if len(parts) == 4 and parts[0] == "user" and parts[2] == "traffic":
                uuid = parts[1]
                direction = parts[3] # "uplink" or "downlink"
                
                if uuid not in stats:
                    stats[uuid] = {"uplink": 0, "downlink": 0}
                stats[uuid][direction] = value
                
        return stats
    except FileNotFoundError:
        logger.error("Xray binary command line tool not found in path.")
        return {}
    except subprocess.CalledProcessError as e:
        logger.error(f"Xray stats API query failed (check if service is running and API is active): {e.stderr.strip()}")
        return {}
    except Exception as e:
        logger.error(f"Unexpected error querying Xray traffic: {e}")
        return {}
