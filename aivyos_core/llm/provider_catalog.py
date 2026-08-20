"""模型提供商目录 — 管理 11+ 主流 LLM 提供商的元数据。

功能：
    - 提供商信息：名称、描述、API 端点、认证方式
    - 模型列表：每个提供商支持的主要模型
    - 能力标签：上下文长度、是否支持视觉/工具调用/思考链
    - 成本估算：输入/输出 Token 单价
    - 分类：本地部署 / 云端兼容 / 云端原生

对应需求：模型管理系统增强 — 11 提供商模型集成。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ProviderModel:
    """单个模型信息。"""
    name: str                  # 模型标识，如 "deepseek-chat"
    display_name: str = ""     # 显示名称
    context_window: int = 32768
    supports_vision: bool = False
    supports_tool_use: bool = True
    supports_thinking: bool = False
    supports_streaming: bool = True
    input_price_per_1m: float = 0.0   # 每百万输入 Token 美元
    output_price_per_1m: float = 0.0  # 每百万输出 Token 美元
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name or self.name,
            "context_window": self.context_window,
            "supports_vision": self.supports_vision,
            "supports_tool_use": self.supports_tool_use,
            "supports_thinking": self.supports_thinking,
            "supports_streaming": self.supports_streaming,
            "input_price_per_1m": self.input_price_per_1m,
            "output_price_per_1m": self.output_price_per_1m,
            "description": self.description,
        }


@dataclass
class ProviderInfo:
    """提供商信息。"""
    id: str                    # 唯一标识，如 "deepseek"
    name: str                  # 显示名称
    category: str              # local / cloud-compat / cloud-native
    description: str = ""
    base_url: str = ""
    api_key_env: str = ""
    auth_type: str = "api_key"  # api_key / oauth / sigv4 / none
    models: List[ProviderModel] = field(default_factory=list)
    website: str = ""
    default_model: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "auth_type": self.auth_type,
            "website": self.website,
            "default_model": self.default_model,
            "models": [m.to_dict() for m in self.models],
        }


# ============================================================================
# 11+ 主流提供商目录
# ============================================================================

PROVIDER_CATALOG: List[ProviderInfo] = [
    # 1. Ollama — 本地部署
    ProviderInfo(
        id="ollama",
        name="Ollama",
        category="local",
        description="本地大模型部署框架，支持 Llama、Mistral、Qwen 等开源模型",
        base_url="http://127.0.0.1:11434/v1",
        auth_type="none",
        website="https://ollama.com",
        default_model="qwen2.5:3b",
        models=[
            ProviderModel("qwen2.5:3b", "Qwen 2.5 (3B)", 32768, False, True, False, True, 0, 0, "阿里云通义开源模型，3B 轻量版"),
            ProviderModel("qwen2.5:7b", "Qwen 2.5 (7B)", 32768, False, True, False, True, 0, 0, "阿里云通义开源模型，7B 标准版"),
            ProviderModel("qwen2.5:14b", "Qwen 2.5 (14B)", 32768, False, True, True, True, 0, 0, "阿里云通义开源模型，14B 增强版"),
            ProviderModel("llama3.1:8b", "Llama 3.1 (8B)", 128000, False, True, False, True, 0, 0, "Meta 开源模型，8B 指令版"),
            ProviderModel("mistral:7b", "Mistral (7B)", 32768, False, True, False, True, 0, 0, "Mistral AI 开源模型"),
        ],
    ),

    # 2. vLLM — 本地部署
    ProviderInfo(
        id="vllm",
        name="vLLM",
        category="local",
        description="高性能推理引擎，支持动态批处理、PagedAttention",
        base_url="http://127.0.0.1:8000/v1",
        auth_type="none",
        website="https://docs.vllm.ai",
        default_model="qwen2.5:3b",
        models=[
            ProviderModel("qwen2.5:3b", "Qwen 2.5 (3B)", 32768, False, True, False, True, 0, 0),
            ProviderModel("qwen2.5:7b", "Qwen 2.5 (7B)", 32768, False, True, False, True, 0, 0),
            ProviderModel("llama3.1:8b", "Llama 3.1 (8B)", 128000, False, True, False, True, 0, 0),
        ],
    ),

    # 3. DeepSeek — 云端兼容
    ProviderInfo(
        id="deepseek",
        name="DeepSeek",
        category="cloud-compat",
        description="国内云端 AI 服务商，免费额度，代码能力强",
        base_url="https://api.deepseek.com/v1",
        api_key_env="DEEPSEEK_API_KEY",
        website="https://www.deepseek.com",
        default_model="deepseek-v4-flash",
        models=[
            ProviderModel("deepseek-v4-flash", "DeepSeek V4 Flash", 1000000, False, True, True, True, 0.00014, 0.00028, "通用主力，性价比首选，支持1M上下文"),
            ProviderModel("deepseek-v4-pro", "DeepSeek V4 Pro", 1000000, False, True, True, True, 0.00174, 0.00348, "旗舰推理，高难度工程任务"),
            ProviderModel("deepseek-v3", "DeepSeek V3", 128000, False, True, False, True, 0.0005, 0.002, "低成本版本"),
        ],
    ),

    # 4. OpenAI — 云端原生
    ProviderInfo(
        id="openai",
        name="OpenAI",
        category="cloud-native",
        description="全球领先的 AI 研究公司，GPT 系列模型",
        base_url="https://api.openai.com/v1",
        api_key_env="OPENAI_API_KEY",
        website="https://openai.com",
        default_model="gpt-4o",
        models=[
            ProviderModel("gpt-4o", "GPT-4o", 128000, True, True, True, True, 0.015, 0.060, "旗舰多模态模型"),
            ProviderModel("gpt-4o-mini", "GPT-4o Mini", 128000, True, True, False, True, 0.00015, 0.0006, "轻量版，低成本高性能"),
            ProviderModel("gpt-4.1", "GPT-4.1", 128000, True, True, True, True, 0.015, 0.060, "GPT-4 增强版"),
            ProviderModel("gpt-3.5-turbo", "GPT-3.5 Turbo", 16384, False, True, False, True, 0.0005, 0.0015, "经典对话模型"),
            ProviderModel("o3-mini", "o3 Mini", 200000, False, True, True, True, 0.0011, 0.0044, "推理优化模型"),
        ],
    ),

    # 5. Anthropic — 云端原生
    ProviderInfo(
        id="anthropic",
        name="Anthropic",
        category="cloud-native",
        description="安全优先的 AI 公司，Claude 系列模型",
        base_url="https://api.anthropic.com/v1",
        api_key_env="ANTHROPIC_API_KEY",
        website="https://anthropic.com",
        default_model="claude-3-5-sonnet-latest",
        models=[
            ProviderModel("claude-3-5-sonnet-latest", "Claude 3.5 Sonnet", 200000, True, True, True, True, 0.003, 0.015, "最新 Sonnet 模型"),
            ProviderModel("claude-3-opus-latest", "Claude 3 Opus", 200000, True, True, True, True, 0.015, 0.075, "旗舰模型，最高智能水平"),
            ProviderModel("claude-3-haiku-latest", "Claude 3 Haiku", 200000, True, True, False, True, 0.00025, 0.00125, "快速响应模型"),
        ],
    ),

    # 6. Google — 云端原生
    ProviderInfo(
        id="google",
        name="Google",
        category="cloud-native",
        description="Google DeepMind 推出的 Gemini 系列模型",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key_env="GOOGLE_API_KEY",
        website="https://deep.google",
        default_model="gemini-2.0-flash-exp",
        models=[
            ProviderModel("gemini-2.0-flash-exp", "Gemini 2.0 Flash", 1048576, True, True, False, True, 0.00035, 0.00105, "快速响应，百万 Token 上下文"),
            ProviderModel("gemini-1.5-pro", "Gemini 1.5 Pro", 1048576, True, True, True, True, 0.0005, 0.0015, "旗舰 Pro 模型"),
            ProviderModel("gemini-1.5-flash", "Gemini 1.5 Flash", 1048576, True, True, False, True, 0.000075, 0.0003, "低成本 Flash 模型"),
        ],
    ),

    # 7. Qwen / DashScope — 云端兼容
    ProviderInfo(
        id="qwen",
        name="阿里云 DashScope",
        category="cloud-compat",
        description="阿里云通义系列模型，中文优化，国内网络低延迟",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key_env="DASHSCOPE_API_KEY",
        website="https://dashscope.aliyun.com",
        default_model="qwen-plus",
        models=[
            ProviderModel("qwen-plus", "通义 Plus", 128000, True, True, True, True, 0.004, 0.012, "增强版，支持多模态和思考链"),
            ProviderModel("qwen-turbo", "通义 Turbo", 128000, False, True, False, True, 0.0008, 0.002, "快速低成本版本"),
            ProviderModel("qwen-max", "通义 Max", 128000, True, True, True, True, 0.008, 0.024, "旗舰模型，最高智能水平"),
            ProviderModel("qwen-long", "通义 Long", 1000000, True, True, False, True, 0.002, 0.006, "超长上下文模型"),
        ],
    ),

    # 8. SiliconFlow — 云端兼容
    ProviderInfo(
        id="siliconflow",
        name="硅基流动 SiliconFlow",
        category="cloud-compat",
        description="聚合多家开源模型的低成本平台",
        base_url="https://api.siliconflow.cn/v1",
        api_key_env="SILICONFLOW_API_KEY",
        website="https://siliconflow.cn",
        default_model="deepseek-v4-flash",
        models=[
            ProviderModel("deepseek-v4-flash", "DeepSeek V4 Flash", 1000000, False, True, True, True, 0.002, 0.004),
            ProviderModel("qwen2.5-7b", "Qwen 2.5 (7B)", 32768, False, True, False, True, 0.0003, 0.0006),
            ProviderModel("glm-4", "GLM-4", 128000, True, True, False, True, 0.001, 0.003),
        ],
    ),

    # 9. Azure OpenAI — 云端兼容
    ProviderInfo(
        id="azure-openai",
        name="Azure OpenAI",
        category="cloud-compat",
        description="微软 Azure 托管的 OpenAI 服务",
        base_url="https://{resource}.openai.azure.com/openai/deployments/{deployment}",
        api_key_env="AZURE_OPENAI_API_KEY",
        website="https://azure.microsoft.com/products/ai-services/openai-service",
        default_model="gpt-4o",
        models=[
            ProviderModel("gpt-4o", "GPT-4o", 128000, True, True, True, True, 0.015, 0.060),
            ProviderModel("gpt-4o-mini", "GPT-4o Mini", 128000, True, True, False, True, 0.00015, 0.0006),
            ProviderModel("gpt-35-turbo", "GPT-3.5 Turbo", 16384, False, True, False, True, 0.0005, 0.0015),
        ],
    ),

    # 10. Mistral AI — 云端兼容
    ProviderInfo(
        id="mistral",
        name="Mistral AI",
        category="cloud-compat",
        description="欧洲开源 AI 公司，Mixtral 稀疏专家模型",
        base_url="https://api.mistral.ai/v1",
        api_key_env="MISTRAL_API_KEY",
        website="https://mistral.ai",
        default_model="mistral-small-latest",
        models=[
            ProviderModel("mistral-large-latest", "Mistral Large", 128000, True, True, True, True, 0.003, 0.009, "旗舰模型"),
            ProviderModel("mistral-medium-latest", "Mistral Medium", 128000, True, True, True, True, 0.002, 0.006, "中等规模"),
            ProviderModel("mistral-small-latest", "Mistral Small", 32768, False, True, False, True, 0.001, 0.003, "轻量快速"),
            ProviderModel("open-mixtral-8x7b", "Mixtral 8x7B", 32768, False, True, False, True, 0.001, 0.003),
        ],
    ),

    # 11. AWS Bedrock — 云端原生
    ProviderInfo(
        id="bedrock",
        name="AWS Bedrock",
        category="cloud-native",
        description="亚马逊云 AI 服务，集成多家模型提供商",
        base_url="https://bedrock-runtime.{region}.amazonaws.com",
        api_key_env="AWS_ACCESS_KEY_ID",
        auth_type="sigv4",
        website="https://aws.amazon.com/bedrock",
        default_model="anthropic.claude-3-5-sonnet-20241022-v2:0",
        models=[
            ProviderModel("anthropic.claude-3-5-sonnet-20241022-v2:0", "Claude 3.5 Sonnet", 200000, True, True, True, True, 0.003, 0.015),
            ProviderModel("meta.llama3-8b-instruct-v1:0", "Llama 3 8B", 32768, False, True, False, True, 0.00025, 0.00075),
            ProviderModel("mistral.mixtral-8x7b-instruct-v0:1", "Mixtral 8x7B", 32768, False, True, False, True, 0.0007, 0.0021),
        ],
    ),

    # 12. 豆包 / 火山引擎 — 云端兼容
    ProviderInfo(
        id="doubao",
        name="豆包（火山引擎）",
        category="cloud-compat",
        description="字节跳动推出的大模型，支持文本/视觉/语音",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key_env="VOLCENGINE_API_KEY",
        website="https://www.volcengine.com/product/doubao",
        default_model="doubao-pro-32k",
        models=[
            ProviderModel("doubao-pro-32k", "豆包 Pro (32K)", 32768, False, True, False, True, 0.0008, 0.002, "基础 Pro 版本"),
            ProviderModel("doubao-pro-256k", "豆包 Pro (256K)", 262144, True, True, False, True, 0.001, 0.003, "长上下文 Pro 版本"),
            ProviderModel("doubao-lite-32k", "豆包 Lite (32K)", 32768, False, True, False, True, 0.0003, 0.0005, "轻量低成本版本"),
            ProviderModel("doubao-pro-32k", "豆包 Pro 视觉版", 32768, True, True, False, True, 0.0015, 0.004, "支持多模态输入"),
        ],
    ),
]

# 快速查找索引
_PROVIDER_MAP: Dict[str, ProviderInfo] = {p.id: p for p in PROVIDER_CATALOG}


def get_provider_catalog() -> List[Dict[str, Any]]:
    """获取完整提供商目录。

    Returns:
        提供商列表（序列化后的字典列表）。
    """
    return [p.to_dict() for p in PROVIDER_CATALOG]


def get_provider_info(provider_id: str) -> Optional[ProviderInfo]:
    """获取指定提供商信息。

    Args:
        provider_id: 提供商 ID。

    Returns:
        ProviderInfo 或 None。
    """
    return _PROVIDER_MAP.get(provider_id)


def get_provider_models(provider_id: str) -> List[Dict[str, Any]]:
    """获取指定提供商的模型列表。

    Args:
        provider_id: 提供商 ID。

    Returns:
        模型列表。
    """
    info = _PROVIDER_MAP.get(provider_id)
    if not info:
        return []
    return [m.to_dict() for m in info.models]


def search_models(keyword: str) -> List[Dict[str, Any]]:
    """按关键字搜索模型（跨提供商）。

    Args:
        keyword: 搜索关键字（匹配模型名或描述）。

    Returns:
        匹配的模型列表，包含提供商信息。
    """
    keyword_lower = keyword.lower()
    results = []
    for provider in PROVIDER_CATALOG:
        for model in provider.models:
            if (keyword_lower in model.name.lower()
                    or keyword_lower in model.display_name.lower()
                    or keyword_lower in provider.name.lower()):
                entry = model.to_dict()
                entry["provider_id"] = provider.id
                entry["provider_name"] = provider.name
                results.append(entry)
    return results


def get_categories() -> Dict[str, List[ProviderInfo]]:
    """按分类获取提供商。

    Returns:
        分类 → 提供商列表映射。
    """
    categories: Dict[str, List[ProviderInfo]] = {}
    for p in PROVIDER_CATALOG:
        categories.setdefault(p.category, []).append(p)
    return categories


def get_all_provider_ids() -> List[str]:
    """获取所有提供商 ID 列表。"""
    return list(_PROVIDER_MAP.keys())