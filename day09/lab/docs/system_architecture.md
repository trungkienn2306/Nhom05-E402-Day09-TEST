# System Architecture — Lab Day 09: Multi-Agent RAG Orchestration

**Nhóm:** Nhóm 05 — E402  
**Ngày:** 2026-04-14  
**Version:** 1.0  

---

## 1. Tổng quan kiến trúc

Hệ thống triển khai kiến trúc **Supervisor-Worker** — một Supervisor phân tích truy vấn đầu vào và điều phối tới worker chuyên trách tương ứng. Không có worker nào tự sinh ra câu trả lời trực tiếp từ ngữ cảnh riêng; mọi đầu ra cuối cùng đều được xử lý qua Synthesis Worker với yêu cầu trích dẫn nguồn nghiêm ngặt.

**Pattern đã chọn:** Supervisor-Worker (Multi-Agent Orchestration)

**Lý do chọn pattern này (thay vì single-agent):**

- **Separation of Concerns**: Retrieval, policy checking và synthesis là ba mối quan tâm kỹ thuật (concerns) độc lập — tách biệt chúng giúp mỗi thành phần có thể được kiểm thử và cải tiến mà không ảnh hưởng đến phần còn lại.
- **Debuggability**: Mỗi bước xử lý ghi lại `worker_io_logs` chi tiết vào AgentState — khi pipeline tạo ra đầu ra sai, trace JSON cho phép xác định lỗi ở worker nào chỉ trong vài phút.
- **Extensibility**: Thêm một worker mới (ví dụ: `billing_worker`) chỉ đòi hỏi định nghĩa keyword routing và file worker tương ứng, không yêu cầu sửa đổi logic cốt lõi.
- **MCP Integration**: Policy Tool Worker có thể gọi các MCP tools qua HTTP mà Retrieval Worker không cần biết — tách biệt rõ ràng trách nhiệm giữa evidence retrieval và tool-based reasoning.

---

## 2. Sơ đồ Pipeline

```
                        User Request (task: str)
                               │
                               ▼
                    ┌──────────────────────┐
                    │       SUPERVISOR     │
                    │      (graph.py)      │
                    │                      │
                    │  Keyword routing:    │
                    │  - access/level KW   │─→ policy_tool_worker
                    │  - refund/hoàn tiền  │─→ policy_tool_worker
                    │  - sla/p1/ticket KW  │─→ retrieval_worker
                    │  - error code pattern│─→ retrieval_worker
                    │  - default           │─→ retrieval_worker
                    │                      │
                    │  Output fields:      │
                    │  supervisor_route    │
                    │  route_reason        │
                    │  risk_high           │
                    │  needs_tool          │
                    └──────────┬───────────┘
                               │
              ┌────────────────┴──────────────────┐
              │                                   │
              ▼                                   ▼
  ┌───────────────────────┐         ┌─────────────────────────────┐
  │   RETRIEVAL WORKER    │         │    POLICY TOOL WORKER        │
  │  (workers/retrieval.py)│        │  (workers/policy_tool.py)   │
  │                       │         │                             │
  │  ChromaDB semantic    │         │  [Bước 1] Pre-fetch context │
  │  search (cosine sim)  │         │    via retrieval_worker      │
  │  OpenAI text-embedding│         │  [Bước 2] Exception detect: │
  │  -3-small             │         │    flash_sale / digital /   │
  │  Paragraph-level chunk│         │    activated / temporal     │
  │  (split by \n\n)      │         │  [Bước 3] MCP call:         │
  │                       │         │    check_access_permission  │
  │  Output:              │         │    (nếu có access level KW) │
  │  retrieved_chunks     │         │  [Bước 4] MCP call:         │
  │  retrieved_sources    │         │    get_ticket_info           │
  └──────────┬────────────┘         │    (nếu risk_high + P1 KW)  │
             │                      │                             │
             │                      │  Output:                    │
             │                      │  policy_result              │
             │                      │  mcp_tools_used             │
             └──────────┬───────────┘
                        │
                        ▼
                    ┌──────────────────────────┐
                    │    SYNTHESIS WORKER       │
                    │  (workers/synthesis.py)   │
                    │                           │
                    │  [1] Abstain check:        │
                    │     top_score < 0.35?      │
                    │     temporal v3 mismatch?  │
                    │  [2] LLM call:             │
                    │     gpt-4o-mini (primary)  │
                    │     gemini-1.5-flash       │
                    │     rule-based (fallback)  │
                    │  [3] Confidence scoring:   │
                    │     f(cosine_sim, breadth, │
                    │       exceptions)          │
                    │  [4] Citation [source.txt] │
                    │                           │
                    │  Output:                  │
                    │  final_answer             │
                    │  sources                  │
                    │  confidence               │
                    └──────────────┬────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────┐
                    │          OUTPUT           │
                    │  final_answer (cited)     │
                    │  confidence ∈ [0, 1]      │
                    │  sources: list[str]        │
                    │  latency_ms               │
                    │  trace → runs.jsonl       │
                    └──────────────────────────┘

[HITL path: error_code pattern (ERR-\d{3+}) → human_review node → placeholder answer]
```

