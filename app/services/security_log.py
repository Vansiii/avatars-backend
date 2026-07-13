import json
import uuid
from datetime import datetime, timezone

from app.media_paths import SECURITY_LOG_PATH


def log_nsfw_rejection(user_id: uuid.UUID, input_type: str, reason: str) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": str(user_id),
        "input_type": input_type,
        "reason": reason,
    }
    with SECURITY_LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
