# LAB DAY 09 — Tổng Quan & Hướng Dẫn Chi Tiết
# Multi-Agent Orchestration: Supervisor-Worker Pattern · MCP · Trace & Observability

**Môn:** AI in Action (AICB-P1)  
**Thời gian:** 4 giờ (4 sprints × 60 phút)  
**Ngày:** 2026-04-13  

---

## Mục Đích Bài Tập

Bài lab Day 09 tiếp nối Day 08 (RAG Pipeline đơn giản) và nâng cấp lên một hệ thống **Multi-Agent** có cấu trúc rõ ràng. Bài học cốt lõi là:

> **Một AI agent "thông minh" duy nhất làm mọi thứ → dễ viết nhưng khó debug, khó mở rộng, khó biết lỗi ở đâu. Tách thành nhiều agents có vai trò rõ ràng → khó hơn lúc đầu nhưng chuyên nghiệp và bền vững hơn.**

### Vấn đề của Day 08 (Single Agent)
- 1 agent vừa retrieve tài liệu, vừa kiểm tra policy, vừa viết câu trả lời, vừa xử lý lỗi
- Khi trả lời sai: **không biết lỗi ở bước nào** — indexing, retrieval, hay generation?
- Muốn thay retrieval model: phải sửa toàn bộ code
- Không có "trace" để xem luồng xử lý

### Giải pháp Day 09 (Multi-Agent Supervisor-Worker)
- **1 Supervisor** chỉ làm 1 việc: phân tích câu hỏi và quyết định ai xử lý
- **3 Workers** mỗi người 1 chuyên môn: tìm kiếm / kiểm tra policy / viết câu trả lời
- **1 MCP Server** để workers gọi external tools theo chuẩn
- **Trace đầy đủ** mọi bước → debug dễ, audit được

---

## Bối Cảnh Bài Toán

Hệ thống trợ lý nội bộ cho phòng **Customer Support + IT Helpdesk**, cần xử lý được các câu hỏi như:

| Câu hỏi | Yêu cầu xử lý |
|---------|---------------|
| "Ticket P1 lúc 2am — escalation xảy ra thế nào?" | Tìm trong tài liệu SLA |
| "Contractor cần Admin Access để sửa P1 khẩn" | Kiểm tra policy Access Control |
| "Khách Flash Sale yêu cầu hoàn tiền vì lỗi nhà sản xuất" | Kiểm tra policy hoàn tiền + exception |

**5 tài liệu nội bộ có sẵn:**
- `policy_refund_v4.txt` — Chính sách hoàn tiền v4 (hiệu lực từ 01/02/2026)
- `sla_p1_2026.txt` — Quy định SLA xử lý sự cố (P1/P2/P3/P4)
- `access_control_sop.txt` — Quy trình kiểm soát truy cập
- `it_helpdesk_faq.txt` — FAQ IT Helpdesk
- `hr_leave_policy.txt` — Chính sách nghỉ phép và remote work

---

## Mục Tiêu Học Tập

| Mục tiêu | Sprint |
|----------|--------|
| Hiểu và implement Supervisor-Worker pattern | Sprint 1 |
| Xây workers có contract rõ ràng, test độc lập được | Sprint 2 |
| Tích hợp external capability qua MCP interface | Sprint 3 |
| Đo lường hệ thống bằng trace, so sánh với baseline | Sprint 4 |

---

## Kiến Trúc Hệ Thống

