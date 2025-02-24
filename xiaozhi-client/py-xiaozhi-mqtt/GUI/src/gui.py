import threading
import tkinter as tk
from tkinter import ttk
import src.config
import socket
import time

class GUI:
    def __init__(
        self,
        mqtt_client
    ):
        self.mqtt_client = mqtt_client
        """创建 GUI 界面"""
        root = tk.Tk()
        self.root = root
        self.root.title("小智语音控制")
        self.root.geometry("300x200")

        # 状态显示
        self.status_frame = ttk.Frame(root)
        self.status_frame.pack(pady=10)

        self.status_label = ttk.Label(self.status_frame, text="状态: 未连接")
        self.status_label.pack(side=tk.LEFT)

        # 音量控制
        self.volume_frame = ttk.Frame(root)
        self.volume_frame.pack(pady=10)

        ttk.Label(self.volume_frame, text="音量:").pack(side=tk.LEFT)
        self.volume_scale = ttk.Scale(
            self.volume_frame,
            from_=0,
            to=100,
            command=lambda v: self.update_volume(int(float(v)))
        )
        self.volume_scale.set(50)
        self.volume_scale.pack(side=tk.LEFT, padx=10)

        # 控制按钮
        self.btn_frame = ttk.Frame(root)
        self.btn_frame.pack(pady=20)

        self.talk_btn = ttk.Button(self.btn_frame, text="按住说话")
        self.talk_btn.bind("<ButtonPress-1>", self.on_button_press)
        self.talk_btn.bind("<ButtonRelease-1>", self.on_button_release)
        self.talk_btn.pack(side=tk.LEFT, padx=10)

        # 状态更新线程
        threading.Thread(target=self.update_status, daemon=True).start()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.mainloop()

    def on_button_press(self, event):
        """按钮按下事件处理
        功能流程：
        1. 检查连接状态，必要时重建连接
        2. 发送hello协议建立会话
        3. 如果正在TTS播放则发送终止指令
        4. 发送listen指令启动语音采集
        """
        # 检查连接状态和会话
        if not self.mqtt_client.conn_state or not self.mqtt_client.session_id:
            # 清理旧连接
            if src.config.udp_socket:
                src.config.udp_socket.close()
                src.config.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # 发送设备握手协议
            hello_msg = {
                "type": "hello",
                "version": 3,
                "transport": "udp",
                "audio_params": {
                    "format": "opus",
                    "sample_rate": 16000,  # 16kHz采样率
                    "channels": 1,  # 单声道
                    "frame_duration": 60  # 60ms帧时长
                }
            }
            self.mqtt_client.publish(hello_msg)


        # 中断正在播放的语音
        if self.mqtt_client.tts_state in ["start", "entence_start"]:
            self.mqtt_client.publish({
                "type": "abort"
            })

        # 启动语音采集
        session_id = self.mqtt_client.get_session_id()
        if session_id:
            listen_msg = {
                "session_id": session_id,
                "type": "listen",
                "state": "start",
                "mode": "manual"
            }
            self.mqtt_client.publish(listen_msg)

    def on_button_release(self, event):
        """按钮释放事件处理
        发送停止录音指令
        """
        session_id = self.mqtt_client.get_session_id()
        if session_id:
            stop_msg = {
                "session_id": session_id,
                "type": "listen",
                "state": "stop"
            }
            self.mqtt_client.publish(stop_msg)

    def update_status(self):
        """更新状态显示"""
        status = "已连接" if self.mqtt_client.conn_state else "未连接"
        self.status_label.config(text=f"状态: {status} | TTS状态: {self.mqtt_client.tts_state}")
        self.root.after(1000, self.update_status)

    def on_close(self):
        """关闭窗口时退出"""
        self.root.destroy()


    def update_volume(self, volume: int):
        """更新系统音量
        Args:
            volume: 音量值(0-100)
        """
        try:
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            volume_control = cast(interface, POINTER(IAudioEndpointVolume))

            # 将0-100的值转换为-65.25到0的分贝值
            volume_db = -65.25 * (1 - volume/100.0)
            volume_control.SetMasterVolumeLevel(volume_db, None)
        except Exception as e:
            print(f"设置音量失败: {e}")
