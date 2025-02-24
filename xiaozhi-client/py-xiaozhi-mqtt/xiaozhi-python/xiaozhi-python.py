#!/usr/bin/python
# -*- coding: UTF-8 -*-

import json
import threading
import pyaudio
import opuslib
import websocket
from pynput import keyboard as pynput_keyboard
import logging

# 设置交流模式，自动模式自动识别语音，手动模式长按空格键问答
# 自动模式下，如果连接已经建立，空格键按下为打断当前对话，如果连接已经失效，则重建连接
# 手动模式下，如果连接已经建立，长按空格键进行对话，如果连接已经失效，则重建连接
is_manualmode = False  #True 手动模式，False自动模式

# 初始化状态变量
listen_state = "stop"
tts_state = "idle"
key_state = "release"
p = None
ws = None
is_connected = False  # 标志位，用于判断 WebSocket 连接是否建立
send_audio_thread = None

# 记录会话 type state session_id等
msg_info = {"type": "hello", "session_id": "3a66666c"}

# 访问令牌、设备 MAC 地址和设备 UUID
access_token = "test-token"
device_mac = "9c:29:76:21:c8:d9"
device_uuid = "test-uuid"

# 音频参数
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK = 960  # 60ms 的音频数据量（16000 * 0.06）

# 构建请求头
headers = {
    "Authorization": f"Bearer {access_token}",
    "Protocol-Version": "1",
    "Device-Id": device_mac,
    "Client-Id": device_uuid
}
ws_url = "wss://api.tenclass.net/xiaozhi/v1/"

# 配置日志记录
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 发送文本消息（json)
def send_json_message(message):
    global ws
    try:
        ws.send(json.dumps(message))
        logging.info(f"send message: {message}")
    except Exception as e:
        logging.error(f"发送消息时出错: {e}")

# 发送语音二进制消息
def send_audio():
    global listen_state, input_stream, ws, is_connected
    while True:
        if listen_state == "stop" or not is_connected or input_stream.is_stopped():
            continue
        try:
            # 读取音频数据
            pcm_data = input_stream.read(CHUNK)
            # 编码为 OPUS 数据
            opus_data = encoder.encode(pcm_data, CHUNK)
            # 发送 OPUS 数据
            if ws and is_connected:
                ws.send(opus_data, opcode=websocket.ABNF.OPCODE_BINARY)
        except Exception as e:
            logging.error(f"读取或发送音频数据时出错: {e}")

# 空格键按下事件处理
def on_space_key_press(event):
    global key_state, msg_info, listen_state, ws, is_connected, tts_state, is_manualmode
    if key_state == "press":
        return
    key_state = "press"

    # 判断是否需要重建 WebSocket 连接
    if not is_connected:
        # 创建 WebSocket 连接
        ws = websocket.WebSocketApp(ws_url,
                                    on_open=on_open,
                                    on_message=on_message,
                                    on_error=on_error,
                                    on_close=on_close,
                                    header=headers)
        # 启动 WebSocket 线程
        threading.Thread(target=ws.run_forever).start()
    else:
        if tts_state == "start" or tts_state == "sentence_start":
            # 在播放状态下发送abort消息
            send_json_message({"type": "abort"})

        if is_manualmode:
            # 发送start listen消息
            msg = {"session_id": msg_info['session_id'], "type": "listen", "state": "start", "mode": "manual"}
            send_json_message(msg)
            listen_state="start"

# 空格键松开事件处理
def on_space_key_release(event):
    global msg_info, key_state, listen_state, ws, is_manualmode
    key_state = "release"
    if is_manualmode:
        # 发送stop listen消息
        if is_connected:
            msg = {"session_id": msg_info['session_id'], "type": "listen", "state": "stop"}
            send_json_message(msg)

def on_press(key):
    if key == pynput_keyboard.Key.space:
        on_space_key_press(None)

def on_release(key):
    if key == pynput_keyboard.Key.space:
        on_space_key_release(None)
    # Stop listener
    if key == pynput_keyboard.Key.esc:
        return False