```
User Request (câu hỏi)
        │
        ▼
┌───────────────────────────────────────┐
│            SUPERVISOR                  │
│  - Phân tích từ khóa trong câu hỏi    │
│  - Quyết định route (không tự trả lời)│
│  - Ghi route_reason, risk_high        │
└──────────────┬────────────────────────┘
               │ route_decision()
       ┌───────┼───────────┐
       │       │           │
       ▼       ▼           ▼
  Retrieval  Policy     Human
  Worker     Tool       Review
  (SLA,FAQ)  Worker     (HITL)
       │    (refund,     │
       │     access)     │
       │       │         │
       └───────┼─────────┘
               │ (khi cần MCP)
               ▼
        ┌─────────────┐
        │  MCP Server │
        │ search_kb   │
        │ get_ticket  │
        │ check_access│
        └─────────────┘
               │
               ▼
    ┌──────────────────┐
    │  Synthesis Worker│
    │  - Tổng hợp answer│
    │  - Thêm citation  │
    │  - Tính confidence│
    └──────────────────┘
               │
               ▼
        Final Answer
   (với trace đầy đủ)
```

---

## 4 Sprints — Yêu Cầu Cơ Bản (Bắt Buộc)

---

### 🔵 Sprint 1 (60 phút) — Supervisor Orchestrator

**File:** `graph.py`

**Nhiệm vụ:** Xây "não bộ" điều phối của hệ thống.

**Phải làm được:**

1. **`AgentState`** — Shared state truyền qua toàn bộ pipeline:
   ```python
   {
     "task": str,              # Câu hỏi đầu vào
     "supervisor_route": str,  # Worker được chọn
     "route_reason": str,      # Lý do routing (không được là "unknown")
     "risk_high": bool,        # True nếu câu hỏi có rủi ro cao
     "needs_tool": bool,       # True nếu cần gọi MCP tool
     "history": list,          # Lịch sử xử lý
     "retrieved_chunks": list, # Kết quả từ retrieval
     "policy_result": dict,    # Kết quả từ policy worker
     "mcp_tools_used": list,   # MCP tools đã gọi
     "final_answer": str,      # Câu trả lời cuối
     "confidence": float,      # Độ tin cậy 0.0-1.0
     "sources": list,          # Nguồn tài liệu
     "hitl_triggered": bool,   # True nếu cần human review
     "retrieved_sources": list,# Tên file tài liệu nguồn
     "workers_called": list    # Danh sách workers đã gọi
   }
   ```

2. **`supervisor_node(state)`** — Đọc task, phân tích, set routing decision

3. **`route_decision(state)`** — Routing logic theo keyword:
   - "hoàn tiền", "refund", "flash sale", "license", "cấp quyền", "access" → `policy_tool_worker`
   - "P1", "SLA", "ticket", "escalation", "sự cố" → `retrieval_worker`
   - Mã lỗi không rõ (ERR-xxx) → `human_review`
   - Default → `retrieval_worker`

4. **Kết nối graph:** `supervisor → route → [retrieval | policy_tool | human_review] → synthesis → END`

5. **Hàm `run_graph(task)`** để gọi từ bên ngoài

**Definition of Done (DoD):**
- [ ] `python graph.py` chạy không lỗi
- [ ] Supervisor route đúng cho ≥2 loại câu hỏi khác nhau
- [ ] Mỗi routing có `route_reason` rõ ràng (không phải "unknown")
- [ ] State object có đủ fields bắt buộc

---

### 🟢 Sprint 2 (60 phút) — Build Workers

**Files:** `workers/retrieval.py`, `workers/policy_tool.py`, `workers/synthesis.py`

**Nhiệm vụ:** Xây 3 "chuyên gia" xử lý domain knowledge.

#### Retrieval Worker (`workers/retrieval.py`)
- Nhận query từ state
- Embed query bằng SentenceTransformer
- Query ChromaDB để lấy top-k chunks liên quan
- Trả về `retrieved_chunks` và `retrieved_sources`
- **Stateless**: không dùng state ngoài những gì được khai báo

#### Policy Tool Worker (`workers/policy_tool.py`)  
- Nhận task + retrieved_chunks
- Gọi MCP Server để search thêm nếu cần
- Phát hiện **exception cases**: Flash Sale, digital product, activated product
- Kiểm tra temporal scoping (đơn trước ngày hiệu lực → policy v3)
- Trả về `policy_result` với `policy_applies`, `exceptions_found`

