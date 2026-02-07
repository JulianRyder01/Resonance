import pyautogui
import time
import random
import math

# 安全设置：启用 FAILSAFE（默认开启）
pyautogui.FAILSAFE = True

def bezier_point(p0, p1, p2, p3, t):
    """计算三阶贝塞尔曲线上 t 时刻的点 (t ∈ [0, 1])"""
    x = (1 - t)**3 * p0[0] + 3 * (1 - t)**2 * t * p1[0] + \
        3 * (1 - t) * t**2 * p2[0] + t**3 * p3[0]
    y = (1 - t)**3 * p0[1] + 3 * (1 - t)**2 * t * p1[1] + \
        3 * (1 - t) * t**2 * p2[1] + t**3 * p3[1]
    return (x, y)

def human_like_move_to(end_x, end_y, duration=random.uniform(0.8,1.2), steps=None):
    """
    模拟人类鼠标移动到目标点
    :param end_x, end_y: 目标坐标
    :param duration: 总移动时间（秒）
    :param steps: 移动步数（默认根据距离自适应）
    """
    # 获取当前鼠标位置
    start_x, start_y = pyautogui.position()
    
    # 若已在目标点，直接返回
    if abs(start_x - end_x) < 2 and abs(start_y - end_y) < 2:
        return

    # 自适应步数：距离越远，步数越多（但不低于 30，不高于 80）
    distance = math.hypot(end_x - start_x, end_y - start_y)
    if steps is None:
        steps = max(30, min(80, int(distance / 5)))
    
    # 随机生成两个控制点（在起点与终点之间扰动）
    # 控制点偏移量：±30% 的位移向量
    dx = end_x - start_x
    dy = end_y - start_y
    
    # 控制点1：靠近起点
    p1_x = start_x + dx * random.uniform(0.3, 0.6) + random.uniform(-0.2, 0.2) * dx
    p1_y = start_y + dy * random.uniform(0.3, 0.6) + random.uniform(-0.2, 0.2) * dy
    
    # 控制点2：靠近终点
    p2_x = start_x + dx * random.uniform(0.6, 0.9) + random.uniform(-0.2, 0.2) * dx
    p2_y = start_y + dy * random.uniform(0.6, 0.9) + random.uniform(-0.2, 0.2) * dy

    p0 = (start_x, start_y)
    p1 = (p1_x, p1_y)
    p2 = (p2_x, p2_y)
    p3 = (end_x, end_y)

    # 计算每一步的时间间隔
    total_time = duration
    step_delay = total_time / steps

    # 执行贝塞尔轨迹移动
    for i in range(steps + 1):
        t = i / steps
        
        # 速度调节：两头慢，中间快（使用正弦函数平滑）
        speed_factor = 10+5*math.sin(t * math.pi)  # 0 → 1 → 0
        current_delay = step_delay / max(speed_factor, 0.1)  # 避免除零
        
        # 获取贝塞尔点
        x, y = bezier_point(p0, p1, p2, p3, t)
        
        # 移动鼠标（使用整数坐标）
        pyautogui.moveTo(int(x), int(y), _pause=False)
        jitter_count = random.uniform(0, 1)
        if jitter_count > 0.6:
            offset_x = random.randint(-2, 2)
            offset_y = random.randint(-2, 2)
            pyautogui.moveRel(offset_x, offset_y, _pause=False)
        # 添加微小随机延迟（模拟人类不规则节奏）
        time.sleep(current_delay + random.uniform(0.001, 0.004))

    # === 末端抖动（模拟人类对准）===
    jitter_count = random.randint(2, 3)
    for _ in range(jitter_count):
        offset_x = random.randint(-2, 2)
        offset_y = random.randint(-2, 2)
        pyautogui.moveRel(offset_x, offset_y, _pause=False)
        time.sleep(random.uniform(0.02, 0.06))
    
    # 最终回到目标点（确保精准）
    pyautogui.moveTo(end_x, end_y, _pause=False)


# ========================
# 演示主程序
# ========================
def demo():
    print("【拟人鼠标移动 Demo 启动】")
    print("提示：将鼠标快速移至屏幕左上角可紧急停止程序。")
    time.sleep(2)

    screen_w, screen_h = pyautogui.size()
    targets = [
        (screen_w // 4, screen_h // 4),
        (3 * screen_w // 4, screen_h // 4),
        (3 * screen_w // 4, 3 * screen_h // 4),
        (screen_w // 4, 3 * screen_h // 4),
        (screen_w // 2, screen_h // 2),
        (screen_w // 4, screen_h // 4),
        (3 * screen_w // 4, screen_h // 4),
        (3 * screen_w // 4, 3 * screen_h // 4),
        (screen_w // 4, 3 * screen_h // 4),
        (screen_w // 2, screen_h // 2),
    ]

    for i, (x, y) in enumerate(targets, 1):
        print(f"→ 第 {i} 步：移动到 ({x}, {y})")
        human_like_move_to(x, y, duration=random.uniform(0.8, 1.5))
        time.sleep(0.5)  # 短暂停留

    # 最终点击
    print("→ 在中心位置单击")
    pyautogui.click()

    pyautogui.alert("拟人移动演示完成！", title="贝塞尔曲线鼠标 Demo")


if __name__ == "__main__":
    try:
        demo()
    except pyautogui.FailSafeException:
        print("\n⚠️ 程序因触发 FAILSAFE（鼠标移至左上角）而终止。")
    except KeyboardInterrupt:
        print("\n🛑 用户手动中断程序。")