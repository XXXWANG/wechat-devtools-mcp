"""
wechat_ide 工具：IDE 生命周期管理。

合并原 wechat_open、wechat_login、wechat_is_login、
wechat_close_project、wechat_quit_ide、wechat_get_status。
"""
import asyncio
import json
import os
import sys
from typing import TYPE_CHECKING

from ..core.cli import _run_cli, _build_global_args, _resolve_project_path
from ..core.config import CLI_PATH, DEFAULT_PROJECT_PATH
from .. import __version__
from ..core.errors import ErrorCode
from ..core.node_bridge import _check_node_available, _run_node_script
from ..models.schemas import WechatIdeInput
from ..utils.cdp_helpers import _format_cdp_logs_v2
from ..utils.response import _ok, _fail

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register_ide(mcp: "FastMCP") -> None:
    """将 wechat_ide 工具注册到 FastMCP 实例。"""
    mcp.tool(
        name="wechat_ide",
        annotations={
            "title": "IDE 生命周期管理",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )(wechat_ide)


async def wechat_ide(params: WechatIdeInput) -> str:
    """微信开发者工具 IDE 生命周期管理。
    支持 action: open(打开IDE/项目), login(扫码登录), is_login(检查登录),
    close(关闭项目), quit(退出IDE), status(环境诊断)。
    返回 JSON: {success, data, message, error_code?}。
    """
    try:
        if params.action == "open":
            return await _action_open(params)
        elif params.action == "login":
            return await _action_login(params)
        elif params.action == "is_login":
            return await _action_is_login(params)
        elif params.action == "close":
            return await _action_close(params)
        elif params.action == "quit":
            return await _action_quit(params)
        elif params.action == "status":
            return await _action_status()
        else:
            return _fail(ErrorCode.UNKNOWN_ERROR, f"未知 action: {params.action}")
    except ValueError as e:
        return _fail(ErrorCode.PROJECT_PATH_MISSING, str(e))
    except Exception as e:
        return _fail(ErrorCode.UNKNOWN_ERROR, f"执行失败：{type(e).__name__}: {e}")


def _resolve_ide_executable_for_cdp() -> tuple[list[str], str]:
    """从 CLI_PATH 推导 IDE 主程序启动命令前缀和 kill 模式。

    Returns:
        (cmd_prefix, kill_pattern):
          cmd_prefix - 启动 IDE 主程序的命令前缀（不含 --remote-debugging-port）
          kill_pattern - taskkill 镜像名（Windows）或 pkill -f 模式（macOS）

    Raises:
        FileNotFoundError: IDE 主程序或 NW.js 应用包缺失。
        NotImplementedError: 当前平台不支持 cdp_enabled。
    """
    if sys.platform == "win32":
        exe = CLI_PATH.replace("cli.bat", "微信开发者工具.exe")
        return [exe], "wechatdevtools.exe"

    if sys.platform == "darwin":
        # CLI_PATH 形如 /Applications/wechatwebdevtools.app/Contents/MacOS/cli
        # 显式使用 forward slash，避免 os.path.join 在跨平台调试时引入反斜杠
        cli_dir = CLI_PATH.rsplit("/", 1)[0]
        contents = cli_dir.rsplit("/", 1)[0]
        ide_exe = f"{cli_dir}/wechatdevtools"
        package_nw = f"{contents}/Resources/package.nw"
        if not os.path.exists(ide_exe):
            raise FileNotFoundError(f"找不到 macOS IDE 主程序：{ide_exe}")
        if not os.path.exists(package_nw):
            raise FileNotFoundError(f"找不到 NW.js 应用包：{package_nw}")
        return [ide_exe, package_nw], "wechatdevtools"

    raise NotImplementedError(f"cdp_enabled 暂不支持平台：{sys.platform}")


async def _kill_existing_ide(kill_pattern: str) -> None:
    """跨平台 kill 已运行的 IDE 主程序，并等待 2s 确保端口释放。"""
    import subprocess
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/IM", kill_pattern],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    elif sys.platform == "darwin":
        subprocess.run(
            ["pkill", "-9", "-f", kill_pattern],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    await asyncio.sleep(2)


async def _action_open(params: WechatIdeInput) -> str:
    """打开微信开发者工具 IDE 或项目。"""
    import subprocess

    if params.cdp_enabled:
        try:
            cmd_prefix, kill_pattern = _resolve_ide_executable_for_cdp()
        except (FileNotFoundError, NotImplementedError) as e:
            return _fail(ErrorCode.CLI_NOT_FOUND, str(e))

        cmd_args = list(cmd_prefix) + ["--remote-debugging-port=9222"]
        if params.project_path:
            if sys.platform == "darwin":
                cmd_args.append(f"--project={params.project_path}")
            else:
                cmd_args.extend(["--project", params.project_path])

        await _kill_existing_ide(kill_pattern)
    else:
        cli_args = ["open"]
        cli_args.extend(_build_global_args(
            project_path=params.project_path,
            appid=params.appid,
            port=params.port,
            lang=params.lang,
        ))
        if sys.platform == "win32" and CLI_PATH.lower().endswith(".bat"):
            cmd_args = ["cmd", "/c", CLI_PATH] + cli_args
        else:
            cmd_args = [CLI_PATH] + cli_args

    try:
        kwargs: dict = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW

        proc = subprocess.Popen(
            cmd_args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )
        try:
            await asyncio.wait_for(asyncio.to_thread(proc.wait), timeout=15)
        except asyncio.TimeoutError:
            pass

        cdp_note = "CDP 调试端口已开启（9222）" if params.cdp_enabled else ""

        # CDP 启动健康检查：采集 5 秒日志，检测启动阶段致命错误
        if params.cdp_enabled:
            await asyncio.sleep(5)  # 等待小程序页面加载
            cdp_result = await _run_node_script(
                "cdp_listener.js", "5", "9222", timeout=20,
            )
            raw_logs = cdp_result.get("data", cdp_result.get("logs", []))
            if not isinstance(raw_logs, list):
                raw_logs = []
            formatted = _format_cdp_logs_v2(raw_logs, "concise", 50, filter_startup_noise=True)
            error_count = formatted["summary"]["errors"]
            if error_count > 0:
                error_logs = [
                    log for log in formatted["logs"] if log["level"] == "error"
                ]
                return _fail(
                    ErrorCode.UNKNOWN_ERROR,
                    f"小程序启动阶段检测到 {error_count} 个错误，页面可能无法正常显示。",
                    hint="请先修复以下启动错误，再继续后续操作。",
                    extra={"startup_errors": error_logs, "cdp_summary": formatted["summary"]},
                )

        return _ok(
            {"cdp_enabled": params.cdp_enabled, "cdp_port": 9222 if params.cdp_enabled else None},
            message=f"IDE 已在后台启动。{cdp_note}",
        )
    except FileNotFoundError:
        return _fail(
            ErrorCode.CLI_NOT_FOUND,
            f"找不到微信开发者工具文件：{cmd_args[0]}",
            hint="请确认微信开发者工具已安装，或通过 WECHAT_DEVTOOLS_CLI 指定路径。",
        )
    except Exception as e:
        return _fail(ErrorCode.UNKNOWN_ERROR, f"启动失败：{type(e).__name__}: {e}")


async def _action_login(params: WechatIdeInput) -> str:
    """登录微信开发者工具，生成二维码供扫码。"""
    args = ["login"]
    if params.qr_format:
        args.extend(["--qr-format", params.qr_format])
    if params.qr_output:
        args.extend(["--qr-output", params.qr_output])
    if params.result_output:
        args.extend(["--result-output", params.result_output])
    if params.port is not None:
        args.extend(["--port", str(params.port)])
    if params.lang:
        args.extend(["--lang", params.lang])

    result = await _run_cli(*args, timeout=120)
    if result["success"]:
        return _ok({"stdout": result["stdout"]}, message="登录二维码已生成。")
    return _fail(ErrorCode.UNKNOWN_ERROR, result.get("stderr") or result.get("stdout") or "登录失败")


async def _action_is_login(params: WechatIdeInput) -> str:
    """检查微信开发者工具当前是否已登录。"""
    args = ["islogin"]
    args.extend(_build_global_args(project_path=params.project_path, appid=params.appid, port=params.port))
    result = await _run_cli(*args)
    logged_in = result["success"]
    return _ok(
        {"logged_in": logged_in, "stdout": result.get("stdout", "")},
        message="已登录" if logged_in else "未登录",
    )


async def _action_close(params: WechatIdeInput) -> str:
    """关闭指定小程序项目窗口。"""
    proj = _resolve_project_path(params.project_path)
    args = ["close", "--project", proj]
    if params.port is not None:
        args.extend(["--port", str(params.port)])
    result = await _run_cli(*args)
    if result["success"]:
        return _ok({}, message="项目窗口已关闭。")
    return _fail(ErrorCode.UNKNOWN_ERROR, result.get("stderr") or "关闭失败")


async def _action_quit(params: WechatIdeInput) -> str:
    """退出整个微信开发者工具 IDE。"""
    args = ["quit"]
    if params.port is not None:
        args.extend(["--port", str(params.port)])
    result = await _run_cli(*args)
    if result["success"]:
        return _ok({}, message="IDE 已退出。")
    return _fail(ErrorCode.UNKNOWN_ERROR, result.get("stderr") or "退出失败")


async def _action_status() -> str:
    """返回 MCP 服务运行状态和环境配置信息。"""
    project_path = DEFAULT_PROJECT_PATH or ""
    cli_path = CLI_PATH

    project_exists = os.path.isdir(project_path) if project_path else False
    cli_exists = os.path.exists(cli_path)
    node_ok, node_path = await _check_node_available()

    data: dict = {
        "mcp_version": __version__,
        "cli_path": cli_path,
        "cli_exists": cli_exists,
        "project_path": project_path or "未配置",
        "project_exists": project_exists,
        "node_available": node_ok,
        "node_path": node_path,
    }

    if project_exists:
        config_path = os.path.join(project_path, "project.config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = json.load(f)
                data["project_name"] = config.get("projectname", "未知")
                data["appid"] = config.get("appid", "未知")
                data["lib_version"] = config.get("libVersion", "未知")
            except Exception:
                pass

    hints = []
    if not cli_exists:
        hints.append(f"CLI 文件不存在：{cli_path}，请设置 WECHAT_DEVTOOLS_CLI 环境变量")
    if not project_exists:
        hints.append("项目路径未配置或不存在，请设置 WECHAT_PROJECT_PATH 环境变量")
    if not node_ok:
        hints.append("Node.js 未检测到，请安装并配置 PATH")

    return _ok(data, message="状态正常" if not hints else "；".join(hints))
