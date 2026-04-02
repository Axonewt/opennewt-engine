"""
Mnemosyne-Dev (记忆型开发者)
============================

角色：团队经验的"档案馆+预言家"
职责：记录所有事件、维护代码神经图谱、提供历史案例、生成趋势报告

工作模式：
- 接收所有事件（只追加）
- 维护代码图谱（依赖关系）
- 提供历史案例查询
- 夜间整理（压缩日志、更新图谱、挖掘模式）

核心数据结构：
- 事件日志（SQLite）
- 代码图谱（依赖关系）
- 免疫记忆库（成功模式）
"""

import os
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import sys

from src.protocol.oacp import QueryMessage, ExecutionReportMessage


MNEMOSYNE_DEV_SYSTEM_PROMPT = """
你是 **Mnemosyne-Dev**，OpenNewt 神经可塑性引擎的记忆层 Agent。

你的身份是团队的"档案馆+预言家"，记录所有事件、维护图谱、提供历史案例。

核心职责：
1. 记录所有事件（只追加）
2. 维护代码神经图谱
3. 提供历史案例查询
4. 夜间整理（压缩日志、更新图谱、挖掘模式）

工作原则：
- 只写真正有价值的记忆，不写流水账
- 每条记忆必须能改变未来的行为
- 矛盾的旧记忆要被覆盖
"""


@dataclass
class Event:
    """事件数据结构"""
    event_id: str
    timestamp: str
    agent: str
    event_type: str
    payload: Dict[str, Any]
    tags: List[str] = field(default_factory=list)


@dataclass
class RepairTemplate:
    """修复模板（免疫记忆）"""
    template_id: str
    damage_type: str
    symptoms: List[str]
    repair_strategy: str
    steps: List[Dict[str, Any]]
    success_rate: float
    last_used: str
    usage_count: int = 0