#### Synthesis Worker (`workers/synthesis.py`)
- Nhận task + retrieved_chunks + policy_result
- Gọi LLM với **grounded prompt** (chỉ dùng context được cung cấp)
- Output có `answer` kèm citation `[source_name]`
- Tính `confidence` score thực tế (không hard-code)
- Nếu không có chunks → **abstain** (không hallucinate)
- Nếu confidence < 0.4 → trigger HITL

**Definition of Done:**
- [ ] Mỗi worker test độc lập được
- [ ] Input/output khớp với `contracts/worker_contracts.yaml`
- [ ] Policy worker detect đúng ≥1 exception case
- [ ] Synthesis có citation `[source]` trong answer

---

### 🟡 Sprint 3 (60 phút) — MCP Server

**File:** `mcp_server.py`

**Nhiệm vụ:** Xây "công cụ ngoại vi" cho workers gọi qua chuẩn giao tiếp.

**Phải implement ≥2 tools:**

| Tool | Input | Output |
|------|-------|--------|
| `search_kb` | query, top_k | chunks, sources, total_found |
| `get_ticket_info` | ticket_id | ticket details, sla_deadline |
| `check_access_permission` | access_level, requester_role, is_emergency | can_grant, required_approvers |

**Policy worker phải gọi MCP** thay vì trực tiếp query ChromaDB.

**Trace phải ghi:**
```json
{
  "tool": "search_kb",
  "input": {"query": "...", "top_k": 3},
  "output": {"chunks": [...], "sources": [...]},
  "timestamp": "2026-04-13T14:32:11"
}
```

**Definition of Done:**
- [ ] `mcp_server.py` có ≥2 tools implement
- [ ] Policy worker gọi MCP, không direct call ChromaDB
- [ ] Trace ghi được `mcp_tool_called` và `mcp_result`

---

### 🔴 Sprint 4 (60 phút) — Trace & Docs & Report

**File:** `eval_trace.py`

**Nhiệm vụ:** Đo lường, so sánh, và tài liệu hóa hệ thống.

**Phải làm được:**

1. Chạy pipeline với 15 test questions từ `data/test_questions.json`
2. Lưu trace mỗi câu vào `artifacts/traces/` (JSONL format)
3. Tính metrics: avg_confidence, avg_latency_ms, route_accuracy, abstain_rate
4. So sánh Day 08 (baseline) vs Day 09 (multi-agent)
5. Điền vào 3 doc templates trong `docs/`
6. Viết báo cáo nhóm và cá nhân

**Trace format bắt buộc mỗi câu:**
```json
{
  "run_id": "run_2026-04-13_1432",
  "task": "câu hỏi đầu vào",
  "supervisor_route": "retrieval_worker",
  "route_reason": "task contains SLA keyword",
  "workers_called": ["retrieval_worker", "synthesis_worker"],
  "mcp_tools_used": [],
  "retrieved_sources": ["sla_p1_2026.txt"],
  "final_answer": "...",
  "confidence": 0.88,
  "hitl_triggered": false,
  "latency_ms": 1230,
  "timestamp": "2026-04-13T14:32:11"
}
```

**Definition of Done:**
- [ ] `python eval_trace.py` chạy end-to-end với 15 câu không crash
- [ ] Trace có đủ fields bắt buộc
- [ ] `docs/routing_decisions.md` có ≥3 quyết định routing thực tế từ trace
- [ ] `docs/single_vs_multi_comparison.md` có ≥2 metrics có số liệu
- [ ] Reports (group + individual) hoàn chỉnh

---

## Phần Extra — Lấy Điểm Bonus (+5 điểm tối đa)

### Extra 1: Real MCP Server (+2 điểm)
**Yêu cầu:** Implement MCP server thật bằng FastAPI (HTTP server), không phải mock class Python.

