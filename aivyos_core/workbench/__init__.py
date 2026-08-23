"""双模型协同工作台（Workbench）：读取 cc-switch 配置，编排 Claude Code / Codex CLI。

安全约束（计划书 §六）：
- API Key 只注入子进程环境变量，不写日志 / 记忆 / 持久化文件 / 工具返回值
- cc-switch 数据库只读打开（mode=ro），缺失时降级到 AivyOS 自身 workbench 配置
"""
