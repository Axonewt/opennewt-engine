"""
Chaos Agent - 故障注入器
========================

在目标项目中随机注入故障，用于测试 Axonewt 自愈引擎。

支持的故障类型：
1. DELETE_LINE — 删除函数/类中的随机一行代码
2. SWAP_VARIABLES — 交换两个变量的值
3. BAD_SYNTAX — 注入语法错误（缺少冒号、括号不匹配）
4. DELETE_IMPORT — 删除关键 import 语句
5. BREAK_STRING — 截断字符串常量
6. ZERO_DIVISION — 将除法操作的除数改为 0

用法：
    # 注入 3 个故障到目标项目
    python chaos_agent.py --target /path/to/project --count 3
    
    # 指定故障类型
    python chaos_agent.py --target /path/to/project --types BAD_SYNTAX,DELETE_LINE
    
    # 持续模式：每隔 60 秒注入一个故障
    python chaos_agent.py --target /path/to/project --daemon --interval 60
    
    # 查看注入记录
    python chaos_agent.py --target /path/to/project --log

安全机制：
- 每次注入前备份文件
- 记录所有注入的故障（便于回滚）
- 跳过 __pycache__、.git、venv 等目录
"""

import os
import sys
import json
import random
import hashlib
import argparse
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field, asdict


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class Fault:
    """单次故障注入记录"""
    fault_id: str            # 唯一 ID
    fault_type: str          # 故障类型
    file_path: str           # 目标文件（相对路径）
    line_number: int         # 修改的行号
    original_line: str       # 原始行内容
    modified_line: str       # 修改后的行内容
    timestamp: str           # 注入时间
    reverted: bool = False   # 是否已回滚
    
    def to_dict(self):
        return asdict(self)


@dataclass  
class ChaosLog:
    """故障注入日志"""
    target_path: str
    created_at: str
    faults: List[Fault] = field(default_factory=list)
    
    def to_dict(self):
        return {
            "target_path": self.target_path,
            "created_at": self.created_at,
            "total_faults": len(self.faults),
            "active_faults": len([f for f in self.faults if not f.reverted]),
            "faults": [f.to_dict() for f in self.faults]
        }


# ============================================================================
# 故障注入器
# ============================================================================

# 需要跳过的目录
SKIP_DIRS = {
    "__pycache__", ".git", "venv", ".venv", "env", ".env",
    "node_modules", ".idea", ".vscode", "dist", "build",
    ".mypy_cache", ".pytest_cache", ".tox", "data", "logs"
}

# 需要跳过的文件
SKIP_FILES = {"chaos_agent.py", "chaos_log.json"}

# 支持的文件扩展名
PYTHON_EXTENSIONS = {".py"}


