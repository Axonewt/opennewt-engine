"""
健康度计算模型 - Soma-Dev 核心算法

计算代码库的多维度健康度，判断是否触发损伤信号
"""

from dataclasses import dataclass
from typing import List, Dict, Optional
import json


@dataclass
class HealthMetrics:
    """健康度指标"""
    static_analysis_score: float  # 静态分析分数（0-1）
    test_coverage: float  # 测试覆盖率（0-1）
    dependency_health: float  # 依赖健康度（0-1）
    code_complexity: float  # 代码复杂度（反向，越低越好）
    historical_stability: float  # 历史稳定性（0-1）
    documentation_completeness: float  # 文档完整度（0-1）
    
    def to_dict(self) -> Dict[str, float]:
        """转换为字典"""
        return {
            "static_analysis_score": self.static_analysis_score,
            "test_coverage": self.test_coverage,
            "dependency_health": self.dependency_health,
            "code_complexity": self.code_complexity,
            "historical_stability": self.historical_stability,
            "documentation_completeness": self.documentation_completeness
        }


@dataclass
class HealthWeights:
    """健康度权重配置"""
    static_analysis: float = 0.25
    test_coverage: float = 0.20
    dependency_health: float = 0.15
    code_complexity: float = 0.15
    historical_stability: float = 0.15
    documentation: float = 0.10
    
    def validate(self) -> bool:
        """验证权重总和为 1"""
        total = (self.static_analysis + self.test_coverage + 
                 self.dependency_health + self.code_complexity + 
                 self.historical_stability + self.documentation)
        return abs(total - 1.0) < 0.001


class HealthCalculator:
    """健康度计算器"""
    
    def __init__(self, weights: Optional[HealthWeights] = None):
        """初始化
        
        Args:
            weights: 健康度权重配置，默认使用标准配置
        """
        self.weights = weights or HealthWeights()
        assert self.weights.validate(), "权重总和必须为 1"
    
    def calculate(self, metrics: HealthMetrics) -> float:
        """计算总体健康度
        
        Args:
            metrics: 健康度指标
            
        Returns:
            健康度分数（0-1）
        """
        health_score = (
            metrics.static_analysis_score * self.weights.static_analysis +
            metrics.test_coverage * self.weights.test_coverage +
            metrics.dependency_health * self.weights.dependency_health +
            (1 - metrics.code_complexity) * self.weights.code_complexity +  # 复杂度反向
            metrics.historical_stability * self.weights.historical_stability +
            metrics.documentation_completeness * self.weights.documentation
        )
        
        return round(health_score, 3)
    
    def get_health_status(self, health_score: float) -> str:
        """获取健康状态
        
        Args:
            health_score: 健康度分数
            
        Returns:
            健康状态（"healthy" | "subhealthy" | "damaged"）
        """
        if health_score > 0.85:
            return "healthy"
        elif health_score >= 0.70:
            return "subhealthy"
        else:
            return "damaged"
    
    def should_trigger_signal(self, health_score: float) -> bool:
        """判断是否触发损伤信号
        
        Args:
            health_score: 健康度分数
            
        Returns:
            是否触发信号
        """
        return health_score < 0.70


class CodeHealthMonitor:
    """代码健康监控器（Soma-Dev 核心组件）"""
    
    def __init__(self, health_calculator: Optional[HealthCalculator] = None):
        """初始化
        
        Args:
            health_calculator: 健康度计算器
        """
        self.calculator = health_calculator or HealthCalculator()
        self.history: List[Dict[str, any]] = []
    
    def scan_codebase(
        self,
        static_analysis_score: float,
        test_coverage: float,
        dependency_health: float,
        code_complexity: float,
        historical_stability: float,
        documentation_completeness: float
    ) -> Dict[str, any]:
        """扫描代码库并计算健康度
        
        Args:
            各项健康度指标（0-1）
            
        Returns:
            健康度报告
        """
        metrics = HealthMetrics(
            static_analysis_score=static_analysis_score,
            test_coverage=test_coverage,
            dependency_health=dependency_health,
            code_complexity=code_complexity,
            historical_stability=historical_stability,
            documentation_completeness=documentation_completeness
        )
        
        health_score = self.calculator.calculate(metrics)
        health_status = self.calculator.get_health_status(health_score)
        should_signal = self.calculator.should_trigger_signal(health_score)
        
        report = {
            "health_score": health_score,
            "health_status": health_status,
            "should_trigger_signal": should_signal,
            "metrics": metrics.to_dict(),
            "weights": {
                "static_analysis": self.calculator.weights.static_analysis,
                "test_coverage": self.calculator.weights.test_coverage,
                "dependency_health": self.calculator.weights.dependency_health,
                "code_complexity": self.calculator.weights.code_complexity,
                "historical_stability": self.calculator.weights.historical_stability,
                "documentation": self.calculator.weights.documentation
            }
        }
        
        # 记录历史
        self.history.append({
            "timestamp": "2026-03-31T22:46:00Z",  # TODO: 使用真实时间戳
            "report": report
        })
        
        return report
    
    def get_health_trend(self, days: int = 7) -> Dict[str, any]:
        """获取健康度趋势
        
        Args:
            days: 统计天数
            
        Returns:
            趋势数据
        """
        # TODO: 实现真实的历史数据分析
        if len(self.history) == 0:
            return {"trend": "no_data", "message": "暂无历史数据"}
        
        recent_scores = [h["report"]["health_score"] for h in self.history[-days:]]
        
        if len(recent_scores) < 2:
            return {"trend": "insufficient_data", "message": "数据不足"}
        
        avg_score = sum(recent_scores) / len(recent_scores)
        trend = "improving" if recent_scores[-1] > recent_scores[0] else "declining"
        
        return {
            "trend": trend,
            "average_score": round(avg_score, 3),
            "latest_score": recent_scores[-1],
            "days_analyzed": len(recent_scores)
        }


# 示例使用
if __name__ == "__main__":
    # 创建健康度计算器
    calculator = HealthCalculator()
    
    # 示例：计算一个项目的健康度
    metrics = HealthMetrics(
        static_analysis_score=0.85,  # clippy/pylint 分数
        test_coverage=0.72,  # 测试覆盖率 72%
        dependency_health=0.90,  # 依赖健康度
        code_complexity=0.25,  # 复杂度较低（好事）
        historical_stability=0.95,  # 最近 30 天很稳定
        documentation_completeness=0.60  # 文档完整度 60%
    )
    
    health_score = calculator.calculate(metrics)
    health_status = calculator.get_health_status(health_score)
    should_signal = calculator.should_trigger_signal(health_score)
    
    print(f"健康度分数: {health_score}")
    print(f"健康状态: {health_status}")
    print(f"是否触发信号: {should_signal}")
    print(f"\n详细指标:")
    for key, value in metrics.to_dict().items():
        print(f"  {key}: {value}")
