import re
from collections import defaultdict
from datetime import datetime

def count_requests():
    with open("quota_output.txt", "r") as f:
        content = f.read()
    
    # regex to find fit timestamps
    p = r"'request_time': '([^']+)'"
    matches = re.findall(p, content)
    
    print(f"Total history K-line requests in the logs: {len(matches)}")
    
    # Group by 30-second intervals or minute
    time_groups = defaultdict(int)
    for m in matches:
        dt = datetime.strptime(m, "%Y-%m-%d %H:%M:%S")
        is_first_half = dt.second < 30
        window = f"{dt.strftime('%Y-%m-%d %H:%M')}:{'00' if is_first_half else '30'}"
        time_groups[window] += 1
        
    print("\n=== Requests per 30-second window ===")
    for window, count in sorted(time_groups.items(), reverse=True)[:10]:
        print(f"[{window}] -> {count} requests")

if __name__ == "__main__":
    count_requests()
