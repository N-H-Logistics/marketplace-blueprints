import logging
from pathlib import Path

import httpx

from . import config

logger = logging.getLogger("chat-ui")


async def _attached_knowledge_bases(client):
    agent_resp = await client.get(
        f"{config.DO_API_BASE}/v2/gen-ai/agents/{config.AGENT_UUID}",
        headers=config.do_headers(),
    )
    agent_resp.raise_for_status()
    return agent_resp.json().get("agent", {}).get("knowledge_bases") or []


async def _require_attached_knowledge_base(client, kb_uuid):
    if not kb_uuid:
        raise ValueError("Thiếu Knowledge Base.")
    attached_kbs = await _attached_knowledge_bases(client)
    if not any(kb.get("uuid") == kb_uuid for kb in attached_kbs):
        raise ValueError("Knowledge Base không được gắn với agent này.")


def validate_upload(file_name, file_size):
    safe_name = Path(str(file_name or "")).name
    if not safe_name or safe_name != file_name:
        raise ValueError("Tên file không hợp lệ.")

    try:
        size = int(file_size)
    except (TypeError, ValueError) as exc:
        raise ValueError("Kích thước file không hợp lệ.") from exc

    if size <= 0:
        raise ValueError("File rỗng không thể được tải lên.")
    if size > config.KB_UPLOAD_MAX_BYTES:
        limit_mb = config.KB_UPLOAD_MAX_BYTES // (1024 * 1024)
        raise ValueError(f"File vượt quá giới hạn {limit_mb} MB.")
    if Path(safe_name).suffix.lower() not in config.KB_UPLOAD_EXTENSIONS:
        allowed = ", ".join(sorted(config.KB_UPLOAD_EXTENSIONS))
        raise ValueError(f"Định dạng file không được hỗ trợ. Cho phép: {allowed}.")
    return safe_name, size


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


async def list_knowledge_bases():
    async with httpx.AsyncClient(timeout=30.0) as client:
        attached_kbs = await _attached_knowledge_bases(client)

        result = []
        for kb in attached_kbs:
            kb_uuid = kb.get("uuid")
            if not kb_uuid:
                continue

            sources_resp = await client.get(
                f"{config.DO_API_BASE}/v2/gen-ai/knowledge_bases/{kb_uuid}/data_sources",
                headers=config.do_headers(),
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

    return result


async def create_upload(file_name, file_size, kb_uuid):
    safe_name, size = validate_upload(file_name, file_size)
    async with httpx.AsyncClient(timeout=30.0) as client:
        await _require_attached_knowledge_base(client, kb_uuid)
        response = await client.post(
            f"{config.DO_API_BASE}/v2/gen-ai/knowledge_bases/data_sources/file_upload_presigned_urls",
            headers=config.do_headers(),
            json={"files": [{"file_name": safe_name, "file_size": str(size)}]},
        )
        response.raise_for_status()
        uploads = response.json().get("uploads") or []
        if not uploads or not uploads[0].get("presigned_url") or not uploads[0].get("object_key"):
            raise RuntimeError("DigitalOcean không trả về URL tải file.")
        upload = uploads[0]
        return {
            "upload_url": upload["presigned_url"],
            "object_key": upload["object_key"],
            "file_name": upload.get("original_file_name") or safe_name,
            "file_size": size,
            "expires_at": upload.get("expires_at"),
        }


async def complete_upload(file_name, file_size, object_key, kb_uuid):
    safe_name, size = validate_upload(file_name, file_size)
    if not object_key or not isinstance(object_key, str):
        raise ValueError("Thiếu object key của file đã tải lên.")

    async with httpx.AsyncClient(timeout=60.0) as client:
        await _require_attached_knowledge_base(client, kb_uuid)
        source_response = await client.post(
            f"{config.DO_API_BASE}/v2/gen-ai/knowledge_bases/{kb_uuid}/data_sources",
            headers=config.do_headers(),
            json={
                "file_upload_data_source": {
                    "original_file_name": safe_name,
                    "size_in_bytes": str(size),
                    "stored_object_key": object_key,
                }
            },
        )
        source_response.raise_for_status()
        source_payload = source_response.json()
        source = (
            source_payload.get("knowledge_base_data_source")
            or source_payload.get("data_source")
            or source_payload
        )
        source_uuid = source.get("uuid") if isinstance(source, dict) else None
        if not source_uuid:
            raise RuntimeError("Datasource đã được tạo nhưng không có UUID để indexing.")

        index_response = await client.post(
            f"{config.DO_API_BASE}/v2/gen-ai/indexing_jobs",
            headers=config.do_headers(),
            json={"knowledge_base_uuid": kb_uuid, "data_source_uuids": [source_uuid]},
        )
        index_response.raise_for_status()
        return {"data_source_uuid": source_uuid, "indexing_job": index_response.json().get("job")}


async def delete_data_source(kb_uuid, data_source_uuid):
    if not data_source_uuid or not isinstance(data_source_uuid, str):
        raise ValueError("Thiếu datasource cần xoá.")

    async with httpx.AsyncClient(timeout=30.0) as client:
        await _require_attached_knowledge_base(client, kb_uuid)
        response = await client.delete(
            f"{config.DO_API_BASE}/v2/gen-ai/knowledge_bases/{kb_uuid}/data_sources/{data_source_uuid}",
            headers=config.do_headers(),
        )
        response.raise_for_status()
        return {"deleted": True, "data_source_uuid": data_source_uuid}
