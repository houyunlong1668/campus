# 前端镜像：node 构建 dist → nginx 托管静态 + 反代后端（同源七路径，与 vite dev 代理一致）
FROM node:22-alpine AS build

WORKDIR /app
# 先 .npmrc（镜像源与项目约定一致）+ 锁文件，再装依赖——层缓存友好
COPY .npmrc ./
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build          # vue-tsc -b && vite build（类型检查是前端唯一防线）

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
# 健康检查只测本容器静态服务：后端死活由后端自己的 healthcheck 管，
# 否则后端重启会把前端一起拖成 unhealthy。
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD wget -q -O /dev/null http://127.0.0.1/index.html || exit 1
