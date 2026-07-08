import json
import concurrent.futures
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional, Tuple

from tools import ToolRegistry
from memory import MemorySystem
from cache_optimizer import CacheFirstLoop, CostTracker
from prompt_compressor import PromptOptimizer
from resilience import ResilientAPIClient, CircuitBreakerOpenError
from context_manager import ContextWindowManager, ConversationSummarizer, count_tokens
from telemetry import get_tracer, get_metrics


@dataclass
class ToolCallPlan:
    tools: List[Dict[str, Any]] = field(default_factory=list)
    reasoning: str = ""


@dataclass
class ReflectionResult:
    is_sufficient: bool = True
    missing_info: str = ""
    next_steps: List[Dict[str, Any]] = field(default_factory=list)


class AgentLoop:
    def __init__(
        self,
        ai_chat: Any,
        memory_system: Optional[MemorySystem] = None,
        tool_registry: Optional[ToolRegistry] = None,
    ):
        self.ai = ai_chat
        self.memory = memory_system or MemorySystem()
        self.tools = tool_registry or ToolRegistry()
        self.cache_loop = CacheFirstLoop()
        self.cost_tracker = CostTracker()
        self.prompt_optimizer = PromptOptimizer()
        self.max_iterations: int = 5
        self.max_parallel_tools: int = 3
        self.active_skill: Optional[Any] = None
        self.use_cache: bool = True
        self.use_compression: bool = False
        self.use_function_calling: bool = True
        self.use_self_reflection: bool = True
        self.resilience = ResilientAPIClient(
            max_retries=3,
            base_delay=1.0,
            circuit_threshold=5,
            circuit_recovery=30.0,
        )
        self.context_manager = ContextWindowManager(
            model=self.ai.model,
            reserve_output_tokens=self.ai.max_tokens,
        )
        self.summarizer = ConversationSummarizer(self.ai)
        self._cached_tool_funcs: Optional[List[Dict[str, Any]]] = None
        self._tool_cache_version: int = 0

    def set_skill(self, skill_name: str, skill_manager: Any) -> bool:
        skill = skill_manager.get_skill(skill_name)
        if skill:
            self.active_skill = skill
            self.ai.system_prompt = skill.prompt
            skill_manager.use_skill(skill_name)
            self._cached_tool_funcs = None
            return True
        return False

    def clear_skill(self, default_prompt: str) -> None:
        self.active_skill = None
        self.ai.system_prompt = default_prompt
        self._cached_tool_funcs = None

    def _build_tool_functions(self) -> List[Dict[str, Any]]:
        tool_count = len(self.tools.list_tools())
        if self._cached_tool_funcs is not None and self._tool_cache_version == tool_count:
            return self._cached_tool_funcs

        funcs: List[Dict[str, Any]] = []
        for tool_info in self.tools.list_tools():
            tool = self.tools.get(tool_info["name"])
            if tool is None:
                continue
            props: Dict[str, Any] = {}
            required: List[str] = []
            for param_name, param_desc in tool.parameters.items():
                desc = str(param_desc)
                props[param_name] = {
                    "type": "string",
                    "description": desc,
                }
                if "可选" not in desc and "optional" not in desc.lower():
                    required.append(param_name)

            func_def: Dict[str, Any] = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": props,
                        "required": required,
                    },
                },
            }
            funcs.append(func_def)
        self._cached_tool_funcs = funcs
        self._tool_cache_version = tool_count
        return funcs

    def _execute_single_tool(self, tool_info: Dict[str, Any]) -> Any:
        return self.tools.execute(tool_info["name"], **tool_info["params"])

    def _execute_tools_parallel(self, tools: List[Dict[str, Any]]) -> List[Any]:
        """并行执行多个无依赖工具 - 参考 smolagents/CrewAI 最佳实践"""
        if len(tools) <= 1:
            return self._act(tools)

        results: List[Any] = []
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(tools), self.max_parallel_tools)
        ) as executor:
            futures = [
                executor.submit(self._execute_single_tool, tool)
                for tool in tools[:self.max_parallel_tools]
            ]
            for future in concurrent.futures.as_completed(futures):
                try:
                    results.append(future.result())
                except Exception:
                    results.append(None)

        for tool in tools[self.max_parallel_tools:]:
            results.append(self._execute_single_tool(tool))

        return [r for r in results if r is not None]

    def _think_llm_structured(self, message: str) -> ToolCallPlan:
        tool_funcs = self._build_tool_functions()
        if not tool_funcs:
            return ToolCallPlan(tools=[], reasoning="no tools available")

        system_prompt = (
            "You are a tool call planner. Based on the user message, decide if tools are needed.\n"
            "Return a JSON object:\n"
            "{\n"
            '  "reasoning": "your reasoning",\n'
            '  "tools": [{"name": "tool_name", "params": {"param": "value"}}]\n'
            "}\n\n"
            "If no tools are needed, return an empty tools array."
        )

        try:
            response = self.resilience.call(
                lambda: self.ai.client.chat.completions.create(
                    model=self.ai.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": message},
                    ],
                    tools=tool_funcs,
                    tool_choice="auto",
                    temperature=0,
                    max_tokens=500,
                    response_format={"type": "json_object"},
                )
            )
            msg = response.choices[0].message
            content = msg.content or "{}"

            try:
                data = json.loads(content)
                plan = ToolCallPlan(
                    tools=data.get("tools", []),
                    reasoning=data.get("reasoning", "JSON parsed"),
                )
                return plan
            except (json.JSONDecodeError, TypeError):
                pass

            if msg.tool_calls:
                tools: List[Dict[str, Any]] = []
                for tc in msg.tool_calls:
                    try:
                        tools.append({
                            "name": tc.function.name,
                            "params": json.loads(tc.function.arguments),
                        })
                    except json.JSONDecodeError:
                        pass
                return ToolCallPlan(
                    tools=tools,
                    reasoning="native function calling",
                )

            return ToolCallPlan(tools=[], reasoning="no tool calls needed")

        except Exception:
            plan = self._think_keyword(message)
            return ToolCallPlan(
                tools=plan["tools"],
                reasoning="fallback to keyword matching",
            )

    def _think_llm(self, message: str) -> Dict[str, Any]:
        """兼容旧接口，返回 dict"""
        plan = self._think_llm_structured(message)
        return {"tools": plan.tools, "reasoning": plan.reasoning}

    def _think_keyword(self, message: str) -> Dict[str, Any]:
        plan: Dict[str, Any] = {"tools": []}

        keyword_rules = [
            (r"(?:搜索|查一下|帮我查|搜)\s*[:：]?\s*(.+)", "web_search", "query", False),
            (r"(?:算|计算)\s*[:：]?\s*(.+)", "calculator", "expression", False),
            (r"(?:运行|执行).*?代码\s*[:：]?\s*```(\w*)\n(.*?)```", "execute_code", "code", True),
            (r"(?:运行|执行).*?代码\s*[:：]?\s*(.+)", "execute_code", "code", False),
            (r"(?:读取|读|打开).*?文件\s*[:：]?\s*(.+)", "file_operations", "operation", False),
            (r"(?:json|JSON).*?(?:解析|处理|查询)\s*[:：]?\s*(.+)", "json_processor", "json_data", False),
            (r"(?:时间|日期|今天|现在).*?(?:几点|几号|是什么时候)", "time_utils", "operation", False),
            (r"(?:统计|计数|提取).*?(?:文本|文字)\s*[:：]?\s*(.+)", "text_processor", "text", False),
        ]

        for pattern, tool_name, param_name, dotall in keyword_rules:
            flags = re.IGNORECASE | (re.DOTALL if dotall else 0)
            m = re.search(pattern, message, flags)
            if m:
                if tool_name == "execute_code" and dotall:
                    code = m.group(2).strip()
                    plan["tools"].append({"name": tool_name, "params": {"code": code}})
                elif tool_name == "file_operations":
                    plan["tools"].append({
                        "name": tool_name,
                        "params": {"operation": "read", "path": m.group(1).strip()},
                    })
                elif tool_name == "time_utils":
                    plan["tools"].append({
                        "name": tool_name,
                        "params": {"operation": "now"},
                    })
                else:
                    plan["tools"].append({
                        "name": tool_name,
                        "params": {param_name: m.group(1).strip()},
                    })
                break

        return plan

    def _reflect_on_result(
        self,
        original_message: str,
        tool_results: List[Any]
    ) -> ReflectionResult:
        if not self.use_self_reflection:
            return ReflectionResult(
                is_sufficient=True,
                missing_info="",
                next_steps=[]
            )

        result_text = "\n".join([
            f"Tool {i+1}: " + (r.content if r.success else f"Failed: {r.error}")
            for i, r in enumerate(tool_results)
        ])

        prompt = (
            "User question: {0}\n\n"
            "Tool results:\n{1}\n\n"
            "Are the current results sufficient to answer the user's question?\n"
            "If yes, return is_sufficient = true.\n"
            "If no, explain what's missing and what tools to call next.\n\n"
            'Return JSON: {{"is_sufficient": true/false, "missing_info": "", "next_steps": []}}'
        ).format(original_message, result_text)

        try:
            response = self.resilience.call(
                lambda: self.ai.client.chat.completions.create(
                    model=self.ai.model,
                    messages=[
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0,
                    max_tokens=400,
                    response_format={"type": "json_object"},
                )
            )
            content = response.choices[0].message.content or "{}"
            data = json.loads(content)
            return ReflectionResult(
                is_sufficient=data.get("is_sufficient", True),
                missing_info=data.get("missing_info", ""),
                next_steps=data.get("next_steps", []),
            )
        except Exception:
            return ReflectionResult(
                is_sufficient=True,
                missing_info="",
                next_steps=[]
            )

    def _act(self, tools: List[Dict[str, Any]]) -> List[Any]:
        results: List[Any] = []
        for tool_info in tools:
            result = self.tools.execute(tool_info["name"], **tool_info["params"])
            results.append(result)
        return results

    def _build_context(
        self, original_message: str, tool_results: List[Any]
    ) -> str:
        parts: List[str] = [original_message]
        for i, result in enumerate(tool_results):
            if result is None:
                parts.append(f"\n[工具 {i+1} 执行失败]\n未知错误")
            elif result.success:
                parts.append(f"\n[工具 {i+1} 返回结果]\n{result.content}")
            else:
                parts.append(f"\n[工具 {i+1} 执行失败]\n{result.error}")
        return "\n".join(parts)

    def _learn(self, user_message: str, ai_reply: str) -> None:
        learn_patterns = [
            (r"我叫\s*(\S+)", "name"),
            (r"我是\s*(\S+)", "name"),
            (r"我的名字[是叫]?\s*(\S+)", "name"),
            (r"我[在就于]\s*(\S+)", "location"),
            (r"我[住在]\s*(\S+[省市])", "location"),
            (r"我的邮箱[是]?\s*(\S+@\S+)", "email"),
            (r"我[用使]的[是]?\s*([Pp]ython|Java|Go|Rust|C\+\+|JS|Node)", "language"),
            (r"我[的]?技术栈[是]?\s*(.+)", "tech_stack"),
            (r"我[的]?职业[是]?\s*(.+)", "profession"),
            (r"我喜欢\s*(.+)", "like"),
            (r"我偏好\s*(.+)", "preference"),
            (r"我不喜欢\s*(.+)", "dislike"),
        ]
        for pattern, key in learn_patterns:
            m = re.search(pattern, user_message)
            if m:
                value = m.group(1).strip()
                if value and len(value) < 200:
                    self.memory.learn_preference(key, value)
                    if key == "name":
                        break

    def run(self, user_message: str) -> str:
        tracer = get_tracer()
        metrics = get_metrics()
        trace_id = f"req-{int(time.time() * 1000)}"
        trace = tracer.start_trace(trace_id)
        span = tracer.start_span("agent_loop.run", message=user_message[:100])

        self.memory.record_interaction(user_message, "")
        metrics.counter("total_requests").add()

        if self.use_compression:
            memory_ctx = self.memory.get_memory_context()
            user_message = self.prompt_optimizer.optimize(user_message, memory_ctx)

        if self.use_function_calling:
            plan = self._think_llm(user_message)
        else:
            plan = self._think_keyword(user_message)

        current_message = user_message
        iterations = 0

        while plan.get("tools") and iterations < self.max_iterations:
            tool_results = self._execute_tools_parallel(plan["tools"])

            if self.use_self_reflection:
                reflection = self._reflect_on_result(current_message, tool_results)
                if not reflection.is_sufficient and reflection.next_steps:
                    plan = {"tools": reflection.next_steps}
                    current_message = self._build_context(current_message, tool_results)
                    iterations += 1
                    continue
                else:
                    current_message = self._build_context(current_message, tool_results)
                    break
            else:
                current_message = self._build_context(current_message, tool_results)
                if self.use_function_calling:
                    follow_up = self._think_llm(current_message)
                    if not follow_up.get("tools"):
                        break
                    plan = follow_up
                iterations += 1

        enhanced_message = current_message

        memory_ctx = self.memory.get_memory_context()
        if memory_ctx:
            enhanced_message = (
                f"[相关记忆]\n{memory_ctx}\n\n[当前消息]\n{enhanced_message}"
            )

        if self.context_manager.is_overflow(self.ai.history):
            enhanced_message = self.summarizer.rolling_summary(
                self.ai.history, enhanced_message
            )
            self.ai.history = self.context_manager.truncate_messages(
                self.ai.history, preserve_system=True
            )

        if self.use_cache:
            cached = self.cache_loop.check_cache(self.ai.history)
            if cached:
                self.cost_tracker.record_request(
                    self.ai.model, enhanced_message,
                    cached["result"],
                    cache_hit_tokens=count_tokens(enhanced_message) // 3,
                )
                metrics.counter("cache_hits").add()
                reply = cached["result"]
                self.memory.record_interaction(user_message, reply)
                self._learn(user_message, reply)
                tracer.end_span(span, success=True, cached=True)
                return reply

        reply = self.ai.chat(enhanced_message)
        self.memory.record_interaction(user_message, reply)

        if self.use_cache:
            self.cache_loop.update_cache(self.ai.history, {"result": reply})

        self.cost_tracker.record_request(self.ai.model, enhanced_message, reply)
        self._learn(user_message, reply)

        tracer.end_span(span, success=True)
        metrics.histogram("request_duration_ms").record(span.duration_ms)
        tracer.export()

        return reply

    def run_stream(self, user_message: str) -> Generator[str, None, None]:
        """流式输出版本的 ReAct 循环 - 带进度报告和容错"""
        tracer = get_tracer()
        metrics = get_metrics()
        trace_id = f"stream-{int(time.time() * 1000)}"
        tracer.start_trace(trace_id)
        span = tracer.start_span("agent_loop.run_stream", message=user_message[:100])
        metrics.counter("total_requests").add()

        self.memory.record_interaction(user_message, "")

        if self.use_compression:
            memory_ctx = self.memory.get_memory_context()
            user_message = self.prompt_optimizer.optimize(user_message, memory_ctx)

        if self.use_function_calling:
            plan = self._think_llm(user_message)
        else:
            plan = self._think_keyword(user_message)

        current_message = user_message
        iterations = 0

        while plan.get("tools") and iterations < self.max_iterations:
            tool_count = len(plan["tools"])
            yield f"\n🔧 正在调用 {tool_count} 个工具...\n"

            tool_results = self._execute_tools_parallel(plan["tools"])

            for i, result in enumerate(tool_results):
                if result and result.success:
                    yield f"  ✅ 工具 {i+1}: {result.content[:100]}...\n"
                else:
                    yield f"  ❌ 工具 {i+1}: {result.error if result else '失败'}\n"

            if self.use_self_reflection:
                yield "🔍 正在反思结果...\n"
                reflection = self._reflect_on_result(current_message, tool_results)
                if not reflection.is_sufficient and reflection.next_steps:
                    plan = {"tools": reflection.next_steps}
                    current_message = self._build_context(current_message, tool_results)
                    iterations += 1
                    continue
                else:
                    current_message = self._build_context(current_message, tool_results)
                    break
            else:
                current_message = self._build_context(current_message, tool_results)
                if self.use_function_calling:
                    follow_up = self._think_llm(current_message)
                    if not follow_up.get("tools"):
                        break
                    plan = follow_up
                iterations += 1

        enhanced_message = current_message

        memory_ctx = self.memory.get_memory_context()
        if memory_ctx:
            enhanced_message = (
                f"[相关记忆]\n{memory_ctx}\n\n[当前消息]\n{enhanced_message}"
            )

        if self.context_manager.is_overflow(self.ai.history):
            yield "📝 上下文过长，正在生成摘要...\n"
            enhanced_message = self.summarizer.rolling_summary(
                self.ai.history, enhanced_message
            )
            self.ai.history = self.context_manager.truncate_messages(
                self.ai.history, preserve_system=True
            )

        if self.use_cache:
            cached = self.cache_loop.check_cache(self.ai.history)
            if cached:
                self.cost_tracker.record_request(
                    self.ai.model, enhanced_message,
                    cached["result"],
                    cache_hit_tokens=count_tokens(enhanced_message) // 3,
                )
                metrics.counter("cache_hits").add()
                reply = cached["result"]
                self.memory.record_interaction(user_message, reply)
                self._learn(user_message, reply)
                tracer.end_span(span, success=True, cached=True)
                yield reply
                return

        full_reply = ""
        try:
            for chunk in self.ai.chat_stream(enhanced_message):
                full_reply += chunk
                yield chunk
        except Exception as e:
            metrics.counter("stream_errors").add()
            tracer.add_event("stream_error", error=str(e))
            yield f"\n❌ 流式响应出错: {e}\n"
            if full_reply:
                yield full_reply
            return

        self.memory.record_interaction(user_message, full_reply)

        if self.use_cache:
            self.cache_loop.update_cache(self.ai.history, {"result": full_reply})

        self.cost_tracker.record_request(self.ai.model, enhanced_message, full_reply)
        self._learn(user_message, full_reply)

        tracer.end_span(span, success=True)
        metrics.histogram("request_duration_ms").record(span.duration_ms)
        tracer.export()

    def get_cache_stats(self) -> Dict[str, Any]:
        return self.cache_loop.get_cache_stats()

    def get_cost_stats(self) -> Dict[str, Any]:
        return self.cost_tracker.get_stats()

    def get_compression_stats(self) -> Dict[str, Any]:
        return self.prompt_optimizer.get_stats()

    def get_resilience_stats(self) -> Dict[str, Any]:
        cb = self.resilience.circuit_breaker
        return {
            "circuit_state": cb.state,
            "failure_count": cb.failure_count,
            "failure_threshold": cb.failure_threshold,
            "recovery_timeout": cb.recovery_timeout,
        }

    def toggle_cache(self, enabled: Optional[bool] = None) -> bool:
        if enabled is not None:
            self.use_cache = enabled
        else:
            self.use_cache = not self.use_cache
        return self.use_cache

    def toggle_compression(self, enabled: Optional[bool] = None) -> bool:
        if enabled is not None:
            self.use_compression = enabled
        else:
            self.use_compression = not self.use_compression
        return self.use_compression

    def toggle_function_calling(self, enabled: Optional[bool] = None) -> bool:
        if enabled is not None:
            self.use_function_calling = enabled
        else:
            self.use_function_calling = not self.use_function_calling
        return self.use_function_calling

    def toggle_self_reflection(self, enabled: Optional[bool] = None) -> bool:
        if enabled is not None:
            self.use_self_reflection = enabled
        else:
            self.use_self_reflection = not self.use_self_reflection
        return self.use_self_reflection