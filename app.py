from flask import Flask, render_template, jsonify
from flask_cors import CORS
import requests
from datetime import datetime, timezone
import threading
import time
from collections import deque
import logging
import json
import os
import urllib3

# Suppress InsecureRequestWarning
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# --- CONFIGURATION ---
HISTORY_FILE = 'history.json'
HISTORY_LENGTH = 20  # 20 items * 30 sec = 10 mins
UPDATE_INTERVAL = 30 # Seconds

SITES = {
    'Self-Service': 'https://apps.uillinois.edu/selfservice',
    'Canvas': 'https://canvas.illinois.edu',
    'MyIllini': 'https://myillini.illinois.edu',
    'Course Explorer': 'https://courses.illinois.edu',
    'UIUC Status': 'https://status.illinois.edu',
    'Media Space': 'https://mediaspace.illinois.edu',
    'APPS Directory': 'https://apps.uillinois.edu',
    'Illinois.edu': 'https://illinois.edu',
    'Student Affairs': 'https://studentaffairs.illinois.edu',
    'Admissions': 'https://admissions.illinois.edu',
    'University Housing': 'https://housing.illinois.edu',
    'Library': 'https://library.illinois.edu',
    'Technology Services': 'https://techservices.illinois.edu',
    'Box': 'https://uofi.box.com',
    'Webstore': 'https://webstore.illinois.edu'
}

# --- DATA PERSISTENCE ---
# We use a dictionary of lists instead of deques for JSON compatibility
status_history = {} 
current_status = {}
last_check_time = None


# 全局 Session 对象，用于复用 TCP 连接，提高性能
session = requests.Session()
# 设置请求头，伪装成 Chrome 浏览器，防止被防火墙拦截 (WAF)
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Sec-Fetch-User': '?1',
    'Cache-Control': 'max-age=0',
    'Referer': 'https://www.google.com/',
    'Sec-Ch-Ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"'
})

def check_website(name, url):
    """
    检查单个网站的状态
    :param name: 网站名称
    :param url: 网站 URL
    :return: 包含状态信息的字典
    """
    try:
        start_time = time.time()  # 记录开始时间
        
        # 发送 GET 请求
        # timeout=15: 设置 15 秒超时，防止网络卡顿
        # verify=False: 禁用 SSL 证书验证（解决 Media Space 等网站证书报错问题）
        # allow_redirects=True: 允许自动跳转
        response = session.get(url, timeout=15, verify=False, allow_redirects=True)
        
        # 计算响应时间（毫秒）
        response_time = round((time.time() - start_time) * 1000)
        
        # 判断状态：200, 301, 302 都视为正常
        # 403 有时是防爬虫拦截，但在本监控中严谨起见，非 2xx/3xx 视为异常
        status = 'up' if response.status_code in [200, 301, 302] else 'down'
        
        # 特殊处理 403 Forbidden 错误，标记为防火墙拦截
        if response.status_code == 403:
             status = 'down'
             error_msg = f"403 Forbidden (WAF Block)"
             return {
                'status': status,
                'time': response_time,
                'code': response.status_code,
                'error': error_msg,
                'timestamp': datetime.now(timezone.utc).isoformat()  # 使用 UTC 时间
            }

        return {
            'status': status,
            'time': response_time,
            'code': response.status_code,
            'timestamp': datetime.now(timezone.utc).isoformat()  # 使用 UTC 时间
        }
    except Exception as e:
        # 捕获所有连接异常（如超时、DNS 解析失败等）
        logger.error(f"Error checking {name}: {e}")  # 记录错误日志
        return {
            'status': 'down',
            'time': 0,
            'error': str(e),  # 将具体错误信息返回给前端
            'timestamp': datetime.now(timezone.utc).isoformat()  # 使用 UTC 时间
        }

def monitor_loop():
    """
    后台监控循环线程
    每隔 UPDATE_INTERVAL 秒检查一次所有站点
    """
    global last_check_time
    logger.info("Monitor thread started...")  # 记录线程启动
    while True:
        try:
            # 遍历所有站点进行检查
            for name, url in SITES.items():
                result = check_website(name, url)
                
                # 更新当前状态
                current_status[name] = result
                
                # 更新历史记录
                if name not in status_history:
                    status_history[name] = []
                
                status_history[name].append(result)
                
                # 保持历史记录长度不超过 HISTORY_LENGTH
                if len(status_history[name]) > HISTORY_LENGTH:
                    status_history[name].pop(0)
            
            # 更新最后检查时间 (使用 UTC 时间，并确保包含时区信息 'Z' 以便 JS 正确解析)
            # datetime.utcnow() 是不带时区的，isoformat() 加上 'Z' 表示 UTC
            last_check_time = datetime.now(timezone.utc).isoformat()
            
            logger.info(f"Check complete at {last_check_time}")  # 记录检查完成
            
        except Exception as e:
            logger.error(f"Error in monitor loop: {e}")  # 记录循环中的意外错误
        
        time.sleep(UPDATE_INTERVAL)  # 等待下一次检查

# 启动后台监控线程
# 注意：在 Gunicorn 等生产环境中，需要确保这部分代码能被执行
if not os.environ.get('WERKZEUG_RUN_MAIN'):
    # daemon=True: 守护线程，主程序退出时线程自动退出
    threading.Thread(target=monitor_loop, daemon=True).start()

@app.route('/')
def index():
    """
    首页路由
    渲染 index.html 并注入初始数据
    """
    # 构造初始数据包
    initial_data = {
        'sites': {
            name: {
                'current': current_status.get(name, {}),
                'history': status_history.get(name, []),
                'url': url,
                # 计算在线率 (Uptime)
                'uptime': calculate_uptime(name)
            } for name, url in SITES.items()
        },
        'last_check': last_check_time
    }
    return render_template('index.html', initial_data=initial_data)

@app.route('/api/status')
def get_status():
    """
    API 接口
    返回当前所有站点的 JSON 数据，供前端 AJAX 轮询
    """
    data = {
        'sites': {
            name: {
                'current': current_status.get(name, {}),
                'history': status_history.get(name, []),
                'url': url,
                'uptime': calculate_uptime(name)
            } for name, url in SITES.items()
        },
        'last_check': last_check_time
    }
    return jsonify(data)

def calculate_uptime(name):
    """
    计算在线率辅助函数
    基于内存中的历史数据计算百分比
    """
    history = status_history.get(name, [])
    if not history:
        return 0
    # 统计状态为 'up' 的次数
    up_count = sum(1 for x in history if x['status'] == 'up')
    # 计算百分比并取整
    return int((up_count / len(history)) * 100)

if __name__ == '__main__':
    # 开发环境启动模式
    app.run(debug=True, host='0.0.0.0', port=5000)