**Cách làm:**
- MCP server expose REST API endpoints
- Workers gọi qua HTTP request (không phải function call trực tiếp)
- Server chạy được trên port (ví dụ: `http://localhost:8080`)

**Bằng chứng cần có:** Trace log ghi URL endpoint được gọi.

### Extra 2: Confidence Score Thực Tế (+1 điểm)
**Yêu cầu:** Confidence phải được tính thực tế từ evidence, không được hard-code.

**Cách tính gợi ý:**
- Dựa vào retrieval score từ ChromaDB (cosine similarity)
- Số lượng sources tìm được
- LLM có đưa ra disclaimer không
- Tổng hợp thành số 0.0-1.0

**Bằng chứng:** Confidence khác nhau giữa các câu trong trace.

### Extra 3: Câu gq09 Full Marks (+2 điểm)
**Yêu cầu:** Câu khó nhất (16 điểm) — P1 lúc 2am + cấp Level 2 cho contractor.

**Phải làm được:**
1. Retrieve từ `sla_p1_2026.txt` → quy trình escalation P1
2. Retrieve từ `access_control_sop.txt` → quy trình emergency access Level 2
3. Trả lời đầy đủ **cả hai** quy trình song song
4. Trace ghi rõ **2 workers được gọi** cho câu này

**Điểm chính:** Level 2 có emergency bypass (khác Level 3!) — cần approval đồng thời Line Manager + IT Admin on-call.

---

## Cách Chấm Điểm Chi Tiết

### Điểm Nhóm (60 điểm)

| Hạng mục | Điểm |
|----------|------|
| Sprint Deliverables — Code chạy được | 20 |
| Group Documentation (3 docs) | 10 |
| Grading Questions (10 câu ẩn, 96 raw points) | 30 |
| **Tổng nhóm** | **60** |

**Quy đổi Grading Questions:**
```
Điểm = (raw đạt được / 96) × 30
```

**10 Grading Questions (public lúc 17:00):**

| ID | Chủ đề | Raw Points |
|----|--------|------------|
| gq01 | P1 lúc 22:47 — ai nhận thông báo, qua kênh nào, escalation lúc mấy giờ? | 10 |
| gq02 | Đơn 31/01/2026, hoàn tiền 07/02/2026 — được không? | 10 |
| gq03 | Level 3 access — bao nhiêu người phê duyệt, ai cuối? | 10 |
| gq04 | Store credit = bao nhiêu % tiền gốc? | 6 |
| gq05 | P1 không phản hồi sau 10 phút — hệ thống làm gì? | 8 |
| gq06 | Nhân viên thử việc muốn remote — điều kiện? | 8 |
| gq07 | **Câu ABSTAIN** — mức phạt tài chính vi phạm SLA P1? (Không có trong tài liệu!) | 10 |
| gq08 | Mật khẩu đổi mấy ngày, cảnh báo trước mấy ngày? | 8 |
| gq09 | **Câu MULTI-HOP** — P1 lúc 2am + Level 2 emergency cho contractor | 16 |
| gq10 | Flash Sale + lỗi nhà sản xuất + 7 ngày — hoàn tiền không? | 10 |

> ⚠️ **Quan trọng — gq07:** Tài liệu KHÔNG có thông tin về mức phạt tài chính. Pipeline phải **abstain** rõ ràng. Nếu bịa số liệu → **−5 điểm penalty**!

### Điểm Cá Nhân (40 điểm)

| Hạng mục | Điểm |
|----------|------|
| Individual Report (500-800 từ) | 30 |
| Code Contribution Evidence | 10 |
| **Tổng cá nhân** | **40** |

**Individual Report cần có:**
- Mô tả cụ thể module bạn phụ trách (7đ)
- 1 quyết định kỹ thuật bạn đề xuất + lý do (8đ)
- 1 lỗi đã sửa + bằng chứng trước/sau (8đ)
- Tự đánh giá: làm tốt gì, yếu gì (4đ)
- Nếu có 2h thêm sẽ làm gì (3đ)

