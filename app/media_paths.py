from pathlib import Path

MEDIA_ROOT = Path(__file__).resolve().parent / "media"
AVATARS_DIR = MEDIA_ROOT / "avatars"
SECURITY_LOG_PATH = MEDIA_ROOT / "security.log"

AVATARS_DIR.mkdir(parents=True, exist_ok=True)
