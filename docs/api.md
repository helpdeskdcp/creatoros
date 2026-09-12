# API

Full interactive documentation (OpenAPI/Swagger) is generated automatically
and served at `/docs` (Swagger UI) and `/redoc` (ReDoc) whenever the
backend is running. The raw schema is at `/api/v1/openapi.json`. This
document is a map of what exists, not a substitute for it.

## Conventions

- Base path: `/api/v1`
- Auth: `Authorization: Bearer <access_token>` header, obtained from
  `/auth/login` or `/auth/register`; refreshed via the httpOnly
  `creatoros_refresh_token` cookie against `POST /auth/refresh`.
- Errors: always `{"error": {"code", "message", "request_id"}}` with an
  appropriate HTTP status.
- Pagination: list endpoints currently return full result sets (no
  cursor/offset pagination yet — see `docs/ROADMAP.md`); most lists are
  naturally small (per-user resources).

## Route groups

| Prefix | Module | Notes |
|---|---|---|
| `/auth` | auth | register, login, refresh, logout, me |
| `/users` | users | admin-only list/role/active management |
| `/channels` | channels | connect (public or OAuth), sync, list, get |
| `/videos` | videos | list per channel, Channel Intelligence |
| `/competitors` | competitors | track, sync, content-gap detection |
| `/trends` | trends | list, refresh (recompute from real data) |
| `/topics` | topics | create, list, compute opportunity |
| `/research` | research | projects, sources, credibility |
| `/hooks`, `/titles`, `/scripts`, `/thumbnails`, `/seo` | AI generation | list + `/generate` |
| `/content` | content | Kanban items, calendar, status history, comments |
| `/analytics` | analytics | snapshots + `/growth/*` (scorecard, diagnosis, subscribers) |
| `/retention` | retention | per-video retention compute/list |
| `/recommendations` | recommendations | list + `/next-best-video` |
| `/experiments` | experiments | A/B test create/start/record-result |
| `/notifications` | notifications | list, mark-read |
| `/audit` | audit | read-only log of the current user's actions |
| `/publishing` | publishing | rules, runs, safety-gate check, approval |
| `/distribution` | distribution | campaigns, platform-specific asset generation |
| `/settings` | settings | kill switch, Autonomous Control Center |

## Role requirements

Most write operations require `EDITOR` or above
(`require_editor` dependency); user management requires `ADMIN`/`OWNER`
(`require_admin`); publishing-rule changes require `EDITOR`. Read
operations generally require only an authenticated session
(`get_current_user`). See each router's `Depends(...)` for the exact gate.

## Example: full creator flow

```bash
TOKEN=$(curl -s -X POST $BASE/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"a-strong-password-here"}' \
  | python3 -c 'import json,sys;print(json.load(sys.stdin)["access_token"])')

curl -s -X POST $BASE/channels -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"youtube_channel_id":"UC..."}'

curl -s -X POST $BASE/channels/<id>/sync -H "Authorization: Bearer $TOKEN"

curl -s $BASE/videos/channel/<id>/intelligence -H "Authorization: Bearer $TOKEN"

curl -s $BASE/analytics/growth/<id>/diagnosis -H "Authorization: Bearer $TOKEN"

curl -s -X POST $BASE/recommendations/next-best-video -H "Authorization: Bearer $TOKEN"
```