---

## 3. Vai trò từng thành phần

### Supervisor (`graph.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **Nhiệm vụ** | Phân tích truy vấn đầu vào, quyết định route điều phối; tuyệt đối không tự sinh câu trả lời domain |
| **Input** | `task` (str từ người dùng) |
| **Output** | `supervisor_route`, `route_reason`, `risk_high`, `needs_tool` |
| **Routing logic** | Keyword matching có thứ tự ưu tiên: `access/level` → `policy_tool_worker`; `refund/hoàn tiền` → `policy_tool_worker`; `sla/p1/ticket` → `retrieval_worker`; error code regex → `retrieval_worker`; default → `retrieval_worker` |
| **HITL condition** | Khi phát hiện error code pattern `ERR-\d{3+}` HOẶC khi `confidence < 0.30` (Post-synthesis fallback) |

### Retrieval Worker (`workers/retrieval.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **Nhiệm vụ** | Thực hiện semantic search trong ChromaDB, trả về top-k chunks bằng chứng liên quan nhất |
| **Embedding model** | `text-embedding-3-small` (OpenAI API) — cosine similarity, collection `day09_docs_openai` |
| **Chunking strategy** | Phân đoạn theo ký tự xuống dòng kép (`\n\n`), lọc đoạn có độ dài ≥ 30 ký tự |
| **Top-k** | Mặc định 3, có thể cấu hình qua `state["top_k"]` |
| **Stateless** | Yes — `_collection_cache` là module-level singleton; không lưu state ngoài AgentState |
| **Index build** | Tự động xây dựng khi collection rỗng, đọc tất cả file `.txt` trong `data/docs/` |

### Policy Tool Worker (`workers/policy_tool.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **Nhiệm vụ** | Phân tích ngoại lệ chính sách (exceptions) dựa trên context; gọi MCP tools cho access control và ticket lookup |
| **MCP tools gọi** | `search_kb` (khi retrieved_chunks < 2); `check_access_permission` (khi phát hiện access level keyword); `get_ticket_info` (khi `risk_high=True` và có P1/ticket keyword) |
| **Exception types xử lý** | `flash_sale_exception`, `digital_product_exception`, `activated_product_exception`, `temporal_scope_mismatch` (policy v3 không có trong KB) |
| **MCP endpoint** | `http://localhost:8765` (HTTP FastAPI server, cấu hình qua biến môi trường `MCP_SERVER_URL`) |

### Synthesis Worker (`workers/synthesis.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **LLM model** | `gpt-4o-mini` (primary) → `gemini-1.5-flash` (fallback) → rule-based concatenation (final fallback) |
| **Temperature** | 0.05 — giá trị thấp nhằm tối đa hóa tính deterministic và giảm thiểu hallucination |
| **Grounding strategy** | System prompt strict: chỉ được dùng thông tin từ `TÀI LIỆU THAM KHẢO`; abstain nếu không đủ bằng chứng; cite mọi claim bằng `[source_file]` |
| **Abstain condition** | `top_score < 0.35` (ngưỡng cosine similarity), hoặc không có chunks, hoặc phát hiện temporal scope mismatch (đơn hàng trước 01/02/2026) |
| **Confidence formula** | `0.65 × top_score + 0.35 × avg_score + breadth_bonus − abstain_penalty − exception_penalty` |

### MCP Server (`mcp_server.py`)

| Tool | Input | Output |
|------|-------|--------|
| `search_kb` | `query: str`, `top_k: int` | `chunks: list`, `sources: list`, `total_found: int` |
| `get_ticket_info` | `ticket_id: str` | Ticket details dict (mock P1-LATEST với SLA deadline) |
| `check_access_permission` | `access_level: int`, `requester_role: str`, `is_emergency: bool` | `can_grant: bool`, `required_approvers: list`, `emergency_override: bool`, `notes: list` |
| `create_ticket` | `priority: str`, `title: str`, `description: str` | `ticket_id`, `url`, `created_at` (MOCK — không tạo thật) |

**Triển khai HTTP thực (Bonus +2):** MCP Server được triển khai dưới dạng HTTP REST API độc lập bằng **FastAPI + Uvicorn**, không phải mock class hay in-process call. Policy Tool Worker gọi các tools qua `requests.post(f"http://localhost:8765/tools/{tool_name}", json=tool_input)` — tức là giao tiếp thật qua mạng, hoàn toàn tách biệt process.

| Endpoint | Method | Mô tả |
|----------|--------|-------|
| `/health` | GET | Kiểm tra trạng thái server, liệt kê tools available |
| `/tools` | GET | MCP tool discovery — trả về list schema của tất cả tools |
| `/tools/{tool_name}` | POST | MCP tool execution — nhận `body: dict`, trả về tool output |

**Cách chạy (2-terminal setup):**
- Terminal 1: `python day09/lab/mcp_server.py` → server lắng nghe tại `http://0.0.0.0:8765`
- Terminal 2: `python day09/lab/graph.py` / `eval_trace.py` → pipeline gọi MCP qua HTTP

---

## 4. Shared State Schema (AgentState)

