import os

print("=== 当前工作目录 ===")
cwd = os.getcwd()
print(cwd)

print("\n=== 当前目录下的文件/文件夹 ===")
files = os.listdir(cwd)
print(files)

# 检查是否有 Data 或 data 文件夹
data_dir = None
if "Data" in files: data_dir = "Data"
elif "data" in files: data_dir = "data"

if data_dir:
    print(f"\n=== 发现 '{data_dir}' 文件夹，里面的内容 ===")
    print(os.listdir(os.path.join(cwd, data_dir)))
else:
    print("\n❌ 严重错误：当前目录下没有发现 'Data' 或 'data' 文件夹！")
    print("请确保 web_app.py 放在 Chan.py 所在的同一个文件夹里。")