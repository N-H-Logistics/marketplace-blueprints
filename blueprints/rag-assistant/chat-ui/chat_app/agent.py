import json
import logging

import httpx

from . import config, taiga

logger = logging.getLogger("chat-ui")

ENDPOINT = None
API_KEY = None


def ready():
    return ENDPOINT is not None and API_KEY is not None


def discover():
    """Fetch agent details from the DO API to get the deployment URL and API key."""
    global ENDPOINT, API_KEY

    logger.info("Discovering agent %s ...", config.AGENT_UUID)
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(f"{config.DO_API_BASE}/v2/gen-ai/agents/{config.AGENT_UUID}", headers=config.do_headers())
        resp.raise_for_status()
        agent = resp.json()["agent"]

        deployment = agent.get("deployment", {})
        deploy_url = deployment.get("url")
        if not deploy_url:
            logger.error("Agent has no deployment URL. Status: %s", deployment.get("status"))
            raise RuntimeError("Agent deployment URL not available")

        ENDPOINT = f"{deploy_url}/api/v1/chat/completions"
        logger.info("Agent endpoint: %s", ENDPOINT)

        logger.info("Creating agent API key...")
        key_resp = client.post(
            f"{config.DO_API_BASE}/v2/gen-ai/agents/{config.AGENT_UUID}/api_keys",
            headers=config.do_headers(),
            json={"name": "chat-ui"},
        )
        key_resp.raise_for_status()
        API_KEY = key_resp.json()["api_key_info"]["secret_key"]
        logger.info("Agent API key created")


async def build_messages(message, history):
    messages = [{"role": h.get("role", "user"), "content": h.get("content", "")} for h in history]

    if taiga.is_taiga_question(message):
        try:
            taiga_result = await taiga.search(message, config.TAIGA_MAX_RESULTS)
            taiga_context = taiga.format_context(taiga_result.get("items", []))
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


def _auth_headers():
    return {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


async def complete(message, history):
    messages = await build_messages(message, history)

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(ENDPOINT, json={"messages": messages}, headers=_auth_headers())
    except httpx.TimeoutException:
        return 504, {"error": "Agent phan hoi qua cham. Vui long thu lai sau it phut."}
    except httpx.RequestError as exc:
        logger.exception("Agent request failed")
        return 502, {"error": f"Khong goi duoc agent: {exc}"}

    try:
        data = resp.json()
    except Exception:
        return resp.status_code, {"error": resp.text}

    if resp.status_code >= 400:
        error = data.get("error") or data.get("detail") or data.get("message") or resp.text
        if isinstance(error, dict):
            error = error.get("message") or str(error)
        if resp.status_code == 429:
            error = "Agent dang bi gioi han tan suat. Vui long doi mot luc roi thu lai."
        return resp.status_code, {"error": error}

    content = ""
    if "choices" in data and len(data["choices"]) > 0:
        content = data["choices"][0].get("message", {}).get("content", "")
    elif "detail" in data:
        content = f"Error: {data['detail']}"
    elif "message" in data:
        content = data["message"]

    return 200, {"content": content, "usage": data.get("usage")}


async def stream(message, history):
    messages = await build_messages(message, history)

    try:
        timeout = httpx.Timeout(120.0, read=120.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                ENDPOINT,
                json={"messages": messages, "stream": True},
                headers=_auth_headers(),
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
