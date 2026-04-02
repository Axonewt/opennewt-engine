# Axonewt ↔ Axiom Bridge 协议

## 通信方式

Axonewt 引擎与外部 AI Agent（Axiom/WorkBuddy）通过 `bridge/` 目录下的 JSON 文件通信。

## 文件约定

### trigger.json（Axonewt 写，Axiom 读）

Axonewt 检测到故障后写入此文件。Axiom 读到后执行修复，完成后删除此文件。

```json
{
  "id": "TICK-001-20260402020100",
  "timestamp": "2026-04-02T02:01:00+08:00",
  "health_score": 0.45,
  "severity": "P0",
  "damage_type": "CODE_DECAY",
  "location": "src/agents/soma_dev.py",
  "symptoms": [
    "Health score dropped below 0.5",
    "2 files with syntax errors detected"
  ],
  "issues": [
    {
      "file": "src/agents/soma_dev.py",
      "line": 42,
      "type": "syntax_error",
      "message": "unexpected EOF while parsing"
    }
  ],
  "context": {
    "project_path": "D:\\opennewt-engine",
    "recent_changes": ["chaos_agent injected at 01:55"],
    "immune_memory_hits": []
  }
}
```

### result.json（Axiom 写，Axonewt 读）

Axiom 完成修复后写入此文件。Axonewt 读到后将修复方案转成 BLUEPRINT 交给 Effector 执行。

```json
{
  "id": "TICK-001-20260402020100",
  "trigger_id": "TICK-001-20260402020100",
  "timestamp": "2026-04-02T02:03:15+08:00",
  "status": "success",
  "summary": "Fixed syntax error in soma_dev.py by restoring missing closing parenthesis",
  "steps": [
    {
      "number": 1,
      "action": "file_edit",
      "file_path": "src/agents/soma_dev.py",
      "description": "Restore closing parenthesis on line 42",
      "content": "    return HealthReport(health_score=score, ...)"
    }
  ],
  "confidence": 0.95,
  "time_spent_seconds": 135
}
```

### status.json（Bridge 服务维护）

Bridge HTTP 服务维护的运行状态，供调试用。

```json
{
  "bridge_version": "0.1.0",
  "started_at": "2026-04-02T02:00:00+08:00",
  "triggers_sent": 3,
  "results_received": 2,
  "last_trigger": "2026-04-02T02:05:00+08:00",
  "last_result": "2026-04-02T02:06:30+08:00"
}
```

## 流程

```
1. Axonewt tick → Soma 检测故障
2. 如果 bridge 模式启用：
   a. 写 trigger.json 到 bridge/
   b. 向 bridge HTTP (localhost:9110) POST /trigger 发通知
   c. 等待 result.json 出现（轮询，最长 5 分钟）
   d. 读 result.json → 转成 BLUEPRINT → 发给 Effector
3. Axonewt 验证修复 → Mnemosyne 记录

4. WorkBuddy Automation 定时触发：
   a. 检查 bridge/trigger.json 是否存在
   b. 如果存在：读取故障报告 → 修复代码 → 写 result.json → 删除 trigger.json
   c. 如果不存在：无事可做，退出
```

## 超时处理

- trigger.json 写入后 5 分钟内没有 result.json → 标记为超时
- 超时后 Axonewt 回退到本地 LLM 方案（如果有 Ollama）或跳过本轮
