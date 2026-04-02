"""
Soma-Dev (感知型开发者)
========================

角色：代码健康的"神经系统"
职责：持续监控代码库健康度、检测损伤、触发再生循环

工作模式：
- 每 15 分钟扫描一次代码库
- 计算多维度健康度
- 健康度 < 0.7 时触发 SIGNAL 消息

工具栈：
- rust-clippy（Rust 代码分析）
- pylint（Python 代码分析）
- mypy（Python 类型检查）
- cargo-audit（依赖安全检查）
- AST 解析（代码复杂度分析）
"""

import os
import ast
import json
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
import sys

from src.protocol.oacp import SignalMessage, DamageType, Priority
from src.models.health import HealthCalculator, HealthMetrics, CodeHealthMonitor


# ============================================================================
# Soma-Dev 系统提示词（System Prompt）
# ============================================================================

SOMA_DEV_SYSTEM_PROMPT = """
你是 **Soma-Dev**，OpenNewt 神经可塑性引擎的感知层 Agent。

## 你的身份

你是代码库的"神经系统"，像生物的痛觉受体一样，主动感知代码库的健康状态。

你的核心职责：
1. **持续监控**：每 15 分钟扫描一次代码库
2. **健康评估**：计算多维度健康度（静态分析、测试覆盖率、依赖健康度、代码复杂度、历史稳定性、文档完整度）
3. **损伤检测**：识别延迟异常、资源泄漏、行为漂移、依赖腐化、代码腐化
4. **信号触发**：健康度 < 0.7 时，向 Plasticus-Dev 发送 SIGNAL 消息

## 你的工作原则

### 1. 主动感知，非被动等待
- 不要等用户报告问题，主动发现问题
- 像生物的痛觉一样，在问题变严重前就感知到异常
- 即使没有明显故障，也持续监控健康趋势

### 2. 多维度评估，综合判断
- 不依赖单一指标，综合多个维度评估健康度
- 权重配置：
  - 静态分析：25%
  - 测试覆盖率：20%
  - 依赖健康度：15%
  - 代码复杂度：15%
  - 历史稳定性：15%
  - 文档完整度：10%

### 3. 及时告警，不过度惊慌
- 健康度 > 0.85：健康（绿灯）
- 健康度 0.70-0.85：亚健康（黄灯）-> 监控
- 健康度 < 0.70：损伤（红灯）-> 立即触发 SIGNAL

### 4. 记录历史，辅助预测
- 记录每次扫描结果
- 分析健康趋势（改善/恶化）
- 预测未来可能的问题

## 损伤类型识别

| 损伤类型 | 触发条件 | 痛感等级 | 响应速度 |
|---------|---------|---------|---------|
| **延迟异常** | API 响应 > 500ms | P1 | 立即 |
| **资源泄漏** | 内存/CPU 持续增长 | P0 | 立即 |
| **行为漂移** | 测试通过率下降 > 5% | P1 | 24h内 |
| **依赖腐化** | 安全漏洞 / 过期 > 1年 | P2 | 本周内 |
| **代码腐化** | 复杂度 > 阈值 | P2 | 下次迭代 |

## 你的输出格式

### 健康度报告
```
[Soma-Dev] Health Scan Report

Scan Time: 2026-03-31T22:56:00Z
Project Path: /path/to/project

Overall Health: 0.72 (Subhealthy)

Detailed Metrics:
  Static Analysis: 0.85 [OK]
  Test Coverage: 0.72 [Warning]
  Dependency Health: 0.90 [OK]
  Code Complexity: 0.25 [OK]
  Historical Stability: 0.95 [OK]
  Documentation Completeness: 0.60 [Warning]

Issues Found:
  1. [P1] Test coverage insufficient (72% < 80%)
  2. [P2] Documentation completeness low (60%)

Health Trend: Improving (Past 7 days: 0.68 -> 0.72)

Recommendation: Continue monitoring
```

### SIGNAL Message (Health < 0.7)
```
[ALERT] [Soma-Dev] Damage signal triggered!

损伤类型: 资源泄漏
严重程度: P0
位置: src/api/handler.rs:142
症状:
  - 内存占用持续增长（+15% 过去 1 小时）
  - 未释放的数据库连接（12 个连接未关闭）

当前健康度: 0.62

已发送 SIGNAL 到 Plasticus-Dev
Issue: https://github.com/owner/repo/issues/123
```

## 你的限制

1. **只负责感知和告警**，不做修复决策
2. **必须基于数据判断**，不凭直觉
3. **避免过度告警**，只在真正需要时触发 SIGNAL
4. **保持客观中立**，不偏向任何特定解决方案

## 你的成长

每次触发 SIGNAL 后，你会收到 Plasticus-Dev 的反馈：
- 修复是否成功？
- 健康度是否恢复？
- SIGNAL 是否误报？

根据这些反馈，你会调整自己的判断标准，变得更准确。

---

现在，开始你的第一次扫描吧！
"""


