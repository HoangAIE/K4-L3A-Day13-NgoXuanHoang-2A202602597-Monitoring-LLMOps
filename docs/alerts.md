# Template Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

## Alert 1

- Tên: HighLatencyDegradation
- Severity: critical
- Duration: 5m
- Kênh thông báo: Slack (#alerts-llmops)
- SLI/SLO liên quan: Primary SLO `fast_successful_requests` (latency <= 3000ms, target 99.5%)
- Điều kiện và thời gian duy trì: `p95(latency_ms) > 3000ms` liên tục trong 5 phút
- Ảnh hưởng tới người dùng: Người dùng nhận phản hồi câu hỏi rất chậm, trải nghiệm bị gián đoạn, client có thể bị timeout (504 Gateway Timeout).
- Ba bước kiểm tra đầu tiên:
  1. Kiểm tra panel Latency trên Dashboard để xác định P50/P95/P99 và TTFT tăng ở tính năng nào (`qa` hay `summary`).
  2. Lọc log trong `data/logs.jsonl` tìm correlation ID của các request có `latency_ms > 3000`.
  3. Mở Langfuse trace tương ứng với correlation ID đó, kiểm tra span waterfall xem bước chậm nằm ở retrieval (vector store) hay generation (LLM call).
- Mitigation tạm thời:
  - Nếu retrieval bị chậm (ví dụ do vector db nghẽn): tạm thời fallback sang in-memory cache hoặc kích hoạt fallback retrieval replica.
  - Nếu do traffic spike: scale out số worker uvicorn hoặc bật rate limiter tạm thời.
- Owner: oncall-llmops

## Alert 2

- Tên: HighErrorRate
- Severity: critical
- Duration: 3m
- Kênh thông báo: Slack (#alerts-llmops)
- SLI/SLO liên quan: Guardrail `error_rate_pct_max: 2%` và `retrieval_success_rate_pct_min: 90%`
- Điều kiện và thời gian duy trì: `error_rate_pct > 2%` (hoặc `retrieval_success_rate < 90%`) trong 3 phút
- Ảnh hưởng tới người dùng: Người dùng nhận mã lỗi HTTP 500 (`request_failed`), không nhận được câu trả lời từ chatbot.
- Ba bước kiểm tra đầu tiên:
  1. Kiểm tra panel Errors trên Dashboard để xem breakdown `error_type` (ví dụ `RuntimeError`, `TimeoutError`, v.v.) và retrieval success rate.
  2. Lấy log `request_failed` gần nhất trong `data/logs.jsonl`, xem trường `error_type` và `payload.detail`.
  3. Tra cứu trace ID trên Langfuse để xác định span bị lỗi (bước retriever hay LLM generation) cùng stack trace chi tiết.
- Mitigation tạm thời:
  - Nếu vector database bị lỗi kết nối/timeout: khởi động lại service vector database hoặc chuyển sang cơ chế fallback cached context.
  - Nếu mô hình trả về lỗi: rollback prompt version về bản ổn định gần nhất hoặc chuyển hướng traffic sang fallback LLM.
- Owner: oncall-llmops

## Alert 3

- Tên: HighCostBurnSpike
- Severity: warning
- Duration: 10m
- Kênh thông báo: Slack (#alerts-llmops)
- SLI/SLO liên quan: Guardrail `daily_cost_usd_max: 2.50` và Token budget `50,000 tokens`
- Điều kiện và thời gian duy trì: `total(cost_usd) > 2.50` trong 1 giờ hoặc burn rate vượt 0.50 USD trong 10 phút
- Ảnh hưởng tới người dùng: Hệ thống có nguy cơ bị cạn ngân sách API, chạm quota giới hạn token và có thể bị shutdown hoặc gián đoạn dịch vụ diện rộng.
- Ba bước kiểm tra đầu tiên:
  1. Kiểm tra panel Cost và Tokens trên Dashboard để xem tổng chi phí và sự bất thường của `tokens_out` so với `tokens_in`.
  2. Lọc log `response_sent` có `cost_usd` hoặc `tokens_out` cao đột biến để tìm `user_id_hash`, `session_id` hoặc prompt version đang kích hoạt.
  3. Mở trace trên Langfuse để kiểm tra output length và prompt version liên quan (kiểm tra xem prompt candidate mới có làm LLM lặp từ hoặc sinh câu trả lời quá dài hay không).
- Mitigation tạm thời:
  - Rollback prompt version về phiên bản trước (v1) nếu nguyên nhân do prompt mới gây lặp từ hoặc dài dòng.
  - Áp dụng cấu hình `max_tokens` chặt chẽ hơn ở tầng LLM config hoặc rate limit user/session gửi truy vấn gây tốn kém bất thường.
- Owner: oncall-llmops
