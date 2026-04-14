# Routing Decisions Log — Lab Day 09: Multi-Agent RAG Orchestration

**Nhóm:** Nhóm 05 — E402  
**Ngày:** 2026-04-14  
**Nguồn dữ liệu:** `day09/lab/artifacts/traces/runs.jsonl` (15 runs thực tế)

> Ghi lại 5 quyết định routing thực tế từ logic Supervisor trong `graph.py`.  
> Mỗi entry bao gồm: truy vấn đầu vào → worker được chọn → `route_reason` từ trace → kết quả thực tế và nhận xét kỹ thuật.

---

## Routing Decision #1 — SLA đơn giản

**Truy vấn đầu vào:**
> "SLA xử lý ticket P1 là bao lâu?"

**Worker được chọn:** `retrieval_worker`  
**Route reason (từ trace):** `"Task chứa từ khóa SLA/P1/ticket → retrieval_worker tìm quy định (risk_high=True)"`  
**MCP tools được gọi:** Không (retrieval only)  
**Workers called sequence:** `retrieval_worker → synthesis_worker`

**Kết quả thực tế:**
- `final_answer`: "SLA xử lý ticket P1: Phản hồi ban đầu **15 phút** kể từ khi ticket được tạo. Xử lý và khắc phục tối đa **4 giờ**. Tự động escalate lên Senior Engineer nếu không có phản hồi trong 10 phút. [sla_p1_2026.txt]"
- `confidence`: 0.814 (top chunk cosine score = 0.8178)
- `retrieved_sources`: `['sla_p1_2026.txt']`
- Routing chính xác? **Có** ✓

**Nhận xét kỹ thuật:**  
Tổ hợp keyword `"sla"` và `"p1"` kích hoạt đồng thời → route chính xác vào `retrieval_worker`. Tài liệu `sla_p1_2026.txt` chứa thông tin SLA đầy đủ → top chunk score cao → Synthesis Worker sinh câu trả lời với confidence cao. Đây là trường hợp đơn giản nhất trong bộ test — single-document, không cần exception detection hay MCP tool call.

---

## Routing Decision #2 — Exception phát hiện: Flash Sale

**Truy vấn đầu vào:**
> "Khách hàng Flash Sale yêu cầu hoàn tiền vì sản phẩm lỗi — được không?"

**Worker được chọn:** `policy_tool_worker`  
**Route reason (từ trace):** `"Task chứa từ khóa hoàn tiền/policy → kiểm tra refund policy + exceptions"`  
**MCP tools được gọi:** Không (exception phát hiện qua keyword matching; không có access level keyword → `check_access_permission` không kích hoạt)  
**Workers called sequence:** `retrieval_worker (pre-context) → policy_tool_worker → synthesis_worker`

**Kết quả thực tế:**
- `final_answer`: "Không thể hoàn tiền cho khách hàng Flash Sale — đơn hàng đã áp dụng mã giảm giá đặc biệt theo chương trình Flash Sale, thuộc danh mục ngoại lệ không được hoàn tiền theo Điều 3. [policy_refund_v4.txt]"
- `confidence`: 0.737 (exception penalty −0.04 trừ vào base score)
- `exceptions_found`: `[flash_sale_exception (severity=hard_block)]`
- Routing chính xác? **Có** ✓

**Nhận xét kỹ thuật:**  
Từ khóa `"flash sale"` đồng thời kích hoạt cả routing sang `policy_tool_worker` và exception detection bên trong worker đó. Policy Tool Worker phát hiện `flash_sale_exception` với `severity=hard_block` → Synthesis Worker nêu ngoại lệ trước kết luận chính, đúng theo grounding rule. Đây là pattern quan trọng nhất của architecture này: Supervisor quyết định *ai làm*, Policy Tool quyết định *exception nào áp dụng*.

---

## Routing Decision #3 — MCP Tool Call: check_access_permission

