"""用户反馈：点赞/点踩记录到本地 JSON Lines 文件。"""
from __future__ import annotations

import json
import time
from typing import List

from app.config import FEEDBACK_FILE


def record_feedback(question: str, answer: str, rating: int,
                    session_id: str = "", source: str = "") -> dict:
    """rating: +1 点赞 / -1 点踩。写入 outputs/feedback.jsonl。"""
    FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    item = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "session_id": session_id,
        "question": question,
        "answer": answer[:500],
        "rating": rating,
        "source": source,
    }
    with open(FEEDBACK_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
    return item


def load_feedback() -> List[dict]:
    if not FEEDBACK_FILE.exists():
        return []
    items = []
    with open(FEEDBACK_FILE, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def summary() -> dict:
    items = load_feedback()
    likes = sum(1 for i in items if i.get("rating") == 1)
    dislikes = sum(1 for i in items if i.get("rating") == -1)
    return {"total": len(items), "likes": likes, "dislikes": dislikes,
            "satisfaction": round(likes / len(items), 4) if items else None}
