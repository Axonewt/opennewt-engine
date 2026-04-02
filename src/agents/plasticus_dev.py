"""
Plasticus-Dev (决策型开发者)
============================

角色：修复策略的"大脑"
职责：接收损伤报告、生成多套修复方案、评估成本风险成功率

工作模式：
- 接收 SIGNAL 消息
- 查询历史案例
- LLM 多次采样生成 3-5 套方案
- 使用可塑性评估矩阵打分
- 选择最优方案
- 发送 BLUEPRINT 消息

核心能力：
- 可塑性评估矩阵（停机时间 0.3、代码质量 0.25、实现复杂度 0.2、历史成功率 0.15、回滚难度 0.1）
- 历史案例检索（向量相似度搜索）
- 成功率预测（基于历史数据）
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import sys

from src.protocol.oacp import SignalMessage, BlueprintMessage
from src.models.plasticity import PlasticityEvaluator, BlueprintGenerator, RepairPlan

try:
    from src.integrations.llm_client import LLMClient, LLMConfig, create_client
    HAS_LLM_CLIENT = True
except ImportError:
    HAS_LLM_CLIENT = False

from src.integrations.ollama_client import OllamaClient


# ============================================================================
# Plasticus-Dev 系统提示词（System Prompt）
# ============================================================================

PLASTICUS_DEV_SYSTEM_PROMPT = """
你是 **Plasticus-Dev**，OpenNewt 神经可塑性引擎的决策层 Agent。

## 你的身份

你是代码修复的"大脑"，像大脑皮层一样，接收感知层的信号，生成多套修复方案，评估并选择最优方案。

你的核心职责：
1. **接收 SIGNAL**：从 Soma-Dev 接收损伤信号
2. **查询历史**：从 Mnemosyne-Dev 查询相似案例
3. **生成方案**：使用 LLM 多次采样生成 3-5 套修复方案
4. **评估方案**：使用可塑性评估矩阵打分
5. **选择最优**：选择得分最高的方案
6. **发送蓝图**：向 Effector-Dev 发送 BLUEPRINT 消息

## 你的工作原则

### 1. 多方案生成，不做单一选择
- 至少生成 3 套方案（快速修复、平衡方案、彻底重构）
- 每套方案都要有明确的优缺点
- 避免陷入"唯一答案"的陷阱

### 2. 数据驱动评估，客观公正
- 使用可塑性评估矩阵统一打分
- 权重配置：
  - 停机时间：30%
  - 代码质量：25%
  - 实现复杂度：20%
  - 历史成功率：15%
  - 回滚难度：10%
- 不凭直觉，只看得分

### 3. 历史案例优先，避免重复错误
- 先查询 Mnemosyne-Dev，看是否有相似案例
- 如果有成功案例，优先复用
- 如果有失败教训，避免重蹈覆辙

### 4. 预演验证，降低风险
- 对于得分相近的方案（差值 < 0.1），选择更保守的方案
- 对于 P0 问题，必须预演模拟
- 成功率预测 < 70% 的方案，自动降级或请求人工确认

## 可塑性评估矩阵

```
方案得分 = 
  停机时间 × 0.30（越短越好）
  + 代码质量 × 0.25（符合最佳实践）
  + 实现复杂度 × 0.20（越简单越好）
  + 历史成功率 × 0.15（相似案例的统计）
  + 回滚难度 × 0.10（越容易回滚越好）
```

**示例**：

| 方案 | 停机时间 | 代码质量 | 复杂度 | 成功率 | 回滚难度 | 总分 |
|-----|---------|---------|--------|--------|---------|------|
| A. 热补丁 | 0ms | 0.6 | 0.9 | 0.7 | 0.9 | **0.76** |
| B. 重构连接池 | 2s | 0.9 | 0.6 | 0.85 | 0.7 | **0.79** [Check] |
| C. 完全重写 | 10s | 1.0 | 0.3 | 0.95 | 0.3 | **0.70** |

-> **选择方案 B**（得分最高）

## 你的输出格式

### 接收 SIGNAL
```
[Receive] [Plasticus-Dev] 接收到 SIGNAL

损伤类型: 资源泄漏
严重程度: P0
位置: src/api/handler.rs:142
健康度: 0.62

开始处理...
```

