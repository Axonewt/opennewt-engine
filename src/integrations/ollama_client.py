"""
Ollama Client - Ollama API 封装（兼容柚子服务器）
================================================

支持 OpenAI 兼容的 Ollama API（如柚子服务器 GLM-4）
"""

import requests
from typing import Dict, List, Optional, Any
from dataclasses import dataclass


@dataclass
class OllamaResponse:
    """Ollama 响应"""
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    finish_reason: str = "stop"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "finish_reason": self.finish_reason
        }


class OllamaClient:
    """Ollama API 客户端（OpenAI 兼容）"""
    
    def __init__(self, base_url: str = "http://127.0.0.1:11434"):
        """
        初始化 Ollama 客户端
        
        Args:
            base_url: Ollama 服务器地址（默认本地 Ollama）
        """
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
    
    def chat_completion(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        n: int = 1
    ) -> OllamaResponse:
        """
        调用 Ollama API（原生格式）
        
        Args:
            model: 模型名称（如 "glm-4.7-flash:latest"）
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大生成 token 数
            n: 生成数量（目前只支持 n=1）
            
        Returns:
            Ollama 响应
        """
        # 构建请求（Ollama 原生格式）
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": model,
            "messages": messages,
            "stream": False  # 不使用流式响应
        }
        
        # 只在需要时添加 options
        if temperature != 0.7 or max_tokens != 4096:
            payload["options"] = {}
            if temperature != 0.7:
                payload["options"]["temperature"] = temperature
            if max_tokens != 4096:
                payload["options"]["num_predict"] = max_tokens
        
        try:
            response = self.session.post(url, json=payload, timeout=120)
            response.raise_for_status()
            
            data = response.json()
            
            # 解析响应（Ollama 格式）
            message = data.get("message", {})
            text = message.get("content", "")
            
            # Token 统计
            eval_count = data.get("eval_count", 0)  # 输出 tokens
            prompt_eval_count = data.get("prompt_eval_count", 0)  # 输入 tokens
            
            # Debug: 打印响应（可选）
            # print(f"DEBUG: Response text length: {len(text)}")
            # if not text:
            #     print(f"DEBUG: Full response: {data}")
            
            return OllamaResponse(
                text=text,
                model=model,
                input_tokens=prompt_eval_count,
                output_tokens=eval_count,
                total_tokens=prompt_eval_count + eval_count,
                finish_reason=data.get("done_reason", "stop")
            )
            
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Ollama API call failed: {e}")
    
    def test_connection(self) -> bool:
        """测试连接"""
        try:
            url = f"{self.base_url}/api/tags"
            response = self.session.get(url, timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def list_models(self) -> List[str]:
        """列出可用模型"""
        try:
            url = f"{self.base_url}/api/tags"
            response = self.session.get(url, timeout=5)
            response.raise_for_status()
            
            data = response.json()
            models = [model["name"] for model in data.get("models", [])]
            return models
            
        except Exception as e:
            print(f"WARNING: Failed to list models: {e}")
            return []


# ============================================================================
# 测试和示例
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🧪 Ollama Client 测试")
    print("=" * 60)
    print()
    
    # 创建客户端（连接到柚子服务器）
    client = OllamaClient("http://localhost:5051")
    
    # 测试连接
    print("🔍 测试连接...")
    if client.test_connection():
        print("✅ 连接成功！")
    else:
        print("❌ 连接失败，请检查柚子服务器是否运行")
        exit(1)
    
    print()
    
    # 列出模型
    print("📋 可用模型:")
    models = client.list_models()
    for model in models:
        print(f"  - {model}")
    
    print()
    
    # 测试生成
    print("\nTesting generation...")
    try:
        response = client.chat_completion(
            model="glm4",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Explain neural plasticity in one sentence."}
            ],
            temperature=0.7,
            max_tokens=100
        )
        
        print("OK: Generation successful!")
        print(f"   Response: {response.text}")
        print(f"   Tokens: {response.total_tokens} (input: {response.input_tokens}, output: {response.output_tokens})")
        
    except Exception as e:
        print(f"ERROR: Generation failed: {e}")
    
    print()
    print("=" * 60)
