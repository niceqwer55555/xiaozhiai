# 使用Python 3.11基础镜像
FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 使用清华源替换默认的apt源
RUN rm -rf /etc/apt/sources.list.d/* && \
    echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm main contrib non-free non-free-firmware" > /etc/apt/sources.list && \
    echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-updates main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bookworm-backports main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian-security bookworm-security main contrib non-free non-free-firmware" >> /etc/apt/sources.list

# 安装系统依赖
RUN apt-get update && \
    apt-get install -y \
        build-essential \
        pkg-config \
        python3-dev \
        python3-setuptools \
        python3-wheel \
        python3-pip \
        python3-numpy \
        python3-scipy \
        libopus0 \
        libopus-dev \
        opus-tools \
        libsndfile1 \
        libsndfile1-dev \
        portaudio19-dev \
        libportaudio2 \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# 设置pip源为清华源
RUN python3 -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple pip -U && \
    python3 -m pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 复制 requirements.txt
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir wheel setuptools && \
    pip install --no-cache-dir opuslib==3.0.1 && \
    pip install --no-cache-dir -r requirements.txt

# 复制项目文件
COPY . .

# 暴露端口
EXPOSE 5001 5002

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV LD_LIBRARY_PATH=/usr/local/lib:/usr/lib:/lib
ENV PYTHONPATH=/app

# 启动命令
CMD ["python3", "app.py"] 