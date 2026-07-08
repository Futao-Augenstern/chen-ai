import time
import random
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Type, TypeVar

T = TypeVar("T")

logger = logging.getLogger("resilience")


class CircuitBreakerOpenError(Exception):
    pass


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max: int = 3

    failure_count: int = field(default=0, init=False)
    last_failure_time: float = field(default=0.0, init=False)
    state: str = field(default="closed", init=False)
    half_open_successes: int = field(default=0, init=False)

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        if self.state == "open":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "half-open"
                self.half_open_successes = 0
                logger.info("断路器: open -> half-open, 尝试恢复")
            else:
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
        if self.state == "open":
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = "half-open"
                self.half_open_successes = 0
                logger.info("断路器: open -> half-open, 尝试恢复")
            else:
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
            logger.warning(
                f"断路器: closed -> open, 连续失败 {self.failure_count} 次"
            )

    def reset(self) -> None:
        self.failure_count = 0
        self.state = "closed"
        self.half_open_successes = 0


def retry_with_backoff(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: Optional[tuple] = None,
) -> Callable:
    if retryable_exceptions is None:
        retryable_exceptions = (Exception,)

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception: Optional[Exception] = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = min(base_delay * (backoff_factor ** attempt), max_delay)
                        if jitter:
                            delay *= 0.5 + random.random()
                        logger.warning(
                            f"重试 {attempt + 1}/{max_retries}: {func.__name__} "
                            f"失败 ({e}), {delay:.1f}s 后重试"
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"重试耗尽: {func.__name__} 失败 {max_retries + 1} 次"
                        )
            raise last_exception  # type: ignore[misc]

        return wrapper

    return decorator


class ResilientAPIClient:
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        circuit_threshold: int = 5,
        circuit_recovery: float = 30.0,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=circuit_threshold,
            recovery_timeout=circuit_recovery,
        )

    def call(self, func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        def _attempt() -> T:
            return self.circuit_breaker.call(func, *args, **kwargs)

        return retry_with_backoff(
            max_retries=self.max_retries,
            base_delay=self.base_delay,
            retryable_exceptions=(CircuitBreakerOpenError, Exception),
        )(_attempt)()

    async def async_call(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> T:
        async def _attempt() -> T:
            return await self.circuit_breaker.async_call(func, *args, **kwargs)

        last_exception: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                return await _attempt()
            except (CircuitBreakerOpenError, Exception) as e:
                last_exception = e
                if attempt < self.max_retries:
                    delay = min(self.base_delay * (2 ** attempt), 30.0)
                    delay *= 0.5 + random.random()
                    logger.warning(
                        f"异步重试 {attempt + 1}/{self.max_retries}: "
                        f"失败 ({e}), {delay:.1f}s 后重试"
                    )
                    time.sleep(delay)
                else:
                    logger.error(f"异步重试耗尽: 失败 {self.max_retries + 1} 次")
        raise last_exception  # type: ignore[misc]