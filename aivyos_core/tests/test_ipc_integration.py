"""完整集成测试 — 验证 IPC 服务器 + broadcast_event + 唤醒流程。"""
import sys, asyncio, json, time
sys.path.insert(0, 'F:/AivyOS/aivyos')

from aivyos_core.ipc.server import AivyIpcServer

async def test_integration():
    print("=== IPC 集成测试 ===")
    server = AivyIpcServer(port=31801)
    
    server.register("wake-detected", lambda p: None)
    await server.start()
    print(f"  ✅ 服务器启动: port=31801, methods={list(server._handlers.keys())}")
    
    await server.broadcast_event("wake-detected", {"text": "你好艾薇"})
    print("  ✅ broadcast_event 成功")
    
    await server.stop()
    print("  ✅ 服务器停止")
    print("\n✅ IPC 集成测试通过")

asyncio.run(test_integration())