# 接收服务器消息处理
def on_message(ws, received_message):
    global msg_info, tts_state, send_audio_thread, listen_state, is_manualmode
    if isinstance(received_message, bytes):# 处置二进制音频流
        try:
            # 解码 OPUS 数据为 PCM 数据
            pcm_data = decoder.decode(received_message, CHUNK)
            # 播放解码后的 PCM 数据
            output_stream.write(pcm_data)
        except Exception as e:
            logging.error(f"解码或播放音频时出错: {e}")
    else:# 处置文本类消息
        try:
            msg = json.loads(received_message)
            logging.info(f"recv msg: {msg}")
            if msg['type'] == 'hello':
                msg_info = msg

                # 检查send_audio_thread线程是否启动
                if send_audio_thread is None or not send_audio_thread.is_alive():
                    # 启动一个线程，用于发送音频数据
                    send_audio_thread = threading.Thread(target=send_audio)
                    send_audio_thread.start()
                else:
                    logging.info("send_audio_thread is alive")

            if msg['type'] == 'tts':
                tts_state = msg['state']

            # hello握手后或者前一次语音发送完成后启动自动监听
            if msg['type'] == 'stt' or msg['type'] == 'hello':
                if not is_manualmode:
                    # 启动自动识别消息
                    msg = {"session_id": msg_info['session_id'], "type": "listen", "state": "start", "mode": "auto"}
                    send_json_message(msg)
                    listen_state = "start"

            # 收到断开会话消息处理
            if msg['type'] == 'goodbye' and msg['session_id'] == msg_info['session_id']:
                logging.info(f"recv good bye msg")
                msg_info['session_id'] = None

        except json.JSONDecodeError:
            logging.error("无法解析接收到的消息，不是有效的 JSON 格式")

def on_error(ws, error):
    logging.error(f"发生错误: {error}")

def on_open(ws):
    global is_connected, msg_info, listen_state
    logging.info("WebServer connected by WebSocket !")
    logging.info("==================================")
    # websocket连接成功后发送hello消息
    hello_msg = {"type": "hello", "version": 1, "transport": "websocket",
                 "audio_params": {"format": "opus", "sample_rate": 16000, "channels": 1, "frame_duration": 60}}
    send_json_message(hello_msg)
    is_connected = True

def on_close(ws, close_status_code, close_msg):
    global is_connected, listen_state
    is_connected=False
    listen_state="stop"
    logging.info("==================================================")
    logging.info("WebServer is closed! Press “Space” Key to connect again!")


if __name__ == "__main__":
    try:
        # 监听键盘按键
        listener = pynput_keyboard.Listener(on_press=on_press, on_release=on_release)
        listener.start()

        # 创建 PyAudio 对象
        p = pyaudio.PyAudio()

        # 打开输入音频流
        input_stream = p.open(format=pyaudio.paInt16,
                              channels=CHANNELS,
                              rate=SAMPLE_RATE,
                              input=True,
                              frames_per_buffer=CHUNK)
        # 创建 OPUS 编码器用于发送音频
        encoder = opuslib.Encoder(SAMPLE_RATE, CHANNELS, opuslib.APPLICATION_AUDIO)


        # 打开输出音频流用于播放接收到的音频
        output_stream = p.open(format=pyaudio.paInt16,
                               channels=CHANNELS,
                               rate=SAMPLE_RATE,
                               output=True,
                               frames_per_buffer=CHUNK)
        # 创建 OPUS 解码器用于接收音频
        decoder = opuslib.Decoder(SAMPLE_RATE, CHANNELS)

        # 创建 WebSocket 连接
        ws = websocket.WebSocketApp(ws_url,
                                    on_open=on_open,
                                    on_message=on_message,
                                    on_error=on_error,
                                    on_close=on_close,
                                    header=headers)
        # 启动 WebSocket 线程
        websocket_thread = threading.Thread(target=ws.run_forever)
        websocket_thread.start()

        # 等待键盘监听线程结束
        listener.join()

    except Exception as e:
        logging.error(f"程序发生异常: {e}")
    finally:
        # 停止 WebSocket 线程
        if ws:
            ws.close()
        if websocket_thread:
            websocket_thread.join()
        # 确保资源正确释放
        if input_stream:
            input_stream.stop_stream()
            input_stream.close()
        if output_stream:
            output_stream.stop_stream()
            output_stream.close()
        if p:
            p.terminate()
        if listener:
            listener.stop()
