# Báo cáo cá nhân — K4-L3A Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Ngô Xuân Hoàng
- **MSSV:** 2A202602597
- **Lớp:** K4-L3A
- **Repository URL:** https://github.com/HoangAIE/K4-L3A-Day13-NgoXuanHoang-2A202602597-Monitoring-LLMOps
- **Commit SHA cuối:** `13b6066` *(cập nhật SHA của commit cuối khi nộp)*
- **Challenge ID:** `day13-k4-l3a-monitoring-llmops-v1`
- **Tên project Langfuse cá nhân:** `day13-k4-l3a-2A202602597`

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Pytest cuối | `evidence/01-pytest.png` |
| Log validator | `evidence/02-log-validator.png` |
| Dashboard validator | `evidence/03-dashboard-validator.png` |
| Structured log | `evidence/04-structured-log.png` |
| PII redaction | `evidence/05-pii-redaction.png` |
| Trace list | `evidence/06-trace-list.png` |
| Trace waterfall | `evidence/07-trace-waterfall.png` |
| Trace metadata | `evidence/08-trace-metadata.png` |
| Prompt versions | `evidence/09-prompt-versions.png` |
| Prompt rollback | `evidence/10-prompt-rollback.png` |
| Dashboard runtime | `evidence/11-dashboard-overview.png` |
| Incident metric | `evidence/12-incident-metric.png` |
| Incident log | `evidence/13-incident-log.png` |
| Incident trace | `evidence/14-incident-trace.png` |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 40/100 (thiếu context & PII) | 100/100 | Đạt tuyệt đối: 0 missing context, 0 PII leak |
| `validate_dashboard.py` | 0/6 panels | 6/6 panels | Hợp lệ 100% theo contract `config/dashboard.yaml` |
| `pytest` | 18 passed / 6 failed | 24/24 passed | 100% unit tests pass |
| Số traces hợp lệ | 0 | 34 traces | Đầy đủ quan hệ cha-con root, retrieval, generation |
| Số PII leak | Chưa kiểm soát | 0 leaks | 4 mẫu PII đều được scrub thành công |
| Latency P95 / TTFT P95 | ~2600ms (incident) | 151.0 ms / 50.0 ms | Đạt ngưỡng SLO sau khi khôi phục sự cố |
| Retrieval success rate | 100% | 100% | Retrieval hoạt động ổn định và chính xác |

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:**
  - Được cài đặt trong `CorrelationIdMiddleware` (`app/middleware.py`).
  - Mỗi request đến được gọi `clear_contextvars()` để xóa context cũ, chống rò rỉ dữ liệu giữa các request.
  - Lấy correlation ID từ header `x-request-id`; nếu không có thì tự động sinh theo mẫu chuẩn `req-<8-hex>` (`req-` + `uuid.uuid4().hex[:8]`).
  - Dùng `bind_contextvars(correlation_id=correlation_id)` để gắn vào ngữ cảnh log và lưu vào `request.state.correlation_id`.
  - Trả lại client qua response headers `x-request-id` và `x-response-time-ms`.

- **Các metadata được ghi vào structured log:**
  - Các trường định danh và ngữ cảnh: `correlation_id`, `user_id_hash` (băm SHA-256 từ `user_id`), `session_id`, `feature`, `model`, `env`, `service`, `level`, `ts` / `timestamp`.
  - Các trường đo lường hiệu năng và chi phí: `latency` / `latency_ms`, `ttft_ms`, `tokens_in`, `tokens_out`, `cost_usd`, `quality_score`, `tool_name`, `tool_success`.
  - Payload tóm tắt: `message_preview`, `answer_preview`.

- **Cách bảo đảm PII được scrub trước khi ghi:**
  - Áp dụng kiến trúc bảo vệ đa tầng (Defense-in-depth):
    1. **Tầng ứng dụng (`app/pii.py`):** `summarize_text()` gọi `scrub_text()` để thay thế toàn bộ 4 mẫu nhạy cảm (`email`, `phone_vn`, `cccd`, `credit_card`) bằng các thẻ redacted tương ứng `[REDACTED_EMAIL]`, `[REDACTED_PHONE_VN]`, `[REDACTED_CCCD]`, `[REDACTED_CREDIT_CARD]`. `user_id` thô được hash bằng SHA-256 thành `user_id_hash`.
    2. **Tầng Logging Processor (`app/logging_config.py`):** Processor `scrub_event` được cấu hình nằm **trước** `JsonlFileProcessor` và `JSONRenderer`. Nó đệ quy quét qua toàn bộ cấu trúc dict/list/string trong `event_dict["payload"]` và `event` để loại bỏ mọi PII còn sót lại trước khi ghi xuống đĩa hoặc in ra console.

