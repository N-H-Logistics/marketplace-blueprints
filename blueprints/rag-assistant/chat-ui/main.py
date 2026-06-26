"""RAG Assistant Chat UI — a lightweight FastAPI app that proxies chat
messages to a DigitalOcean managed GenAI agent and serves a simple web
interface.

The app self-discovers the agent's deployment URL and API key at startup
using the DO API.

Environment variables (injected by terraform via App Platform):
    AGENT_UUID   — UUID of the managed agent
    DO_API_TOKEN — DigitalOcean API token
    AGENT_NAME   — Display name of the agent (optional)
"""

import logging
import json
import os
import sys
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("chat-ui")

app = FastAPI(title="RAG Assistant")

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

# Populated at startup.
AGENT_ENDPOINT = None
AGENT_API_KEY = None
TAIGA_PROJECT_CACHE = {}
TAIGA_METADATA_CACHE = {}

# Serve the static HTML chat page.
INDEX_HTML = (Path(__file__).parent / "static" / "index.html").read_text()


def _do_headers():
    return {"Authorization": f"Bearer {DO_API_TOKEN}", "Content-Type": "application/json"}


def _taiga_configured():
    return bool(TAIGA_BASE_URL and (TAIGA_AUTH_TOKEN or (TAIGA_USERNAME and TAIGA_PASSWORD)))


def _taiga_question(message):
    lowered = (message or "").lower()
    keywords = (
        "taiga",
        "ticket",
        "issue",
        "bug",
        "task",
        "user story",
        "story",
        "sprint",
        "backlog",
        "kanban",
        "lỗi",
        "pending",
        "hoàn tất",
        "chưa xử lý",
        "chưa hoàn tất",
        "chưa gán",
        "trạng thái",
        "công việc",
        "đầu việc",
    )
    return any(keyword in lowered for keyword in keywords)


async def _taiga_headers(client):
    base_headers = {"Content-Type": "application/json", "User-Agent": "Onflow-RAG-Assistant/1.0"}
    if TAIGA_AUTH_TOKEN:
        token = TAIGA_AUTH_TOKEN
    else:
        auth_resp = await client.post(
            f"{TAIGA_BASE_URL}/auth",
            headers=base_headers,
            json={"type": "normal", "username": TAIGA_USERNAME, "password": TAIGA_PASSWORD},
        )
        auth_resp.raise_for_status()
        token = auth_resp.json().get("auth_token")
        if not token:
            raise RuntimeError("Taiga auth did not return auth_token")

    return {**base_headers, "Authorization": f"Bearer {token}"}


async def _taiga_project_id(client, headers):
    if TAIGA_PROJECT_ID:
        return TAIGA_PROJECT_ID
    if not TAIGA_PROJECT_SLUG:
        return ""
    if TAIGA_PROJECT_SLUG in TAIGA_PROJECT_CACHE:
        return TAIGA_PROJECT_CACHE[TAIGA_PROJECT_SLUG]

    resp = await client.get(f"{TAIGA_BASE_URL}/projects/by_slug", headers=headers, params={"slug": TAIGA_PROJECT_SLUG})
    resp.raise_for_status()
    project_id = str(resp.json().get("id", ""))
    TAIGA_PROJECT_CACHE[TAIGA_PROJECT_SLUG] = project_id
    return project_id


def _matches_query(item, query):
    if not query:
        return True
    haystack = " ".join(
        str(item.get(key, ""))
        for key in ("subject", "ref", "description", "status_extra_info", "assigned_to_extra_info")
    ).lower()
    return query.lower() in haystack


def _taiga_search_term(query):
    lowered = (query or "").lower()
    business_terms = ("oms", "wms", "pvm", "spx", "tiktok", "shopee", "lazada", "pos")
    for term in business_terms:
        if term in lowered:
            return term.upper()

    words = [word.strip("#:,.!?()[]") for word in lowered.split()]
    refs = [word for word in words if word.isdigit() and len(word) >= 2]
    if refs:
        return refs[0]

    if 0 < len(words) <= 3 and not any(word in words for word in ("taiga", "task", "issue", "lỗi")):
        return query

    return ""


def _taiga_web_base():
    return TAIGA_BASE_URL.removesuffix("/api/v1").rstrip("/")


