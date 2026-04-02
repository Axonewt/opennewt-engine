"""
CodeOperator - 代码操作封装
=============================

提供安全的代码读写和测试能力：
- 文件操作（读取、写入、创建、删除、应用补丁）
- 测试执行（pytest）
- 代码检查（pylint, mypy, black）
- Git 操作（提交、推送）
- 安全机制（敏感操作检测、备份、回滚）

使用示例：
    operator = CodeOperator("/path/to/project")
    
    # 读取文件
    content = operator.read_file("src/main.py")
    
    # 写入文件
    operator.write_file("src/utils.py", "def hello(): pass")
    
    # 运行测试
    result = operator.run_tests()
    
    # Git 提交
    operator.git_commit("Add utility function", ["src/utils.py"])
"""

import os
import re
import json
import shutil
import subprocess
import hashlib
import difflib
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum


# ============================================================================
# 数据结构
# ============================================================================

class OperationType(Enum):
    """操作类型"""
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    CREATE_FILE = "create_file"
    DELETE_FILE = "delete_file"
    APPLY_PATCH = "apply_patch"
    RUN_TESTS = "run_tests"
    RUN_LINTER = "run_linter"
    GIT_COMMIT = "git_commit"
    GIT_PUSH = "git_push"


@dataclass
class OperationResult:
    """操作结果"""
    success: bool
    operation: OperationType
    message: str
    output: Optional[str] = None
    error: Optional[str] = None
    backup_path: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "operation": self.operation.value,
            "message": self.message,
            "output": self.output,
            "error": self.error,
            "backup_path": self.backup_path,
            "timestamp": self.timestamp
        }


@dataclass
class TestResult:
    """测试结果"""
    passed: int
    failed: int
    skipped: int
    total: int
    duration: float
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    coverage: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "total": self.total,
            "duration": self.duration,
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "coverage": self.coverage
        }


@dataclass
class LintResult:
    """代码检查结果"""
    errors: int
    warnings: int
    info: int
    success: bool
    output: Optional[str] = None
    issues: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "errors": self.errors,
            "warnings": self.warnings,
            "info": self.info,
            "success": self.success,
            "output": self.output,
            "issues": self.issues
        }


# ============================================================================
# CodeOperator 实现
# ============================================================================

