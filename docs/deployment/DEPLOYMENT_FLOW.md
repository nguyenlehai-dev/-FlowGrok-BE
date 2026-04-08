# FlowGrok BE Deployment Flow

## Runtime Mapping

- Backend container public port:
  - `127.0.0.1:8080 -> container:8000`
- Frontend Nginx proxy:
  - `https://testflowgrok.plxeditor.com/api/` -> `http://127.0.0.1:8080/api/`
  - `https://flowgrok.plxeditor.com/api/` -> `http://127.0.0.1:8080/api/`

Production API entrypoint from frontend:

- `https://flowgrok.plxeditor.com/api/v1/...`

## Source Model

- Chỉ có **1 source gốc** để phát triển backend:
  - `/home/vpsroot/projects/backend/-FlowGrok-BE`
- Runtime hiện tại chạy bằng Docker Compose tại chính repo này.
- Dữ liệu runtime cần giữ lại:
  - `/home/vpsroot/projects/backend/-FlowGrok-BE/flowgrok.db`
  - `/home/vpsroot/projects/backend/-FlowGrok-BE/storage/`
- Redis chạy cùng stack qua `docker-compose.yml`

## Current State

- Repo hiện đang ở trạng thái local bootstrap:
  - branch local `main`
  - chưa có commit local
  - remote `origin/main` đang không còn tồn tại
- Vì vậy hiện trạng deploy thực tế là **deploy trực tiếp từ source repo hiện tại**.
- Nếu muốn release flow giống frontend, cần chuẩn hóa lại branch trước khi vận hành chính thức.

## Recommended Release Flow

1. Develop trong `/home/vpsroot/projects/backend/-FlowGrok-BE`
2. Commit thay đổi lên branch làm việc
3. Promote commit cần test lên `staging`
4. Trên server staging, pull branch `staging`
5. Rebuild và restart Docker Compose
6. Validate API qua frontend test hoặc gọi trực tiếp endpoint health/auth
7. Promote `staging -> prod`
8. Trên server production, pull branch `prod`
9. Rebuild và restart Docker Compose
10. Smoke test qua domain production

Short form:

- `source -> staging -> compose up -> test -> promote -> prod -> compose up`

## SOP

1. Sửa code trong `/home/vpsroot/projects/backend/-FlowGrok-BE`
2. Kiểm tra `git status`
3. Nếu đổi dependency thì cập nhật `requirements.txt`
4. Build thử image local
5. Commit thay đổi
6. Push branch hiện tại
7. Promote lên `staging`
8. Trên môi trường cần deploy, checkout đúng branch và pull mới nhất
9. Backup `flowgrok.db` và `storage/` trước khi restart nếu thay đổi có rủi ro
10. Chạy `docker compose up -d --build`
11. Kiểm tra container `api` và `redis` đã lên
12. Kiểm tra endpoint `/` và `/api/v1/auth/me`
13. Sau khi QA xong thì promote `staging -> prod`
14. Lặp lại `docker compose up -d --build` trên production

Lệnh thường dùng:

```bash
cd /home/vpsroot/projects/backend/-FlowGrok-BE
git status
docker compose build
docker compose up -d --build
docker compose ps
docker compose logs -f api
```

Promote branch bằng script:

```bash
cd /home/vpsroot/projects/backend/-FlowGrok-BE
./scripts/promote-branch.sh staging prod
```

Backup dữ liệu trước deploy:

```bash
cd /home/vpsroot/projects/backend/-FlowGrok-BE
./scripts/deploy-compose.sh staging
```

## Runtime Config

- Source path:
  - `/home/vpsroot/projects/backend/-FlowGrok-BE`
- Compose file:
  - `/home/vpsroot/projects/backend/-FlowGrok-BE/docker-compose.yml`
- Dockerfile:
  - `/home/vpsroot/projects/backend/-FlowGrok-BE/Dockerfile`
- Promote script:
  - `/home/vpsroot/projects/backend/-FlowGrok-BE/scripts/promote-branch.sh`
- Deploy script:
  - `/home/vpsroot/projects/backend/-FlowGrok-BE/scripts/deploy-compose.sh`
- Branch bootstrap guide:
  - `/home/vpsroot/projects/backend/-FlowGrok-BE/docs/deployment/BRANCHING_SETUP.md`
- API runtime command:
  - `uvicorn main:app --host 0.0.0.0 --port 8000 --reload`
- Published API port:
  - `8080`
- Redis port:
  - `6380`
- Database hiện tại:
  - SQLite file `flowgrok.db`
- Persistent runtime files:
  - `storage/`

## Verify

```bash
curl http://127.0.0.1:8080/
curl http://127.0.0.1:8080/api/v1/auth/me
docker compose ps
docker compose logs --tail=100 api
```

## Rules

- Không xóa hoặc overwrite `flowgrok.db` và `storage/` trong quá trình deploy
- Không chạy backend production bằng `uvicorn` tay ngoài Docker nếu stack đang chuẩn hóa theo Compose
- Nếu vẫn dùng volume mount `.:/app`, cần kiểm soát kỹ thay đổi local trước khi restart container
- Trước khi áp dụng flow `staging -> prod`, cần tạo và thống nhất branch release thực sự trên remote
