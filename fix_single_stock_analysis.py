#!/usr/bin/env python3
"""
修复单股票扫描功能的脚本
- 自动处理不同格式的股票代码输入
- 提供更好的错误提示
"""

import re

def normalize_stock_code(code_input):
    """
    标准化股票代码输入
    
    支持的输入格式：
    - 完整格式: SH.600000, SZ.000001, HK.00700, US.AAPL
    - 纯数字: 600000, 000001, 00700
    - 带市场前缀的数字: 600000.SH, 000001.SZ
    
    Returns:
        str: 标准化后的股票代码 (SH.600000, SZ.000001, HK.00700, US.AAPL)
    """
    code = code_input.strip().upper()
    
    # 如果已经是完整格式，直接返回
    if re.match(r'^(SH|SZ|HK|US)\.\w+$', code):
        return code
    
    # 如果是带市场后缀的格式 (600000.SH)
    if re.match(r'^\d+\.(SH|SZ|HK|US)$', code):
        parts = code.split('.')
        return f"{parts[1]}.{parts[0]}"
    
    # 如果是纯数字，尝试推断市场
    if re.match(r'^\d+$', code):
        # 检查长度和前缀来推断市场
        if len(code) == 6:
            if code.startswith('6'):
                return f"SH.{code}"
            elif code.startswith('0') or code.startswith('3'):
                return f"SZ.{code}"
            else:
                # 可能是其他市场，先假设是SH
                return f"SH.{code}"
        elif len(code) == 5:
            # 港股通常是5位数字
            return f"HK.{code}"
        elif len(code) <= 4:
            # 美股通常是1-4个字母，但这里输入的是数字，可能是错误
            # 先假设是A股
            if code.startswith('6'):
                return f"SH.{code.zfill(6)}"
            else:
                return f"SZ.{code.zfill(6)}"
    
    # 如果无法识别，返回原输入（让后续处理报错）
    return code_input

def test_normalize():
    """测试标准化函数"""
    test_cases = [
        ("600000", "SH.600000"),
        ("000001", "SZ.000001"),
        ("00700", "HK.00700"),
        ("AAPL", "AAPL"),  # 这个会保持原样，因为不是数字
        ("SH.600000", "SH.600000"),
        ("600000.SH", "SH.600000"),
        ("000001.SZ", "SZ.000001"),
    ]
    
    for input_code, expected in test_cases:
        result = normalize_stock_code(input_code)
        print(f"输入: {input_code} -> 输出: {result} {'✅' if result == expected else '❌'}")

if __name__ == "__main__":
    test_normalize()