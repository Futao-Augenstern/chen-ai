import json
import logging
import sys
from pathlib import Path
from typing import Optional

from ai_core import AIChat
from memory import MemorySystem
from skills import SkillManager
from tools import ToolRegistry
from agent_loop import AgentLoop
from hooks import hook_system
from mcp_server import MCPManager

LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
)
logger = logging.getLogger("ai_agent")

try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich.markdown import Markdown
    from rich import print as rprint
    from rich.status import Status

    console = Console()
    RICH = True
except ImportError:
    RICH = False
    logger.warning("rich 未安装，使用纯文本输出。pip install rich 获取彩色界面")


def _print_panel(title: str, content: str, style: str = "bold cyan") -> None:
    if RICH:
        console.print(Panel(content, title=title, style=style))
    else:
        print(f"\n{title}\n{'=' * 40}\n{content}\n{'=' * 40}")


def _print_table(title: str, headers: list, rows: list) -> None:
    if RICH:
        table = Table(title=title)
        for h in headers:
            table.add_column(h, style="cyan")
        for row in rows:
            table.add_row(*[str(c) for c in row])
        console.print(table)
    else:
        print(f"\n{title}")
        print(" | ".join(headers))
        for row in rows:
            print(" | ".join(str(c) for c in row))


def _print_status(text: str) -> None:
    if RICH:
        console.print(f"[bold green]✓[/bold green] {text}")
    else:
        print(f"✓ {text}")


def _safe_input(prompt: str) -> Optional[str]:
    try:
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        return None


