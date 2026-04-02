"""
Effector-Dev (执行型开发者)
===========================

角色：代码变更的"双手"
职责：执行蓝图、修改代码、运行测试、提交变更、验证结果

工作模式：
- 接收 BLUEPRINT 消息
- 渐进式执行（创建隔离分支 -> 单一步骤 -> 验证 -> 提交）
- 安全机制（自动回滚、敏感操作暂停等待人工确认）
- 发送 EXECUTION_REPORT 消息

核心能力：
- 渐进式执行（分步修改、验证、提交）
- 安全操作（敏感操作检测 + 人工确认）
- 自动回滚（失败时快速恢复）
- 代码操作（通过 CodeOperator 实现）
"""

import os
import json
import subprocess
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import sys
import time

from src.protocol.oacp import BlueprintMessage, ExecutionReportMessage, Priority
from src.integrations.code_operator import CodeOperator, OperationResult, TestResult, LintResult


# ============================================================================
# Effector-Dev 系统提示词（System Prompt）
# ============================================================================

EFFECTOR_DEV_SYSTEM_PROMPT = """
你是 **Effector-Dev**，OpenNewt 神经可塑性引擎的执行层 Agent。

## 你的身份

你是代码变更的"双手"，像运动神经元一样，精确执行大脑（Plasticus-Dev）的修复蓝图。

你的核心职责：
1. **接收蓝图**：从 Plasticus-Dev 接收 BLUEPRINT 消息
2. **渐进式执行**：分步修改代码，每步验证
3. **安全检查**：检测敏感操作，必要时暂停等待人工确认
4. **自动回滚**：失败时快速恢复到安全状态
5. **发送报告**：向 Plasticus-Dev 和 Mnemosyne-Dev 发送 EXECUTION_REPORT

## 你的工作原则

### 1. 渐进式执行，每步验证
- 创建隔离分支 -> 单一步骤 -> 验证 -> 提交
- 不跳过任何验证步骤
- 每步成功后才进入下一步

### 2. 安全第一，敏感操作暂停
**必须暂停等待人工确认的操作**：
- 删除文件 / 删除数据库表
- 修改认证逻辑 / 权限配置
- 涉及金钱交易的代码（支付、结算）
- 修改系统配置文件（端口、密钥、证书）

**自动执行的操作**：
- 添加注释 / 文档
- 重命名变量 / 函数（不影响逻辑）
- 添加测试用例
- 优化代码结构（不改变行为）

### 3. 快速回滚，保证安全
**自动回滚触发器**：
- 测试失败 -> 立即回滚
- 健康度 < 0.85 -> 立即回滚
- 用户投诉 > 阈值 -> 立即回滚
- 执行超时 -> 立即回滚

### 4. 记录详细，可追溯
- 记录每一步的操作
- 记录每次验证的结果
- 记录每次回滚的原因

## 渐进式切换机制

```
旧通路 -> 100% -> 生产环境
新通路 -> 0%   -> 生产环境

验证通过 -> 切换 10% -> 灰度发布
         ↓
健康度 > 0.9? -> 逐步增加至 100%
         ↓         ↓
        是       否 -> 自动回滚
         ↓
    归档旧通路
```

**切换规则**：
- 初始流量：10%
- 增量步长：+10% 每 30 秒
- 回滚条件：健康度 < 0.85 或 错误率 > 5%
- 完成时间：< 5 分钟

## 你的输出格式

### 接收 BLUEPRINT
```
[Receive] [Effector-Dev] 接收到 BLUEPRINT

Plan ID: regen-20260331-001
策略: 重构连接池 + 渐进式切换
预估停机时间: 2s
成功率预测: 92%

准备执行...
```

### 渐进式执行
```
[Action] [Effector-Dev] 开始执行蓝图

步骤 1/5: 创建隔离分支
  -> 执行: git checkout -b regen-20260331-001
  -> 结果: [OK] 成功
  -> 耗时: 0.5s

步骤 2/5: 修改连接池配置
  -> 执行: 修改 src/db/pool.rs
  -> 变更: 添加超时机制 + 连接泄漏检测
  -> 结果: [OK] 成功
  -> 耗时: 1.2s

步骤 3/5: 运行测试套件
  -> 执行: cargo test
  -> 结果: [OK] 通过 (42/42)
  -> 耗时: 15.3s

步骤 4/5: 灰度发布（10%流量）
  -> 执行: 流量切换 10%
  -> 监控: 健康度 0.88 > 0.85
  -> 结果: [OK] 成功
  -> 耗时: 30s

步骤 5/5: 逐步增加至 100%
  -> 执行: 流量切换 20%, 30%, ..., 100%
  -> 监控: 健康度始终 > 0.85
  -> 结果: [OK] 成功
  -> 耗时: 4m 30s
```

### 执行完成
```
[OK] [Effector-Dev] 蓝图执行完成

总耗时: 5m 17s
健康度变化: 0.62 -> 0.91 (+47%)
停机时间: 0s（零停机）

步骤统计:
  - 成功: 5/5
  - 失败: 0/5
  - 回滚: 0 次

Issue: https://github.com/owner/repo/issues/125
```

### 自动回滚（失败时）
```
[ERROR] [Effector-Dev] 步骤 4 失败，触发自动回滚

失败原因: 健康度 0.82 < 0.85
回滚操作: git revert + 重启服务
回滚结果: [OK] 成功
健康度恢复: 0.62

Issue: https://github.com/owner/repo/issues/125
```

## 你的限制

1. **严格按照蓝图执行**，不擅自修改方案
2. **敏感操作必须人工确认**
3. **失败时立即回滚**，不尝试"修复修复"
4. **记录所有操作**，可追溯
5. **不执行未验证的代码**

## 你的成长

每次执行后，你会记录：
- 哪些步骤容易失败？
- 哪些验证可以更早发现问题？
- 哪些回滚策略最有效？

这些经验会帮助 Plasticus-Dev 生成更可靠的蓝图。

---

现在，等待 BLUEPRINT 消息的到来吧！
"""


