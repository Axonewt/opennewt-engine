"""
降级引擎 - 预算超限时的备用方案
==================================

当 LLM 预算超限或 API 不可用时，使用规则引擎生成方案。
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime


# ============================================================================
# 规则定义
# ============================================================================

@dataclass
class RepairRule:
    """修复规则"""
    damage_type: str
    severity: str
    name: str
    description: str
    strategy: str  # quick_fix, balanced, thorough
    downtime_seconds: int
    code_quality_score: float
    implementation_complexity: float
    rollback_difficulty: float
    steps: List[str]
    priority: int = 0  # 规则优先级，越高越优先


# 预定义的修复规则库
REPAIR_RULES = [
    # ===== 资源泄漏 =====
    RepairRule(
        damage_type="资源泄漏",
        severity="P0",
        name="紧急释放资源",
        description="添加显式资源释放调用，快速止血",
        strategy="quick_fix",
        downtime_seconds=0,
        code_quality_score=0.5,
        implementation_complexity=0.2,
        rollback_difficulty=0.1,
        steps=[
            "定位资源创建点",
            "添加 try-finally 块",
            "在 finally 中释放资源",
            "添加日志记录"
        ],
        priority=10
    ),
    RepairRule(
        damage_type="资源泄漏",
        severity="P0",
        name="重构资源管理",
        description="使用 RAII 或连接池重构资源管理",
        strategy="balanced",
        downtime_seconds=2,
        code_quality_score=0.85,
        implementation_complexity=0.5,
        rollback_difficulty=0.3,
        steps=[
            "创建隔离分支",
            "引入资源池模式",
            "重构资源获取逻辑",
            "添加超时和重试机制",
            "运行测试套件"
        ],
        priority=20
    ),
    
    # ===== 内存泄漏 =====
    RepairRule(
        damage_type="内存泄漏",
        severity="P0",
        name="添加内存释放",
        description="定位泄漏点并添加释放逻辑",
        strategy="quick_fix",
        downtime_seconds=0,
        code_quality_score=0.6,
        implementation_complexity=0.3,
        rollback_difficulty=0.2,
        steps=[
            "使用内存分析工具定位泄漏",
            "添加释放逻辑",
            "添加内存使用监控",
            "验证修复效果"
        ],
        priority=10
    ),
    RepairRule(
        damage_type="内存泄漏",
        severity="P1",
        name="优化内存管理",
        description="重构内存管理架构，使用智能指针",
        strategy="balanced",
        downtime_seconds=5,
        code_quality_score=0.9,
        implementation_complexity=0.6,
        rollback_difficulty=0.4,
        steps=[
            "分析内存使用模式",
            "引入智能指针或 GC",
            "重构内存密集模块",
            "添加内存限制和告警"
        ],
        priority=20
    ),
    
    # ===== 性能退化 =====
    RepairRule(
        damage_type="性能退化",
        severity="P1",
        name="添加缓存",
        description="为热点代码添加缓存层",
        strategy="quick_fix",
        downtime_seconds=0,
        code_quality_score=0.7,
        implementation_complexity=0.3,
        rollback_difficulty=0.2,
        steps=[
            "性能分析定位热点",
            "添加内存缓存",
            "添加缓存失效策略",
            "验证性能提升"
        ],
        priority=10
    ),
    RepairRule(
        damage_type="性能退化",
        severity="P1",
        name="优化算法",
        description="重构低效算法，降低时间复杂度",
        strategy="balanced",
        downtime_seconds=3,
        code_quality_score=0.85,
        implementation_complexity=0.6,
        rollback_difficulty=0.3,
        steps=[
            "算法复杂度分析",
            "选择更优算法",
            "重构核心代码",
            "添加性能基准测试"
        ],
        priority=20
    ),
    
    # ===== 异常处理缺失 =====
    RepairRule(
        damage_type="异常处理缺失",
        severity="P2",
        name="添加异常处理",
        description="添加 try-catch 块处理已知异常",
        strategy="quick_fix",
        downtime_seconds=0,
        code_quality_score=0.6,
        implementation_complexity=0.2,
        rollback_difficulty=0.1,
        steps=[
            "识别异常抛出点",
            "添加异常捕获",
            "记录异常日志",
            "添加恢复逻辑"
        ],
        priority=10
    ),
    RepairRule(
        damage_type="异常处理缺失",
        severity="P2",
        name="统一异常处理",
        description="建立统一的异常处理框架",
        strategy="balanced",
        downtime_seconds=2,
        code_quality_score=0.9,
        implementation_complexity=0.5,
        rollback_difficulty=0.3,
        steps=[
            "设计异常层级",
            "实现全局异常处理器",
            "添加重试和熔断机制",
            "统一错误响应格式"
        ],
        priority=20
    ),
    
    # ===== 依赖过时 =====
    RepairRule(
        damage_type="依赖过时",
        severity="P2",
        name="更新依赖版本",
        description="升级到最新稳定版本",
        strategy="quick_fix",
        downtime_seconds=1,
        code_quality_score=0.7,
        implementation_complexity=0.3,
        rollback_difficulty=0.4,
        steps=[
            "检查依赖更新日志",
            "更新依赖版本",
            "修复 API 变更",
            "运行测试套件"
        ],
        priority=10
    ),
    
    # ===== 默认规则 =====
    RepairRule(
        damage_type="*",
        severity="*",
        name="通用修复流程",
        description="标准的问题排查和修复流程",
        strategy="balanced",
        downtime_seconds=5,
        code_quality_score=0.7,
        implementation_complexity=0.5,
        rollback_difficulty=0.3,
        steps=[
            "分析问题根因",
            "设计修复方案",
            "实施修复",
            "验证效果",
            "添加监控"
        ],
        priority=0
    )
]


# ============================================================================
# 降级引擎
# ============================================================================

class FallbackEngine:
    """降级引擎
    
    当 LLM 预算超限或 API 不可用时，使用规则引擎生成方案。
    """
    
    def __init__(self):
        """初始化降级引擎"""
        self.rules = REPAIR_RULES
        self._build_index()
    
    def _build_index(self):
        """构建规则索引"""
        self._damage_type_index: Dict[str, List[RepairRule]] = {}
        
        for rule in self.rules:
            # 建立按损伤类型的索引
            key = rule.damage_type
            if key not in self._damage_type_index:
                self._damage_type_index[key] = []
            self._damage_type_index[key].append(rule)
    
    def find_rules(
        self, 
        damage_type: str, 
        severity: str
    ) -> List[RepairRule]:
        """查找匹配的规则
        
        Args:
            damage_type: 损伤类型
            severity: 严重程度
            
        Returns:
            匹配的规则列表（按优先级排序）
        """
        results = []
        
        # 精确匹配
        if damage_type in self._damage_type_index:
            for rule in self._damage_type_index[damage_type]:
                if rule.severity == severity or rule.severity == "*":
                    results.append(rule)
        
        # 如果没有精确匹配，使用默认规则
        if not results:
            for rule in self._damage_type_index.get("*", []):
                results.append(rule)
        
        # 按优先级排序
        results.sort(key=lambda r: r.priority, reverse=True)
        
        return results
    
    def generate_plans(
        self,
        damage_type: str,
        location: str,
        severity: str,
        symptoms: List[str],
        health_score: float,
        n_plans: int = 3
    ) -> List[Dict[str, Any]]:
        """使用规则引擎生成修复方案
        
        Args:
            damage_type: 损伤类型
            location: 损伤位置
            severity: 严重程度
            symptoms: 症状列表
            health_score: 当前健康度
            n_plans: 方案数量
            
        Returns:
            方案列表
        """
        print("📋 [FallbackEngine] 使用规则引擎生成方案...\n")
        
        rules = self.find_rules(damage_type, severity)
        
        plans = []
        seen_strategies = set()
        
        for rule in rules:
            if len(plans) >= n_plans:
                break
            
            # 避免重复策略
            if rule.strategy in seen_strategies:
                continue
            seen_strategies.add(rule.strategy)
            
            # 根据健康度调整评分
            health_factor = health_score  # 健康度越低，越需要彻底的修复
            
            plan = {
                "name": rule.name,
                "description": rule.description,
                "strategy": rule.strategy,
                "downtime_seconds": rule.downtime_seconds,
                "code_quality_score": rule.code_quality_score,
                "implementation_complexity": rule.implementation_complexity,
                "rollback_difficulty": rule.rollback_difficulty,
                "steps": rule.steps,
                "risks": [],
                "benefits": [],
                "source": "rule_engine",  # 标记来源
                "rule_id": f"{rule.damage_type}:{rule.name}"
            }
            
            plans.append(plan)
        
        # 如果方案数量不足，生成通用方案
        while len(plans) < n_plans:
            base_plan = {
                "name": f"方案 {chr(65 + len(plans))}",
                "description": "基于通用修复流程",
                "strategy": "balanced",
                "downtime_seconds": 5,
                "code_quality_score": 0.7,
                "implementation_complexity": 0.5,
                "rollback_difficulty": 0.3,
                "steps": [
                    "分析问题",
                    "设计解决方案",
                    "实施修复",
                    "验证效果"
                ],
                "risks": ["可能需要多次迭代"],
                "benefits": ["灵活性高"],
                "source": "rule_engine",
                "rule_id": "default"
            }
            plans.append(base_plan)
        
        return plans[:n_plans]
    
    def get_status(self) -> str:
        """获取引擎状态"""
        return (
            f"📋 降级引擎状态\n"
            f"  规则数量: {len(self.rules)}\n"
            f"  损伤类型覆盖: {len(self._damage_type_index) - 1}\n"
            f"  状态: ✅ 就绪"
        )


# ============================================================================
# 便捷函数
# ============================================================================

def create_fallback_engine() -> FallbackEngine:
    """创建降级引擎实例"""
    return FallbackEngine()


# ============================================================================
# 测试
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🧪 降级引擎测试")
    print("=" * 60)
    print()
    
    # 创建引擎
    engine = create_fallback_engine()
    
    # 打印状态
    print(engine.get_status())
    print()
    
    # 测试生成方案
    test_cases = [
        ("资源泄漏", "P0", 0.62),
        ("内存泄漏", "P1", 0.55),
        ("性能退化", "P1", 0.70),
        ("未知问题", "P2", 0.80)
    ]
    
    for damage_type, severity, health_score in test_cases:
        print(f"测试用例: {damage_type} ({severity})")
        plans = engine.generate_plans(
            damage_type=damage_type,
            location="src/test.py:100",
            severity=severity,
            symptoms=["测试症状"],
            health_score=health_score
        )
        
        for i, plan in enumerate(plans):
            print(f"  方案 {i+1}: {plan['name']} ({plan['strategy']})")
        print()