def handle_command(
    cmd_name: str,
    arg: Optional[str],
    loop: AgentLoop,
    skills: SkillManager,
    memory: MemorySystem,
    mcp: MCPManager,
) -> None:
    if cmd_name == "/help":
        _print_panel(
            "帮助",
            "以下是可用命令：\n\n"
            "  /help             显示此帮助\n"
            "  /providers        查看可用服务商\n"
            "  /provider <名>    切换服务商\n"
            "  /model <名>        切换模型\n"
            "  /skills           查看技能列表\n"
            "  /skill <名>        切换技能\n"
            "  /uns              取消技能\n"
            "  /tools            查看工具\n"
            "  /memory           查看记忆\n"
            "  /save             保存会话\n"
            "  /pref             查看偏好\n"
            "  /pref <K> <V>     设置偏好\n"
            "  /temp <值>         调节Temperature\n"
            "  /tokens <值>       设置Max Tokens\n"
            "  /cache            切换前缀缓存\n"
            "  /compress         切换Prompt压缩\n"
            "  /fc               切换Function Calling\n"
            "  /reflect          切换自我反思\n"
            "  /perf             查看性能统计\n"
            "  /metrics          查看遥测指标\n"
            "  /cost             查看成本统计\n"
            "  /mcp              列出MCP服务器\n"
            "  /mcp <名称>        启用/禁用MCP\n"
            "  /mcp-export       导出mcp.json\n"
            "  /clear            清空对话\n"
            "  /export           导出对话\n"
            "  /quit             退出",
        )

    elif cmd_name == "/providers":
        rows = [
            [p["name"], p.get("default_model", "")]
            for p in loop.ai.providers
        ]
        _print_table("可用服务商", ["名称", "默认模型"], rows)

    elif cmd_name == "/provider":
        if not arg:
            _print_status(f"当前服务商: {loop.ai.provider_name}")
            return
        try:
            loop.ai.set_provider(arg)
            _print_status(f"已切换到: {loop.ai.provider_name} (模型: {loop.ai.model})")
            logger.info(f"切换服务商: {arg}")
        except ValueError as e:
            print(f"错误: {e}")

    elif cmd_name == "/model":
        if not arg:
            _print_status(f"当前模型: {loop.ai.model}")
            models = loop.ai.get_models_for_provider(loop.ai.provider_name)
            if models:
                _print_panel("可用模型", ", ".join(models))
            return
        loop.ai.set_model(arg)
        _print_status(f"模型已切换: {loop.ai.model}")

    elif cmd_name == "/skills":
        rows = [
            [s.category, s.name, s.description[:40], str(s.usage_count)]
            for s in skills.list_skills()
        ]
        _print_table("技能列表", ["分类", "名称", "描述", "使用次数"], rows)

    elif cmd_name == "/skill":
        if not arg:
            if loop.active_skill:
                _print_status(f"当前技能: {loop.active_skill.name}")
            else:
                _print_status("未激活技能")
            return
        if loop.set_skill(arg, skills):
            _print_status(f"技能已激活: {arg}")
        else:
            print(f"未找到技能: {arg}")
            print("可用: " + ", ".join(s.name for s in skills.list_skills()))

    elif cmd_name == "/uns":
        if loop.active_skill:
            name = loop.active_skill.name
            loop.clear_skill(loop.ai.default_system_prompt)
            _print_status(f"已取消技能: {name}")
        else:
            _print_status("当前无激活技能")

    elif cmd_name == "/tools":
        rows = [
            [t["name"], t["description"]]
            for t in loop.tools.list_tools()
        ]
        _print_table("工具列表", ["名称", "描述"], rows)

    elif cmd_name == "/memory":
        stats = memory.get_stats()
        _print_panel(
            "记忆统计",
            f"工作记忆: {stats['working_messages']} 条\n"
            f"情景记忆: {stats['episodes']} 条\n"
            f"知识事实: {stats['facts']} 条\n"
            f"偏好设置: {stats['preferences']} 项",
        )

    elif cmd_name == "/save":
        memory.save_session(arg if arg else None)
        _print_status("会话已保存")

    elif cmd_name == "/pref":
        if not arg:
            prefs = memory.semantic.get_all_preferences()
            if prefs:
                rows = [[k, str(v)] for k, v in prefs.items()]
                _print_table("偏好设置", ["键", "值"], rows)
            else:
                _print_status("无偏好设置")
            return
        parts = arg.split(None, 1)
        if len(parts) >= 2:
            memory.learn_preference(parts[0], parts[1])
            _print_status(f"偏好已设置: {parts[0]} = {parts[1]}")
        else:
            val = memory.semantic.get_preference(arg)
            if val:
                _print_status(f"{arg} = {val}")
            else:
                _print_status(f"未找到: {arg}")

    elif cmd_name == "/temp":
        if arg:
            loop.ai.set_temperature(arg)
            _print_status(f"Temperature: {loop.ai.temperature}")

    elif cmd_name == "/tokens":
        if arg:
            loop.ai.set_max_tokens(arg)
            _print_status(f"Max Tokens: {loop.ai.max_tokens}")

    elif cmd_name == "/cache":
        state = loop.toggle_cache()
        _print_status(f"前缀缓存: {'开启' if state else '关闭'}")

    elif cmd_name == "/compress":
        state = loop.toggle_compression()
        _print_status(f"Prompt压缩: {'开启' if state else '关闭'}")

    elif cmd_name == "/fc":
        state = loop.toggle_function_calling()
        _print_status(f"Function Calling: {'开启' if state else '关闭'}")

    elif cmd_name == "/reflect":
        state = loop.toggle_self_reflection()
        _print_status(f"自我反思: {'开启' if state else '关闭'}")

    elif cmd_name == "/perf":
        cache = loop.get_cache_stats()
        cost = loop.get_cost_stats()
        comp = loop.get_compression_stats()
        _print_panel(
            "性能统计",
            f"缓存: 命中 {cache['hits']}/{cache['hits']+cache['misses']} "
            f"({cache['hit_rate']}) | 条目 {cache['entries']}\n"
            f"成本: 请求 {cost['requests']} 次 | "
            f"Token {cost['total_tokens']} | "
            f"费用 {cost['total_cost']} | "
            f"平均 {cost['avg_cost_per_request']}\n"
            f"压缩: 原 {comp['original_tokens']} | "
            f"压缩后 {comp['compressed_tokens']} | "
            f"节省 {comp['savings_rate']}",
        )

    elif cmd_name == "/metrics":
        from telemetry import get_metrics
        metrics = get_metrics()
        data = metrics.collect()
        resilience = loop.get_resilience_stats()
        _print_panel(
            "遥测指标",
            f"计数器: {json.dumps(data['counters'], ensure_ascii=False)}\n"
            f"直方图: {json.dumps(data['histograms'], ensure_ascii=False)}\n"
            f"仪表: {json.dumps(data['gauges'], ensure_ascii=False)}\n"
            f"断路器: {resilience['circuit_state']} "
            f"(失败 {resilience['failure_count']}/{resilience['failure_threshold']})",
        )

    elif cmd_name == "/cost":
        cost = loop.get_cost_stats()
        _print_panel(
            "成本统计",
            f"请求次数: {cost['requests']}\n"
            f"输入 Token: {cost['input_tokens']}\n"
            f"输出 Token: {cost['output_tokens']}\n"
            f"缓存命中 Token: {cost['cache_hit_tokens']}\n"
            f"总 Token: {cost['total_tokens']}\n"
            f"估计总成本: {cost['total_cost']}\n"
            f"平均每次: {cost['avg_cost_per_request']}",
        )

    elif cmd_name == "/mcp":
        if not arg:
            stats = mcp.get_stats()
            rows: list = []
            for s in mcp.list_servers():
                status = "✅" if s.enabled else "❌"
                rows.append([status, s.category, s.name, s.description[:50]])
            _print_panel(
                f"MCP 服务器 ({stats['enabled']}/{stats['total']} 启用)",
                "使用 /mcp <名称> 启用/禁用服务器",
            )
            _print_table("MCP列表", ["状态", "分类", "名称", "描述"], rows)
        else:
            server = mcp.get_server(arg)
            if server:
                if server.enabled:
                    mcp.disable(arg)
                    _print_status(f"已禁用: {arg}")
                else:
                    mcp.enable(arg)
                    _print_status(f"已启用: {arg}")
            else:
                print(f"未找到: {arg}")
                print("可用: " + ", ".join(s.name for s in mcp.list_servers()))

    elif cmd_name == "/mcp-export":
        path = mcp.export_config()
        _print_status(f"MCP配置已导出: {path}")

    elif cmd_name == "/export":
        text = loop.ai.export_history()
        export_path = Path("chat_export.txt")
        export_path.write_text(text, encoding="utf-8")
        _print_status(f"对话已导出: {export_path}")

    else:
        print(f"未知命令: {cmd_name}，输入 /help 查看帮助")


