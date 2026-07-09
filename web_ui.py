try:
    import gradio as gr
    GRADIO_AVAILABLE = True
except ImportError:
    GRADIO_AVAILABLE = False
    gr = None

import traceback
import tempfile
import os
from ai_core import AIChat
from memory import MemorySystem
from skills import SkillManager
from tools import ToolRegistry
from agent_loop import AgentLoop
from config import get_provider_names, get_provider_config
from mcp_server import MCPManager
from typing import Any, Dict, Generator, List, Optional, Tuple


class SessionState:
    """Session-level state for Gradio to avoid multi-user concurrency issues"""
    def __init__(self):
        self.ai: AIChat = AIChat()
        self.memory: MemorySystem = MemorySystem()
        self.skills: SkillManager = SkillManager()
        self.tools: ToolRegistry = ToolRegistry()
        self.mcp: MCPManager = MCPManager()
        self.loop: AgentLoop = AgentLoop(self.ai, self.memory, self.tools)


def respond_stream(
    message: str,
    history: List[Dict[str, Any]],
    state: SessionState
) -> Generator[List[Dict[str, Any]], None, None]:
    full_response = ""
    try:
        for chunk in state.loop.run_stream(message):
            full_response += chunk
            # Build messages in Gradio format
            messages = []
            # Add history
            for msg in history:
                messages.append(msg)
            # Add current message
            messages.append({"role": "user", "content": message})
            messages.append({"role": "assistant", "content": full_response})
            yield messages
    except Exception as e:
        error_msg = f"❌ 发生错误: {str(e)}"
        print(f"[ERROR] respond_stream exception:\n{traceback.format_exc()}")
        messages = []
        for msg in history:
            messages.append(msg)
        messages.append({"role": "user", "content": message})
        messages.append({"role": "assistant", "content": error_msg})
        yield messages
        raise gr.Error(error_msg)


def switch_provider(
    provider_name: str,
    state: SessionState
) -> Tuple[gr.update, str]:
    try:
        state.ai.set_provider(provider_name)
        config = get_provider_config(provider_name)
        model_list = config.get("models", []) if config else []
        default_model = config.get("default_model", "") if config else ""
        return (
            gr.update(choices=model_list, value=default_model),
            f"已切换到: {provider_name}",
        )
    except Exception as e:
        error_msg = f"切换失败: {e}"
        print(f"[ERROR] switch_provider exception:\n{traceback.format_exc()}")
        raise gr.Error(error_msg)


def switch_model(
    model_name: str,
    state: SessionState
) -> str:
    try:
        state.ai.set_model(model_name)
        return f"模型已切换为: {model_name}"
    except Exception as e:
        error_msg = f"切换模型失败: {e}"
        print(f"[ERROR] switch_model exception:\n{traceback.format_exc()}")
        raise gr.Error(error_msg)


def update_temperature(
    value: float,
    state: SessionState
) -> str:
    try:
        state.ai.set_temperature(value)
        return f"Temperature: {value}"
    except Exception as e:
        error_msg = f"更新 temperature 失败: {e}"
        print(f"[ERROR] update_temperature exception:\n{traceback.format_exc()}")
        raise gr.Error(error_msg)


def update_max_tokens(
    value: int,
    state: SessionState
) -> str:
    try:
        state.ai.set_max_tokens(value)
        return f"Max Tokens: {value}"
    except Exception as e:
        error_msg = f"更新 max tokens 失败: {e}"
        print(f"[ERROR] update_max_tokens exception:\n{traceback.format_exc()}")
        raise gr.Error(error_msg)


def clear_chat(
    state: SessionState
) -> List[Any]:
    try:
        state.ai.clear_history()
        state.memory.clear_working()
        return []
    except Exception as e:
        error_msg = f"清空对话失败: {e}"
        print(f"[ERROR] clear_chat exception:\n{traceback.format_exc()}")
        raise gr.Error(error_msg)


