# So sánh Single Agent (Day 08) vs Multi-Agent (Day 09)

**Nhóm:** Nhóm 05 — E402  
**Ngày:** 2026-04-14  
**Nguồn dữ liệu:**
- Day 08: `day08/lab/result/scorecard_baseline.md`, `scorecard_variant.md`, `logs/grading_run.json`
- Day 09: `day09/lab/artifacts/traces/runs.jsonl`, `artifacts/eval_report_grading.json`

---

## 1. So sánh Scorecard tổng hợp (Day 08 — 10 câu test)

Bộ câu hỏi Day 08 được đánh giá theo 4 chỉ số: **Faithfulness**, **Relevance**, **Context Recall**, **Completeness** — thang điểm 1–5.

### 1.1 Day 08: Baseline Dense vs Variant Hybrid

| Metric | Baseline Dense | Variant Hybrid | Delta |
|--------|---------------|-----------------|-------|
| Faithfulness | 2.90 / 5 | 2.90 / 5 | 0.00 |
| Relevance | 4.10 / 5 | 4.20 / 5 | **+0.10** |
| Context Recall | 5.00 / 5 | 5.00 / 5 | 0.00 |
| Completeness | 3.30 / 5 | 3.40 / 5 | **+0.10** |

**Nhận xét Day 08:**
- Retrieval recall đạt 5.00/5 ở cả hai config — Knowledge Base nhỏ (5 tài liệu), segment rõ ràng → chunking đơn giản đã đủ để retrieve đúng document.
- Faithfulness ở mức trung bình (2.90/5) — single-agent có xu hướng diễn giải thêm thông tin không có trong KB, đặc biệt trên câu hỏi refund và access control.
- Variant Hybrid cải thiện nhẹ Relevance và Completeness so với Baseline Dense (+0.10 mỗi metric), nhưng không đủ có ý nghĩa thống kê với n=10.

### 1.2 Day 08: Chi tiết từng câu (Baseline vs Variant)

| ID | Category | Faithful (Base/Var) | Relevant (Base/Var) | Recall (Base/Var) | Complete (Base/Var) |
|----|----------|---------------------|---------------------|-------------------|---------------------|
| q01 | SLA | 2 / 2 | 3 / 3 | 5 / 5 | 4 / 4 |
| q02 | Refund | 3 / 3 | 5 / 5 | 5 / 5 | 5 / 5 |
| q03 | Access Control | 2 / 2 | 5 / 5 | 5 / 5 | 4 / 4 |
| q04 | Refund | 3 / 3 | 5 / 5 | 5 / 5 | 2 / 2 |
| q05 | IT Helpdesk | 3 / 3 | 5 / 5 | 5 / 5 | 5 / 5 |
| q06 | SLA | 4 / 4 | 4 / **5** | 5 / 5 | 5 / 5 |
| q07 | Access Control | 4 / **3** | 5 / 5 | 5 / 5 | 2 / 2 |
| q08 | HR Policy | 2 / **3** | 5 / 5 | 5 / 5 | 3 / **4** |
| q09 | Insufficient Context | 1 / 1 | 1 / 1 | — / — | 1 / 1 |
| q10 | Refund (Abstain) | 5 / 5 | 3 / 3 | 5 / 5 | 2 / 2 |

*Giá trị in đậm = thay đổi so với baseline. Câu q09 (ERR-403-AUTH): không có expected sources, Context Recall = N/A.*

---

## 2. So sánh Kiến trúc: Single Agent (Day 08) vs Multi-Agent (Day 09)

### 2.1 So sánh chỉ số hiệu suất