**Truy vấn đầu vào:**
> "Ai phải phê duyệt để cấp quyền Level 3?"

**Worker được chọn:** `policy_tool_worker`  
**Route reason (từ trace):** `"Task chứa từ khóa quyền truy cập → kiểm tra Access Control SOP (risk_high=False)"`  
**MCP tools được gọi:**  
- `check_access_permission(access_level=3, requester_role='employee', is_emergency=False)` → `can_grant=True, required_approvers=['Line Manager', 'IT Admin', 'IT Security'], emergency_override=False`

**Workers called sequence:** `retrieval_worker (pre-context) → policy_tool_worker → synthesis_worker`

**Kết quả thực tế:**
- `final_answer`: "Để cấp quyền Level 3, cần có sự phê duyệt của **3 người**: Line Manager, IT Admin và IT Security. Không có cơ chế emergency bypass cho Level 3 — phải tuân theo quy trình chuẩn đầy đủ. [access_control_sop.txt]"
- `confidence`: 0.799
- `mcp_tools_used`: 1 call
- Routing chính xác? **Có** ✓

**Nhận xét kỹ thuật:**  
Từ khóa `"level 3"` kết hợp với `"cấp quyền"` → route sang `policy_tool_worker`. Hàm `_detect_access_level()` trích xuất được `access_level=3` → kích hoạt MCP call `check_access_permission`. MCP Server trả về structured data với danh sách approvers rõ ràng → Synthesis Worker trích dẫn chính xác số lượng người phê duyệt mà không cần parse text thô từ chunks. Đây là lợi thế rõ ràng của kiến trúc MCP: dữ liệu có cấu trúc giúp giảm thiểu hallucination.

---

## Routing Decision #4 — Multi-hop khó nhất: P1 + Level 2 Emergency

**Truy vấn đầu vào:**
> "Ticket P1 lúc 2am. Cần cấp Level 2 access tạm thời cho contractor. Nêu đủ cả hai quy trình."

**Worker được chọn:** `policy_tool_worker`  
**Route reason (từ trace):** `"Task chứa từ khóa quyền truy cập → kiểm tra Access Control SOP (risk_high=True)"`  
**MCP tools được gọi:**
1. `check_access_permission(access_level=2, requester_role='contractor', is_emergency=True)` → `emergency_override=True, required_approvers=['Line Manager', 'IT Admin']`
2. `get_ticket_info(ticket_id='P1-LATEST')` → ticket IT-9847, `sla_deadline='2026-04-14T02:47:00'`, `escalated=True`

**Workers called sequence:** `retrieval_worker (pre-context, fetches sla_p1_2026.txt + access_control_sop.txt) → policy_tool_worker → synthesis_worker`

**Kết quả thực tế:**
- `final_answer`: Trình bày đầy đủ hai quy trình: (1) SLA P1: phản hồi 15 phút, resolve 4 giờ, escalate, kênh thông báo Slack/PagerDuty/email; (2) Level 2 emergency: Line Manager + IT Admin on-call verbal approval là đủ để cấp tạm thời.
- `confidence`: 0.851 (hai source documents, MCP structured data, risk_high)
- `retrieved_sources`: `['sla_p1_2026.txt', 'access_control_sop.txt']`
- Routing chính xác? **Có** ✓

**Nhận xét kỹ thuật — Đây là trường hợp routing khó nhất trong bộ test:**  
Truy vấn chứa cả keyword SLA/P1 (→ `retrieval_worker`) lẫn keyword access/level (→ `policy_tool_worker`). Supervisor xử lý đúng vì access keyword được đặt ở vị trí ưu tiên cao hơn trong routing logic. Pre-fetch retrieval đảm bảo Policy Tool Worker có context từ cả hai tài liệu (`sla_p1_2026.txt` và `access_control_sop.txt`) trước khi thực hiện MCP calls. Kết quả: Synthesis Worker nhận đủ bằng chứng để trả lời multi-hop với confidence cao (0.851).

