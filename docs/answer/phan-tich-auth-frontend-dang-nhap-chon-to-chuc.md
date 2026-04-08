# Phân tích Auth từ Frontend: Đăng nhập và Chọn Tổ chức

Tài liệu này được cập nhật theo contract hiện tại của backend `Auth` (Python FastAPI).

## 1. Bản chất flow hiện tại

Hệ thống FlowGrok sử dụng **2 cơ chế xác thực song song**:

### 1.1. JWT Token (cho Dashboard Admin/User)
- **Đăng nhập:** `POST /api/v1/auth/login` với body `{"email": "...", "password": "..."}`.
- **Phản hồi:** Server trả về `access_token` (JWT, sống 24h).
- **Sử dụng:** Frontend React gắn token vào Header `Authorization: Bearer <token>` cho mọi request CRUD (tạo Profile, xem Proxy...).
- **Hết hạn:** Token hết hạn sau 24h, user phải đăng nhập lại.

### 1.2. API Key (cho Client Tool bên ngoài)
- **Tạo Key:** Admin tạo API Key qua Dashboard hoặc trực tiếp qua API.
- **Sử dụng:** Client gắn vào Header `X-API-Key: <key>` để gọi các endpoint sinh ảnh/video.
- **Phạm vi:** API Key chỉ có quyền gọi endpoint Generation, không có quyền CRUD quản trị.

## 2. Endpoint Auth đã triển khai

| Method | Path | Mô tả |
|--------|------|--------|
| POST | `/api/v1/auth/login` | Đăng nhập bằng email/password, nhận JWT |
| POST | `/api/v1/auth/register` | Đăng ký tài khoản mới |
| GET | `/api/v1/auth/me` | Lấy thông tin user hiện tại (cần Bearer token) |

## 3. Cấu trúc kỹ thuật

- **Framework:** FastAPI với `Depends()` injection.
- **Mã hóa password:** `bcrypt` qua thư viện `passlib`.
- **JWT:** Thư viện `python-jose` với thuật toán `HS256`.
- **Database:** SQLAlchemy Model `User` (xem `app/models/core.py`).

## 4. Tổ chức (Organization)
- Hiện tại hệ thống chưa triển khai multi-organization. Mỗi user sở hữu Profiles/API Keys riêng biệt.  
- Header `X-Organization-Id` được reserve cho tương lai khi cần phân tách tài nguyên giữa nhiều workspace.
