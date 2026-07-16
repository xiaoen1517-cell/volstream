import os
from pathlib import Path
from typing import Any, Dict, List

import yaml
from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).parent.parent
CONFIG_PATH = ROOT_DIR / "config.yaml"


def load_config(path: Path = CONFIG_PATH) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_db_url() -> str:
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    user = os.getenv("DB_USER", "crypto")
    password = os.getenv("DB_PASSWORD", "crypto123")
    db = os.getenv("DB_NAME", "volstream")
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"


CONFIG = load_config()

__all__ = ["CONFIG", "get_db_url", "ROOT_DIR"]
