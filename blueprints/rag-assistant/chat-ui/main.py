"""RAG Assistant Chat UI FastAPI entrypoint."""

import logging
import sys

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from chat_app import agent
from chat_app.config import BASE_DIR
from chat_app.routes import router

logging.basicConfig(level=logging.INFO, stream=sys.stdout)

app = FastAPI(title="RAG Assistant")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(router)


@app.on_event("startup")
async def startup_event():
    agent.discover()
