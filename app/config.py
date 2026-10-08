import os
from pathlib import Path

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./certs.db")
STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "./storage"))
MAX_RECIPIENTS_PER_JOB = int(os.getenv("MAX_RECIPIENTS_PER_JOB", "1000"))
