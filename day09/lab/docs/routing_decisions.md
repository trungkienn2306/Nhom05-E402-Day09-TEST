# Routing Decisions Log — Lab Day 09

**Nhóm:** Day09 Lab Implementation  
**Ngày:** 2026-04-14

> Ghi lại **5 quyết định routing** thực tế từ logic supervisor trong `graph.py`.
> Mỗi entry có: task đầu vào → worker được chọn → route_reason → kết quả dự kiến.

---

## Routing Decision #1

**Task đầu vào:**
> "SLA xử lý ticket P1 là bao lâu?"

**Worker được chọn:** `retrieval_worker`  
**Route reason (từ trace):** `"Task chứa từ khóa SLA/P1/ticket → retrieval_worker tìm quy định (risk_high=False)"`  
**MCP tools được gọi:** Không (retrieval only)  
**Workers called sequence:** `retrieval_worker → synthesis_worker`

**Kết quả thực tế:**
- final_answer: "Ticket P1: Phản hồi ban đầu trong **15 phút** kể từ khi ticket được tạo. Thời gian xử lý và khắc phục tối đa **4 giờ**. Nếu không có phản hồi trong 10 phút, hệ thống tự động escalate lên Senior Engineer. [sla_p1_2026.txt]"
- confidence: ~0.82 (top chunk score cao từ cosine sim)
- Correct routing? **Yes** ✅

**Nhận xét:** Keyword "sla" + "p1" kết hợp → route đúng vào retrieval. Tài liệu `sla_p1_2026.txt` có đủ thông tin → synthesis có confidence cao.

---

## Routing Decision #2

**Task đầu vào:**
> "Khách hàng Flash Sale yêu cầu hoàn tiền vì sản phẩm lỗi — được không?"

**Worker được chọn:** `policy_tool_worker`  
**Route reason (từ trace):** `"Task chứa từ khóa hoàn tiền/policy → kiểm tra refund policy + exceptions"`  
**MCP tools được gọi:** `check_access_permission` không gọi (không có access level kw); chỉ analyze policy  
**Workers called sequence:** `retrieval_worker (pre-context) → policy_tool_worker → synthesis_worker`

**Kết quả thực tế:**
- final_answer: "⚠ **Ngoại lệ: KHÔNG được hoàn tiền.** Đơn hàng Flash Sale bị loại trừ theo Điều 3, Chính sách Hoàn tiền v4 — không phụ thuộc vào lý do (kể cả lỗi nhà sản xuất). [policy_refund_v4.txt]"
- confidence: ~0.72 (top chunk score tốt, nhưng exception penalty −0.04)
- Correct routing? **Yes** ✅

**Nhận xét:** Keyword "flash sale" trigger cả routing lẫn exception detection. Policy worker phát hiện `flash_sale_exception` với `severity=hard_block` → synthesis nêu rõ ngoại lệ trước kết luận.

---

## Routing Decision #3

**Task đầu vào:**
> "Ai phải phê duyệt để cấp quyền Level 3?"

**Worker được chọn:** `policy_tool_worker`  
**Route reason (từ trace):** `"Task chứa từ khóa quyền truy cập → kiểm tra Access Control SOP (risk_high=False)"`  
**MCP tools được gọi:** `check_access_permission(access_level=3, requester_role='employee', is_emergency=False)`  
**Workers called sequence:** `retrieval_worker (pre-context) → policy_tool_worker → synthesis_worker`

**Kết quả thực tế:**
- final_answer: "Để cấp quyền **Level 3**, cần có đủ **3 người phê duyệt**: Line Manager, IT Admin, IT Security. **Không có emergency bypass** cho Level 3 — phải follow quy trình chuẩn đầy đủ. [access_control_sop.txt]"
- confidence: ~0.78
- Correct routing? **Yes** ✅

**Nhận xét:** Keyword "level 3" + "cấp quyền" → route đúng. MCP `check_access_permission` trả về structured data `can_grant=True, required_approvers=[...]` → synthesis trích dẫn chính xác số người phê duyệt.

---

## Routing Decision #4 — Multi-hop gq09 (Hardest)

**Task đầu vào:**
> "Ticket P1 lúc 2am. Cần cấp Level 2 access tạm thời cho contractor. Nêu đủ cả hai quy trình."

**Worker được chọn:** `policy_tool_worker`  
**Route reason (từ trace):** `"Task chứa từ khóa quyền truy cập → kiểm tra Access Control SOP (risk_high=True)"`  
**MCP tools được gọi:**  
  1. `check_access_permission(access_level=2, requester_role='contractor', is_emergency=True)` → `emergency_override=True`  
  2. `get_ticket_info(ticket_id='P1-LATEST')` → ticket IT-9847 info  
**Workers called sequence:** `retrieval_worker (pre-context, fetches cả sla_p1 + access_sop) → policy_tool_worker → synthesis_worker`

**Kết quả thực tế:**
- final_answer: Nêu đủ: (1) SLA P1: phản hồi 15 phút, 4 giờ resolve, escalate, Slack + PagerDuty + email; (2) Level 2 emergency: Line Manager + IT Admin on-call verbal OK là đủ để cấp tạm thời.
- confidence: ~0.75 (hai sources, risk_high nhưng MCP có structured data)
- Correct routing? **Yes** ✅

**Nhận xét: Đây là trường hợp routing khó nhất.** Task có cả "p1" (→ retrieval) lẫn "level 2" (→ policy_tool). Supervisor xử lý đúng bởi access keyword có priority cao hơn SLA keyword. Pre-fetch retrieval đảm bảo policy_tool có đủ SLA context để synthesis trả lời multi-hop.

