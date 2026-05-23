"""
wechat_cloud 工具：云函数管理聚合。

合并原 wechat_cloud_env_list、wechat_cloud_func_list、wechat_cloud_func_info、
wechat_cloud_func_deploy、wechat_cloud_func_download。
"""
import asyncio
import json as _json
from typing import TYPE_CHECKING

from ..core.cli import _run_cli, _resolve_project_path
from ..core.errors import ErrorCode
from ..core.node_bridge import _run_node_script
from ..models.schemas import WechatCloudInput
from ..utils.response import _ok, _fail

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register_cloud(mcp: "FastMCP") -> None:
    """将 wechat_cloud 工具注册到 FastMCP 实例。"""
    mcp.tool(
        name="wechat_cloud",
        annotations={
            "title": "云函数管理",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )(wechat_cloud)


async def wechat_cloud(params: WechatCloudInput) -> str:
    """微信云开发环境与云函数管理。
    支持 action: env_list(列出环境), func_list(函数列表),
    func_info(函数信息), func_deploy(上传函数), func_download(下载函数)。
    返回 JSON: {success, data, message, error_code?}。
    """
    # env 必填校验（db 系列 action 不需要 env）
    CLI_ACTIONS_REQUIRING_ENV = ("func_list", "func_info", "func_deploy", "func_download")
    if params.action in CLI_ACTIONS_REQUIRING_ENV:
        if not params.env:
            return _fail(
                ErrorCode.PARAM_MISSING,
                f"action='{params.action}' 缺少必填参数: env",
                hint="请提供云环境 ID。",
            )

    if params.action == "func_download":
        missing = [p for p in ["name", "download_path"] if not getattr(params, p)]
        if missing:
            return _fail(ErrorCode.PARAM_MISSING, f"action='func_download' 缺少必填参数: {', '.join(missing)}")

    try:
        if params.action == "env_list":
            return await _action_env_list(params)
        elif params.action == "func_list":
            return await _action_func_list(params)
        elif params.action == "func_info":
            return await _action_func_info(params)
        elif params.action == "func_deploy":
            return await _action_func_deploy(params)
        elif params.action == "func_download":
            return await _action_func_download(params)
        elif params.action == "db_collection_add":
            return await _action_db_collection_add(params)
        elif params.action == "db_collection_count":
            return await _action_db_collection_count(params)
        else:
            return _fail(ErrorCode.UNKNOWN_ERROR, f"未知 action: {params.action}")
    except ValueError as e:
        return _fail(ErrorCode.PROJECT_PATH_MISSING, str(e))
    except Exception as e:
        return _fail(ErrorCode.UNKNOWN_ERROR, f"执行失败：{type(e).__name__}: {e}")


async def _action_env_list(params: WechatCloudInput) -> str:
    proj = _resolve_project_path(params.project_path)
    args = ["cloud", "env", "list", "--project", proj]
    if params.appid:
        args.extend(["--appid", params.appid])
    if params.port is not None:
        args.extend(["--port", str(params.port)])
    if params.lang:
        args.extend(["--lang", params.lang])
    result = await _run_cli(*args)
    if result["success"]:
        return _ok({"stdout": result["stdout"]}, message="云环境列表获取成功。")
    return _fail(ErrorCode.UNKNOWN_ERROR, result.get("stderr") or "获取失败")


async def _action_func_list(params: WechatCloudInput) -> str:
    proj = _resolve_project_path(params.project_path)
    args = ["cloud", "functions", "list", "--env", params.env, "--project", proj]
    if params.appid:
        args.extend(["--appid", params.appid])
    if params.port is not None:
        args.extend(["--port", str(params.port)])
    result = await _run_cli(*args)
    if result["success"]:
        return _ok({"env": params.env, "stdout": result["stdout"]}, message="云函数列表获取成功。")
    return _fail(ErrorCode.UNKNOWN_ERROR, result.get("stderr") or "获取失败")


async def _action_func_info(params: WechatCloudInput) -> str:
    if not params.names:
        return _fail(ErrorCode.PARAM_MISSING, "action='func_info' 缺少必填参数: names")
    proj = _resolve_project_path(params.project_path)
    args = ["cloud", "functions", "info", "--env", params.env, "--names"] + params.names
    args.extend(["--project", proj])
    if params.appid:
        args.extend(["--appid", params.appid])
    if params.port is not None:
        args.extend(["--port", str(params.port)])
    result = await _run_cli(*args)
    if result["success"]:
        return _ok({"env": params.env, "names": params.names, "stdout": result["stdout"]}, message="云函数信息获取成功。")
    return _fail(ErrorCode.UNKNOWN_ERROR, result.get("stderr") or "获取失败")


async def _action_func_deploy(params: WechatCloudInput) -> str:
    proj = _resolve_project_path(params.project_path)
    args = ["cloud", "functions", "deploy", "--env", params.env]
    if params.remote_npm_install:
        args.append("-r")
    if params.names:
        args.extend(["--names"] + params.names)
    if params.paths:
        args.extend(["--paths"] + params.paths)
    args.extend(["--project", proj])
    if params.appid:
        args.extend(["--appid", params.appid])
    if params.port is not None:
        args.extend(["--port", str(params.port)])
    result = await _run_cli(*args, timeout=120)
    if result["success"]:
        deploy_output = result.get("stdout", "")
        deployed_names = params.names or []

        # 延迟验证（云端部署是异步的）
        verification = None
        try:
            await asyncio.sleep(3)
            verify_result = await _action_func_list(params)
            verification = _json.loads(verify_result)
        except Exception:
            verification = {"note": "验证步骤执行失败，请手动确认"}

        return _ok(
            {
                "env": params.env,
                "deploy_output": deploy_output,
                "deployed_names": deployed_names,
                "verification": verification,
            },
            message="云函数上传成功。建议使用 evaluate 做一次真实调用验证函数是否生效。",
        )
    return _fail(ErrorCode.UNKNOWN_ERROR, result.get("stderr") or "上传失败")


async def _action_func_download(params: WechatCloudInput) -> str:
    proj = _resolve_project_path(params.project_path)
    args = ["cloud", "functions", "download", "--env", params.env, "--name", params.name, "--path", params.download_path]
    args.extend(["--project", proj])
    if params.appid:
        args.extend(["--appid", params.appid])
    if params.port is not None:
        args.extend(["--port", str(params.port)])
    result = await _run_cli(*args, timeout=120)
    if result["success"]:
        return _ok({"name": params.name, "path": params.download_path}, message=f"云函数 {params.name} 下载成功。")
    return _fail(ErrorCode.UNKNOWN_ERROR, result.get("stderr") or "下载失败")


# ── 数据库集合管理（通过 automator evaluate 实现）──────────────


async def _action_db_collection_add(params: WechatCloudInput) -> str:
    if not params.collection_name:
        return _fail(ErrorCode.PARAM_MISSING, "action='db_collection_add' 缺少必填参数: collection_name")

    script = f"wx.cloud.database().createCollection('{params.collection_name}')"
    try:
        result = await _run_node_script(
            "ui_debug.js",
            "--port", str(params.auto_port),
            "--action", "evaluate",
            "--code", script,
            timeout=30,
        )
        if result.get("success"):
            return _ok(
                {"collection_name": params.collection_name, "result": result.get("result")},
                message=f"集合 '{params.collection_name}' 创建成功。",
            )
        return _fail(
            ErrorCode.UNKNOWN_ERROR,
            result.get("error", "创建失败"),
            hint="请确认 automator 已启动：wechat_automator(action='start')",
        )
    except Exception as e:
        return _fail(ErrorCode.UNKNOWN_ERROR, f"执行失败：{e}", hint="请确认 automator 已启动。")


async def _action_db_collection_count(params: WechatCloudInput) -> str:
    if not params.collection_name:
        return _fail(ErrorCode.PARAM_MISSING, "action='db_collection_count' 缺少必填参数: collection_name")

    script = f"wx.cloud.database().collection('{params.collection_name}').count()"
    try:
        result = await _run_node_script(
            "ui_debug.js",
            "--port", str(params.auto_port),
            "--action", "evaluate",
            "--code", script,
            timeout=30,
        )
        if result.get("success"):
            return _ok(
                {"collection_name": params.collection_name, "result": result.get("result")},
                message=f"集合 '{params.collection_name}' 文档计数获取成功。",
            )
        return _fail(
            ErrorCode.UNKNOWN_ERROR,
            result.get("error", "查询失败"),
            hint="请确认 automator 已启动：wechat_automator(action='start')",
        )
    except Exception as e:
        return _fail(ErrorCode.UNKNOWN_ERROR, f"执行失败：{e}", hint="请确认 automator 已启动。")
