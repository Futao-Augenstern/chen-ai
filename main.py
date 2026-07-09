import argparse
import atexit
import json
import logging
import sys
import traceback
from pathlib import Path
from typing import Optional

from ai_core import AIChat
from config import get_provider_summary
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


def cleanup(mcp: "MCPManager") -> None:
    """清理资源，停止所有 MCP 子进程"""
    try:
        mcp.stop_all()
        logger.info("MCP 子进程已全部停止")
    except Exception:
        logger.warning("清理 MCP 子进程时出错", exc_info=True)


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
        try:
            loop.ai.set_model(arg)
            _print_status(f"模型已切换: {loop.ai.model}")
        except ValueError as e:
            print(f"错误: {e}")
            logger.error(f"切换模型失败: {e}")
            traceback.print_exc()

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
        try:
            if loop.set_skill(arg, skills):
                _print_status(f"技能已激活: {arg}")
            else:
                print(f"未找到技能: {arg}")
                print("可用: " + ", ".join(s.name for s in skills.list_skills()))
        except (ValueError, AttributeError) as e:
            print(f"错误: {e}")
            logger.error(f"切换技能失败: {e}")
            traceback.print_exc()

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
        try:
            path = mcp.export_config()
            _print_status(f"MCP配置已导出: {path}")
        except (IOError, OSError, PermissionError) as e:
            print(f"导出MCP配置失败: {e}")
            logger.error(f"导出MCP配置失败: {e}")
            traceback.print_exc()

    elif cmd_name == "/export":
        try:
            text = loop.ai.export_history()
            export_path = Path("chat_export.txt")
            export_path.write_text(text, encoding="utf-8")
            _print_status(f"对话已导出: {export_path}")
        except (IOError, OSError, PermissionError) as e:
            print(f"导出对话失败: {e}")
            logger.error(f"导出对话失败: {e}")
            traceback.print_exc()

    else:
        print(f"未知命令: {cmd_name}，输入 /help 查看帮助")