- **Cách kiểm chứng kết quả:**
  - Kiểm tra tự động bằng `python scripts/validate_logs.py` đạt **100/100** điểm với `Potential PII leaks detected: 0`.
  - Kiểm tra bộ unit tests PII bằng `pytest tests/test_pii.py` đạt **4/4 passed** (test email, sdt Việt Nam, CCCD, thẻ tín dụng).
  - Kiểm tra thực tế bằng cách gửi request chứa cả 4 loại PII vào API `/chat` và đối chiếu trong `data/logs.jsonl` (xem ảnh `evidence/05-pii-redaction.png`).

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:**
  - Ứng dụng kết nối với Langfuse qua biến môi trường trong `.env` sử dụng API keys thuộc Project ID `cmumdmrgj20paad0chxpbe7a8` với tên project `day13-k4-l3a-2A202602597`.
  - Mọi traces đều chứa metadata cá nhân: `userId` (băm từ MSSV), tags `["lab", feature, model]`.

- **Cấu trúc root/retrieval/generation observations:**
  - Root observation: `lab-agent-run` (Type: `AGENT`, `parentObservationId: None`).
  - Child observation 1: `retrieval` (Type: `RETRIEVER`, kế thừa `parentObservationId` từ `lab-agent-run`).
  - Child observation 2: `fake-llm-generate` (Type: `GENERATION`, kế thừa `parentObservationId` từ `lab-agent-run`, ghi nhận model, prompt, token usage và chi phí USD).

- **Cách nối trace với log:**
  - Gắn chung một `correlation_id` (ví dụ `req-ce2017c5` hoặc `req-dffe2979`) vào metadata của Langfuse trace thông qua hàm `propagate_attributes(metadata={"correlation_id": correlation_id})` và trường `correlation_id` trong structured log.

- **Prompt name:** `day13-chat`
- **Version/label baseline:** Version 1, gắn labels `['baseline', 'production']`.
- **Version/label candidate:** Version 2, gắn labels `['candidate', 'latest']` (chỉnh sửa định dạng câu trả lời dạng bullet points ngắn gọn).
- **Trace ID của mỗi version:**
  - Baseline v1 (`baseline`): `3ddbcd00f35c40cbbc86466536980765`
  - Candidate v2 (`candidate`): `d53420e22241edfe3c7c2b6d28ff1abf`
  - Promoted Production v2 (`production`): `a0aa5a9f541994378ee9e42d021c4bd9`
  - Rollback Production v1 (`production`): `dfe2c98ff1eb6181db800e74302f3dad`

- **Cách promote và rollback `production`:**
  - **Promote:** Trên giao diện Langfuse (hoặc qua SDK), chuyển label `production` sang gắn cho Version 2. Ứng dụng tự động load bản v2 khi gọi `LANGFUSE_PROMPT_LABEL=production`.
  - **Rollback:** Khi cần hoàn tác, chuyển label `production` quay lại gắn cho Version 1. Ứng dụng ngay lập tức trở về dùng bản v1 ổn định mà không cần khởi động lại máy chủ (zero downtime).

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:**
  - Dashboard web runtime hiển thị tại `/dashboard` và file tĩnh `data/dashboard.html` gồm đủ 6 panels theo đúng hợp đồng:
    1. `Latency percentiles and TTFT`: P50, P95, P99 và TTFT P95.
    2. `Request traffic`: Số lượng request và tốc độ req/phút.
    3. `Error rate and retrieval success`: Tỷ lệ lỗi (%) và tỷ lệ tool retrieval thành công (%).
    4. `Cost over time`: Tổng chi phí USD tiêu thụ theo thời gian.
    5. `Input and output tokens`: Biểu đồ cơ cấu Token In / Token Out và tổng token.
    6. `Quality proxy`: Điểm đánh giá chất lượng phản hồi trung bình (thang điểm 0 - 1.0).
  - Tích hợp thêm bảng **Live Structured Log Explorer** hiển thị trực tiếp đầy đủ 7 trường JSON chuẩn hóa và nút View JSON.

