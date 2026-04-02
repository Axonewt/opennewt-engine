"""
LLM Client - 支持 OpenAI 和 Ollama API
======================================

功能：
- generate(): 单次生成
- generate_multi(): 多次采样（用于多方案生成）
- count_tokens(): 计算 token 数
- estimate_cost(): 估算成本
- 成本控制和缓存机制
- 支持 Ollama（本地模型，如 GLM-4）

支持的 Provider：
- openai: OpenAI GPT 系列
- ollama: Ollama 兼容服务器（柚子服务器）
"""

import os
import json
import hashlib
import time
from datetime import datetime, date
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from pathlib import Path
import threading

# OpenAI 库
try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    print("⚠️ openai 库未安装，请运行: pip install openai")

# tiktoken 库（用于精确计算 token）
try:
    import tiktoken
    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False
    print("⚠️ tiktoken 库未安装，将使用估算方法计算 token")

# Requests 库（用于 Ollama API）
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    print("⚠️ requests 库未安装，请运行: pip install requests")


# ============================================================================
# 配置和常量
# ============================================================================

# GPT-4o-mini 定价（2026年3月）
# 参考：https://openai.com/api/pricing/
PRICING = {
    "gpt-4o-mini": {
        "input": 0.15 / 1_000_000,   # $0.15 / 1M tokens
        "output": 0.60 / 1_000_000,  # $0.60 / 1M tokens
    },
    "gpt-4o": {
        "input": 2.50 / 1_000_000,   # $2.50 / 1M tokens
        "output": 10.00 / 1_000_000, # $10.00 / 1M tokens
    },
    "gpt-4-turbo": {
        "input": 10.00 / 1_000_000,  # $10.00 / 1M tokens
        "output": 30.00 / 1_000_000, # $30.00 / 1M tokens
    },
    "gpt-3.5-turbo": {
        "input": 0.50 / 1_000_000,   # $0.50 / 1M tokens
        "output": 1.50 / 1_000_000,  # $1.50 / 1M tokens
    },
    # Ollama 本地模型免费
    "glm4": {
        "input": 0.0,
        "output": 0.0,
    },
    "llama3": {
        "input": 0.0,
        "output": 0.0,
    }
}

# 默认配置
DEFAULT_PROVIDER = "ollama"
DEFAULT_MODEL = "glm4"
DEFAULT_BASE_URL = "http://localhost:5051"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.7
DEFAULT_DAILY_BUDGET = 0.0  # 本地模型免费
MAX_RETRIES = 3
RETRY_DELAY = 1.0  # 秒


# ============================================================================
# 数据类
# ============================================================================

@dataclass
class LLMConfig:
    """LLM 配置"""
    provider: str = DEFAULT_PROVIDER  # "openai" 或 "ollama"
    api_key: Optional[str] = None
    base_url: Optional[str] = None  # Ollama 服务器地址
    model: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS
    default_temperature: float = DEFAULT_TEMPERATURE
    daily_budget: float = DEFAULT_DAILY_BUDGET
    cache_enabled: bool = True
    cache_dir: Optional[str] = None
    
    def __post_init__(self):
        """初始化后处理"""
        # OpenAI 需要 API Key
        if self.provider == "openai" and self.api_key is None:
            self.api_key = os.environ.get("OPENAI_API_KEY")
        
        # Ollama 使用 base_url
        if self.provider == "ollama" and self.base_url is None:
            self.base_url = os.environ.get("OLLAMA_BASE_URL", DEFAULT_BASE_URL)
        
        if self.cache_dir is None:
            self.cache_dir = os.path.join(
                os.path.dirname(__file__), 
                "..", "..", "data", "llm_cache"
            )


@dataclass
class LLMResponse:
    """LLM 响应"""
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost: float
    cached: bool = False
    finish_reason: str = "stop"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost": self.cost,
            "cached": self.cached,
            "finish_reason": self.finish_reason
        }


# ============================================================================
# 成本追踪器
# ============================================================================

@dataclass
class DailyUsage:
    """每日使用量"""
    date: str  # YYYY-MM-DD
    total_requests: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0


