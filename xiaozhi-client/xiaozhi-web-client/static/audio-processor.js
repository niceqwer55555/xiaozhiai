class AudioProcessor extends AudioWorkletProcessor {
    constructor() {
        super();
        this.sampleRate = 16000;
        this.waitingForLastData = false;
        
        this.port.onmessage = (e) => {
            if (e.data.type === 'getLastData') {
                this.waitingForLastData = true;
            }
        };
    }

    process(inputs) {
        const input = inputs[0][0];
        if (!input) return true;

        // 创建一个新的 Float32Array 并复制数据
        const audioData = new Float32Array(input);
        
        // 发送音频数据
        this.port.postMessage(audioData, [audioData.buffer]);

        // 如果正在等待最后的数据，发送完成消息
        if (this.waitingForLastData) {
            this.port.postMessage({ type: 'lastData' });
            this.waitingForLastData = false;
        }

        return true;
    }
}

registerProcessor('audio-processor', AudioProcessor);