| Metric | Day 08 — Baseline Dense | Day 08 — Variant Hybrid | Day 09 — Multi-Agent | Ghi chú |
|--------|------------------------|------------------------|---------------------|---------|
| Faithfulness (avg, /5) | 2.90 | 2.90 | **~4.70** | Day 09 dùng strict grounding + citation |
| Relevance (avg, /5) | 4.10 | 4.20 | **~4.85** | Routing chính xác 100% |
| Context Recall (avg, /5) | 5.00 | 5.00 | **~5.00** | KB nhỏ → recall của cả hai thường cao |
| Completeness (avg, /5) | 3.30 | 3.40 | **~4.20** | Multi-hop được xử lý trọn vẹn hơn |
| Avg confidence (internal) | N/A (heuristic) | N/A (heuristic) | **0.679** | Day 09: weighted cosine similarity formula |
| Avg latency (ms) | ~800ms | ~900ms | **4,946ms** | Multi-agent: pre-fetch + MCP overhead |
| Abstain rate | ~10% (1/10, q09) | ~10% (1/10, q09) | **20% (2/10)** | gq07 (mức phạt tài chính) + 403-AUTH |
| MCP tool usage | N/A | N/A | **20% (2/10 câu)** | gq03, gq09 gọi MCP Tools |
| HITL triggered | N/A | N/A | **10% (1/10)** | Kích hoạt cho gq02 (temporal) |
| Routing visibility | Không có | Không có | **Có** (`route_reason` mỗi trace) | |
| Exception detection | Không có | Không có | **4 types** | flash_sale, digital, activated, temporal |
| Multi-hop accuracy (ước tính) | ~40% | ~45% | **~90%** | Xử lý gq09 (SLA + Access) hoàn hảo |

### 2.2 Phân tích theo loại câu hỏi

#### Câu hỏi đơn giản (single-document)

| Tiêu chí | Day 08 | Day 09 |
|---------|--------|--------|
| Accuracy | ~90% | ~90% |
| Latency | ~800ms | ~1,500–2,000ms |
| Observation | Đủ dùng — không cần nhiều agent | Overhead +~700ms, accuracy không cải thiện đáng kể |

**Kết luận:** Với câu hỏi chỉ cần một tài liệu (ví dụ: "SLA P1 là bao lâu?"), kiến trúc multi-agent không mang lại cải thiện về độ chính xác nhưng tốn thêm latency đáng kể. Single-agent RAG là lựa chọn hiệu quả hơn cho các use case đơn giản, latency-critical.

#### Câu hỏi multi-hop (cross-document)

| Tiêu chí | Day 08 | Day 09 |
|---------|--------|--------|
| Accuracy | ~40% | ~85% |
| Sources retrieved | Thường chỉ 1 tài liệu | 2+ tài liệu (nhờ pre-fetch retrieval) |
| Observation | Thường chỉ trả lời được một phần truy vấn | Pre-fetch retrieval + MCP structured data → synthesis đủ context |

**Kết luận:** Câu hỏi kết hợp SLA lẫn Access Control (ví dụ: "Ticket P1 + Level 2 emergency") là điểm mạnh rõ rệt nhất của kiến trúc multi-agent. Day 08 thường chỉ trả lời được một trong hai phần do single retrieval pass không đủ context đa chiều.

#### Câu hỏi cần abstain (ngoài phạm vi KB)

| Tiêu chí | Day 08 | Day 09 |
|---------|--------|--------|
| Abstain rate | ~10% (q09 — không biết) | ~13% (2/15 câu) |
| Phản hồi khi không có info | "Tôi không biết." (ngắn, không có lý giải) | Nêu rõ lý do abstain + hướng tiếp theo (liên hệ IT Helpdesk) |
| Hallucination risk | Có — một số câu diễn giải thêm không có trong KB | Thấp — confidence threshold + grounding rules strict |

**Kết luận:** Day 09 abstain đúng và rõ ràng hơn nhờ cosine similarity threshold (< 0.35). Câu trả lời "Không đủ thông tin trong tài liệu nội bộ..." kèm hướng xử lý là phản hồi phù hợp hơn về mặt nghiệp vụ so với "Tôi không biết." của Day 08.

---

## 3. Kết quả Grading Questions (Chính thức)

### 3.1 Day 09 — Grading Results Mới nhất

| ID | Câu hỏi (tóm tắt) | Route | Confidence | Abstained | Ghi chú |
|----|-------------------|-------|------------|-----------|---------|
| gq01 | SLA P1 notification steps & deadline | retrieval_worker | 0.81 | No | Cite đúng sla_p1_2026.txt |
| gq02 | Refund temporal scope (31/01/2026) | policy_tool_worker | 0.00 | **Yes** | HITL triggered (confidence fallback) |
| gq03 | Level 3 access approvals | policy_tool_worker | 0.78 | No | Gọi 2 MCP tools (access + ticket) |
| gq04 | Store credit percentage | policy_tool_worker | 0.79 | No | Trả lời chính xác 110% |
| gq05 | On-call no response escalation | retrieval_worker | 0.84 | No | Đúng Senior Engineer escalation |
| gq06 | Remote during probation | retrieval_worker | 0.85 | No | Trả lời "Không" + 3 điều kiện |
| gq07 | Financial penalty for SLA | retrieval_worker | 0.30 | **Yes** | Abstain: info not in docs |
| gq08 | Password rotation & warning | retrieval_worker | 0.84 | No | 90 ngày / 7 ngày cảnh báo |
| gq09 | P1 2am + Level 2 Emergency Access | policy_tool_worker | 0.84 | No | **Multi-hop thành công** (3 workers, 2 MCPs) |
| gq10 | Flash Sale defect refund | policy_tool_worker | 0.73 | No | Detect đúng Flash Sale exception |

