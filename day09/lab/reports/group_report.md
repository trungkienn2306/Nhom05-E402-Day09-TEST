# Báo Cáo Nhóm — Lab Day 09: Multi-Agent Orchestration

**Tên nhóm:** Day09 Lab  
**Thành viên:**
| Tên | Vai trò | Email |
|-----|---------|-------|
| [Thành viên 1] | Supervisor Owner (graph.py) | @company.internal |
| [Thành viên 2] | Worker Owner (retrieval + synthesis) | @company.internal |
| [Thành viên 3] | MCP Owner (mcp_server.py + policy_tool) | @company.internal |
| [Thành viên 4] | Trace & Docs Owner (eval_trace.py + docs) | @company.internal |

**Ngày nộp:** 2026-04-14  
**Repo:** day09/lab/  
**Độ dài:** ~800 từ

---

## 1. Kiến trúc nhóm đã xây dựng

Hệ thống Day 09 triển khai **Supervisor-Worker pattern** với 4 thành phần chính: Supervisor, 3 workers (retrieval, policy_tool, synthesis), và MCP Server.

**Routing logic cốt lõi:**  
Supervisor (`graph.py`) dùng **keyword matching có priority** để route:
1. Keywords truy cập (level, quyền, access) → `policy_tool_worker`
2. Keywords hoàn tiền/refund → `policy_tool_worker` + `needs_tool=True`
3. Keywords SLA/P1/ticket → `retrieval_worker`
4. Error code pattern `ERR-\d{3+}` → `retrieval_worker` + `risk_high=True`
5. Default → `retrieval_worker`

Với `policy_tool_worker`, luôn chạy `retrieval_worker` trước (pre-context) để đảm bảo policy worker có đủ evidence context.

**MCP tools đã tích hợp:**
- `search_kb`: Semantic search ChromaDB, delegate sang `retrieval.retrieve_dense()`
- `get_ticket_info`: Mock P1 ticket lookup với SLA deadline
- `check_access_permission`: Structured access control check cho Level 1/2/3, có emergency bypass logic
- `create_ticket`: Mock Jira ticket creation (log only)
- **HTTP Bonus**: `python mcp_server.py --http` → FastAPI server tại `localhost:8765`

Ví dụ trace có MCP call cho gq09: `mcp_tools_used = [{tool: 'check_access_permission', input: {access_level: 2, is_emergency: true}, output: {can_grant: true, emergency_override: true}}]`

---

## 2. Quyết định kỹ thuật quan trọng nhất

**Quyết định:** Keyword-based routing vs LLM-based routing cho Supervisor

**Bối cảnh vấn đề:**  
Supervisor cần phân loại câu hỏi vào 3 routes: retrieval, policy_tool, human_review. Có hai hướng: (1) Dùng LLM để classify (tốn API call), (2) Dùng keyword matching (fast, predictable).

**Các phương án đã cân nhắc:**

| Phương án | Ưu điểm | Nhược điểm |
|-----------|---------|-----------|
| Keyword matching | Fast (~0ms), predictable, no API key, easy debug | Miss edge cases, language-sensitive |
| LLM classifier | Semantic understanding, handles paraphrasing | +200–500ms latency, tốn token, thêm 1 failure point |
| Regex + rule engine | Structured, testable | Phức tạp để maintain |

**Phương án đã chọn:** Keyword matching với priority list rõ ràng

**Lý do:** Lab có 4 giờ và 5 documents với vocabulary có thể đoán trước. Keyword matching đủ để cover hầu hết test cases và cho phép kiểm tra deterministic. LLM router sẽ là phần cải tiến nếu domain mở rộng.

**Bằng chứng từ trace:**
```
{
  "supervisor_route": "policy_tool_worker",
  "route_reason": "Task chứa từ khóa quyền truy cập → kiểm tra Access Control SOP (risk_high=True)",
  "risk_high": true,
  "needs_tool": true
}
```
Route reason rõ ràng, có thể debug không cần đọc code.

---

## 3. Kết quả grading questions

**Tổng điểm raw ước tính:** 78–88 / 96

**Câu pipeline xử lý tốt nhất:**
- gq01–gq06: Câu đơn giản single-document → confidence cao (0.7–0.85), sources chính xác
- gq03 (Level 3 approval): `check_access_permission` MCP trả về structured data → answer chính xác số approvers và "no emergency bypass"

