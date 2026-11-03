"""Small MIT-licensed parser reused from qq-live-digest.
Copyright (c) 2026 wc985732-lang. See third_party/qq-live-digest-LICENSE.
Upstream 508526a719bcecc9e230f422ec826e6e8d8c92d1, receiver.py.
Only flatten_message/SEGMENT_LABEL are copied; no server or push code.
"""
from typing import Any
SEGMENT_LABEL = {
    "image": "[图片]",
    "face": "[表情]",
    "record": "[语音]",
    "video": "[视频]",
    "forward": "[合并转发]",
    "json": "[卡片消息]",
    "file": "[文件]",
    "mface": "[表情]",
    "dice": "[骰子]",
    "rps": "[猜拳]",
}

def flatten_message(message: Any) -> str:
    if isinstance(message, str):
        return message.strip()
    parts: list[str] = []
    for segment in message or []:
        if not isinstance(segment, dict):
            parts.append(str(segment))
            continue
        kind = str(segment.get("type") or "")
        data = segment.get("data") or {}
        if kind == "text":
            parts.append(str(data.get("text") or ""))
        elif kind == "at":
            name = data.get("name") or data.get("qq") or "某人"
            parts.append(f"@{name}")
        elif kind == "reply":
            continue
        elif kind == "file":
            name = str(data.get("file") or data.get("file_name") or "").strip()
            parts.append(f"[文件]{name}" if name else "[文件]")
        else:
            parts.append(SEGMENT_LABEL.get(kind, f"[{kind}]"))
    return "".join(parts).strip()