**Tổng điểm raw ước tính:** 10 / 10 (Hệ thống xử lý đúng trọng tâm tất cả các task)

### 3.2 Day 08 — Grading Results (Tham khảo, từ `logs/grading_run.json`)

| ID | Câu hỏi (tóm tắt) | Answer (tóm tắt) | Nguồn | Status |
|----|-------------------|-----------------|-------|--------|
| gq01 | SLA P1 thay đổi so với phiên bản trước? | Giảm từ 6 giờ → 4 giờ (v2026.1) | sla-p1-2026.pdf | ok |
| gq02 | Remote: VPN tối đa bao nhiêu thiết bị? | Tối đa 2 thiết bị cùng lúc | helpdesk-faq.md | ok |
| gq03 | Flash Sale + đã kích hoạt → hoàn tiền? | Không — hai ngoại lệ đồng thời | refund-v4.pdf | ok |
| gq04 | Store credit = bao nhiêu % tiền gốc? | 110% | refund-v4.pdf | ok |
| gq05 | Contractor cấp Admin Access: bao lâu + điều kiện? | Tối thiểu 1 ngày, qua Jira IT-ACCESS | helpdesk-faq.md, access-control-sop.md | ok |
| gq06 | P1 lúc 2am: cấp quyền tạm thời, quy trình + thời hạn? | On-call IT Admin + Tech Lead verbal, tối đa 24 giờ | sla-p1, access-control-sop | ok |
| gq07 | Penalty tài chính khi vi phạm SLA P1? | "Tôi không biết." (abstain) | helpdesk-faq.md | ok |
| gq08 | Nghỉ phép năm báo trước bao nhiêu ngày? Khác nghỉ ốm? | 3 ngày làm việc (phép năm) vs 9:00 sáng ngày đó (ốm) | access-control-sop, leave-policy | ok |
| gq09 | Mật khẩu đổi định kỳ bao lâu? Nhắc trước mấy ngày? | 90 ngày; nhắc trước 7 ngày | helpdesk-faq.md | ok |
| gq10 | Chính sách hoàn tiền áp dụng cho đơn trước 01/02/2026? | Không — áp dụng policy v3 (không có trong hệ thống) | refund-v4.pdf | ok |

---

## 4. Phân tích Debuggability

### Day 08 — Quy trình debug khi pipeline trả lời sai

```
Khi answer sai → phải đọc toàn bộ RAG pipeline code
  → Không biết lỗi ở indexing, retrieval hay generation
  → Phải thêm print statements, re-run
  → Không có trace structure để so sánh
Thời gian ước tính: ~15–20 phút / bug
```

**Ví dụ thực tế (q04 — Sản phẩm kỹ thuật số):**  
Day 08 trả lời "...trừ khi có lỗi do nhà sản xuất" — không đúng với expected answer ("tuyệt đối không được hoàn tiền"). Để debug, cần đọc lại toàn prompt và re-test. Không có dấu vết nào cho thấy retrieval có lấy đúng đoạn ngoại lệ hay không.

### Day 09 — Quy trình debug khi pipeline trả lời sai

```
Khi answer sai → mở artifacts/traces/runs.jsonl
  → Kiểm tra supervisor_route + route_reason → route đúng chưa?
  → Kiểm tra retrieved_chunks[0].score → evidence quality?
  → Kiểm tra mcp_tools_used → MCP call có thành công không?
  → Kiểm tra confidence → abstain threshold có kích hoạt không?
  → Chạy python workers/xxx.py để reproduce độc lập
Thời gian ước tính: ~3–5 phút / bug
```

**Ví dụ thực tế (debug q15 — multi-hop):**
1. Mở trace → `retrieved_sources = ['access_control_sop.txt']` (thiếu `sla_p1_2026.txt`)
2. → Route đúng (`policy_tool_worker`), nhưng pre-fetch retrieval chỉ lấy access control chunks
3. → Nguyên nhân: query quá ngắn, semantic search không đủ để pull SLA document
4. → Xác nhận từ `worker_io_logs`: `top_score=0.812` cho access_control, nhưng SLA chunks score thấp hơn ngưỡng

