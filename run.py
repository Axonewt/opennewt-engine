"""
OpenNewt Engine v0.2 - Main Entry Point

Axonewt Neural Plasticity Engine
Core architecture: Perception -> Decision -> Execution -> Memory

Phase 2: Message-driven architecture with real Effector execution

Usage:
    python run.py                    # Start monitoring loop
    python run.py --demo             # Run single-cycle demo
    python run.py --self-heal        # Run self-heal test scenario
    python run.py --tick-interval 60 # Set monitoring interval
"""

import os
import sys
import asyncio
import signal
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional

# Project root
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from src.protocol.oacp import (
    SignalMessage, BlueprintMessage, ExecutionReportMessage,
    OACPMessage, DamageType, Priority, MessageType
)
from src.agents.soma_dev import SomaDev
from src.agents.plasticus_dev import PlasticusDev
from src.agents.effector_dev import EffectorDev
from src.agents.mnemosyne_dev import MnemosyneDev
from src.agents.message_bus import MessageBus

import yaml


def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file"""
    path = Path(config_path)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


class OpenNewtEngine:
    """OpenNewt Neural Plasticity Engine - Message-driven Architecture"""

    def __init__(self, config: dict):
        self.config = config
        self.data_dir = ROOT / "data"
        self.data_dir.mkdir(exist_ok=True)

        self.running = False
        self.iteration = 0
        self.tick_interval = config.get("monitoring", {}).get(
            "tick_interval", 30
        )

        # GitHub token from environment
        self.github_token = os.getenv("GITHUB_TOKEN")

        # Bridge 模式（Axonewt → WorkBuddy/Axiom 桥接）
        bridge_cfg = config.get("bridge", {})
        self.bridge_enabled = bridge_cfg.get("enabled", False)
        self.bridge_timeout = bridge_cfg.get("timeout", 300)
        self._bridge = None  # 延迟初始化，避免 import 失败

        # 当前修复状态
        self._current_signal = None
        self._current_blueprint = None
        self._current_report = None
        self._health_after_repair = None

        print("=" * 60)
        print("  OpenNewt Engine v0.2 - Starting (Phase 2)")
        print("=" * 60)

        # Initialize components
        self._init_agents()
        self._init_bus()

        # Bridge 模式：启动 HTTP 服务
        if self.bridge_enabled:
            self._init_bridge()

    def _init_agents(self):
        """Initialize all four agents"""

        db_path = str(self.data_dir / "opennewt.db")

        print("\n[1/4] Initializing Mnemosyne (Memory Layer)...")
        self.mnemosyne = MnemosyneDev(db_path=db_path)
        print("      OK - Mnemosyne ready")

        print("[2/4] Initializing Soma (Perception Layer)...")
        self.soma = SomaDev(
            project_path=str(ROOT),
            github_token=self.github_token
        )
        print("      OK - Soma ready")

        print("[3/4] Initializing Plasticus (Decision Layer)...")
        llm_cfg = self.config.get("llm", {})
        llm_provider = llm_cfg.get("provider", "ollama")
        
        if llm_provider == "workbuddy":
            self.plasticus = PlasticusDev(
                workbuddy_enabled=True,
                github_token=self.github_token
            )
        elif llm_provider == "ollama":
            self.plasticus = PlasticusDev(
                ollama_url=llm_cfg.get("base_url", llm_cfg.get("ollama_url", "http://127.0.0.1:11434")),
                ollama_model=llm_cfg.get("model", "glm-4.7-flash:latest"),
                github_token=self.github_token
            )
        else:
            self.plasticus = PlasticusDev(
                ollama_url=llm_cfg.get("base_url", "http://127.0.0.1:11434"),
                ollama_model=llm_cfg.get("model", "glm-4.7-flash:latest"),
                github_token=self.github_token
            )
        print("      OK - Plasticus ready")

        print("[4/4] Initializing Effector (Execution Layer)...")
        self.effector = EffectorDev(
            project_path=str(ROOT),
            github_token=self.github_token
        )
        print("      OK - Effector ready")

        print("\n  All agents initialized successfully!")

    def _init_bus(self):
        """Initialize message bus and register handlers"""
        self.bus = MessageBus()

        # Plasticus 处理 SIGNAL -> 生成 BLUEPRINT
        self.bus.register("Plasticus-Dev", self._handle_signal)

        # Effector 处理 BLUEPRINT -> 执行 -> 生成 EXECUTION_REPORT
        self.bus.register("Effector-Dev", self._handle_blueprint)

        # Mnemosyne 处理 EXECUTION_REPORT -> 记录
        self.bus.register("Mnemosyne-Dev", self._handle_report)

        print("  Message bus ready")

    def _init_bridge(self):
        """初始化 Axonewt-Axiom Bridge"""
        try:
            from bridge import AxonewtBridge
            self._bridge = AxonewtBridge()
            self._bridge.start_http_server()
            print(f"  Bridge ready on http://127.0.0.1:9110")
        except ImportError as e:
            print(f"  [WARN] Bridge module not available: {e}")
            self.bridge_enabled = False

    async def _handle_signal(self, message: OACPMessage) -> Optional[OACPMessage]:
        """Plasticus: 接收 SIGNAL，生成修复方案，返回 BLUEPRINT"""
        payload = message.payload
        health_score = payload.get("health_score", 0.0)

        print(f"\n[Plasticus] Processing SIGNAL from {message.source}")
        print(f"  Damage: {payload.get('damage_type')}")
        print(f"  Severity: {payload.get('severity')}")
        print(f"  Health: {health_score:.2f}")

        self._current_signal = payload

        # Bridge 模式：转发给外部 Agent
        if self.bridge_enabled and self._bridge:
            return await self._handle_signal_bridge(payload)

        try:
            # 查询历史案例（如果有）
            # self.mnemosyne.query_similar_cases(...)

            # 生成修复方案
            plans = self.plasticus.generate_plans(
                damage_type=payload.get("damage_type", "CODE_DECAY"),
                location=payload.get("location", "unknown"),
                symptoms=payload.get("symptoms", []),
                health_score=health_score,
                use_llm=True,
                use_multi_sample=False
            )

            if not plans:
                print("[Plasticus] No repair plans generated.")
                return None

            # 评估并选择最优方案
            best_plan = self.plasticus.evaluate_plans(plans)
            print(f"[Plasticus] Best plan: {best_plan.name}")
            print(f"  Success rate: {best_plan.historical_success_rate * 100:.0f}%")
            print(f"  Steps: {len(best_plan.steps)}")

            # 生成 BLUEPRINT 消息
            blueprint = BlueprintMessage.create(
                plan_id=f"PLAN-{self.iteration}",
                strategy=best_plan.name,
                steps=[
                    {
                        "number": i + 1,
                        "name": step.get("name", step.get("description", f"Step {i+1}")),
                        "description": step.get("description", ""),
                        "action": step.get("description", f"Step {i+1}"),
                        "type": step.get("type", "generic"),
                        "file_path": step.get("file_path"),
                        "content": step.get("content"),
                    }
                    for i, step in enumerate(best_plan.steps)
                ],
                estimated_downtime=f"{best_plan.downtime_seconds}s",
                success_rate_prediction=best_plan.historical_success_rate,
                rollback_plan="Revert changes"
            )

            self._current_blueprint = blueprint
            return blueprint  # 发送给 Effector

        except Exception as e:
            print(f"[Plasticus] ERROR: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def _handle_signal_bridge(self, payload: dict) -> Optional[OACPMessage]:
        """
        Bridge 模式的信号处理：不走本地 LLM，而是通过 Bridge 转发给外部 Agent。
        
        流程：
        1. 写 trigger.json（故障报告）
        2. 等待 result.json（外部 Agent 的修复方案）
        3. 将 result 转成 BLUEPRINT 返回给 Effector
        """
        if not self._bridge:
            print("[Bridge] Not initialized, falling back to local LLM")
            return None

        # 构造 trigger
        trigger = {
            "id": payload.get("event_id", f"TICK-{self.iteration}-{datetime.now().strftime('%Y%m%d%H%M%S')}"),
            "health_score": payload.get("health_score", 0.0),
            "severity": payload.get("severity", "P1"),
            "damage_type": payload.get("damage_type", "CODE_DECAY"),
            "location": payload.get("location", "unknown"),
            "symptoms": payload.get("symptoms", []),
            "issues": payload.get("issues", []),
            "context": {
                "project_path": str(ROOT),
                "iteration": self.iteration
            }
        }

        # 写入 trigger
        print(f"\n[Bridge] Writing trigger for {trigger['id']}...")
        self._bridge.write_trigger(trigger)
        print(f"[Bridge] Waiting for external agent to fix (timeout: {self.bridge_timeout}s)...")

        # 等待 result
        result = await self._bridge.async_wait_for_result(timeout=self.bridge_timeout, poll_interval=5)

        if not result:
            print("[Bridge] Timeout - no result received from external agent")
            return None

        # 将 result 转成 BLUEPRINT
        print(f"[Bridge] Received fix: {result.get('summary', 'N/A')}")
        print(f"[Bridge] Status: {result.get('status')}, Confidence: {result.get('confidence', 'N/A')}")

        if result.get("status") != "success":
            print(f"[Bridge] External agent reported failure, skipping")
            return None

        steps = result.get("steps", [])
        if not steps:
            print("[Bridge] No fix steps provided")
            return None

        blueprint = BlueprintMessage.create(
            plan_id=f"BRIDGE-{self.iteration}",
            strategy=result.get("summary", "Bridge Fix"),
            steps=[
                {
                    "number": i + 1,
                    "name": step.get("name", step.get("description", f"Step {i+1}")),
                    "description": step.get("description", ""),
                    "action": step.get("action", step.get("description", "")),
                    "type": step.get("type", "generic"),
                    "file_path": step.get("file_path"),
                    "content": step.get("content"),
                }
                for i, step in enumerate(steps)
            ],
            estimated_downtime="0s",
            success_rate_prediction=result.get("confidence", 0.8),
            rollback_plan="Revert changes"
        )

        self._current_blueprint = blueprint
        return blueprint

    async def _handle_blueprint(self, message: OACPMessage) -> Optional[OACPMessage]:
        """Effector: 接收 BLUEPRINT，执行修复，返回 EXECUTION_REPORT"""
        print(f"\n[Effector] Processing BLUEPRINT from {message.source}")

        try:
            # 设置自动批准模式（守护进程中不需要人工交互）
            os.environ["EFFECTOR_AUTO_APPROVE"] = "true"

            # 执行蓝图
            report = self.effector.execute_blueprint(message)

            self._current_report = report
            return report  # 发送给 Mnemosyne

        except Exception as e:
            print(f"[Effector] ERROR: {e}")
            import traceback
            traceback.print_exc()

            # 返回失败报告
            return ExecutionReportMessage.create(
                plan_id=message.payload.get("plan_id", "unknown"),
                status="failed",
                steps_completed=0,
                steps_total=len(message.payload.get("steps", [])),
                errors=[str(e)]
            )

    async def _handle_report(self, message: OACPMessage) -> Optional[OACPMessage]:
        """Mnemosyne: 接收 EXECUTION_REPORT，记录到数据库"""
        print(f"\n[Mnemosyne] Recording EXECUTION_REPORT")

        try:
            from src.agents.mnemosyne_dev import Event

            payload = message.payload
            event = Event(
                event_id=f"EXEC-{self.iteration}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                timestamp=datetime.now().isoformat() + "Z",
                agent="Effector-Dev",
                event_type="EXECUTION_REPORT",
                payload={
                    "plan_id": payload.get("plan_id"),
                    "status": payload.get("status"),
                    "steps_completed": payload.get("steps_completed"),
                    "steps_total": payload.get("steps_total"),
                    "errors": payload.get("errors", []),
                    "health_after": payload.get("health_after")
                }
            )
            self.mnemosyne.log_event(event)
            print(f"[Mnemosyne] Recorded: {payload.get('status')} "
                  f"({payload.get('steps_completed', 0)}/{payload.get('steps_total', 0)} steps)")

        except Exception as e:
            print(f"[Mnemosyne] ERROR: {e}")

        return None  # 不需要进一步响应

    # =========================================================================
    # Tick Cycle (主循环)
    # =========================================================================

    async def tick(self):
        """Single monitoring cycle: Sense -> Signal -> Decide -> Execute -> Record"""
        self.iteration += 1
        print(f"\n{'='*60}")
        print(f"  Tick #{self.iteration} - {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*60}")

        # Phase 1: Perception (感知)
        print("\n[Soma] Scanning health...")
        soma_report = {}
        try:
            soma_report = self.soma.scan_codebase()
            health_score = soma_report["health_score"]
            health_status = soma_report.get("health_status", "unknown")
            print(f"[Soma] Health score: {health_score:.2f} ({health_status})")
        except Exception as e:
            print(f"[Soma] Scan failed: {e}")
            import traceback
            traceback.print_exc()
            health_score = 1.0

        # 记录感知事件（无论健康与否）
        try:
            from src.agents.mnemosyne_dev import Event
            event = Event(
                event_id=f"TICK-{self.iteration}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                timestamp=datetime.now().isoformat() + "Z",
                agent="Soma-Dev",
                event_type="TICK",
                payload={
                    "iteration": self.iteration,
                    "health_score": health_score,
                    "health_status": health_status
                }
            )
            self.mnemosyne.log_event(event)
        except Exception:
            pass

        if health_score >= 0.7:
            print("[OK] System healthy, no action needed.")
            return

        # Phase 2: Signal (触发信号)
        print(f"\n[!] Health below threshold, triggering repair cycle...")

        signal = SignalMessage.create(
            damage_type=DamageType.CODE_DECAY,
            severity=Priority.P0 if health_score < 0.5 else Priority.P1,
            location="detected by Soma",
            symptoms=[f"Health score {health_score:.2f}"],
            health_score=health_score
        )
        # 附加 Soma 详细报告（供 Bridge 模式使用）
        signal.payload["soma_report"] = soma_report
        signal.payload["issues"] = soma_report.get("issues", [])

        # Phase 3: Decision + Execution (通过消息总线)
        # Signal -> Plasticus -> Blueprint -> Effector -> Report -> Mnemosyne
        print(f"\n[Bus] Sending SIGNAL to Plasticus-Dev...")
        await self.bus.send(signal)

        # 等待消息总线处理完成（所有消息被消费）
        await self._wait_bus_idle(timeout=120)

        # Phase 4: 验证修复结果
        if self._current_report:
            status = self._current_report.payload.get("status")
            print(f"\n[Result] Repair status: {status}")

            if status == "success":
                print("[OK] Repair completed successfully!")
            elif status == "partial_success":
                print("[WARN] Repair partially successful.")
            elif status == "rolled_back":
                print("[WARN] Repair failed and was rolled back.")
            else:
                print("[ERROR] Repair failed.")
        else:
            print("[WARN] No execution report received.")

        # 打印总线统计
        stats = self.bus.stats
        print(f"\n[Bus] Stats: sent={stats.total_sent}, delivered={stats.total_delivered}, failed={stats.total_failed}")

    async def _wait_bus_idle(self, timeout: int = 120):
        """等待消息总线空闲（所有消息被处理）"""
        # 给消息总线一个 tick 来处理
        await asyncio.sleep(0.5)
        
        elapsed = 0
        while elapsed < timeout:
            pending = sum(q.qsize() for q in self.bus._mailboxes.values())
            stats = self.bus.stats
            
            # 每 5 秒打印一次状态
            if elapsed % 5 == 0 and pending > 0:
                print(f"[Bus] Waiting... pending={pending}, sent={stats.total_sent}, "
                      f"delivered={stats.total_delivered}, log_count={len(self.bus.message_log)}")
            
            if pending == 0:
                # 额外等待 1 秒，确保最后的 handler 完成
                await asyncio.sleep(1)
                pending = sum(q.qsize() for q in self.bus._mailboxes.values())
                if pending == 0:
                    return
            
            await asyncio.sleep(1)
            elapsed += 1
        
        print(f"[Bus] WARNING: Timeout waiting for bus to idle ({timeout}s)")
        # 打印消息日志用于调试
        for entry in self.bus.message_log:
            print(f"  [{entry['time']}] {entry['type']}: {entry['from']} -> {entry['to']}")

    # =========================================================================
    # Self-Heal Test (自愈测试场景)
    # =========================================================================

    async def run_self_heal_test(self):
        """运行自愈测试场景"""
        print("\n" + "=" * 60)
        print("  Self-Heal Test Scenario")
        print("=" * 60)

        # 创建测试目录
        test_dir = ROOT / "tests" / "self_heal"
        test_dir.mkdir(parents=True, exist_ok=True)

        # 创建一个"故意坏掉的"测试文件
        broken_file = test_dir / "broken_module.py"
        healthy_content = '''"""
