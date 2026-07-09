import os
import time
import asyncio
from typing import Any, Dict, Generator, List, Optional, Tuple
from config import get_provider_config, load_providers

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── openai 为可选依赖 ──
try:
    from openai import OpenAI, AsyncOpenAI, APIError, APIConnectionError, RateLimitError
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False
    OpenAI = None  # type: ignore
    AsyncOpenAI = None  # type: ignore
    APIError = Exception  # type: ignore
    APIConnectionError = Exception  # type: ignore
    RateLimitError = Exception  # type: ignore


class AIChat:
    def __init__(self, provider_name: Optional[str] = None, temperature: Optional[float] = None,
                 max_tokens: Optional[int] = None):
        self.providers = load_providers()
        self.provider_name: Optional[str] = None
        self.api_key: Optional[str] = None
        self.base_url: Optional[str] = None
        self.temperature = temperature or float(os.getenv("TEMPERATURE", "0.7"))
        self.max_tokens = max_tokens or int(os.getenv("MAX_TOKENS", "2048"))
        self.max_history = int(os.getenv("MAX_HISTORY", "100"))
        self.system_prompt = os.getenv("SYSTEM_PROMPT", "你是一个智能助手，请用中文回答用户的问题。")
        self.default_system_prompt = self.system_prompt
        self.model: Optional[str] = None
        self.client: Optional[OpenAI] = None
        self.async_client: Optional[AsyncOpenAI] = None
        self.history: List[Dict[str, str]] = []
        self._client_cache: Dict[str, OpenAI] = {}
        self._async_client_cache: Dict[str, AsyncOpenAI] = {}
        self.set_provider(provider_name or os.getenv("PROVIDER", "OpenAI"))
        self._init_history()

    _API_KEY_MAP = {
        "OpenAI": "OPENAI_API_KEY",
        "DeepSeek": "DEEPSEEK_API_KEY",
        "通义千问": "DASHSCOPE_API_KEY",
        "Moonshot (Kimi)": "MOONSHOT_API_KEY",
        "智谱 GLM": "ZHIPUAI_API_KEY",
        "百度文心": "BAIDU_API_KEY",
        "零一万物": "LINGYIWANWU_API_KEY",
        "Groq": "GROQ_API_KEY",
        "Together AI": "TOGETHER_API_KEY",
        "硅基流动": "SILICONFLOW_API_KEY",
    }

    def _get_provider_api_key(self, name: str) -> str:
        env_key = self._API_KEY_MAP.get(name, "OPENAI_API_KEY")
        return os.getenv(env_key, os.getenv("OPENAI_API_KEY", "sk-placeholder"))

    def _init_history(self) -> None:
        self.history = [{"role": "system", "content": self.system_prompt}]

    def _trim_history(self) -> None:
        if len(self.history) > self.max_history:
            keep = len(self.history) - self.max_history + 1
            self.history = [self.history[0]] + self.history[keep:]

    def set_provider(self, name: str) -> None:
        config = get_provider_config(name)
        if config is None:
            raise ValueError(f"未找到服务商: {name}")
        self.provider_name = config["name"]
        self.api_key = self._get_provider_api_key(name)
        self.base_url = config.get("base_url") or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.model = config.get("default_model") or os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")

        if not _OPENAI_AVAILABLE:
            self.client = None
            self.async_client = None
            return

        cache_key = f"{self.base_url}:{self.api_key[:12]}"
        if cache_key in self._client_cache:
            self.client = self._client_cache[cache_key]
            self.async_client = self._async_client_cache.get(cache_key)
        else:
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url, max_retries=0)
            self._client_cache[cache_key] = self.client
            self.async_client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, max_retries=0)
            self._async_client_cache[cache_key] = self.async_client

    def set_model(self, model_name: str) -> None:
        self.model = model_name

    def set_temperature(self, value: float) -> None:
        self.temperature = float(value)

    def set_max_tokens(self, value: int) -> None:
        self.max_tokens = int(value)

    def set_max_history(self, value: int) -> None:
        self.max_history = int(value)

    def set_system_prompt(self, prompt: str) -> None:
        self.system_prompt = prompt
        self.history[0] = {"role": "system", "content": prompt}

    def reset_system_prompt(self) -> None:
        self.set_system_prompt(self.default_system_prompt)

    def list_providers(self) -> List[str]:
        return [p["name"] for p in self.providers]

    def get_models_for_provider(self, name: str) -> List[str]:
        config = get_provider_config(name)
        return config.get("models", []) if config else []

    def _retry_request(self, func, max_retries: int = 3) -> Tuple[Any, Optional[str]]:
        for attempt in range(max_retries):
            try:
                return func(), None
            except RateLimitError as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** (attempt + 1))
                    continue
                return None, f"[速率限制错误] {e}"
            except (APIConnectionError, APIError) as e:
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                return None, f"[API错误] {e}"
            except Exception as e:
                return None, f"[错误] {e}"

    async def _retry_request_async(self, func, max_retries: int = 3) -> Tuple[Any, Optional[str]]:
        for attempt in range(max_retries):
            try:
                return await func(), None
            except RateLimitError as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** (attempt + 1))
                    continue
                return None, f"[速率限制错误] {e}"
            except (APIConnectionError, APIError) as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                    continue
                return None, f"[API错误] {e}"
            except Exception as e:
                return None, f"[错误] {e}"

    def chat(self, user_message: str, max_retries: int = 3) -> str:
        self.history.append({"role": "user", "content": user_message})
        self._trim_history()

        if not _OPENAI_AVAILABLE or self.client is None:
            reply = "[错误] openai 库未安装，无法调用 API。请运行: pip install openai"
            self.history.append({"role": "assistant", "content": reply})
            return reply

        result, error = self._retry_request(
            lambda: self.client.chat.completions.create(
                model=self.model,
                messages=self.history,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            ), max_retries
        )

        reply = result.choices[0].message.content if result else error
        self.history.append({"role": "assistant", "content": reply})
        return reply

    def chat_stream(self, user_message: str, max_retries: int = 3) -> Generator[str, None, None]:
        self.history.append({"role": "user", "content": user_message})
        self._trim_history()

        if not _OPENAI_AVAILABLE or self.client is None:
            reply = "[错误] openai 库未安装，无法调用 API。请运行: pip install openai"
            self.history.append({"role": "assistant", "content": reply})
            yield reply
            return

        result, error = self._retry_request(
            lambda: self.client.chat.completions.create(
                model=self.model,
                messages=self.history,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=True,
            ), max_retries
        )

        if error:
            yield error
            self.history.append({"role": "assistant", "content": error})
            return

        full_reply = ""
        for chunk in result:
            if chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                full_reply += content
                yield content
        self.history.append({"role": "assistant", "content": full_reply})

    async def chat_async(self, user_message: str, max_retries: int = 3) -> str:
        self.history.append({"role": "user", "content": user_message})
        self._trim_history()

        if not _OPENAI_AVAILABLE or self.async_client is None:
            reply = "[错误] openai 库未安装，无法调用 API。请运行: pip install openai"
            self.history.append({"role": "assistant", "content": reply})
            return reply

        result, error = await self._retry_request_async(
            lambda: self.async_client.chat.completions.create(
                model=self.model,
                messages=self.history,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            ), max_retries
        )

        reply = result.choices[0].message.content if result else error
        self.history.append({"role": "assistant", "content": reply})
        return reply

    async def chat_stream_async(self, user_message: str, max_retries: int = 3):
        self.history.append({"role": "user", "content": user_message})
        self._trim_history()

        if not _OPENAI_AVAILABLE or self.async_client is None:
            reply = "[错误] openai 库未安装，无法调用 API。请运行: pip install openai"
            self.history.append({"role": "assistant", "content": reply})
            yield reply
            return

        result, error = await self._retry_request_async(
            lambda: self.async_client.chat.completions.create(
                model=self.model,
                messages=self.history,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=True,
            ), max_retries
        )

        if error:
            yield error
            self.history.append({"role": "assistant", "content": error})
            return

        full_reply = ""
        async for chunk in result:
            if chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                full_reply += content
                yield content
        self.history.append({"role": "assistant", "content": full_reply})

    def clear_history(self) -> None:
        self._init_history()

    def get_history(self) -> List[Dict[str, str]]:
        return self.history[1:]

    def export_history(self) -> str:
        lines = []
        for msg in self.history[1:]:
            role = "你" if msg["role"] == "user" else "AI"
            lines.append(f"{role}: {msg['content']}")
        return "\n\n".join(lines)

    def get_history_length(self) -> int:
        return len(self.history) - 1