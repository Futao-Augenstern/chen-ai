import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Generator

sys.path.insert(0, str(Path(__file__).parent))


def test_tool_result():
    from tools import ToolResult
    r = ToolResult(True, "hello")
    assert r.success is True
    assert r.content == "hello"
    assert r.error is None

    r = ToolResult(False, "", "bad")
    assert r.success is False
    assert r.error == "bad"


def test_calculator_safe():
    from tools import CalculatorTool
    calc = CalculatorTool()
    r = calc.execute(expression="1 + 2 * 3")
    assert r.success is True
    assert r.content == "7"

    r = calc.execute(expression="pow(2, 3)")
    assert r.success is True
    assert r.content == "8"

    r = calc.execute(expression="abs(-5)")
    assert r.success is True
    assert r.content == "5"

    r = calc.execute(expression="__import__('os')")
    assert r.success is False


def test_calculator_rejects_eval():
    from tools import CalculatorTool
    calc = CalculatorTool()
    r = calc.execute(expression="open('/etc/passwd')")
    assert r.success is False
    r = calc.execute(expression="os.system('ls')")
    assert r.success is False


def test_code_execution_safe():
    from tools import CodeExecutionTool
    cet = CodeExecutionTool()
    safe, reason = cet._is_safe("print('hello')")
    assert safe is True
    safe, reason = cet._is_safe("import os; os.system('ls')")
    assert safe is False


def test_code_execution():
    from tools import CodeExecutionTool
    cet = CodeExecutionTool()
    r = cet.execute(code="print('hello world')")
    assert r.success is True
    assert "hello world" in r.content


def test_web_search():
    from tools import WebSearchTool
    ws = WebSearchTool()
    r = ws.execute(query="python")
    assert r.success is True


def test_file_tool():
    from tools import FileTool
    ft = FileTool()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write("test content")
        tmp_path = tmp.name
    try:
        r = ft.execute(operation="read", path=tmp_path)
        assert r.success is True
        assert r.content == "test content"
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def test_tool_registry():
    from tools import ToolRegistry
    tr = ToolRegistry()
    tools = tr.list_tools()
    assert len(tools) >= 4
    names = [t["name"] for t in tools]
    assert "web_search" in names
    assert "calculator" in names
    assert "execute_code" in names
    assert "file_operations" in names


def test_working_memory():
    from memory import WorkingMemory
    wm = WorkingMemory(max_messages=5)
    wm.add("user", "hello")
    wm.add("assistant", "hi")
    assert len(wm.messages) == 2
    assert wm.messages[0]["role"] == "user"
    ctx = wm.summarize()
    assert "hello" in ctx


def test_memory_overflow():
    from memory import WorkingMemory
    wm = WorkingMemory(max_messages=3)
    for i in range(10):
        wm.add("user", f"msg{i}")
    assert len(wm.messages) == 3


def test_semantic_memory():
    from memory import SemanticMemory
    sm = SemanticMemory()
    sm.set_preference("name", "test_user")
    assert sm.get_preference("name") == "test_user"
    sm.add_fact("topic", "python programming")
    results = sm.search_facts("python")
    assert len(results) > 0


def test_tfidf_search():
    from memory import TFIDFSearch
    tfidf = TFIDFSearch()
    tfidf.add_document("python is a programming language")
    tfidf.add_document("java is also a programming language")
    tfidf.add_document("hello world")
    results = tfidf.search("python")
    assert len(results) > 0
    assert results[0][0] == 0


def test_episodic_memory():
    from memory import EpisodicMemory
    em = EpisodicMemory()
    em.add("test session", "user asked about python", ["python"])
    results = em.search("python")
    assert len(results) > 0


def test_memory_system():
    from memory import MemorySystem
    ms = MemorySystem()
    ms.record_interaction("hi", "hello")
    stats = ms.get_stats()
    assert stats["working_messages"] == 2
    ms.learn_preference("lang", "python")
    assert ms.semantic.get_preference("lang") == "python"


