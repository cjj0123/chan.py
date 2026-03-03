"""
配置加载类，用于从 YAML 配置文件中加载和管理配置。
"""

import os
import yaml
from typing import Any, Dict


class EnvConfig:
    """
    环境配置加载器。
    负责从 config.yaml 文件中加载配置，并提供便捷的访问方法。
    """

    def __init__(self, config_path: str = "Config/config.yaml"):
        """
        初始化配置加载器。

        Args:
            config_path: 配置文件的路径。
        """
        self.config_path = config_path
        self._config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """从 YAML 文件加载配置。"""
        if not os.path.exists(self.config_path):
            # 如果配置文件不存在，返回一个空的默认配置
            return {}
        
        with open(self.config_path, 'r', encoding='utf-8') as file:
            return yaml.safe_load(file) or {}

    def get(self, key: str, default: Any = None) -> Any:
        """
        使用点分隔符获取配置值。

        例如: config.get("database.path", "default.db")

        Args:
            key: 点分隔的键路径，如 "database.path"。
            default: 如果键不存在时的默认值。

        Returns:
            配置值或默认值。
        """
        keys = key.split('.')
        value = self._config

        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default

    def __getattr__(self, name: str) -> Any:
        """
        允许通过属性访问顶级配置项。
        例如: config.database
        """
        if name in self._config:
            return self._config[name]
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")


# 创建全局配置实例
env_config = EnvConfig()