import logging
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "auto_shorts.log"

formatter = logging.Formatter(
    "%(asctime)s %(levelname)s %(name)s %(message)s"
)

handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
handler.setFormatter(formatter)

logger = logging.getLogger("auto_shorts")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    logger.addHandler(handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)