def export_chat(
    state: SessionState
) -> Optional[str]:
    """Export chat history with 10000 message limit"""
    try:
        content = state.ai.export_history()
        if not content.strip():
            return None

        # Count messages (each line starts with "你:" or "AI:")
        lines = content.splitlines()
        message_count = sum(1 for line in lines if line.startswith("你:") or line.startswith("AI:"))

        # If more than 10000 messages, only keep the last 10000
        if message_count > 10000:
            truncated_lines = []
            messages_found = 0
            for line in reversed(lines):
                truncated_lines.insert(0, line)
                if line.startswith("你:") or line.startswith("AI:"):
                    messages_found += 1
                    if messages_found >= 10000:
                        break
            content = "\n".join(truncated_lines)
            content = f"[注意：聊天记录过长，仅导出最近 10000 条消息]\n\n{content}"

        # Write to temp file for gr.File download
        fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="chat_export_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            os.unlink(tmp_path)
            raise
        return tmp_path
    except Exception as e:
        error_msg = f"导出对话失败: {e}"
        print(f"[ERROR] export_chat exception:\n{traceback.format_exc()}")
        raise gr.Error(error_msg)


def activate_skill(
    skill_name: str,
    state: SessionState
) -> str:
    try:
        if skill_name == "无（默认助手）":
            state.loop.clear_skill(state.ai.default_system_prompt)
            return f"已恢复默认助手模式"
        if state.skills.get_skill(skill_name):
            if state.loop.set_skill(skill_name, state.skills):
                return f"技能已激活: {skill_name}"
        return f"激活失败: {skill_name}"
    except Exception as e:
        error_msg = f"激活技能失败: {e}"
        print(f"[ERROR] activate_skill exception:\n{traceback.format_exc()}")
        raise gr.Error(error_msg)


def get_memory_info(
    state: SessionState
) -> Tuple[str, str, str]:
    try:
        stats = state.memory.get_stats()
        prefs = state.memory.semantic.get_all_preferences()
        pref_lines = "\n".join(f"- {k}: {v}" for k, v in prefs.items()) if prefs else "暂无偏好"
        episodes = state.memory.episodic.recent(5)
        epi_lines = "\n".join(
            f"- [{ep['time'][:16]}] {ep['title']}" for ep in episodes
        ) if episodes else "暂无历史会话"
        return (
            f"工作记忆: {stats['working_messages']} 条  |  "
            f"历史会话: {stats['episodes']} 个  |  "
            f"偏好: {stats['preferences']} 项",
            pref_lines,
            epi_lines,
        )
    except Exception as e:
        error_msg = f"获取记忆信息失败: {e}"
        print(f"[ERROR] get_memory_info exception:\n{traceback.format_exc()}")
        raise gr.Error(error_msg)


def get_performance_stats(
    state: SessionState
) -> Tuple[str, str, str]:
    try:
        cache = state.loop.get_cache_stats()
        cost = state.loop.get_cost_stats()
        compression = state.loop.get_compression_stats()

        cache_str = (
            f"缓存命中: {cache['hits']} / {cache['hits'] + cache['misses']}\n"
            f"命中率: {cache['hit_rate']}\n"
            f"缓存条目: {cache['entries']}"
        )
        cost_str = (
            f"请求数: {cost['requests']}\n"
            f"总 Token: {cost['total_tokens']}\n"
            f"缓存命中 Token: {cost['cache_hit_tokens']}\n"
            f"估计成本: {cost['total_cost']}\n"
            f"平均请求成本: {cost['avg_cost_per_request']}"
        )
        comp_str = (
            f"原 Token: {compression['original_tokens']}\n"
            f"压缩后: {compression['compressed_tokens']}\n"
            f"节省: {compression['savings']} ({compression['savings_rate']})"
        )
        return cache_str, cost_str, comp_str
    except Exception as e:
        error_msg = f"获取性能统计失败: {e}"
        print(f"[ERROR] get_performance_stats exception:\n{traceback.format_exc()}")
        raise gr.Error(error_msg)


