import os
import time
from typing import Dict
from openai import OpenAI
from openai import APIError, APIConnectionError, RateLimitError
from config import get_provider_config, load_providers

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class AIChat:
    def __init__(self, provider_name=None, temperature=None, max_tokens=None):
        self.providers = load_providers()
        self.provider_name = None
        self.api_key = None
        self.base_url = None
        self.temperature = temperature or float(os.getenv("TEMPERATURE", "0.7"))
        self.max_tokens = max_tokens or int(os.getenv("MAX_TOKENS", "2048"))
        self.max_history = int(os.getenv("MAX_HISTORY", "100"))
        self.system_prompt = os.getenv(
            "SYSTEM_PROMPT", "你是一个智能助手，请用中文回答用户的问题。"
        )
        self.default_system_prompt = self.system_prompt
        self.model = None
        self.client = None
        self.history = []
        self._client_cache: Dict[str, OpenAI] = {}
        if provider_name:
            self.set_provider(provider_name)
        else:
            self.set_provider(os.getenv("PROVIDER", "OpenAI"))
        self._init_history()

    def _get_provider_api_key(self, name):
        key_map = {
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
        env_key = key_map.get(name, "OPENAI_API_KEY")
        return os.getenv(env_key, os.getenv("OPENAI_API_KEY", "sk-placeholder"))

    def _init_history(self):
        self.history = [{"role": "system", "content": self.system_prompt}]

    def _trim_history(self):
        if len(self.history) > self.max_history:
            keep_start = len(self.history) - self.max_history + 1
            self.history = [self.history[0]] + self.history[keep_start:]

    def set_provider(self, name):
        config = get_provider_config(name)
        if config is None:
            raise ValueError(f"未找到服务商: {name}")

        self.provider_name = config["name"]
        self.api_key = self._get_provider_api_key(name)
        self.base_url = config.get("base_url") or os.getenv(
            "OPENAI_BASE_URL", "https://api.openai.com/v1"
        )

        cache_key = f"{self.base_url}:{self.api_key[:12]}"
        if cache_key in self._client_cache:
            self.client = self._client_cache[cache_key]
        else:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                max_retries=0,
            )
            self._client_cache[cache_key] = self.client

        self.model = config.get("default_model") or os.getenv(
            "OPENAI_MODEL", "gpt-3.5-turbo"
        )

    def set_model(self, model_name):
        self.model = model_name

    def set_temperature(self, value):
        self.temperature = float(value)

    def set_max_tokens(self, value):
        self.max_tokens = int(value)

    def set_max_history(self, value):
        self.max_history = int(value)

    def set_system_prompt(self, prompt):
        self.system_prompt = prompt
        self.history[0] = {"role": "system", "content": prompt}

    def reset_system_prompt(self):
        self.system_prompt = self.default_system_prompt
        self.history[0] = {"role": "system", "content": self.default_system_prompt}

    def list_providers(self):
        return [p["name"] for p in self.providers]

    def get_models_for_provider(self, name):
        config = get_provider_config(name)
        if config:
            return config.get("models", [])
        return []

    def chat(self, user_message: str, max_retries: int = 3) -> str:
        self.history.append({"role": "user", "content": user_message})
        self._trim_history()

        for attempt in range(max_retries):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=self.history,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                reply = response.choices[0].message.content
                self.history.append({"role": "assistant", "content": reply})
                return reply
            except RateLimitError as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** (attempt + 1))
                    continue
                error_msg = f"[速率限制错误] {e}"
                self.history.append({"role": "assistant", "content": error_msg})
                return error_msg
            except (APIConnectionError, APIError) as e:
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                error_msg = f"[API错误] {e}"
                self.history.append({"role": "assistant", "content": error_msg})
                return error_msg
            except Exception as e:
                error_msg = f"[错误] {e}"
                self.history.append({"role": "assistant", "content": error_msg})
                return error_msg

    def chat_stream(self, user_message: str, max_retries: int = 3):
        self.history.append({"role": "user", "content": user_message})
        self._trim_history()

        for attempt in range(max_retries):
            try:
                stream = self.client.chat.completions.create(
                    model=self.model,
                    messages=self.history,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    stream=True,
                )
                full_reply = ""
                for chunk in stream:
                    if chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        full_reply += content
                        yield content
                self.history.append({"role": "assistant", "content": full_reply})
                return
            except RateLimitError as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** (attempt + 1))
                    continue
                error_msg = f"[速率限制错误] {e}"
                yield error_msg
                self.history.append({"role": "assistant", "content": error_msg})
                return
            except (APIConnectionError, APIError) as e:
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
                error_msg = f"[API错误] {e}"
                yield error_msg
                self.history.append({"role": "assistant", "content": error_msg})
                return
            except Exception as e:
                error_msg = f"[错误] {e}"
                yield error_msg
                self.history.append({"role": "assistant", "content": error_msg})
                return

    def clear_history(self):
        self._init_history()

    def get_history(self):
        return self.history[1:]

    def export_history(self):
        lines = []
        for msg in self.history[1:]:
            role = "你" if msg["role"] == "user" else "AI"
            lines.append(f"{role}: {msg['content']}")
        return "\n\n".join(lines)

    def get_history_length(self):
        return len(self.history) - 1