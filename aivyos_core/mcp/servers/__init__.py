"""MCP 服务器集合（§5.1.2 清单）。"""

from aivyos_core.mcp.servers.browser import BrowserServer
from aivyos_core.mcp.servers.code_exec import CodeExecServer
from aivyos_core.mcp.servers.filesystem import FilesystemServer
from aivyos_core.mcp.servers.memory import MemoryServer
from aivyos_core.mcp.servers.office import OfficeServer
from aivyos_core.mcp.servers.screenshot import ScreenshotServer
from aivyos_core.mcp.servers.search import SearchServer
from aivyos_core.mcp.servers.shell import ShellServer

__all__ = [
    "FilesystemServer", "ShellServer", "CodeExecServer", "BrowserServer",
    "OfficeServer", "SearchServer", "ScreenshotServer", "MemoryServer",
]
