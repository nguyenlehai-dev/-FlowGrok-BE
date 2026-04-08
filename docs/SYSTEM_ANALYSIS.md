# Phân Tích Chuyên Sâu Kiến Trúc FlowGrok (Deep Analysis)

Tài liệu này đi sâu vào giải pháp kỹ thuật vi mô (Micro-architecture) nhằm giải quyết triệt để vấn đề Chống phát hiện (Antidetect), Khóa luồng (Concurrency), độ tin cậy của Automation Browser và thiết kế cơ sở hạ tầng.

---

## 1. Cơ Chế Môi Trường Tách Biệt & Antidetect Profile (Chuyên Sâu)

Sự sống còn của hệ thống nằm ở việc các AI như Google (Flow) và Twitter/Grok (`grok.com`) không phát hiện ra đây là hoạt động của Bot hoặc chung 1 người dùng.

### 1.1. Persistent Context (Phiên Lưu Trữ Bền Vững)
- **Sai lầm phổ biến:** Load Cookie vào chế độ ẩn danh (Incognito/Browser Context thông thường). Cookie sẽ bị thoát nếu JWT hoặc Token của Google refresh. Tệ hơn, IndexedDB và ServiceWorkers không được nạp dẫn đến mất phiên liên tục.
- **Giải pháp:** Sử dụng `playwright.chromium.launchPersistentContext`. Mỗi khi tạo Profile, tạo một thư mục vật lý (VD: `/storage/profiles/profile_userX_id1`). Thư mục này hoạt động như một ổ cứng của máy ảo, duy trì toàn bộ lịch sử lướt web, giúp trust-score của tài khoản luôn ở mức cao (Giống hệt 1 trình duyệt thực).

### 1.2. Fingerprint Spoofing & Ngụy Trang (Stealth)
- Mỗi Profile cần được ấn định cố định 1 **Static Fingerprint** (Dấu vân tay tĩnh) không thay đổi suốt phần đời của Profile đó:
  - `User-Agent`: (Ví dụ: Windows 10 Chrome 12x).
  - WebGL Vendor/Renderer.
  - Timezone & Geolocation (phải đồng bộ tuyệt đối với timezone của Proxy).
- **Tooling:** Áp dụng module `playwright-extra` và `puppeteer-extra-plugin-stealth` để xóa các biến mặc định sinh ra bởi webdriver (ví dụ `navigator.webdriver = false`). Ghi đè cấu trúc Canvas để chống bị check độ phân giải màn hình.

### 1.3. Cơ chế Khai báo và Tiêm Proxy
- Bắt buộc dùng Proxy loại **Static Residential** hoặc **Datacenter tĩnh** dành riêng biệt 1-1 cho từng Profile. Tránh Proxy Rotate (IP xoay) vì hành vi đổi IP liên tục sẽ làm chết Cookie Google/Grok.
- Proxy phải hỗ trợ chuẩn xác thực `username:password` và cài đặt thẳng vào arguments của lệnh khởi động Chromium.

---

## 2. Chiến Lược Điều Phối Luồng Xử Lý Cốt Lõi (Concurrency & Mutex Limit)

Đây là vấn đề giải quyết rủi ro Văng RAM trên VPS và Lỗi DOM do thao tác trùng.

### 2.1. Cấu trúc Job Queue đa tầng
- 1 cửa sổ Playwright tiêu thụ tối thiểu `200MB - 350MB RAM`. Nếu chạy đồng thời 20 Browser = `~ 7GB RAM`. Cần khống chế nghiêm ngặt.
- **Mutex Limit cấp Profile:** Một Profile Grok "A" **TUYỆT ĐỐI** không thể chạy cùng lúc 2 lệnh sinh video (Sẽ làm hỏng quá trình bắt DOM và gửi prompt của tab kia).
- **Thuật toán xếp hàng:**
  1. Yêu cầu (Request) từ người dùng đổ về -> **Redis Queue** của Node.js.
  2. Queue sẽ phân nhóm `group: [profile_id]`. Nếu Profile ID 1 đang xử lý 1 lệnh, các lệnh còn lại gửi đến Profile 1 sẽ ở trạng thái chờ (Wait).
  3. Thợ đào (Worker) chỉ bốc Job lên khi Profile đó đang rảnh (Idle).
  4. Nếu số Browser đang chạy chung của toàn Server đạt giới hạn `MAX_CONCURRENCY=5`, Worker sẽ đóng băng không mở trình duyệt mới cho tới khi có RAM trống.