def _taiga_detail_url(kind, item):
    project = item.get("project_extra_info") or {}
    slug = project.get("slug") if isinstance(project, dict) else ""
    ref = item.get("ref")
    if not slug or not ref:
        return ""

    route = {"issue": "issue", "task": "task", "user_story": "us"}.get(kind)
    if not route:
        return ""
    return f"{_taiga_web_base()}/project/{slug}/{route}/{ref}"


def _brief_text(value, limit=180):
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _compact_taiga_option(item, label_keys=("name",)):
    label = ""
    for key in label_keys:
        if item.get(key):
            label = item[key]
            break
    return {"id": item.get("id"), "name": label or str(item.get("id", ""))}


def _compact_taiga_item(kind, item):
    status = item.get("status_extra_info") or {}
    assignee = item.get("assigned_to_extra_info") or {}
    return {
        "type": kind,
        "id": item.get("id"),
        "ref": item.get("ref"),
        "subject": item.get("subject", ""),
        "description": _brief_text(item.get("description")),
        "url": _taiga_detail_url(kind, item),
        "status": status.get("name") if isinstance(status, dict) else None,
        "assigned_to": assignee.get("full_name_display") if isinstance(assignee, dict) else None,
        "is_closed": item.get("is_closed"),
        "created_date": item.get("created_date"),
        "modified_date": item.get("modified_date"),
    }


async def _taiga_project_metadata():
    if not _taiga_configured():
        return {"configured": False}

    async with httpx.AsyncClient(timeout=30.0) as client:
        headers = await _taiga_headers(client)
        project_id = await _taiga_project_id(client, headers)
        if not project_id:
            return {"configured": False, "error": "TAIGA_PROJECT_ID hoặc TAIGA_PROJECT_SLUG chưa được cấu hình."}

        if project_id in TAIGA_METADATA_CACHE:
            return TAIGA_METADATA_CACHE[project_id]

        resp = await client.get(f"{TAIGA_BASE_URL}/projects/{project_id}", headers=headers)
        resp.raise_for_status()
        project = resp.json()
        metadata = {
            "configured": True,
            "project": {
                "id": project.get("id"),
                "name": project.get("name"),
                "slug": project.get("slug"),
            },
            "defaults": {
                "status": project.get("default_issue_status"),
                "priority": project.get("default_priority"),
                "severity": project.get("default_severity"),
                "type": project.get("default_issue_type"),
            },
            "statuses": [
                _compact_taiga_option(item)
                for item in project.get("issue_statuses", [])
                if not item.get("is_closed")
            ],
            "priorities": [_compact_taiga_option(item) for item in project.get("priorities", [])],
            "severities": [_compact_taiga_option(item) for item in project.get("severities", [])],
            "types": [_compact_taiga_option(item) for item in project.get("issue_types", [])],
            "members": [
                {
                    "id": item.get("id"),
                    "name": item.get("full_name_display") or item.get("full_name") or item.get("username") or str(item.get("id", "")),
                    "username": item.get("username"),
                }
                for item in project.get("members", [])
            ],
        }
        TAIGA_METADATA_CACHE[project_id] = metadata
        return metadata


def _first_option_id(options, default=None):
    if default:
        return default
    if options:
        return options[0].get("id")
    return None


async def _create_taiga_issue(payload):
    if not _taiga_configured():
        return {"configured": False, "error": "Taiga chưa được cấu hình cho trợ lý này."}

    subject = " ".join(str(payload.get("subject") or "").split())
    if not subject:
        return {"configured": True, "error": "Tiêu đề báo lỗi là bắt buộc."}
    if len(subject) > 500:
        return {"configured": True, "error": "Tiêu đề báo lỗi quá dài."}

    description = str(payload.get("description") or "").strip()
    metadata = await _taiga_project_metadata()
    if not metadata.get("configured"):
        return metadata

    defaults = metadata.get("defaults", {})
    options = {
        "status": metadata.get("statuses", []),
        "priority": metadata.get("priorities", []),
        "severity": metadata.get("severities", []),
        "type": metadata.get("types", []),
    }

    issue_payload = {
        "project": metadata["project"]["id"],
        "subject": subject,
        "description": description,
        "status": int(payload.get("status") or _first_option_id(options["status"], defaults.get("status"))),
        "priority": int(payload.get("priority") or _first_option_id(options["priority"], defaults.get("priority"))),
        "severity": int(payload.get("severity") or _first_option_id(options["severity"], defaults.get("severity"))),
        "type": int(payload.get("type") or _first_option_id(options["type"], defaults.get("type"))),
    }

    assigned_to = payload.get("assigned_to")
    if assigned_to:
        issue_payload["assigned_to"] = int(assigned_to)

    async with httpx.AsyncClient(timeout=30.0) as client:
        headers = await _taiga_headers(client)
        resp = await client.post(f"{TAIGA_BASE_URL}/issues", headers=headers, json=issue_payload)
        resp.raise_for_status()
        item = resp.json()
        if not item.get("project_extra_info"):
            item["project_extra_info"] = {"slug": metadata["project"].get("slug"), "id": metadata["project"].get("id")}

    return {"configured": True, "issue": _compact_taiga_item("issue", item)}