def test_prompt_cache():
    from cache_optimizer import PromptCache
    pc = PromptCache()
    msgs = [{"role": "system", "content": "test"}]
    assert pc.get_cached_prefix(msgs) is None
    pc.set_cached_prefix(msgs, {"result": "cached"})
    cached = pc.get_cached_prefix(msgs)
    assert cached is not None
    assert cached["result"] == "cached"


def test_cost_tracker():
    from cache_optimizer import CostTracker
    ct = CostTracker()
    ct.record_request("gpt-3.5-turbo", "hello", "hi")
    stats = ct.get_stats()
    assert stats["requests"] == 1


def test_prompt_compressor():
    from prompt_compressor import PromptCompressor
    pc = PromptCompressor()
    original = "请问你能帮我搜索一下最新的新闻吗？"
    compressed = pc.compress(original, "medium")
    assert len(compressed) <= len(original)


def test_mcp_server():
    from mcp_server import MCPServer
    s = MCPServer("test", "desc", "echo")
    d = s.to_dict()
    assert d["name"] == "test"
    s2 = MCPServer.from_dict(d)
    assert s2.name == "test"


def test_mcp_manager():
    from mcp_server import MCPManager
    m = MCPManager()
    stats = m.get_stats()
    assert stats["total"] >= 20
    assert len(m.get_categories()) > 0
    config = m.generate_mcp_json()
    assert "mcpServers" in config


def test_skill_manager():
    from skills import SkillManager
    sm = SkillManager()
    skills = sm.list_skills()
    assert len(skills) >= 39
    categories = sm.get_categories()
    assert "编程" in categories


def test_skill_suggest():
    from skills import SkillManager
    sm = SkillManager()
    result = sm.suggest_skill("帮我审查一下这段代码")
    assert result is not None
    result = sm.suggest_skill("帮我写个SQL")
    assert result == "数据库设计"


def test_hook_system():
    from hooks import HookSystem
    hs = HookSystem()
    results = []

    def test_hook(**kwargs):
        results.append(kwargs.get("msg", ""))

    hs.register("before_chat", "test", test_hook)
    hs.trigger("before_chat", msg="hello")
    assert "hello" in results


def test_agent_loop_think_keyword():
    from tools import ToolRegistry
    from memory import MemorySystem
    from agent_loop import AgentLoop

    class FakeAI:
        def __init__(self):
            self.temperature = 0.7
            self.max_tokens = 2048
            self.model = "test"
            self.system_prompt = "test"
            self.client = None
            self.history = []
            self.default_system_prompt = "test"
            self.provider_name = "test"

    ai = FakeAI()
    loop = AgentLoop(ai)
    plan = loop._think_keyword("计算 1+1")
    assert len(plan["tools"]) > 0
    assert plan["tools"][0]["name"] == "calculator"


def test_agent_loop_learn():
    from tools import ToolRegistry
    from memory import MemorySystem
    from agent_loop import AgentLoop

    class FakeAI:
        def __init__(self):
            self.temperature = 0.7
            self.max_tokens = 2048
            self.model = "test"
            self.system_prompt = "test"
            self.client = None
            self.history = []
            self.default_system_prompt = "test"
            self.provider_name = "test"

    ai = FakeAI()
    loop = AgentLoop(ai)
    loop._learn("我叫张三", "")
    assert loop.memory.semantic.get_preference("name") == "张三"
    loop._learn("我是李四", "")
    assert loop.memory.semantic.get_preference("name") == "李四"


def test_config():
    from config import load_providers, get_provider_config, get_provider_names
    names = get_provider_names()
    assert "OpenAI" in names
    assert "DeepSeek" in names
    cfg = get_provider_config("OpenAI")
    assert cfg is not None
    assert cfg["name"] == "OpenAI"


