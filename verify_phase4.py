
import os
import sys
import json
import logging
import pandas as pd
from unittest.mock import MagicMock

# 设置路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ML.SignalValidator import SignalValidator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_signal_validator():
    logger.info("🧪 Testing SignalValidator Phase 4 features...")
    
    # 1. 模拟数据
    validator = SignalValidator(policy="MAJORITY")
    
    # 模拟 Chan 和 Bsp
    mock_chan = MagicMock()
    mock_chan.code = "US.NVDA"
    
    mock_bsp = MagicMock()
    mock_bsp.is_buy = True
    mock_bsp.dt = "2026-03-11 21:00:00"
    
    # 模拟特征提取
    validator.extractor.extract_bsp_features = MagicMock(return_value={
        "feat1": 0.5,
        "feat2": 1.2
    })
    
    # 模拟模型预测
    # 我们需要模拟 _prepare_feature_row 否则会因为没有 real models 而失败
    validator._prepare_feature_row = MagicMock(return_value=[0.5, 1.2])
    
    # 模拟模型对象
    validator.models = {"XGB": MagicMock(), "LGB": MagicMock()}
    validator.is_loaded = True
    
    # 模拟预测结果
    # XGB predict 返回一个 list-like
    validator.models["XGB"].predict.return_value = [0.8]
    validator.models["LGB"].predict.return_value = [0.3]
    
    # 设置阈值
    validator.thresholds = {"XGB": 0.7, "LGB": 0.5}
    
    # 2. 测试 MAJORITY 策略 (XGB 0.8 >= 0.7 OK, LGB 0.3 < 0.5 FAIL) -> 1/2 pass -> ValidCount 1 -> is_valid true
    validator.policy = "MAJORITY"
    res = validator.validate_signal(mock_chan, mock_bsp)
    logger.info(f"Majority Result: {res['is_valid']} (Expected: True)")
    
    # 3. 测试 STRICT 策略
    validator.policy = "STRICT"
    res = validator.validate_signal(mock_chan, mock_bsp)
    logger.info(f"Strict Result: {res['is_valid']} (Expected: False)")
    
    # 4. 测试日志记录
    if os.path.exists(validator.online_log_path):
        df = pd.read_csv(validator.online_log_path)
        logger.info(f"✅ Online logs created with {len(df)} rows.")
        # print(df.head())
    else:
        logger.error("❌ Online logs NOT created!")

    # 5. 测试热加载 (模拟文件更新)
    validator._model_timestamps["XGB"] = 1000
    # 模拟文件存在但时间戳更大
    os.path.getmtime = MagicMock(return_value=2000)
    os.path.exists = MagicMock(return_value=True)
    validator._load_all_models = MagicMock()
    
    validator.check_and_reload()
    if validator._load_all_models.called:
        logger.info("✅ check_and_reload: Reload triggered as expected.")
    else:
        logger.error("❌ check_and_reload: Reload NOT triggered!")

if __name__ == "__main__":
    test_signal_validator()
