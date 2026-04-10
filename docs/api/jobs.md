# API Jobs, Worker, Security

Tài liệu này phản ánh contract hiện tại của module `Jobs` trong backend FastAPI.

## 1. Tạo Job

```http
POST /api/v1/jobs/
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "profile_id": "uuid",
  "job_type": "generate_image",
  "prompt": "A cinematic neon city at night"
}
```

Backend sẽ chặn nếu profile bị disable hoặc đã vượt `concurrency_limit`.

## 2. Xem Jobs và Artifacts

```http
GET /api/v1/jobs/
Authorization: Bearer <access_token>
```

```http
GET /api/v1/jobs/{job_id}
Authorization: Bearer <access_token>
```

```http
GET /api/v1/jobs/{job_id}/artifacts
Authorization: Bearer <access_token>
```

## 3. Chạy Worker Từ Dashboard

Frontend dashboard không gọi internal route nữa. Thay vào đó dùng endpoint yêu cầu JWT:

```http
POST /api/v1/jobs/run-worker-once
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "worker_id": "staging-worker-01",
  "max_priority": 100
}
```

Endpoint này chạy một vòng worker với `headless=true`.

## 4. Internal Worker Endpoints

Các endpoint internal dưới prefix:

```http
/api/v1/internal/jobs/*
```

hiện yêu cầu header:

```http
x-worker-token: <WORKER_TOKEN>
```

Các route đang được bảo vệ:

- `POST /api/v1/internal/jobs/claim`
- `POST /api/v1/internal/jobs/{job_id}/heartbeat`
- `POST /api/v1/internal/jobs/{job_id}/status`
- `POST /api/v1/internal/jobs/{job_id}/artifacts`
- `POST /api/v1/internal/jobs/run-once`

Nếu thiếu token hợp lệ, backend trả `401 Invalid worker token`.

## 5. CORS

Backend không còn dùng wildcard CORS cho runtime mặc định. Cấu hình qua:

```env
CORS_ORIGINS=http://localhost:3000,http://localhost:5173,https://testflowgrok.plxeditor.com,https://flowgrok.plxeditor.com
```

## 6. Worker Secret

Thiết lập token nội bộ qua:

```env
WORKER_TOKEN=change-me-worker-token
```

Token này dành cho worker/server-side integrations, không nên nhúng vào frontend public.
