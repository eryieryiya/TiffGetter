"""TG_EVENT 结构化运行事件输出。"""
import json
import threading
from typing import Optional

EVENT_PREFIX = 'TG_EVENT '
_lock = threading.Lock()


def emit(event: dict) -> None:
    """线程安全地输出一行 TG_EVENT JSON。"""
    with _lock:
        print(EVENT_PREFIX + json.dumps(event, ensure_ascii=False, default=str),
              flush=True)


def parse(line: str) -> Optional[dict]:
    """解析一行 TG_EVENT；非事件行返回 None。"""
    if not line.startswith(EVENT_PREFIX):
        return None
    return json.loads(line[len(EVENT_PREFIX):])
