"""
workers/synthesis.py — Synthesis Worker
Sprint 2: Tổng hợp câu trả lời từ retrieved_chunks và policy_result.

Input (từ AgentState):
    - task: câu hỏi
    - retrieved_chunks: evidence từ retrieval_worker
    - policy_result: kết quả từ policy_tool_worker (nếu có)

Output (vào AgentState):
    - final_answer: câu trả lời cuối với citation [source_name]
    - sources: danh sách nguồn tài liệu được cite
    - confidence: mức độ tin cậy thực sự (0.0 - 1.0)
    - worker_io_logs: log (append)

Grounding rules:
    - CHỈ dùng thông tin có trong context — không hallucinate
    - Nếu context không đủ → abstain rõ ràng
    - Cite mỗi claim với [source_file]

Gọi độc lập để test:
    python workers/synthesis.py
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

WORKER_NAME = "synthesis_worker"

# Abstain threshold: nếu top chunk score < này → abstain
ABSTAIN_SCORE_THRESHOLD = 0.35
# Confidence floor cho abstain answers
ABSTAIN_CONFIDENCE = 0.15

SYSTEM_PROMPT = """Bạn là trợ lý IT Helpdesk nội bộ. Nhiệm vụ: trả lời câu hỏi dựa HOÀN TOÀN vào tài liệu được cung cấp.