---

## Routing Decision #5 — Abstain chính xác: Không có thông tin trong KB

**Truy vấn đầu vào:**
> "Penalty tài chính khi vi phạm SLA P1 là bao nhiêu?"

**Worker được chọn:** `retrieval_worker`  
**Route reason (từ trace):** `"Task chứa từ khóa SLA/P1/ticket → retrieval_worker tìm quy định (risk_high=True)"`  
**MCP tools được gọi:** Không  
**Workers called sequence:** `retrieval_worker → synthesis_worker`

**Kết quả thực tế:**
- `final_answer`: "Không đủ thông tin trong tài liệu nội bộ để trả lời câu hỏi này. Tài liệu `sla_p1_2026.txt` không đề cập đến penalty tài chính khi vi phạm SLA. Vui lòng liên hệ IT Helpdesk (ext. 9000)."
- `confidence`: 0.15 (abstain penalty −0.45 được áp dụng)
- `retrieved_chunks`: Tìm được 3 chunks, nhưng nội dung không liên quan đến penalty tài chính
- Routing chính xác? **Có** ✓ (abstract đúng — không có thông tin trong KB)

**Nhận xét kỹ thuật:**  
Routing đúng vào `retrieval_worker` (SLA keyword), nhưng Knowledge Base không chứa thông tin về penalty tài chính. Synthesis Worker phát hiện câu trả lời chứa phrase abstain → áp dụng penalty `−0.45` → confidence = 0.15. Pipeline abstain đúng và rõ ràng thay vì hallucinate một con số penalty có thể gây hệ quả pháp lý. Điều này minh chứng tầm quan trọng của grounding rules nghiêm ngặt trong domain nhạy cảm.

---

## Tổng kết

### Routing Distribution (trên 10 câu grading_questions.json)

| Worker | Số câu được route | Tỷ lệ |
|--------|------------------|-------|
| `retrieval_worker` | 5 | 50% |
| `policy_tool_worker` | 5 | 50% |
| `human_review` | 1 | 10% |

*(Số liệu thực tế từ artifacts/grading_run.jsonl)*

### Routing Accuracy

- Câu route chính xác: **10 / 10** (100% chính xác về mặt logic điều hướng)
- Câu trigger HITL: **1 / 10** (Câu gq02 — đơn hàng ngày 31/01/2026). Đây là minh chứng cho tính hiệu quả của cơ chế "Post-synthesis fallback": Dù Supervisor route đúng vào Policy Worker, nhưng Synthesis phát hiện ra sự thiếu hụt tài liệu (v3 policy) → confidence = 0.0 → đẩy sang Human Review.

### Bài học kỹ thuật về Routing

1. **Thứ tự ưu tiên keyword quyết định routing multi-hop**: Access keyword phải có priority cao hơn SLA keyword trong routing logic. Nếu không, truy vấn như "Ticket P1 + Level 2 access" (Routing Decision #4) sẽ bị route nhầm vào `retrieval_worker` và không kích hoạt được MCP `check_access_permission`.

2. **Pre-fetch retrieval là bắt buộc cho policy route**: Policy Tool Worker cần context chunks để phân tích exception và enrich MCP output. Khi `supervisor_route = "policy_tool_worker"`, `graph.py` luôn chạy `retrieval_worker` trước nhằm đảm bảo Synthesis Worker nhận được đầy đủ bằng chứng từ Knowledge Base.

### Chất lượng Route Reason

Toàn bộ `route_reason` trong trace đều có đủ thông tin để debug: ghi rõ (1) keyword nào kích hoạt, (2) worker đích, (3) giá trị `risk_high`. Ví dụ: `"Task chứa từ khóa quyền truy cập → kiểm tra Access Control SOP (risk_high=True)"` → đủ để tái hiện lại quyết định routing mà không cần đọc code. Format này được giữ nguyên vì đáp ứng yêu cầu traceability của hệ thống production.
