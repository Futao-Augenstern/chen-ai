try:
    import gradio as gr
    GRADIO_AVAILABLE = True
except ImportError:
    GRADIO_AVAILABLE = False
    gr = None

from ai_core import AIChat
from memory import MemorySystem
from skills import SkillManager
from tools import ToolRegistry
from agent_loop import AgentLoop
from config import get_provider_names, get_provider_config
from mcp_server import MCPManager

ai = AIChat()
memory = MemorySystem()
skills = SkillManager()
tools = ToolRegistry()
mcp = MCPManager()
loop = AgentLoop(ai, memory, tools)
provider_names = get_provider_names()


def respond_stream(message, history):
    full_response = ""
    for chunk in loop.run_stream(message):
        full_response += chunk
        yield full_response


def switch_provider(provider_name):
    try:
        ai.set_provider(provider_name)
        config = get_provider_config(provider_name)
        model_list = config.get("models", []) if config else []
        default_model = config.get("default_model", "") if config else ""
        return (
            gr.update(choices=model_list, value=default_model),
            f"已切换到: {provider_name}",
        )
    except Exception as e:
        return gr.update(), f"切换失败: {e}"


def switch_model(model_name):
    ai.set_model(model_name)
    return f"模型已切换为: {model_name}"


def update_temperature(value):
    ai.set_temperature(value)
    return f"Temperature: {value}"


def update_max_tokens(value):
    ai.set_max_tokens(value)
    return f"Max Tokens: {value}"


def clear_chat():
    ai.clear_history()
    memory.clear_working()
    return []


def export_chat():
    content = ai.export_history()
    if not content.strip():
        return None
    return content


def activate_skill(skill_name):
    if skill_name == "无（默认助手）":
        loop.clear_skill(ai.default_system_prompt)
        return f"已恢复默认助手模式"
    if skills.get_skill(skill_name):
        if loop.set_skill(skill_name, skills):
            return f"技能已激活: {skill_name}"
    return f"激活失败: {skill_name}"


def get_memory_info():
    stats = memory.get_stats()
    prefs = memory.semantic.get_all_preferences()
    pref_lines = "\n".join(f"- {k}: {v}" for k, v in prefs.items()) if prefs else "暂无偏好"
    episodes = memory.episodic.recent(5)
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


def get_performance_stats():
    cache = loop.get_cache_stats()
    cost = loop.get_cost_stats()
    compression = loop.get_compression_stats()

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


def toggle_cache(enabled):
    result = loop.toggle_cache(enabled)
    return result, f"前缀缓存: {'开启' if result else '关闭'}"


def toggle_compression(enabled):
    result = loop.toggle_compression(enabled)
    return result, f"Prompt压缩: {'开启' if result else '关闭'}"


def toggle_self_reflection(enabled):
    result = loop.toggle_self_reflection(enabled)
    return result, f"自我反思: {'开启' if result else '关闭'}"


def save_session(title):
    memory.save_session(title if title else None)
    return f"会话已保存: {title or '自动命名'}"


def refresh_skills():
    return [[s.category, s.name, s.description, s.usage_count] for s in skills.list_skills()]


