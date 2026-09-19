# ---- 依赖源（华为云镜像；现场/内部构建时覆盖这两个 ARG 即可）----
ARG NPM_REGISTRY=https://mirrors.huaweicloud.com/npm
ARG PIP_INDEX_URL=https://mirrors.huaweicloud.com/repository/pypi/simple

# ---- 阶段 1：构建前端静态产物 ----
FROM node:22-alpine AS frontend-build
ARG NPM_REGISTRY
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --registry="$NPM_REGISTRY"
COPY web/ ./
RUN npm run build

# ---- 阶段 2：后端运行时 ----
FROM python:3.12-slim
ARG PIP_INDEX_URL

WORKDIR /app

# 依赖
COPY service/requirements.txt .
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r requirements.txt

# 代码
COPY service/app ./app

# 前端产物（方案 B：后端顺带 serve，默认落在 FRONTEND_DIR=web）
COPY --from=frontend-build /web/dist ./web

EXPOSE 8000

# 单副本；多副本水平扩展时跑多个本容器（api 无状态，worker 靠 Redis 队列）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
