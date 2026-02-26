#!/usr/bin/env python3
"""
OpenAI兼容API工具调用Agent演示
支持read、write、edit、glob、grep、bash工具
支持从 .env 文件自动加载环境变量

使用方法:
1. 创建 .env 文件并配置:
   OPENAI_BASE_URL=https://api.openai.com/v1
   OPENAI_API_KEY=sk-xxx
   OPENAI_MODEL=gpt-4o-mini

2. 运行: python agent.py

可选依赖: pip install python-dotenv
"""

import json
import os
import sys
from typing import Callable
from openai import OpenAI

try:
    from colorama import init, Fore, Style

    init(autoreset=True)
    _COLOR = True
except ImportError:
    _COLOR = False

    class Fore:
        CYAN = GREEN = YELLOW = RED = MAGENTA = BLUE = ""

    class Style:
        BRIGHT = RESET_ALL = ""


# 尝试加载 .env 文件
_DOTENV_LOADED = False
try:
    from dotenv import load_dotenv

    _DOTENV_LOADED = load_dotenv()  # 自动加载当前目录下的 .env 文件
except ImportError:
    pass  # 如果没有安装 python-dotenv，则跳过

# ==================== 工具函数实现 ====================


def read(path: str, offset: int = None, limit: int = None) -> str:
    """读取文件内容，带行号"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        if offset is not None:
            start = max(0, offset - 1)
            end = len(lines) if limit is None else min(len(lines), start + limit)
            lines = lines[start:end]
            line_num_start = start + 1
        else:
            line_num_start = 1

        result = []
        for i, line in enumerate(lines, line_num_start):
            result.append(f"{i:4d} | {line.rstrip()}")
        return "\n".join(result) if result else "(空文件)"
    except Exception as e:
        return f"错误: {e}"


def write(path: str, content: str) -> str:
    """写入文件"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"成功写入文件: {path}"
    except Exception as e:
        return f"错误: {e}"