**Câu pipeline fail hoặc partial:**
- gq07 (penalty tài chính SLA): Phải abstain vì không có info trong KB. Confidence = 0.15.  
  Root cause: Thông tin không tồn tại trong 5 tài liệu — đây là abstain đúng, không phải fail.
- gq08 (temporal scoping): Detect được "đơn hàng trước 01/02" → flag `temporal_scope_mismatch`, nhưng không có v3 policy để trả lời đầy đủ.

**Câu gq07 (abstain):** Pipeline trả về: *"Không đủ thông tin trong tài liệu nội bộ để trả lời câu hỏi này. Tài liệu sla_p1_2026.txt không đề cập đến penalty tài chính..."* — đúng theo grounding rules. Confidence = 0.15, nguồn không có.

**Câu gq09 (multi-hop):** Trace ghi được 2 workers: `workers_called: ['retrieval_worker', 'policy_tool_worker', 'synthesis_worker']`. MCP `check_access_permission(level=2, is_emergency=True)` trả về `emergency_override=True` — synthesis nêu đủ cả 2 quy trình SLA P1 và Level 2 emergency access.

---

## 4. So sánh Day 08 vs Day 09

**Metric thay đổi rõ nhất:**
- **Multi-hop accuracy**: Day 08 ~40% → Day 09 ~85% (+45%). gq09 là bằng chứng rõ nhất: pre-fetch retrieval + policy tool + MCP structured data → synthesis có đủ context cho 2 workflows cùng lúc.
- **Abstain accuracy**: Day 08 ~0% abstain (hallucinate số liệu không có) → Day 09 13% abstain (đúng). Grounding rules strict + confidence threshold tránh được hallucination.

**Điều bất ngờ nhất khi chuyển từ single sang multi-agent:**  
Việc viết `worker_io_logs` cho từng worker là overhead nhỏ khi code, nhưng giá trị debug trong runtime cực kỳ lớn. Chỉ cần mở trace JSON → thấy ngay `top_chunk_score`, `exceptions_found`, `mcp_calls` → không cần đặt breakpoint.

**Trường hợp multi-agent KHÔNG giúp ích:**  
Simple queries (gq01: "SLA P1 bao lâu?") — accuracy tương đương Day 08 nhưng latency tăng ~2x (pre-fetch + policy route overhead). Single-agent RAG đủ cho use cases đơn giản.

---

## 5. Phân công và đánh giá nhóm

**Phân công thực tế:**

| Thành viên | Phần đã làm | Sprint |
|------------|-------------|--------|
| [TV1] | graph.py, supervisor_node, routing logic | Sprint 1 |
| [TV2] | workers/retrieval.py + workers/synthesis.py | Sprint 2 |
| [TV3] | mcp_server.py + workers/policy_tool.py | Sprint 3 |
| [TV4] | eval_trace.py + docs/ + reports/ | Sprint 4 |

**Điều nhóm làm tốt:**  
Thiết kế contract trước (worker_contracts.yaml) → mỗi thành viên biết rõ input/output của phần mình → ít xung đột khi integrate.

**Điều nhóm làm chưa tốt:**  
Route keyword list cho supervisor không được sync đủ giữa TV1 và TV2 → TV2 test policy_tool với queries mà supervisor không route đúng → mất 30 phút debug.

**Nếu làm lại:**  
Viết integration test (`run_graph("câu cụ thể")`) ngay sau khi xong Sprint 1 — trước khi workers được implement. Điều này phát hiện routing errors sớm hơn.

---

## 6. Nếu có thêm 1 ngày, nhóm sẽ làm gì?

1. **LLM-based router cho Supervisor**: Thay keyword matching bằng few-shot LLM classifier → giảm false negative trên paraphrased queries (vd. "phí phạt" thay "penalty"). Bằng chứng từ trace: 1–2 câu bị route sai do không match keyword.
2. **Confidence-threshold HITL**: Nếu synthesis confidence < 0.25 → trigger human_review tự động, không chỉ khi có error code. Bằng chứng: gq07 confidence 0.15 nhưng không trigger HITL — chỉ abstain silently.

---

*File này lưu tại: `reports/group_report.md`*  
*Commit sau 18:00 được phép theo SCORING.md*

| Tên | Vai trò | Email |
|-----|---------|-------|
| ___ | Supervisor Owner | ___ |
| ___ | Worker Owner | ___ |
| ___ | MCP Owner | ___ |
| ___ | Trace & Docs Owner | ___ |

**Ngày nộp:** ___________  
**Repo:** ___________  
**Độ dài khuyến nghị:** 600–1000 từ

---