class ChaosAgent:
    """故障注入 Agent"""
    
    def __init__(self, target_path: str, log_dir: Optional[str] = None):
        self.target_path = Path(target_path).resolve()
        if not self.target_path.exists():
            raise FileNotFoundError(f"Target path not found: {target_path}")
        
        self.log_dir = Path(log_dir) if log_dir else self.target_path / ".chaos"
        self.log_dir.mkdir(exist_ok=True)
        self.log_file = self.log_dir / "chaos_log.json"
        
        self.log = self._load_log()
        
        print(f"[Chaos] Target: {self.target_path}")
        print(f"[Chaos] Log: {self.log_file}")
        print(f"[Chaos] Existing faults: {len(self.log.faults)}")
    
    def _load_log(self) -> ChaosLog:
        """加载故障日志"""
        if self.log_file.exists():
            try:
                with open(self.log_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    faults = [Fault(**f) for f in data.get("faults", [])]
                    return ChaosLog(
                        target_path=data.get("target_path", str(self.target_path)),
                        created_at=data.get("created_at", datetime.now().isoformat()),
                        faults=faults
                    )
            except Exception as e:
                print(f"[Chaos] Warning: Failed to load log: {e}")
        return ChaosLog(
            target_path=str(self.target_path),
            created_at=datetime.now().isoformat()
        )
    
    def _save_log(self):
        """保存故障日志"""
        with open(self.log_file, "w", encoding="utf-8") as f:
            json.dump(self.log.to_dict(), f, indent=2, ensure_ascii=False)
    
    def _generate_fault_id(self) -> str:
        """生成故障 ID"""
        raw = f"{datetime.now().isoformat()}{random.random()}"
        return hashlib.md5(raw.encode()).hexdigest()[:8]
    
    def _find_python_files(self) -> List[Path]:
        """查找目标项目中所有 Python 文件"""
        files = []
        for root, dirs, filenames in os.walk(self.target_path):
            # 跳过目录
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            
            for fname in filenames:
                if fname in SKIP_FILES:
                    continue
                if Path(fname).suffix in PYTHON_EXTENSIONS:
                    files.append(Path(root) / fname)
        
        return files
    
    def _read_file_lines(self, file_path: Path) -> List[str]:
        """读取文件所有行"""
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.readlines()
    
    def _write_file_lines(self, file_path: Path, lines: List[str]):
        """写入文件所有行"""
        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
    
    def _backup_file(self, file_path: Path):
        """备份文件"""
        backup_dir = self.log_dir / "backups"
        backup_dir.mkdir(exist_ok=True)
        rel = file_path.relative_to(self.target_path)
        backup_path = backup_dir / rel
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, backup_path)
    
    def inject_fault(self, fault_type: Optional[str] = None) -> Optional[Fault]:
        """注入一个随机故障（最多重试 10 次找到合适的注入点）"""
        files = self._find_python_files()
        if not files:
            print("[Chaos] No Python files found in target.")
            return None
        
        # 选择故障类型列表
        fault_types = ["DELETE_LINE", "BAD_SYNTAX", "BREAK_STRING", "SWAP_VARIABLES", "ZERO_DIVISION"]
        if fault_type:
            fault_types = [fault_type]
        
        # 最多重试 10 次
        for attempt in range(10):
            target_file = random.choice(files)
            lines = self._read_file_lines(target_file)
            
            if len(lines) < 5:
                continue
            
            # 过滤出可修改的行
            modifiable = []
            for i, line in enumerate(lines):
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and stripped not in ('"""', "'''"):
                    modifiable.append(i)
            
            if not modifiable:
                continue
            
            chosen_type = random.choice(fault_types)
            chosen_line_idx = random.choice(modifiable)
            
            original_line = lines[chosen_line_idx]
            modified_line = self._apply_fault(chosen_type, original_line, lines, chosen_line_idx)
            
            if modified_line is None:
                continue  # 这个类型不适合这行，重试
            
            # 备份并修改
            self._backup_file(target_file)
            lines[chosen_line_idx] = modified_line
            self._write_file_lines(target_file, lines)
            
            # 记录故障
            rel_path = str(target_file.relative_to(self.target_path))
            fault = Fault(
                fault_id=self._generate_fault_id(),
                fault_type=chosen_type,
                file_path=rel_path,
                line_number=chosen_line_idx + 1,
                original_line=original_line.rstrip(),
                modified_line=modified_line.rstrip(),
                timestamp=datetime.now().isoformat()
            )
            self.log.faults.append(fault)
            self._save_log()
            
            print(f"[Chaos] Injected {chosen_type} at {rel_path}:{fault.line_number}")
            print(f"  Before: {original_line.strip()[:80]}")
            print(f"  After:  {modified_line.strip()[:80]}")
            
            return fault
        
        print("[Chaos] Failed to find suitable injection point after 10 attempts")
        return None

    def _apply_fault(
        self, 
        fault_type: str, 
        line: str, 
        all_lines: List[str],
        line_idx: int
    ) -> Optional[str]:
        """应用故障到单行"""
        stripped = line.strip()
        
        if fault_type == "DELETE_LINE":
            # 注释掉该行（不真正删除，保留可追溯性）
            indent = line[:len(line) - len(line.lstrip())]
            return f"{indent}# [CHAOS] DELETED: {stripped}\n"
        
        elif fault_type == "BAD_SYNTAX":
            # 缺少冒号
            if stripped.endswith(":"):
                return line.rstrip()[:-1] + "\n"
            # 或者缺少右括号
            if "(" in stripped and ")" in stripped:
                return line.replace(")", "").replace("(", "(", 1) + "\n"
            # 默认：截断行
            mid = len(stripped) // 2
            return line[:len(line) - len(stripped)] + stripped[:mid] + "\n"
        
        elif fault_type == "BREAK_STRING":
            # 截断字符串常量
            if '"' in stripped or "'" in stripped:
                quote = '"' if '"' in stripped else "'"
                parts = stripped.split(quote)
                if len(parts) >= 3:
                    # 截断字符串内容
                    parts[1] = parts[1][:len(parts[1]) // 2]
                    indent = line[:len(line) - len(line.lstrip())]
                    result = indent + quote.join(parts)
                    if not result.endswith("\n"):
                        result += "\n"
                    return result
            return None  # 跳过没有字符串的行
        
        elif fault_type == "SWAP_VARIABLES":
            # 找到下一个可交换的行，交换两个变量赋值
            if "=" in stripped and not stripped.startswith(("if ", "elif ", "while ", "for ", "return", "def ", "class ", "#")):
                # 找下一行
                next_idx = line_idx + 1
                while next_idx < len(all_lines):
                    next_line = all_lines[next_idx].strip()
                    if next_line and "=" in next_line and not next_line.startswith(("if ", "elif ", "while ", "for ", "return", "def ", "class ", "#")):
                        # 交换两行的右值
                        left_val = stripped.split("=", 1)[1].strip()
                        right_val = next_line.split("=", 1)[1].strip()
                        indent = line[:len(line) - len(line.lstrip())]
                        new_line = indent + stripped.split("=", 1)[0] + " = " + right_val + "\n"
                        # 同时修改下一行
                        next_indent = all_lines[next_idx][:len(all_lines[next_idx]) - len(all_lines[next_idx].lstrip())]
                        all_lines[next_idx] = next_indent + next_line.split("=", 1)[0] + " = " + left_val + "\n"
                        return new_line
                    next_idx += 1
            return None
        
        elif fault_type == "ZERO_DIVISION":
            # 将除法除数改为 0
            if "/ " in stripped or "/(" in stripped or " / " in stripped:
                # 替换第一个数字除数为 0
                import re
                modified = re.sub(r'/\s*(\d+\.?\d*)', '/ 0', stripped, count=1)
                if modified != stripped:
                    indent = line[:len(line) - len(line.lstrip())]
                    return indent + modified + "\n"
            return None
        
        return None
    
    def inject_multiple(self, count: int, fault_types: Optional[List[str]] = None) -> List[Fault]:
        """注入多个故障"""
        faults = []
        types_str = ",".join(fault_types) if fault_types else "random"
        print(f"[Chaos] Injecting {count} faults (types: {types_str})...")
        
        for i in range(count):
            fault_type = random.choice(fault_types) if fault_types else None
            fault = self.inject_fault(fault_type)
            if fault:
                faults.append(fault)
            else:
                print(f"[Chaos] Fault {i+1}/{count} skipped (no suitable target)")
        
        print(f"[Chaos] Done: {len(faults)}/{count} faults injected")
        return faults
    
    def revert_all(self):
        """回滚所有故障"""
        backup_dir = self.log_dir / "backups"
        if not backup_dir.exists():
            print("[Chaos] No backups found.")
            return 0
        
        reverted = 0
        for backup_file in backup_dir.rglob("*"):
            if backup_file.is_file():
                rel = backup_file.relative_to(backup_dir)
                original = self.target_path / rel
                if original.exists():
                    shutil.copy2(backup_file, original)
                    reverted += 1
                    print(f"  Reverted: {rel}")
        
        # 标记所有故障为已回滚
        for fault in self.log.faults:
            fault.reverted = True
        self._save_log()
        
        print(f"[Chaos] Reverted {reverted} files")
        return reverted
    
    def get_summary(self) -> str:
        """获取故障摘要"""
        active = [f for f in self.log.faults if not f.reverted]
        by_type = {}
        for f in active:
            by_type[f.fault_type] = by_type.get(f.fault_type, 0) + 1
        
        lines = [
            f"Chaos Agent Summary",
            f"==================",
            f"Target: {self.target_path}",
            f"Total faults: {len(self.log.faults)}",
            f"Active faults: {len(active)}",
            f"",
            f"By type:"
        ]
        for ftype, count in sorted(by_type.items(), key=lambda x: -x[1]):
            lines.append(f"  {ftype}: {count}")
        
        if active:
            lines.append(f"")
            lines.append(f"Recent faults:")
            for f in active[-5:]:
                lines.append(f"  [{f.fault_id}] {f.fault_type} @ {f.file_path}:{f.line_number}")
        
        return "\n".join(lines)


# ============================================================================
# 主入口
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Chaos Agent - Fault Injector for Axonewt Self-Healing Tests")
    parser.add_argument("--target", "-t", required=True, help="Target project path")
    parser.add_argument("--count", "-n", type=int, default=1, help="Number of faults to inject")
    parser.add_argument("--types", help="Comma-separated fault types (DELETE_LINE, BAD_SYNTAX, etc.)")
    parser.add_argument("--daemon", action="store_true", help="Run in daemon mode (continuous injection)")
    parser.add_argument("--interval", type=int, default=60, help="Interval between injections in daemon mode (seconds)")
    parser.add_argument("--revert", action="store_true", help="Revert all injected faults")
    parser.add_argument("--log", action="store_true", help="Show fault log summary")
    parser.add_argument("--log-dir", help="Custom log directory")
    
    args = parser.parse_args()
    
    agent = ChaosAgent(args.target, log_dir=args.log_dir)
    
    if args.log:
        print(agent.get_summary())
        return
    
    if args.revert:
        agent.revert_all()
        return
    
    if args.daemon:
        print(f"[Chaos] Daemon mode: injecting 1 fault every {args.interval}s (Ctrl+C to stop)")
        try:
            while True:
                agent.inject_fault()
                import time
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n[Chaos] Daemon stopped.")
        return
    
    fault_types = args.types.split(",") if args.types else None
    agent.inject_multiple(args.count, fault_types)
    print()
    print(agent.get_summary())


if __name__ == "__main__":
    main()
