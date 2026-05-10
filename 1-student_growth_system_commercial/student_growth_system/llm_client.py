from __future__ import annotations
import json
import requests
from typing import Any
from .config import SILICONFLOW_API_KEY, SF_MODEL_NAME, SF_BASE_URL


class SiliconFlowClient:
    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None, timeout: int = 90):
        self.api_key = api_key if api_key is not None else SILICONFLOW_API_KEY
        self.model = model or SF_MODEL_NAME
        self.base_url = base_url or SF_BASE_URL
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(self.api_key and self.api_key != "xxxxx")

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.2, max_tokens: int = 2048) -> str:
        if not self.available:
            raise RuntimeError("未配置 SILICONFLOW_API_KEY，无法调用大模型。")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "enable_thinking": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        r = requests.post(self.base_url, headers=headers, json=payload, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"]

    def extract_json(self, system_prompt: str, user_prompt: str, temperature: float = 0.1, max_tokens: int = 3000) -> dict[str, Any]:
        content = self.chat(
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            start, end = content.find("{"), content.rfind("}")
            if start >= 0 and end > start:
                return json.loads(content[start:end + 1])
            raise ValueError(f"模型没有返回合法JSON：{content[:500]}")
