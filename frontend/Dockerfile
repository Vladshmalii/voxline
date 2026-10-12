FROM node:20-alpine AS build

WORKDIR /app

# Empty (default) = same-origin: the browser calls /api on this host and nginx
# proxies it to API_UPSTREAM. Set a full URL to talk to a backend directly.
ARG VITE_API_URL=
ENV VITE_API_URL=${VITE_API_URL}

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
ENV API_UPSTREAM=http://backend:8086
EXPOSE 80
