"""
可塑性评估矩阵 - Plasticus-Dev 核心算法

评估多套修复方案的得分，选择最优方案
"""

from dataclasses import dataclass
from typing import List, Dict, Optional
import json


@dataclass
class RepairPlan:
    """修复方案"""
    plan_id: str
    name: str
    description: str
    downtime_seconds: float  # 停机时间（秒）
    code_quality_score: float  # 代码质量分数（0-1）
    implementation_complexity: float  # 实现复杂度（反向，越低越好）
    historical_success_rate: float  # 历史成功率（0-1）
    rollback_difficulty: float  # 回滚难度（反向，越低越好）
    estimated_cost: float  # 预估成本（美元）
    steps: List[Dict[str, any]]  # 执行步骤
    
    def to_dict(self) -> Dict[str, any]:
        """转换为字典"""
        return {
            "plan_id": self.plan_id,
            "name": self.name,
            "description": self.description,
            "downtime_seconds": self.downtime_seconds,
            "code_quality_score": self.code_quality_score,
            "implementation_complexity": self.implementation_complexity,
            "historical_success_rate": self.historical_success_rate,
            "rollback_difficulty": self.rollback_difficulty,
            "estimated_cost": self.estimated_cost,
            "steps": self.steps
        }


@dataclass
class PlasticityWeights:
    """可塑性评估权重配置"""
    downtime: float = 0.30  # 停机时间权重
    code_quality: float = 0.25  # 代码质量权重
    implementation_complexity: float = 0.20  # 实现复杂度权重
    historical_success: float = 0.15  # 历史成功率权重
    rollback_difficulty: float = 0.10  # 回滚难度权重
    
    def validate(self) -> bool:
        """验证权重总和为 1"""
        total = (self.downtime + self.code_quality + 
                 self.implementation_complexity + 
                 self.historical_success + self.rollback_difficulty)
        return abs(total - 1.0) < 0.001


@dataclass
class ScoredPlan:
    """评分后的方案"""
    plan: RepairPlan
    score: float
    score_breakdown: Dict[str, float]
    
    def to_dict(self) -> Dict[str, any]:
        """转换为字典"""
        return {
            "plan_id": self.plan.plan_id,
            "name": self.plan.name,
            "total_score": round(self.score, 3),
            "score_breakdown": {k: round(v, 3) for k, v in self.score_breakdown.items()},
            "plan_details": self.plan.to_dict()
        }