---

## 5. Phân tích Extensibility

| Scenario | Day 08 | Day 09 |
|---------|--------|--------|
| Thêm 1 tool / API mới | Phải inject tool description vào system prompt → re-test toàn bộ hành vi | Thêm function vào `TOOL_REGISTRY` trong `mcp_server.py` → auto-discoverable |
| Thêm domain tri thức mới | Phải điều chỉnh system prompt + re-test toàn bộ pipeline | Thêm file `.txt` vào `data/docs/` → tự động được index khi ChromaDB rỗng |
| Thay đổi retrieval strategy | Sửa trực tiếp trong monolithic pipeline | Sửa `workers/retrieval.py` độc lập, các worker khác không bị ảnh hưởng |
| A/B test một thành phần | Phải clone toàn bộ pipeline | Swap worker (ví dụ: dense → hybrid retrieval) mà không đụng đến Supervisor hay Synthesis |
| Thêm worker chuyên biệt mới | Không thể — single agent | Thêm `billing_worker.py` + keyword routing rule trong `graph.py` |

---

## 6. Phân tích Chi phí & Latency (Cost & Latency Trade-off)

| Scenario | Day 08 | Day 09 |
|---------|--------|--------|
| Simple query (SLA P1) | 1 LLM call + 1 embed call | 1 LLM call + 1 embed call (+ retrieval overhead ~500ms) |
| Complex query (multi-hop) | 1 LLM call | 1 LLM call + 2–3 MCP HTTP calls |
| Policy query với exception | 1 LLM call | 1 LLM call + 1 `check_access_permission` MCP call |
| MCP tool call latency | N/A | ~10–50ms (in-process); ~5–20ms thêm nếu dùng HTTP MCP |
| Avg total latency | ~800–900ms | ~4,354ms (avg, bao gồm LLM generation) |

**Đánh giá cost-benefit:**  
Day 09 tốn thêm khoảng 3,500ms so với Day 08, chủ yếu do bước pre-fetch retrieval cho `policy_tool_worker` và LLM generation cho Synthesis Worker. Số lượng LLM calls tương đương (1 call cho synthesis). Chi phí tăng thêm là hợp lý khi xét đến lợi ích: multi-hop accuracy tăng ~45%, abstain accuracy được cải thiện, và debuggability giảm thời gian debug từ 20 phút xuống 5 phút.

---

## 7. Kết luận

### Multi-agent vượt trội hơn single-agent ở:

1. **Multi-hop queries:** Pre-fetch retrieval kết hợp Policy Tool Worker cho phép pipeline cross-reference nhiều tài liệu cùng lúc — accuracy tăng từ ~40% lên ~85% trên bộ câu hỏi phức hợp.
2. **Abstain accuracy:** Cosine similarity threshold (< 0.35) và grounding rules strict ngăn hallucination — pipeline trả về "không đủ thông tin" thay vì bịa số liệu.
3. **Debuggability:** `worker_io_logs` trong trace JSON → xác định lỗi trong 3–5 phút thay vì 15–20 phút.
4. **Tool integration:** MCP server cho phép mở rộng capabilities mà không cần sửa core pipeline.

### Multi-agent không cải thiện hoặc kém hơn ở:

1. **Simple single-document queries:** Accuracy tương đương (~90%) nhưng latency cao hơn ~5x.
2. **Chi phí vận hành:** Cần duy trì thêm MCP Server (Terminal 1) song song với RAG Pipeline (Terminal 2).

### Khi nào KHÔNG nên dùng multi-agent:

- Use cases chỉ cần tra cứu một tài liệu đơn giản, latency yêu cầu < 1 giây.
- Domain không có exception handling phức tạp hoặc không cần tool integration.
- Team nhỏ không có resource để maintain nhiều service.

### Hướng phát triển tiếp theo:

1. **LLM-based router:** Thay keyword matching bằng few-shot LLM classifier → giảm false negative trên paraphrased queries ("phạt tài chính" thay vì "penalty").
2. **Confidence-threshold HITL:** Tự động trigger human review khi `confidence < 0.25`, không chỉ khi có error code pattern.
3. **Streaming synthesis:** Giảm perceived latency bằng cách stream token output thay vì chờ toàn bộ response.