async def _search_taiga(query="", limit=TAIGA_MAX_RESULTS):
    if not _taiga_configured():
        return {"configured": False, "items": []}

    async with httpx.AsyncClient(timeout=30.0) as client:
        headers = await _taiga_headers(client)
        project_id = await _taiga_project_id(client, headers)
        if not project_id:
            return {"configured": False, "error": "TAIGA_PROJECT_ID hoặc TAIGA_PROJECT_SLUG chưa được cấu hình.", "items": []}

        search_term = _taiga_search_term(query)
        endpoints = (("issue", "issues"), ("task", "tasks"), ("user_story", "userstories"))
        items = []
        page_size = min(max(limit, 1), 100)
        for kind, endpoint in endpoints:
            page = 1
            endpoint_items = 0
            while endpoint_items < limit:
                params = {"project": project_id, "order_by": "-modified_date", "page": page, "page_size": page_size}
                if search_term:
                    params["q"] = search_term
                resp = await client.get(
                    f"{TAIGA_BASE_URL}/{endpoint}",
                    headers=headers,
                    params=params,
                )
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, list) or not data:
                    break
                for item in data:
                    if _matches_query(item, search_term):
                        items.append(_compact_taiga_item(kind, item))
                        endpoint_items += 1
                        if endpoint_items >= limit:
                            break
                if len(data) < page_size:
                    break
                page += 1

        items.sort(key=lambda item: item.get("modified_date") or item.get("created_date") or "", reverse=True)
        return {"configured": True, "project_id": project_id, "items": items[:limit]}


def _filter_taiga_items_for_question(message, items):
    lowered = (message or "").lower()
    filtered = list(items)

    if any(word in lowered for word in ("issue", "bug", "lỗi")):
        filtered = [item for item in filtered if item.get("type") == "issue"]
    elif "story" in lowered:
        filtered = [item for item in filtered if item.get("type") == "user_story"]

    if any(word in lowered for word in ("chưa xử lý", "pending", "chưa hoàn tất", "đang mở", "open")):
        filtered = [item for item in filtered if not item.get("is_closed")]

    return filtered


def _format_taiga_item_line(item):
    ref = f"#{item['ref']}" if item.get("ref") else f"id {item.get('id')}"
    status = item.get("status") or "chưa rõ trạng thái"
    assignee = item.get("assigned_to") or "chưa gán"
    closed = "đã đóng" if item.get("is_closed") else "đang mở"
    url = item.get("url") or ""
    line = f"- {item['type']} {ref}: {item.get('subject', '')} | {status} | {assignee} | {closed}"
    if url:
        line += f" | {url}"
    if item.get("description"):
        line += f"\n  Chi tiết: {item['description']}"
    return line


def _format_taiga_direct_answer(message, result):
    if not result.get("configured"):
        return "Taiga chưa được cấu hình cho trợ lý này."

    items = _filter_taiga_items_for_question(message, result.get("items", []))
    lowered = (message or "").lower()
    if not items:
        return "Không tìm thấy dữ liệu Taiga phù hợp với câu hỏi này."

    if any(word in lowered for word in ("bao nhiêu", "số lượng", "count", "mấy")):
        open_count = sum(1 for item in items if not item.get("is_closed"))
        closed_count = len(items) - open_count
        return f"Trong dữ liệu Taiga tìm được có {len(items)} mục phù hợp: {open_count} đang mở/chưa hoàn tất và {closed_count} đã đóng."

    title = "Các mục Taiga phù hợp gần đây:"
    if any(word in lowered for word in ("mới cập nhật", "gần đây", "recent")):
        title = "Các mục Taiga mới cập nhật gần đây:"
    elif any(word in lowered for word in ("pending", "chưa xử lý", "chưa hoàn tất")):
        title = "Các mục Taiga đang mở/chưa hoàn tất:"

    lines = [title]
    lines.extend(_format_taiga_item_line(item) for item in items[:8])
    if len(items) > 8:
        lines.append(f"Còn {len(items) - 8} mục khác.")
    return "\n".join(lines)