def toggle_cache(
    enabled: bool,
    state: SessionState
) -> Tuple[bool, str]:
    try:
        result = state.loop.toggle_cache(enabled)
        return result, f"前缀缓存: {'开启' if result else '关闭'}"
    except Exception as e:
        error_msg = f"切换缓存状态失败: {e}"
        print(f"[ERROR] toggle_cache exception:\n{traceback.format_exc()}")
        raise gr.Error(error_msg)


def toggle_compression(
    enabled: bool,
    state: SessionState
) -> Tuple[bool, str]:
    try:
        result = state.loop.toggle_compression(enabled)
        return result, f"Prompt压缩: {'开启' if result else '关闭'}"
    except Exception as e:
        error_msg = f"切换压缩状态失败: {e}"
        print(f"[ERROR] toggle_compression exception:\n{traceback.format_exc()}")
        raise gr.Error(error_msg)


def toggle_self_reflection(
    enabled: bool,
    state: SessionState
) -> Tuple[bool, str]:
    try:
        result = state.loop.toggle_self_reflection(enabled)
        return result, f"自我反思: {'开启' if result else '关闭'}"
    except Exception as e:
        error_msg = f"切换自我反思状态失败: {e}"
        print(f"[ERROR] toggle_self_reflection exception:\n{traceback.format_exc()}")
        raise gr.Error(error_msg)


def save_session(
    title: str,
    state: SessionState
) -> str:
    try:
        state.memory.save_session(title if title else None)
        return f"会话已保存: {title or '自动命名'}"
    except Exception as e:
        error_msg = f"保存会话失败: {e}"
        print(f"[ERROR] save_session exception:\n{traceback.format_exc()}")
        raise gr.Error(error_msg)


def refresh_skills(
    state: SessionState
) -> List[List[Any]]:
    try:
        return [[s2.category, s2.name, s2.description, s2.usage_count] for s2 in state.skills.list_skills()]
    except Exception as e:
        error_msg = f"刷新技能列表失败: {e}"
        print(f"[ERROR] refresh_skills exception:\n{traceback.format_exc()}")
        raise gr.Error(error_msg)


def _get_mcp_list(state: SessionState) -> List[List[Any]]:
    """Helper for MCP server list display"""
    rows: List[List[Any]] = []
    for srv in state.mcp.list_servers():
        rows.append([
            srv.category, srv.name, srv.description[:50],
            "✅" if srv.enabled else "❌",
            srv.command,
        ])
    return rows


def _get_mcp_stats(state: SessionState) -> str:
    """Helper for MCP stats display"""
    stats = state.mcp.get_stats()
    return f"总计: {stats['total']} 个  |  已启用: {stats['enabled']} 个  |  分类: {stats['categories']} 类"


def toggle_mcp(
    name: str,
    state: SessionState,
    confirm: bool
) -> Tuple[List[List[Any]], str, str, bool]:
    """Toggle MCP server with confirmation step.
    If confirm=False, returns a confirmation prompt.
    If confirm=True, executes the toggle.
    """
    try:
        if not confirm:
            server = state.mcp.get_server(name)
            if server is None:
                return (_get_mcp_list(state), _get_mcp_stats(state),
                        f"未找到 MCP Server: {name}", False)
            action = "禁用" if server.enabled else "启用"
            return (_get_mcp_list(state), _get_mcp_stats(state),
                    f"再次点击确认{action} MCP Server: {name}", True)
        # Confirmed - execute toggle
        server = state.mcp.get_server(name)
        if server is not None:
            if server.enabled:
                state.mcp.disable(name)
            else:
                state.mcp.enable(name)
        return (_get_mcp_list(state), _get_mcp_stats(state), "操作成功", False)
    except Exception as e:
        error_msg = f"MCP 操作失败: {e}"
        print(f"[ERROR] toggle_mcp exception:\n{traceback.format_exc()}")
        raise gr.Error(error_msg)


def export_mcp_config(
    state: SessionState
) -> str:
    """Export MCP configuration to JSON file"""
    try:
        return f"配置已导出到: {state.mcp.export_config()}"
    except Exception as e:
        error_msg = f"导出 MCP 配置失败: {e}"
        print(f"[ERROR] export_mcp_config exception:\n{traceback.format_exc()}")
        raise gr.Error(error_msg)