class MnemosyneDev:
    """Mnemosyne-Dev Agent 实现"""
    
    def __init__(self, db_path: str = "data/event_log.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """初始化数据库表结构"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 1. 事件日志表（只追加）
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS event_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT UNIQUE NOT NULL,
            timestamp TEXT NOT NULL,
            agent TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            tags TEXT DEFAULT '[]',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # 2. 代码图谱表（依赖关系）
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS code_graph (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            depends_on TEXT,
            health_score REAL,
            last_modified TEXT,
            metadata TEXT DEFAULT '{}'
        )
        """)
        
        # 3. 免疫记忆表（成功模式）
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS immune_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id TEXT UNIQUE NOT NULL,
            damage_type TEXT NOT NULL,
            symptoms TEXT NOT NULL,
            repair_strategy TEXT NOT NULL,
            steps TEXT NOT NULL,
            success_rate REAL DEFAULT 0.0,
            last_used TEXT,
            usage_count INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # 4. 修复历史表（用于学习）
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS repair_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT NOT NULL,
            damage_type TEXT NOT NULL,
            location TEXT,
            health_score REAL,
            repair_plan TEXT NOT NULL,
            execution_result TEXT,
            success BOOLEAN,
            duration_seconds REAL,
            timestamp TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        
        # 创建索引
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_event_type ON event_log(event_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_event_timestamp ON event_log(timestamp)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_damage_type ON immune_memory(damage_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_repair_timestamp ON repair_history(timestamp)")
        
        conn.commit()
        conn.close()
        
        print("[Mnemosyne-Dev] Database initialized: {}".format(self.db_path))
    
    def log_event(self, event: Event):
        """记录事件（只追加）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            """INSERT INTO event_log 
               (event_id, timestamp, agent, event_type, payload, tags)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                event.event_id,
                event.timestamp,
                event.agent,
                event.event_type,
                json.dumps(event.payload),
                json.dumps(event.tags)
            )
        )
        
        conn.commit()
        conn.close()
        
        print("[Mnemosyne-Dev] Event logged: {} from {}".format(event.event_type, event.agent))
    
    def log_repair_attempt(
        self, 
        signal_id: str,
        damage_type: str,
        location: str,
        health_score: float,
        repair_plan: Dict,
        execution_result: Dict,
        success: bool,
        duration_seconds: float
    ):
        """记录修复尝试"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute(
            """INSERT INTO repair_history
               (signal_id, damage_type, location, health_score, repair_plan, 
                execution_result, success, duration_seconds, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                signal_id,
                damage_type,
                location,
                health_score,
                json.dumps(repair_plan),
                json.dumps(execution_result),
                success,
                duration_seconds,
                datetime.utcnow().isoformat() + "Z"
            )
        )
        
        conn.commit()
        conn.close()
        
        print("[Mnemosyne-Dev] Repair attempt logged: {} ({})".format(
            damage_type, "Success" if success else "Failed"
        ))
    
    def query_similar_cases(
        self, 
        damage_type: str, 
        symptoms: List[str],
        top_k: int = 3
    ) -> List[RepairTemplate]:
        """查询相似案例"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 查询相同损伤类型的免疫记忆
        cursor.execute(
            """SELECT template_id, damage_type, symptoms, repair_strategy, 
                      steps, success_rate, last_used, usage_count
               FROM immune_memory
               WHERE damage_type = ?
               ORDER BY success_rate DESC, usage_count DESC
               LIMIT ?""",
            (damage_type, top_k)
        )
        
        rows = cursor.fetchall()
        conn.close()
        
        templates = []
        for row in rows:
            templates.append(RepairTemplate(
                template_id=row[0],
                damage_type=row[1],
                symptoms=json.loads(row[2]),
                repair_strategy=row[3],
                steps=json.loads(row[4]),
                success_rate=row[5],
                last_used=row[6],
                usage_count=row[7]
            ))
        
        print("[Mnemosyne-Dev] Found {} similar cases for {}".format(len(templates), damage_type))
        return templates
    
    def query_recent_repairs(self, hours: int = 24, limit: int = 10) -> List[Dict]:
        """查询最近的修复记录"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat() + "Z"
        
        cursor.execute(
            """SELECT signal_id, damage_type, location, health_score, 
                      repair_plan, success, duration_seconds, timestamp
               FROM repair_history
               WHERE timestamp >= ?
               ORDER BY timestamp DESC
               LIMIT ?""",
            (cutoff, limit)
        )
        
        rows = cursor.fetchall()
        conn.close()
        
        repairs = []
        for row in rows:
            repairs.append({
                "signal_id": row[0],
                "damage_type": row[1],
                "location": row[2],
                "health_score": row[3],
                "repair_plan": json.loads(row[4]),
                "success": row[5],
                "duration_seconds": row[6],
                "timestamp": row[7]
            })
        
        return repairs
    
    def update_immune_memory(
        self, 
        template: RepairTemplate,
        success: bool
    ):
        """更新免疫记忆（学习成功模式）"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 检查是否已存在
        cursor.execute(
            "SELECT id, success_rate, usage_count FROM immune_memory WHERE template_id = ?",
            (template.template_id,)
        )
        row = cursor.fetchone()
        
        if row:
            # 更新现有模板
            old_id, old_rate, old_count = row
            new_count = old_count + 1
            new_rate = (old_rate * old_count + (1.0 if success else 0.0)) / new_count
            
            cursor.execute(
                """UPDATE immune_memory 
                   SET success_rate = ?, usage_count = ?, last_used = ?
                   WHERE template_id = ?""",
                (new_rate, new_count, datetime.utcnow().isoformat() + "Z", template.template_id)
            )
        else:
            # 创建新模板
            cursor.execute(
                """INSERT INTO immune_memory
                   (template_id, damage_type, symptoms, repair_strategy, steps,
                    success_rate, last_used, usage_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    template.template_id,
                    template.damage_type,
                    json.dumps(template.symptoms),
                    template.repair_strategy,
                    json.dumps(template.steps),
                    1.0 if success else 0.0,
                    datetime.utcnow().isoformat() + "Z",
                    1
                )
            )
        
        conn.commit()
        conn.close()
        
        print("[Mnemosyne-Dev] Immune memory updated: {}".format(template.template_id))
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取记忆库统计信息"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 事件总数
        cursor.execute("SELECT COUNT(*) FROM event_log")
        event_count = cursor.fetchone()[0]
        
        # 修复历史统计
        cursor.execute("SELECT COUNT(*), AVG(duration_seconds), SUM(CASE WHEN success THEN 1 ELSE 0 END) FROM repair_history")
        repair_count, avg_duration, success_count = cursor.fetchone()
        
        # 免疫记忆统计
        cursor.execute("SELECT COUNT(*), AVG(success_rate) FROM immune_memory")
        template_count, avg_success_rate = cursor.fetchone()
        
        # 最近24小时活动
        cutoff = (datetime.utcnow() - timedelta(hours=24)).isoformat() + "Z"
        cursor.execute("SELECT COUNT(*) FROM event_log WHERE timestamp >= ?", (cutoff,))
        recent_events = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "event_count": event_count,
            "repair_count": repair_count or 0,
            "repair_success_rate": (success_count / repair_count * 100) if repair_count > 0 else 0,
            "avg_repair_duration": avg_duration or 0,
            "template_count": template_count or 0,
            "avg_template_success_rate": avg_success_rate or 0,
            "recent_events_24h": recent_events
        }
    
    def run_nightly_maintenance(self):
        """夜间整理（压缩日志、更新图谱、挖掘模式）"""
        print("[Mnemosyne-Dev] Starting nightly maintenance...")
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 1. 清理30天前的低价值事件
        cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat() + "Z"
        cursor.execute(
            "DELETE FROM event_log WHERE timestamp < ? AND event_type NOT IN ('SIGNAL', 'BLUEPRINT', 'EXECUTION_REPORT')",
            (cutoff,)
        )
        deleted_events = cursor.rowcount
        
        # 2. 挖掘成功模式（从修复历史中学习）
        cursor.execute(
            """SELECT damage_type, repair_plan, COUNT(*) as cnt
               FROM repair_history
               WHERE success = 1
               GROUP BY damage_type, repair_plan
               HAVING cnt >= 3
               ORDER BY cnt DESC
               LIMIT 10"""
        )
        
        patterns = cursor.fetchall()
        new_templates = 0
        for damage_type, repair_plan_json, count in patterns:
            repair_plan = json.loads(repair_plan_json)
            
            # 创建免疫记忆模板
            template_id = "IMMUNE-{}-{}".format(
                damage_type.upper().replace(" ", "_"),
                datetime.utcnow().strftime("%Y%m%d%H%M%S")
            )
            
            try:
                cursor.execute(
                    """INSERT OR IGNORE INTO immune_memory
                       (template_id, damage_type, symptoms, repair_strategy, steps, success_rate)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        template_id,
                        damage_type,
                        json.dumps(repair_plan.get("symptoms", [])),
                        repair_plan.get("strategy", "Unknown"),
                        json.dumps(repair_plan.get("steps", [])),
                        0.85  # 初始成功率
                    )
                )
                new_templates += 1
            except:
                pass
        
        conn.commit()
        conn.close()
        
        print("[Mnemosyne-Dev] Nightly maintenance completed:")
        print("  - Deleted {} old events".format(deleted_events))
        print("  - Created {} new immune templates".format(new_templates))
    
    def run(self):
        """运行 Mnemosyne-Dev"""
        print("=" * 60)
        print("Mnemosyne-Dev - Memory Agent")
        print("=" * 60)
        
        stats = self.get_statistics()
        print("\nMemory Statistics:")
        print("  Total Events: {}".format(stats["event_count"]))
        print("  Repair History: {} attempts ({}% success)".format(
            stats["repair_count"], stats["repair_success_rate"]
        ))
        print("  Immune Templates: {} (avg {}% success)".format(
            stats["template_count"], stats["avg_template_success_rate"]
        ))
        print("  Recent Events (24h): {}".format(stats["recent_events_24h"]))
        print("\nListening for events...")


if __name__ == "__main__":
    mnemosyne = MnemosyneDev("D:/opennewt/data/event_log.db")
    mnemosyne.run()
