# ---- 构建阶段：Node 编译前端静态产物 ----
FROM node:24-alpine AS build
WORKDIR /app

# 先复制依赖清单单独安装，利用镜像层缓存：package.json 不变则下次构建跳过重装
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

# 复制源码并构建（tsc 类型检查 + vite 打包 → /app/dist）
COPY . .
RUN npm run build

# ---- 运行阶段：Nginx 提供静态文件并反代后端 ----
FROM nginx:stable-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
