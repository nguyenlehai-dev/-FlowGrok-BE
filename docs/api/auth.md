# API Xác thực (Auth) & API Keys

Tài liệu này phản ánh contract hiện tại của module `Auth` trong backend **FastAPI (Python)**.

## 1. Đăng Ký Tài Khoản

```
POST /api/v1/auth/register
Content-Type: application/json

{"email": "user@example.com", "password": "mypassword"}
```

**Response (200):**
```json
{
    "id": "uuid",
    "email": "user@example.com",
    "role": "user",
    "is_active": true
}
```

## 2. Đăng Nhập (Nhận JWT Token)

```
POST /api/v1/auth/login
Content-Type: application/json

{"email": "user@example.com", "password": "mypassword"}
```

**Response (200):**
```json
{
    "access_token": "eyJhbGciOiJIUzI1NiIs...",
    "token_type": "bearer"
}
```

Token sống **24 giờ**. Sau đó cần đăng nhập lại.

## 3. Lấy Thông Tin User Hiện Tại

```
GET /api/v1/auth/me
Authorization: Bearer <access_token>
```

**Response (200):**
```json
{
    "id": "uuid",
    "email": "user@example.com",
    "role": "user",
    "is_active": true
}
```

## 4. Quản Lý API Keys

### 4.1. Tạo API Key mới
```
POST /api/v1/auth/api-keys
Authorization: Bearer <access_token>
```

**Response (200):**
```json
{
    "id": "uuid",
    "key": "fgk_RN3-nboYsLd1ygCZLw4dSUpcnhT9EW3eExd0XQC8EMA",
    "status": "active",
    "key_preview": "fgk_RN3-nb...QC8EMA"
}
```

Lưu ý:

- `key` chỉ trả về đầy đủ đúng **một lần** ở thời điểm tạo.
- Backend lưu `key_hash`, không dùng plaintext key để xác thực mới.

### 4.2. Liệt kê API Keys
```
GET /api/v1/auth/api-keys
Authorization: Bearer <access_token>
```

**Response (200):**
```json
[
  {
    "id": "uuid",
    "key": null,
    "status": "active",
    "key_preview": "fgk_RN3-nb...QC8EMA",
    "rate_limit_per_minute": 60,
    "last_used_at": null
  }
]
```

### 4.3. Thu hồi API Key
```
DELETE /api/v1/auth/api-keys/{key_id}
Authorization: Bearer <access_token>
```

## 5. Cách Sử Dụng API Key (cho Client Tool)

Client bên ngoài dùng API Key thay cho JWT Token:
```
GET /api/v1/profiles
Authorization: Bearer fgk_RN3-nboYsLd1ygCZLw4dSUpcnhT9EW3eExd0XQC8EMA
```

Hệ thống tự động nhận diện đầu vào là API Key hay JWT Token và xác thực tương ứng.

## 6. Cấu Trúc Kỹ Thuật

| Thành phần | Công nghệ |
|-----------|-----------|
| Framework | FastAPI `Depends()` injection |
| Mã hóa password | `bcrypt` (trực tiếp, không qua passlib) |
| JWT | `python-jose` thuật toán `HS256` |
| Database | SQLAlchemy Model `User` + `ApiKey` |
| Token TTL | 24 giờ |
| API Key prefix | `fgk_` |
