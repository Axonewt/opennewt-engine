"""
WorkBuddy Client - 通过 CodeBuddy CLI 调用云端 AI
==================================================

将 WorkBuddy 的 CodeBuddy CLI 作为 LLM 后端，
实现与 OllamaClient 相同的 chat_completion() 接口，
可无缝替换 Ollama 作为 Plasticus 的决策大脑。

用法：
    from src.integrations.workbuddy_client import WorkBuddyClient
    
    wb = WorkBuddyClient()
    response = wb.chat_completion(
        model="workbuddy",
        messages=[{"role": "user", "content": "分析这个错误..."}],
        temperature=0.7
    )
    print(response.text)  # WorkBuddy 的 AI 响应

CLI 命令参考（来源: codebuddy.ai/docs）：
    codebuddy -p "查询"                      # 非交互 + 打印后退出
    codebuddy -p --output-format json "查询"   # JSON 输出
    codebuddy -p --system-prompt "角色" "查询"  # 自定义系统提示词
    codebuddy -p -y "查询"                     # 跳过权限确认
"""

import asyncio
import json
import shutil
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

# 复用 OllamaResponse 作为统一接口
try:
    from .ollama_client import OllamaResponse
except ImportError:
    # 允许独立导入
    @dataclass
    class OllamaResponse:
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


class WorkBuddyClient:
    """WorkBuddy CLI 适配器（实现 OllamaClient 相同接口）"""
    
    def __init__(
        self,
        cli_path: Optional[str] = None,
        timeout: int = 120,
        max_turns: int = 5,
        auto_approve: bool = True
    ):
        """
        初始化 WorkBuddy 客户端
        
        Args:
            cli_path: codebuddy CLI 可执行文件路径（None 则自动查找）
            timeout: 命令执行超时（秒）
            max_turns: Agent 最大执行轮次
            auto_approve: 是否自动批准文件操作（-y 参数）
        """
        self.cli_path = cli_path or self._find_cli()
        self.timeout = timeout
        self.max_turns = max_turns
        self.auto_approve = auto_approve
        
        if self.cli_path:
            print(f"[WorkBuddy] CLI found: {self.cli_path}")
        else:
            print("[WorkBuddy] WARNING: codebuddy CLI not found in PATH")
    
    def _find_cli(self) -> Optional[str]:
        """在系统 PATH 中查找 codebuddy CLI"""
        return shutil.which("codebuddy")
    
    def chat_completion(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        n: int = 1
    ) -> OllamaResponse:
        """
        调用 WorkBuddy CLI（接口与 OllamaClient.chat_completion 一致）
        
        Args:
            model: 模型名称（WorkBuddy 模式下忽略，保留接口兼容）
            messages: 消息列表 [{"role": "system/user/assistant", "content": "..."}]
            temperature: 温度参数（WorkBuddy 模式下忽略）
            max_tokens: 最大 token 数（WorkBuddy 模式下忽略）
            n: 生成数量（WorkBuddy 只支持 1）
            
        Returns:
            OllamaResponse（text 字段包含 AI 响应）
        """
        if not self.cli_path:
            raise RuntimeError(
                "WorkBuddy CLI (codebuddy) not found. "
                "Please install CodeBuddy or provide cli_path."
            )
        
        # 从 messages 中提取 system prompt 和 user prompt
        system_prompt = None
        user_content_parts = []
        
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_prompt = content
            elif role == "user":
                user_content_parts.append(content)
            elif role == "assistant":
                user_content_parts.append(f"[AI之前说过]: {content}")
        
        # 合并 user 内容作为最终 prompt
        prompt = "\n\n".join(user_content_parts)
        
        # 构建 CLI 命令
        cmd = [self.cli_path, "-p"]
        
        # 添加自动批准
        if self.auto_approve:
            cmd.append("-y")
        
        # 添加 JSON 输出格式
        cmd.extend(["--output-format", "json"])
        
        # 添加最大轮次限制
        cmd.extend(["--max-turns", str(self.max_turns)])
        
        # 添加系统提示词
        if system_prompt:
            cmd.extend(["--system-prompt", system_prompt])
        
        # 添加用户 prompt
        cmd.append(prompt)
        
        print(f"[WorkBuddy] Calling CLI (prompt length: {len(prompt)} chars)...")
        start_time = time.time()
        
        # 同步执行（在异步上下文中也可以用，因为 Plasticus 是同步调用）
        import subprocess
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                encoding="utf-8",
                errors="replace"
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"WorkBuddy CLI timed out after {self.timeout}s")
        except FileNotFoundError:
            raise RuntimeError(f"WorkBuddy CLI not found at: {self.cli_path}")
        
        elapsed = time.time() - start_time
        
        # 解析响应
        if result.returncode != 0:
            error_msg = result.stderr.strip() or f"Exit code: {result.returncode}"
            print(f"[WorkBuddy] CLI error: {error_msg}")
            raise RuntimeError(f"WorkBuddy CLI failed: {error_msg}")
        
        response_text = result.stdout.strip()
        
        # 尝试解析 JSON 输出
        text_content = response_text
        estimated_input_tokens = 0
        estimated_output_tokens = 0
        
        if response_text.startswith("{") or response_text.startswith("["):
            try:
                data = json.loads(response_text)
                # JSON 格式可能有不同的结构，提取文本内容
                if isinstance(data, dict):
                    text_content = data.get("text") or data.get("content") or data.get("message", "")
                    estimated_input_tokens = data.get("input_tokens", 0)
                    estimated_output_tokens = data.get("output_tokens", 0)
            except json.JSONDecodeError:
                # JSON 解析失败，使用原始文本
                pass
        
        if not text_content:
            text_content = "(empty response)"
        
        # 粗略估算 token 数（中文约 1.5 字/token，英文约 4 字/token）
        if estimated_input_tokens == 0:
            estimated_input_tokens = len(prompt) // 3
        if estimated_output_tokens == 0:
            estimated_output_tokens = len(text_content) // 3
        
        print(f"[WorkBuddy] Response received ({elapsed:.1f}s, ~{estimated_output_tokens} output tokens)")
        
        return OllamaResponse(
            text=text_content,
            model="workbuddy",
            input_tokens=estimated_input_tokens,
            output_tokens=estimated_output_tokens,
            total_tokens=estimated_input_tokens + estimated_output_tokens,
            finish_reason="stop"
        )
    
    def check_health(self) -> Dict[str, Any]:
        """检查 WorkBuddy CLI 是否可用"""
        return {
            "available": self.cli_path is not None,
            "cli_path": self.cli_path,
            "timeout": self.timeout,
            "max_turns": self.max_turns,
            "auto_approve": self.auto_approve
        }


