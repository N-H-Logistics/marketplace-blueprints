import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
INDEX_HTML = (BASE_DIR / "static" / "index.html").read_text()

AGENT_UUID = os.environ["AGENT_UUID"]
DO_API_TOKEN = os.environ["DO_API_TOKEN"]
AGENT_NAME = os.environ.get("AGENT_NAME", "RAG Assistant")
DO_API_BASE = os.environ.get("DO_API_BASE", "https://api.digitalocean.com")

TAIGA_BASE_URL = os.environ.get("TAIGA_BASE_URL", "").rstrip("/")
TAIGA_USERNAME = os.environ.get("TAIGA_USERNAME", "")
TAIGA_PASSWORD = os.environ.get("TAIGA_PASSWORD", "")
TAIGA_AUTH_TOKEN = os.environ.get("TAIGA_AUTH_TOKEN", "")
TAIGA_PROJECT_ID = os.environ.get("TAIGA_PROJECT_ID", "")
TAIGA_PROJECT_SLUG = os.environ.get("TAIGA_PROJECT_SLUG", "")
TAIGA_MAX_RESULTS = int(os.environ.get("TAIGA_MAX_RESULTS", "12"))

KB_UPLOAD_MAX_BYTES = int(os.environ.get("KB_UPLOAD_MAX_BYTES", str(25 * 1024 * 1024)))
KB_UPLOAD_EXTENSIONS = {
    extension.strip().lower()
    for extension in os.environ.get(
        "KB_UPLOAD_EXTENSIONS",
        ".pdf,.txt,.md,.markdown,.html,.csv,.docx",
    ).split(",")
    if extension.strip()
}


def do_headers():
    return {"Authorization": f"Bearer {DO_API_TOKEN}", "Content-Type": "application/json"}