### 查询历史案例
```
[Search] [Plasticus-Dev] 查询历史案例...

找到 2 个相似案例：
  1. [成功] regen-20260315-003 (相似度: 0.92)
     - 问题: 数据库连接泄漏
     - 方案: 重构连接池 + 添加超时机制
     - 结果: 成功修复，健康度从 0.58 恢复到 0.91
  
  2. [失败] regen-20260320-007 (相似度: 0.78)
     - 问题: 文件句柄泄漏
     - 方案: 热补丁添加关闭逻辑
     - 结果: 失败，引入新 bug，已回滚

建议: 复用案例 1 的方案（重构连接池）
```

### 生成方案
```
[AI] [Plasticus-Dev] 生成修复方案...

方案 A: 热补丁修复
  - 描述: 快速修补连接泄漏
  - 停机时间: 0ms
  - 代码质量: 0.6
  - 实现复杂度: 低（0.2）
  - 历史成功率: 70%
  - 回滚难度: 低（0.1）
  - 预估成本: $0.5

方案 B: 重构连接池
  - 描述: 重构连接池实现，添加超时和泄漏检测
  - 停机时间: 2s
  - 代码质量: 0.9
  - 实现复杂度: 中（0.4）
  - 历史成功率: 85%
  - 回滚难度: 中（0.3）
  - 预估成本: $2.0

方案 C: 完全重写
  - 描述: 完全重写连接池架构
  - 停机时间: 10s
  - 代码质量: 1.0
  - 实现复杂度: 高（0.8）
  - 历史成功率: 95%
  - 回滚难度: 高（0.7）
  - 预估成本: $10.0
```

### 评估与选择
```
[Stats] [Plasticus-Dev] 评估方案...

方案评分结果：
  1. 方案 B (重构连接池) - 总分: 0.79 [Star]
     - 停机时间: 0.28
     - 代码质量: 0.225
     - 实现复杂度: 0.12
     - 历史成功率: 0.1275
     - 回滚难度: 0.07
  
  2. 方案 A (热补丁) - 总分: 0.76
  3. 方案 C (完全重写) - 总分: 0.70

[Check] 推荐方案: 方案 B (重构连接池)
```

### 发送 BLUEPRINT
```
[Send] [Plasticus-Dev] 发送 BLUEPRINT

Plan ID: regen-20260331-001
策略: 重构连接池 + 渐进式切换
预估停机时间: 2s
成功率预测: 92%

步骤:
  1. 创建隔离分支
  2. 修改连接池配置
  3. 运行测试套件
  4. 灰度发布（10%流量）
  5. 逐步增加至 100%

Issue: https://github.com/owner/repo/issues/124
```

## 你的限制

1. **只负责决策，不负责执行**
2. **必须生成至少 3 套方案**
3. **必须使用评估矩阵打分**
4. **得分相近时选择更保守的方案**
5. **P0 问题必须预演验证**

## 你的成长

每次决策后，你会收到 Effector-Dev 的执行反馈：
- 方案是否成功？
- 健康度是否恢复？
- 实际成本 vs 预估成本？

根据这些反馈，你会调整自己的评估标准，变得更准确。

---

现在，等待 SIGNAL 消息的到来吧！
"""


# ============================================================================
# LLM 方案生成提示词
# ============================================================================

PLAN_GENERATION_PROMPT = """请为以下代码问题生成 {n} 套修复方案。

## 问题描述

- **损伤类型**: {damage_type}
- **严重程度**: {severity}
- **位置**: {location}
- **当前健康度**: {health_score}
- **症状**: {symptoms}

{historical_context}

## 要求

请生成 {n} 套不同策略的修复方案：

1. **方案 A（快速修复）**：最小改动，快速止血
2. **方案 B（平衡方案）**：适度重构，平衡成本和效果
3. **方案 C（彻底重构）**：根本解决，长期最优

每套方案请提供：
- 方案名称
- 简要描述
- 预估停机时间
- 代码质量评分（0-1）
- 实现复杂度评分（0-1，越高越复杂）
- 回滚难度评分（0-1，越高越难）

## 输出格式

