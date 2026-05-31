import subprocess
import logging

logger = logging.getLogger("vps_manager")

# Graceful import check for pwd to allow cross-platform testing (Windows dev / Linux prod)
try:
    import pwd
except ImportError:
    pwd = None

def get_ssh_user_uid(username):
    """
    Looks up the system UID of the specified Linux user.
    """
    if pwd is not None:
        try:
            return pwd.getpwnam(username).pw_uid
        except KeyError:
            return None
    else:
        # Fallback for systems/environments without pwd module (e.g. testing)
        try:
            result = subprocess.run(
                ['id', '-u', username],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            if result.returncode == 0:
                return int(result.stdout.strip())
        except Exception:
            pass
        return None

def create_ssh_user(username, password):
    """
    Creates a system Linux user with a non-interactive shell.
    Registers an iptables tracking rule.
    """
    try:
        # Create user with nologin shell
        subprocess.run(
            ['useradd', '-m', '-s', '/usr/sbin/nologin', username],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Set password
        chpasswd_proc = subprocess.Popen(
            ['chpasswd'],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = chpasswd_proc.communicate(input=f"{username}:{password}\n")
        
        if chpasswd_proc.returncode != 0:
            logger.error(f"chpasswd failed for user {username}: {stderr.strip()}")
            # Cleanup user
            subprocess.run(['userdel', '-r', username], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return False

        # Add iptables rule for traffic tracking
        ensure_ssh_rule_exists(username)
        
        logger.info(f"Linux SSH user '{username}' created successfully.")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Command execution error during SSH user '{username}' creation: {e.stderr.decode().strip()}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during SSH user '{username}' creation: {e}")
        return False

def delete_ssh_user(username):
    """
    Deletes the system Linux user and deletes their iptables tracking rule.
    Immediately terminates all active sessions.
    """
    uid = get_ssh_user_uid(username)
    try:
        # Terminate current sessions immediately
        subprocess.run(['pkill', '-u', username], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Delete iptables rule if UID was found
        if uid is not None:
            subprocess.run(
                ['iptables', '-D', 'OUTPUT', '-m', 'owner', '--uid-owner', str(uid), '-j', 'ACCEPT'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
        # Delete the system user
        subprocess.run(
            ['userdel', '-r', username],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        logger.info(f"Linux SSH user '{username}' deleted successfully.")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Command execution error during SSH user '{username}' deletion: {e.stderr.decode().strip()}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during SSH user '{username}' deletion: {e}")
        return False

def suspend_ssh_user(username):
    """
    Suspends a Linux user by locking their password and killing active processes.
    """
    try:
        # Lock account password (prevents login)
        subprocess.run(['usermod', '-L', username], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # Terminate active SSH sessions immediately
        subprocess.run(['pkill', '-u', username], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logger.info(f"Linux SSH user '{username}' has been suspended.")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to suspend Linux user '{username}': {e.stderr.decode().strip()}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error suspending Linux user '{username}': {e}")
        return False

def unsuspend_ssh_user(username):
    """
    Unsuspends a Linux user by unlocking their password.
    """
    try:
        # Unlock account password
        subprocess.run(['usermod', '-U', username], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        logger.info(f"Linux SSH user '{username}' has been unsuspended.")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to unsuspend Linux user '{username}': {e.stderr.decode().strip()}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error unsuspending Linux user '{username}': {e}")
        return False

def get_ssh_traffic_bytes(username):
    """
    Queries iptables to read cumulative output bytes matched to the user's UID.
    """
    uid = get_ssh_user_uid(username)
    if uid is None:
        return 0
    try:
        result = subprocess.run(
            ['iptables', '-L', 'OUTPUT', '-v', '-n', '-x'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        
        # Parse output line by line
        # Target output line contains owner matching block: "owner UID match 1001"
        for line in result.stdout.splitlines():
            if f"owner UID match {uid}" in line or f"owner: {uid}" in line:
                parts = line.strip().split()
                if len(parts) >= 2:
                    try:
                        return int(parts[1]) # The second column is raw byte count
                    except ValueError:
                        continue
    except Exception as e:
        logger.error(f"Error querying iptables bytes count for user '{username}': {e}")
    return 0

def ensure_ssh_rule_exists(username):
    """
    Checks if the output owner matching rule exists. Adds it if not.
    """
    uid = get_ssh_user_uid(username)
    if uid is None:
        return False
    try:
        # Check rule existence
        res = subprocess.run(
            ['iptables', '-C', 'OUTPUT', '-m', 'owner', '--uid-owner', str(uid), '-j', 'ACCEPT'],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        if res.returncode == 0:
            return True # Rule exists
            
        # Add rule if it does not exist
        subprocess.run(
            ['iptables', '-I', 'OUTPUT', '1', '-m', 'owner', '--uid-owner', str(uid), '-j', 'ACCEPT'],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        logger.info(f"iptables tracking rule created for user '{username}' (UID: {uid}).")
        return True
    except Exception as e:
        logger.error(f"Failed to verify/append iptables tracking rule for user '{username}': {e}")
        return False