def edit(path: str, old: str, new: str, all: bool = False) -> str:
    """替换文件内容"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        if all:
            new_content = content.replace(old, new)
            count = content.count(old)
        else:
            if content.count(old) > 1:
                return f"错误: 找到多个匹配，请使用 all=true 或确保 old 唯一"
            new_content = content.replace(old, new, 1)
            count = 1 if old in content else 0

        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)

        return f"成功替换 {count} 处内容" if count > 0 else "未找到匹配内容"
    except Exception as e:
        return f"错误: {e}"


def glob(pat: str, path: str = ".") -> str:
    """查找匹配文件"""
    import fnmatch

    try:
        matches = []
        for root, dirs, files in os.walk(path):
            for filename in files:
                if fnmatch.fnmatch(filename, pat):
                    full_path = os.path.join(root, filename)
                    mtime = os.path.getmtime(full_path)
                    matches.append((full_path, mtime))

        matches.sort(key=lambda x: x[1], reverse=True)
        return (
            "\n".join([f"{p} | {m}" for p, m in matches])
            if matches
            else "未找到匹配文件"
        )
    except Exception as e:
        return f"错误: {e}"


def grep(pat: str, path: str = ".") -> str:
    """搜索文件内容"""
    import re

    try:
        results = []
        for root, dirs, files in os.walk(path):
            for filename in files:
                filepath = os.path.join(root, filename)
                try:
                    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                        for i, line in enumerate(f, 1):
                            if re.search(pat, line):
                                results.append(f"{filepath}:{i}: {line.rstrip()}")
                except:
                    continue
        return "\n".join(results[:50]) if results else "未找到匹配"  # 限制返回数量
    except Exception as e:
        return f"错误: {e}"


def _decode_bytes(data: bytes) -> str:
    """解码字节，尝试多种编码（Windows GBK/UTF-8）"""
    if not data:
        return ""
    # 尝试 UTF-8
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    # 尝试 GBK (Windows 中文)
    try:
        return data.decode("gbk")
    except UnicodeDecodeError:
        pass
    # 回退：替换错误字符
    return data.decode("utf-8", errors="replace")


def bash(cmd: str) -> str:
    """执行shell命令"""
    import subprocess

    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, timeout=60)
        # 解码输出，处理 Windows 中文编码
        stdout = _decode_bytes(result.stdout)
        stderr = _decode_bytes(result.stderr)

        output = stdout
        if stderr:
            output += f"\n[stderr]: {stderr}"
        if result.returncode != 0:
            output += f"\n[退出码]: {result.returncode}"
        return output or "(无输出)"
    except subprocess.TimeoutExpired:
        return "错误: 命令超时(60秒)"
    except Exception as e:
        return f"错误: {e}"


# ==================== 工具定义 ====================

TOOLS: dict[str, tuple[str, dict, Callable]] = {
    "read": (
        "Read file with line numbers (file path, not directory)",
        {"path": "string", "offset": "number?", "limit": "number?"},
        read,
    ),
    "write": (
        "Write content to file",
        {"path": "string", "content": "string"},
        write,
    ),
    "edit": (
        "Replace old with new in file (old must be unique unless all=true)",
        {"path": "string", "old": "string", "new": "string", "all": "boolean?"},
        edit,
    ),
    "glob": (
        "Find files by pattern, sorted by mtime",
        {"pat": "string", "path": "string?"},
        glob,
    ),
    "grep": (
        "Search files for regex pattern",
        {"pat": "string", "path": "string?"},
        grep,
    ),
    "bash": (
        "Run shell command",
        {"cmd": "string"},
        bash,
    ),
}


def build_openai_tools() -> list[dict]:
    """将工具定义转换为OpenAI格式"""
    openai_tools = []
    for name, (description, params, _) in TOOLS.items():
        properties = {}
        required = []

        for param_name, param_type in params.items():
            if param_type.endswith("?"):
                param_type = param_type[:-1]
            else:
                required.append(param_name)

            if param_type == "string":
                properties[param_name] = {"type": "string"}
            elif param_type == "number":
                properties[param_name] = {"type": "number"}
            elif param_type == "boolean":
                properties[param_name] = {"type": "boolean"}

        openai_tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }
        )
    return openai_tools


def execute_tool(name: str, arguments: dict) -> str:
    """执行工具调用"""
    if name not in TOOLS:
        return f"错误: 未知工具 {name}"

    _, _, func = TOOLS[name]
    try:
        return func(**arguments)
    except Exception as e:
        return f"工具执行错误: {e}"


# ==================== Agent核心 ====================


class ToolAgent:
    def __init__(self, base_url: str = None, api_key: str = None, model: str = None):
        """
        初始化Agent
        base_url: OpenAI兼容API的基础URL，如 http://localhost:8000/v1
        api_key: API密钥
        model: 模型名称
        """
        # 从环境变量获取配置
        self.base_url = base_url or os.getenv(
            "OPENAI_BASE_URL", "https://api.openai.com/v1"
        )
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        self.client = OpenAI(base_url=self.base_url, api_key=self.api_key)
        self.tools = build_openai_tools()
        self.messages = []

        # 系统提示
        self.system_prompt = """你是一个有用的AI助手，可以使用以下工具帮助用户:
- read: 读取文件内容
- write: 写入文件
- edit: 编辑文件内容
- glob: 查找文件
- grep: 搜索文件内容
- bash: 执行shell命令

