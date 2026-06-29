FROM node:20-slim AS frontend

WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci

COPY frontend ./frontend
COPY vite.config.js .
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /build/static ./static

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
