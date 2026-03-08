import os
import sys
import json
import threading
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from scripts.analyze_results import BacktestAnalyzer
except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)

def run_analysis_in_thread(results_file, output_dir):
    try:
        print(f"Starting analysis in thread: {threading.current_thread().name}")
        analyzer = BacktestAnalyzer(results_file)
        
        equity_path = os.path.join(output_dir, "test_equity.png")
        dist_path = os.path.join(output_dir, "test_dist.png")
        report_path = os.path.join(output_dir, "test_report.md")
        
        analyzer.plot_equity_curve(equity_path)
        analyzer.plot_trade_distribution(dist_path)
        analyzer.generate_analysis_report(report_path)
        
        print(f"Analysis completed successfully in thread.")
        return True
    except Exception as e:
        print(f"Error in background thread: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    # Find a recent results file
    report_dir = "backtest_reports"
    if not os.path.exists(report_dir):
        print(f"Directory {report_dir} not found.")
        return
        
    files = [f for f in os.listdir(report_dir) if f.startswith("results_") and f.endswith(".json")]
    if not files:
        print("No results files found.")
        return
        
    files.sort()
    latest_file = os.path.join(report_dir, files[-1])
    print(f"Using latest results file: {latest_file}")
    
    output_dir = "backtest_reports/test_verify"
    os.makedirs(output_dir, exist_ok=True)
    
    # Run in a background thread and wait
    thread = threading.Thread(target=run_analysis_in_thread, args=(latest_file, output_dir), name="BacktestVerifyThread")
    thread.start()
    thread.join()
    
    if os.path.exists(os.path.join(output_dir, "test_equity.png")):
        print("✅ Plotting verification PASSED (plots generated).")
    else:
        print("❌ Plotting verification FAILED (plots NOT generated).")

if __name__ == "__main__":
    main()