def create_ui() -> gr.Blocks:
    """Create the Gradio UI with session-scoped state to avoid multi-user concurrency issues."""
    with gr.Blocks(
        title="AI 智能助手 v1.0.2",
        theme=gr.themes.Soft(primary_hue="blue", secondary_hue="slate"),
        css="""
        .panel { padding: 10px; background: var(--background-fill-secondary); border-radius: 8px; margin-bottom: 10px; }
        .perf-box { background: #f0f4f8; padding: 8px; border-radius: 6px; }
        """,
    ) as demo:
        # Session-scoped state - each user gets their own instance
        state = gr.State(SessionState())

        # Temporary state for UI construction defaults
        _init = SessionState()
        provider_names = get_provider_names()

        gr.Markdown("# 🤖 AI 智能助手 v1.0.2")
        gr.Markdown(
            "融合 **Reasonix** Cache-First + **Claude Code** 记忆 + **Codex** Agent Loop + "
            "**Hermes Agent** 技能系统 + **OpenClaw** 持久记忆"
        )

        with gr.Tabs():
            with gr.TabItem("💬 对话"):
                with gr.Row(elem_classes="panel"):
                    with gr.Column(scale=2):
                        provider_dropdown = gr.Dropdown(
                            label="服务商",
                            choices=provider_names,
                            value=_init.ai.provider_name,
                            interactive=True,
                        )
                    with gr.Column(scale=2):
                        current_models = get_provider_config(_init.ai.provider_name)
                        model_choices = current_models.get("models", []) if current_models else []
                        model_dropdown = gr.Dropdown(
                            label="模型",
                            choices=model_choices,
                            value=_init.ai.model,
                            interactive=True,
                        )
                    with gr.Column(scale=1):
                        temperature_slider = gr.Slider(
                            label="Temperature",
                            minimum=0.0,
                            maximum=2.0,
                            value=_init.ai.temperature,
                            step=0.1,
                        )
                    with gr.Column(scale=1):
                        max_tokens_input = gr.Number(
                            label="Max Tokens",
                            value=_init.ai.max_tokens,
                            minimum=1,
                            maximum=128000,
                            step=256,
                        )

                with gr.Row(elem_classes="panel"):
                    with gr.Column(scale=3):
                        skill_names = ["无（默认助手）"] + [sn.name for sn in _init.skills.list_skills()]
                        skill_dropdown = gr.Dropdown(
                            label="🎯 激活技能",
                            choices=skill_names,
                            value="无（默认助手）",
                            interactive=True,
                        )
                    with gr.Column(scale=1):
                        skill_status = gr.Textbox(
                            label="技能状态",
                            value="默认助手模式",
                            interactive=False,
                            max_lines=1,
                        )

                with gr.Row(elem_classes="panel"):
                    with gr.Column():
                        cache_checkbox = gr.Checkbox(
                            label="启用前缀缓存 (Reasonix Cache-First)",
                            value=_init.loop.use_cache,
                            interactive=True,
                        )
                    with gr.Column():
                        compress_checkbox = gr.Checkbox(
                            label="启用Prompt压缩 (Caveman/Headroom)",
                            value=_init.loop.use_compression,
                            interactive=True,
                        )
                    with gr.Column():
                        reflect_checkbox = gr.Checkbox(
                            label="启用自我反思 (OpenManus/Manus)",
                            value=_init.loop.use_self_reflection,
                            interactive=True,
                        )
                cache_status = gr.Textbox(label="缓存状态", interactive=False, max_lines=1)
                compress_status = gr.Textbox(label="压缩状态", interactive=False, max_lines=1)
                reflect_status = gr.Textbox(label="反思状态", interactive=False, max_lines=1)
                cache_checkbox.change(toggle_cache, [cache_checkbox, state], [cache_checkbox, cache_status])
                compress_checkbox.change(toggle_compression, [compress_checkbox, state], [compress_checkbox, compress_status])
                reflect_checkbox.change(toggle_self_reflection, [reflect_checkbox, state], [reflect_checkbox, reflect_status])

                status = gr.Textbox(label="状态", max_lines=1, interactive=False)

                chatbot = gr.Chatbot(
                    height=450,
                    placeholder="开始对话吧...  AI 会自动调用工具、检索记忆、建议技能",
                    type="messages",
                    show_copy_button=True,
                )

                with gr.Row():
                    msg = gr.Textbox(
                        label="输入消息",
                        placeholder="请输入你的问题...",
                        scale=4,
                        show_label=False,
                    )
                    send_btn = gr.Button("发送", variant="primary", scale=1)

                with gr.Row():
                    clear_btn = gr.Button("清空对话", size="sm", variant="secondary")
                    export_btn = gr.Button("导出对话", size="sm", variant="secondary")
                    export_file = gr.File(label="下载", visible=True)

                send_btn.click(
                    respond_stream,
                    inputs=[msg, chatbot, state],
                    outputs=[chatbot],
                ).then(lambda: "", None, [msg])

                msg.submit(
                    respond_stream,
                    inputs=[msg, chatbot, state],
                    outputs=[chatbot],
                ).then(lambda: "", None, [msg])

                provider_dropdown.change(
                    switch_provider,
                    inputs=[provider_dropdown, state],
                    outputs=[model_dropdown, status],
                )

                model_dropdown.change(
                    switch_model,
                    inputs=[model_dropdown, state],
                    outputs=[status],
                )

                temperature_slider.change(
                    update_temperature,
                    inputs=[temperature_slider, state],
                    outputs=[status],
                )

                max_tokens_input.change(
                    update_max_tokens,
                    inputs=[max_tokens_input, state],
                    outputs=[status],
                )

                skill_dropdown.change(
                    activate_skill,
                    inputs=[skill_dropdown, state],
                    outputs=[skill_status],
                )

                clear_btn.click(clear_chat, [state], [chatbot])
                export_btn.click(export_chat, [state], [export_file])

            with gr.TabItem("🧠 记忆管理"):
                gr.Markdown("### 三层记忆系统 (OpenClaw + Hermes)")
                gr.Markdown("**工作记忆**（当前会话） + **情节记忆**（历史会话） + **语义记忆**（偏好知识）")

                refresh_btn = gr.Button("刷新记忆", variant="secondary")
                mem_stats = gr.Textbox(label="记忆统计", interactive=False, max_lines=1)
                mem_prefs = gr.Textbox(label="偏好设置", interactive=False, max_lines=10)
                mem_episodes = gr.Textbox(label="最近会话", interactive=False, max_lines=10)

                refresh_btn.click(
                    get_memory_info,
                    [state],
                    [mem_stats, mem_prefs, mem_episodes],
                )

                with gr.Row():
                    save_title = gr.Textbox(
                        label="会话标题",
                        placeholder="给当前会话起个名字...",
                        scale=3,
                    )
                    save_btn = gr.Button("保存当前会话", scale=1, variant="primary")

                save_result = gr.Textbox(label="保存结果", interactive=False, max_lines=1)
                save_btn.click(save_session, [save_title, state], [save_result])

            with gr.TabItem("🛠️ 技能 & 工具"):
                with gr.Row():
                    with gr.Column(scale=2):
                        gr.Markdown("### 可用技能")
                        gr.Markdown("GitHub 热门技能已预装：Superpowers、Taste、Caveman 等")
                        refresh_skills_btn = gr.Button("刷新", variant="secondary", size="sm")
                        skill_list = gr.Dataframe(
                            headers=["分类", "名称", "描述", "使用次数"],
                            value=[
                                [sk.category, sk.name, sk.description, sk.usage_count]
                                for sk in _init.skills.list_skills()
                            ],
                            interactive=False,
                        )
                        refresh_skills_btn.click(refresh_skills, [state], [skill_list])

                    with gr.Column(scale=1):
                        gr.Markdown("### 可用工具")
                        tool_list = gr.Dataframe(
                            headers=["工具名", "描述"],
                            value=[
                                [t["name"], t["description"]]
                                for t in _init.tools.list_tools()
                            ],
                            interactive=False,
                        )

            with gr.TabItem("📊 性能统计"):
                gr.Markdown("### 缓存与成本优化 (Reasonix + Caveman + Headroom)")
                gr.Markdown(
                    "- **Reasonix Cache-First**：前缀缓存可以降低 80% API 成本  \n"
                    "- **Caveman Prompt 压缩**：精简冗余措辞，节省 Token  \n"
                    "- **Headroom 上下文压缩**：压缩长对话保留关键信息"
                )
                refresh_perf_btn = gr.Button("刷新统计", variant="primary")
                with gr.Row():
                    cache_text = gr.Textbox(
                        label="缓存统计",
                        interactive=False,
                        lines=4,
                        elem_classes="perf-box",
                    )
                    cost_text = gr.Textbox(
                        label="成本统计",
                        interactive=False,
                        lines=5,
                        elem_classes="perf-box",
                    )
                    comp_text = gr.Textbox(
                        label="压缩统计",
                        interactive=False,
                        lines=4,
                        elem_classes="perf-box",
                    )
                refresh_perf_btn.click(
                    get_performance_stats,
                    [state],
                    [cache_text, cost_text, comp_text],
                )

            with gr.TabItem("🔌 MCP 服务器"):
                gr.Markdown("### MCP (Model Context Protocol) 服务器管理")
                gr.Markdown(
                    "MCP 让 AI 能访问外部工具和数据源。参考 Claude Code/Cursor 生态。\n\n"
                    "**预设 20 个热门 MCP Server**，覆盖源码管理、搜索、数据库、前端、部署等。"
                )

                mcp_stats = gr.Textbox(
                    label="MCP 统计",
                    value=_get_mcp_stats(_init),
                    interactive=False,
                    max_lines=1,
                )
                refresh_mcp_btn = gr.Button("刷新", variant="secondary", size="sm")
                mcp_list = gr.Dataframe(
                    headers=["分类", "名称", "描述", "状态", "命令"],
                    value=_get_mcp_list(_init),
                    interactive=False,
                    row_count=(20, "dynamic"),
                )

                with gr.Row():
                    mcp_name_input = gr.Dropdown(
                        label="选择 MCP Server",
                        choices=[srv.name for srv in _init.mcp.list_servers()],
                        interactive=True,
                    )
                    toggle_btn = gr.Button("启用/禁用", variant="primary")
                    export_btn = gr.Button("导出 mcp.json", variant="secondary")

                mcp_result = gr.Textbox(label="操作结果", interactive=False, max_lines=1)
                mcp_confirm_state = gr.State(False)

                toggle_btn.click(
                    toggle_mcp,
                    inputs=[mcp_name_input, state, mcp_confirm_state],
                    outputs=[mcp_list, mcp_stats, mcp_result, mcp_confirm_state],
                )

                export_btn.click(
                    export_mcp_config,
                    [state],
                    [mcp_result],
                )

                refresh_mcp_btn.click(
                    fn=lambda s: _get_mcp_list(s),
                    inputs=[state],
                    outputs=[mcp_list],
                ).then(
                    fn=lambda s: _get_mcp_stats(s),
                    inputs=[state],
                    outputs=[mcp_stats],
                )

    return demo


if __name__ == "__main__":
    demo = create_ui()
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)


def start_web_server(ai, memory, skills, mcp, port: int = 7860, server_name: str = "127.0.0.1") -> None:
    """启动 Web UI 服务（供 main.py --web 调用）。

    Args:
        ai: AIChat 实例（预留，当前 create_ui 内部创建）。
        memory: MemorySystem 实例（预留）。
        skills: SkillManager 实例（预留）。
        mcp: MCPManager 实例（预留）。
        port: 监听端口，默认 7860。
        server_name: 监听地址，默认 127.0.0.1。
    """
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Web UI 启动: {server_name}:{port}")
    demo = create_ui()
    demo.launch(server_name=server_name, server_port=port, share=False)