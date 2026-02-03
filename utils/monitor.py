# utils/monitor.py
import psutil
import datetime
import pandas as pd

class SystemMonitor:
    """
    负责监控宿主机的系统状态。
    """
    @staticmethod
    def get_system_metrics():
        """获取CPU、内存、电池等基础信息"""
        try:
            cpu_usage = psutil.cpu_percent(interval=None) # Non-blocking
            memory = psutil.virtual_memory()
            battery = psutil.sensors_battery()
            
            return {
                "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
                "cpu_percent": cpu_usage,
                "memory_percent": memory.percent,
                "memory_used_gb": round(memory.used / (1024**3), 2),
                "memory_total_gb": round(memory.total / (1024**3), 2),
                "battery_percent": battery.percent if battery else 100,
                "power_plugged": battery.power_plugged if battery else True
            }
        except Exception:
            # Fallback
            return {
                "cpu_percent": 0, "memory_percent": 0, "memory_used_gb": 0, "memory_total_gb": 0
            }

    @staticmethod
    def get_process_list(limit=10):
        """获取占用资源最高的进程列表"""
        processes = []
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
                try:
                    p_info = proc.info
                    # 过滤掉空闲进程
                    if p_info['cpu_percent'] is None: p_info['cpu_percent'] = 0.0
                    if p_info['memory_percent'] is None: p_info['memory_percent'] = 0.0
                    processes.append(p_info)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
        except Exception:
            pass
        
        # 按CPU使用率排序
        df = pd.DataFrame(processes)
        if not df.empty:
            df = df.sort_values(by='cpu_percent', ascending=False).head(limit)
        else:
            df = pd.DataFrame(columns=['pid', 'name', 'cpu_percent', 'memory_percent'])
        return df

    @staticmethod
    def get_disk_usage():
        """获取磁盘使用情况"""
        try:
            disk = psutil.disk_usage('C:\\')
            return {
                "total_gb": round(disk.total / (1024**3), 2),
                "used_gb": round(disk.used / (1024**3), 2),
                "percent": disk.percent
            }
        except Exception:
            return {"total_gb": 0, "used_gb": 0, "percent": 0}