class CostTracker:
    """成本追踪器"""
    
    def __init__(self, daily_budget: float = DEFAULT_DAILY_BUDGET, 
                 data_dir: Optional[str] = None):
        """
        初始化成本追踪器
        
        Args:
            daily_budget: 每日预算上限（美元）
            data_dir: 数据存储目录
        """
        self.daily_budget = daily_budget
        self.data_dir = data_dir or os.path.join(
            os.path.dirname(__file__),
            "..", "..", "data", "cost_tracking"
        )
        
        # 确保目录存在
        os.makedirs(self.data_dir, exist_ok=True)
        
        # 使用量文件路径
        self.usage_file = os.path.join(self.data_dir, "usage.json")
        
        # 线程锁
        self._lock = threading.Lock()
        
        # 加载使用量数据
        self._usage_data = self._load_usage()
    
    def _load_usage(self) -> Dict[str, DailyUsage]:
        """加载使用量数据"""
        if os.path.exists(self.usage_file):
            try:
                with open(self.usage_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return {k: DailyUsage(**v) for k, v in data.items()}
            except Exception as e:
                print(f"⚠️ 加载使用量数据失败: {e}")
        return {}
    
    def _save_usage(self):
        """保存使用量数据"""
        try:
            with open(self.usage_file, "w", encoding="utf-8") as f:
                data = {k: v.__dict__ for k, v in self._usage_data.items()}
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ 保存使用量数据失败: {e}")
    
    def _get_today_key(self) -> str:
        """获取今日日期键"""
        return datetime.now().strftime("%Y-%m-%d")
    
    def record_usage(self, input_tokens: int, output_tokens: int, 
                     cost: float) -> DailyUsage:
        """
        记录使用量
        
        Args:
            input_tokens: 输入 token 数
            output_tokens: 输出 token 数
            cost: 成本（美元）
            
        Returns:
            更新后的每日使用量
        """
        with self._lock:
            today_key = self._get_today_key()
            
            # 获取或创建今日使用量
            if today_key not in self._usage_data:
                self._usage_data[today_key] = DailyUsage(date=today_key)
            
            usage = self._usage_data[today_key]
            usage.total_requests += 1
            usage.total_tokens += input_tokens + output_tokens
            usage.input_tokens += input_tokens
            usage.output_tokens += output_tokens
            usage.total_cost += cost
            
            # 保存
            self._save_usage()
            
            return usage
    
    def get_today_usage(self) -> DailyUsage:
        """获取今日使用量"""
        with self._lock:
            today_key = self._get_today_key()
            return self._usage_data.get(today_key, DailyUsage(date=today_key))
    
    def check_budget(self) -> Tuple[bool, float]:
        """
        检查预算是否足够
        
        Returns:
            (是否足够, 剩余预算)
        """
        usage = self.get_today_usage()
        remaining = self.daily_budget - usage.total_cost
        return remaining > 0, remaining
    
    def is_over_budget(self) -> bool:
        """是否超出预算"""
        usage = self.get_today_usage()
        return usage.total_cost >= self.daily_budget
    
    def get_usage_summary(self) -> str:
        """获取使用量摘要"""
        usage = self.get_today_usage()
        remaining = self.daily_budget - usage.total_cost
        status = "✅" if remaining > 0 else "❌"
        
        return (
            f"📊 今日 LLM 使用量统计 ({usage.date})\n"
            f"  请求数: {usage.total_requests}\n"
            f"  总 tokens: {usage.total_tokens:,}\n"
            f"  输入 tokens: {usage.input_tokens:,}\n"
            f"  输出 tokens: {usage.output_tokens:,}\n"
            f"  成本: ${usage.total_cost:.4f} / ${self.daily_budget:.2f}\n"
            f"  剩余预算: ${remaining:.4f} {status}"
        )


# ============================================================================
# 缓存管理
# ============================================================================

class PromptCache:
    """Prompt 缓存管理"""
    
    def __init__(self, cache_dir: str):
        """
        初始化缓存管理器
        
        Args:
            cache_dir: 缓存目录
        """
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
    
    def _get_cache_key(self, prompt: str, model: str, 
                       temperature: float, max_tokens: int) -> str:
        """生成缓存键"""
        content = f"{model}:{temperature}:{max_tokens}:{prompt}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]
    
    def _get_cache_path(self, cache_key: str) -> str:
        """获取缓存文件路径"""
        return os.path.join(self.cache_dir, f"{cache_key}.json")
    
    def get(self, prompt: str, model: str, temperature: float, 
            max_tokens: int) -> Optional[LLMResponse]:
        """
        获取缓存的响应
        
        Args:
            prompt: 提示词
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大 token 数
            
        Returns:
            缓存的响应，如果不存在则返回 None
        """
        cache_key = self._get_cache_key(prompt, model, temperature, max_tokens)
        cache_path = self._get_cache_path(cache_key)
        
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return LLMResponse(**data, cached=True)
            except Exception as e:
                print(f"⚠️ 读取缓存失败: {e}")
        
        return None
    
    def set(self, prompt: str, model: str, temperature: float, 
            max_tokens: int, response: LLMResponse):
        """
        缓存响应
        
        Args:
            prompt: 提示词
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大 token 数
            response: LLM 响应
        """
        cache_key = self._get_cache_key(prompt, model, temperature, max_tokens)
        cache_path = self._get_cache_path(cache_key)
        
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(response.to_dict(), f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ 写入缓存失败: {e}")
    
    def clear(self):
        """清空缓存"""
        import shutil
        if os.path.exists(self.cache_dir):
            shutil.rmtree(self.cache_dir)
            os.makedirs(self.cache_dir, exist_ok=True)


# ============================================================================
# LLM Client
# ============================================================================

class LLMClient:
    """LLM API 客户端（支持 OpenAI 和 Ollama）"""
    
    def __init__(self, config: Optional[LLMConfig] = None):
        """
        初始化 LLM 客户端
        
        Args:
            config: LLM 配置，如果为 None 则使用默认配置
        """
        self.config = config or LLMConfig()
        
        # 根据 provider 初始化客户端
        if self.config.provider == "openai":
            if HAS_OPENAI and self.config.api_key:
                self.client = OpenAI(api_key=self.config.api_key)
                self.ollama_client = None
            else:
                self.client = None
                self.ollama_client = None
                if not HAS_OPENAI:
                    print("WARNING: OpenAI library not installed")
                elif not self.config.api_key:
                    print("WARNING: OPENAI_API_KEY not set")
        
        elif self.config.provider == "ollama":
            self.client = None
            if HAS_REQUESTS and self.config.base_url:
                from .ollama_client import OllamaClient
                self.ollama_client = OllamaClient(self.config.base_url)
            else:
                self.ollama_client = None
                if not HAS_REQUESTS:
                    print("WARNING: requests library not installed")
                elif not self.config.base_url:
                    print("WARNING: Ollama base_url not set")
        
        else:
            raise ValueError(f"ERROR: Unsupported provider: {self.config.provider}")
        
        # 初始化成本追踪器
        self.cost_tracker = CostTracker(
            daily_budget=self.config.daily_budget
        )
        
        # 初始化缓存
        self.cache = PromptCache(self.config.cache_dir) if self.config.cache_enabled else None
    
    def count_tokens(self, text: str, model: Optional[str] = None) -> int:
        """
        计算 token 数
        
        Args:
            text: 文本内容
            model: 模型名称
            
        Returns:
            token 数量
        """
        model = model or self.config.model
        
        if HAS_TIKTOKEN:
            try:
                # GPT-4o-mini 使用 cl100k_base 编码
                encoding = tiktoken.encoding_for_model("gpt-4o-mini")
                return len(encoding.encode(text))
            except Exception:
                pass
        
        # 简单估算：平均每个 token 约 4 个字符
        # 对于中文，每个 token 约 1.5-2 个字符
        # 这里使用混合估算
        chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        other_chars = len(text) - chinese_chars
        
        estimated_tokens = (
            chinese_chars / 1.5 +  # 中文
            other_chars / 4        # 英文和其他
        )
        
        return int(estimated_tokens)
    
    def estimate_cost(self, input_tokens: int, output_tokens: int, 
                      model: Optional[str] = None) -> float:
        """
        估算成本
        
        Args:
            input_tokens: 输入 token 数
            output_tokens: 输出 token 数
            model: 模型名称
            
        Returns:
            成本（美元）
        """
        model = model or self.config.model
        
        if model not in PRICING:
            # 使用 gpt-4o-mini 作为默认
            model = DEFAULT_MODEL
        
        pricing = PRICING[model]
        cost = (
            input_tokens * pricing["input"] +
            output_tokens * pricing["output"]
        )
        
        return cost
    
    def generate(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        n: int = 1,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None,
        use_cache: bool = True
    ) -> LLMResponse:
        """
        生成文本
        
        Args:
            prompt: 提示词
            temperature: 温度参数（0-2），越高越随机
            n: 生成数量（目前只支持 n=1）
            max_tokens: 最大生成 token 数
            system_prompt: 系统提示词
            use_cache: 是否使用缓存
            
        Returns:
            LLM 响应
        """
        temperature = temperature if temperature is not None else self.config.default_temperature
        max_tokens = max_tokens or self.config.max_tokens
        
        # 检查缓存
        if use_cache and self.cache:
            cached = self.cache.get(prompt, self.config.model, temperature, max_tokens)
            if cached:
                print(f"✅ 使用缓存响应")
                return cached
        
        # 检查预算（仅对付费服务）
        if self.config.provider == "openai" and self.config.daily_budget > 0:
            is_ok, remaining = self.cost_tracker.check_budget()
            if not is_ok:
                raise RuntimeError(
                    f"ERROR: Daily budget exceeded (${self.config.daily_budget:.2f})\n"
                    f"Current usage: ${self.cost_tracker.get_today_usage().total_cost:.4f}"
                )
            
            if remaining < 0.1:
                print(f"WARNING: Budget almost exhausted, remaining: ${remaining:.4f}")
        
        # 调用 LLM API
        if self.config.provider == "openai":
            # OpenAI API
            if not self.client:
                raise RuntimeError("ERROR: OpenAI client not initialized")
            
            # 构建消息
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            # 重试机制
            last_error = None
            for attempt in range(MAX_RETRIES):
                try:
                    response = self.client.chat.completions.create(
                        model=self.config.model,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        n=n
                    )
                    
                    # 提取结果
                    choice = response.choices[0]
                    text = choice.message.content
                    
                    # 创建响应对象
                    llm_response = LLMResponse(
                        text=text,
                        model=response.model,
                        input_tokens=response.usage.prompt_tokens,
                        output_tokens=response.usage.completion_tokens,
                        total_tokens=response.usage.total_tokens,
                        cost=self.estimate_cost(
                            response.usage.prompt_tokens,
                            response.usage.completion_tokens
                        ),
                        cached=False,
                        finish_reason=choice.finish_reason
                    )
                    
                    # 记录使用量
                    self.cost_tracker.record_usage(
                        llm_response.input_tokens,
                        llm_response.output_tokens,
                        llm_response.cost
                    )
                    
                    # 缓存响应
                    if use_cache and self.cache:
                        self.cache.set(prompt, self.config.model, temperature, max_tokens, llm_response)
                    
                    return llm_response
                    
                except Exception as e:
                    last_error = e
                    print(f"WARNING: API call failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_DELAY * (attempt + 1))
            
            raise RuntimeError(f"ERROR: API call failed after {MAX_RETRIES} retries: {last_error}")
        
        elif self.config.provider == "ollama":
            # Ollama API
            if not self.ollama_client:
                raise RuntimeError("ERROR: Ollama client not initialized")
            
            # 构建消息
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            
            # 调用 Ollama（无需重试，内部已处理）
            try:
                ollama_response = self.ollama_client.chat_completion(
                    model=self.config.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                
                # 转换为统一格式
                llm_response = LLMResponse(
                    text=ollama_response.text,
                    model=ollama_response.model,
                    input_tokens=ollama_response.input_tokens,
                    output_tokens=ollama_response.output_tokens,
                    total_tokens=ollama_response.total_tokens,
                    cost=0.0,  # Ollama 免费
                    cached=False,
                    finish_reason=ollama_response.finish_reason
                )
                
                # 记录使用量（成本为 0）
                self.cost_tracker.record_usage(
                    llm_response.input_tokens,
                    llm_response.output_tokens,
                    0.0
                )
                
                # 缓存响应
                if use_cache and self.cache:
                    self.cache.set(prompt, self.config.model, temperature, max_tokens, llm_response)
                
                return llm_response
                
            except Exception as e:
                raise RuntimeError(f"ERROR: Ollama API call failed: {e}")
        
        else:
            raise RuntimeError(f"ERROR: Unsupported provider: {self.config.provider}")
    
    def generate_multi(
        self,
        prompt: str,
        n: int = 3,
        temperature: float = 0.8,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None
    ) -> List[LLMResponse]:
        """
        多次采样生成（用于多方案生成）
        
        使用较高的温度参数进行多次独立采样，
        产生多样化的结果。
        
        Args:
            prompt: 提示词
            n: 采样次数
            temperature: 温度参数（建议 0.7-1.0）
            max_tokens: 最大生成 token 数
            system_prompt: 系统提示词
            
        Returns:
            LLM 响应列表
        """
        print(f"🔄 开始多次采样 (n={n}, temperature={temperature})...")
        
        responses = []
        for i in range(n):
            try:
                # 注意：不使用缓存，确保每次都独立生成
                response = self.generate(
                    prompt=prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    system_prompt=system_prompt,
                    use_cache=False  # 多次采样不使用缓存
                )
                responses.append(response)
                print(f"  ✓ 采样 {i+1}/{n} 完成")
            except Exception as e:
                print(f"  ✗ 采样 {i+1}/{n} 失败: {e}")
                # 继续尝试下一个
        
        if not responses:
            raise RuntimeError("❌ 所有采样都失败了")
        
        print(f"✅ 完成多次采样，成功 {len(responses)}/{n}")
        return responses
    
    def generate_with_fallback(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        system_prompt: Optional[str] = None
    ) -> LLMResponse:
        """
        带降级策略的生成
        
        如果超出预算或 API 失败，尝试使用缓存。
        如果缓存也没有，返回错误。
        
        Args:
            prompt: 提示词
            temperature: 温度参数
            max_tokens: 最大生成 token 数
            system_prompt: 系统提示词
            
        Returns:
            LLM 响应
        """
        temperature = temperature if temperature is not None else self.config.default_temperature
        max_tokens = max_tokens or self.config.max_tokens
        
        try:
            # 首先尝试正常调用
            return self.generate(
                prompt=prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
                use_cache=True
            )
        except RuntimeError as e:
            # 检查是否是预算超限
            if "预算" in str(e) or "budget" in str(e).lower():
                print("⚠️ 预算超限，尝试使用缓存...")
                
                # 尝试使用缓存
                if self.cache:
                    cached = self.cache.get(prompt, self.config.model, temperature, max_tokens)
                    if cached:
                        print("✅ 找到缓存响应")
                        return cached
                
                print("❌ 没有可用的缓存")
            
            raise
    
    def get_status(self) -> str:
        """获取客户端状态"""
        usage = self.cost_tracker.get_usage_summary()
        
        cache_status = "已启用" if self.cache else "已禁用"
        api_status = "已连接" if self.client else "未连接"
        
        return (
            f"🤖 LLM 客户端状态\n"
            f"  模型: {self.config.model}\n"
            f"  API 状态: {api_status}\n"
            f"  缓存: {cache_status}\n"
            f"  每日预算: ${self.config.daily_budget:.2f}\n"
            f"\n{usage}"
        )


# ============================================================================
# 便捷函数
# ============================================================================

def create_client(api_key: Optional[str] = None, 
                  model: str = DEFAULT_MODEL,
                  daily_budget: float = DEFAULT_DAILY_BUDGET) -> LLMClient:
    """
    创建 LLM 客户端的便捷函数
    
    Args:
        api_key: OpenAI API Key
        model: 模型名称
        daily_budget: 每日预算
        
    Returns:
        LLM 客户端实例
    """
    config = LLMConfig(
        api_key=api_key,
        model=model,
        daily_budget=daily_budget
    )
    return LLMClient(config)


# ============================================================================
# 测试和示例
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🧪 LLM Client 测试")
    print("=" * 60)
    print()
    
    # 创建客户端
    client = create_client()
    
    # 打印状态
    print(client.get_status())
    print()
    
    # 测试 token 计算
    test_text = "Hello, world! 你好世界！"
    tokens = client.count_tokens(test_text)
    print(f"📝 测试文本: '{test_text}'")
    print(f"   Token 数: {tokens}")
    print()
    
    # 测试成本估算
    cost = client.estimate_cost(input_tokens=1000, output_tokens=500)
    print(f"💰 成本估算示例:")
    print(f"   输入: 1000 tokens")
    print(f"   输出: 500 tokens")
    print(f"   成本: ${cost:.6f}")
    print()
    
    # 如果 API 可用，测试生成
    if client.client:
        print("🔄 测试生成...")
        try:
            response = client.generate(
                prompt="请用一句话解释什么是神经网络可塑性。",
                temperature=0.7,
                max_tokens=100
            )
            print(f"✅ 生成成功:")
            print(f"   响应: {response.text}")
            print(f"   Tokens: {response.total_tokens} (输入: {response.input_tokens}, 输出: {response.output_tokens})")
            print(f"   成本: ${response.cost:.6f}")
            print(f"   缓存: {'是' if response.cached else '否'}")
        except Exception as e:
            print(f"❌ 生成失败: {e}")
    else:
        print("⚠️ API 未配置，跳过生成测试")
    
    print()
    print("=" * 60)