请以 JSON 格式输出，结构如下：

```json
{{
  "plans": [
    {{
      "name": "方案名称",
      "description": "方案描述",
      "strategy": "quick_fix | balanced | thorough",
      "downtime_seconds": 0,
      "code_quality_score": 0.7,
      "implementation_complexity": 0.3,
      "rollback_difficulty": 0.2,
      "steps": [
        "步骤1",
        "步骤2"
      ],
      "risks": ["风险1"],
      "benefits": ["优点1"]
    }}
  ]
}}
```

请确保输出是有效的 JSON 格式。
"""


# ============================================================================
# Plasticus-Dev 实现
# ============================================================================

@dataclass
class HistoricalCase:
    """历史案例"""
    case_id: str
    problem_type: str
    solution: str
    result: str  # "success" | "failed"
    similarity: float = 0.0


class PlasticusDev:
    """Plasticus-Dev Agent 实现"""
    
    def __init__(
        self, 
        openai_api_key: Optional[str] = None, 
        github_token: Optional[str] = None,
        llm_client: Optional[LLMClient] = None,
        llm_config: Optional[LLMConfig] = None,
        ollama_url: Optional[str] = None,
        ollama_model: Optional[str] = None,
        workbuddy_enabled: bool = False
    ):
        """初始化 Plasticus-Dev
        
        Args:
            openai_api_key: OpenAI API Key（优先级低于 llm_client/llm_config）
            github_token: GitHub Personal Access Token
            llm_client: 预配置的 LLM 客户端实例
            llm_config: LLM 配置（如果提供，将创建新客户端）
            ollama_url: Ollama 服务器地址（如提供则使用 Ollama 替代 OpenAI）
            ollama_model: Ollama 模型名称
            workbuddy_enabled: 启用 WorkBuddy CLI 作为 LLM 后端（优先级最高）
        """
        self.ollama_client = None
        
        # 优先级: workbuddy > ollama > openai
        if workbuddy_enabled:
            from src.integrations.workbuddy_client import WorkBuddyClient
            self.ollama_client = WorkBuddyClient()
            self.ollama_model = "workbuddy"
            self.llm_client = None
            print("[OK] WorkBuddy 客户端已初始化（云端 AI 模式）")
        elif ollama_url:
            self.ollama_client = OllamaClient(ollama_url)
            self.ollama_model = ollama_model or "glm-4.7-flash:latest"
            self.llm_client = None
            print(f"[OK] Ollama 客户端已初始化: {ollama_url} / {self.ollama_model}")
        else:
            # 初始化 LLM 客户端（OpenAI）
            if llm_client:
                self.llm_client = llm_client
            elif HAS_LLM_CLIENT:
                if llm_config:
                    self.llm_client = LLMClient(llm_config)
                elif openai_api_key:
                    config = LLMConfig(api_key=openai_api_key)
                    self.llm_client = LLMClient(config)
                else:
                    self.llm_client = create_client()
            else:
                self.llm_client = None
            
            if self.llm_client:
                print("[OK] LLM 客户端已初始化")
            else:
                print("[Warning] LLM 客户端未初始化，将使用默认方案生成")
        
        self.github_token = github_token
        self.evaluator = PlasticityEvaluator()
        self.generator = BlueprintGenerator(self.evaluator)
        self.case_history: List[HistoricalCase] = []
    
    def receive_signal(self, signal: SignalMessage):
        """接收 SIGNAL 消息
        
        Args:
            signal: SIGNAL 消息
        """
        print("=" * 60)
        print("[Receive] [Plasticus-Dev] 接收到 SIGNAL")
        print("=" * 60)
        print()
        
        payload = signal.payload
        
        print(f"损伤类型: {payload['damage_type']}")
        print(f"严重程度: {payload['severity']}")
        print(f"位置: {payload['location']}")
        print(f"健康度: {payload['health_score']}")
        print()
        
        print("开始处理...\n")
    
    def query_historical_cases(self, damage_type: str) -> List[HistoricalCase]:
        """查询历史案例
        
        Args:
            damage_type: 损伤类型
            
        Returns:
            历史案例列表
        """
        print("[Search] [Plasticus-Dev] 查询历史案例...\n")
        
        # TODO: 实现真实的向量相似度搜索
        # 这里先用模拟数据
        
        cases = [
            HistoricalCase(
                case_id="regen-20260315-003",
                problem_type="资源泄漏",
                solution="重构连接池 + 添加超时机制",
                result="success",
                similarity=0.92
            ),
            HistoricalCase(
                case_id="regen-20260320-007",
                problem_type="资源泄漏",
                solution="热补丁添加关闭逻辑",
                result="failed",
                similarity=0.78
            )
        ]
        
        if cases:
            print("找到相似案例：")
            for i, case in enumerate(cases, 1):
                result_icon = "[OK]" if case.result == "success" else "[ERROR]"
                print(f"  {i}. [{result_icon}] {case.case_id} (相似度: {case.similarity:.2f})")
                print(f"     - 问题: {case.problem_type}")
                print(f"     - 方案: {case.solution}")
                print(f"     - 结果: {case.result}")
            print()
            
            # 找到最成功的案例
            successful_cases = [c for c in cases if c.result == "success"]
            if successful_cases:
                best_case = max(successful_cases, key=lambda c: c.similarity)
                print(f"建议: 复用案例 {best_case.case_id} 的方案\n")
        
        return cases
    
    def _generate_plans_with_llm(
        self,
        damage_type: str,
        location: str,
        severity: str,
        symptoms: List[str],
        health_score: float,
        historical_cases: List[HistoricalCase] = None,
        n_plans: int = 3
    ) -> List[Dict[str, Any]]:
        """使用 LLM 生成修复方案
        
        Args:
            damage_type: 损伤类型
            location: 损伤位置
            severity: 严重程度
            symptoms: 症状列表
            health_score: 当前健康度
            historical_cases: 历史案例
            n_plans: 方案数量
            
        Returns:
            方案列表（字典格式）
        """
        if not self.llm_client and not self.ollama_client:
            print("[Warning] LLM 客户端不可用，使用默认方案生成")
            return None
        
        print("[AI] [Plasticus-Dev] 使用 LLM 生成修复方案...\n")
        
        # 构建历史案例上下文
        historical_context = ""
        if historical_cases:
            historical_context = "## 历史相似案例\n\n"
            for case in historical_cases:
                result_str = "[OK] 成功" if case.result == "success" else "[ERROR] 失败"
                historical_context += f"- [{result_str}] {case.case_id}\n"
                historical_context += f"  方案: {case.solution}\n"
                historical_context += f"  相似度: {case.similarity:.2f}\n\n"
        
        # 构建提示词
        prompt = PLAN_GENERATION_PROMPT.format(
            n=n_plans,
            damage_type=damage_type,
            severity=severity,
            location=location,
            health_score=health_score,
            symptoms=", ".join(symptoms),
            historical_context=historical_context
        )
        
        try:
            if self.ollama_client:
                # 使用 Ollama
                messages = [
                    {"role": "system", "content": PLASTICUS_DEV_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ]
                response = self.ollama_client.chat_completion(
                    model=self.ollama_model,
                    messages=messages,
                    temperature=0.8,
                    max_tokens=2048
                )
                print(f"   Ollama 响应 tokens: {response.total_tokens}")
                text = response.text
            else:
                # 使用 OpenAI LLM 客户端
                response = self.llm_client.generate(
                    prompt=prompt,
                    temperature=0.8,
                    max_tokens=2048,
                    system_prompt=PLASTICUS_DEV_SYSTEM_PROMPT
                )
                print(f"   LLM 响应 tokens: {response.total_tokens}")
                print(f"   成本: ${response.cost:.6f}\n")
                text = response.text
            
            # 解析 JSON 响应
            # 提取 JSON 部分（去除可能的 markdown 代码块）
            text = text.strip()
            # 去除 markdown 代码块包裹
            if "```json" in text:
                text = text.split("```json")[1]
            if "```" in text:
                text = text.split("```")[0]
            text = text.strip()
            
            result = json.loads(text)
            return result.get("plans", [])
            
        except json.JSONDecodeError as e:
            print(f"[Warning] JSON 解析失败: {e}")
            print(f"   原始响应: {text[:200]}...")
            return None
        except Exception as e:
            print(f"[Warning] LLM 调用失败: {e}")
            return None
    
    def _generate_plans_multi_sample(
        self,
        damage_type: str,
        location: str,
        severity: str,
        symptoms: List[str],
        health_score: float,
        historical_cases: List[HistoricalCase] = None,
        n_samples: int = 3
    ) -> List[Dict[str, Any]]:
        """使用 LLM 多次采样生成多样化方案
        
        这是更高级的方法：多次独立采样，
        然后合并和去重，产生真正多样化的方案。
        
        Args:
            damage_type: 损伤类型
            location: 损伤位置
            severity: 严重程度
            symptoms: 症状列表
            health_score: 当前健康度
            historical_cases: 历史案例
            n_samples: 采样次数
            
        Returns:
            方案列表（字典格式）
        """
        if not self.llm_client:
            print("[Warning] LLM 客户端不可用，使用默认方案生成")
            return None
        
        print("[Sync] [Plasticus-Dev] 使用多次采样生成方案...\n")
        
        # 构建历史案例上下文
        historical_context = ""
        if historical_cases:
            historical_context = "## 历史相似案例\n\n"
            for case in historical_cases:
                result_str = "[OK] 成功" if case.result == "success" else "[ERROR] 失败"
                historical_context += f"- [{result_str}] {case.case_id}\n"
                historical_context += f"  方案: {case.solution}\n"
                historical_context += f"  相似度: {case.similarity:.2f}\n\n"
        
        # 构建提示词
        prompt = PLAN_GENERATION_PROMPT.format(
            n=3,  # 每次采样生成 3 个方案
            damage_type=damage_type,
            severity=severity,
            location=location,
            health_score=health_score,
            symptoms=", ".join(symptoms),
            historical_context=historical_context
        )
        
        try:
            # 多次采样
            responses = self.llm_client.generate_multi(
                prompt=prompt,
                n=n_samples,
                temperature=0.9,  # 高温度，增加多样性
                max_tokens=2048,
                system_prompt=PLASTICUS_DEV_SYSTEM_PROMPT
            )
            
            # 收集所有方案
            all_plans = []
            seen_names = set()
            
            for i, response in enumerate(responses):
                print(f"   采样 {i+1}: {response.total_tokens} tokens, ${response.cost:.6f}")
                
                try:
                    # 解析 JSON
                    text = response.text.strip()
                    if text.startswith("```json"):
                        text = text[7:]
                    if text.startswith("```"):
                        text = text[3:]
                    if text.endswith("```"):
                        text = text[:-3]
                    text = text.strip()
                    
                    result = json.loads(text)
                    plans = result.get("plans", [])
                    
                    # 去重（基于名称）
                    for plan in plans:
                        name = plan.get("name", "")
                        if name and name not in seen_names:
                            seen_names.add(name)
                            all_plans.append(plan)
                            
                except json.JSONDecodeError as e:
                    print(f"   [Warning] JSON 解析失败: {e}")
                    continue
            
            print(f"\n   合并后共 {len(all_plans)} 个不同方案\n")
            return all_plans
            
        except Exception as e:
            print(f"[Warning] 多次采样失败: {e}")
            return None
    
    def generate_plans(
        self,
        damage_type: str,
        location: str,
        symptoms: List[str],
        health_score: float,
        historical_cases: List[HistoricalCase] = None,
        use_llm: bool = True,
        use_multi_sample: bool = False
    ) -> List[RepairPlan]:
        """生成修复方案
        
        Args:
            damage_type: 损伤类型
            location: 损伤位置
            symptoms: 症状列表
            health_score: 当前健康度
            historical_cases: 历史案例
            use_llm: 是否使用 LLM 生成
            use_multi_sample: 是否使用多次采样
            
        Returns:
            修复方案列表
        """
        print("[AI] [Plasticus-Dev] 生成修复方案...\n")
        
        plans = []
        
        # 尝试使用 LLM 生成
        if use_llm and (self.llm_client or self.ollama_client):
            if use_multi_sample:
                llm_plans = self._generate_plans_multi_sample(
                    damage_type=damage_type,
                    location=location,
                    severity="P0",  # TODO: 从 signal 获取
                    symptoms=symptoms,
                    health_score=health_score,
                    historical_cases=historical_cases
                )
            else:
                llm_plans = self._generate_plans_with_llm(
                    damage_type=damage_type,
                    location=location,
                    severity="P0",
                    symptoms=symptoms,
                    health_score=health_score,
                    historical_cases=historical_cases
                )
            
            if llm_plans:
                # 转换为 RepairPlan 对象
                for i, plan_dict in enumerate(llm_plans):
                    plan = RepairPlan(
                        plan_id=f"plan-{datetime.now().strftime('%Y%m%d%H%M%S')}-{i}",
                        name=plan_dict.get("name", f"Plan {chr(65 + i)}"),
                        description=plan_dict.get("description", ""),
                        downtime_seconds=plan_dict.get("downtime_seconds", 0),
                        code_quality_score=plan_dict.get("code_quality_score", 0.7),
                        implementation_complexity=plan_dict.get("implementation_complexity", 0.5),
                        historical_success_rate=0.8,
                        rollback_difficulty=plan_dict.get("rollback_difficulty", 0.3),
                        steps=[{"step": j+1, "action": step} for j, step in enumerate(plan_dict.get("steps", []))],
                        estimated_cost=0.5
                    )
                    plans.append(plan)
        
        # 如果 LLM 生成失败或未启用，使用默认生成器
        if not plans:
            plans = self.generator.generate_plans_from_signal(
                damage_type=damage_type,
                location=location,
                symptoms=symptoms,
                health_score=health_score,
                historical_cases=[{"case_id": c.case_id, "solution": c.solution} for c in historical_cases] if historical_cases else None
            )
        
        # 打印方案
        for i, plan in enumerate(plans):
            print(f"方案 {chr(64 + i + 1)}: {plan.name}")
            print(f"  - 描述: {plan.description}")
            print(f"  - 停机时间: {plan.downtime_seconds}s")
            print(f"  - 代码质量: {plan.code_quality_score}")
            print(f"  - 实现复杂度: {plan.implementation_complexity}")
            print(f"  - 历史成功率: {plan.historical_success_rate * 100:.0f}%")
            print(f"  - 回滚难度: {plan.rollback_difficulty}")
            print(f"  - 预估成本: ${plan.estimated_cost}")
            print()
        
        return plans
    
    def evaluate_plans(self, plans: List[RepairPlan]) -> RepairPlan:
        """评估方案并选择最优
        
        Args:
            plans: 修复方案列表
            
        Returns:
            最优方案
        """
        print("[Stats] [Plasticus-Dev] 评估方案...\n")
        
        # 评估所有方案
        scored_plans = self.evaluator.evaluate_plans(plans)
        
        # 打印评分结果
        print("方案评分结果：")
        for i, sp in enumerate(scored_plans, 1):
            print(f"  {i}. 方案 {sp.plan.plan_id.split('-')[-1]} ({sp.plan.name}) - 总分: {sp.score:.2f} [Star]")
            print(f"     - 停机时间: {sp.score_breakdown['downtime']:.3f}")
            print(f"     - 代码质量: {sp.score_breakdown['code_quality']:.3f}")
            print(f"     - 实现复杂度: {sp.score_breakdown['implementation_complexity']:.3f}")
            print(f"     - 历史成功率: {sp.score_breakdown['historical_success']:.3f}")
            print(f"     - 回滚难度: {sp.score_breakdown['rollback_difficulty']:.3f}")
            print()
        
        # 选择最优方案
        best_plan = scored_plans[0]
        print(f"[Check] 推荐方案: {best_plan.plan.name}\n")
        
        # 检查是否需要预演
        if best_plan.score < 0.7:
            print("[Warning] 警告: 所有方案得分较低，建议人工确认\n")
        elif best_plan.score < 0.5:
            print("[ERROR] 错误: 没有合适的方案，需要人工干预\n")
        
        return best_plan.plan
    
    def create_blueprint(self, plan: RepairPlan) -> BlueprintMessage:
        """创建蓝图
        
        Args:
            plan: 修复方案
            
        Returns:
            BLUEPRINT 消息
        """
        print("[Send] [Plasticus-Dev] 发送 BLUEPRINT\n")
        
        blueprint = BlueprintMessage.create(
            plan_id=plan.plan_id,
            strategy=plan.name,
            steps=plan.steps,
            estimated_downtime=f"{plan.downtime_seconds}s",
            success_rate_prediction=plan.historical_success_rate,
            rollback_plan="git revert + 重启服务"
        )
        
        print(f"Plan ID: {plan.plan_id}")
        print(f"策略: {plan.name}")
        print(f"预估停机时间: {plan.downtime_seconds}s")
        print(f"成功率预测: {plan.historical_success_rate * 100:.0f}%")
        print()
        print("步骤:")
        for step in plan.steps:
            print(f"  {step['step']}. {step['action']}")
        print()
        
        return blueprint
    
    def process_signal(
        self, 
        signal: SignalMessage,
        use_llm: bool = True,
        use_multi_sample: bool = False
    ) -> BlueprintMessage:
        """处理 SIGNAL 消息（端到端流程）
        
        Args:
            signal: SIGNAL 消息
            use_llm: 是否使用 LLM 生成方案
            use_multi_sample: 是否使用多次采样
            
        Returns:
            BLUEPRINT 消息
        """
        # 1. 接收 SIGNAL
        self.receive_signal(signal)
        
        payload = signal.payload
        
        # 2. 查询历史案例
        historical_cases = self.query_historical_cases(payload["damage_type"])
        
        # 3. 生成方案
        plans = self.generate_plans(
            damage_type=payload["damage_type"],
            location=payload["location"],
            symptoms=payload["symptoms"],
            health_score=payload["health_score"],
            historical_cases=historical_cases,
            use_llm=use_llm,
            use_multi_sample=use_multi_sample
        )
        
        # 4. 评估方案
        best_plan = self.evaluate_plans(plans)
        
        # 5. 创建蓝图
        blueprint = self.create_blueprint(best_plan)
        
        print("=" * 60)
        print()
        
        return blueprint
    
    def get_llm_status(self) -> str:
        """获取 LLM 客户端状态"""
        if self.llm_client:
            return self.llm_client.get_status()
        return "[Warning] LLM 客户端未初始化"
    
    def run(self):
        """运行 Plasticus-Dev（监听模式）"""
        print("=" * 60)
        print("🧠 Plasticus-Dev - 决策型开发者")
        print("=" * 60)
        print()
        
        # 打印 LLM 状态
        print(self.get_llm_status())
        print()
        
        print("等待 SIGNAL 消息...\n")
        
        # TODO: 实现真实的消息监听（从 GitHub Issues 或消息队列）
        # 这里先用示例信号
        
        # 创建一个示例 SIGNAL
        example_signal = SignalMessage.create(
            damage_type="资源泄漏",
            severity="P0",
            location="src/api/handler.rs:142",
            symptoms=["内存占用持续增长", "未释放的数据库连接"],
            health_score=0.62
        )
        
        # 处理信号
        blueprint = self.process_signal(example_signal, use_llm=True)
        
        print("Blueprint JSON:")
        print(blueprint.to_json())


# ============================================================================
# 主程序
# ============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Plasticus-Dev - 决策型开发者")
    parser.add_argument("--openai-key", help="OpenAI API Key", default=None)
    parser.add_argument("--github-token", help="GitHub Personal Access Token", default=None)
    parser.add_argument("--daily-budget", type=float, default=5.0, help="每日 LLM 预算（美元）")
    parser.add_argument("--model", default="gpt-4o-mini", help="LLM 模型")
    parser.add_argument("--no-llm", action="store_true", help="禁用 LLM")
    
    args = parser.parse_args()
    
    # 创建 LLM 配置
    llm_config = None
    if not args.no_llm:
        llm_config = LLMConfig(
            api_key=args.openai_key,
            model=args.model,
            daily_budget=args.daily_budget
        )
    
    # 创建 Plasticus-Dev
    plasticus_dev = PlasticusDev(
        openai_api_key=args.openai_key,
        github_token=args.github_token,
        llm_config=llm_config
    )
    
    # 运行
    plasticus_dev.run()
