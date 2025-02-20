from flask import Flask, render_template, jsonify, request
import os
import uuid
from dotenv import load_dotenv, set_key, find_dotenv
import websockets
import asyncio
import json
import threading
import multiprocessing
import atexit
import socket
from proxy import WebSocketProxy  # 导入 proxy.py 中的 WebSocketProxy 类

# 默认配置
DEFAULT_CONFIG = {
    'WS_URL': 'ws://localhost:8000/xiaozhi/v1/',
    'DEVICE_TOKEN': '123',
    'WEB_PORT': '5001',
    'PROXY_PORT': '5002',
    'ENABLE_TOKEN': 'true',  # 新增token开关配置
    'LOCAL_PROXY_URL': 'ws://localhost:5002'  # 新增本地代理地址配置
}

def ensure_env_file():
    """确保.env文件存在，如果不存在则创建默认配置"""
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    if not os.path.exists(env_path):
        print("未找到.env文件，创建默认配置...")
        with open(env_path, 'w') as f:
            for key, value in DEFAULT_CONFIG.items():
                f.write(f"{key}={value}\n")
    return env_path

# 确保.env文件存在并加载配置
env_path = ensure_env_file()
load_dotenv(env_path)

app = Flask(__name__, static_url_path='/static')

# 获取本机IP
def get_local_ip():
    try:
        # 创建一个UDP socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 连接任意可用地址(这里不会真的建立连接)
        s.connect(('8.8.8.8', 80))
        # 获取本机IP
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '0.0.0.0'

# 配置
WS_URL = os.getenv("WS_URL", DEFAULT_CONFIG['WS_URL'])
if not WS_URL:
    print("警告: 未设置WS_URL环境变量，请检查.env文件")
    WS_URL = "ws://localhost:9005"  # 默认值改为localhost

LOCAL_IP = get_local_ip()
WEB_PORT = int(os.getenv("WEB_PORT", DEFAULT_CONFIG['WEB_PORT']))
PROXY_PORT = int(os.getenv("PROXY_PORT", DEFAULT_CONFIG['PROXY_PORT']))
PROXY_URL = f"ws://{LOCAL_IP}:{PROXY_PORT}"
TOKEN = os.getenv("DEVICE_TOKEN", DEFAULT_CONFIG['DEVICE_TOKEN'])
ENABLE_TOKEN = os.getenv("ENABLE_TOKEN", DEFAULT_CONFIG['ENABLE_TOKEN']).lower() == 'true'

proxy_process = None

def get_mac_address():
    mac = uuid.getnode()
    return ':'.join(['{:02x}'.format((mac >> elements) & 0xff) for elements in range(0,8*6,8)][::-1])

async def test_websocket_connection():
    """测试WebSocket连接"""
    try:
        # 测试代理连接
        async with websockets.connect(PROXY_URL) as ws:
            await ws.close()
            return True, None
    except Exception as e:
        return False, str(e)

@app.route('/')
def index():
    return render_template('index.html', 
                         device_id=get_mac_address(),
                         token=TOKEN,
                         enable_token=ENABLE_TOKEN,
                         ws_url=WS_URL,
                         local_proxy_url=os.getenv("LOCAL_PROXY_URL", DEFAULT_CONFIG['LOCAL_PROXY_URL']))

@app.route('/test_connection', methods=['GET'])
def test_connection():
    try:
        device_id = get_mac_address()
        success, error = asyncio.run(test_websocket_connection())
        
        if success:
            return jsonify({
                'status': 'success',
                'message': '连接测试成功',
                'device_id': device_id,
                'token': TOKEN,
                'ws_url': PROXY_URL
            })
        else:
            return jsonify({
                'status': 'error',
                'message': f'连接测试失败: {error}'
            }), 500
            
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/save_config', methods=['POST'])
def save_config():
    try:
        global proxy_process
        data = request.get_json()
        new_ws_url = data.get('ws_url')
        new_local_proxy_url = data.get('local_proxy_url')
        new_token = data.get('token')
        enable_token = data.get('enable_token', False)
        
        if not new_ws_url or not new_local_proxy_url:
            return jsonify({'success': False, 'error': '服务器地址和本地代理地址不能为空'})
        
        # 更新.env文件
        dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
        set_key(dotenv_path, 'WS_URL', new_ws_url)
        set_key(dotenv_path, 'LOCAL_PROXY_URL', new_local_proxy_url)
        set_key(dotenv_path, 'DEVICE_TOKEN', new_token if new_token else '')
        set_key(dotenv_path, 'ENABLE_TOKEN', str(enable_token).lower())
        
        # 重新加载环境变量
        load_dotenv()
        
        # 重启代理进程
        if proxy_process:
            proxy_process.terminate()
            proxy_process.join()
        
        proxy_process = multiprocessing.Process(target=run_proxy)
        proxy_process.start()
        print(f"Proxy server restarted with new config: WS_URL={new_ws_url}, TOKEN_ENABLED={enable_token}")
        
        return jsonify({'success': True, 'message': '配置已保存并重启代理服务器'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

def cleanup():
    """清理进程"""
    global proxy_process
    if proxy_process:
        proxy_process.terminate()
        proxy_process.join()
        proxy_process = None

def run_proxy():
    """在单独的进程中运行proxy服务器"""
    proxy = WebSocketProxy()
    asyncio.run(proxy.main())

if __name__ == '__main__':
    # 注册退出时的清理函数
    atexit.register(cleanup)
    
    device_id = get_mac_address()
    print(f"Device ID: {device_id}")
    print(f"Token: {TOKEN}")
    print(f"WS URL: {WS_URL}")
    print(f"Proxy URL: {PROXY_URL}")
    print(f"Web server will run on port {WEB_PORT}")
    print(f"Proxy server will run on port {PROXY_PORT}")
    
    # 在单独的进程中启动proxy服务器
    proxy_process = multiprocessing.Process(target=run_proxy)
    proxy_process.start()
    print("Proxy server started in background process")
    
    print("Starting web server...")
    # 禁用调试模式运行Flask
    app.run(host='0.0.0.0', port=WEB_PORT, debug=False) 