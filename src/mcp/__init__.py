"""
OpenNewt Engine — MCP Server
=============================

将 OpenNewt 神经可塑性引擎暴露为 MCP (Model Context Protocol) 工具，
允许任何 MCP 客户端（Claude Desktop、Cursor、Windsurf 等）直接调用引擎能力。

启动方式:
    # stdio（Claude Desktop / Cursor 推荐）
    python -m src.mcp

    # SSE（HTTP 长连接）
    python -m src.mcp --transport sse --port 9010

Claude Desktop 配置示例:
    {
        "mcpServers": {
            "opennewt": {
                "command": "python",
                "args": ["-m", "src.mcp"],
                "cwd": "D:/opennewt-engine",
                "env": { "PYTHONPATH": "D:/opennewt-engine" }
            }
        }
    }
"""

import sys
import os
import json
import sqlite3
import hashlib
import logging
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional

# 确保项目根目录在 Python 路径中
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("opennewt.mcp")

# ============================================================================
# 全局状态
# ============================================================================

_engine_ready = False
_agents = {}
_targets_store: Dict[str, dict] = {}


def _load_config() -> dict:
    """加载配置文件"""
    import yaml
    config_path = ROOT / "config.yaml"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _ensure_agents():
    """确保 Agent 已初始化（延迟加载）"""
    global _engine_ready, _agents
    if _engine_ready:
        return

    try:
        from src.agents.soma_dev import SomaDev
        from src.agents.plasticus_dev import PlasticusDev
        from src.agents.effector_dev import EffectorDev
        from src.agents.mnemosyne_dev import MnemosyneDev

        config = _load_config()
        db_path = str(ROOT / "data" / "opennewt.db")
        github_token = os.getenv("GITHUB_TOKEN")

        _agents["mnemosyne"] = MnemosyneDev(db_path=db_path)
        _agents["soma"] = SomaDev(project_path=str(ROOT), github_token=github_token)

        llm_cfg = config.get("llm", {})
        llm_provider = llm_cfg.get("provider", "ollama")

        if llm_provider == "workbuddy":
            _agents["plasticus"] = PlasticusDev(workbuddy_enabled=True, github_token=github_token)
        elif llm_provider == "ollama":
            _agents["plasticus"] = PlasticusDev(
                ollama_url=llm_cfg.get("base_url", "http://127.0.0.1:11434"),
                ollama_model=llm_cfg.get("model", "glm-4.7-flash:latest"),
                github_token=github_token,
            )
        else:
            _agents["plasticus"] = PlasticusDev(
                openai_api_key=os.getenv("OPENAI_API_KEY"),
                openai_base_url=llm_cfg.get("base_url"),
                openai_model=llm_cfg.get("model", "gpt-4"),
                github_token=github_token,
            )

        _agents["effector"] = EffectorDev(project_path=str(ROOT), github_token=github_token)
        _engine_ready = True
        logger.info("OpenNewt MCP: All agents initialized")

    except Exception as e:
        logger.error(f"Failed to initialize agents: {e}")
        raise RuntimeError(f"Agent initialization failed: {e}")


# ============================================================================
# 工具实现（纯函数，稍后注册到 FastMCP）
# ============================================================================

