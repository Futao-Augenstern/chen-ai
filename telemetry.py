import time
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

TELEMETRY_DIR = Path(__file__).parent / "telemetry"
TELEMETRY_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class Span:
    name: str
    start_time: float
    end_time: Optional[float] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def duration_ms(self) -> float:
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000


@dataclass
class Trace:
    trace_id: str
    spans: List[Span] = field(default_factory=list)


class Tracer:
    def __init__(self, service_name: str = "ai-agent"):
        self.service_name = service_name
        self.current_trace: Optional[Trace] = None
        self.traces: List[Trace] = []
        self._spans_stack: List[Span] = []

    def start_trace(self, trace_id: str) -> Trace:
        trace = Trace(trace_id=trace_id)
        self.current_trace = trace
        self.traces.append(trace)
        return trace

    def start_span(self, name: str, **attributes: Any) -> Span:
        span = Span(name=name, start_time=time.time(), attributes=attributes)
        if self.current_trace:
            self.current_trace.spans.append(span)
        self._spans_stack.append(span)
        return span

    def end_span(self, span: Span, **attributes: Any) -> Span:
        span.end_time = time.time()
        if attributes:
            span.attributes.update(attributes)
        if self._spans_stack and self._spans_stack[-1] is span:
            self._spans_stack.pop()
        return span

    def add_event(self, name: str, **attrs: Any) -> None:
        if not self._spans_stack:
            return
        span = self._spans_stack[-1]
        span.events.append({
            "name": name,
            "time": time.time(),
            "attributes": attrs,
        })

    def get_current_span(self) -> Optional[Span]:
        if self._spans_stack:
            return self._spans_stack[-1]
        return None

    def export(self) -> None:
        if not self.traces:
            return
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_file = TELEMETRY_DIR / f"trace-{timestamp}.json"
        data = {
            "service": self.service_name,
            "exported_at": datetime.now().isoformat(),
            "traces": [
                {
                    "trace_id": t.trace_id,
                    "spans": [
                        {
                            "name": s.name,
                            "start_time": s.start_time,
                            "end_time": s.end_time,
                            "duration_ms": s.duration_ms,
                            "attributes": s.attributes,
                            "events": s.events,
                        }
                        for s in t.spans
                    ],
                }
                for t in self.traces
            ],
        }
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def clear(self) -> None:
        self.traces.clear()
        self.current_trace = None
        self._spans_stack.clear()


class Histogram:
    def __init__(self, buckets: Optional[List[float]] = None):
        self.buckets = buckets or [10, 50, 100, 500, 1000, 5000]
        self.counts: Dict[float, int] = {b: 0 for b in self.buckets}
        self.sum: float = 0.0
        self.count: int = 0
        self.min: float = float("inf")
        self.max: float = 0.0
        self._values: List[float] = []

    def record(self, value: float) -> None:
        self.sum += value
        self.count += 1
        self.min = min(self.min, value)
        self.max = max(self.max, value)
        for b in self.buckets:
            if value <= b:
                self.counts[b] += 1
                break
        self._values.append(value)
        if len(self._values) > 10000:
            self._values = self._values[-10000:]

    def stats(self) -> Dict[str, Any]:
        if self.count == 0:
            return {
                "count": 0,
                "sum": 0,
                "min": 0,
                "max": 0,
                "avg": 0,
            }
        return {
            "count": self.count,
            "sum": self.sum,
            "min": self.min,
            "max": self.max,
            "avg": self.sum / self.count,
            "p50": self._percentile(50),
            "p90": self._percentile(90),
            "p99": self._percentile(99),
        }

    def _percentile(self, p: float) -> float:
        if not self._values:
            return 0.0
        sorted_vals = sorted(self._values)
        k = (len(sorted_vals) - 1) * p / 100.0
        f = int(k)
        c = f + 1 if f + 1 < len(sorted_vals) else f
        if f == c:
            return sorted_vals[f]
        return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


class Counter:
    def __init__(self):
        self.value: int = 0

    def add(self, delta: int = 1) -> None:
        self.value += delta

    def get(self) -> int:
        return self.value


class Gauge:
    def __init__(self, initial: float = 0.0):
        self.value: float = initial

    def set(self, value: float) -> None:
        self.value = value

    def get(self) -> float:
        return self.value


class Metrics:
    def __init__(self):
        self.counters: Dict[str, Counter] = {}
        self.histograms: Dict[str, Histogram] = {}
        self.gauges: Dict[str, Gauge] = {}

    def counter(self, name: str) -> Counter:
        if name not in self.counters:
            self.counters[name] = Counter()
        return self.counters[name]

    def histogram(self, name: str, buckets: Optional[List[float]] = None) -> Histogram:
        if name not in self.histograms:
            self.histograms[name] = Histogram(buckets)
        return self.histograms[name]

    def gauge(self, name: str, initial: float = 0.0) -> Gauge:
        if name not in self.gauges:
            self.gauges[name] = Gauge(initial)
        return self.gauges[name]

    def collect(self) -> Dict[str, Any]:
        return {
            "counters": {name: c.get() for name, c in self.counters.items()},
            "histograms": {name: h.stats() for name, h in self.histograms.items()},
            "gauges": {name: g.get() for name, g in self.gauges.items()},
        }

    def export_json(self) -> str:
        return json.dumps(self.collect(), indent=2, ensure_ascii=False)


_default_tracer = Tracer()
_default_metrics = Metrics()


def get_tracer() -> Tracer:
    return _default_tracer


def get_metrics() -> Metrics:
    return _default_metrics


def timed(span_name: str):
    def decorator(func):
        def wrapper(*args, **kwargs):
            tracer = get_tracer()
            span = tracer.start_span(span_name)
            try:
                result = func(*args, **kwargs)
                tracer.end_span(span)
                return result
            except Exception as e:
                tracer.end_span(span, error=str(e))
                raise e
        return wrapper
    return decorator