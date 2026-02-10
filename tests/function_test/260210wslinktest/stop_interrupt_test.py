# tests/test_stop_interrupt.py
import asyncio
import websockets
import json
import time

async def test_interrupt():
    uri = "ws://localhost:8000/ws/chat"
    session_id = "test_interrupt_session"
    
    async with websockets.connect(uri) as websocket:
        print("[Test] Connected to WebSocket.")
        
        # 1. 发送一个由于网络原因或长思考需要时间的指令
        # 我们可以利用 'internet_search' 来模拟，或者单纯让 AI 写长文
        long_task_msg = {
            "message": "Write a very long poem about the universe, at least 500 words. Do it slowly.",
            "session_id": session_id
        }
        
        print(f"[Test] Sending long task: {long_task_msg['message']}")
        await websocket.send(json.dumps(long_task_msg))
        
        # 2. 接收几条消息，确认 AI 开始工作
        print("[Test] Waiting for AI start...")
        received_count = 0
        try:
            while received_count < 3:
                resp = await websocket.recv()
                data = json.loads(resp)
                if data['type'] == 'delta':
                    print(f"[AI Output]: {data['content']}", end="", flush=True)
                    received_count += 1
        except Exception as e:
            print(f"Error receiving: {e}")

        # 3. 发送打断指令
        print("\n\n[Test] !!! SENDING STOP COMMAND !!!")
        stop_msg = {
            "message": "/stop",
            "session_id": session_id
        }
        await websocket.send(json.dumps(stop_msg))
        
        # 4. 验证是否立即收到 status: aborted
        print("[Test] Waiting for confirmation...")
        start_wait = time.time()
        stopped = False
        
        while time.time() - start_wait < 5: # 5秒超时
            try:
                resp = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                data = json.loads(resp)
                
                if data['type'] == 'status' and 'Aborted' in data['content']:
                    print(f"\n[Success] Received Stop Confirmation: {data['content']}")
                    stopped = True
                    break
                elif data['type'] == 'delta':
                    print(".", end="", flush=True) # 可能会有少量残留消息
            except asyncio.TimeoutError:
                print("\n[Timeout] Waiting for stop response...")
                break
        
        if stopped:
            print("\n✅ TEST PASSED: Interrupt was successful and immediate.")
        else:
            print("\n❌ TEST FAILED: Did not receive immediate stop confirmation.")

if __name__ == "__main__":
    # 需要先安装 websockets: pip install websockets
    try:
        asyncio.run(test_interrupt())
    except KeyboardInterrupt:
        pass