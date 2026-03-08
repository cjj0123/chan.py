with open('visual_judge.py', 'r', encoding='utf-8') as f:
    code = f.read()

padding = "\n" + "-"*80 + "\n" + """# 补充规则与容错说明 (Padding tokens to satisfy Gemini caching minimums)
# 1. 如果K线图数据时间不足或因网络导致断线，请尽量在现有图表中提取有效笔和线段。
# 2. 如果MACD面积肉眼无法直接看出背驰，重点看当前柱子是否缩短/黄白线是否钝化。
# 3. 区间套必须看到内部结构的背驰才算买点/卖点。
# 4. 所有分析最终必须统一输出合法的 JSON，任何多余的开头结尾描述一概忽略。
# 5. 对于不同宽度的显示设备，忽略分辨率问题，只认图表内部的相对几何结构。
""" + "-"*80 + "\n"

code = code.replace('  "score": 85\n}\n"""\n', '  "score": 85\n}\n"""' + padding)

with open('visual_judge.py', 'w', encoding='utf-8') as f:
    f.write(code)
