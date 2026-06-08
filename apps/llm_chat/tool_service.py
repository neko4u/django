import json
import requests
from django.conf import settings
from typing import List
import requests.exceptions


def _get_tavily_config():
    with open(settings.CONFIG_FILE, 'r', encoding='utf-8') as f:
        full_config = json.load(f)
    return full_config.get('tavily', {})


def tavily_search(query: str, max_results: int = 5, **kwargs) -> dict:
    """
    调用 Tavily 搜索 API。
    参数由 LLM 决定，api_key 和 base_url 从配置文件中自动读取。
    """
    config = _get_tavily_config()
    api_key = config.get('api_key')
    base_url = config.get('base_url')
    if not api_key or not base_url:
        raise RuntimeError("Tavily 配置缺失")

    url = f"{base_url.rstrip('/')}/search"
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
    }
    payload.update(kwargs)
    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()
    except requests.exceptions.Timeout:
        raise RuntimeError("Tavily 搜索请求超时，当前网络无法访问外部搜索服务，请稍后重试或联系管理员。")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Tavily 搜索请求失败: {str(e)}")
    return response.json()
    response.raise_for_status()
    return response.json()


class ToolManager:
    # 工具注册表：名称 -> 定义 + 执行函数
    TOOLS_REGISTRY = {
        "tavily_search": {
            "definition": {
                "type": "function",
                "function": {
                    "name": "tavily_search",
                    "description": "使用 Tavily API 进行实时网络搜索，获取最新信息。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "搜索关键词"
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "返回结果数量，默认5",
                                "default": 5
                            }
                        },
                        "required": ["query"],
                        "additionalProperties": False
                    },
                    "strict": True
                }
            },
            "executor": tavily_search,
        }
    }

    @classmethod
    def get_tools_for_model(cls, model_name=None) -> List[dict]:
        """返回所有已注册的工具定义（未来可扩展按模型过滤）"""
        return [tool['definition'] for tool in cls.TOOLS_REGISTRY.values()]

    @classmethod
    def execute_tool(cls, function_name: str, arguments: dict) -> dict:
        """执行指定工具，arguments 由 LLM 传入"""
        tool = cls.TOOLS_REGISTRY.get(function_name)
        if not tool:
            raise ValueError(f"未注册的工具: {function_name}")
        return tool["executor"](**arguments)