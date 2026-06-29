import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from . import agent, config, knowledge, taiga

logger = logging.getLogger("chat-ui")
router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index():
    return config.INDEX_HTML.replace("{{AGENT_NAME}}", config.AGENT_NAME)


@router.get("/health")
async def health():
    return {"status": "ok", "agent_ready": agent.ready()}


@router.get("/api/taiga/search")
async def taiga_search(q: str = "", limit: int = config.TAIGA_MAX_RESULTS):
    try:
        return await taiga.search(q, max(1, min(limit, 50)))
    except httpx.HTTPStatusError as exc:
        logger.exception("Taiga search failed")
        return JSONResponse(status_code=exc.response.status_code, content={"error": exc.response.text})
    except (httpx.RequestError, RuntimeError) as exc:
        logger.exception("Taiga search failed")
        return JSONResponse(status_code=502, content={"error": f"Không lấy được dữ liệu Taiga: {exc}"})


@router.get("/api/taiga/metadata")
async def taiga_metadata():
    try:
        data = await taiga.project_metadata()
        if not data.get("configured"):
            return JSONResponse(status_code=503, content=data)
        return data
    except httpx.HTTPStatusError as exc:
        logger.exception("Taiga metadata request failed")
        return JSONResponse(status_code=exc.response.status_code, content={"error": exc.response.text})
    except (httpx.RequestError, RuntimeError, ValueError) as exc:
        logger.exception("Taiga metadata request failed")
        return JSONResponse(status_code=502, content={"error": f"Không lấy được cấu hình Taiga: {exc}"})


@router.post("/api/taiga/issues")
async def create_taiga_issue(request: Request):
    try:
        payload = await request.json()
        data = await taiga.create_issue(payload)
        if data.get("error"):
            return JSONResponse(status_code=400 if data.get("configured") else 503, content=data)
        return data
    except httpx.HTTPStatusError as exc:
        logger.exception("Taiga issue creation failed")
        return JSONResponse(status_code=exc.response.status_code, content={"error": exc.response.text})
    except (httpx.RequestError, RuntimeError, ValueError) as exc:
        logger.exception("Taiga issue creation failed")
        return JSONResponse(status_code=502, content={"error": f"Không tạo được báo lỗi Taiga: {exc}"})


@router.get("/api/knowledge-bases")
async def knowledge_bases():
    try:
        return {"knowledge_bases": await knowledge.list_knowledge_bases()}
    except httpx.HTTPStatusError as exc:
        logger.exception("Knowledge base metadata request failed")
        return JSONResponse(status_code=exc.response.status_code, content={"error": exc.response.text})
    except httpx.RequestError as exc:
        logger.exception("Knowledge base metadata request failed")
        return JSONResponse(status_code=502, content={"error": f"Không lấy được Knowledge Base: {exc}"})


@router.post("/api/knowledge-bases/uploads")
async def create_knowledge_base_upload(request: Request):
    try:
        payload = await request.json()
        return await knowledge.create_upload(
            payload.get("file_name"), payload.get("file_size"), payload.get("knowledge_base_uuid")
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except httpx.HTTPStatusError as exc:
        logger.exception("Knowledge base upload initialization failed")
        return JSONResponse(status_code=exc.response.status_code, content={"error": exc.response.text})
    except (httpx.RequestError, RuntimeError) as exc:
        logger.exception("Knowledge base upload initialization failed")
        return JSONResponse(status_code=502, content={"error": f"Không khởi tạo được upload: {exc}"})


@router.post("/api/knowledge-bases/uploads/complete")
async def complete_knowledge_base_upload(request: Request):
    try:
        payload = await request.json()
        return await knowledge.complete_upload(
            payload.get("file_name"),
            payload.get("file_size"),
            payload.get("object_key"),
            payload.get("knowledge_base_uuid"),
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except httpx.HTTPStatusError as exc:
        logger.exception("Knowledge base upload completion failed")
        return JSONResponse(status_code=exc.response.status_code, content={"error": exc.response.text})
    except (httpx.RequestError, RuntimeError) as exc:
        logger.exception("Knowledge base upload completion failed")
        return JSONResponse(status_code=502, content={"error": f"Không thêm được tài liệu: {exc}"})


@router.delete("/api/knowledge-bases/{knowledge_base_uuid}/data-sources/{data_source_uuid}")
async def delete_knowledge_base_data_source(knowledge_base_uuid: str, data_source_uuid: str):
    try:
        return await knowledge.delete_data_source(knowledge_base_uuid, data_source_uuid)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    except httpx.HTTPStatusError as exc:
        logger.exception("Knowledge base datasource deletion failed")
        return JSONResponse(status_code=exc.response.status_code, content={"error": exc.response.text})
    except (httpx.RequestError, RuntimeError) as exc:
        logger.exception("Knowledge base datasource deletion failed")
        return JSONResponse(status_code=502, content={"error": f"Không xoá được tài liệu: {exc}"})


@router.post("/api/chat")
async def chat(request: Request):
    if not agent.ready():
        return JSONResponse(status_code=503, content={"error": "Agent not ready"})

    body = await request.json()
    message = body.get("message", "")
    history = body.get("history", [])

    if taiga.is_taiga_question(message):
        try:
            content = await taiga.answer_question(message)
            return JSONResponse(content={"content": content, "usage": None})
        except Exception as exc:
            logger.exception("Taiga direct answer failed")
            return JSONResponse(status_code=502, content={"error": f"Không lấy được dữ liệu Taiga: {exc}"})

    status_code, payload = await agent.complete(message, history)
    return JSONResponse(status_code=status_code, content=payload)


@router.post("/api/chat/stream")
async def chat_stream(request: Request):
    if not agent.ready():
        return JSONResponse(status_code=503, content={"error": "Agent not ready"})

    body = await request.json()
    message = body.get("message", "")
    history = body.get("history", [])

    if taiga.is_taiga_question(message):
        async def generate_taiga():
            try:
                yield await taiga.answer_question(message)
            except Exception as exc:
                logger.exception("Taiga direct stream answer failed")
                yield f"Không lấy được dữ liệu Taiga: {exc}"

        return StreamingResponse(generate_taiga(), media_type="text/plain; charset=utf-8")

    return StreamingResponse(agent.stream(message, history), media_type="text/plain; charset=utf-8")