class PlasticityEvaluator:
    """可塑性评估器"""
    
    def __init__(self, weights: Optional[PlasticityWeights] = None):
        """初始化
        
        Args:
            weights: 可塑性评估权重配置
        """
        self.weights = weights or PlasticityWeights()
        assert self.weights.validate(), "权重总和必须为 1"
    
    def normalize_downtime(self, downtime_seconds: float) -> float:
        """归一化停机时间（越短越好）
        
        Args:
            downtime_seconds: 停机时间（秒）
            
        Returns:
            归一化分数（0-1）
        """
        # 0s = 1.0, 10s = 0.5, 30s+ = 0.0
        if downtime_seconds <= 0:
            return 1.0
        elif downtime_seconds >= 30:
            return 0.0
        else:
            return 1.0 - (downtime_seconds / 30.0)
    
    def normalize_complexity(self, complexity: float) -> float:
        """归一化复杂度（越低越好）
        
        Args:
            complexity: 复杂度（0-1，越低越好）
            
        Returns:
            归一化分数（0-1）
        """
        # 已经是 0-1，越低越好，所以反转
        return 1.0 - complexity
    
    def normalize_rollback_difficulty(self, difficulty: float) -> float:
        """归一化回滚难度（越低越好）
        
        Args:
            difficulty: 回滚难度（0-1，越低越好）
            
        Returns:
            归一化分数（0-1）
        """
        # 已经是 0-1，越低越好，所以反转
        return 1.0 - difficulty
    
    def evaluate_plan(self, plan: RepairPlan) -> ScoredPlan:
        """评估单个方案
        
        Args:
            plan: 修复方案
            
        Returns:
            评分后的方案
        """
        # 归一化各项指标
        downtime_score = self.normalize_downtime(plan.downtime_seconds)
        complexity_score = self.normalize_complexity(plan.implementation_complexity)
        rollback_score = self.normalize_rollback_difficulty(plan.rollback_difficulty)
        
        # 计算加权分数
        score_breakdown = {
            "downtime": downtime_score * self.weights.downtime,
            "code_quality": plan.code_quality_score * self.weights.code_quality,
            "implementation_complexity": complexity_score * self.weights.implementation_complexity,
            "historical_success": plan.historical_success_rate * self.weights.historical_success,
            "rollback_difficulty": rollback_score * self.weights.rollback_difficulty
        }
        
        total_score = sum(score_breakdown.values())
        
        return ScoredPlan(
            plan=plan,
            score=total_score,
            score_breakdown=score_breakdown
        )
    
    def evaluate_plans(self, plans: List[RepairPlan]) -> List[ScoredPlan]:
        """评估多套方案并排序
        
        Args:
            plans: 修复方案列表
            
        Returns:
            评分后的方案列表（按得分降序）
        """
        scored_plans = [self.evaluate_plan(plan) for plan in plans]
        scored_plans.sort(key=lambda x: x.score, reverse=True)
        return scored_plans
    
    def select_best_plan(self, plans: List[RepairPlan]) -> Optional[ScoredPlan]:
        """选择最优方案
        
        Args:
            plans: 修复方案列表
            
        Returns:
            最优方案（如果存在）
        """
        if not plans:
            return None
        
        scored_plans = self.evaluate_plans(plans)
        best_plan = scored_plans[0]
        
        # 如果得分最高的方案得分 < 0.5，说明所有方案都不理想
        if best_plan.score < 0.5:
            # TODO: 触发人工确认
            pass
        
        return best_plan