QUY TẮC BẮT BUỘC:
1. CHỈ dùng thông tin từ TÀI LIỆU THAM KHẢO bên dưới. TUYỆT ĐỐI không dùng kiến thức ngoài.
2. Nếu tài liệu KHÔNG có đủ thông tin → trả lời: "Không đủ thông tin trong tài liệu nội bộ để trả lời câu hỏi này."
3. Cuối mỗi câu quan trọng → trích dẫn nguồn: [tên_file]
4. Nếu có ngoại lệ (exception) → nêu rõ TRƯỚC khi kết luận chính.
5. Câu trả lời súc tích, có cấu trúc rõ ràng. Không dài dòng.
6. Nếu phát hiện temporal scope (đơn hàng trước ngày hiệu lực policy) → cảnh báo rõ ràng.
"""


# ─────────────────────────────────────────────────────────────────────────────
# LLM Caller — OpenAI with Gemini fallback
# ─────────────────────────────────────────────────────────────────────────────

def _call_llm(messages: List[Dict]) -> str:
    """
    Gọi LLM để tổng hợp câu trả lời.
    Priority: OpenAI gpt-4o-mini → Gemini gemini-1.5-flash → rule-based fallback
    """
    # Option A: OpenAI
    try:
        openai_key = os.getenv("OPENAI_API_KEY", "")
        if openai_key and openai_key != "your-openai-key-here":
            from openai import OpenAI
            client = OpenAI(api_key=openai_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.05,   # Very low: grounded, consistent
                max_tokens=600,
            )
            return response.choices[0].message.content.strip()
    except Exception:
        pass

    # Option B: Gemini
    try:
        google_key = os.getenv("GOOGLE_API_KEY", "")
        if google_key and google_key != "your-google-key-here":
            import google.generativeai as genai
            genai.configure(api_key=google_key)
            model = genai.GenerativeModel(
                "gemini-1.5-flash",
                system_instruction=messages[0]["content"] if messages else "",
            )
            user_msg = "\n\n".join(m["content"] for m in messages[1:])
            response = model.generate_content(user_msg)
            return response.text.strip()
    except Exception:
        pass

    # Fallback: No LLM available — synthesize deterministically from chunks
    return _rule_based_synthesis(messages)


def _rule_based_synthesis(messages: List[Dict]) -> str:
    """
    Fallback synthesis when no LLM available.
    Extracts key info from the context section in the last user message.
    """
    if not messages:
        return "[SYNTHESIS ERROR] Không có context để tổng hợp."

    user_content = next(
        (m["content"] for m in reversed(messages) if m.get("role") == "user"),
        ""
    )
    # Extract context chunks from the user message
    if "TÀI LIỆU THAM KHẢO" in user_content:
        idx = user_content.index("TÀI LIỆU THAM KHẢO")
        context_section = user_content[idx:]
        # Return a clean synthesis note
        return (
            "[Tổng hợp tự động — không có LLM]\n\n"
            + context_section[:800]
            + "\n\n(Lưu ý: Kết quả trên được tổng hợp tự động từ tài liệu. "
            "Hãy đọc trực tiếp để có thông tin chính xác nhất.)"
        )
    return "[SYNTHESIS] Không có thông tin trong tài liệu phù hợp với câu hỏi."


# ─────────────────────────────────────────────────────────────────────────────
# Context Builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_context(chunks: List[Dict], policy_result: Optional[Dict]) -> str:
    """
    Xây dựng context string có cấu trúc từ chunks + policy result.
    Format để LLM dễ reference và cite.
    """
    parts: List[str] = []

    if chunks:
        parts.append("=== TÀI LIỆU THAM KHẢO ===")
        for i, chunk in enumerate(chunks, 1):
            source = chunk.get("source", "unknown")
            text = chunk.get("text", "").strip()
            score = chunk.get("score", 0)
            parts.append(f"[Nguồn {i}] {source} (độ liên quan: {score:.2f})\n{text}")

    if policy_result:
        exceptions = policy_result.get("exceptions_found", [])
        if exceptions:
            parts.append("\n=== NGOẠI LỆ PHÁT HIỆN ===")
            for ex in exceptions:
                parts.append(f"⚠ {ex.get('type', '')}: {ex.get('rule', '')}")

        ap = policy_result.get("access_permission")
        if ap:
            parts.append("\n=== KẾT QUẢ KIỂM TRA QUYỀN TRUY CẬP ===")
            parts.append(
                f"Level {ap.get('access_level')}: can_grant={ap.get('can_grant')}, "
                f"approvers={ap.get('required_approvers')}, "
                f"emergency_override={ap.get('emergency_override')}"
            )
            notes = ap.get("notes", [])
            for note in notes:
                parts.append(f"  Note: {note}")

        p1_ticket = policy_result.get("active_p1_ticket")
        if p1_ticket:
            parts.append("\n=== THÔNG TIN TICKET P1 HIỆN TẠI ===")
            parts.append(
                f"Ticket: {p1_ticket.get('ticket_id')} | "
                f"Status: {p1_ticket.get('status')} | "
                f"Deadline SLA: {p1_ticket.get('sla_deadline')}"
            )

        version_note = policy_result.get("policy_version_note", "")
        if version_note:
            parts.append(f"\n⚠ TEMPORAL SCOPE: {version_note}")

    if not parts:
        return "(Không có tài liệu tham khảo)"

    return "\n\n".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Confidence Calculator — Real scoring, not hard-coded
# ─────────────────────────────────────────────────────────────────────────────

def _calculate_confidence(chunks: List[Dict], answer: str, policy_result: Optional[Dict]) -> float:
    """
    Tính confidence thực từ các tín hiệu:

    1. Top chunk score (cosine similarity từ ChromaDB)
    2. Số lượng chunks evidence
    3. Abstain penalty nếu câu trả lời thiếu thông tin
    4. Exception penalty nếu có hard blocks
    5. Knowledge gap penalty nếu temporal scope mismatch

    Returns:
        float in [0.0, 1.0]
    """
    if not chunks:
        return 0.1  # No evidence → very low

    # Signal 1: top chunk cosine similarity
    top_score = max(c.get("score", 0) for c in chunks)
    avg_score = sum(c.get("score", 0) for c in chunks) / len(chunks)

    # Signal 2: weighted combination (top matters more)
    base_confidence = 0.65 * top_score + 0.35 * avg_score

    # Signal 3: evidence breadth bonus (more sources = more confident)
    unique_sources = len({c.get("source", "") for c in chunks})
    breadth_bonus = min(0.08, 0.04 * (unique_sources - 1))

    # Signal 4: Abstain penalty
    abstain_phrases = [
        "không đủ thông tin", "không có trong tài liệu", "không tìm thấy",
        "not found", "tài liệu nội bộ không có", "synthesis error",
        "tổng hợp tự động",
    ]
    is_abstain = any(phrase in answer.lower() for phrase in abstain_phrases)
    abstain_penalty = 0.45 if is_abstain else 0.0

    # Signal 5: Exception/knowledge gap penalty
    exception_penalty = 0.0
    if policy_result:
        exceptions = policy_result.get("exceptions_found", [])
        # Knowledge gap is worse than known exceptions
        for ex in exceptions:
            if ex.get("severity") == "knowledge_gap":
                exception_penalty += 0.12
            else:
                exception_penalty += 0.04

    confidence = base_confidence + breadth_bonus - abstain_penalty - exception_penalty
    return round(max(0.05, min(0.97, confidence)), 3)


# ─────────────────────────────────────────────────────────────────────────────
# Abstain Check
# ─────────────────────────────────────────────────────────────────────────────

def _should_abstain(chunks: List[Dict], policy_result: Optional[Dict]) -> Optional[str]:
    """
    Kiểm tra xem có nên abstain không.

    Returns:
        str: abstain message nếu nên abstain
        None: nếu có đủ evidence để trả lời
    """
    if not chunks:
        return (
            "Không đủ thông tin trong tài liệu nội bộ để trả lời câu hỏi này. "
            "Vui lòng liên hệ IT Helpdesk (ext. 9000) để được hỗ trợ trực tiếp."
        )

    top_score = max((c.get("score", 0) for c in chunks), default=0)
    if top_score < ABSTAIN_SCORE_THRESHOLD:
        return (
            f"Tài liệu nội bộ không có thông tin đủ liên quan đến câu hỏi này "
            f"(độ liên quan cao nhất: {top_score:.2f} < ngưỡng {ABSTAIN_SCORE_THRESHOLD}). "
            "Vui lòng liên hệ IT Helpdesk (ext. 9000) để được hỗ trợ trực tiếp."
        )

    # Check for temporal scope mismatch (knowledge gap)
    if policy_result:
        exceptions = policy_result.get("exceptions_found", [])
        temporal = [e for e in exceptions if e.get("type") == "temporal_scope_mismatch"]
        if temporal and len(exceptions) == 1:
            return (
                "Câu hỏi này liên quan đến đơn hàng đặt trước 01/02/2026, thuộc phạm vi "
                "Chính sách Hoàn tiền v3 — tài liệu này chưa có trong hệ thống nội bộ. "
                "Vui lòng liên hệ bộ phận Kế toán hoặc Customer Service để áp dụng chính sách cũ."
            )

    return None  # Do not abstain — proceed with synthesis


# ─────────────────────────────────────────────────────────────────────────────
# Synthesize
# ─────────────────────────────────────────────────────────────────────────────

def synthesize(task: str, chunks: List[Dict], policy_result: Optional[Dict]) -> Dict:
    """
    Tổng hợp câu trả lời từ chunks và policy context.

    Returns:
        {"answer": str, "sources": list[str], "confidence": float, "abstained": bool}
    """
    # Check abstain first (fast path)
    abstain_msg = _should_abstain(chunks, policy_result)
    if abstain_msg:
        sources = list({c.get("source", "unknown") for c in chunks}) if chunks else []
        confidence = ABSTAIN_CONFIDENCE
        return {
            "answer": abstain_msg,
            "sources": sources,
            "confidence": confidence,
            "abstained": True,
        }

    # Build context
    context = _build_context(chunks, policy_result)

    # Build messages
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Câu hỏi: {task}\n\n"
                f"{context}\n\n"
                "Hãy trả lời câu hỏi trên dựa HOÀN TOÀN vào tài liệu tham khảo. "
                "Trích dẫn nguồn bằng [tên_file] sau mỗi claim. "
                "Nếu có ngoại lệ → nêu TRƯỚC. "
                "Nếu không đủ thông tin → nói rõ không đủ thông tin."
            ),
        },
    ]

    answer = _call_llm(messages)
    sources = list({c.get("source", "unknown") for c in chunks})
    confidence = _calculate_confidence(chunks, answer, policy_result)

    return {
        "answer": answer,
        "sources": sources,
        "confidence": confidence,
        "abstained": False,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Worker Entry Point — run(state)
# ─────────────────────────────────────────────────────────────────────────────

def run(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Synthesis Worker — theo contract worker_contracts.yaml.
    Input:  task, retrieved_chunks, policy_result
    Output: final_answer, sources, confidence, worker_io_logs (append)
    """
    task = state.get("task", "")
    chunks = state.get("retrieved_chunks", [])
    policy_result = state.get("policy_result") or {}

    io_log = {
        "worker": WORKER_NAME,
        "input": {
            "task": task[:120],
            "chunks_count": len(chunks),
            "has_policy": bool(policy_result),
            "top_chunk_score": max((c.get("score", 0) for c in chunks), default=0),
        },
        "timestamp_start": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }

    try:
        result = synthesize(task, chunks, policy_result)

        io_log.update({
            "output": {
                "answer_length": len(result["answer"]),
                "sources": result["sources"],
                "confidence": result["confidence"],
                "abstained": result.get("abstained", False),
            },
            "status": "success",
            "timestamp_end": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        })

        print(f"[SYNTHESIS] conf={result['confidence']:.3f} | "
              f"abstained={result.get('abstained', False)} | "
              f"sources={result['sources']}")

        updated = dict(state)
        updated["final_answer"] = result["answer"]
        updated["sources"] = result["sources"]
        updated["confidence"] = result["confidence"]
        updated.setdefault("worker_io_logs", [])
        updated["worker_io_logs"].append(io_log)
        return updated

    except Exception as exc:
        io_log.update({
            "status": "error",
            "error": {"code": "SYNTHESIS_FAILED", "reason": str(exc)},
            "timestamp_end": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        })
        updated = dict(state)
        updated["final_answer"] = f"[SYNTHESIS ERROR] {exc}"
        updated["sources"] = []
        updated["confidence"] = 0.0
        updated.setdefault("worker_io_logs", [])
        updated["worker_io_logs"].append(io_log)
        print(f"[SYNTHESIS] ERROR: {exc}")
        return updated