- **SLO và lý do chọn:**
  - SLO: **99.5% requests có Latency P95 $\le 3000\text{ ms}$ trong chu kỳ 28 ngày** (ghi nhận tại `config/slo.yaml`).
  - Lý do: Đảm bảo độ trễ phản hồi không gây gián đoạn trải nghiệm người dùng trong luồng chat trực tiếp, đồng thời cho phép một biên độ an toàn cho bước truy xuất dữ liệu (retrieval) và suy luận mô hình (LLM inference).

- **Cách tính error budget:**
  - $\text{Error Budget} = 100\% - 99.5\% = 0.5\%$.
  - Với quy mô ví dụ 100,000 requests trong chu kỳ 28 ngày, số lượng request được phép vượt quá ngưỡng 3000ms hoặc bị lỗi tối đa là:
    $$100,000 \times 0.5\% = 500\text{ requests}$$

- **Ba alert và runbook tương ứng:**
  - Tham chiếu chi tiết tại `config/alert_rules.yaml` và `docs/alerts.md`:
    1. **`HighLatencyDegradation`** (Severity: Warning, điều kiện: P95 Latency > 2000ms kéo dài trong 2 phút):
       - *Runbook:* Kiểm tra bước retrieval, kiểm tra tài nguyên bộ nhớ của vector index, kích hoạt semantic cache hoặc fallback model nhẹ hơn.
    2. **`HighErrorRate`** (Severity: Critical, điều kiện: Error rate > 5% kéo dài trong 1 phút):
       - *Runbook:* Kiểm tra mã lỗi trả về (5xx/4xx), kiểm tra kết nối mạng tới LLM provider/vector DB, kích hoạt circuit breaker và rollback bản release gần nhất.
    3. **`HighCostBurnSpike`** (Severity: Warning, điều kiện: Chi phí tiêu thụ > $5.00 USD/giờ trong 5 phút):
       - *Runbook:* Kiểm tra số lượng output tokens đột biến, siết chặt giới hạn `max_tokens`, kiểm tra vòng lặp truy vấn agent hoặc tấn công lạm dụng API.

## 7. Điều tra challenge

- **Challenge ID:** `day13-k4-l3a-monitoring-llmops-v1`
- **Khoảng thời gian điều tra:** `2026-09-29T09:22:56Z` đến `2026-09-29T09:38:55Z` (tương đương 16:22:56 - 16:38:55 GMT+7).
- **Triệu chứng từ metrics:**
  - Panel số 1 (`Latency percentiles and TTFT`) chuyển sang trạng thái cảnh báo **`ALERT`**.
  - P95 Latency tăng vọt bất thường từ baseline ~151ms lên **`2652 ms – 3888 ms`**, vượt ngưỡng cho phép 2000ms của challenge.
  - Các chỉ số khác hoàn toàn bình thường: Error rate = 0%, TTFT P95 = 50ms, Quality score = 0.8 - 0.9.
- **Log line và correlation ID liên quan:**
  - Correlation ID: **`req-dffe2979`** (Session: `k4-l3a-challenge-s02`, User: `aae0b94055a9`).
  - Log `response_sent`:
    ```json
    {
      "service": "api",
      "event": "response_sent",
      "correlation_id": "req-dffe2979",
      "session_id": "k4-l3a-challenge-s02",
      "feature": "monitoring",
      "model": "claude-sonnet-4-5",
      "latency_ms": 3888,
      "ttft_ms": 50,
      "tool_name": "retrieval",
      "tool_success": true,
      "ts": "2026-09-29T09:23:00.311992Z"
    }
    ```