---

## Cách Nộp Bài

### Timeline

| Thời điểm | Sự kiện |
|-----------|---------|
| **17:00** | `grading_questions.json` được public |
| **17:00–18:00** | Chạy pipeline với 10 câu ẩn |
| **18:00** | **DEADLINE code & trace** (commit sau không tính) |
| **Sau 18:00** | Vẫn commit được report nhóm + cá nhân |

### Files phải nộp (trước 18:00)

```
lab/
├── graph.py                           # Sprint 1 — bắt buộc
├── mcp_server.py                      # Sprint 3 — bắt buộc
├── eval_trace.py                      # Sprint 4 — bắt buộc
├── workers/
│   ├── retrieval.py                   # Sprint 2 — bắt buộc
│   ├── policy_tool.py                 # Sprint 2 — bắt buộc
│   └── synthesis.py                   # Sprint 2 — bắt buộc
├── contracts/
│   └── worker_contracts.yaml          # Bắt buộc (đã cập nhật)
├── artifacts/
│   ├── grading_run.jsonl              # Bắt buộc — kết quả 10 câu ẩn
│   └── traces/                        # Bắt buộc — trace 15 test questions
├── docs/
│   ├── system_architecture.md         # Bắt buộc (điền xong)
│   ├── routing_decisions.md           # Bắt buộc (≥3 quyết định thực tế)
│   └── single_vs_multi_comparison.md  # Bắt buộc (≥2 metrics có số)
```

### Files nộp sau 18:00 (được phép)

```
reports/
├── group_report.md        # Nhóm — 600-1000 từ
└── individual/
    └── [ten_ban].md       # Cá nhân — 500-800 từ
```

### Cách chạy grading (sau 17:00)

```bash
# 1. Tải grading_questions.json về data/
# 2. Chạy:
python eval_trace.py --grading
# 3. Kết quả tự động lưu vào artifacts/grading_run.jsonl
```

---

## Setup Môi Trường

```bash
# 1. Cài dependencies
pip install -r requirements.txt

# 2. Tạo .env từ template
cp .env.example .env
# Điền OPENAI_API_KEY hoặc GOOGLE_API_KEY

# 3. Build ChromaDB index (lần đầu)
python -c "from workers.retrieval import build_index; build_index()"

# 4. Test nhanh
python graph.py
```

---

## Hình Phạt (Penalties)

| Vi phạm | Hình phạt |
|---------|-----------|
| Hallucinate trong grading questions | −50% điểm câu đó |
| Trace thiếu `route_reason` | −20% điểm câu đó |
| Report cá nhân không khớp code/trace | **0/40 điểm cá nhân** |
| Nhận công lao người khác | **0/40 điểm cá nhân** |
| Report sao chép nhau | **0/40 tất cả liên quan** |
| Commit code sau 18:00 | Commit đó không tính |

---

## Câu Hỏi Thường Gặp

**Có phải dùng LangGraph không?**  
Không bắt buộc. Dùng Python thuần với if/else routing cũng được full credit. Quan trọng là trace đủ fields.

**MCP phải thật hay mock được?**  
Mock class Python được full credit. HTTP server thật được bonus +2.

**Không có Day 08 thì sao?**  
Dùng data/docs/ có sẵn. Build ChromaDB index từ script setup trong README. Baseline Day 08 có thể ước tính từ trace Day 09 (giả lập single-agent bằng cách bỏ routing).

**Nhóm 1-2 người phân vai thế nào?**  
- 1 người: Supervisor + Workers (Sprint 1+2)  
- 1 người: MCP + Trace + Docs (Sprint 3+4)

**Confidence cần tính thực tế không?**  
Không bắt buộc cho điểm cơ bản, nhưng tính thực tế được bonus +1.