class BlueprintGenerator:
    """蓝图生成器（Plasticus-Dev 核心组件）"""
    
    def __init__(self, evaluator: Optional[PlasticityEvaluator] = None):
        """初始化
        
        Args:
            evaluator: 可塑性评估器
        """
        self.evaluator = evaluator or PlasticityEvaluator()
    
    def generate_plans_from_signal(
        self,
        damage_type: str,
        location: str,
        symptoms: List[str],
        health_score: float,
        historical_cases: Optional[List[Dict]] = None
    ) -> List[RepairPlan]:
        """从损伤信号生成多套修复方案
        
        Args:
            damage_type: 损伤类型
            location: 损伤位置
            symptoms: 症状列表
            health_score: 当前健康度
            historical_cases: 历史案例（用于复用成功模式）
            
        Returns:
            修复方案列表（至少 3 套）
        """
        # TODO: 实现 LLM 多次采样生成方案
        # 这里先用示例方案
        
        plans = []
        
        # 方案 A: 热补丁（快速但质量一般）
        plans.append(RepairPlan(
            plan_id=f"regen-{damage_type}-A",
            name="热补丁修复",
            description=f"快速修补 {location} 的 {damage_type}",
            downtime_seconds=0.0,
            code_quality_score=0.6,
            implementation_complexity=0.2,  # 简单
            historical_success_rate=0.7,
            rollback_difficulty=0.1,  # 容易回滚
            estimated_cost=0.5,
            steps=[
                {"step": 1, "action": "添加临时补丁"},
                {"step": 2, "action": "验证补丁有效性"},
                {"step": 3, "action": "部署到生产"}
            ]
        ))
        
        # 方案 B: 局部重构（平衡方案）
        plans.append(RepairPlan(
            plan_id=f"regen-{damage_type}-B",
            name="局部重构",
            description=f"重构 {location} 的相关模块",
            downtime_seconds=2.0,
            code_quality_score=0.9,
            implementation_complexity=0.4,  # 中等
            historical_success_rate=0.85,
            rollback_difficulty=0.3,  # 中等难度回滚
            estimated_cost=2.0,
            steps=[
                {"step": 1, "action": "创建隔离分支"},
                {"step": 2, "action": "重构代码"},
                {"step": 3, "action": "运行测试"},
                {"step": 4, "action": "灰度发布（10%流量）"},
                {"step": 5, "action": "逐步增加至100%"}
            ]
        ))
        
        # 方案 C: 完全重写（质量最高但成本高）
        plans.append(RepairPlan(
            plan_id=f"regen-{damage_type}-C",
            name="完全重写",
            description=f"完全重写 {location} 的实现",
            downtime_seconds=10.0,
            code_quality_score=1.0,
            implementation_complexity=0.8,  # 复杂
            historical_success_rate=0.95,
            rollback_difficulty=0.7,  # 难以回滚
            estimated_cost=10.0,
            steps=[
                {"step": 1, "action": "分析现有代码"},
                {"step": 2, "action": "设计新架构"},
                {"step": 3, "action": "实现新代码"},
                {"step": 4, "action": "全面测试"},
                {"step": 5, "action": "并行运行验证"},
                {"step": 6, "action": "切换流量"}
            ]
        ))
        
        return plans
    
    def select_and_generate_blueprint(
        self,
        damage_type: str,
        location: str,
        symptoms: List[str],
        health_score: float
    ) -> Optional[Dict[str, any]]:
        """生成蓝图（端到端流程）
        
        Args:
            damage_type: 损伤类型
            location: 损伤位置
            symptoms: 症状列表
            health_score: 当前健康度
            
        Returns:
            蓝图数据（用于发送给 Effector-Dev）
        """
        # 1. 生成多套方案
        plans = self.generate_plans_from_signal(
            damage_type, location, symptoms, health_score
        )
        
        # 2. 评估并选择最优方案
        best_plan = self.evaluator.select_best_plan(plans)
        
        if not best_plan:
            return None
        
        # 3. 生成蓝图
        # TODO: 转换为 BlueprintMessage 格式
        return best_plan.to_dict()


# 示例使用
if __name__ == "__main__":
    # 创建评估器
    evaluator = PlasticityEvaluator()
    
    # 示例：评估三套方案
    plan_a = RepairPlan(
        plan_id="regen-001-A",
        name="热补丁",
        description="快速修复",
        downtime_seconds=0.0,
        code_quality_score=0.6,
        implementation_complexity=0.2,
        historical_success_rate=0.7,
        rollback_difficulty=0.1,
        estimated_cost=0.5,
        steps=[]
    )
    
    plan_b = RepairPlan(
        plan_id="regen-001-B",
        name="重构连接池",
        description="重构连接池实现",
        downtime_seconds=2.0,
        code_quality_score=0.9,
        implementation_complexity=0.4,
        historical_success_rate=0.85,
        rollback_difficulty=0.3,
        estimated_cost=2.0,
        steps=[]
    )
    
    plan_c = RepairPlan(
        plan_id="regen-001-C",
        name="完全重写",
        description="完全重写连接池",
        downtime_seconds=10.0,
        code_quality_score=1.0,
        implementation_complexity=0.8,
        historical_success_rate=0.95,
        rollback_difficulty=0.7,
        estimated_cost=10.0,
        steps=[]
    )
    
    plans = [plan_a, plan_b, plan_c]
    scored_plans = evaluator.evaluate_plans(plans)
    
    print("方案评分结果：\n")
    for i, sp in enumerate(scored_plans, 1):
        print(f"{i}. {sp.plan.name}")
        print(f"   总分: {sp.score:.3f}")
        print(f"   详细得分:")
        for key, value in sp.score_breakdown.items():
            print(f"     - {key}: {value:.3f}")
        print()
    
    print(f"✓ 推荐方案: {scored_plans[0].plan.name}")
