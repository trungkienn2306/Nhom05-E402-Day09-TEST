# System Architecture — Lab Day 09

**Nhóm:** Day09 Lab Implementation  
**Ngày:** 2026-04-14  
**Version:** 1.0

---

## 1. Tổng quan kiến trúc

Hệ thống triển khai pattern **Supervisor-Worker** — một Supervisor phân tích câu hỏi và điều phối tới đúng worker chuyên trách. Không có worker nào tự trả lời trực tiếp; mọi câu trả lời đều qua Synthesis Worker có citation.

**Pattern đã chọn:** Supervisor-Worker  
**Lý do chọn pattern này (thay vì single agent):**

- **Separation of Concerns**: Retrieval, policy checking, synthesis là 3 concerns riêng biệt → dễ test độc lập.
- **Debuggability**: Mỗi bước ghi `worker_io_logs` → khi sai dễ xác định lỗi ở worker nào.
- **Extensibility**: Thêm worker mới (vd. `billing_worker`) không cần sửa core — chỉ thêm route và import.
- **MCP Integration**: Policy tool worker gọi MCP tools mà không cần retrieval worker biết.

---

## 2. Sơ đồ Pipeline

```
                        User Request (task: str)
                               │
                               ▼
                    ┌──────────────────────┐
                    │     SUPERVISOR       │
                    │    (graph.py)        │
                    │  Keyword routing:    │
                    │  - access/refund KW  │─→ policy_tool_worker
                    │  - sla/p1/ticket KW  │─→ retrieval_worker
                    │  - error code        │─→ retrieval_worker
                    │  - default           │─→ retrieval_worker
                    │  Output:             │
                    │  supervisor_route    │
                    │  route_reason        │
                    │  risk_high, needs_tool│
                    └──────────┬───────────┘
                               │
              ┌────────────────┴──────────────────┐
              │                                   │
              ▼                                   ▼
  ┌───────────────────────┐         ┌─────────────────────────────┐
  │   RETRIEVAL WORKER    │         │    POLICY TOOL WORKER        │
  │  (workers/retrieval.py│         │  (workers/policy_tool.py)    │
  │                       │         │                              │
  │  ChromaDB semantic    │         │  1. Pre-fetch via            │
  │  search (cosine sim)  │         │     MCP search_kb (if thin)  │
  │  all-MiniLM-L6-v2     │         │  2. Exception detection:     │
  │  paragraph chunks     │         │     flash sale / digital /   │
  │                       │         │     activated / temporal     │
  │  Output:              │         │  3. MCP check_access_perm    │
  │  retrieved_chunks     │         │     (if access level found)  │
  │  retrieved_sources    │         │  4. MCP get_ticket_info      │
  └──────────┬────────────┘         │     (if P1/risk_high)        │
             │    (also runs first) │  Output:                     │
             │    for policy route  │  policy_result               │
             └──────────┬───────────┘  mcp_tools_used              │
                        │              └──────────────┬────────────┘
                        │                             │
                        └──────────┬──────────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────┐
                    │    SYNTHESIS WORKER       │
                    │  (workers/synthesis.py)   │
                    │                           │
                    │  1. Abstain check:        │
                    │     top_score < 0.35?     │
                    │     temporal scope miss?  │
                    │  2. LLM call (GPT-4o-mini │
                    │     / Gemini / fallback)  │
                    │  3. Confidence = f(score, │
                    │     breadth, exceptions)  │
                    │  4. Citation [source.txt] │
                    │                           │
                    │  Output:                  │
                    │  final_answer             │
                    │  sources                  │
                    │  confidence               │
                    └──────────────┬────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────┐
                    │        OUTPUT             │
                    │  final_answer (cited)     │
                    │  confidence ∈ [0, 1]      │
                    │  sources: list[str]       │
                    │  latency_ms               │
                    │  trace JSON saved         │
                    └──────────────────────────┘

         [HITL path: error code không rõ → human_review node]
```

---

## 3. Vai trò từng thành phần

### Supervisor (`graph.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **Nhiệm vụ** | Phân tích task, quyết định route, KHÔNG tự trả lời |
| **Input** | task (str từ user) |
| **Output** | supervisor_route, route_reason, risk_high, needs_tool |
| **Routing logic** | Keyword matching priority: access_kw → policy_tool; refund_kw → policy_tool; sla_kw → retrieval; error_code → retrieval+HITL |
| **HITL condition** | Error code không rõ (ERR-xxx pattern) hoặc không tìm thấy context |

### Retrieval Worker (`workers/retrieval.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **Nhiệm vụ** | Semantic search trong ChromaDB từ 5 tài liệu .txt |
| **Embedding model** | all-MiniLM-L6-v2 (SentenceTransformers, offline, no API key) |
| **Top-k** | 3 mặc định, configurable qua state["top_k"] |
| **Stateless?** | Yes — `_collection_cache` là module-level singleton, không lưu state ngoài |
| **Index build** | Auto-build khi collection empty, paragraph-level chunks (≥30 chars) |

