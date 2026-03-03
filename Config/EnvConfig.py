"""
环境配置加载类
"""

import os
import yaml
from typing import Any, Dict


class EnvConfig:
    """
    环境配置加载类
    """
    
    def __init__(self, config_path: str = "Config/config.yaml"):
        """
        初始化配置加载器
        
        Args:
            config_path (str): 配置文件路径
        """
        self.config = self.load_config(config_path)
    
    def load_config(self, config_path: str) -> Dict[str, Any]:
        """
        加载YAML配置文件
        
        Args:
            config_path (str): 配置文件路径
            
        Returns:
            Dict[str, Any]: 配置字典
        """
        if not os.path.exists(config_path):
            # 返回默认配置
            return {
                'database': {
                    'path': 'chan_trading.db'
                },
                'email': {
                    'smtp_server': 'smtp.gmail.com',
                    'smtp_port': 587,
                    'sender_email': '',
                    'sender_password': '',
                    'recipient_email': ''
                }
            }
        
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值
        
        Args:
            key (str): 配置键，支持点分隔符（如 'database.path'）
            default (Any): 默认值
            
        Returns:
            Any: 配置值或默认值
        """
        keys = key.split('.')
        value = self.config
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default


# 创建全局配置实例
config = EnvConfig()