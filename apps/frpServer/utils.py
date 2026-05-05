import subprocess
import tomlkit
import secrets
import string
import requests
import os

# ================= 配置常量 =================

# 核心系统工具绝对路径 (请在终端通过 which sudo/systemctl 确认)
SUDO_PATH = "/usr/bin/sudo"
SYSTEMCTL_PATH = "/usr/bin/systemctl"

# FRP 文件路径
FRP_PATH = "/frp/frp_0.65.0_linux_amd64"
CONFIG_FILE = os.path.join(FRP_PATH, "frps.toml")

# FRP API 配置 (用于获取实时流量状态)
FRP_API_URL = "http://127.0.0.1:7500"
FRP_ADMIN_USER = "admin"
FRP_ADMIN_PWD = "admin123"

# ================= 核心工具函数 =================

def _run_frp_command(action):
    """
    内部封装：使用安全的方式执行 systemctl 操作
    action: "start", "stop", "restart"
    """
    if action not in ["start", "stop", "restart"]:
        return False, "非法的服务操作"

    # 构造命令列表，不使用 shell=True 更加安全
    cmd = [SUDO_PATH, SYSTEMCTL_PATH, action, "frps"]
    
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # 将错误和正常输出合并
            encoding='utf-8',
            timeout=10
        )
        
        if result.returncode == 0:
            return True, f"服务 {action} 成功"
        else:
            return False, f"执行失败: {result.stdout}"
            
    except subprocess.TimeoutExpired:
        return False, "操作超时，请检查系统状态"
    except Exception as e:
        return False, f"系统异常: {str(e)}"


def read_config():
    """读取 frps.toml 配置"""
    if not os.path.exists(CONFIG_FILE):
        return None, f"配置文件不存在: {CONFIG_FILE}"
    
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            # tomlkit 会保留原始文件的注释和格式
            data = tomlkit.load(f)
            return data, None
    except Exception as e:
        return None, f"解析配置文件失败: {str(e)}"


def update_frp_token():
    """生成新 Token 并更新配置文件"""
    data, error = read_config()
    if error:
        return False, error
    
    # 生成 16位 强随机 Token
    new_token = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
    
    try:
        # 确保 [auth] 部分存在
        if 'auth' not in data:
            data['auth'] = {}
        
        data['auth']['token'] = new_token
        
        # 写回文件
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            tomlkit.dump(data, f)
            
        return True, new_token
    except Exception as e:
        return False, f"写入新Token失败: {str(e)}"


def get_frp_stats():
    """通过 FRP Dashboard API 获取实时运行数据"""
    try:
        url = f"{FRP_API_URL}/api/serverinfo"
        response = requests.get(
            url, 
            auth=(FRP_ADMIN_USER, FRP_ADMIN_PWD), 
            timeout=2
        )
        if response.status_code == 200:
            return True, response.json()
        elif response.status_code == 401:
            return False, "FRP API 认证失败，请检查用户名密码"
        else:
            return False, f"FRP 接口响应异常: {response.status_code}"
    except requests.exceptions.ConnectionError:
        return False, "无法连接到 FRP API (服务可能未启动)"
    except Exception as e:
        return False, f"获取状态异常: {str(e)}"


# ================= 供外部 View 调用的接口 =================

def start_service():
    """启动服务"""
    return _run_frp_command("start")

def stop_service():
    """停止服务"""
    return _run_frp_command("stop")

def restart_service():
    """重启服务"""
    return _run_frp_command("restart")