---

## 3. Quá Trình Flow Của Khách Hàng Gọi API (The API Contract Lifecycle)

Mô hình này tối đa hóa chuẩn RESTful API, cho phép các Client (ứng dụng của khách hàng bạn) dễ dàng tích hợp bằng Python/PHP/Curl.

### Step-by-step Flow
1. **[Client API POST]** Client gửi Yêu cầu qua Endpoint (đính kèm `X-API-Key`):
   `POST /api/v1/generate` -> Payload `{"category": "flow", "prompt": "Dog flying on mars"}`
2. **[Laravel Backend Handler]**
   - Xác minh `X-API-Key`, kiểm tra User credits/Quyền.
   - Routing: Tìm Profile có `category = flow` thông thoáng nhất hiện trường.
   - Sinh ra 1 `Job_ID` và lưu db `status = processing`. Trả về cho Client `HTTP 200 OK` chứa mã `Job_ID` đó.
3. **[BE to Worker Dispatch]** Laravel đẩy tải HTTP nội bộ/gửi message qua RabbitMQ sang cục **Node.js Playwright Service** đằng sau.
4. **[Node.js Engine Execution]**
   - Headless Worker khởi chạy bằng cấu trúc Persistent Context.
   - Load trang đích (`labs.google` hoặc `grok.com`).
   - Đánh lệnh thao tác giả lập Input prompt. 
   - Lắng nghe Traffic mạng ngầm (Network Intercept) thay vì ngồi cào DOM để lấy kết quả nhanh hơn và né lỗi khi UI thay đổi định thức HTML.
5. **[Webhook Callback]**
   - Trình duyệt đóng lại. Node.js ném cục Kết quả Video/Image URL thông báo về Laravel `POST /internal-webhook/completed`.
6. **[Client Fetches Result]**
   - Client chủ động hỏi lệnh `GET /api/v1/jobs/[Job_ID]` nhiều lần (Long Pooling) cho tới khi `status == completed` thì nhận Link về. Hoặc hệ thống hỗ trợ PUSH webhook thẳng qua URL của Client.

---

## 4. Xử Lý Các Rủi Ro Hiện Trường (Failover Mechanisms)

- **Cookie Hết Hạn:** Engine khi Load trang sẽ tóm (catch) sự kiện thẻ Login hoặc URL chuyển hướng về trang chủ. Lúc này Node.js phải ném Error Code đánh giấu Profile `cookie_dead`, tự động hủy kết nối, dừng nhận lệnh mới và báo đỏ trên màn hình Admin Dashboard để Admin nạp Cookie mới.
- **Catching Timeout DOM:** Thời gian AI sinh Video bên ngoài diễn ra chênh lệch mạnh (20s - 3 phút). Worker phải override default timeout của Playwright thành cường độ `300,000ms (5 phút)`, nhưng đi dọn dẹp bằng vòng lặp try/catch tinh vi, đảm bảo khi văng timeout, tiến trình con browser được huỷ an toàn `browser.close()`, RAM được giải phóng.
- **Rủi ro rác Temp:** Hạn chế download video về server VPS. Tốt nhất là bóc (parse) link `source src=` hoặc Cloudflare/CDN url gốc của Grok/Flow để tiết kiệm Disk Storage I/O.
