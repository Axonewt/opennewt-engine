"""
Agent Message Bus - Agent 消息总线
=====================================

基于 asyncio.Queue 的异步消息传递系统。
实现 OACP v0.1 协议的 Agent 间通信。

架构:
    Soma --[SIGNAL]--> MessageBus --[SIGNAL]--> Plasticus
    Plasticus --[BLUEPRINT]--> MessageBus --[BLUEPRINT]--> Effector
    Effector --[EXECUTION_REPORT]--> MessageBus --[REPORT]--> Mnemosyne

使用:
    bus = MessageBus()

    # 注册处理器
    bus.register("Plasticus-Dev", handle_signal)  # 处理 SIGNAL
    bus.register("Effector-Dev", handle_blueprint)  # 处理 BLUEPRINT

    # 发送消息
    await bus.send(signal_message)

    # 启动消息循环
    await bus.start()
"""

import asyncio
from typing import Dict, Callable, Awaitable, Optional
from dataclasses import dataclass
from datetime import datetime

from src.protocol.oacp import OACPMessage, MessageType


@dataclass
class BusStats:
    """消息总线统计"""
    total_sent: int = 0
    total_delivered: int = 0
    total_failed: int = 0
    pending: int = 0

    def to_dict(self) -> dict:
        return {
            "total_sent": self.total_sent,
            "total_delivered": self.total_delivered,
            "total_failed": self.total_failed,
            "pending": self.pending
        }


# 消息处理器类型
MessageHandler = Callable[[OACPMessage], Awaitable[Optional[OACPMessage]]]


class MessageBus:
    """
    Agent 消息总线

    每个 Agent 有独立的 asyncio.Queue 作为消息邮箱。
    Agent 注册处理器后，消息总线自动将消息路由到目标 Agent 的邮箱。
    """

    def __init__(self):
        # Agent 邮箱: {agent_name: asyncio.Queue}
        self._mailboxes: Dict[str, asyncio.Queue] = {}

        # 消息处理器: {agent_name: handler}
        self._handlers: Dict[str, MessageHandler] = {}

        # Agent 运行任务
        self._agent_tasks: Dict[str, asyncio.Task] = {}

        # 统计
        self._stats = BusStats()

        # 全局停止事件
        self._stop_event = asyncio.Event()

        # 消息历史（用于调试）
        self._message_log: list = []

    def register(self, agent_name: str, handler: MessageHandler):
        """
        注册 Agent 及其消息处理器

        Args:
            agent_name: Agent 名称（必须与 OACPMessage.target/source 匹配）
            handler: 异步消息处理函数，返回可选的响应消息
        """
        self._mailboxes[agent_name] = asyncio.Queue()
        self._handlers[agent_name] = handler
        print(f"[Bus] Registered: {agent_name}")

    async def send(self, message: OACPMessage) -> bool:
        """
        发送消息到目标 Agent

        Args:
            message: OACP 消息

        Returns:
            是否成功投递
        """
        target = message.target

        # 特殊处理: "All" 广播
        if target == "All":
            success = True
            for agent_name in self._mailboxes:
                if agent_name != message.source:
                    try:
                        await self._mailboxes[agent_name].put(message)
                        self._stats.total_sent += 1
                    except Exception:
                        success = False
                        self._stats.total_failed += 1
            return success

        # 点对点发送
        if target not in self._mailboxes:
            print(f"[Bus] WARNING: No mailbox for '{target}' (from '{message.source}')")
            self._stats.total_failed += 1
            return False

        try:
            await self._mailboxes[target].put(message)
            self._stats.total_sent += 1
            self._stats.total_delivered += 1

            # 记录日志
            self._message_log.append({
                "time": datetime.utcnow().isoformat() + "Z",
                "type": message.type.value,
                "from": message.source,
                "to": target,
                "msg_id": message.message_id
            })

            # 保持日志不超过 100 条
            if len(self._message_log) > 100:
                self._message_log = self._message_log[-50:]

            print(f"[Bus] {message.type.value}: {message.source} -> {target}")
            return True

        except Exception as e:
            print(f"[Bus] ERROR sending to {target}: {e}")
            self._stats.total_failed += 1
            return False

    async def _agent_loop(self, agent_name: str):
        """
        单个 Agent 的消息处理循环

        持续从邮箱读取消息，调用处理器，如果处理器返回消息则发送出去。
        """
        queue = self._mailboxes[agent_name]
        handler = self._handlers[agent_name]

        print(f"[Bus] {agent_name} listener started")

        while not self._stop_event.is_set():
            try:
                # 带超时的获取，避免无限阻塞
                message = await asyncio.wait_for(
                    queue.get(), timeout=1.0
                )

                try:
                    # 调用处理器
                    response = await handler(message)

                    # 如果处理器返回响应消息，自动发送
                    if response is not None:
                        await self.send(response)

                except Exception as e:
                    print(f"[Bus] ERROR in {agent_name} handler: {e}")
                    import traceback
                    traceback.print_exc()

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Bus] ERROR in {agent_name} loop: {e}")
                await asyncio.sleep(1)

        print(f"[Bus] {agent_name} listener stopped")

    async def start(self):
        """启动所有 Agent 的消息监听循环"""
        self._stop_event.clear()

        for agent_name in self._mailboxes:
            task = asyncio.create_task(
                self._agent_loop(agent_name),
                name=f"bus-{agent_name}"
            )
            self._agent_tasks[agent_name] = task

        print(f"[Bus] Started with {len(self._mailboxes)} agents")

    async def stop(self):
        """停止消息总线"""
        print("[Bus] Stopping...")
        self._stop_event.set()

        # 取消所有任务
        for task in self._agent_tasks.values():
            if not task.done():
                task.cancel()

        # 等待任务结束
        if self._agent_tasks:
            await asyncio.gather(
                *self._agent_tasks.values(),
                return_exceptions=True
            )

        self._agent_tasks.clear()
        print("[Bus] Stopped")

    @property
    def stats(self) -> BusStats:
        """获取总线统计"""
        self._stats.pending = sum(q.qsize() for q in self._mailboxes.values())
        return self._stats

    @property
    def message_log(self) -> list:
        """获取消息日志"""
        return self._message_log.copy()

    def has_pending(self) -> bool:
        """检查是否有待处理的消息"""
        return any(q.qsize() > 0 for q in self._mailboxes.values())