with gr.Blocks(
    title="AI 智能助手 v3.0",
    theme=gr.themes.Soft(primary_hue="blue", secondary_hue="slate"),
    css="""
    .panel { padding: 10px; background: var(--background-fill-secondary); border-radius: 8px; margin-bottom: 10px; }
    .perf-box { background: #f0f4f8; padding: 8px; border-radius: 6px; }
    """,
) as demo:
    gr.Markdown("# 🤖 AI 智能助手 v3.0")
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
                        value=ai.provider_name,
                        interactive=True,
                    )
                with gr.Column(scale=2):
                    current_models = get_provider_config(ai.provider_name)
                    model_choices = current_models.get("models", []) if current_models else []
                    model_dropdown = gr.Dropdown(
                        label="模型",
                        choices=model_choices,
                        value=ai.model,
                        interactive=True,
                    )
                with gr.Column(scale=1):
                    temperature_slider = gr.Slider(
                        label="Temperature",
                        minimum=0.0,
                        maximum=2.0,
                        value=ai.temperature,
                        step=0.1,
                    )
                with gr.Column(scale=1):
                    max_tokens_input = gr.Number(
                        label="Max Tokens",
                        value=ai.max_tokens,
                        minimum=1,
                        maximum=128000,
                        step=256,
                    )

            with gr.Row(elem_classes="panel"):
                with gr.Column(scale=3):
                    skill_names = ["无（默认助手）"] + [s.name for s in skills.list_skills()]
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
                        value=loop.use_cache,
                        interactive=True,
                    )
                with gr.Column():
                    compress_checkbox = gr.Checkbox(
                        label="启用Prompt压缩 (Caveman/Headroom)",
                        value=loop.use_compression,
                        interactive=True,
                    )
                with gr.Column():
                    reflect_checkbox = gr.Checkbox(
                        label="启用自我反思 (OpenManus/Manus)",
                        value=loop.use_self_reflection,
                        interactive=True,
                    )
            cache_status = gr.Textbox(label="优化状态", interactive=False, max_lines=1)
            cache_checkbox.change(toggle_cache, [cache_checkbox], [cache_checkbox, cache_status])
            compress_checkbox.change(toggle_compression, [compress_checkbox], [compress_checkbox, cache_status])
            reflect_checkbox.change(toggle_self_reflection, [reflect_checkbox], [reflect_checkbox, cache_status])

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
                inputs=[msg, chatbot],
                outputs=[chatbot],
            ).then(lambda: "", None, [msg])

            msg.submit(
                respond_stream,
                inputs=[msg, chatbot],
                outputs=[chatbot],
            ).then(lambda: "", None, [msg])

            provider_dropdown.change(
                switch_provider,
                inputs=[provider_dropdown],
                outputs=[model_dropdown, status],
            )

            model_dropdown.change(
                switch_model,
                inputs=[model_dropdown],
                outputs=[status],
            )

            temperature_slider.change(
                update_temperature,
                inputs=[temperature_slider],
                outputs=[status],
            )

            max_tokens_input.change(
                update_max_tokens,
                inputs=[max_tokens_input],
                outputs=[status],
            )

            skill_dropdown.change(
                activate_skill,
                inputs=[skill_dropdown],
                outputs=[skill_status],
            )

            clear_btn.click(clear_chat, None, [chatbot])
            export_btn.click(export_chat, None, [export_file])

        with gr.TabItem("🧠 记忆管理"):
            gr.Markdown("### 三层记忆系统 (OpenClaw + Hermes)")
            gr.Markdown("**工作记忆**（当前会话） + **情节记忆**（历史会话） + **语义记忆**（偏好知识）")

            refresh_btn = gr.Button("刷新记忆", variant="secondary")
            mem_stats = gr.Textbox(label="记忆统计", interactive=False, max_lines=1)
            mem_prefs = gr.Textbox(label="偏好设置", interactive=False, max_lines=10)
            mem_episodes = gr.Textbox(label="最近会话", interactive=False, max_lines=10)

            refresh_btn.click(
                get_memory_info,
                None,
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
            save_btn.click(save_session, [save_title], [save_result])

        with gr.TabItem("🛠️ 技能 & 工具"):
            with gr.Row():
                with gr.Column(scale=2):
                    gr.Markdown("### 可用技能")
                    gr.Markdown("GitHub 热门技能已预装：Superpowers、Taste、Caveman 等")
                    refresh_skills_btn = gr.Button("刷新", variant="secondary", size="sm")
                    skill_list = gr.Dataframe(
                        headers=["分类", "名称", "描述", "使用次数"],
                        value=[
                            [s.category, s.name, s.description, s.usage_count]
                            for s in skills.list_skills()
                        ],
                        interactive=False,
                    )
                    refresh_skills_btn.click(refresh_skills, outputs=[skill_list])

                with gr.Column(scale=1):
                    gr.Markdown("### 可用工具")
                    tool_list = gr.Dataframe(
                        headers=["工具名", "描述"],
                        value=[
                            [t["name"], t["description"]]
                            for t in tools.list_tools()
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
                outputs=[cache_text, cost_text, comp_text],
            )

        with gr.TabItem("🔌 MCP 服务器"):
            gr.Markdown("### MCP (Model Context Protocol) 服务器管理")
            gr.Markdown(
                "MCP 让 AI 能访问外部工具和数据源。参考 Claude Code/Cursor 生态。\n\n"
                "**预设 20 个热门 MCP Server**，覆盖源码管理、搜索、数据库、前端、部署等。"
            )

            def get_mcp_list():
                rows = []
                for s in mcp.list_servers():
                    rows.append([
                        s.category, s.name, s.description[:50],
                        "✅" if s.enabled else "❌",
                        s.command,
                    ])
                return rows

            def get_mcp_stats():
                stats = mcp.get_stats()
                return f"总计: {stats['total']} 个  |  已启用: {stats['enabled']} 个  |  分类: {stats['categories']} 类"

            def toggle_mcp(name):
                server = mcp.get_server(name)
                if server:
                    if server.enabled:
                        mcp.disable(name)
                    else:
                        mcp.enable(name)
                return get_mcp_list(), get_mcp_stats()

            mcp_stats = gr.Textbox(
                label="MCP 统计",
                value=get_mcp_stats(),
                interactive=False,
                max_lines=1,
            )
            refresh_mcp_btn = gr.Button("刷新", variant="secondary", size="sm")
            mcp_list = gr.Dataframe(
                headers=["分类", "名称", "描述", "状态", "命令"],
                value=get_mcp_list(),
                interactive=False,
                row_count=(20, "dynamic"),
            )

            with gr.Row():
                mcp_name_input = gr.Dropdown(
                    label="选择 MCP Server",
                    choices=[s.name for s in mcp.list_servers()],
                    interactive=True,
                )
                toggle_btn = gr.Button("启用/禁用", variant="primary")
                export_btn = gr.Button("导出 mcp.json", variant="secondary")

            mcp_result = gr.Textbox(label="操作结果", interactive=False, max_lines=1)

            toggle_btn.click(
                lambda name: toggle_mcp(name),
                [mcp_name_input],
                [mcp_list, mcp_stats],
            ).then(
                lambda: "操作成功",
                outputs=[mcp_result],
            )

            export_btn.click(
                lambda: f"配置已导出到: {mcp.export_config()}",
                outputs=[mcp_result],
            )

            refresh_mcp_btn.click(
                get_mcp_list, outputs=[mcp_list]
            ).then(get_mcp_stats, outputs=[mcp_stats])

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)