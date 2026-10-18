# Деплой Voxline

| Домен | Сервис | Workflow |
|---|---|---|
| `voxline.dvms.tech` | `landing` (nginx, `landing/`) | `.github/workflows/landing.yml` |
| `voxline-admin.dvms.tech` | `frontend` (nginx, `/api` → `app:8080`) | `.github/workflows/frontend.yml` |
| `voxline-backend.dvms.tech` | `app` (`/api/...`) + `hooks` (`/hooks/...`) | `.github/workflows/backend.yml` |

Пайплайн: тесты → образ в `ghcr.io/vladshmalii/voxline-<name>` (`:latest` и `:sha-<commit>`) →
SSH на сервер → `docker compose pull && up -d` только своих сервисов. На PR — только тесты.
Workflow запускается, только если менялась его папка; вручную — через *Run workflow*.

## Однократная настройка

**GitHub → Settings → Secrets and variables → Actions**

- Secrets: `SSH_HOST`, `SSH_USER` (deploy), `SSH_PRIVATE_KEY`; опционально `SSH_PORT`,
  `SSH_KNOWN_HOSTS` (вывод `ssh-keyscan <host>`, иначе ключ хоста принимается при первом подключении).
- Variable (опционально): `DEPLOY_PATH` — по умолчанию `/opt/voxline`.
- Environment `production` создаётся автоматически; в нём можно включить ручное подтверждение деплоя.

**Сервер**

```bash
sudo mkdir -p /opt/voxline && sudo chown deploy:deploy /opt/voxline
# публичный ключ пары из SSH_PRIVATE_KEY -> ~deploy/.ssh/authorized_keys
# пользователь deploy должен быть в группе docker
cp deploy/.env.example /opt/voxline/.env   # и заполнить секреты
```

**Cloudflare DNS**: A-записи для трёх доменов на сервер — до первого деплоя (иначе не выпустится сертификат).

## Первый запуск

Запусти `backend` (поднимет postgres, redis, migrate с bootstrap-суперпользователем),
затем `frontend` и `landing`. После первого входа убери `BOOTSTRAP_PASSWORD` из `.env`.

## Откат

```bash
cd /opt/voxline
BACKEND_TAG=sha-<commit> docker compose up -d migrate app hooks worker scheduler
```
(аналогично `FRONTEND_TAG` / `LANDING_TAG`; либо пропиши тег в `.env`).
Миграции БД при откате назад не откатываются.

## Телефония

Колбэки идут на `wss://voxline-backend.dvms.tech/hooks/api/v1/media/...` —
это значение `CALL_WORKER__MEDIA_URL` в `.env`. Traefik срезает `/hooks` и отправляет запрос в `hooks:8081`.
