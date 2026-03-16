#!/usr/bin/env python3
import os
import sys
import time
import subprocess
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('pipeline_post_sync.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("PostSyncPipeline")

SYNC_LOG = "sync_completion.log"
SYNC_SCRIPT = "complete_sync.py"

def is_sync_running():
    try:
        output = subprocess.check_output(["pgrep", "-f", SYNC_SCRIPT])
        return len(output) > 0
    except subprocess.CalledProcessError:
        return False

def wait_for_sync():
    logger.info("⏳ Waiting for complete_sync.py to finish...")
    while is_sync_running():
        time.sleep(60)
    
    # Check if it finished successfully in log
    if os.path.exists(SYNC_LOG):
        with open(SYNC_LOG, 'r') as f:
            content = f.read()
            if "All completion tasks finished" in content:
                logger.info("✅ Sync completed successfully.")
                return True
    
    logger.warning("⚠️ Sync process ended, but status unknown or log incomplete.")
    return True

def run_step(name, command):
    logger.info(f"🚀 Starting step: {name}")
    start_time = time.time()
    try:
        process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        # Stream output to log
        for line in process.stdout:
            logger.info(f"[{name}] {line.strip()}")
        
        process.wait()
        duration = time.time() - start_time
        if process.returncode == 0:
            logger.info(f"✅ Step {name} finished successfully in {duration:.1f}s")
            return True
        else:
            logger.error(f"❌ Step {name} failed with return code {process.returncode}")
            return False
    except Exception as e:
        logger.error(f"❌ Error running {name}: {e}")
        return False

def main():
    # 1. Wait for data sync
    wait_for_sync()
    
    # 2. ML Optimization (Training) - HK
    run_step("ML-Train-HK", "python3 scripts/train_ml_model.py --market HK --limit 50")
    
    # 3. ML Optimization (Training) - US
    run_step("ML-Train-US", "python3 scripts/train_ml_model.py --market US --limit 50")
    
    # 4. ML Optimization (Training) - A-Share (CN)
    run_step("ML-Train-CN", "python3 scripts/train_ml_model.py --market A --limit 50")
    
    # 5. Comparative Backtest across HK, US, and CN
    # This will generate the detailed per-stock report
    run_step("Backtest-Comparative", "python3 backtesting/ComparativeBacktester.py --markets HK US CN --limit 20 --workers 4")
    
    logger.info("🎉 All post-sync tasks completed!")
    
    # Analysis & Market Comparison
    logger.info("📊 Generating Market Comparison Summary...")
    try:
        reports_dir = "backtest_reports/comparative"
        reports = [os.path.join(reports_dir, f) for f in os.listdir(reports_dir) if f.startswith("comparison_report")]
        if reports:
            latest_report = max(reports, key=os.path.getctime)
            
            # Simple logic to extract market-level stats from the report or logs
            # For now, we point the user to the report which contains detailed codes
            logger.info(f"📄 Full comparison report: {latest_report}")
            
            print(f"\n✅ 流水线任务完成！已涵盖 A股/港股/美股 全市场。")
            print(f"📊 市场差异对比及报告路径: {latest_report}")
    except Exception as e:
        logger.error(f"Error finding latest report: {e}")

if __name__ == "__main__":
    main()
