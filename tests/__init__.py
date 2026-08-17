"""AivyOS 单元测试（unittest，零第三方依赖）。"""

import os
import shutil
import unittest

# 测试统一使用工作区内的临时数据目录（沙箱只允许工作区写）
_WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TMP = os.path.join(_WS, ".aivyos_test")
shutil.rmtree(_TMP, ignore_errors=True)
os.makedirs(_TMP, exist_ok=True)
os.environ["AIVYOS_HOME"] = _TMP
os.environ.pop("AIVYOS_CLOUD_API_KEY", None)
os.environ.pop("AIVYOS_LLM_MODE", None)


def make_config(**overrides) -> dict:
    from aivyos_core.config import load_config

    cfg = load_config()
    cfg["home"] = os.path.join(_TMP, "data")
    cfg["llm"]["mode"] = "mock"  # 测试默认 mock，保证离线可跑
    if overrides:
        from aivyos_core.config import deep_merge

        cfg = deep_merge(cfg, overrides)
    return cfg


class AivyTestCase(unittest.TestCase):
    pass