| Field | Type | Mô tả | Ai đọc / ghi |
|-------|------|-------|-------------|
| `task` | `str` | Truy vấn đầu vào từ người dùng | Supervisor đọc |
| `supervisor_route` | `str` | Worker được chọn để xử lý | Supervisor ghi |
| `route_reason` | `str` | Lý do routing (human-readable, dùng để debug) | Supervisor ghi |
| `risk_high` | `bool` | Truy vấn có rủi ro cao (P1, emergency, ngoài giờ) | Supervisor ghi; Policy Tool đọc |
| `needs_tool` | `bool` | Cần thực hiện MCP tool call | Supervisor ghi; Policy Tool đọc |
| `retrieved_chunks` | `list[dict]` | Danh sách chunks bằng chứng từ ChromaDB | Retrieval ghi; Synthesis/Policy đọc |
| `retrieved_sources` | `list[str]` | Tên file nguồn tương ứng với chunks | Retrieval ghi |
| `policy_result` | `dict` | Kết quả phân tích exception + MCP tool output | Policy Tool ghi; Synthesis đọc |
| `mcp_tools_used` | `list[dict]` | Nhật ký đầy đủ mọi MCP tool call (tool name, input, output, timestamp) | Policy Tool ghi (append) |
| `final_answer` | `str` | Câu trả lời cuối kèm citation | Synthesis ghi |
| `confidence` | `float` | Mức độ tin cậy [0.0, 1.0], tính từ cosine similarity và các tín hiệu phụ | Synthesis ghi |
| `sources` | `list[str]` | Danh sách file được trích dẫn trong câu trả lời | Synthesis ghi |
| `workers_called` | `list[str]` | Chuỗi thứ tự các worker đã được gọi | `graph.py` ghi (append) |
| `worker_io_logs` | `list[dict]` | Chi tiết input/output/timestamp của từng worker | Mỗi worker append |
| `latency_ms` | `float` | Tổng thời gian xử lý end-to-end (milliseconds) | `graph.py` ghi |
| `run_id` | `str` | ID định danh duy nhất cho mỗi lần chạy (`run_YYYY-MM-DD_HHMM`) | `make_initial_state()` ghi |
| `hitl_triggered` | `bool` | Human-in-the-Loop đã được kích hoạt | `human_review_node` ghi |

---

## 5. So sánh Supervisor-Worker với Single Agent (Day 08)

| Tiêu chí | Single Agent (Day 08) | Supervisor-Worker (Day 09) |
|----------|----------------------|--------------------------|
| Debug khi pipeline sai | Khó — không rõ lỗi ở indexing, retrieval hay generation | Dễ — kiểm thử từng worker độc lập bằng `python workers/xxx.py` |
| Thêm capability mới | Phải sửa toàn bộ prompt và re-test toàn pipeline | Thêm worker hoặc MCP tool riêng biệt, không ảnh hưởng core |
| Routing visibility | Không có — black box | Có `route_reason` rõ ràng trong mọi trace JSON |
| Exception handling | Hard-code trong system prompt | Policy worker với exception detection module riêng biệt |
| Tool use | Phải inject tool descriptions vào prompt | MCP server expose schema, `dispatch_tool` tự động |
| Latency | Thấp hơn (~800ms) — đơn giản hơn | Cao hơn (~1500–4500ms) — nhiều bước xử lý hơn |
| Multi-hop accuracy | ~40% — thường chỉ trả lời một phần | ~85% — pre-fetch retrieval đảm bảo synthesis đủ context từ nhiều nguồn |
| Abstain accuracy | ~0% — có xu hướng hallucinate số liệu không có trong KB | ~13% — abstain đúng nhờ cosine similarity threshold (< 0.35) |

**Quan sát thực tế từ trace:**  
Policy Tool Worker gọi `check_access_permission` MCP → Synthesis nhận structured data (`can_grant`, `required_approvers`, `emergency_override`) thay vì phải parse text thô từ chunks. Điều này giảm thiểu đáng kể tỷ lệ hallucination trên các câu hỏi access control.

---

## 6. Giới hạn và Hướng cải tiến

1. **Routing bằng keyword matching dễ bỏ sót edge cases**: Câu hỏi như "Hậu quả khi vi phạm SLA P1?" có từ khóa SLA nhưng thông tin penalty không có trong Knowledge Base — routing đúng nhưng synthesis phải abstain. Cải tiến đề xuất: sử dụng LLM-based router với few-shot examples để xử lý paraphrased queries chính xác hơn.

2. **Temporal scoping detection còn hạn chế**: Logic hiện tại chỉ nhận diện các mốc tháng 1/2026 qua danh sách keyword cứng (`"31/01"`, `"trước 01/02"`...). Các câu hỏi liên quan đến năm 2024 hoặc các date format khác sẽ không bị phát hiện. Cải tiến đề xuất: triển khai regex date parsing tổng quát hơn.

3. **Tận dụng LLM cho routing phức tạp hơn**: Logic hiện tại dựa trên keyword. Cải tiến đề xuất: sử dụng LLM-based router với few-shot examples để xử lý các câu hỏi mang tính diễn giải (paraphrased queries) mà không chứa keyword trực tiếp.
