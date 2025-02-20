from config.logger import setup_logging
import requests, json
from core.providers.llm.base import LLMProviderBase

TAG = __name__
logger = setup_logging()


class LLMProvider(LLMProviderBase):
    def __init__(self, config):

        self.base_url = config.get("base_url", "http://192.168.137.91:8080")

    def response(self, session_id, dialogue):
        try:
            # Convert dialogue format to Ollama format
            headers = {"Content-Type": "application/json"}
            prompt = ""
            for msg in dialogue:
                if msg["role"] == "system":
                    prompt += f"System: {msg['content']}\n"
                elif msg["role"] == "user":
                    prompt += f"User: {msg['content']}\n"
                elif msg["role"] == "assistant":
                    prompt += f"Assistant: {msg['content']}\n"

            # Make request to Ollama API
            payload = {
            "messages": dialogue
        }
            response = requests.post(
                f"{self.base_url}/v1/chat/completions",
                data=json.dumps(payload),
                headers=headers
            )

            for line in response.iter_lines():
                if line:
                    json_response = json.loads(line)
                    yield json_response["choices"][0]["message"]["content"]

        except Exception as e:
            logger.bind(tag=TAG).error(f"Error in llamacpp response generation: {e}")
            yield "【llamacpp服务响应异常】"
