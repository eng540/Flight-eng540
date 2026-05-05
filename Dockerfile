# Stage 1: Build Frontend
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./

RUN mkdir -p src/lib && \
    echo 'import { clsx, type ClassValue } from "clsx";' > src/lib/utils.ts && \
    echo 'import { twMerge } from "tailwind-merge";' >> src/lib/utils.ts && \
    echo 'export function cn(...inputs: ClassValue[]) {' >> src/lib/utils.ts && \
    echo '  return twMerge(clsx(inputs));' >> src/lib/utils.ts && \
    echo '}' >> src/lib/utils.ts

ENV VITE_API_URL=""
RUN npm run build

# Stage 2: Build Backend & Worker
FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt aiofiles

COPY backend/ ./backend/
COPY worker/ ./worker/
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

ENV PYTHONPATH=/app/backend:/app

COPY start.sh ./
RUN chmod +x start.sh

CMD ["./start.sh"]