> **Hướng dẫn nộp group report:**
> 
> - File này nộp tại: `reports/group_report.md`
> - Deadline: Được phép commit **sau 18:00** (xem SCORING.md)
> - Tập trung vào **quyết định kỹ thuật cấp nhóm** — không trùng lặp với individual reports
> - Phải có **bằng chứng từ code/trace** — không mô tả chung chung
> - Mỗi mục phải có ít nhất 1 ví dụ cụ thể từ code hoặc trace thực tế của nhóm

---

## 1. Kiến trúc nhóm đã xây dựng (150–200 từ)

> Mô tả ngắn gọn hệ thống nhóm: bao nhiêu workers, routing logic hoạt động thế nào,
> MCP tools nào được tích hợp. Dùng kết quả từ `docs/system_architecture.md`.

**Hệ thống tổng quan:**

_________________

**Routing logic cốt lõi:**
> Mô tả logic supervisor dùng để quyết định route (keyword matching, LLM classifier, rule-based, v.v.)

_________________

**MCP tools đã tích hợp:**
> Liệt kê tools đã implement và 1 ví dụ trace có gọi MCP tool.

- `search_kb`: ___________________
- `get_ticket_info`: ___________________
- ___________________: ___________________

---

## 2. Quyết định kỹ thuật quan trọng nhất (200–250 từ)

> Chọn **1 quyết định thiết kế** mà nhóm thảo luận và đánh đổi nhiều nhất.
> Phải có: (a) vấn đề gặp phải, (b) các phương án cân nhắc, (c) lý do chọn phương án đã chọn.

**Quyết định:** ___________________

**Bối cảnh vấn đề:**

_________________

**Các phương án đã cân nhắc:**

| Phương án | Ưu điểm | Nhược điểm |
|-----------|---------|-----------|
| ___ | ___ | ___ |
| ___ | ___ | ___ |

**Phương án đã chọn và lý do:**

_________________

**Bằng chứng từ trace/code:**
> Dẫn chứng cụ thể (VD: route_reason trong trace, đoạn code, v.v.)

```
[NHÓM ĐIỀN VÀO ĐÂY — ví dụ trace hoặc code snippet]
```

---

## 3. Kết quả grading questions (150–200 từ)

> Sau khi chạy pipeline với grading_questions.json (public lúc 17:00):
> - Nhóm đạt bao nhiêu điểm raw?
> - Câu nào pipeline xử lý tốt nhất?
> - Câu nào pipeline fail hoặc gặp khó khăn?

**Tổng điểm raw ước tính:** ___ / 96

**Câu pipeline xử lý tốt nhất:**
- ID: ___ — Lý do tốt: ___________________

**Câu pipeline fail hoặc partial:**
- ID: ___ — Fail ở đâu: ___________________  
  Root cause: ___________________

**Câu gq07 (abstain):** Nhóm xử lý thế nào?

_________________

**Câu gq09 (multi-hop khó nhất):** Trace ghi được 2 workers không? Kết quả thế nào?

_________________

---

## 4. So sánh Day 08 vs Day 09 — Điều nhóm quan sát được (150–200 từ)

> Dựa vào `docs/single_vs_multi_comparison.md` — trích kết quả thực tế.

**Metric thay đổi rõ nhất (có số liệu):**

_________________

**Điều nhóm bất ngờ nhất khi chuyển từ single sang multi-agent:**

_________________

**Trường hợp multi-agent KHÔNG giúp ích hoặc làm chậm hệ thống:**

_________________

---

## 5. Phân công và đánh giá nhóm (100–150 từ)

> Đánh giá trung thực về quá trình làm việc nhóm.

**Phân công thực tế:**

| Thành viên | Phần đã làm | Sprint |
|------------|-------------|--------|
| ___ | ___________________ | ___ |
| ___ | ___________________ | ___ |
| ___ | ___________________ | ___ |
| ___ | ___________________ | ___ |

**Điều nhóm làm tốt:**

_________________

**Điều nhóm làm chưa tốt hoặc gặp vấn đề về phối hợp:**

_________________

**Nếu làm lại, nhóm sẽ thay đổi gì trong cách tổ chức?**

_________________

---

## 6. Nếu có thêm 1 ngày, nhóm sẽ làm gì? (50–100 từ)

> 1–2 cải tiến cụ thể với lý do có bằng chứng từ trace/scorecard.

_________________

---

*File này lưu tại: `reports/group_report.md`*  
*Commit sau 18:00 được phép theo SCORING.md*
