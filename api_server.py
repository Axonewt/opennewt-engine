"""
OpenNewt Engine API Server — 一键启动

用法:
    python api_server.py                # 默认 127.0.0.1:5055
    python api_server.py --port 8080    # 自定义端口
    python api_server.py --reload       # 开发模式（文件变化自动重启）
"""

import sys
import argparse
from pathlib import Path

# 确保 project root 在 sys.path 中
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description="OpenNewt Engine API Server v0.3")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5055, help="Bind port (default: 5055)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev mode)")
    parser.add_argument("--workers", type=int, default=1, help="Number of workers")
    args = parser.parse_args()

    print("=" * 60)
    print("  OpenNewt Engine API Server v0.3")
    print("  Axonewt Neural Plasticity Engine")
    print("=" * 60)
    print(f"  Host: {args.host}")
    print(f"  Port: {args.port}")
    print(f"  Reload: {args.reload}")
    print()
    print("  API Docs: http://{}:{}/docs".format(args.host, args.port))
    print("  Health:   http://{}:{}/health".format(args.host, args.port))
    print()

    import uvicorn
    uvicorn.run(
        "src.api.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=args.workers,
        log_level="info",
    )


if __name__ == "__main__":
    main()
