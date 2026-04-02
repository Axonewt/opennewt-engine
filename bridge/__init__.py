"""
Axonewt-Axiom Bridge - 零依赖 HTTP 服务器

轻量 HTTP 服务，作为 Axonewt 引擎与外部 AI Agent（WorkBuddy/Axiom）之间的桥梁。
纯标准库实现，无第三方依赖。

通信协议见 PROTOCOL.md
"""

import json
import time
import asyncio
import logging
import os
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict
from http.server import HTTPServer, BaseHTTPRequestHandler
from threading import Thread
import urllib.parse

# Bridge 目录（此文件所在目录）
BRIDGE_DIR = Path(__file__).parent

logger = logging.getLogger("axonewt-bridge")


@dataclass
class BridgeStatus:
    bridge_version: str = "0.1.0"
    started_at: str = ""
    triggers_sent: int = 0
    results_received: int = 0
    last_trigger: str = ""
    last_result: str = ""


class AxonewtBridge:
    """Axonewt 与外部 AI Agent 的桥接器"""

    def __init__(self, bridge_dir: Optional[str] = None, port: int = 9110):
        self.bridge_dir = Path(bridge_dir) if bridge_dir else BRIDGE_DIR
        self.bridge_dir.mkdir(parents=True, exist_ok=True)
        self.port = port
        self.status = BridgeStatus(
            started_at=datetime.now().isoformat()
        )
        self._server_thread: Optional[Thread] = None
        self._httpd: Optional[HTTPServer] = None

    # =========================================================================
    # 文件操作
    # =========================================================================

    def write_trigger(self, trigger_data: dict) -> str:
        """写入 trigger.json"""
        trigger_path = self.bridge_dir / "trigger.json"
        result_path = self.bridge_dir / "result.json"

        # 清理上一次的残留
        if result_path.exists():
            result_path.unlink()

        trigger_data["timestamp"] = datetime.now().isoformat()
        trigger_path.write_text(
            json.dumps(trigger_data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

        trigger_id = trigger_data.get("id", "unknown")
        self.status.triggers_sent += 1
        self.status.last_trigger = datetime.now().isoformat()
        self._save_status()

        logger.info(f"[Bridge] Trigger written: {trigger_id}")
        return trigger_id

    def read_trigger(self) -> Optional[dict]:
        """读取 trigger.json"""
        trigger_path = self.bridge_dir / "trigger.json"
        if not trigger_path.exists():
            return None
        try:
            return json.loads(trigger_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            return None

    def consume_trigger(self) -> Optional[dict]:
        """读取并删除 trigger.json"""
        trigger = self.read_trigger()
        if trigger:
            (self.bridge_dir / "trigger.json").unlink()
            logger.info(f"[Bridge] Trigger consumed: {trigger.get('id', 'unknown')}")
        return trigger

    def write_result(self, result_data: dict) -> str:
        """写入 result.json"""
        result_path = self.bridge_dir / "result.json"
        result_data["timestamp"] = datetime.now().isoformat()
        result_path.write_text(
            json.dumps(result_data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

        self.status.results_received += 1
        self.status.last_result = datetime.now().isoformat()
        self._save_status()

        logger.info(f"[Bridge] Result written: {result_data.get('id', 'unknown')}")
        return result_data.get("id", "unknown")

    def read_result(self) -> Optional[dict]:
        """读取 result.json"""
        result_path = self.bridge_dir / "result.json"
        if not result_path.exists():
            return None
        try:
            return json.loads(result_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            return None

    def consume_result(self) -> Optional[dict]:
        """读取并删除 result.json"""
        result = self.read_result()
        if result:
            (self.bridge_dir / "result.json").unlink()
            logger.info(f"[Bridge] Result consumed: {result.get('id', 'unknown')}")
        return result

    def has_pending_trigger(self) -> bool:
        return (self.bridge_dir / "trigger.json").exists()

    def has_pending_result(self) -> bool:
        return (self.bridge_dir / "result.json").exists()

    def wait_for_result(self, timeout: float = 300, poll_interval: float = 5) -> Optional[dict]:
        """阻塞等待 result.json（同步版）"""
        elapsed = 0
        while elapsed < timeout:
            result = self.read_result()
            if result:
                logger.info(f"[Bridge] Result received after {elapsed:.0f}s")
                return self.consume_result()
            time.sleep(poll_interval)
            elapsed += poll_interval
        logger.error(f"[Bridge] Timeout waiting for result ({timeout:.0f}s)")
        return None

    async def async_wait_for_result(self, timeout: float = 300, poll_interval: float = 5) -> Optional[dict]:
        """阻塞等待 result.json（异步版）"""
        elapsed = 0
        while elapsed < timeout:
            result = self.read_result()
            if result:
                logger.info(f"[Bridge] Result received after {elapsed:.0f}s")
                return self.consume_result()
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        logger.error(f"[Bridge] Timeout waiting for result ({timeout:.0f}s)")
        return None

    # =========================================================================
    # 状态
    # =========================================================================

    def _save_status(self):
        status_path = self.bridge_dir / "status.json"
        status_path.write_text(json.dumps(asdict(self.status), indent=2), encoding="utf-8")

    def get_status(self) -> dict:
        return asdict(self.status)

    def clear(self):
        for name in ["trigger.json", "result.json"]:
            path = self.bridge_dir / name
            if path.exists():
                path.unlink()
        logger.info("[Bridge] Cleared")

    # =========================================================================
    # HTTP 服务器（后台线程，不阻塞 asyncio 事件循环）
    # =========================================================================

    def start_http_server(self):
        """启动 HTTP 服务器（在后台线程中运行）"""
        bridge_ref = self

        class RequestHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                # 静默 HTTP 访问日志
                pass

            def _send_json(self, data: dict, status: int = 200):
                body = json.dumps(data, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _read_body(self) -> dict:
                length = int(self.headers.get("Content-Length", 0))
                if length:
                    return json.loads(self.rfile.read(length).decode("utf-8"))
                return {}

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                path = parsed.path

                if path == "/trigger":
                    trigger = bridge_ref.read_trigger()
                    if trigger:
                        self._send_json(trigger)
                    else:
                        self._send_json({"pending": False})

                elif path == "/result":
                    result = bridge_ref.read_result()
                    if result:
                        self._send_json(result)
                    else:
                        self._send_json({"pending": False})

                elif path == "/status":
                    self._send_json(bridge_ref.get_status())

                elif path == "/health":
                    self._send_json({"status": "ok", "version": "0.1.0"})

                else:
                    self._send_json({"error": "not_found"}, status=404)

            def do_POST(self):
                parsed = urllib.parse.urlparse(self.path)
                path = parsed.path

                if path == "/trigger":
                    try:
                        data = self._read_body()
                        trigger_id = bridge_ref.write_trigger(data)
                        self._send_json({"ok": True, "trigger_id": trigger_id})
                    except Exception as e:
                        self._send_json({"ok": False, "error": str(e)}, status=400)

                elif path == "/result":
                    try:
                        data = self._read_body()
                        result_id = bridge_ref.write_result(data)
                        self._send_json({"ok": True, "result_id": result_id})
                    except Exception as e:
                        self._send_json({"ok": False, "error": str(e)}, status=400)

                elif path == "/clear":
                    bridge_ref.clear()
                    self._send_json({"ok": True})

                else:
                    self._send_json({"error": "not_found"}, status=404)

        self._httpd = HTTPServer(("127.0.0.1", self.port), RequestHandler)
        self._server_thread = Thread(target=self._httpd.serve_forever, daemon=True)
        self._server_thread.start()
        logger.info(f"[Bridge] HTTP server started on http://127.0.0.1:{self.port}")

    def stop_http_server(self):
        """停止 HTTP 服务器"""
        if self._httpd:
            self._httpd.shutdown()
            self._httpd = None
            logger.info("[Bridge] HTTP server stopped")


# =============================================================================
# CLI
# =============================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Axonewt-Axiom Bridge")
    sub = parser.add_subparsers(dest="command")

    wt = sub.add_parser("write-trigger", help="写入测试 trigger")
    wt.add_argument("--id", default="TEST-001")
    wt.add_argument("--health", type=float, default=0.3)

    sub.add_parser("read-trigger", help="读取 trigger")

    wr = sub.add_parser("write-result", help="写入测试 result")
    wr.add_argument("--id", default="TEST-001")
    wr.add_argument("--status", default="success")

    sub.add_parser("read-result", help="读取 result")

    sub.add_parser("clear", help="清理")

    sub.add_parser("status", help="查看状态")

    srv = sub.add_parser("serve", help="启动 HTTP 服务")
    srv.add_argument("--port", type=int, default=9110)

    args = parser.parse_args()
    bridge = AxonewtBridge()

    if args.command == "write-trigger":
        trigger = {
            "id": args.id,
            "health_score": args.health,
            "severity": "P0" if args.health < 0.5 else "P1",
            "damage_type": "CODE_DECAY",
            "location": "test file",
            "symptoms": [f"Health score {args.health}"],
            "issues": []
        }
        tid = bridge.write_trigger(trigger)
        print(f"Written trigger: {tid}")

    elif args.command == "read-trigger":
        trigger = bridge.read_trigger()
        print(json.dumps(trigger, indent=2, ensure_ascii=False) if trigger else "No pending trigger")

    elif args.command == "write-result":
        result = {
            "id": args.id,
            "status": args.status,
            "summary": "Test fix",
            "steps": []
        }
        rid = bridge.write_result(result)
        print(f"Written result: {rid}")

    elif args.command == "read-result":
        result = bridge.read_result()
        print(json.dumps(result, indent=2, ensure_ascii=False) if result else "No pending result")

    elif args.command == "clear":
        bridge.clear()
        print("Cleared")

    elif args.command == "status":
        print(json.dumps(bridge.get_status(), indent=2))

    elif args.command == "serve":
        bridge.port = args.port
        bridge.start_http_server()
        print(f"Bridge server running on http://127.0.0.1:{args.port}")
        print("Endpoints: GET/POST /trigger, GET/POST /result, GET /status, POST /clear")
        print("Press Ctrl+C to stop")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            bridge.stop_http_server()
            print("\nStopped.")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