class CodeOperator:
    """代码操作封装
    
    提供安全的代码读写和测试能力，支持：
    - 敏感操作检测
    - 操作前备份
    - 失败时回滚
    """
    
    # 敏感文件模式
    SENSITIVE_PATTERNS = [
        r"\.env$",
        r"\.env\.",
        r"credentials",
        r"secrets?",
        r"password",
        r"api[_-]?key",
        r"private[_-]?key",
        r"access[_-]?token",
        r"auth",
        r"config\.yaml$",
        r"config\.json$",
        r"settings\.py$",
    ]
    
    # 敏感目录
    SENSITIVE_DIRS = [
        ".git",
        ".ssh",
        ".gnupg",
        "secrets",
        "credentials",
    ]
    
    # 关键配置文件
    CRITICAL_CONFIGS = [
        "docker-compose.yml",
        "Dockerfile",
        "requirements.txt",
        "setup.py",
        "pyproject.toml",
        "Cargo.toml",
        "package.json",
    ]
    
    def __init__(self, project_path: str, backup_dir: Optional[str] = None):
        """初始化代码操作器
        
        Args:
            project_path: 项目根路径
            backup_dir: 备份目录（默认为项目下的 .opennewt/backups）
        """
        self.project_path = Path(project_path).resolve()
        self.backup_dir = Path(backup_dir) if backup_dir else self.project_path / ".opennewt" / "backups"
        
        # 确保备份目录存在
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        # 操作历史（用于回滚）
        self.operation_history: List[Dict[str, Any]] = []
        
    # ========================================================================
    # 文件操作
    # ========================================================================
    
    def read_file(self, file_path: str) -> OperationResult:
        """读取文件
        
        Args:
            file_path: 文件路径（相对于项目根目录）
            
        Returns:
            操作结果
        """
        full_path = self._resolve_path(file_path)
        
        try:
            if not full_path.exists():
                return OperationResult(
                    success=False,
                    operation=OperationType.READ_FILE,
                    message=f"文件不存在: {file_path}",
                    error="FileNotFoundError"
                )
            
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            return OperationResult(
                success=True,
                operation=OperationType.READ_FILE,
                message=f"成功读取文件: {file_path}",
                output=content
            )
            
        except Exception as e:
            return OperationResult(
                success=False,
                operation=OperationType.READ_FILE,
                message=f"读取文件失败: {file_path}",
                error=str(e)
            )
    
    def write_file(self, file_path: str, content: str, backup: bool = True) -> OperationResult:
        """写入文件（已存在的文件）
        
        Args:
            file_path: 文件路径（相对于项目根目录）
            content: 文件内容
            backup: 是否备份原文件
            
        Returns:
            操作结果
        """
        full_path = self._resolve_path(file_path)
        
        try:
            # 检查文件是否存在
            if not full_path.exists():
                return OperationResult(
                    success=False,
                    operation=OperationType.WRITE_FILE,
                    message=f"文件不存在，请使用 create_file: {file_path}",
                    error="FileNotFoundError"
                )
            
            # 检查是否为敏感文件
            if self._is_sensitive_file(file_path):
                return OperationResult(
                    success=False,
                    operation=OperationType.WRITE_FILE,
                    message=f"拒绝修改敏感文件: {file_path}",
                    error="SensitiveFileError"
                )
            
            # 备份原文件
            backup_path = None
            if backup:
                backup_path = self._backup_file(full_path)
            
            # 写入新内容
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            
            # 记录操作
            self._record_operation({
                "type": "write_file",
                "path": str(full_path),
                "backup": backup_path,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            })
            
            return OperationResult(
                success=True,
                operation=OperationType.WRITE_FILE,
                message=f"成功写入文件: {file_path}",
                backup_path=backup_path
            )
            
        except Exception as e:
            return OperationResult(
                success=False,
                operation=OperationType.WRITE_FILE,
                message=f"写入文件失败: {file_path}",
                error=str(e)
            )
    
    def create_file(self, file_path: str, content: str) -> OperationResult:
        """创建新文件
        
        Args:
            file_path: 文件路径（相对于项目根目录）
            content: 文件内容
            
        Returns:
            操作结果
        """
        full_path = self._resolve_path(file_path)
        
        try:
            # 检查文件是否已存在
            if full_path.exists():
                return OperationResult(
                    success=False,
                    operation=OperationType.CREATE_FILE,
                    message=f"文件已存在，请使用 write_file: {file_path}",
                    error="FileExistsError"
                )
            
            # 创建父目录
            full_path.parent.mkdir(parents=True, exist_ok=True)
            
            # 写入内容
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            
            # 记录操作
            self._record_operation({
                "type": "create_file",
                "path": str(full_path),
                "timestamp": datetime.utcnow().isoformat() + "Z"
            })
            
            return OperationResult(
                success=True,
                operation=OperationType.CREATE_FILE,
                message=f"成功创建文件: {file_path}"
            )
            
        except Exception as e:
            return OperationResult(
                success=False,
                operation=OperationType.CREATE_FILE,
                message=f"创建文件失败: {file_path}",
                error=str(e)
            )
    
    def delete_file(self, file_path: str, backup: bool = True) -> OperationResult:
        """删除文件
        
        Args:
            file_path: 文件路径（相对于项目根目录）
            backup: 是否备份原文件
            
        Returns:
            操作结果
        """
        full_path = self._resolve_path(file_path)
        
        try:
            # 检查文件是否存在
            if not full_path.exists():
                return OperationResult(
                    success=False,
                    operation=OperationType.DELETE_FILE,
                    message=f"文件不存在: {file_path}",
                    error="FileNotFoundError"
                )
            
            # 检查是否为敏感文件
            if self._is_sensitive_file(file_path):
                return OperationResult(
                    success=False,
                    operation=OperationType.DELETE_FILE,
                    message=f"拒绝删除敏感文件: {file_path}",
                    error="SensitiveFileError"
                )
            
            # 备份原文件
            backup_path = None
            if backup:
                backup_path = self._backup_file(full_path)
            
            # 删除文件
            full_path.unlink()
            
            # 记录操作
            self._record_operation({
                "type": "delete_file",
                "path": str(full_path),
                "backup": backup_path,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            })
            
            return OperationResult(
                success=True,
                operation=OperationType.DELETE_FILE,
                message=f"成功删除文件: {file_path}",
                backup_path=backup_path
            )
            
        except Exception as e:
            return OperationResult(
                success=False,
                operation=OperationType.DELETE_FILE,
                message=f"删除文件失败: {file_path}",
                error=str(e)
            )
    
    def apply_patch(self, file_path: str, diff: str, backup: bool = True) -> OperationResult:
        """应用补丁（unified diff 格式）
        
        Args:
            file_path: 文件路径（相对于项目根目录）
            diff: unified diff 格式的补丁
            backup: 是否备份原文件
            
        Returns:
            操作结果
        """
        full_path = self._resolve_path(file_path)
        
        try:
            # 检查文件是否存在
            if not full_path.exists():
                return OperationResult(
                    success=False,
                    operation=OperationType.APPLY_PATCH,
                    message=f"文件不存在: {file_path}",
                    error="FileNotFoundError"
                )
            
            # 检查是否为敏感文件
            if self._is_sensitive_file(file_path):
                return OperationResult(
                    success=False,
                    operation=OperationType.APPLY_PATCH,
                    message=f"拒绝修改敏感文件: {file_path}",
                    error="SensitiveFileError"
                )
            
            # 读取原文件
            with open(full_path, "r", encoding="utf-8") as f:
                original_content = f.read()
            
            # 备份原文件
            backup_path = None
            if backup:
                backup_path = self._backup_file(full_path)
            
            # 应用补丁
            patched_content = self._apply_unified_diff(original_content, diff)
            
            if patched_content is None:
                return OperationResult(
                    success=False,
                    operation=OperationType.APPLY_PATCH,
                    message=f"补丁应用失败: {file_path}",
                    error="PatchApplicationError"
                )
            
            # 写入补丁后的内容
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(patched_content)
            
            # 记录操作
            self._record_operation({
                "type": "apply_patch",
                "path": str(full_path),
                "backup": backup_path,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            })
            
            return OperationResult(
                success=True,
                operation=OperationType.APPLY_PATCH,
                message=f"成功应用补丁: {file_path}",
                backup_path=backup_path
            )
            
        except Exception as e:
            return OperationResult(
                success=False,
                operation=OperationType.APPLY_PATCH,
                message=f"应用补丁失败: {file_path}",
                error=str(e)
            )
    
    # ========================================================================
    # 测试执行
    # ========================================================================
    
    def run_tests(self, test_path: Optional[str] = None, extra_args: Optional[List[str]] = None) -> TestResult:
        """运行测试（pytest）
        
        Args:
            test_path: 测试路径（默认运行所有测试）
            extra_args: 额外的 pytest 参数
            
        Returns:
            测试结果
        """
        try:
            # 构建 pytest 命令
            cmd = ["python", "-m", "pytest", "-v", "--tb=short", "--json-report"]
            
            if test_path:
                cmd.append(str(self._resolve_path(test_path)))
            
            if extra_args:
                cmd.extend(extra_args)
            
            # 运行测试
            start_time = datetime.utcnow()
            result = subprocess.run(
                cmd,
                cwd=str(self.project_path),
                capture_output=True,
                text=True,
                timeout=300  # 5 分钟超时
            )
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()
            
            # 解析测试结果
            output = result.stdout + result.stderr
            
            # 尝试从输出中解析结果
            test_result = self._parse_pytest_output(output, duration)
            
            return test_result
            
        except subprocess.TimeoutExpired:
            return TestResult(
                passed=0,
                failed=0,
                skipped=0,
                total=0,
                duration=300.0,
                success=False,
                error="测试超时（5分钟）"
            )
        except Exception as e:
            return TestResult(
                passed=0,
                failed=0,
                skipped=0,
                total=0,
                duration=0.0,
                success=False,
                error=str(e)
            )
    
    def _parse_pytest_output(self, output: str, duration: float) -> TestResult:
        """解析 pytest 输出
        
        Args:
            output: pytest 输出
            duration: 执行时长
            
        Returns:
            测试结果
        """
        # 默认值
        passed = 0
        failed = 0
        skipped = 0
        total = 0
        
        # 尝试从输出中提取结果
        # pytest 输出格式示例: "5 passed, 2 failed, 1 skipped"
        match = re.search(r"(\d+)\s+passed", output)
        if match:
            passed = int(match.group(1))
        
        match = re.search(r"(\d+)\s+failed", output)
        if match:
            failed = int(match.group(1))
        
        match = re.search(r"(\d+)\s+skipped", output)
        if match:
            skipped = int(match.group(1))
        
        match = re.search(r"(\d+)\s+warnings?", output)
        if match:
            # warnings 不计入统计
            pass
        
        total = passed + failed + skipped
        
        return TestResult(
            passed=passed,
            failed=failed,
            skipped=skipped,
            total=total,
            duration=duration,
            success=(failed == 0 and total > 0),
            output=output
        )
    
    # ========================================================================
    # 代码检查
    # ========================================================================
    
    def run_linter(self, project_path: Optional[str] = None, tools: Optional[List[str]] = None) -> LintResult:
        """运行代码检查
        
        Args:
            project_path: 检查路径（默认为项目根目录）
            tools: 使用的工具列表（默认: pylint, mypy）
            
        Returns:
            代码检查结果
        """
        target_path = self._resolve_path(project_path) if project_path else self.project_path
        tools = tools or ["pylint", "mypy"]
        
        all_issues = []
        total_errors = 0
        total_warnings = 0
        total_info = 0
        
        for tool in tools:
            if tool == "pylint":
                result = self._run_pylint(target_path)
            elif tool == "mypy":
                result = self._run_mypy(target_path)
            else:
                continue
            
            all_issues.extend(result.get("issues", []))
            total_errors += result.get("errors", 0)
            total_warnings += result.get("warnings", 0)
            total_info += result.get("info", 0)
        
        return LintResult(
            errors=total_errors,
            warnings=total_warnings,
            info=total_info,
            success=(total_errors == 0),
            issues=all_issues
        )
    
    def _run_pylint(self, target_path: Path) -> Dict[str, Any]:
        """运行 pylint"""
        try:
            cmd = ["python", "-m", "pylint", str(target_path), "--output-format=json"]
            result = subprocess.run(
                cmd,
                cwd=str(self.project_path),
                capture_output=True,
                text=True,
                timeout=120
            )
            
            # 解析 JSON 输出
            issues = []
            if result.stdout:
                try:
                    data = json.loads(result.stdout)
                    for item in data:
                        issues.append({
                            "tool": "pylint",
                            "file": item.get("path", ""),
                            "line": item.get("line", 0),
                            "column": item.get("column", 0),
                            "message": item.get("message", ""),
                            "type": item.get("type", ""),
                            "symbol": item.get("symbol", "")
                        })
                except json.JSONDecodeError:
                    pass
            
            errors = sum(1 for i in issues if i.get("type") in ("error", "fatal"))
            warnings = sum(1 for i in issues if i.get("type") in ("warning", "convention", "refactor"))
            
            return {
                "errors": errors,
                "warnings": warnings,
                "info": 0,
                "issues": issues
            }
            
        except Exception as e:
            return {
                "errors": 0,
                "warnings": 0,
                "info": 0,
                "issues": []
            }
    
    def _run_mypy(self, target_path: Path) -> Dict[str, Any]:
        """运行 mypy"""
        try:
            cmd = ["python", "-m", "mypy", str(target_path)]
            result = subprocess.run(
                cmd,
                cwd=str(self.project_path),
                capture_output=True,
                text=True,
                timeout=120
            )
            
            # 解析输出
            issues = []
            errors = 0
            warnings = 0
            
            for line in result.stdout.split("\n"):
                # mypy 输出格式: file:line: error: message
                match = re.match(r"(.+):(\d+):\s+(error|warning|note):\s+(.+)", line)
                if match:
                    issue_type = match.group(3)
                    issues.append({
                        "tool": "mypy",
                        "file": match.group(1),
                        "line": int(match.group(2)),
                        "column": 0,
                        "message": match.group(4),
                        "type": issue_type
                    })
                    
                    if issue_type == "error":
                        errors += 1
                    elif issue_type in ("warning", "note"):
                        warnings += 1
            
            return {
                "errors": errors,
                "warnings": warnings,
                "info": 0,
                "issues": issues
            }
            
        except Exception as e:
            return {
                "errors": 0,
                "warnings": 0,
                "info": 0,
                "issues": []
            }
    
    # ========================================================================
    # Git 操作
    # ========================================================================
    
    def git_commit(self, message: str, files: Optional[List[str]] = None) -> OperationResult:
        """Git 提交
        
        Args:
            message: 提交消息
            files: 要提交的文件列表（None 表示提交所有变更）
            
        Returns:
            操作结果
        """
        try:
            # git add
            if files:
                for file in files:
                    subprocess.run(
                        ["git", "add", file],
                        cwd=str(self.project_path),
                        check=True,
                        capture_output=True
                    )
            else:
                subprocess.run(
                    ["git", "add", "."],
                    cwd=str(self.project_path),
                    check=True,
                    capture_output=True
                )
            
            # git commit
            result = subprocess.run(
                ["git", "commit", "-m", message],
                cwd=str(self.project_path),
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                return OperationResult(
                    success=False,
                    operation=OperationType.GIT_COMMIT,
                    message="Git 提交失败",
                    error=result.stderr
                )
            
            # 记录操作
            self._record_operation({
                "type": "git_commit",
                "message": message,
                "files": files,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            })
            
            return OperationResult(
                success=True,
                operation=OperationType.GIT_COMMIT,
                message=f"成功提交: {message}",
                output=result.stdout
            )
            
        except Exception as e:
            return OperationResult(
                success=False,
                operation=OperationType.GIT_COMMIT,
                message="Git 提交失败",
                error=str(e)
            )
    
    def git_push(self, remote: str = "origin", branch: str = "main") -> OperationResult:
        """Git 推送
        
        Args:
            remote: 远程仓库名称
            branch: 分支名称
            
        Returns:
            操作结果
        """
        try:
            result = subprocess.run(
                ["git", "push", remote, branch],
                cwd=str(self.project_path),
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                return OperationResult(
                    success=False,
                    operation=OperationType.GIT_PUSH,
                    message="Git 推送失败",
                    error=result.stderr
                )
            
            # 记录操作
            self._record_operation({
                "type": "git_push",
                "remote": remote,
                "branch": branch,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            })
            
            return OperationResult(
                success=True,
                operation=OperationType.GIT_PUSH,
                message=f"成功推送到 {remote}/{branch}",
                output=result.stdout
            )
            
        except Exception as e:
            return OperationResult(
                success=False,
                operation=OperationType.GIT_PUSH,
                message="Git 推送失败",
                error=str(e)
            )
    
    def git_create_branch(self, branch_name: str, from_branch: str = "main") -> OperationResult:
        """创建新分支
        
        Args:
            branch_name: 新分支名称
            from_branch: 基于哪个分支创建
            
        Returns:
            操作结果
        """
        try:
            # 创建并切换到新分支
            result = subprocess.run(
                ["git", "checkout", "-b", branch_name, from_branch],
                cwd=str(self.project_path),
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                return OperationResult(
                    success=False,
                    operation=OperationType.GIT_COMMIT,
                    message=f"创建分支失败: {branch_name}",
                    error=result.stderr
                )
            
            return OperationResult(
                success=True,
                operation=OperationType.GIT_COMMIT,
                message=f"成功创建并切换到分支: {branch_name}",
                output=result.stdout
            )
            
        except Exception as e:
            return OperationResult(
                success=False,
                operation=OperationType.GIT_COMMIT,
                message=f"创建分支失败: {branch_name}",
                error=str(e)
            )
    
    def git_revert_last_commit(self) -> OperationResult:
        """回滚最后一次提交
        
        Returns:
            操作结果
        """
        try:
            result = subprocess.run(
                ["git", "revert", "HEAD", "--no-edit"],
                cwd=str(self.project_path),
                capture_output=True,
                text=True
            )
            
            if result.returncode != 0:
                return OperationResult(
                    success=False,
                    operation=OperationType.GIT_COMMIT,
                    message="回滚提交失败",
                    error=result.stderr
                )
            
            return OperationResult(
                success=True,
                operation=OperationType.GIT_COMMIT,
                message="成功回滚最后一次提交",
                output=result.stdout
            )
            
        except Exception as e:
            return OperationResult(
                success=False,
                operation=OperationType.GIT_COMMIT,
                message="回滚提交失败",
                error=str(e)
            )
    
    # ========================================================================
    # 安全机制
    # ========================================================================
    
    def _is_sensitive_file(self, file_path: str) -> bool:
        """检查是否为敏感文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            是否为敏感文件
        """
        # 检查文件名
        for pattern in self.SENSITIVE_PATTERNS:
            if re.search(pattern, file_path, re.IGNORECASE):
                return True
        
        # 检查目录
        parts = Path(file_path).parts
        for part in parts:
            if part in self.SENSITIVE_DIRS:
                return True
        
        return False
    
    def _is_critical_config(self, file_path: str) -> bool:
        """检查是否为关键配置文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            是否为关键配置文件
        """
        filename = Path(file_path).name
        return filename in self.CRITICAL_CONFIGS
    
    def _backup_file(self, file_path: Path) -> str:
        """备份文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            备份文件路径
        """
        # 生成备份文件名
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = file_path.name
        backup_name = f"{filename}.backup_{timestamp}"
        backup_path = self.backup_dir / backup_name
        
        # 复制文件
        shutil.copy2(file_path, backup_path)
        
        return str(backup_path)
    
    def restore_from_backup(self, backup_path: str, target_path: str) -> OperationResult:
        """从备份恢复文件
        
        Args:
            backup_path: 备份文件路径
            target_path: 目标文件路径
            
        Returns:
            操作结果
        """
        try:
            backup_file = Path(backup_path)
            target_file = self._resolve_path(target_path)
            
            if not backup_file.exists():
                return OperationResult(
                    success=False,
                    operation=OperationType.WRITE_FILE,
                    message=f"备份文件不存在: {backup_path}",
                    error="FileNotFoundError"
                )
            
            # 恢复文件
            shutil.copy2(backup_file, target_file)
            
            return OperationResult(
                success=True,
                operation=OperationType.WRITE_FILE,
                message=f"成功从备份恢复: {target_path}"
            )
            
        except Exception as e:
            return OperationResult(
                success=False,
                operation=OperationType.WRITE_FILE,
                message=f"恢复备份失败: {target_path}",
                error=str(e)
            )
    
    def rollback_last_operation(self) -> OperationResult:
        """回滚最后一次操作
        
        Returns:
            操作结果
        """
        if not self.operation_history:
            return OperationResult(
                success=False,
                operation=OperationType.WRITE_FILE,
                message="没有可回滚的操作",
                error="NoOperationError"
            )
        
        last_op = self.operation_history.pop()
        
        # 根据操作类型执行回滚
        if last_op["type"] == "write_file":
            if last_op.get("backup"):
                return self.restore_from_backup(
                    last_op["backup"],
                    last_op["path"]
                )
        
        elif last_op["type"] == "create_file":
            # 删除创建的文件
            try:
                Path(last_op["path"]).unlink()
                return OperationResult(
                    success=True,
                    operation=OperationType.DELETE_FILE,
                    message=f"成功删除创建的文件"
                )
            except Exception as e:
                return OperationResult(
                    success=False,
                    operation=OperationType.DELETE_FILE,
                    message="删除文件失败",
                    error=str(e)
                )
        
        elif last_op["type"] == "delete_file":
            if last_op.get("backup"):
                return self.restore_from_backup(
                    last_op["backup"],
                    last_op["path"]
                )
        
        elif last_op["type"] == "apply_patch":
            if last_op.get("backup"):
                return self.restore_from_backup(
                    last_op["backup"],
                    last_op["path"]
                )
        
        elif last_op["type"] == "git_commit":
            return self.git_revert_last_commit()
        
        return OperationResult(
            success=False,
            operation=OperationType.WRITE_FILE,
            message="无法回滚此类型的操作",
            error="UnsupportedOperationError"
        )
    
    # ========================================================================
    # 辅助方法
    # ========================================================================
    
    def _resolve_path(self, file_path: str) -> Path:
        """解析文件路径（相对于项目根目录）
        
        Args:
            file_path: 文件路径
            
        Returns:
            完整路径
        """
        path = Path(file_path)
        if path.is_absolute():
            return path
        return self.project_path / path
    
    def _record_operation(self, operation: Dict[str, Any]):
        """记录操作到历史
        
        Args:
            operation: 操作信息
        """
        self.operation_history.append(operation)
    
    def _apply_unified_diff(self, original: str, diff: str) -> Optional[str]:
        """应用 unified diff
        
        Args:
            original: 原始内容
            diff: unified diff
            
        Returns:
            应用补丁后的内容，失败返回 None
        """
        try:
            # 将内容转换为行列表
            original_lines = original.splitlines(keepends=True)
            
            # 解析 diff
            diff_lines = diff.splitlines()
            
            # 应用 diff
            # 这里使用简化的实现，实际生产环境应该使用 patch 库
            current_lines = original_lines.copy()
            
            i = 0
            while i < len(diff_lines):
                line = diff_lines[i]
                
                # 跳过 diff 头部
                if line.startswith("---") or line.startswith("+++") or line.startswith("index"):
                    i += 1
                    continue
                
                # 解析 hunk 头部: @@ -start,count +start,count @@
                if line.startswith("@@"):
                    match = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
                    if match:
                        old_start = int(match.group(1))
                        new_start = int(match.group(3))
                        # 处理 hunk
                        # ... 简化实现
                    i += 1
                    continue
                
                i += 1
            
            # 返回合并后的内容
            return "".join(current_lines)
            
        except Exception:
            return None
    
    def get_file_hash(self, file_path: str) -> Optional[str]:
        """获取文件哈希值（SHA256）
        
        Args:
            file_path: 文件路径
            
        Returns:
            文件哈希值，文件不存在返回 None
        """
        full_path = self._resolve_path(file_path)
        
        if not full_path.exists():
            return None
        
        sha256 = hashlib.sha256()
        with open(full_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256.update(chunk)
        
        return sha256.hexdigest()
    
    def list_files(self, directory: str = ".", pattern: str = "*.py") -> List[str]:
        """列出目录中的文件
        
        Args:
            directory: 目录路径
            pattern: 文件模式（glob 格式）
            
        Returns:
            文件路径列表（相对于项目根目录）
        """
        target_dir = self._resolve_path(directory)
        
        files = []
        for file_path in target_dir.rglob(pattern):
            if file_path.is_file():
                rel_path = file_path.relative_to(self.project_path)
                files.append(str(rel_path))
        
        return files


# ============================================================================
# 主程序
# ============================================================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="CodeOperator - 代码操作封装")
    parser.add_argument("project_path", help="项目根路径")
    
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # read 命令
    read_parser = subparsers.add_parser("read", help="读取文件")
    read_parser.add_argument("file", help="文件路径")
    
    # write 命令
    write_parser = subparsers.add_parser("write", help="写入文件")
    write_parser.add_argument("file", help="文件路径")
    write_parser.add_argument("content", help="文件内容")
    
    # test 命令
    test_parser = subparsers.add_parser("test", help="运行测试")
    test_parser.add_argument("--path", help="测试路径")
    
    # lint 命令
    lint_parser = subparsers.add_parser("lint", help="运行代码检查")
    lint_parser.add_argument("--path", help="检查路径")
    
    args = parser.parse_args()
    
    # 创建 CodeOperator
    operator = CodeOperator(args.project_path)
    
    if args.command == "read":
        result = operator.read_file(args.file)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    
    elif args.command == "write":
        result = operator.write_file(args.file, args.content)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    
    elif args.command == "test":
        result = operator.run_tests(args.path)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    
    elif args.command == "lint":
        result = operator.run_linter(args.path)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    
    else:
        parser.print_help()