请根据用户需求选择合适工具。如果需要多个步骤，请逐步执行。"""

    def chat(self, user_input: str) -> str:
        """
        处理用户输入，支持多轮工具调用
        返回最终回复
        """
        # 添加用户消息
        self.messages.append({"role": "user", "content": user_input})

        max_iterations = 10  # 防止无限循环

        for iteration in range(max_iterations):
            # 调用API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": self.system_prompt}]
                + self.messages,
                tools=self.tools,
                tool_choice="auto",
            )

            message = response.choices[0].message

            # 检查是否有工具调用
            if not message.tool_calls:
                # 没有工具调用，直接返回内容
                self.messages.append({"role": "assistant", "content": message.content})
                return message.content

            # 有工具调用，执行工具
            print(f"\n{Fore.YELLOW}[工具调用第 {iteration + 1} 轮]{Style.RESET_ALL}")

            # 添加assistant的tool_calls消息
            self.messages.append(
                {
                    "role": "assistant",
                    "content": message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in message.tool_calls
                    ],
                }
            )

            # 执行每个工具调用
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    tool_args = {}

                print(
                    f"  {Fore.MAGENTA}🔧 {tool_name}{Style.RESET_ALL}({json.dumps(tool_args, ensure_ascii=False)})"
                )

                # 执行工具
                result = execute_tool(tool_name, tool_args)

                # 截断过长的结果
                display_result = result[:500] + "..." if len(result) > 500 else result
                print(f"  {Fore.BLUE}📤 结果: {Style.RESET_ALL}{display_result}")

                # 添加工具结果到消息
                self.messages.append(
                    {"role": "tool", "tool_call_id": tool_call.id, "content": result}
                )

            # 继续循环，让模型处理工具结果

        return "达到最大迭代次数，请简化您的请求。"

    def clear_history(self):
        """清空对话历史"""
        self.messages = []
        print("对话历史已清空")


# ==================== 主程序 ====================


def main():
    print("=" * 50)
    print("🤖 OpenAI兼容API工具调用Agent")
    print("=" * 50)
    print("\n环境变量配置 (优先从 .env 文件加载):")
    print("  OPENAI_BASE_URL - API基础URL (默认: https://api.openai.com/v1)")
    print("  OPENAI_API_KEY  - API密钥")
    print("  OPENAI_MODEL    - 模型名称 (默认: gpt-4o-mini)")
    print("\n.env 文件示例:")
    print("  OPENAI_BASE_URL=https://api.openai.com/v1")
    print("  OPENAI_API_KEY=sk-xxx")
    print("  OPENAI_MODEL=gpt-4o-mini")
    print("\n命令:")
    print("  /clear - 清空对话历史")
    print("  /quit  - 退出")
    print("  /tools - 显示可用工具")
    print("=" * 50)

    # 初始化Agent
    agent = ToolAgent()
    print(f"\n✅ Agent已初始化")
    print(f"   模型: {agent.model}")
    print(f"   API: {agent.base_url}")

    # 显示 .env 加载状态
    if _DOTENV_LOADED:
        print(f"   .env: 已加载")
    else:
        # 检查是否有 python-dotenv
        try:
            import dotenv  # noqa: F401

            print(f"   .env: 未找到文件或文件为空")
        except ImportError:
            print(f"   .env: 未安装 python-dotenv (pip install python-dotenv)")

    # 外循环：用户交互
    while True:
        try:
            print()
            user_input = input(f"{Fore.CYAN}👤 用户: {Style.RESET_ALL}").strip()

            if not user_input:
                continue

            if user_input.lower() in ["/quit", "/exit", "quit", "exit"]:
                print("👋 再见!")
                break

            if user_input.lower() == "/clear":
                agent.clear_history()
                continue

            if user_input.lower() == "/tools":
                print("\n可用工具:")
                for name, (desc, params, _) in TOOLS.items():
                    print(f"  - {name}: {desc}")
                    print(f"    参数: {params}")
                continue

            # 内循环：工具调用（在agent.chat内部处理）
            print()
            response = agent.chat(user_input)
            print(f"\n{Fore.GREEN}🤖 Agent: {response}{Style.RESET_ALL}")

        except KeyboardInterrupt:
            print("\n👋 再见!")
            break
        except Exception as e:
            print(f"\n❌ 错误: {e}")


if __name__ == "__main__":
    main()
