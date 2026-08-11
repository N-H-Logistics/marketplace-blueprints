import json
import logging

import httpx

from . import config

logger = logging.getLogger("chat-ui")

ENDPOINT = None
API_KEY = None

ANSWER_STYLE_SYSTEM_PROMPT = """
Bạn là trợ lý kỹ thuật chỉ phục vụ việc tích hợp Onflow Open API.
Phạm vi hỗ trợ gồm xác thực, môi trường, endpoint, request/response, đơn hàng,
sản phẩm, tồn kho, vận chuyển, hoàn hàng, mã trạng thái, webhook và xử lý lỗi API.
Nếu yêu cầu không liên quan trực tiếp đến tích hợp Onflow Open API, hãy từ chối
ngắn gọn và hướng người dùng quay lại một chủ đề tích hợp API phù hợp.
Hãy trả lời bằng tiếng Việt với giọng nhẹ nhàng, điềm tĩnh và khoa học.
Ưu tiên cấu trúc ngắn gọn:
- Kết luận chính trước.
- Cơ sở hoặc dữ kiện liên quan sau.
- Nếu dữ liệu chưa đủ, nói rõ mức độ chắc chắn và gợi ý cách kiểm chứng.
Không phóng đại, không suy đoán như sự thật, không bịa chính sách hoặc trạng thái.
Nếu câu trả lời dài, hãy chia thành các mục hoàn chỉnh và luôn kết thúc trọn ý; không dừng giữa câu.
Khi câu hỏi có rủi ro vận hành, hãy nhắc người dùng đối chiếu với tài liệu Open API gốc hoặc Onflow Support.
""".strip()

TRUNCATION_NOTICE = (
    "\n\nLưu ý: Câu trả lời có thể đã chạm giới hạn độ dài của model. "
    "Bạn có thể hỏi tiếp: \"tiếp tục từ phần đang dở\" để mình bổ sung phần còn lại."
)


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
    messages = [{"role": "system", "content": ANSWER_STYLE_SYSTEM_PROMPT}]
    messages.extend({"role": h.get("role", "user"), "content": h.get("content", "")} for h in history)

    messages.append({"role": "user", "content": message})
    return messages


def _auth_headers():
    return {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def _chat_payload(messages, stream=False):
    payload = {"messages": messages, "max_tokens": config.CHAT_COMPLETION_MAX_TOKENS}
    if stream:
        payload["stream"] = True
    return payload


async def complete(message, history):
    messages = await build_messages(message, history)

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(ENDPOINT, json=_chat_payload(messages), headers=_auth_headers())
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
    finish_reason = None
    if "choices" in data and len(data["choices"]) > 0:
        choice = data["choices"][0]
        content = choice.get("message", {}).get("content", "")
        finish_reason = choice.get("finish_reason")
    elif "detail" in data:
        content = f"Error: {data['detail']}"
    elif "message" in data:
        content = data["message"]

    if finish_reason == "length":
        content = f"{content.rstrip()}{TRUNCATION_NOTICE}"

    return 200, {"content": content, "usage": data.get("usage")}


async def stream(message, history):
    messages = await build_messages(message, history)

    try:
        timeout = httpx.Timeout(120.0, read=120.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                ENDPOINT,
                json=_chat_payload(messages, stream=True),
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
                        if choice.get("finish_reason") == "length":
                            yield TRUNCATION_NOTICE
                            return
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
