# Kế Hoạch Triển Khai (Implementation Plan) - FlowGrok (Python + ReactTS)

Tài liệu này ghi chú lại cấu trúc (scaffolding) sẽ triển khai cho Backend và Frontend dựa trên stack công nghệ: **Backend (Python/FastAPI)**, **Frontend (React/TypeScript)**.

## Những Thay Đổi Trọng Yếu (Architecture Mapping)

Khác với thiết kế cũ dùng PHP Laravel, khi dùng Python làm API Backend, ta có thể tích hợp **native** công cụ giả lập `playwright-python` nằm ngay bên trong Server. Mô hình này giúp loại bỏ độ trễ và sự kềnh càng của việc phải tách riêng Microservice.

### 1. Kiến Trúc Backend (`~/projects/backend/-FlowGrok-BE`)
Thiết lập toàn bộ khung mã nguồn mạnh mẽ dựa trên **FastAPI**:
- **API Framework**: Sử dụng `FastAPI` (hiệu năng đỉnh cao của Python, hỗ trợ asynchronous request, và tự động generate Swagger Docs).
- **ORM / Database**: Cài đặt `SQLAlchemy`, dùng `Alembic` để xử lý Migration (bảng Profiles, Proxies, Clients).
- **Control Flow / Task Queue**: Tích hợp module quản lý hàng đợi `Celery` chạy kẹp với DB `Redis` để khống chế RAM và tránh tình trạng mở quá nhiều Chrome cùng lúc khi Profile dồn việc vọt (Mutex).
- **Automation Playwright**: Khai báo công nghệ `playwright` bản Python. 
- **Cấu trúc thư mục (Quy chuẩn Production)**:
  - `/app/api/endpoints/` (Lưới định tuyến - Routers).
  - `/app/models/` & `/app/schemas/` (Khởi tạo DB tables, chuẩn hóa output bằng Pydantic).
  - `/app/services/` (Các lệnh cốt lõi của Playwright auto cho Grok/Flow/Dreamina).
  - `/app/worker/` (Kịch bản khởi động ngầm cho Celery/Redis).

### 2. Kiến Trúc Frontend (`~/projects/frontend/FlowGrok`)
Tạo bộ khung (Scaffold) mạnh mẽ cho giao diện quản trị dựa trên Node.js toolchain:
- **Build Tool**: Gõ lệnh `npx create-vite@latest` với template **React + TypeScript**.
- **Styles / UI**: Cài đặt framework **TailwindCSS** để dựng UI tối ưu, clean.
- **Routing & Networking**:
  - `axios` gọi tới Server BE (`http://localhost:8000/api/v1`).
  - `react-router-dom` xử lý luồng trang.
- **Cấu trúc Thư mục**:
  - `/src/api` (Bộ móc nối BE).
  - `/src/components` & `/src/layouts` (Thành phần giao diện chung: Header, Sidebar, Datatable proxy).
  - `/src/pages` (Gồm Profile Manager, Setup Antidetect, Dashboard Thống Kê, System Logs).
  - `/src/store` (Trạng thái trung tâm bằng thư viện Zustand).

---

## Các Vấn Đề Cần Phê Duyệt Trước Khi Gõ Code (Open Questions)

> [!IMPORTANT]
> Để chuẩn bị chính xác cho môi trường code, có 2 chi tiết về hạ tầng bạn cần đưa ra quyết định:
> 
> 1. **Môi trường Database:** Ở giai đoạn này, bạn muốn cấu hình cơ sở dữ liệu dùng thẳng **SQLite** (file độc lập, dễ copy/backup toàn dự án) hay thiết lập kết nối chuẩn chỉnh tới **MySQL / PostgreSQL** trên máy chủ?
> 2. **Kiến trúc Docker & Redis:** Do Celery Python bắt buộc cần Redis RAM để giữ thông báo khi load task Playwright nặng, mình sẽ khởi tạo một file `docker-compose.yml` để nhốt cả Backend lẫn Redis cho nó tự vận hành trơn tru nhé?

---

## Kế Hành Nghiệm Thu (Verification Checklist)
- [ ] Truy cập đường link `:8000/docs` phải nảy ra giao diện Swagger OpenAPI xịn xò. Backend chạy trơn tru định danh Authentication (Bearer Key).
- [ ] Gõ `npm run dev` ở thư mục thư Frontend biên dịch ra React Dashboard Vite ở `:5173`. Typescript sạch bóng báo lỗi.