def test_ai_chat_init():
    from ai_core import AIChat
    ai = AIChat(provider_name="OpenAI")
    assert ai.provider_name == "OpenAI"
    assert ai.model is not None
    history = ai.get_history()
    assert len(history) == 0


def test_ai_chat_provider_key():
    from ai_core import AIChat
    ai = AIChat(provider_name="DeepSeek")
    assert ai.provider_name == "DeepSeek"
    assert ai.api_key is not None


def test_ai_chat_history_trim():
    from ai_core import AIChat
    ai = AIChat(provider_name="OpenAI")
    ai.max_history = 10
    for i in range(50):
        ai.history.append({"role": "user", "content": f"msg{i}"})
    ai._trim_history()
    assert len(ai.history) <= 10


def test_resilience_circuit_breaker():
    from resilience import CircuitBreaker, CircuitBreakerOpenError
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.1)
    call_count = [0]

    def fail_twice():
        call_count[0] += 1
        if call_count[0] <= 2:
            raise ValueError("fail")
        return "ok"

    for _ in range(2):
        try:
            cb.call(fail_twice)
        except ValueError:
            pass

    assert cb.state == "open"
    import time
    time.sleep(0.15)

    result = cb.call(fail_twice)
    assert result == "ok"
    assert cb.state == "closed"


def test_retry_with_backoff():
    from resilience import retry_with_backoff
    call_count = [0]

    @retry_with_backoff(max_retries=3, base_delay=0.01, jitter=False)
    def succeed_after_2():
        call_count[0] += 1
        if call_count[0] < 3:
            raise ValueError("fail")
        return "ok"

    result = succeed_after_2()
    assert result == "ok"
    assert call_count[0] == 3


def test_context_manager_token_count():
    from context_manager import count_tokens, _estimate_tokens
    text = "Hello, world!"
    tokens = count_tokens(text)
    assert tokens > 0

    chinese = "你好世界"
    tokens_cn = count_tokens(chinese)
    assert tokens_cn > 0


def test_context_window_truncation():
    from context_manager import ContextWindowManager
    cwm = ContextWindowManager(model="gpt-4", max_input_tokens=100)
    msgs = [{"role": "user", "content": "x" * 500} for _ in range(5)]
    truncated = cwm.truncate_messages(msgs)
    assert len(truncated) < len(msgs)


def test_json_tool():
    from tools import JSONTool
    jt = JSONTool()
    r = jt.execute(json_data='{"a": {"b": 1}, "c": [1,2,3]}', query="a.b")
    assert r.success
    assert "1" in r.content

    r = jt.execute(json_data='[{"name": "a"}, {"name": "b"}]', query="*.name")
    assert r.success
    assert "a" in r.content


def test_time_tool():
    from tools import TimeTool
    tt = TimeTool()
    r = tt.execute(operation="now")
    assert r.success
    assert "iso" in r.content

    r = tt.execute(operation="add", value="2024-01-01,10")
    assert r.success


def test_text_tool():
    from tools import TextTool
    tt = TextTool()
    r = tt.execute(operation="count", text="Hello World 你好")
    assert r.success
    assert "中文字符" in r.content

    r = tt.execute(operation="extract", text="Contact: user@test.com, https://example.com")
    assert r.success
    assert "user@test.com" in r.content


def test_telemetry_tracer():
    from telemetry import Tracer
    t = Tracer("test")
    t.start_trace("trace-1")
    span = t.start_span("test_op")
    t.end_span(span)
    assert span.duration_ms >= 0


def test_telemetry_metrics():
    from telemetry import Metrics
    m = Metrics()
    m.counter("req").add(5)
    assert m.counter("req").get() == 5

    m.histogram("latency").record(100)
    stats = m.histogram("latency").stats()
    assert stats["count"] == 1

    m.gauge("mem").set(42.5)
    assert m.gauge("mem").get() == 42.5


def test_lru_cache():
    from cache_optimizer import LRUCache
    cache = LRUCache(max_size=3)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert cache.get("a") == 1
    cache.put("d", 4)
    assert cache.get("b") is None
    assert cache.get("a") == 1


