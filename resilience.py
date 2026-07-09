import os
import time
import random
import logging
import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, TypeVar

T = TypeVar("T")
logger = logging.getLogger("resilience")

try:
    from config import CIRCUIT_RECOVERY_TIMEOUT, RETRY_MAX_DELAY
except ImportError:
    CIRCUIT_RECOVERY_TIMEOUT = float(os.environ.get("CIRCUIT_RECOVERY_TIMEOUT", "30.0"))
    RETRY_MAX_DELAY = float(os.environ.get("RETRY_MAX_DELAY", "30.0"))


class CircuitBreakerOpenError(Exception):
    pass


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    recovery_timeout: float = CIRCUIT_RECOVERY_TIMEOUT
    half_open_max: int = 3

    failure_count: int = field(default=0, init=False)
    last_failure_time: float = field(default=0.0, init=False)
    state: str = field(default="closed", init=False)
    half_open_successes: int = field(default=0, init=False)

    def _check_state(self) -> None:
        if self.state == "open" and time.time() - self.last_failure_time > self.recovery_timeout:
            self.state = "half-open"
            self.half_open_successes = 0
            logger.info("断路器: open -> half-open, 尝试恢复")

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        self._check_state()
        if self.state == "open":
            raise CircuitBreakerOpenError(
                f"断路器打开中，{self.recovery_timeout - (time.time() - self.last_failure_time):.0f}s 后重试"
            )
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e

    async def async_call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> T:
        self._check_state()
        if self.state == "open":
            raise CircuitBreakerOpenError(
                f"断路器打开中，{self.recovery_timeout - (time.time() - self.last_failure_time):.0f}s 后重试"
            )
        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise e

    def _on_success(self) -> None:
        if self.state == "half-open":
            self.half_open_successes += 1
            if self.half_open_successes >= self.half_open_max:
                self.state = "closed"
                self.failure_count = 0
                logger.info("断路器: half-open -> closed, 已恢复")
        else:
            self.failure_count = 0

    def _on_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.state == "half-open":
            self.state = "open"
            logger.warning("断路器: half-open -> open, 恢复失败")
        elif self.failure_count >= self.failure_threshold:
            self.state = "open"
            logger.warning(f"断路器: closed -> open, 连续失败 {self.failure_count} 次")

    def reset(self) -> None:
        self.failure_count = 0
        self.state = "closed"
        self.half_open_successes = 0


def _calc_delay(attempt: int, base_delay: float, max_delay: float,
                backoff_factor: float, jitter: bool) -> float:
    delay = min(base_delay * (backoff_factor ** attempt), max_delay)
    if jitter:
        delay *= 0.5 + random.random()
    return delay


def retry_with_backoff(max_retries: int = 3, base_delay: float = 1.0,
                       max_delay: float = RETRY_MAX_DELAY, backoff_factor: float = 2.0,
                       jitter: bool = True,
                       retryable_exceptions: Optional[tuple] = None) -> Callable:
    if retryable_exceptions is None:
        retryable_exceptions = (Exception,)

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exc: Optional[Exception] = None
            for attempt in range(max_retries + 1):
                try:
                    result = func(*args, **kwargs)
                    if attempt > 0:
                        logger.info(f"重试成功: {func.__name__} 在第 {attempt} 次重试后恢复")
                    return result
                except retryable_exceptions as e:
                    last_exc = e
                    if attempt < max_retries:
                        delay = _calc_delay(attempt, base_delay, max_delay, backoff_factor, jitter)
                        logger.warning(f"重试 {attempt + 1}/{max_retries}: {func.__name__} 失败 ({e}), {delay:.1f}s 后重试")
                        time.sleep(delay)
                    else:
                        logger.error(f"重试耗尽: {func.__name__} 失败 {max_retries + 1} 次")
            raise last_exc  # type: ignore[misc]
        return wrapper
    return decorator


class ResilientAPIClient:
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0,
                 circuit_threshold: int = 5, circuit_recovery: float = CIRCUIT_RECOVERY_TIMEOUT):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=circuit_threshold,
            recovery_timeout=circuit_recovery,
        )

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                return self.circuit_breaker.call(func, *args, **kwargs)
            except CircuitBreakerOpenError:
                raise
            except Exception as e:
                last_exc = e
                if attempt < self.max_retries:
                    delay = _calc_delay(attempt, self.base_delay, RETRY_MAX_DELAY, 2.0, True)
                    logger.warning(f"重试 {attempt + 1}/{self.max_retries}: 失败 ({e}), {delay:.1f}s 后重试")
                    time.sleep(delay)
                else:
                    logger.error(f"重试耗尽: 失败 {self.max_retries + 1} 次")
        raise last_exc  # type: ignore[misc]

    async def async_call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> T:
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                return await self.circuit_breaker.async_call(func, *args, **kwargs)
            except CircuitBreakerOpenError:
                raise
            except Exception as e:
                last_exc = e
                if attempt < self.max_retries:
                    delay = _calc_delay(attempt, self.base_delay, RETRY_MAX_DELAY, 2.0, True)
                    logger.warning(f"异步重试 {attempt + 1}/{self.max_retries}: 失败 ({e}), {delay:.1f}s 后重试")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"异步重试耗尽: 失败 {self.max_retries + 1} 次")
        raise last_exc  # type: ignore[misc]