### Policy Tool Worker (`workers/policy_tool.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **Nhiệm vụ** | Phân tích policy exceptions + gọi MCP tools cho access control và ticket info |
| **MCP tools gọi** | search_kb (khi chunks mỏng), check_access_permission (khi có level kw), get_ticket_info (khi risk_high + P1) |
| **Exception cases xử lý** | flash_sale, digital_product, activated_product, temporal_scope_mismatch (v3 không có trong KB) |

### Synthesis Worker (`workers/synthesis.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **LLM model** | gpt-4o-mini (primary) → gemini-1.5-flash (fallback) → rule-based (final fallback) |
| **Temperature** | 0.05 — cực thấp để grounded, tránh hallucination |
| **Grounding strategy** | System prompt strict: CHỈ dùng context, abstain nếu không đủ, cite mọi claim |
| **Abstain condition** | top_score < 0.35 OR no chunks OR temporal scope v3 mismatch |
| **Confidence calculation** | 0.65 × top_score + 0.35 × avg_score + breadth_bonus − abstain_penalty − exception_penalty |

### MCP Server (`mcp_server.py`)

| Tool | Input | Output |
|------|-------|--------|
| search_kb | query: str, top_k: int | chunks: list, sources: list, total_found: int |
| get_ticket_info | ticket_id: str | ticket details dict (P1-LATEST mock) |
| check_access_permission | access_level: int, requester_role: str, is_emergency: bool | can_grant, required_approvers, emergency_override, notes |
| create_ticket | priority: str, title: str, description: str | ticket_id, url, created_at (MOCK) |

**HTTP Bonus**: `python mcp_server.py --http` → FastAPI server tại `http://localhost:8765`

---

## 4. Shared State Schema

| Field | Type | Mô tả | Ai đọc/ghi |
|-------|------|-------|-----------| 
| task | str | Câu hỏi đầu vào | supervisor đọc |
| supervisor_route | str | Worker được chọn | supervisor ghi |
| route_reason | str | Lý do route (human-readable) | supervisor ghi |
| risk_high | bool | Task có rủi ro cao (P1, emergency) | supervisor ghi, policy_tool đọc |
| needs_tool | bool | Cần MCP tool call | supervisor ghi, policy_tool đọc |
| retrieved_chunks | list[dict] | Evidence từ retrieval | retrieval ghi, synthesis/policy đọc |
| retrieved_sources | list[str] | File names của sources | retrieval ghi |
| policy_result | dict | Exceptions, access permission, ticket info | policy_tool ghi, synthesis đọc |
| mcp_tools_used | list[dict] | Mọi tool calls với input/output | policy_tool ghi |
| final_answer | str | Câu trả lời cuối có citation | synthesis ghi |
| confidence | float | 0.0-1.0 từ cosine sim + signals | synthesis ghi |
| sources | list[str] | Danh sách files được cite | synthesis ghi |
| workers_called | list[str] | Sequence of workers executed | graph.py ghi |
| worker_io_logs | list[dict] | Chi tiết input/output từng worker | mỗi worker append |
| latency_ms | float | Total end-to-end latency | graph.py ghi |
| run_id | str | Unique ID cho mỗi run | make_initial_state() |
| hitl_triggered | bool | Human review activated | human_review_node ghi |

---

## 5. Lý do chọn Supervisor-Worker so với Single Agent (Day 08)

| Tiêu chí | Single Agent (Day 08) | Supervisor-Worker (Day 09) |
|----------|----------------------|--------------------------|
| Debug khi sai | Khó — không rõ lỗi ở đâu trong prompt | Dễ — test từng worker độc lập với `python workers/xxx.py` |
| Thêm capability mới | Phải sửa toàn prompt và re-test | Thêm worker/MCP tool riêng, không ảnh hưởng core |
| Routing visibility | Không có — black box | Có route_reason rõ ràng trong mỗi trace JSON |
| Exception handling | Hard-code trong prompt | Policy worker + MCP layer riêng |
| Tool use | Phải inject tool descriptions vào prompt | MCP server expose schema, dispatch tự động |
| Latency | Thấp hơn (1 LLM call) | Cao hơn (multi-step), but more accurate |

**Quan sát thực tế:**  
Policy tool worker gọi `check_access_permission` MCP → synthesis nhận structured data thay vì phải LLM parse text thô → giảm hallucination trên access control questions.

---

## 6. Giới hạn và điểm cần cải tiến