def test_prompt_compressor_dedup():
    from prompt_compressor import PromptCompressor
    pc = PromptCompressor()
    text = "line1\nline1\nline2\n"
    result = pc.deduplicate(text)
    assert result.count("line1") == 1


def test_benchmark_cache():
    from cache_optimizer import PromptCache
    import time
    pc = PromptCache()
    start = time.time()
    for i in range(100):
        msgs = [{"role": "system", "content": f"test{i}"}]
        pc.set_cached_prefix(msgs, {"result": str(i)})
        pc.get_cached_prefix(msgs)
    elapsed = time.time() - start
    assert elapsed < 5.0, f"缓存操作太慢: {elapsed:.2f}s"


def test_benchmark_tool_execution():
    from tools import CalculatorTool
    import time
    calc = CalculatorTool()
    start = time.time()
    for i in range(100):
        calc.execute(expression=f"{i} + {i}")
    elapsed = time.time() - start
    assert elapsed < 2.0, f"工具执行太慢: {elapsed:.2f}s"


if __name__ == "__main__":
    import traceback

    tests = [
        ("test_tool_result", test_tool_result),
        ("test_calculator_safe", test_calculator_safe),
        ("test_calculator_rejects_eval", test_calculator_rejects_eval),
        ("test_code_execution_safe", test_code_execution_safe),
        ("test_code_execution", test_code_execution),
        ("test_web_search", test_web_search),
        ("test_file_tool", test_file_tool),
        ("test_tool_registry", test_tool_registry),
        ("test_working_memory", test_working_memory),
        ("test_memory_overflow", test_memory_overflow),
        ("test_semantic_memory", test_semantic_memory),
        ("test_tfidf_search", test_tfidf_search),
        ("test_episodic_memory", test_episodic_memory),
        ("test_memory_system", test_memory_system),
        ("test_prompt_cache", test_prompt_cache),
        ("test_cost_tracker", test_cost_tracker),
        ("test_prompt_compressor", test_prompt_compressor),
        ("test_mcp_server", test_mcp_server),
        ("test_mcp_manager", test_mcp_manager),
        ("test_skill_manager", test_skill_manager),
        ("test_skill_suggest", test_skill_suggest),
        ("test_hook_system", test_hook_system),
        ("test_agent_loop_think_keyword", test_agent_loop_think_keyword),
        ("test_agent_loop_learn", test_agent_loop_learn),
        ("test_config", test_config),
        ("test_ai_chat_init", test_ai_chat_init),
        ("test_ai_chat_provider_key", test_ai_chat_provider_key),
        ("test_ai_chat_history_trim", test_ai_chat_history_trim),
        ("test_resilience_circuit_breaker", test_resilience_circuit_breaker),
        ("test_retry_with_backoff", test_retry_with_backoff),
        ("test_context_manager_token_count", test_context_manager_token_count),
        ("test_context_window_truncation", test_context_window_truncation),
        ("test_json_tool", test_json_tool),
        ("test_time_tool", test_time_tool),
        ("test_text_tool", test_text_tool),
        ("test_telemetry_tracer", test_telemetry_tracer),
        ("test_telemetry_metrics", test_telemetry_metrics),
        ("test_lru_cache", test_lru_cache),
        ("test_prompt_compressor_dedup", test_prompt_compressor_dedup),
        ("test_benchmark_cache", test_benchmark_cache),
        ("test_benchmark_tool_execution", test_benchmark_tool_execution),
    ]

    passed = 0
    failed = 0
    for name, func in tests:
        try:
            func()
            print(f"  ✅ {name}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {name}: {e}")
            failed += 1

    print(f"\n{'=' * 40}")
    print(f"  通过: {passed}  |  失败: {failed}  |  总计: {len(tests)}")
    print(f"{'=' * 40}")
    sys.exit(1 if failed > 0 else 0)