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

# Populated at startup.
AGENT_ENDPOINT = None
AGENT_API_KEY = None

# Serve the static HTML chat page.
INDEX_HTML = (Path(__file__).parent / "static" / "index.html").read_text()


def _do_headers():
    return {"Authorization": f"Bearer {DO_API_TOKEN}", "Content-Type": "application/json"}


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


@app.post("/api/chat")
async def chat(request: Request):
    """Proxy a chat message to the managed agent and return the response."""
    if not AGENT_ENDPOINT or not AGENT_API_KEY:
        return JSONResponse(status_code=503, content={"error": "Agent not ready"})

    body = await request.json()
    message = body.get("message", "")
    history = body.get("history", [])

    # Build OpenAI-compatible messages array.
    messages = []
    for h in history:
        messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": message})

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

    messages = []
    for h in history:
        messages.append({"role": h.get("role", "user"), "content": h.get("content", "")})
    messages.append({"role": "user", "content": message})

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
