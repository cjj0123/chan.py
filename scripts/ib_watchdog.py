#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IB Gateway Watchdog - macOS Edition
Monitors IB Gateway port and application status.
"""

import os
import sys
import time
import socket
import subprocess
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('ib_watchdog.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("IBWatchdog")

IB_HOST = os.getenv("IB_HOST", "127.0.0.1")
IB_PORT = int(os.getenv("IB_PORT", "4002"))
IB_APP_NAME = "IB Gateway 10.44" 
IB_APP_PATH = "/Users/jijunchen/IBC/mac_gateway_start.sh"

def is_port_open(host, port):
    """Check if the IB Gateway port is listening."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(3)
        return s.connect_ex((host, port)) == 0

def is_app_running(app_name):
    """Check if the application is in the process list."""
    # With IBC, the process will be 'java' with 'IBC' in command line
    try:
        output = subprocess.check_output(["pgrep", "-f", "IBC.jar"])
        return len(output) > 0
    except subprocess.CalledProcessError:
        return False

def launch_ib_gateway():
    """Launch IB Gateway on macOS using IBC."""
    logger.info(f"🚀 Attempting to launch IB Gateway via IBC: {IB_APP_PATH}...")
    try:
        # Launch using the new IBC script
        subprocess.Popen([IB_APP_PATH], stdout=open('ibc_startup.log', 'a'), stderr=subprocess.STDOUT)
        logger.info("✅ IBC launch command sent in background.")
        # Give IBC more time to handle the login sequence
        time.sleep(60)
    except Exception as e:
        logger.error(f"❌ Failed to launch IBC: {e}")

def main_loop():
    logger.info(f"🕵️ Watchdog started for {IB_HOST}:{IB_PORT}")
    
    consecutive_failures = 0
    
    while True:
        port_ok = is_port_open(IB_HOST, IB_PORT)
        
        if port_ok:
            if consecutive_failures > 0:
                logger.info("✅ IB Gateway connection RE-ESTABLISHED.")
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            logger.warning(f"⚠️ IB Gateway port {IB_PORT} is CLOSED (Failure {consecutive_failures}/3)")
            
            if consecutive_failures >= 3:
                # Port is closed, check if app needs restart
                if not is_app_running(IB_APP_NAME):
                    logger.error(f"‼️ {IB_APP_NAME} is NOT running. Attempting restart...")
                    launch_ib_gateway()
                else:
                    logger.warning(f"🤔 {IB_APP_NAME} process exists but port is closed. It might be stuck at login or initializing.")
                
                # Reset failure count after attempting action to avoid spamming
                consecutive_failures = 0

        # Run every 30 seconds
        time.sleep(30)

if __name__ == "__main__":
    try:
        main_loop()
    except KeyboardInterrupt:
        logger.info("Watchdog stopped by user.")
