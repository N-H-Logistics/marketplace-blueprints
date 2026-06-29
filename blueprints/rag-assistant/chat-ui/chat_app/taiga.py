import httpx

from . import config


PROJECT_CACHE = {}
METADATA_CACHE = {}


def configured():
    return bool(config.TAIGA_BASE_URL and (config.TAIGA_AUTH_TOKEN or (config.TAIGA_USERNAME and config.TAIGA_PASSWORD)))


def is_taiga_question(message):
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


async def headers(client):
    base_headers = {"Content-Type": "application/json", "User-Agent": "Onflow-RAG-Assistant/1.0"}
    if config.TAIGA_AUTH_TOKEN:
        token = config.TAIGA_AUTH_TOKEN
    else:
        auth_resp = await client.post(
            f"{config.TAIGA_BASE_URL}/auth",
            headers=base_headers,
            json={"type": "normal", "username": config.TAIGA_USERNAME, "password": config.TAIGA_PASSWORD},
        )
        auth_resp.raise_for_status()
        token = auth_resp.json().get("auth_token")
        if not token:
            raise RuntimeError("Taiga auth did not return auth_token")

    return {**base_headers, "Authorization": f"Bearer {token}"}


async def project_id(client, request_headers):
    if config.TAIGA_PROJECT_ID:
        return config.TAIGA_PROJECT_ID
    if not config.TAIGA_PROJECT_SLUG:
        return ""
    if config.TAIGA_PROJECT_SLUG in PROJECT_CACHE:
        return PROJECT_CACHE[config.TAIGA_PROJECT_SLUG]

    resp = await client.get(
        f"{config.TAIGA_BASE_URL}/projects/by_slug",
        headers=request_headers,
        params={"slug": config.TAIGA_PROJECT_SLUG},
    )
    resp.raise_for_status()
    resolved_project_id = str(resp.json().get("id", ""))
    PROJECT_CACHE[config.TAIGA_PROJECT_SLUG] = resolved_project_id
    return resolved_project_id


def _matches_query(item, query):
    if not query:
        return True
    haystack = " ".join(
        str(item.get(key, ""))
        for key in ("subject", "ref", "description", "status_extra_info", "assigned_to_extra_info")
    ).lower()
    return query.lower() in haystack


def _search_term(query):
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


def web_base():
    return config.TAIGA_BASE_URL.removesuffix("/api/v1").rstrip("/")


def detail_url(kind, item):
    project = item.get("project_extra_info") or {}
    slug = project.get("slug") if isinstance(project, dict) else ""
    ref = item.get("ref")
    if not slug or not ref:
        return ""

    route = {"issue": "issue", "task": "task", "user_story": "us"}.get(kind)
    if not route:
        return ""
    return f"{web_base()}/project/{slug}/{route}/{ref}"


def brief_text(value, limit=180):
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def compact_option(item, label_keys=("name",)):
    label = ""
    for key in label_keys:
        if item.get(key):
            label = item[key]
            break
    return {"id": item.get("id"), "name": label or str(item.get("id", ""))}


def compact_item(kind, item):
    status = item.get("status_extra_info") or {}
    assignee = item.get("assigned_to_extra_info") or {}
    return {
        "type": kind,
        "id": item.get("id"),
        "ref": item.get("ref"),
        "subject": item.get("subject", ""),
        "description": brief_text(item.get("description")),
        "url": detail_url(kind, item),
        "status": status.get("name") if isinstance(status, dict) else None,
        "assigned_to": assignee.get("full_name_display") if isinstance(assignee, dict) else None,
        "is_closed": item.get("is_closed"),
        "created_date": item.get("created_date"),
        "modified_date": item.get("modified_date"),
    }


async def project_metadata():
    if not configured():
        return {"configured": False}

    async with httpx.AsyncClient(timeout=30.0) as client:
        request_headers = await headers(client)
        resolved_project_id = await project_id(client, request_headers)
        if not resolved_project_id:
            return {"configured": False, "error": "TAIGA_PROJECT_ID hoặc TAIGA_PROJECT_SLUG chưa được cấu hình."}

        if resolved_project_id in METADATA_CACHE:
            return METADATA_CACHE[resolved_project_id]

        resp = await client.get(f"{config.TAIGA_BASE_URL}/projects/{resolved_project_id}", headers=request_headers)
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
                compact_option(item)
                for item in project.get("issue_statuses", [])
                if not item.get("is_closed")
            ],
            "priorities": [compact_option(item) for item in project.get("priorities", [])],
            "severities": [compact_option(item) for item in project.get("severities", [])],
            "types": [compact_option(item) for item in project.get("issue_types", [])],
            "members": [
                {
                    "id": item.get("id"),
                    "name": item.get("full_name_display") or item.get("full_name") or item.get("username") or str(item.get("id", "")),
                    "username": item.get("username"),
                }
                for item in project.get("members", [])
            ],
        }
        METADATA_CACHE[resolved_project_id] = metadata
        return metadata