def main() -> None:
    parser = argparse.ArgumentParser(description="AI 智能助手命令行界面")
    parser.add_argument("--provider", "-p", help="指定 AI 服务商名称")
    parser.add_argument("--model", "-m", help="指定模型名称")
    parser.add_argument("--web", "-w", action="store_true", help="启动 Web UI 模式")
    parser.add_argument("--port", type=int, default=7860, help="Web UI 端口号 (默认: 7860)")
    parser.add_argument("--version", "-V", action="store_true", help="显示版本号后退出")
    parser.add_argument("--no-stream", action="store_true", help="禁用流式输出")
    parser.add_argument("--config", help="指定配置文件路径")
    parser.add_argument("--skills", action="store_true", help="列出所有可用技能后退出")
    parser.add_argument("--mcp", action="store_true", help="列出所有 MCP Server 后退出")
    args = parser.parse_args()

    # 端口范围验证
    if args.port and not (1 <= args.port <= 65535):
        print(f"错误: 端口号必须在 1-65535 之间，当前值: {args.port}")
        sys.exit(1)

    # --version: 显示版本号后退出
    if args.version:
        from __init__ import __version__
        print(f"chen-ai v{__version__}")
        sys.exit(0)

    if RICH:
        console.print(
            Panel.fit(
                "[bold cyan]AI 智能助手 v1.0.2[/bold cyan]\n"
                "[dim]融合 Reasonix + Claude Code + Codex + Hermes + OpenClaw[/dim]",
                border_style="cyan",
            )
        )
    else:
        print("=" * 60)
        print("  AI 智能助手 (命令行版)  v1.0.2")
        print("  融合 Reasonix + Claude Code + Codex + Hermes + OpenClaw")
        print("=" * 60)

    ai = AIChat()

    # 提供商配置摘要（一条信息替代刷屏警告）
    summary = get_provider_summary()
    if summary["configured"] == 0:
        _print_status(
            "提示: 未检测到任何 API Key。请复制 .env.example 为 .env 并填入 Key"
        )
    else:
        _print_status(
            f"已配置 API Key: {', '.join(summary['configured_names'])}"
            f" (共 {summary['configured']}/{summary['total']} 个服务商)"
        )

    memory = MemorySystem()
    skills = SkillManager()
    tools = ToolRegistry()
    mcp = MCPManager()
    loop = AgentLoop(ai, memory, tools)

    # 注册清理函数
    atexit.register(cleanup, mcp=mcp)

    # 处理配置文件加载
    if args.config:
        try:
            config_path = Path(args.config)
            if not config_path.exists():
                raise FileNotFoundError(f"配置文件不存在: {args.config}")
            config_data = json.loads(config_path.read_text(encoding="utf-8"))
            if "provider" in config_data:
                ai.set_provider(config_data["provider"])
            if "model" in config_data:
                ai.set_model(config_data["model"])
            logger.info(f"已加载配置文件: {args.config}")
            _print_status(f"已加载配置文件: {args.config}")
        except FileNotFoundError as e:
            logger.error(str(e))
            print(f"错误: {e}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            logger.error(f"配置文件 JSON 解析错误: {e}")
            print(f"配置文件 JSON 解析错误: {e}")
            traceback.print_exc()
            sys.exit(1)
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}", exc_info=True)
            print(f"加载配置文件失败: {e}")
            traceback.print_exc()
            sys.exit(1)

    # 处理命令行参数
    if args.provider:
        try:
            ai.set_provider(args.provider)
            logger.info(f"命令行指定服务商: {args.provider}")
        except ValueError as e:
            print(f"错误: {e}")
            sys.exit(1)

    if args.model:
        try:
            ai.set_model(args.model)
            logger.info(f"命令行指定模型: {args.model}")
        except ValueError as e:
            print(f"错误: {e}")
            sys.exit(1)

    if args.no_stream:
        logger.info("流式输出已禁用")

    # --skills: 列出技能后退出
    if args.skills:
        rows = [
            [s.category, s.name, s.description[:40], str(s.usage_count)]
            for s in skills.list_skills()
        ]
        _print_table("可用技能列表", ["分类", "名称", "描述", "使用次数"], rows)
        sys.exit(0)

    # --mcp: 列出 MCP Server 后退出
    if args.mcp:
        stats = mcp.get_stats()
        rows: list = []
        for s in mcp.list_servers():
            status = "✅" if s.enabled else "❌"
            rows.append([status, s.category, s.name, s.description[:50]])
        print(f"MCP 服务器 ({stats['enabled']}/{stats['total']} 启用)")
        _print_table("MCP 列表", ["状态", "分类", "名称", "描述"], rows)
        sys.exit(0)

    # --web: 启动 Web UI（占位，保持兼容）
    if args.web:
        logger.info(f"Web UI 模式启动，端口: {args.port}")
        try:
            from web_ui import start_web_server
            start_web_server(ai, memory, skills, mcp, port=args.port)
        except ImportError:
            print("错误: web_ui 模块未找到，请检查安装")
            logger.error("web_ui 模块导入失败")
            sys.exit(1)
        except Exception as e:
            logger.error(f"启动 Web UI 失败: {e}", exc_info=True)
            print(f"启动 Web UI 失败: {e}")
            traceback.print_exc()
            sys.exit(1)
        sys.exit(0)

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

            use_stream = not args.no_stream

            if RICH:
                console.print(
                    Panel(
                        user_input,
                        title="[bold]你[/bold]",
                        border_style="green",
                    )
                )
                if use_stream:
                    console.print("[bold blue]AI[/bold]: ", end="")
                    reply = ""
                    for chunk in loop.run_stream(user_input):
                        console.out(chunk, end="")
                        reply += chunk
                    console.print()
                else:
                    reply = ""
                    for chunk in loop.run_stream(user_input):
                        reply += chunk
                    console.print(Panel(Markdown(reply), title="[bold]AI[/bold]", border_style="blue"))
            else:
                if use_stream:
                    print("\nAI: ", end="", flush=True)
                    reply = ""
                    for chunk in loop.run_stream(user_input):
                        print(chunk, end="", flush=True)
                        reply += chunk
                    print()
                else:
                    reply = ""
                    for chunk in loop.run_stream(user_input):
                        reply += chunk
                    print(f"\nAI: {reply}")

            hook_system.trigger(
                "after_chat",
                user_message=user_input,
                ai_reply=reply,
            )

        except KeyboardInterrupt:
            print("\n")
            logger.info("用户中断")
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"网络错误: {e}")
            traceback.print_exc()
            print(f"\n[网络错误] {e}，请检查网络连接后重试")
        except (ValueError, TypeError) as e:
            logger.error(f"参数错误: {e}")
            traceback.print_exc()
            print(f"\n[参数错误] {e}")
        except Exception as e:
            logger.error(f"未预期的错误: {e}", exc_info=True)
            traceback.print_exc()
            print(f"\n[错误] {e}，已恢复，请继续输入命令")

    logger.info("程序退出")


if __name__ == "__main__":
    main()