# ============================================================================
# 异步版本（供未来异步 Agent 使用）
# ============================================================================

class AsyncWorkBuddyClient:
    """异步版 WorkBuddy 客户端"""
    
    def __init__(self, **kwargs):
        self._sync_client = WorkBuddyClient(**kwargs)
        self.cli_path = self._sync_client.cli_path
    
    async def chat_completion(
        self,
        model: str,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        n: int = 1
    ) -> OllamaResponse:
        """异步调用（在线程池中执行同步 CLI）"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._sync_client.chat_completion(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                n=n
            )
        )
    
    async def check_health(self) -> Dict[str, Any]:
        """异步健康检查"""
        return self._sync_client.check_health()


if __name__ == "__main__":
    print("=" * 60)
    print("WorkBuddy Client Test")
    print("=" * 60)
    
    client = WorkBuddyClient()
    health = client.check_health()
    print(f"Health: {json.dumps(health, indent=2)}")
    
    if health["available"]:
        print("\nTesting chat_completion...")
        response = client.chat_completion(
            model="workbuddy",
            messages=[
                {"role": "user", "content": "回复 OK 两个字母，不要说别的。"}
            ],
            temperature=0.0
        )
        print(f"Response: {response.text}")
        print(f"Tokens: {response.total_tokens}")
    else:
        print("\nCLI not available, skipping test.")