def _first_option_id(options, default=None):
    if default:
        return default
    if options:
        return options[0].get("id")
    return None


async def create_issue(payload):
    if not configured():
        return {"configured": False, "error": "Taiga chưa được cấu hình cho trợ lý này."}

    subject = " ".join(str(payload.get("subject") or "").split())
    if not subject:
        return {"configured": True, "error": "Tiêu đề báo lỗi là bắt buộc."}
    if len(subject) > 500:
        return {"configured": True, "error": "Tiêu đề báo lỗi quá dài."}

    metadata = await project_metadata()
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
        "description": str(payload.get("description") or "").strip(),
        "status": int(payload.get("status") or _first_option_id(options["status"], defaults.get("status"))),
        "priority": int(payload.get("priority") or _first_option_id(options["priority"], defaults.get("priority"))),
        "severity": int(payload.get("severity") or _first_option_id(options["severity"], defaults.get("severity"))),
        "type": int(payload.get("type") or _first_option_id(options["type"], defaults.get("type"))),
    }

    assigned_to = payload.get("assigned_to")
    if assigned_to:
        issue_payload["assigned_to"] = int(assigned_to)

    async with httpx.AsyncClient(timeout=30.0) as client:
        request_headers = await headers(client)
        resp = await client.post(f"{config.TAIGA_BASE_URL}/issues", headers=request_headers, json=issue_payload)
        resp.raise_for_status()
        item = resp.json()
        if not item.get("project_extra_info"):
            item["project_extra_info"] = {"slug": metadata["project"].get("slug"), "id": metadata["project"].get("id")}

    return {"configured": True, "issue": compact_item("issue", item)}


async def search(query="", limit=config.TAIGA_MAX_RESULTS):
    if not configured():
        return {"configured": False, "items": []}

    async with httpx.AsyncClient(timeout=30.0) as client:
        request_headers = await headers(client)
        resolved_project_id = await project_id(client, request_headers)
        if not resolved_project_id:
            return {"configured": False, "error": "TAIGA_PROJECT_ID hoặc TAIGA_PROJECT_SLUG chưa được cấu hình.", "items": []}

        search_term = _search_term(query)
        endpoints = (("issue", "issues"), ("task", "tasks"), ("user_story", "userstories"))
        items = []
        page_size = min(max(limit, 1), 100)
        for kind, endpoint in endpoints:
            page = 1
            endpoint_items = 0
            while endpoint_items < limit:
                params = {"project": resolved_project_id, "order_by": "-modified_date", "page": page, "page_size": page_size}
                if search_term:
                    params["q"] = search_term
                resp = await client.get(f"{config.TAIGA_BASE_URL}/{endpoint}", headers=request_headers, params=params)
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, list) or not data:
                    break
                for item in data:
                    if _matches_query(item, search_term):
                        items.append(compact_item(kind, item))
                        endpoint_items += 1
                        if endpoint_items >= limit:
                            break
                if len(data) < page_size:
                    break
                page += 1

        items.sort(key=lambda item: item.get("modified_date") or item.get("created_date") or "", reverse=True)
        return {"configured": True, "project_id": resolved_project_id, "items": items[:limit]}


def filter_items_for_question(message, items):
    lowered = (message or "").lower()
    filtered = list(items)

    if any(word in lowered for word in ("issue", "bug", "lỗi")):
        filtered = [item for item in filtered if item.get("type") == "issue"]
    elif "story" in lowered:
        filtered = [item for item in filtered if item.get("type") == "user_story"]

    if any(word in lowered for word in ("chưa xử lý", "pending", "chưa hoàn tất", "đang mở", "open")):
        filtered = [item for item in filtered if not item.get("is_closed")]

    return filtered


def format_item_line(item):
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


def format_direct_answer(message, result):
    if not result.get("configured"):
        return "Taiga chưa được cấu hình cho trợ lý này."

    items = filter_items_for_question(message, result.get("items", []))
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
    lines.extend(format_item_line(item) for item in items[:8])
    if len(items) > 8:
        lines.append(f"Còn {len(items) - 8} mục khác.")
    return "\n".join(lines)


async def answer_question(message):
    result = await search(message, 300)
    return format_direct_answer(message, result)


def format_context(items):
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
