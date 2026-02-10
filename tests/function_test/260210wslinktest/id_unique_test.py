# tests/test_id_deduplication.py
import asyncio
import websockets
import json

async def test_dedup():
    uri = "ws://localhost:8000/ws/chat"
    async with websockets.connect(uri) as websocket:
        # 发送带 ID 的消息
        msg_id = "test_unique_123"
        test_msg = {
            "message": "Hello Dedup",
            "session_id": "test_session",
            "id": msg_id
        }
        await websocket.send(json.dumps(test_msg))
        
        # 接收回显
        response = await websocket.recv()
        data = json.loads(response)
        
        if data['type'] == 'user' and data.get('id') == msg_id:
            print("✅ 后端正确回传了唯一 ID")
        else:
            print("❌ 后端未回传 ID 或数据格式错误")

if __name__ == "__main__":
    asyncio.run(test_dedup())