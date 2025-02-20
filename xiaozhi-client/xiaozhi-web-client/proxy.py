import asyncio
import websockets
import os
import json
from dotenv import load_dotenv
import uuid
import opuslib
import wave
import io
import numpy as np
from scipy import signal
import soundfile as sf
from urllib.parse import urlparse

load_dotenv()

# 配置
WS_URL = os.getenv("WS_URL")
if not WS_URL:
    print("警告: 未设置WS_URL环境变量，请检查.env文件")
    WS_URL = "ws://localhost:9005"  # 默认值改为localhost

TOKEN = os.getenv("DEVICE_TOKEN")
if not TOKEN:
    print("警告: 未设置DEVICE_TOKEN环境变量，请检查.env文件")
    TOKEN = "123"  # 默认值

LOCAL_PROXY_URL = os.getenv("LOCAL_PROXY_URL", "ws://localhost:5002")
try:
    # 从LOCAL_PROXY_URL中提取主机和端口
    parsed_url = urlparse(LOCAL_PROXY_URL)
    PROXY_HOST = '0.0.0.0'  # 总是监听在所有网络接口上
    PROXY_PORT = parsed_url.port or 5002
except Exception as e:
    print(f"解析LOCAL_PROXY_URL失败: {e}，使用默认值")
    PROXY_HOST = '0.0.0.0'
    PROXY_PORT = 5002

def get_mac_address():
    mac = uuid.getnode()
    return ':'.join(['{:02x}'.format((mac >> elements) & 0xff) for elements in range(0,8*6,8)][::-1])

def pcm_to_opus(pcm_data):
    """将PCM音频数据转换为Opus格式"""
    try:
        # 创建编码器：16kHz, 单声道, VOIP模式
        encoder = opuslib.Encoder(16000, 1, 'voip')
        
        try:
            # 确保PCM数据是Int16格式
            pcm_array = np.frombuffer(pcm_data, dtype=np.int16)
            
            # 编码PCM数据，每帧960个采样点
            opus_data = encoder.encode(pcm_array.tobytes(), 960)  # 60ms at 16kHz
            return opus_data
            
        except opuslib.OpusError as e:
            print(f"Opus编码错误: {e}, 数据长度: {len(pcm_data)}")
            return None
            
    except Exception as e:
        print(f"Opus初始化错误: {e}")
        return None

def opus_to_wav(opus_data):
    """将Opus音频数据转换为WAV格式"""
    try:
        # 创建解码器：16kHz, 单声道
        decoder = opuslib.Decoder(16000, 1)
        
        try:
            # 解码Opus数据
            pcm_data = decoder.decode(opus_data, 960)  # 使用960采样点
            if pcm_data:
                # 将PCM数据转换为numpy数组
                audio_array = np.frombuffer(pcm_data, dtype=np.int16)
                
                # 创建WAV文件
                wav_io = io.BytesIO()
                with wave.open(wav_io, 'wb') as wav:
                    wav.setnchannels(1)  # 单声道
                    wav.setsampwidth(2)  # 16位
                    wav.setframerate(16000)  # 16kHz
                    wav.writeframes(audio_array.tobytes())
                return wav_io.getvalue()
            return None
            
        except opuslib.OpusError as e:
            print(f"Opus解码错误: {e}, 数据长度: {len(opus_data)}")
            return None
            
    except Exception as e:
        print(f"音频处理错误: {e}")
        return None

class AudioProcessor:
    def __init__(self, buffer_size=960):
        self.buffer_size = buffer_size
        self.buffer = np.array([], dtype=np.float32)
        self.sample_rate = 16000
        
    def reset_buffer(self):
        self.buffer = np.array([], dtype=np.float32)
        
    def process_audio(self, input_data):
        # 将输入数据转换为float32数组
        input_array = np.frombuffer(input_data, dtype=np.float32)
        
        # 将新数据添加到缓冲区
        self.buffer = np.append(self.buffer, input_array)
        
        chunks = []
        # 当缓冲区达到指定大小时处理数据
        while len(self.buffer) >= self.buffer_size:
            # 提取数据
            chunk = self.buffer[:self.buffer_size]
            self.buffer = self.buffer[self.buffer_size:]
            
            # 转换为16位整数
            pcm_data = (chunk * 32767).astype(np.int16)
            chunks.append(pcm_data.tobytes())
            
        return chunks
    
    def process_remaining(self):
        if len(self.buffer) > 0:
            # 转换为16位整数
            pcm_data = (self.buffer * 32767).astype(np.int16)
            self.buffer = np.array([], dtype=np.float32)
            return [pcm_data.tobytes()]
        return []

