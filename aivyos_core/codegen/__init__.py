"""代码生成层（文档 §10.1 / T5.1）：后端抽象 + 生成服务。"""

from aivyos_core.codegen.base import CodeGenBackend, FilePlan
from aivyos_core.codegen.cline_adapter import ClineSDKBackend
from aivyos_core.codegen.local_backend import LocalCodeGen
from aivyos_core.codegen.preview import PreviewController
from aivyos_core.codegen.service import CodeGenService
from aivyos_core.codegen.templates import TEMPLATES, list_templates, scaffold

__all__ = [
    "CodeGenBackend", "FilePlan",
    "ClineSDKBackend", "LocalCodeGen",
    "CodeGenService", "PreviewController",
    "TEMPLATES", "list_templates", "scaffold",
]