A healthy Python module for self-heal testing.
"""

def calculate_average(numbers):
    """Calculate the average of a list of numbers."""
    if not numbers:
        return 0.0
    return sum(numbers) / len(numbers)


def is_prime(n):
    """Check if a number is prime."""
    if n < 2:
        return False
    for i in range(2, int(n**0.5) + 1):
        if n % i == 0:
            return False
    return True


class DataProcessor:
    """Process data with validation."""

    def __init__(self, data):
        self.data = data

    def validate(self):
        """Validate the data."""
        return isinstance(self.data, list) and len(self.data) > 0

    def transform(self):
        """Transform the data."""
        if not self.validate():
            raise ValueError("Invalid data")
        return [x * 2 for x in self.data]
'''

        broken_content = '''"""
A broken Python module for self-heal testing.
This file has INTENTIONAL issues that Soma should detect.
"""

def calculate_average(numbers):
    """Calculate the average - MISSING NULL CHECK"""
    return sum(numbers) / len(numbers)


def is_prime(n):
    """Check if prime - INEFFICIENT ALGORITHM"""
    if n < 2:
        return False
    for i in range(2, n):
        if n % i == 0:
            return False
    return True


class DataProcessor:
    """Process data - NO VALIDATION"""

    def __init__(self, data):
        self.data = data

    def transform(self):
        """Transform without validation - DANGEROUS"""
        return [x * 2 for x in self.data]
'''

        # 写入坏掉的文件
        broken_file.write_text(broken_content, encoding="utf-8")
        print(f"\n[Setup] Created broken test file: {broken_file}")
        print("  Issues:")
        print("    1. calculate_average: missing null check -> ZeroDivisionError")
        print("    2. is_prime: O(n) instead of O(sqrt(n))")
        print("    3. DataProcessor: validate() removed, transform() unsafe")

        # 运行一个 tick，看引擎能否检测并修复
        self.iteration = 0

        # 启动消息总线
        await self.bus.start()

        try:
            await self.tick()
        finally:
            await self.bus.stop()

        # 检查结果
        if self._current_report:
            status = self._current_report.payload.get("status")
            print(f"\n{'='*60}")
            print(f"  Self-Heal Test Result: {status}")
            print(f"{'='*60}")

            # 恢复文件（确保不留下坏代码）
            broken_file.write_text(healthy_content, encoding="utf-8")
            print(f"[Cleanup] Restored healthy file: {broken_file}")

            return status == "success"
        else:
            print("\n[!] No repair was attempted.")
            # 清理
            broken_file.write_text(healthy_content, encoding="utf-8")
            return False

    # =========================================================================
    # Engine Control (引擎控制)
    # =========================================================================

    async def run_loop(self):
        """Main async monitoring loop"""
        self._stop_event = asyncio.Event()
        self.running = True
        print(f"\n  Monitoring started (interval: {self.tick_interval}s)")
        print(f"  Press Ctrl+C to stop\n")

        # 启动消息总线
        await self.bus.start()

        while self.running:
            try:
                await self.tick()
            except Exception as e:
                print(f"[ERROR] Tick failed: {e}")
                import traceback
                traceback.print_exc()

            # Wait for next tick or stop signal
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.tick_interval
                )
                break  # Stop event was set
            except asyncio.TimeoutError:
                pass  # Normal tick interval

        # Stop message bus
        await self.bus.stop()

    def stop(self):
        """Stop the engine"""
        print("\n  Stopping engine...")
        self.running = False
        if hasattr(self, "_stop_event"):
            self._stop_event.set()

    async def run_demo(self):
        """Run a single demo cycle with message bus"""
        print("\n  Demo mode: single cycle with message bus\n")
        self._stop_event = asyncio.Event()

        # Start bus for this cycle
        await self.bus.start()

        try:
            await self.tick()
        finally:
            await self.bus.stop()

        print("\n  Demo complete!")


def main():
    parser = argparse.ArgumentParser(
        description="OpenNewt Engine v0.2 - Neural Plasticity Engine"
    )
    parser.add_argument(
        "--config", default="config.yaml",
        help="Path to config.yaml"
    )
    parser.add_argument(
        "--demo", action="store_true",
        help="Run single demo cycle"
    )
    parser.add_argument(
        "--self-heal", action="store_true",
        help="Run self-heal test scenario"
    )
    parser.add_argument(
        "--tick-interval", type=int, default=30,
        help="Monitoring tick interval in seconds"
    )
    args = parser.parse_args()

    config = load_config(args.config)
    if args.tick_interval != 30:
        config.setdefault("monitoring", {})["tick_interval"] = args.tick_interval

    engine = OpenNewtEngine(config)

    # Graceful shutdown
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def shutdown_handler(sig, frame):
        engine.stop()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        if args.demo:
            loop.run_until_complete(engine.run_demo())
        elif args.self_heal:
            loop.run_until_complete(engine.run_self_heal_test())
        else:
            loop.run_until_complete(engine.run_loop())
    finally:
        print("\n  Engine stopped.")
        loop.close()


if __name__ == "__main__":
    main()