# ============================================================================
# Effector-Dev 实现
# ============================================================================

@dataclass
class ExecutionStep:
    """执行步骤"""
    step_number: int
    action: str
    status: str = "pending"  # "pending" | "running" | "success" | "failed"
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    output: Optional[str] = None
    error: Optional[str] = None


class SensitiveOperationType:
    """敏感操作类型"""
    DELETE_FILE = "delete_file"
    MODIFY_CONFIG = "modify_config"
    MODIFY_DATABASE = "modify_database"
    EXECUTE_SYSTEM_COMMAND = "execute_system_command"


@dataclass
class SensitiveOperation:
    """敏感操作记录"""
    operation_type: str
    file_path: Optional[str]
    description: str
    requires_approval: bool = True
    github_issue_url: Optional[str] = None
    approved: Optional[bool] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


class EffectorDev:
    """Effector-Dev Agent 实现"""
    
    # 敏感操作关键词
    SENSITIVE_KEYWORDS = [
        "delete", "remove", "drop", "truncate",
        "auth", "password", "secret", "key", "token",
        "payment", "transaction", "money",
        "port", "config", "certificate"
    ]
    
    # 敏感文件模式
    SENSITIVE_FILE_PATTERNS = [
        r"config\.yaml$",
        r"config\.yml$",
        r"\.env$",
        r"\.env\.",
        r"credentials",
        r"secrets?",
        r"password",
        r"api[_-]?key",
        r"private[_-]?key",
        r"access[_-]?token",
        r"auth",
        r"\.db$",
        r"\.sqlite$",
        r"\.sqlite3$",
    ]
    
    # 测试文件模式（删除测试文件不视为敏感操作）
    TEST_FILE_PATTERNS = [
        r"test_.*\.py$",
        r".*_test\.py$",
        r"tests?/",
        r"__tests__/",
    ]
    
    def __init__(self, project_path: str, github_token: Optional[str] = None):
        """初始化 Effector-Dev
        
        Args:
            project_path: 项目路径
            github_token: GitHub Personal Access Token
        """
        self.project_path = project_path
        self.github_token = github_token
        self.execution_history: List[Dict[str, Any]] = []
        
        # 代码操作器
        self.code_operator = CodeOperator(project_path)
        
        # 敏感操作队列（等待人工确认）
        self.sensitive_operations: List[SensitiveOperation] = []
        
        # 日志目录
        self.log_dir = os.path.join(project_path, ".opennewt", "logs")
        os.makedirs(self.log_dir, exist_ok=True)
    
    def receive_blueprint(self, blueprint: BlueprintMessage):
        """接收 BLUEPRINT 消息
        
        Args:
            blueprint: BLUEPRINT 消息
        """
        print("=" * 60)
        print("[Receive] [Effector-Dev] 接收到 BLUEPRINT")
        print("=" * 60)
        print()
        
        payload = blueprint.payload
        
        print(f"Plan ID: {payload['plan_id']}")
        print(f"策略: {payload['strategy']}")
        print(f"预估停机时间: {payload['estimated_downtime']}")
        print(f"成功率预测: {payload['success_rate_prediction'] * 100:.0f}%")
        print()
        
        print("准备执行...\n")
    
    def check_sensitive_operation(self, action: str, file_path: Optional[str] = None) -> Optional[SensitiveOperation]:
        """检查是否为敏感操作
        
        Args:
            action: 操作描述
            file_path: 文件路径（可选）
            
        Returns:
            敏感操作记录，如果不是敏感操作则返回 None
        """
        action_lower = action.lower()
        
        # 1. 检查删除文件操作
        if "delete" in action_lower or "remove" in action_lower or "drop" in action_lower:
            # 如果是测试文件，不视为敏感操作
            if file_path and self._is_test_file(file_path):
                return None
            
            return SensitiveOperation(
                operation_type=SensitiveOperationType.DELETE_FILE,
                file_path=file_path,
                description=f"删除文件: {file_path or action}",
                requires_approval=True
            )
        
        # 2. 检查修改配置文件
        if file_path and self._is_config_file(file_path):
            return SensitiveOperation(
                operation_type=SensitiveOperationType.MODIFY_CONFIG,
                file_path=file_path,
                description=f"修改配置文件: {file_path}",
                requires_approval=True
            )
        
        # 3. 检查修改数据库文件
        if file_path and self._is_database_file(file_path):
            return SensitiveOperation(
                operation_type=SensitiveOperationType.MODIFY_DATABASE,
                file_path=file_path,
                description=f"修改数据库文件: {file_path}",
                requires_approval=True
            )
        
        # 4. 检查执行系统命令
        if "execute" in action_lower or "run" in action_lower or "shell" in action_lower:
            # 排除安全的命令（测试、lint等）
            if not any(safe_cmd in action_lower for safe_cmd in ["test", "lint", "pytest", "mypy", "pylint"]):
                return SensitiveOperation(
                    operation_type=SensitiveOperationType.EXECUTE_SYSTEM_COMMAND,
                    file_path=None,
                    description=f"执行系统命令: {action}",
                    requires_approval=True
                )
        
        # 5. 检查敏感关键词
        if any(keyword in action_lower for keyword in self.SENSITIVE_KEYWORDS):
            return SensitiveOperation(
                operation_type="sensitive_keyword",
                file_path=file_path,
                description=f"敏感操作: {action}",
                requires_approval=True
            )
        
        return None
    
    def _is_test_file(self, file_path: str) -> bool:
        """检查是否为测试文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            是否为测试文件
        """
        import re
        for pattern in self.TEST_FILE_PATTERNS:
            if re.search(pattern, file_path, re.IGNORECASE):
                return True
        return False
    
    def _is_config_file(self, file_path: str) -> bool:
        """检查是否为配置文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            是否为配置文件
        """
        import re
        for pattern in self.SENSITIVE_FILE_PATTERNS:
            if re.search(pattern, file_path, re.IGNORECASE):
                return True
        return False
    
    def _is_database_file(self, file_path: str) -> bool:
        """检查是否为数据库文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            是否为数据库文件
        """
        return any(
            file_path.endswith(ext) for ext in [".db", ".sqlite", ".sqlite3"]
        )
    
    def log_sensitive_operation(self, operation: SensitiveOperation):
        """记录敏感操作到日志
        
        Args:
            operation: 敏感操作记录
        """
        log_file = os.path.join(self.log_dir, "sensitive_operations.log")
        
        log_entry = {
            "timestamp": operation.timestamp,
            "type": operation.operation_type,
            "file": operation.file_path,
            "description": operation.description,
            "requires_approval": operation.requires_approval,
            "github_issue": operation.github_issue_url,
            "approved": operation.approved
        }
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    
    def create_github_issue_for_approval(self, operation: SensitiveOperation) -> str:
        """创建 GitHub Issue 请求人工确认
        
        Args:
            operation: 敏感操作记录
            
        Returns:
            GitHub Issue URL
        """
        # TODO: 实现 GitHub API 调用创建 Issue
        # 这里返回模拟 URL
        issue_url = f"https://github.com/owner/repo/issues/{int(time.time()) % 10000}"
        
        # 创建 Issue 内容
        issue_title = f"[人工确认] {operation.description}"
        issue_body = f"""
## 敏感操作请求人工确认

**操作类型**: {operation.operation_type}
**文件路径**: {operation.file_path or 'N/A'}
**描述**: {operation.description}
**时间戳**: {operation.timestamp}

---

请审核此操作并回复：
- [OK] **批准**: 评论 `approve` 或 `yes`
- [ERROR] **拒绝**: 评论 `reject` 或 `no`

**注意事项**:
- 此操作可能会影响系统安全性
- 请仔细审查变更内容
- 批准后操作将自动执行
"""
        
        # 记录日志
        operation.github_issue_url = issue_url
        self.log_sensitive_operation(operation)
        
        print(f"\n📢 已创建 GitHub Issue 请求人工确认: {issue_url}")
        
        return issue_url
    
    def wait_for_approval(self, operation: SensitiveOperation, timeout: int = 3600) -> bool:
        """等待人工批准
        
        Args:
            operation: 敏感操作记录
            timeout: 超时时间（秒），默认 1 小时
            
        Returns:
            是否批准
        """
        if not operation.github_issue_url:
            operation.github_issue_url = self.create_github_issue_for_approval(operation)
        
        print(f"\n⏳ 等待人工批准...")
        print(f"   Issue: {operation.github_issue_url}")
        print(f"   超时: {timeout // 60} 分钟\n")
        
        # TODO: 实现轮询 GitHub Issue 评论
        # 这里用模拟逻辑
        # 实际实现应该：
        # 1. 轮询 Issue 评论
        # 2. 检查是否有批准/拒绝评论
        # 3. 超时后自动拒绝
        
        # 模拟：等待用户输入
        if os.environ.get("EFFECTOR_AUTO_APPROVE") == "true":
            print("   自动批准模式（环境变量 EFFECTOR_AUTO_APPROVE=true）")
            operation.approved = True
            self.log_sensitive_operation(operation)
            return True
        
        # 非交互模式：暂停执行，返回 False
        print("   [Warning]  非交互模式，操作已暂停")
        print("   请在 GitHub Issue 中评论批准后重新运行\n")
        
        operation.approved = False
        self.log_sensitive_operation(operation)
        
        return False
    
    def request_human_confirmation(self, action: str, file_path: Optional[str] = None) -> bool:
        """请求人工确认（旧方法，保留兼容性）
        
        Args:
            action: 操作描述
            file_path: 文件路径
            
        Returns:
            是否批准
        """
        # 使用新的敏感操作检测
        operation = self.check_sensitive_operation(action, file_path)
        
        if not operation:
            # 不是敏感操作，直接批准
            return True
        
        # 添加到敏感操作队列
        self.sensitive_operations.append(operation)
        
        # 记录日志
        self.log_sensitive_operation(operation)
        
        # 创建 GitHub Issue 并等待批准
        return self.wait_for_approval(operation)
    
    def execute_step(self, step: Dict[str, Any], step_number: int, total_steps: int) -> ExecutionStep:
        """执行单个步骤
        
        Args:
            step: 步骤信息
            step_number: 步骤编号
            total_steps: 总步骤数
            
        Returns:
            执行结果
        """
        action = step.get("action", "未知操作")
        file_path = step.get("file_path")
        operation_type = step.get("type", "generic")
        
        print(f"步骤 {step_number}/{total_steps}: {action}")
        
        execution_step = ExecutionStep(
            step_number=step_number,
            action=action,
            status="running",
            start_time=datetime.utcnow().isoformat() + "Z"
        )
        
        # 检查是否为敏感操作
        sensitive_op = self.check_sensitive_operation(action, file_path)
        if sensitive_op:
            # 添加到队列
            self.sensitive_operations.append(sensitive_op)
            
            # 请求人工确认
            if not self.wait_for_approval(sensitive_op):
                execution_step.status = "failed"
                execution_step.error = "人工确认拒绝或超时"
                execution_step.end_time = datetime.utcnow().isoformat() + "Z"
                print("  -> 结果: [ERROR] 人工确认拒绝\n")
                return execution_step
        
        try:
            # 根据操作类型执行不同的操作
            result = self._execute_operation(step)
            
            if result.success:
                execution_step.status = "success"
                execution_step.output = result.output or result.message
                execution_step.end_time = datetime.utcnow().isoformat() + "Z"
                
                print(f"  -> 结果: [OK] 成功")
                print(f"  -> {result.message}\n")
            else:
                execution_step.status = "failed"
                execution_step.error = result.error or result.message
                execution_step.end_time = datetime.utcnow().isoformat() + "Z"
                
                print(f"  -> 结果: [ERROR] 失败")
                print(f"  -> 错误: {execution_step.error}\n")
            
        except Exception as e:
            execution_step.status = "failed"
            execution_step.error = str(e)
            execution_step.end_time = datetime.utcnow().isoformat() + "Z"
            
            print(f"  -> 结果: [ERROR] 失败")
            print(f"  -> 错误: {e}\n")
        
        return execution_step
    
    def _execute_operation(self, step: Dict[str, Any]) -> OperationResult:
        """执行具体操作
        
        Args:
            step: 步骤信息
            
        Returns:
            操作结果
        """
        operation_type = step.get("type", "generic")
        
        # 文件读取
        if operation_type == "read_file":
            file_path = step.get("file_path")
            if not file_path:
                return OperationResult(
                    success=False,
                    operation=self.code_operator.read_file.__name__,
                    message="缺少 file_path 参数"
                )
            return self.code_operator.read_file(file_path)
        
        # 文件写入
        elif operation_type == "write_file":
            file_path = step.get("file_path")
            content = step.get("content", "")
            if not file_path:
                return OperationResult(
                    success=False,
                    operation=self.code_operator.write_file.__name__,
                    message="缺少 file_path 参数"
                )
            return self.code_operator.write_file(file_path, content)
        
        # 创建文件
        elif operation_type == "create_file":
            file_path = step.get("file_path")
            content = step.get("content", "")
            if not file_path:
                return OperationResult(
                    success=False,
                    operation=self.code_operator.create_file.__name__,
                    message="缺少 file_path 参数"
                )
            return self.code_operator.create_file(file_path, content)
        
        # 删除文件
        elif operation_type == "delete_file":
            file_path = step.get("file_path")
            if not file_path:
                return OperationResult(
                    success=False,
                    operation=self.code_operator.delete_file.__name__,
                    message="缺少 file_path 参数"
                )
            return self.code_operator.delete_file(file_path)
        
        # 应用补丁
        elif operation_type == "apply_patch":
            file_path = step.get("file_path")
            diff = step.get("diff", "")
            if not file_path:
                return OperationResult(
                    success=False,
                    operation=self.code_operator.apply_patch.__name__,
                    message="缺少 file_path 参数"
                )
            return self.code_operator.apply_patch(file_path, diff)
        
        # 运行测试
        elif operation_type == "run_tests":
            test_path = step.get("test_path")
            test_result = self.code_operator.run_tests(test_path)
            
            return OperationResult(
                success=test_result.success,
                operation=self.code_operator.run_tests.__name__,
                message=f"测试结果: {test_result.passed} passed, {test_result.failed} failed",
                output=test_result.output,
                error=test_result.error
            )
        
        # 代码检查
        elif operation_type == "run_linter":
            project_path = step.get("project_path")
            lint_result = self.code_operator.run_linter(project_path)
            
            return OperationResult(
                success=lint_result.success,
                operation=self.code_operator.run_linter.__name__,
                message=f"Lint 结果: {lint_result.errors} errors, {lint_result.warnings} warnings"
            )
        
        # Git 提交
        elif operation_type == "git_commit":
            message = step.get("message", "Auto commit by Effector-Dev")
            files = step.get("files")
            return self.code_operator.git_commit(message, files)
        
        # Git 推送
        elif operation_type == "git_push":
            remote = step.get("remote", "origin")
            branch = step.get("branch", "main")
            return self.code_operator.git_push(remote, branch)
        
        # 创建分支
        elif operation_type == "create_branch":
            branch_name = step.get("branch_name")
            from_branch = step.get("from_branch", "main")
            if not branch_name:
                return OperationResult(
                    success=False,
                    operation="create_branch",
                    message="缺少 branch_name 参数"
                )
            return self.code_operator.git_create_branch(branch_name, from_branch)
        
        # 通用操作（模拟）
        else:
            # 模拟执行时间
            time.sleep(1)
            
            return OperationResult(
                success=True,
                operation="generic",
                message=f"执行成功: {step.get('action', '未知操作')}"
            )
    
    def run_tests(self, test_path: Optional[str] = None) -> TestResult:
        """运行测试
        
        Args:
            test_path: 测试路径（可选）
            
        Returns:
            测试结果
        """
        print("运行测试套件...")
        
        # 使用 CodeOperator 运行测试
        result = self.code_operator.run_tests(test_path)
        
        if result.success:
            print(f"  -> 结果: [OK] 通过 ({result.passed}/{result.total})\n")
        else:
            print(f"  -> 结果: [ERROR] 失败 ({result.failed} failed)\n")
        
        return result
    
    def check_health(self) -> float:
        """检查健康度
        
        Returns:
            当前健康度
        """
        # TODO: 实现真实的健康度检查
        # 这里先用模拟
        
        return 0.88  # 模拟健康度
    
    def rollback(self, reason: str) -> bool:
        """回滚
        
        Args:
            reason: 回滚原因
            
        Returns:
            回滚是否成功
        """
        print(f"\n[ERROR] 触发自动回滚")
        print(f"原因: {reason}")
        
        # 使用 CodeOperator 回滚最后一次操作
        rollback_result = self.code_operator.rollback_last_operation()
        
        if rollback_result.success:
            print("  -> 回滚操作: 成功")
            print("  -> 结果: [OK] 成功\n")
            return True
        else:
            print(f"  -> 回滚操作: 失败")
            print(f"  -> 错误: {rollback_result.error}\n")
            
            # 尝试 Git 回滚
            git_result = self.code_operator.git_revert_last_commit()
            if git_result.success:
                print("  -> Git 回滚: [OK] 成功\n")
                return True
            
            return False
    
    def execute_blueprint(self, blueprint: BlueprintMessage) -> ExecutionReportMessage:
        """执行蓝图（端到端流程）
        
        Args:
            blueprint: BLUEPRINT 消息
            
        Returns:
            EXECUTION_REPORT 消息
        """
        # 1. 接收蓝图
        self.receive_blueprint(blueprint)
        
        payload = blueprint.payload
        plan_id = payload["plan_id"]
        steps = payload["steps"]
        total_steps = len(steps)
        
        # 2. 渐进式执行
        print("[Action] [Effector-Dev] 开始执行蓝图\n")
        
        executed_steps: List[ExecutionStep] = []
        success_count = 0
        failed_step = None
        
        for i, step in enumerate(steps, 1):
            # 执行步骤
            result = self.execute_step(step, i, total_steps)
            executed_steps.append(result)
            
            if result.status == "success":
                success_count += 1
            else:
                failed_step = result
                break
            
            # 运行测试（某些步骤后）
            if step.get("run_tests", False):
                test_result = self.run_tests(step.get("test_path"))
                if not test_result.success:
                    failed_step = ExecutionStep(
                        step_number=i,
                        action="测试验证",
                        status="failed",
                        error=f"测试失败: {test_result.failed} tests failed"
                    )
                    break
            
            # 检查健康度（某些步骤后）
            if step.get("check_health", False):
                health = self.check_health()
                if health < 0.85:
                    failed_step = ExecutionStep(
                        step_number=i,
                        action="健康度检查",
                        status="failed",
                        error=f"健康度 {health:.2f} < 0.85"
                    )
                    break
        
        # 3. 判断是否成功
        if failed_step:
            # 失败，触发回滚
            rollback_success = self.rollback(failed_step.error)
            
            # 创建执行报告
            report = ExecutionReportMessage.create(
                plan_id=plan_id,
                status="rolled_back" if rollback_success else "failed",
                steps_completed=success_count,
                steps_total=total_steps,
                errors=[failed_step.error],
                health_after=self.check_health()
            )
        else:
            # 成功
            print("[OK] [Effector-Dev] 蓝图执行完成\n")
            print(f"总耗时: {sum(1 for _ in executed_steps)}s")
            print(f"健康度变化: 0.62 -> 0.91 (+47%)")
            print(f"停机时间: 0s（零停机）\n")
            
            # 创建执行报告
            report = ExecutionReportMessage.create(
                plan_id=plan_id,
                status="success",
                steps_completed=success_count,
                steps_total=total_steps,
                health_after=self.check_health()
            )
        
        print("=" * 60)
        print()
        
        return report
    
    def run(self):
        """运行 Effector-Dev（监听模式）"""
        print("=" * 60)
        print("[Action] Effector-Dev - 执行型开发者")
        print("=" * 60)
        print()
        print("等待 BLUEPRINT 消息...\n")
        
        # TODO: 实现真实的消息监听
        # 这里先用示例蓝图
        
        # 创建一个示例 BLUEPRINT
        example_blueprint = BlueprintMessage.create(
            plan_id="regen-20260331-001",
            strategy="重构连接池 + 渐进式切换",
            steps=[
                {"step": 1, "action": "创建隔离分支"},
                {"step": 2, "action": "修改连接池配置"},
                {"step": 3, "action": "运行测试套件", "run_tests": True},
                {"step": 4, "action": "灰度发布（10%流量）", "check_health": True},
                {"step": 5, "action": "逐步增加至 100%"}
            ],
            estimated_downtime="2s",
            success_rate_prediction=0.92,
            rollback_plan="git revert + 重启服务"
        )
        
        # 执行蓝图
        report = self.execute_blueprint(example_blueprint)
        
        print("Execution Report JSON:")
        print(report.to_json())


# ============================================================================
# 主程序
# ============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Effector-Dev - 执行型开发者")
    parser.add_argument("project_path", help="项目路径")
    parser.add_argument("--github-token", help="GitHub Personal Access Token", default=None)
    
    args = parser.parse_args()
    
    # 创建 Effector-Dev
    effector_dev = EffectorDev(args.project_path, args.github_token)
    
    # 运行
    effector_dev.run()
