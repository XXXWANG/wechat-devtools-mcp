"""
tools 包：7 个聚合工具的统一注册入口。

注：wechat_cloud 自 v0.9.5 起已禁用（CloudBase MCP 覆盖其能力），
源码和 schema 保留但不对外注册。
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register_all_tools(mcp: "FastMCP") -> None:
    """将全部 7 个聚合工具注册到 FastMCP 实例。

    注：wechat_cloud 自 v0.9.5 起已禁用（CloudBase MCP 完全覆盖其能力）。
    源码与 schema 保留，但不再对外暴露。

    Args:
        mcp: FastMCP 实例。
    """
    from .ide import register_ide
    from .build import register_build
    from .automator import register_automator
    from .inspector import register_inspector
    from .screenshot import register_screenshot
    from .navigate import register_navigate
    from .file_reader import register_file

    register_ide(mcp)
    register_build(mcp)
    register_automator(mcp)
    register_inspector(mcp)
    register_screenshot(mcp)
    register_navigate(mcp)
    register_file(mcp)