1. **Routing bằng keyword matching**: Dễ miss edge cases (vd. "Phạt tài chính do SLA P1?" bị route vào retrieval nhưng không có info trong KB → đúng nhưng chậm). Cải tiến: LLM-based router với few-shot examples.
2. **Temporal scoping chỉ detect tháng 1**: Nếu user hỏi "đơn năm 2024" → không detect. Cần regex date parsing chính xác hơn.
3. **HITL chỉ dùng error code pattern**: Nếu câu hỏi không có trong KB nhưng không có error code → synthesis abstain nhưng không trigger HITL. Cần confidence threshold HITL trigger.


---

## 1. Tổng quan kiến trúc

> Mô tả ngắn hệ thống của nhóm: chọn pattern gì, gồm những thành phần nào.

**Pattern đã chọn:** Supervisor-Worker  
**Lý do chọn pattern này (thay vì single agent):**

_________________

---

## 2. Sơ đồ Pipeline

> Vẽ sơ đồ pipeline dưới dạng text, Mermaid diagram, hoặc ASCII art.
> Yêu cầu tối thiểu: thể hiện rõ luồng từ input → supervisor → workers → output.

**Ví dụ (ASCII art):**
```
User Request
     │
     ▼
┌──────────────┐
│  Supervisor  │  ← route_reason, risk_high, needs_tool
└──────┬───────┘
       │
   [route_decision]
       │
  ┌────┴────────────────────┐
  │                         │
  ▼                         ▼
Retrieval Worker     Policy Tool Worker
  (evidence)           (policy check + MCP)
  │                         │
  └─────────┬───────────────┘
            │
            ▼
      Synthesis Worker
        (answer + cite)
            │
            ▼
         Output
```

**Sơ đồ thực tế của nhóm:**

```
[NHÓM ĐIỀN VÀO ĐÂY]
```

---

## 3. Vai trò từng thành phần

### Supervisor (`graph.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **Nhiệm vụ** | ___________________ |
| **Input** | ___________________ |
| **Output** | supervisor_route, route_reason, risk_high, needs_tool |
| **Routing logic** | ___________________ |
| **HITL condition** | ___________________ |

### Retrieval Worker (`workers/retrieval.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **Nhiệm vụ** | ___________________ |
| **Embedding model** | ___________________ |
| **Top-k** | ___________________ |
| **Stateless?** | Yes / No |

### Policy Tool Worker (`workers/policy_tool.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **Nhiệm vụ** | ___________________ |
| **MCP tools gọi** | ___________________ |
| **Exception cases xử lý** | ___________________ |

### Synthesis Worker (`workers/synthesis.py`)

| Thuộc tính | Mô tả |
|-----------|-------|
| **LLM model** | ___________________ |
| **Temperature** | ___________________ |
| **Grounding strategy** | ___________________ |
| **Abstain condition** | ___________________ |

### MCP Server (`mcp_server.py`)

| Tool | Input | Output |
|------|-------|--------|
| search_kb | query, top_k | chunks, sources |
| get_ticket_info | ticket_id | ticket details |
| check_access_permission | access_level, requester_role | can_grant, approvers |
| ___________________ | ___________________ | ___________________ |

---

## 4. Shared State Schema

> Liệt kê các fields trong AgentState và ý nghĩa của từng field.

| Field | Type | Mô tả | Ai đọc/ghi |
|-------|------|-------|-----------|
| task | str | Câu hỏi đầu vào | supervisor đọc |
| supervisor_route | str | Worker được chọn | supervisor ghi |
| route_reason | str | Lý do route | supervisor ghi |
| retrieved_chunks | list | Evidence từ retrieval | retrieval ghi, synthesis đọc |
| policy_result | dict | Kết quả kiểm tra policy | policy_tool ghi, synthesis đọc |
| mcp_tools_used | list | Tool calls đã thực hiện | policy_tool ghi |
| final_answer | str | Câu trả lời cuối | synthesis ghi |
| confidence | float | Mức tin cậy | synthesis ghi |
| ___________________ | ___________________ | ___________________ | ___________________ |

---

## 5. Lý do chọn Supervisor-Worker so với Single Agent (Day 08)

| Tiêu chí | Single Agent (Day 08) | Supervisor-Worker (Day 09) |
|----------|----------------------|--------------------------|
| Debug khi sai | Khó — không rõ lỗi ở đâu | Dễ hơn — test từng worker độc lập |
| Thêm capability mới | Phải sửa toàn prompt | Thêm worker/MCP tool riêng |
| Routing visibility | Không có | Có route_reason trong trace |
| ___________________ | ___________________ | ___________________ |

**Nhóm điền thêm quan sát từ thực tế lab:**

_________________

---

## 6. Giới hạn và điểm cần cải tiến

> Nhóm mô tả những điểm hạn chế của kiến trúc hiện tại.

1. ___________________
2. ___________________
3. ___________________