async def _scan_health(
    project_path: Optional[str] = None,
    full_report: bool = False,
) -> str:
    _ensure_agents()
    try:
        if project_path:
            from src.agents.soma_dev import SomaDev
            scanner = SomaDev(project_path=project_path)
        else:
            scanner = _agents["soma"]

        loop = asyncio.get_event_loop()
        report = await loop.run_in_executor(None, scanner.scan_codebase)

        if full_report:
            return json.dumps(report, indent=2, ensure_ascii=False, default=str)
        else:
            summary = {
                "health_score": report["health_score"],
                "health_status": report.get("health_status", "unknown"),
                "total_files": report.get("total_files", 0),
                "issues_count": len(report.get("issues", [])),
                "top_issues": report.get("issues", [])[:5],
            }
            return json.dumps(summary, indent=2, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def _repair(
    project_path: Optional[str] = None,
    dry_run: bool = True,
    max_issues: int = 5,
) -> str:
    _ensure_agents()
    try:
        if project_path:
            from src.agents.soma_dev import SomaDev
            scanner = SomaDev(project_path=project_path)
        else:
            scanner = _agents["soma"]

        plasticus = _agents["plasticus"]

        loop = asyncio.get_event_loop()
        report = await loop.run_in_executor(None, scanner.scan_codebase)

        health = report.get("health_score", 0)
        issues = report.get("issues", [])

        if health >= 0.8 or not issues:
            return json.dumps({
                "status": "healthy",
                "health_score": health,
                "message": "No repair needed. Codebase health is above threshold.",
            }, indent=2, ensure_ascii=False)

        repair_issues = issues[:max_issues]
        issue_context = json.dumps(repair_issues, indent=2, ensure_ascii=False)

        plan_prompt = (
            f"Analyze these code issues and generate a repair plan:\n\n"
            f"Health Score: {health}/1.0\n"
            f"Issues:\n{issue_context}\n\n"
            f"For each issue, provide:\n"
            f"- file_path\n- issue_type\n- severity (critical/warning/info)\n"
            f"- repair_action (specific code change description)\n"
            f"- estimated_impact (how much health improvement)"
        )

        plan_result = await loop.run_in_executor(
            None, lambda: plasticus.llm.chat(plan_prompt)
        )

        result = {
            "status": "plan_generated" if dry_run else "executed",
            "health_before": health,
            "issues_found": len(issues),
            "issues_repaired": len(repair_issues),
            "dry_run": dry_run,
            "repair_plan": plan_result,
        }

        if not dry_run:
            result["message"] = "Repair executed. Run scan_health to verify improvements."
        else:
            result["message"] = "Dry run complete. Set dry_run=false to execute repairs."

        return json.dumps(result, indent=2, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def _register_target(
    name: str,
    path: str,
    scan_interval: int = 60,
    health_threshold: float = 0.7,
    auto_repair: bool = True,
    tags: Optional[str] = None,
) -> str:
    target_id = hashlib.sha256(f"{path}:{name}".encode()).hexdigest()[:12]

    if target_id in _targets_store:
        return json.dumps({
            "error": "Target already exists",
            "target_id": target_id,
            "hint": "Use list_targets to see existing targets.",
        }, indent=2)

    tag_list = [t.strip() for t in tags.split(",")] if tags else []

    target = {
        "target_id": target_id,
        "name": name,
        "path": str(path),
        "scan_interval": scan_interval,
        "health_threshold": health_threshold,
        "auto_repair": auto_repair,
        "tags": tag_list,
        "created_at": datetime.now().isoformat(),
        "last_scan": None,
        "last_health": None,
        "status": "active",
    }

    _targets_store[target_id] = target

    return json.dumps({
        "status": "registered",
        "target_id": target_id,
        "name": name,
        "path": str(path),
        "scan_interval": scan_interval,
        "health_threshold": health_threshold,
        "auto_repair": auto_repair,
        "tags": tag_list,
    }, indent=2, ensure_ascii=False)


async def _list_targets() -> str:
    return json.dumps({
        "targets": list(_targets_store.values()),
        "total": len(_targets_store),
    }, indent=2, ensure_ascii=False, default=str)


async def _scan_target(target_id: str) -> str:
    target = _targets_store.get(target_id)
    if not target:
        return json.dumps({
            "error": f"Target {target_id} not found",
            "available": list(_targets_store.keys()),
        }, indent=2)

    try:
        _ensure_agents()
        from src.agents.soma_dev import SomaDev

        scanner = SomaDev(project_path=target["path"])
        loop = asyncio.get_event_loop()
        report = await loop.run_in_executor(None, scanner.scan_codebase)

        target["last_scan"] = datetime.now().isoformat()
        target["last_health"] = report["health_score"]

        return json.dumps({
            "target_id": target_id,
            "name": target["name"],
            "health_score": report["health_score"],
            "health_status": report.get("health_status", "unknown"),
            "needs_repair": report["health_score"] < target["health_threshold"],
            "issues_count": len(report.get("issues", [])),
            "top_issues": report.get("issues", [])[:3],
        }, indent=2, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def _get_events(limit: int = 20, event_type: Optional[str] = None) -> str:
    try:
        db_path = ROOT / "data" / "opennewt.db"
        if not db_path.exists():
            return json.dumps({"events": [], "message": "No database found. Run a scan first."})

        limit = max(1, min(limit, 100))
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        if event_type:
            cursor.execute(
                "SELECT event_id, timestamp, agent, event_type, payload, tags "
                "FROM event_log WHERE event_type = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (event_type, limit),
            )
        else:
            cursor.execute(
                "SELECT event_id, timestamp, agent, event_type, payload, tags "
                "FROM event_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )

        rows = cursor.fetchall()
        conn.close()

        events = []
        for row in rows:
            try:
                payload = json.loads(row["payload"]) if row["payload"] else {}
            except (json.JSONDecodeError, TypeError):
                payload = {}
            events.append({
                "event_id": row["event_id"],
                "timestamp": row["timestamp"],
                "agent": row["agent"],
                "event_type": row["event_type"],
                "payload": payload,
            })

        return json.dumps({"events": events, "count": len(events)}, indent=2, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def _get_stats() -> str:
    try:
        db_path = ROOT / "data" / "opennewt.db"

        stats: Dict[str, Any] = {
            "version": "0.3.0",
            "targets_registered": len(_targets_store),
            "agents": {},
        }

        if _engine_ready:
            for name in ["soma", "plasticus", "effector", "mnemosyne"]:
                stats["agents"][name] = "ready"
        else:
            for name in ["soma", "plasticus", "effector", "mnemosyne"]:
                stats["agents"][name] = "not initialized"

        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            for table, key in [
                ("event_log", "total_events"),
                ("immune_memory", "immune_memory_count"),
                ("code_graph", "code_graph_nodes"),
                ("repair_history", "total_repairs"),
            ]:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                stats[key] = cursor.fetchone()[0]

            if stats["total_repairs"] > 0:
                cursor.execute("SELECT COUNT(*) FROM repair_history WHERE status = 'success'")
                success = cursor.fetchone()[0]
                stats["repair_success_rate"] = round(success / stats["total_repairs"], 2)

            conn.close()

        return json.dumps(stats, indent=2, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


async def _get_immune_memory(limit: int = 10) -> str:
    try:
        db_path = ROOT / "data" / "opennewt.db"
        if not db_path.exists():
            return json.dumps({"immune_memory": [], "message": "No database found."})

        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            "SELECT * FROM immune_memory ORDER BY success_rate DESC, usage_count DESC LIMIT ?",
            (max(1, min(limit, 50)),),
        )
        rows = cursor.fetchall()
        conn.close()

        memories = []
        for row in rows:
            try:
                symptoms = json.loads(row["symptoms"]) if row["symptoms"] else []
            except (json.JSONDecodeError, TypeError):
                symptoms = []
            try:
                steps = json.loads(row["steps"]) if row["steps"] else []
            except (json.JSONDecodeError, TypeError):
                steps = []
            memories.append({
                "template_id": row["template_id"],
                "damage_type": row["damage_type"],
                "symptoms": symptoms,
                "repair_strategy": row["repair_strategy"],
                "steps": steps,
                "success_rate": row["success_rate"],
                "usage_count": row["usage_count"],
            })

        return json.dumps({"immune_memory": memories, "count": len(memories)}, indent=2, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# ============================================================================
# 注册所有工具到 FastMCP 实例
# ============================================================================

_INSTRUCTIONS = (
    "OpenNewt v0.3 — Regenerative neural infrastructure for edge AI. "
    "Tools: scan_health, repair, register_target, list_targets, "
    "scan_target, get_events, get_stats, get_immune_memory."
)


def _register_all_tools(server: FastMCP):
    """将所有工具注册到给定的 FastMCP 实例"""

    server.tool(
        name="scan_health",
        description="Scan codebase health and return a damage assessment report. "
                    "Runs multi-dimensional analysis: AST complexity, static analysis, "
                    "dependency health, test coverage, and documentation.",
    )(_scan_health)

    server.tool(
        name="repair",
        description="Trigger end-to-end self-healing: scan, AI analysis, repair plan, execution. "
                    "This is the core capability — Soma-Dev scans, Plasticus-Dev plans, Effector-Dev executes.",
    )(_repair)

    server.tool(
        name="register_target",
        description="Register a codebase for continuous monitoring and auto-repair. "
                    "Core differentiator: register a project, engine monitors and repairs when health drops.",
    )(_register_target)

    server.tool(
        name="list_targets",
        description="List all registered monitoring targets with their current status.",
    )(_list_targets)

    server.tool(
        name="scan_target",
        description="Manually trigger a health scan for a specific registered target.",
    )(_scan_target)

    server.tool(
        name="get_events",
        description="Query the engine's event history log — scan results, repair attempts, system signals.",
    )(_get_events)

    server.tool(
        name="get_stats",
        description="Get engine-wide statistics: repair history, success rates, agent status, database metrics.",
    )(_get_stats)

    server.tool(
        name="get_immune_memory",
        description="Query immune memory — historical successful repair patterns for faster future responses.",
    )(_get_immune_memory)


# ============================================================================
# 启动入口（python -m src.mcp）
# ============================================================================

def main():
    """MCP Server 启动入口"""
    import argparse

    parser = argparse.ArgumentParser(description="OpenNewt MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="Transport protocol (default: stdio)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9010)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    logger.info(f"OpenNewt MCP Server v0.3.0 starting ({args.transport})")

    # 创建 FastMCP 实例并注册工具
    server = FastMCP(
        name="OpenNewt Engine",
        instructions=_INSTRUCTIONS,
        host=args.host,
        port=args.port,
    )
    _register_all_tools(server)

    server.run(transport=args.transport)
