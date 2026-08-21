"""一键启动脚本测试：存在性 + 关键模式分支逻辑。"""

import os
import unittest

from tests import AivyTestCase

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestLauncher(AivyTestCase):
    def test_ps1_exists(self):
        """start_aivyos.ps1 存在且包含桌面/Web 模式分支。"""
        path = os.path.join(ROOT, "scripts", "start_aivyos.ps1")
        self.assertTrue(os.path.exists(path), "启动脚本缺失")
        content = open(path, encoding="utf-8", errors="replace").read()
        self.assertIn("-Web", content)          # Web 模式开关
        self.assertIn("aivyos-shell.exe", content)  # 桌面模式 exe
        self.assertIn("tauri dev", content)     # 开发模式回退
        self.assertIn("31701", content)         # 核心端口探测
        self.assertIn("11434", content)         # Ollama 探测

    def test_ps1_build_parameter(self):
        """start_aivyos.ps1 支持 -Build release 构建参数。"""
        path = os.path.join(ROOT, "scripts", "start_aivyos.ps1")
        content = open(path, encoding="utf-8", errors="replace").read()
        self.assertIn("$Build", content)                 # 参数声明
        self.assertIn('[switch]$Build', content)         # switch 参数
        self.assertIn("tauri build", content)            # release 构建命令
        self.assertIn("target\\release\\aivyos-shell.exe", content)  # release 产物路径
        self.assertIn("cargo", content)                  # Rust 工具链检查
        self.assertIn("Ensure-NpmDeps", content)         # 依赖确保函数

    def test_ps1_auto_locate_root(self):
        """脚本自动定位项目根目录（从任意 cwd 可运行）。"""
        path = os.path.join(ROOT, "scripts", "start_aivyos.ps1")
        content = open(path, encoding="utf-8", errors="replace").read()
        self.assertIn("aivyos_core", content)            # 以 aivyos_core 定位
        self.assertIn("MyInvocation.MyCommand.Path", content)  # 基于脚本位置
        self.assertIn("Resolve-Path", content)           # 规范化路径

    def test_ps1_stops_running_instance_before_build(self):
        """构建前停止运行中的应用（解锁 exe，避免 Windows 文件占用）。"""
        path = os.path.join(ROOT, "scripts", "start_aivyos.ps1")
        content = open(path, encoding="utf-8", errors="replace").read()
        self.assertIn('Get-Process -Name "aivyos-shell"', content)  # 检测实例
        self.assertIn("Stop-Process", content)                     # 停止实例
        self.assertIn("taskkill /IM aivyos-shell.exe", content)    # 无法停止时的提示
        # 停止逻辑必须在 -Build 分支内（构建命令之前）
        build_idx = content.index("npm.cmd run tauri build")
        stop_idx = content.index("Stop-Process")
        self.assertLess(stop_idx, build_idx)  # 先停再构建

    def test_ps1_exit_cleanup(self):
        """关闭终端/脚本退出时自动清理进程并关闭桌面端。"""
        path = os.path.join(ROOT, "scripts", "start_aivyos.ps1")
        content = open(path, encoding="utf-8", errors="replace").read()
        # Exiting 事件注册（终端关闭触发）
        self.assertIn("Register-EngineEvent", content)
        self.assertIn("PowerShell.Exiting", content)
        # 清理函数：杀脚本启动的进程 + aivyos-shell + 31701 核心
        self.assertIn("Stop-AivyCleanup", content)
        self.assertIn("Add-AivyPid", content)
        self.assertIn("AivyCleanupPids", content)
        self.assertIn("Get-NetTCPConnection -LocalPort 31701", content)  # 杀核心
        self.assertIn('Get-Process -Name "aivyos-shell"', content)       # 杀桌面端
        # 桌面模式跟踪 app PID
        self.assertIn("Start-Process -FilePath $exe -PassThru", content)
        self.assertIn("Add-AivyPid $appProc.Id", content)

    def test_bat_exists(self):
        """start_aivyos.bat 双击启动器存在。"""
        path = os.path.join(ROOT, "start_aivyos.bat")
        self.assertTrue(os.path.exists(path))
        content = open(path, encoding="utf-8", errors="replace").read()
        self.assertIn("start_aivyos.ps1", content)

    def test_ps1_ascii_comments(self):
        """PS1 脚本注释必须为 ASCII（PS 5.1 对 UTF-8 无 BOM 中文解析有问题）。"""
        path = os.path.join(ROOT, "scripts", "start_aivyos.ps1")
        content = open(path, encoding="utf-8", errors="replace").read()
        # 脚本正文允许中文输出，但注释行（# 开头）不应含中文
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                try:
                    stripped.encode("ascii")
                except UnicodeEncodeError:
                    self.fail(f"注释含非 ASCII 字符: {stripped[:60]}")


if __name__ == "__main__":
    unittest.main()
