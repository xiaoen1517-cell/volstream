"""Telegram Bot 推送。"""
import json
import os
import urllib.error
import urllib.request
from typing import Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


def send_message(text: str, chat_id: Optional[str] = None) -> bool:
    """向配置的 Telegram 会话发送纯文本消息。未配置 token/chat_id 时静默跳过。"""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    target = (chat_id or os.getenv("TELEGRAM_CHAT_ID", "")).strip()
    if not token or not target:
        logger.debug("未配置 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID，跳过推送")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps(
        {
            "chat_id": target,
            "text": text,
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if not body.get("ok"):
            logger.warning(f"Telegram 推送失败: {body}")
            return False
        return True
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        logger.warning(f"Telegram HTTP 错误 {e.code}: {err}")
        return False
    except Exception as e:
        logger.warning(f"Telegram 推送异常: {e}")
        return False