async def _answer_taiga_question(message):
    result = await _search_taiga(message, 300)
    return _format_taiga_direct_answer(message, result)


def _format_taiga_context(items):
    if not items:
        return ""

    lines = ["Dữ liệu realtime từ Taiga:"]
    for item in items:
        ref = f"#{item['ref']}" if item.get("ref") else f"id {item.get('id')}"
        status = item.get("status") or "chưa rõ trạng thái"
        assignee = item.get("assigned_to") or "chưa gán người phụ trách"
        closed = "đã đóng" if item.get("is_closed") else "đang mở"
        lines.append(f"- {item['type']} {ref}: {item.get('subject', '')} | {status} | {assignee} | {closed}")
    return "\n".join(lines)


def _discover_agent():
    """Fetch agent details from the DO API to get the deployment URL and API key."""
    global AGENT_ENDPOINT, AGENT_API_KEY

    logger.info("Discovering agent %s ...", AGENT_UUID)
    with httpx.Client(timeout=30.0) as client:
        # Get agent details.
        resp = client.get(f"{DO_API_BASE}/v2/gen-ai/agents/{AGENT_UUID}", headers=_do_headers())
        resp.raise_for_status()
        agent = resp.json()["agent"]

        # Extract deployment URL.
        deployment = agent.get("deployment", {})
        deploy_url = deployment.get("url")
        if deploy_url:
            AGENT_ENDPOINT = f"{deploy_url}/api/v1/chat/completions"
            logger.info("Agent endpoint: %s", AGENT_ENDPOINT)
        else:
            logger.error("Agent has no deployment URL. Status: %s", deployment.get("status"))
            raise RuntimeError("Agent deployment URL not available")

        # Create an API key for agent authentication.
        # The auto-generated api_keys[].api_key is a chatbot identifier, not a secret key.
        # We need to create a real API key via the API.
        logger.info("Creating agent API key...")
        key_resp = client.post(
            f"{DO_API_BASE}/v2/gen-ai/agents/{AGENT_UUID}/api_keys",
            headers=_do_headers(),
            json={"name": "chat-ui"},
        )
        key_resp.raise_for_status()
        AGENT_API_KEY = key_resp.json()["api_key_info"]["secret_key"]
        logger.info("Agent API key created")


def _pick_datasource_label(source):
    file_source = source.get("file_upload_data_source") or {}
    if file_source:
        return {
            "type": "file",
            "name": file_source.get("original_file_name") or file_source.get("stored_object_key") or "Uploaded file",
            "size_bytes": int(file_source.get("size_in_bytes") or 0),
        }

    web_source = source.get("web_crawler_data_source") or {}
    if web_source:
        return {
            "type": "web",
            "name": web_source.get("base_url") or "Web crawler source",
            "size_bytes": None,
        }

    return {"type": "source", "name": source.get("uuid", "Knowledge source"), "size_bytes": None}


@app.on_event("startup")
async def startup_event():
    _discover_agent()


@app.get("/", response_class=HTMLResponse)
async def index():
    """Serve the chat UI."""
    return INDEX_HTML.replace("{{AGENT_NAME}}", AGENT_NAME)


@app.get("/health")
async def health():
    return {"status": "ok", "agent_ready": AGENT_ENDPOINT is not None}


@app.get("/api/taiga/search")
async def taiga_search(q: str = "", limit: int = TAIGA_MAX_RESULTS):
    """Search Taiga issues, tasks, and user stories through the backend."""
    try:
        return await _search_taiga(q, max(1, min(limit, 50)))
    except httpx.HTTPStatusError as exc:
        logger.exception("Taiga search failed")
        return JSONResponse(status_code=exc.response.status_code, content={"error": exc.response.text})
    except (httpx.RequestError, RuntimeError) as exc:
        logger.exception("Taiga search failed")
        return JSONResponse(status_code=502, content={"error": f"Không lấy được dữ liệu Taiga: {exc}"})


@app.get("/api/taiga/metadata")
async def taiga_metadata():
    """Return Taiga project metadata for creating issues."""
    try:
        data = await _taiga_project_metadata()
        if not data.get("configured"):
            return JSONResponse(status_code=503, content=data)
        return data
    except httpx.HTTPStatusError as exc:
        logger.exception("Taiga metadata request failed")
        return JSONResponse(status_code=exc.response.status_code, content={"error": exc.response.text})
    except (httpx.RequestError, RuntimeError, ValueError) as exc:
        logger.exception("Taiga metadata request failed")
        return JSONResponse(status_code=502, content={"error": f"Không lấy được cấu hình Taiga: {exc}"})