- **Trace ID và span gây ảnh hưởng:**
  - Trace ID tương ứng trên Langfuse: [`5fafc325425593a250d3c3a20405fba0`](https://cloud.langfuse.com/project/cmumdmrgj20paad0chxpbe7a8/traces/5fafc325425593a250d3c3a20405fba0).
  - Span gây ảnh hưởng: **`retrieval`** (Thời gian xử lý: **2.500s**, chiếm tới hơn 64% tổng thời gian 3.888s của request), trong khi span `fake-llm-generate` chỉ mất **0.151s**.
- **Root cause:**
  - Sự cố mô phỏng `rag_slow` đã gây nghẽn ở lớp truy xuất dữ liệu (Vector Retriever), làm chậm quá trình lấy tài liệu ngữ cảnh 2.5 giây. Mô hình LLM vẫn phản hồi bình thường.
- **Fix action:**
  - Tắt tình huống sự cố bằng cách gọi API `/incidents/rag_slow/disable` (hoặc lệnh `python scripts/inject_incident.py --disable`). Chạy lại load test để đưa latency P95 trở về baseline bình thường (151ms).
- **Preventive measure:**
  - Bổ sung Semantic Cache cho các truy vấn retrieval thường gặp.
  - Thiết lập cơ chế timeout (ví dụ: tối đa 1.5s) kèm fallback cho bước retrieval nếu vector store phản hồi chậm.
  - Kích hoạt alert `HighLatencyDegradation` để phát hiện và cảnh báo sớm tình trạng suy thoái độ trễ RAG.

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:**
  - Quyết định thiết lập cơ chế bảo vệ PII hai tầng (Defense-in-depth): tầng 1 scrub ở hàm tóm tắt payload ứng dụng, tầng 2 scrub tự động ở structlog processor trước khi serialize JSON và ghi file. Quyết định này giúp loại bỏ hoàn toàn nguy cơ rò rỉ dữ liệu nhạy cảm ngay cả khi lập trình viên quên gọi hàm scrub ở tầng nghiệp vụ.
- **Một lỗi/blocker đã gặp:**
  - Lỗi không build được wheel cho thư viện `pydantic-core` trên Python 3.14 do thiếu trình biên dịch Rust MSVC.
- **Cách tìm nguyên nhân và xử lý:**
  - Đọc log lỗi compiler nhận diện mã SOABI `cp314-win_amd64` chưa có bản prebuilt wheel ổn định. Xử lý triệt để bằng cách tạo virtual environment chuẩn với Python 3.12 (`.venv`), cài đặt trơn tru mọi dependencies.
- **Cách hiểu luồng Metrics → Logs → Traces:**
  - **Metrics:** Đóng vai trò là chuông báo động tổng thể ("What & When") — thông báo chỉ số P95 tăng vọt và panel chuyển sang ALERT tại một thời điểm nhất định.
  - **Logs:** Đóng vai trò là sổ nhật ký chi tiết ("Where & Who") — lọc tìm chính xác request bị ảnh hưởng và trích xuất `correlation_id` (`req-dffe2979`).
  - **Traces:** Đóng vai trò là kính hiển vi phân tích ("Why") — dựa vào `correlation_id` mở biểu đồ waterfall để soi sâu vào từng span, xác định chính xác span `retrieval` là thủ phạm gây nghẽn.
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:**
  - Cho phép quản trị ứng dụng LLM như một hệ thống phần mềm chuyên nghiệp: kiểm soát chi phí API, quản lý rủi ro khi tối ưu câu lệnh prompt, và khả năng rollback tức thì về phiên bản ổn định (zero-downtime) mà không cần can thiệp redeploy source code.
- **Điều quan trọng nhất đã học:**
  - Hiểu sâu sắc và thực hành trọn vẹn 3 trụ cột Observability trong hệ thống LLMOps hiện đại, từ khâu làm giàu log, bảo mật PII, truy vết distributed tracing trên Langfuse đến thiết lập SLO và quy trình điều tra sự cố chuẩn mực.
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:**
  - Bài lab sử dụng Mock RAG và Mock LLM để mô phỏng sự cố và đo đạc. Trong môi trường production thực tế, cần kết nối với Vector Database thực (như Qdrant, Pinecone) và mô hình LLM thực với streaming token latency monitoring.

## 9. Checklist trước khi nộp

- [x] Kết quả và evidence thuộc commit SHA cuối.
- [x] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [x] Incident evidence nối đúng metric → log → trace.
- [x] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [x] Repository chạy lại được theo README.
- [x] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [x] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
