import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

LOG_DIR = Path(__file__).parent / "logs"
MAX_LOG_AGE_DAYS = 7
LOG_DIR.mkdir(parents=True, exist_ok=True)


class Hook:
    def __init__(self, name: str, hook_type: str, func: Callable[..., Any]) -> None:
        self.name = name
        self.hook_type = hook_type
        self.func = func


class HookSystem:
    HOOK_TYPES: List[str] = [
        "before_chat",
        "after_chat",
        "before_tool",
        "after_tool",
        "on_error",
        "on_session_start",
        "on_session_end",
    ]

    def __init__(self) -> None:
        self.hooks: Dict[str, List[Hook]] = {t: [] for t in self.HOOK_TYPES}
        self._lock = threading.Lock()

    def register(self, hook_type: str, name: str, func: Callable[..., Any]) -> Hook:
        if hook_type not in self.HOOK_TYPES:
            raise ValueError(f"未知钩子类型: {hook_type}，可选: {self.HOOK_TYPES}")
        hook = Hook(name, hook_type, func)
        with self._lock:
            self.hooks[hook_type].append(hook)
        return hook

    def remove(self, hook_type: str, name: str) -> None:
        if hook_type in self.hooks:
            with self._lock:
                self.hooks[hook_type] = [
                    h for h in self.hooks[hook_type] if h.name != name
                ]

    def trigger(self, hook_type: str, **kwargs: Any) -> List[Dict[str, Any]]:
        if hook_type not in self.hooks:
            return []
        results: List[Dict[str, Any]] = []
        with self._lock:
            hooks_snapshot = list(self.hooks[hook_type])
        for hook in hooks_snapshot:
            try:
                result = hook.func(**kwargs)
                results.append({"hook": hook.name, "result": result})
            except Exception as e:
                results.append({"hook": hook.name, "error": str(e)})
                logger = logging.getLogger("hooks")
                logger.error(f"Hook {hook.name} 错误: {e}", exc_info=True)
        return results

    def list_hooks(self) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {}
        for hook_type, hooks_list in self.hooks.items():
            if hooks_list:
                result[hook_type] = [h.name for h in hooks_list]
        return result


hook_system = HookSystem()


_last_cleanup_date: str = ""
_cleanup_lock = threading.Lock()


def _cleanup_old_logs() -> None:
    global _last_cleanup_date
    today = datetime.now().strftime("%Y%m%d")
    with _cleanup_lock:
        if _last_cleanup_date == today:
            return
        _last_cleanup_date = today
    cutoff = datetime.now() - timedelta(days=MAX_LOG_AGE_DAYS)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for log_file in LOG_DIR.glob("chat_log_*.log"):
        try:
            date_str = log_file.stem.replace("chat_log_", "")
            file_date = datetime.strptime(date_str, "%Y%m%d")
            if file_date < cutoff:
                log_file.unlink()
        except (ValueError, OSError):
            pass


def log_chat_hook(user_message: str, ai_reply: str, **kwargs: Any) -> bool:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_path = LOG_DIR / f"chat_log_{datetime.now().strftime('%Y%m%d')}.log"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{timestamp}] 用户: {user_message}\n")
        f.write(f"[{timestamp}] AI: {ai_reply}\n\n")

    _cleanup_old_logs()
    return True


hook_system.register("after_chat", "log_chat", log_chat_hook)