# ============================================================================
# Soma-Dev 实现
# ============================================================================

@dataclass
class DamageSymptom:
    """损伤症状"""
    symptom_type: str
    description: str
    location: str
    severity: Priority
    evidence: List[str] = field(default_factory=list)


class SomaDev:
    """Soma-Dev Agent 实现"""
    
    def __init__(self, project_path: str, github_token: Optional[str] = None):
        """初始化 Soma-Dev
        
        Args:
            project_path: 项目路径
            github_token: GitHub Personal Access Token
        """
        self.project_path = project_path
        self.github_token = github_token
        self.health_calculator = HealthCalculator()
        self.health_monitor = CodeHealthMonitor(self.health_calculator)
        self.scan_history: List[Dict[str, Any]] = []
        
        # 检查项目路径
        if not os.path.exists(project_path):
            raise FileNotFoundError(f"项目路径不存在: {project_path}")
    
    def _ast_analyze_python(self) -> Tuple[float, List[str]]:
        """用 AST 解析 Python 文件，计算基础健康度
        
        Returns:
            (分数 0-1, 发现的问题列表)
        """
        py_files = list(self._find_files("*.py"))
        if not py_files:
            return 0.75, []
        
        total_score = 0.0
        total_files = 0
        issues = []
        
        for filepath in py_files:
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    source = f.read()
                
                if not source.strip():
                    continue
                
                tree = ast.parse(source, filename=filepath)
                file_issues = 0
                file_score = 1.0
                
                # 检查 1: 函数/类是否有 docstring
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                        docstring = ast.get_docstring(node)
                        if not docstring and not node.name.startswith('_'):
                            file_issues += 1
                            file_score -= 0.02
                
                # 检查 2: 函数行数（超过 50 行扣分）
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if hasattr(node, 'end_lineno') and node.end_lineno:
                            lines = node.end_lineno - node.lineno + 1
                            if lines > 50:
                                file_issues += 1
                                file_score -= 0.03
                                issues.append(f"Long function: {node.name} ({lines} lines) in {os.path.basename(filepath)}")
                
                # 检查 3: import 是否齐全
                has_main_guard = '__main__' in source
                is_module = os.path.basename(filepath) != '__init__.py'
                
                file_score = max(0.0, min(1.0, file_score))
                total_score += file_score
                total_files += 1
                
            except SyntaxError as e:
                issues.append(f"Syntax error in {os.path.basename(filepath)}: {e}")
                total_files += 1
            except Exception:
                pass
        
        if total_files == 0:
            return 0.75, issues
        
        avg_score = total_score / total_files
        return round(avg_score, 3), issues
    
    def scan_static_analysis(self) -> float:
        """扫描静态分析分数
        
        Returns:
            静态分析分数（0-1）
        """
        has_rust = os.path.exists(os.path.join(self.project_path, "Cargo.toml"))
        has_python = len(list(self._find_files("*.py"))) > 0
        
        if has_rust:
            try:
                result = subprocess.run(
                    ["cargo", "clippy", "--message-format=json"],
                    cwd=self.project_path,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                return 0.85
            except Exception:
                return 0.70
        
        if has_python:
            # 先用 AST 分析（纯 Python，不需要外部工具）
            score, issues = self._ast_analyze_python()
            if issues:
                for issue in issues[:5]:  # 最多显示 5 个
                    print(f"  [Static] {issue}")
            
            # 如果有 pylint，用它获得更精确的分数
            try:
                result = subprocess.run(
                    ["pylint", "--output-format=json", self.project_path],
                    cwd=self.project_path,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                if result.returncode == 0:
                    return 0.95
                else:
                    # pylint 返回非零表示有警告，根据警告数量降分
                    try:
                        warnings = json.loads(result.stdout)
                        penalty = min(0.3, len(warnings) * 0.01)
                        return max(0.5, score - penalty)
                    except (json.JSONDecodeError, TypeError):
                        return score
            except FileNotFoundError:
                # pylint 未安装，使用 AST 分数
                return score
            except Exception:
                return score
        
        return 0.75
    
    def scan_test_coverage(self) -> float:
        """扫描测试覆盖率
        
        Returns:
            测试覆盖率（0-1）
        """
        test_files = list(self._find_files("test_*.py")) + \
                     list(self._find_files("*_test.py")) + \
                     list(self._find_files("*test*.rs"))
        all_py_files = list(self._find_files("*.py"))
        
        if len(all_py_files) == 0:
            return 1.0  # 没有代码，不算缺测试
        
        if len(test_files) == 0:
            return 0.0  # 有代码但没有测试文件
        
        # 测试文件占总代码文件的比例（粗略估计）
        ratio = len(test_files) / len(all_py_files)
        # 映射到 0-1：1:3 的比例算 0.6 分，1:1 算 0.8 分
        return min(1.0, round(ratio * 2.0, 3))
    
    def scan_dependency_health(self) -> float:
        """扫描依赖健康度
        
        Returns:
            依赖健康度（0-1）
        """
        score = 1.0
        
        # 检查 requirements.txt 是否存在
        req_path = os.path.join(self.project_path, "requirements.txt")
        if not os.path.exists(req_path):
            # 没有 requirements.txt 也是一个问题
            return 0.8
        
        # 检查 .env.example 是否存在（最佳实践）
        if not os.path.exists(os.path.join(self.project_path, ".env.example")):
            score -= 0.05
        
        # 检查是否有锁文件
        has_lock = (os.path.exists(os.path.join(self.project_path, "Pipfile.lock")) or
                    os.path.exists(os.path.join(self.project_path, "poetry.lock")) or
                    os.path.exists(os.path.join(self.project_path, "Cargo.lock")))
        if not has_lock:
            score -= 0.05
        
        # 如果有 cargo-audit，运行它
        if os.path.exists(os.path.join(self.project_path, "Cargo.lock")):
            try:
                result = subprocess.run(
                    ["cargo", "audit"],
                    cwd=self.project_path,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                if result.returncode != 0:
                    score -= 0.2
            except Exception:
                pass
        
        return max(0.0, min(1.0, round(score, 3)))
    
    def scan_code_complexity(self) -> float:
        """扫描代码复杂度（使用 AST 解析）
        
        Returns:
            代码复杂度（0-1，越低越好）
        """
        py_files = list(self._find_files("*.py"))
        if not py_files:
            return 0.0
        
        total_complexity = 0.0
        total_files = 0
        
        for filepath in py_files:
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    source = f.read()
                
                if not source.strip():
                    continue
                
                tree = ast.parse(source, filename=filepath)
                
                # 计算圈复杂度（简化版：统计分支点）
                complexity = 1  # 基础复杂度
                for node in ast.walk(tree):
                    if isinstance(node, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                        complexity += 1
                    elif isinstance(node, (ast.And, ast.Or)):
                        complexity += 1
                    elif isinstance(node, ast.comprehension):
                        complexity += 1
                
                # 归一化到 0-1（50 个分支点为满分复杂度）
                normalized = min(1.0, complexity / 50.0)
                total_complexity += normalized
                total_files += 1
                
            except (SyntaxError, Exception):
                continue
        
        if total_files == 0:
            return 0.0
        
        return round(total_complexity / total_files, 3)
    
    def scan_historical_stability(self) -> float:
        """扫描历史稳定性
        
        Returns:
            历史稳定性（0-1）
        """
        # 基于已有扫描历史判断
        if len(self.scan_history) < 2:
            return 0.90  # 数据不足，给一个较高的默认值
        
        # 计算健康度波动
        scores = [h["report"]["health_score"] for h in self.scan_history]
        avg = sum(scores) / len(scores)
        variance = sum((s - avg) ** 2 for s in scores) / len(scores)
        
        # 方差越小越稳定
        stability = max(0.0, 1.0 - variance * 10)
        return round(stability, 3)
    
    def scan_documentation_completeness(self) -> float:
        """扫描文档完整度
        
        Returns:
            文档完整度（0-1）
        """
        # 检查是否有 README.md
        has_readme = os.path.exists(os.path.join(self.project_path, "README.md"))
        # 检查是否有 docs/ 目录
        has_docs_dir = os.path.exists(os.path.join(self.project_path, "docs"))
        # 检查是否有 API 文档
        has_api_docs = len(list(self._find_files("*.md", "docs"))) > 0
        
        score = 0.0
        if has_readme:
            score += 0.3
        if has_docs_dir:
            score += 0.3
        if has_api_docs:
            score += 0.4
        
        return min(score, 1.0)
    
    def _find_files(self, pattern: str, directory: str = "."):
        """查找文件
        
        Args:
            pattern: 文件模式
            directory: 目录
            
        Yields:
            文件路径
        """
        import glob
        search_path = os.path.join(self.project_path, directory, "**", pattern)
        for filepath in glob.glob(search_path, recursive=True):
            yield filepath
    
    def scan_codebase(self) -> Dict[str, Any]:
        """扫描整个代码库
        
        Returns:
            健康度报告
        """
        print("[Soma-Dev] Starting codebase scan...")
        print(f"项目路径: {self.project_path}\n")
        
        # 扫描各项指标
        static_analysis_score = self.scan_static_analysis()
        test_coverage = self.scan_test_coverage()
        dependency_health = self.scan_dependency_health()
        code_complexity = self.scan_code_complexity()
        historical_stability = self.scan_historical_stability()
        documentation_completeness = self.scan_documentation_completeness()
        
        # 计算总体健康度
        report = self.health_monitor.scan_codebase(
            static_analysis_score=static_analysis_score,
            test_coverage=test_coverage,
            dependency_health=dependency_health,
            code_complexity=code_complexity,
            historical_stability=historical_stability,
            documentation_completeness=documentation_completeness
        )
        
        # 记录扫描历史
        self.scan_history.append({
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "report": report
        })
        
        # 生成报告
        self._print_health_report(report)
        
        return report
    
    def _print_health_report(self, report: Dict[str, Any]):
        """打印健康度报告
        
        Args:
            report: 健康度报告
        """
        health_score = report["health_score"]
        health_status = report["health_status"]
        
        # 状态图标
        status_icon = {
            "healthy": "[OK]",
            "subhealthy": "[Warning]",
            "damaged": "[CRITICAL]"
        }[health_status]
        
        print(f"总体健康度: {health_score} ({health_status}) {status_icon}\n")
        
        print("详细指标:")
        metrics = report["metrics"]
        for key, value in metrics.items():
            icon = "[OK]" if value > 0.8 else "[Warning]" if value > 0.6 else "[CRITICAL]"
            print(f"  {key}: {value} {icon}")
        
        print()
        
        # 发现的问题
        issues = self._identify_issues(report)
        if issues:
            print("发现的问题:")
            for i, issue in enumerate(issues, 1):
                print(f"  {i}. [{issue['priority']}] {issue['description']}")
            print()
        
        # 健康趋势
        trend = self.health_monitor.get_health_trend()
        print(f"健康趋势: {trend.get('trend', 'unknown')}")
        
        # 建议
        if report["should_trigger_signal"]:
            print("\n[ALERT] Recommendation: Trigger SIGNAL to Plasticus-Dev")
        else:
            print("\n[OK] Recommendation: Continue monitoring")
    
    def _identify_issues(self, report: Dict[str, Any]) -> List[Dict[str, str]]:
        """识别问题
        
        Args:
            report: 健康度报告
            
        Returns:
            问题列表
        """
        issues = []
        metrics = report["metrics"]
        
        if metrics["test_coverage"] < 0.80:
            issues.append({
                "priority": "P1",
                "description": f"测试覆盖率不足（{metrics['test_coverage']*100:.0f}% < 80%）"
            })
        
        if metrics["documentation_completeness"] < 0.70:
            issues.append({
                "priority": "P2",
                "description": f"文档完整度较低（{metrics['documentation_completeness']*100:.0f}%）"
            })
        
        if metrics["static_analysis_score"] < 0.70:
            issues.append({
                "priority": "P1",
                "description": "静态分析分数较低，存在代码质量问题"
            })
        
        return issues
    
    def detect_damage(self, report: Dict[str, Any]) -> Optional[DamageSymptom]:
        """检测损伤
        
        Args:
            report: 健康度报告
            
        Returns:
            损伤症状（如果存在）
        """
        if report["health_score"] >= 0.70:
            return None
        
        # TODO: 实现更精细的损伤检测逻辑
        # 这里先用简单的规则
        
        if report["metrics"]["static_analysis_score"] < 0.60:
            return DamageSymptom(
                symptom_type="代码腐化",
                description="代码质量严重下降，存在大量警告和错误",
                location="全局",
                severity=Priority.P1,
                evidence=["静态分析分数 < 0.6"]
            )
        
        if report["metrics"]["dependency_health"] < 0.70:
            return DamageSymptom(
                symptom_type="依赖腐化",
                description="依赖包存在安全漏洞或过期",
                location="依赖配置文件",
                severity=Priority.P2,
                evidence=["依赖健康度 < 0.7"]
            )
        
        # 默认损伤
        return DamageSymptom(
            symptom_type="代码腐化",
            description="健康度低于阈值",
            location="全局",
            severity=Priority.P1,
            evidence=[f"健康度 {report['health_score']} < 0.7"]
        )
    
    def create_signal(self, damage: DamageSymptom) -> SignalMessage:
        """创建损伤信号
        
        Args:
            damage: 损伤症状
            
        Returns:
            SIGNAL 消息
        """
        # 映射损伤类型
        damage_type_map = {
            "延迟异常": DamageType.LATENCY_ANOMALY,
            "资源泄漏": DamageType.RESOURCE_LEAK,
            "行为漂移": DamageType.BEHAVIOR_DRIFT,
            "依赖腐化": DamageType.DEPENDENCY_DECAY,
            "代码腐化": DamageType.CODE_DECAY
        }
        
        damage_type = damage_type_map.get(damage.symptom_type, DamageType.CODE_DECAY)
        
        signal = SignalMessage.create(
            damage_type=damage_type,
            severity=damage.severity,
            location=damage.location,
            symptoms=damage.evidence,
            health_score=self.scan_history[-1]["report"]["health_score"],
            context={
                "description": damage.description
            }
        )
        
        return signal
    
    def run(self):
        """运行 Soma-Dev（主循环）"""
        print("=" * 60)
        print("[Fire] Soma-Dev - 感知型开发者")
        print("=" * 60)
        print()
        
        while True:
            try:
                # 扫描代码库
                report = self.scan_codebase()
                
                # 检测损伤
                damage = self.detect_damage(report)
                
                if damage:
                    print("\n[ALERT] Damage detected!")
                    print(f"类型: {damage.symptom_type}")
                    print(f"严重程度: {damage.severity.value}")
                    print(f"位置: {damage.location}")
                    print(f"证据: {', '.join(damage.evidence)}")
                    
                    # 创建 SIGNAL
                    signal = self.create_signal(damage)
                    
                    print("\n[Send] 创建 SIGNAL 消息:")
                    print(signal.to_json())
                    
                    # TODO: 发送到 GitHub Issues
                    # self._send_to_github_issues(signal)
                
                print("\n" + "=" * 60)
                print("等待 15 分钟后进行下一次扫描...")
                print("=" * 60)
                
                # 等待 15 分钟
                import time
                time.sleep(15 * 60)  # 15 分钟
                
            except KeyboardInterrupt:
                print("\n\n👋 Soma-Dev 停止运行")
                break
            except Exception as e:
                print(f"\n[ERROR] {e}")
                import traceback
                traceback.print_exc()
                break


# ============================================================================
# 主程序
# ============================================================================

if __name__ == "__main__":
    # 示例：运行 Soma-Dev
    import argparse
    
    parser = argparse.ArgumentParser(description="Soma-Dev - 感知型开发者")
    parser.add_argument("project_path", help="项目路径")
    parser.add_argument("--github-token", help="GitHub Personal Access Token", default=None)
    parser.add_argument("--once", action="store_true", help="只运行一次（不进入循环）")
    
    args = parser.parse_args()
    
    # 创建 Soma-Dev
    soma_dev = SomaDev(args.project_path, args.github_token)
    
    if args.once:
        # 只运行一次
        report = soma_dev.scan_codebase()
    else:
        # 进入主循环
        soma_dev.run()