def main() -> None:
    if RICH:
        console.print(
            Panel.fit(
                "[bold cyan]AI 智能助手 v3.0[/bold cyan]\n"
                "[dim]融合 Reasonix + Claude Code + Codex + Hermes + OpenClaw[/dim]",
                border_style="cyan",
            )
        )
    else:
        print("=" * 60)
        print("  AI 智能助手 (命令行版)  v3.0")
        print("  融合 Reasonix + Claude Code + Codex + Hermes + OpenClaw")
        print("=" * 60)

    ai = AIChat()
    memory = MemorySystem()
    skills = SkillManager()
    tools = ToolRegistry()
    mcp = MCPManager()
    loop = AgentLoop(ai, memory, tools)

    logger.info(f"启动 - 服务商: {ai.provider_name}, 模型: {ai.model}")

    _print_status(f"服务商: {ai.provider_name} | 模型: {ai.model}")
    _print_status(f"Temperature: {ai.temperature} | Max Tokens: {ai.max_tokens}")
    _print_status(f"Function Calling: {'开启' if loop.use_function_calling else '关闭'}")
    _print_status(f"自我反思: {'开启' if loop.use_self_reflection else '关闭'}")
    _print_status("输入 /help 查看命令，输入消息开始对话")

    while True:
        try:
            user_input = _safe_input("\n> ")
            if user_input is None:
                break
            user_input = user_input.strip()
            if not user_input:
                continue

            if user_input.startswith("/"):
                parts = user_input.split(None, 1)
                cmd_name = parts[0]
                arg = parts[1] if len(parts) > 1 else None

                if cmd_name == "/quit":
                    logger.info("用户退出")
                    _print_status("再见！")
                    break
                elif cmd_name == "/clear":
                    loop.ai.clear_history()
                    _print_status("对话已清空")
                else:
                    handle_command(cmd_name, arg, loop, skills, memory, mcp)
                continue

            logger.info(f"用户消息: {user_input[:100]}")

            if RICH:
                reply = ""
                with Status("[cyan]思考中...[/cyan]", spinner="dots"):
                    for chunk in loop.run_stream(user_input):
                        reply += chunk
                console.print(
                    Panel(
                        user_input,
                        title="[bold]你[/bold]",
                        border_style="green",
                    )
                )
                console.print(
                    Panel(
                        Markdown(reply),
                        title="[bold]AI[/bold]",
                        border_style="blue",
                    )
                )
            else:
                print("\nAI: ", end="", flush=True)
                reply = ""
                for chunk in loop.run_stream(user_input):
                    print(chunk, end="", flush=True)
                    reply += chunk
                print()

            hook_system.trigger(
                "after_chat",
                user_message=user_input,
                ai_reply=reply,
            )

        except KeyboardInterrupt:
            print("\n")
            logger.info("用户中断")
        except Exception as e:
            logger.error(f"错误: {e}", exc_info=True)
            print(f"\n[错误] {e}")

    logger.info("程序退出")


if __name__ == "__main__":
    main()