@app.post("/api/taiga/issues")
async def create_taiga_issue(request: Request):
    """Create a Taiga issue after the user confirms the issue form."""
    try:
        payload = await request.json()
        data = await _create_taiga_issue(payload)
        if data.get("error"):
            return JSONResponse(status_code=400 if data.get("configured") else 503, content=data)
        return data
    except httpx.HTTPStatusError as exc:
        logger.exception("Taiga issue creation failed")
        return JSONResponse(status_code=exc.response.status_code, content={"error": exc.response.text})
    except (httpx.RequestError, RuntimeError, ValueError) as exc:
        logger.exception("Taiga issue creation failed")
        return JSONResponse(status_code=502, content={"error": f"Không tạo được báo lỗi Taiga: {exc}"})


@app.get("/api/knowledge-bases")
async def knowledge_bases():
    """Return attached knowledge base metadata and data sources for the UI."""
    headers = _do_headers()

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            agent_resp = await client.get(f"{DO_API_BASE}/v2/gen-ai/agents/{AGENT_UUID}", headers=headers)
            agent_resp.raise_for_status()
            agent = agent_resp.json().get("agent", {})
            attached_kbs = agent.get("knowledge_bases") or []

            result = []
            for kb in attached_kbs:
                kb_uuid = kb.get("uuid")
                if not kb_uuid:
                    continue

                sources_resp = await client.get(
                    f"{DO_API_BASE}/v2/gen-ai/knowledge_bases/{kb_uuid}/data_sources",
                    headers=headers,
                    params={"page": 1, "per_page": 200},
                )
                sources = []
                if sources_resp.status_code < 400:
                    sources_data = sources_resp.json()
                    if isinstance(sources_data, dict):
                        raw_sources = sources_data.get("knowledge_base_data_sources") or sources_data.get("data_sources")
                    else:
                        raw_sources = sources_data
                    if isinstance(raw_sources, list):
                        for source in raw_sources:
                            label = _pick_datasource_label(source)
                            sources.append(
                                {
                                    "uuid": source.get("uuid"),
                                    "created_at": source.get("created_at"),
                                    "updated_at": source.get("updated_at"),
                                    **label,
                                }
                            )
                else:
                    logger.warning("Could not fetch data sources for KB %s: %s", kb_uuid, sources_resp.text)

                indexing_job = kb.get("last_indexing_job") or {}
                result.append(
                    {
                        "uuid": kb_uuid,
                        "name": kb.get("name", "Knowledge Base"),
                        "region": kb.get("region"),
                        "updated_at": kb.get("updated_at"),
                        "indexing_status": indexing_job.get("status"),
                        "indexing_phase": indexing_job.get("phase"),
                        "tokens": indexing_job.get("tokens"),
                        "datasources": sources,
                    }
                )

    except httpx.HTTPStatusError as exc:
        logger.exception("Knowledge base metadata request failed")
        return JSONResponse(status_code=exc.response.status_code, content={"error": exc.response.text})
    except httpx.RequestError as exc:
        logger.exception("Knowledge base metadata request failed")
        return JSONResponse(status_code=502, content={"error": f"Không lấy được Knowledge Base: {exc}"})

    return {"knowledge_bases": result}


async def _build_chat_messages(message, history):
    messages = []
    for h in history:
        messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})

    if _taiga_question(message):
        try:
            taiga_result = await _search_taiga(message, TAIGA_MAX_RESULTS)
            taiga_context = _format_taiga_context(taiga_result.get("items", []))
            if taiga_context:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "Nếu câu hỏi liên quan Taiga, hãy dùng dữ liệu realtime dưới đây. "
                            "Trả lời ngắn gọn bằng tiếng Việt, không tự bịa thêm trạng thái.\n\n"
                            f"{taiga_context}"
                        ),
                    }
                )
        except Exception:
            logger.exception("Could not enrich chat with Taiga context")

    messages.append({"role": "user", "content": message})
    return messages