class WebSocketProxy:
    def __init__(self):
        self.device_id = get_mac_address()
        self.enable_token = os.getenv("ENABLE_TOKEN", "true").lower() == "true"
        self.token = os.getenv("DEVICE_TOKEN", "123")
        
        # 根据 token 开关设置 headers
        self.headers = {'device-id': self.device_id}
        if self.enable_token:
            self.headers['Authorization'] = f'Bearer {self.token}'
            
        self.audio_processor = AudioProcessor(buffer_size=960)
        self.decoder = opuslib.Decoder(16000, 1)  # 创建一个持久的解码器实例
        self.audio_buffer = bytearray()  # 改用 bytearray 存储音频数据
        self.is_first_audio = True
        self.total_samples = 0  # 跟踪总采样数

    def create_wav_header(self, total_samples):
        """创建WAV文件头"""
        header = bytearray(44)  # WAV header is 44 bytes
        
        # RIFF header
        header[0:4] = b'RIFF'
        header[4:8] = (total_samples * 2 + 36).to_bytes(4, 'little')  # File size
        header[8:12] = b'WAVE'
        
        # fmt chunk
        header[12:16] = b'fmt '
        header[16:20] = (16).to_bytes(4, 'little')  # Chunk size
        header[20:22] = (1).to_bytes(2, 'little')  # Audio format (PCM)
        header[22:24] = (1).to_bytes(2, 'little')  # Num channels
        header[24:28] = (16000).to_bytes(4, 'little')  # Sample rate
        header[28:32] = (32000).to_bytes(4, 'little')  # Byte rate
        header[32:34] = (2).to_bytes(2, 'little')  # Block align
        header[34:36] = (16).to_bytes(2, 'little')  # Bits per sample
        
        # data chunk
        header[36:40] = b'data'
        header[40:44] = (total_samples * 2).to_bytes(4, 'little')  # Data size
        
        return header

    async def proxy_handler(self, websocket):
        """处理来自浏览器的WebSocket连接"""
        try:
            print(f"New client connection from {websocket.remote_address}")
            async with websockets.connect(WS_URL, extra_headers=self.headers) as server_ws:
                print(f"Connected to server with headers: {self.headers}")
                
                # 创建任务
                client_to_server = asyncio.create_task(self.handle_client_messages(websocket, server_ws))
                server_to_client = asyncio.create_task(self.handle_server_messages(server_ws, websocket))
                
                # 等待任意一个任务完成
                done, pending = await asyncio.wait(
                    [client_to_server, server_to_client],
                    return_when=asyncio.FIRST_COMPLETED
                )
                
                # 取消其他任务
                for task in pending:
                    task.cancel()
                    
        except Exception as e:
            print(f"Proxy error: {e}")
        finally:
            print("Client connection closed")

    async def handle_server_messages(self, server_ws, client_ws):
        """处理来自服务器的消息"""
        try:
            async for message in server_ws:
                if isinstance(message, str):
                    try:
                        msg_data = json.loads(message)
                        if msg_data.get('type') == 'tts' and msg_data.get('state') == 'start':
                            # 新的音频流开始，重置状态
                            if len(self.audio_buffer) > 44:  # 如果还有未播放的数据，先发送
                                size_bytes = (self.total_samples * 2 + 36).to_bytes(4, 'little')
                                data_bytes = (self.total_samples * 2).to_bytes(4, 'little')
                                self.audio_buffer[4:8] = size_bytes
                                self.audio_buffer[40:44] = data_bytes
                                await client_ws.send(bytes(self.audio_buffer))
                            
                            # 完全重置状态
                            self.audio_buffer = bytearray()
                            self.is_first_audio = True
                            self.total_samples = 0
                            self.decoder = opuslib.Decoder(16000, 1)  # 重新创建解码器
                            
                        elif msg_data.get('type') == 'tts' and msg_data.get('state') == 'stop':
                            # 音频流结束，发送剩余数据
                            if len(self.audio_buffer) > 44:  # 确保有音频数据
                                # 更新最终的WAV头
                                size_bytes = (self.total_samples * 2 + 36).to_bytes(4, 'little')
                                data_bytes = (self.total_samples * 2).to_bytes(4, 'little')
                                self.audio_buffer[4:8] = size_bytes
                                self.audio_buffer[40:44] = data_bytes
                                await client_ws.send(bytes(self.audio_buffer))
                                
                                # 等待一小段时间确保音频播放完成
                                await asyncio.sleep(0.1)
                                
                                # 完全重置状态
                                self.audio_buffer = bytearray()
                                self.is_first_audio = True
                                self.total_samples = 0
                                self.decoder = opuslib.Decoder(16000, 1)  # 重新创建解码器
                                
                        await client_ws.send(message)
                    except json.JSONDecodeError:
                        await client_ws.send(message)
                else:
                    try:
                        # 解码Opus数据
                        pcm_data = self.decoder.decode(message, 960)
                        if pcm_data:
                            # 计算采样数
                            samples = len(pcm_data) // 2  # 16位音频，每个采样2字节
                            self.total_samples += samples

                            if self.is_first_audio:
                                # 第一个音频片段，写入WAV头
                                self.audio_buffer.extend(self.create_wav_header(self.total_samples))
                                self.is_first_audio = False
                            
                            # 添加音频数据
                            self.audio_buffer.extend(pcm_data)
                            
                            # 当缓冲区达到一定大小时发送数据
                            if len(self.audio_buffer) >= 32044:  # WAV头(44字节) + 16000个采样(32000字节)
                                # 更新WAV头中的数据大小
                                size_bytes = (self.total_samples * 2 + 36).to_bytes(4, 'little')
                                data_bytes = (self.total_samples * 2).to_bytes(4, 'little')
                                self.audio_buffer[4:8] = size_bytes
                                self.audio_buffer[40:44] = data_bytes
                                
                                # 发送数据
                                await client_ws.send(bytes(self.audio_buffer))
                                
                                # 完全重置缓冲区
                                self.audio_buffer = bytearray()
                                self.is_first_audio = True
                                self.total_samples = 0
                    except Exception as e:
                        print(f"音频处理错误: {e}")
        except Exception as e:
            print(f"Server message handling error: {e}")

    async def handle_client_messages(self, client_ws, server_ws):
        """处理来自客户端的消息"""
        try:
            async for message in client_ws:
                if isinstance(message, str):
                    try:
                        msg_data = json.loads(message)
                        if msg_data.get('type') == 'reset':
                            self.audio_processor.reset_buffer()
                        elif msg_data.get('type') == 'getLastData':
                            # 处理剩余数据
                            remaining_chunks = self.audio_processor.process_remaining()
                            for chunk in remaining_chunks:
                                opus_data = pcm_to_opus(chunk)
                                if opus_data:
                                    await server_ws.send(opus_data)
                            # 发送处理完成消息
                            await client_ws.send(json.dumps({'type': 'lastData'}))
                        else:
                            await server_ws.send(message)
                    except json.JSONDecodeError:
                        await server_ws.send(message)
                else:
                    print("处理客户端音频数据")
                    try:
                        # 确保数据是 Float32Array 格式
                        audio_data = np.frombuffer(message, dtype=np.float32)
                        if len(audio_data) > 0:
                            # 使用AudioProcessor处理音频数据
                            chunks = self.audio_processor.process_audio(audio_data.tobytes())
                            for chunk in chunks:
                                opus_data = pcm_to_opus(chunk)
                                if opus_data:
                                    await server_ws.send(opus_data)
                                else:
                                    print("音频编码失败")
                        else:
                            print("收到空的音频数据")
                    except Exception as e:
                        print(f"音频处理错误: {e}")
        except Exception as e:
            print(f"Client message handling error: {e}")

    async def main(self):
        """启动代理服务器"""
        print(f"Starting proxy server on {PROXY_HOST}:{PROXY_PORT}")
        print(f"Device ID: {self.device_id}")
        print(f"Token: {TOKEN}")
        print(f"Target WS URL: {WS_URL}")
        
        async with websockets.serve(self.proxy_handler, PROXY_HOST, PROXY_PORT):
            await asyncio.Future()  # 运行直到被取消

if __name__ == "__main__":
    proxy = WebSocketProxy()
    asyncio.run(proxy.main()) 