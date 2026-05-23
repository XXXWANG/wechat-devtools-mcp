#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
wechat-devtools-mcp v0.3.0

「瘦 MCP + 胖 Skill」架构：44 个工具聚合为 7 个聚合 API
（v0.9.5 起 wechat_cloud 已禁用，CloudBase MCP 完全覆盖）。

启动入口 + FastMCP 实例 + 7 个工具注册（< 150 行）。
"""

import io
import os
import sys

from mcp.server.fastmcp import FastMCP

from . import __version__

from .tools import register_all_tools

# 初始化 FastMCP Server
mcp = FastMCP("wechat_devtools_mcp")

# 注册全部 7 个聚合工具
register_all_tools(mcp)


def main() -> None:
    """MCP Server 启动入口。

    启动前校验必需的环境变量，Windows 下设置 UTF-8 编码。
    """
    # Windows 下强制 stdio 使用 UTF-8，避免 GBK 编码导致 UnicodeDecodeError
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")

    # 启动前校验必需的环境变量
    missing_envs: list[str] = []

    if "WECHAT_DEVTOOLS_CLI" not in os.environ:
        missing_envs.append("WECHAT_DEVTOOLS_CLI (例如: D:\\Tencent\\微信web开发者工具\\cli.bat)")

    if "WECHAT_PROJECT_PATH" not in os.environ:
        missing_envs.append("WECHAT_PROJECT_PATH (例如: D:\\Projects\\WeChat-App)")

    if missing_envs:
        print("启动失败：缺少必需的环境变量！", file=sys.stderr)
        print("在运行该 MCP Server 之前，您必须配置以下环境变量：\n", file=sys.stderr)
        for env in missing_envs:
            print(f"  - {env}", file=sys.stderr)
        print("\n请在 MCP 客户端配置（如 cursor/mcp.json）或系统环境变量中添加它们。", file=sys.stderr)
        sys.exit(1)

    print(f"wechat-devtools-mcp v{__version__} starting...", file=sys.stderr)
    mcp.run()


if __name__ == "__main__":
    main()