@app.post("/api/chat")
async def chat(request: Request):
    """Proxy a chat message to the managed agent and return the response."""
    if not AGENT_ENDPOINT or not AGENT_API_KEY:
        return JSONResponse(status_code=503, content={"error": "Agent not ready"})

    body = await request.json()
    message = body.get("message", "")
    history = body.get("history", [])

    if _taiga_question(message):
        try:
            content = await _answer_taiga_question(message)
            return JSONResponse(content={"content": content, "usage": None})
        except Exception as exc:
            logger.exception("Taiga direct answer failed")
            return JSONResponse(status_code=502, content={"error": f"Không lấy được dữ liệu Taiga: {exc}"})

    messages = await _build_chat_messages(message, history)

    headers = {
        "Authorization": f"Bearer {AGENT_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(AGENT_ENDPOINT, json={"messages": messages}, headers=headers)
    except httpx.TimeoutException:
        return JSONResponse(
            status_code=504,
            content={"error": "Agent phan hoi qua cham. Vui long thu lai sau it phut."},
        )
    except httpx.RequestError as exc:
        logger.exception("Agent request failed")
        return JSONResponse(status_code=502, content={"error": f"Khong goi duoc agent: {exc}"})

    try:
        data = resp.json()
    except Exception:
        return JSONResponse(status_code=resp.status_code, content={"error": resp.text})

    if resp.status_code >= 400:
        error = data.get("error") or data.get("detail") or data.get("message") or resp.text
        if isinstance(error, dict):
            error = error.get("message") or str(error)
        if resp.status_code == 429:
            error = "Agent dang bi gioi han tan suat. Vui long doi mot luc roi thu lai."
        return JSONResponse(status_code=resp.status_code, content={"error": error})

    # Extract the response text from OpenAI-compatible format.
    content = ""
    if "choices" in data and len(data["choices"]) > 0:
        content = data["choices"][0].get("message", {}).get("content", "")
    elif "detail" in data:
        content = f"Error: {data['detail']}"
    elif "message" in data:
        content = data["message"]

    return JSONResponse(content={"content": content, "usage": data.get("usage")})


@app.post("/api/chat/stream")
async def chat_stream(request: Request):
    """Stream a chat response from the managed agent as plain text chunks."""
    if not AGENT_ENDPOINT or not AGENT_API_KEY:
        return JSONResponse(status_code=503, content={"error": "Agent not ready"})

    body = await request.json()
    message = body.get("message", "")
    history = body.get("history", [])

    if _taiga_question(message):
        async def generate_taiga():
            try:
                yield await _answer_taiga_question(message)
            except Exception as exc:
                logger.exception("Taiga direct stream answer failed")
                yield f"Không lấy được dữ liệu Taiga: {exc}"

        return StreamingResponse(generate_taiga(), media_type="text/plain; charset=utf-8")

    messages = await _build_chat_messages(message, history)

    headers = {
        "Authorization": f"Bearer {AGENT_API_KEY}",
        "Content-Type": "application/json",
    }

    async def generate():
        try:
            timeout = httpx.Timeout(120.0, read=120.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    AGENT_ENDPOINT,
                    json={"messages": messages, "stream": True},
                    headers=headers,
                ) as resp:
                    if resp.status_code >= 400:
                        text = await resp.aread()
                        try:
                            data = json.loads(text.decode("utf-8"))
                            error = data.get("error") or data.get("detail") or data.get("message") or text.decode("utf-8")
                            if isinstance(error, dict):
                                error = error.get("message") or str(error)
                        except Exception:
                            error = text.decode("utf-8", errors="ignore")
                        if resp.status_code == 429:
                            error = "Agent đang bị giới hạn tần suất. Vui lòng đợi một lúc rồi thử lại."
                        yield error
                        return

                    streamed_any = False
                    buffered = ""
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        if line.startswith("data:"):
                            line = line[5:].strip()
                        if line == "[DONE]":
                            return
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            buffered += line
                            continue

                        if "choices" in data and data["choices"]:
                            choice = data["choices"][0]
                            delta = choice.get("delta", {})
                            chunk = delta.get("content") or choice.get("message", {}).get("content") or ""
                            if chunk:
                                streamed_any = True
                                yield chunk
                        elif "message" in data:
                            streamed_any = True
                            yield data["message"]
                        elif "detail" in data:
                            yield str(data["detail"])
                            return

                    if not streamed_any and buffered:
                        yield buffered
        except httpx.TimeoutException:
            yield "Agent phản hồi quá chậm. Vui lòng thử lại sau ít phút."
        except httpx.RequestError as exc:
            logger.exception("Agent stream request failed")
            yield f"Không gọi được agent: {exc}"

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")
