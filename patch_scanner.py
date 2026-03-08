with open("App/ScannerThreads.py", "r") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "first_kl_type = chan.lv_list[0]" in line:
        # found it
        indent = line[:len(line) - len(line.lstrip())]
        lines[i+1] = f"{indent}first_kl_data = chan[first_kl_type]\n"
        lines[i+2] = f"{indent}if hasattr(first_kl_data, 'bi_list'): _ = list(first_kl_data.bi_list)\n"
        lines[i+3] = f"{indent}if hasattr(first_kl_data, 'seg_list'): _ = list(first_kl_data.seg_list)\n"
        lines[i+4] = f"{indent}if hasattr(first_kl_data, 'zs_list'): _ = list(first_kl_data.zs_list)\n"
        break

with open("App/ScannerThreads.py", "w") as f:
    f.writelines(lines)