# ─────────────────────────────────────────────────────────────────────────────
# Standalone Test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("SYNTHESIS WORKER — Standalone Test")
    print("=" * 60)

    tests = [
        {
            "label": "Normal SLA query",
            "state": {
                "task": "SLA ticket P1 là bao lâu?",
                "retrieved_chunks": [
                    {
                        "text": "Ticket P1: Phản hồi ban đầu 15 phút. Xử lý tối đa 4 giờ. Auto-escalate sau 10 phút không có phản hồi. Thông báo: Slack #incident-p1, email, PagerDuty.",
                        "source": "sla_p1_2026.txt",
                        "score": 0.91,
                    }
                ],
                "policy_result": {},
            },
        },
        {
            "label": "Flash Sale exception",
            "state": {
                "task": "Khách hàng Flash Sale yêu cầu hoàn tiền vì sản phẩm lỗi — được không?",
                "retrieved_chunks": [
                    {
                        "text": "Ngoại lệ: Đơn hàng Flash Sale không được hoàn tiền theo Điều 3, chính sách v4.",
                        "source": "policy_refund_v4.txt",
                        "score": 0.89,
                    }
                ],
                "policy_result": {
                    "policy_applies": False,
                    "exceptions_found": [
                        {"type": "flash_sale_exception",
                         "rule": "Flash Sale không được hoàn tiền.",
                         "severity": "hard_block"}
                    ],
                },
            },
        },
        {
            "label": "Abstain: unknown error code",
            "state": {
                "task": "Mã lỗi ERR-403-AUTH nghĩa là gì?",
                "retrieved_chunks": [
                    {"text": "Hướng dẫn đổi mật khẩu sau 90 ngày.", "source": "it_helpdesk_faq.txt", "score": 0.18}
                ],
                "policy_result": {},
            },
        },
        {
            "label": "Empty context → full abstain",
            "state": {
                "task": "Penalty tài chính khi vi phạm SLA P1?",
                "retrieved_chunks": [],
                "policy_result": {},
            },
        },
    ]

    for test in tests:
        print(f"\n{'─'*55}")
        print(f"▶ [{test['label']}] {test['state']['task'][:65]}")
        result = run(dict(test["state"]))
        print(f"  confidence : {result.get('confidence'):.3f}")
        print(f"  sources    : {result.get('sources')}")
        print(f"  answer     : {result.get('final_answer', '')[:200]}")

    print("\n✅ synthesis_worker test done.")