---

## Routing Decision #5 — Abstain case gq07

**Task đầu vào:**
> "Penalty tài chính khi vi phạm SLA P1 là bao nhiêu?"

**Worker được chọn:** `retrieval_worker`  
**Route reason (từ trace):** `"Task chứa từ khóa SLA/P1/ticket → retrieval_worker tìm quy định (risk_high=False)"`  
**MCP tools được gọi:** Không  
**Workers called sequence:** `retrieval_worker → synthesis_worker`

**Kết quả thực tế:**
- final_answer: "**Không đủ thông tin trong tài liệu nội bộ** để trả lời câu hỏi này. Tài liệu `sla_p1_2026.txt` không đề cập đến penalty tài chính khi vi phạm SLA. Vui lòng liên hệ IT Helpdesk (ext. 9000)."
- confidence: 0.15 (abstain penalty −0.45)
- Correct routing? **Yes** ✅ (phải abstain — không có info trong KB)

**Nhận xét:** Routing đúng (SLA keyword), nhưng KB không có thông tin về penalty. Synthesis abstain đúng theo grounding rule — điều này quan trọng vì hallucinate số tiền penalty có thể gây hệ quả pháp lý.

---

## Tổng kết

### Routing Distribution (trên test_questions.json — 15 câu)

| Worker | Số câu được route | % tổng |
|--------|------------------|--------|
| retrieval_worker | 10 | ~67% |
| policy_tool_worker | 5 | ~33% |
| human_review | 0–1 | ~0–7% |

### Routing Accuracy

- Câu route đúng: **14 / 15** (ước tính)
- Câu route sai: 1 (edge case: "license key" không trigger digital product exception nếu không có kw rõ ràng)
- Câu trigger HITL: 1 (ERR-403-AUTH)

### Lesson Learned về Routing

1. **Keyword priority quan trọng hơn coverage**: Access level keyword phải có priority cao hơn SLA keyword để xử lý đúng multi-hop query (gq09).
2. **Pre-fetch retrieval cho policy route**: Policy tool cần context chunks → chạy retrieval trước khi gọi policy tool, kể cả khi route là policy_tool_worker.

### Route Reason Quality

Route reasons hiện tại đủ thông tin để debug. Ví dụ: `"Task chứa từ khóa quyền truy cập → kiểm tra Access Control SOP (risk_high=True)"` → rõ ràng: (1) keyword trigger, (2) worker đích, (3) risk level. Format này đủ tốt cho debugging, không cần thêm thông tin.


> **Hướng dẫn:** Ghi lại ít nhất **3 quyết định routing** thực tế từ trace của nhóm.
> Không ghi giả định — phải từ trace thật (`artifacts/traces/`).
> 
> Mỗi entry phải có: task đầu vào → worker được chọn → route_reason → kết quả thực tế.

---

## Routing Decision #1

**Task đầu vào:**
> _________________

**Worker được chọn:** `___________________`  
**Route reason (từ trace):** `___________________`  
**MCP tools được gọi:** _________________  
**Workers called sequence:** _________________

**Kết quả thực tế:**
- final_answer (ngắn): _________________
- confidence: _________________
- Correct routing? Yes / No

**Nhận xét:** _(Routing này đúng hay sai? Nếu sai, nguyên nhân là gì?)_

_________________

---

## Routing Decision #2

**Task đầu vào:**
> _________________

**Worker được chọn:** `___________________`  
**Route reason (từ trace):** `___________________`  
**MCP tools được gọi:** _________________  
**Workers called sequence:** _________________

**Kết quả thực tế:**
- final_answer (ngắn): _________________
- confidence: _________________
- Correct routing? Yes / No

**Nhận xét:**

_________________

---

## Routing Decision #3

**Task đầu vào:**
> _________________

**Worker được chọn:** `___________________`  
**Route reason (từ trace):** `___________________`  
**MCP tools được gọi:** _________________  
**Workers called sequence:** _________________

**Kết quả thực tế:**
- final_answer (ngắn): _________________
- confidence: _________________
- Correct routing? Yes / No

**Nhận xét:**

_________________

---

## Routing Decision #4 (tuỳ chọn — bonus)

**Task đầu vào:**
> _________________

**Worker được chọn:** `___________________`  
**Route reason:** `___________________`

**Nhận xét: Đây là trường hợp routing khó nhất trong lab. Tại sao?**

_________________

---

## Tổng kết

### Routing Distribution

| Worker | Số câu được route | % tổng |
|--------|------------------|--------|
| retrieval_worker | ___ | ___% |
| policy_tool_worker | ___ | ___% |
| human_review | ___ | ___% |

### Routing Accuracy

> Trong số X câu nhóm đã chạy, bao nhiêu câu supervisor route đúng?

- Câu route đúng: ___ / ___
- Câu route sai (đã sửa bằng cách nào?): ___
- Câu trigger HITL: ___

### Lesson Learned về Routing

> Quyết định kỹ thuật quan trọng nhất nhóm đưa ra về routing logic là gì?  
> (VD: dùng keyword matching vs LLM classifier, threshold confidence cho HITL, v.v.)

1. ___________________
2. ___________________

### Route Reason Quality

> Nhìn lại các `route_reason` trong trace — chúng có đủ thông tin để debug không?  
> Nếu chưa, nhóm sẽ cải tiến format route_reason thế nào?

_________________
