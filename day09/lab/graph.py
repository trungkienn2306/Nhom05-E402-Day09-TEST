"""
Sprint 1 — Supervisor Orchestrator (IMPLEMENTED)
=================================================
Supervisor-Worker pattern — Python thuần, không cần LangGraph.

Kiến trúc:
    Input → Supervisor → [retrieval_worker|policy_tool_worker|human_review] → synthesis → Output

Chạy thử:
    python graph.py
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, TypedDict

from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# AgentState — Shared state toàn pipeline
# ─────────────────────────────────────────────────────────────────────────────

class AgentState(TypedDict, total=False):
    """Shared state truyền qua toàn bộ pipeline."""
    # Input
    task: str
    # Supervisor
    supervisor_route: str
    route_reason: str
    risk_high: bool
    needs_tool: bool
    hitl_triggered: bool
    # Workers
    retrieved_chunks: List[Dict]
    retrieved_sources: List[str]
    policy_result: Optional[Dict]
    mcp_tools_used: List[Dict]
    # Final
    final_answer: str
    sources: List[str]
    confidence: float
    # Trace
    history: List[Dict]
    workers_called: List[str]
    worker_io_logs: List[Dict]
    latency_ms: float
    run_id: str
    timestamp: str


def make_initial_state(task: str) -> AgentState:
    """Khởi tạo state cho một run mới."""
    return {
        "task": task,
        "supervisor_route": "",
        "route_reason": "",
        "risk_high": False,
        "needs_tool": False,
        "hitl_triggered": False,
        "retrieved_chunks": [],
        "retrieved_sources": [],
        "policy_result": None,
        "mcp_tools_used": [],
        "final_answer": "",
        "sources": [],
        "confidence": 0.0,
        "history": [],
        "workers_called": [],
        "worker_io_logs": [],
        "latency_ms": 0.0,
        "run_id": f"run_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:18]}",
        "timestamp": datetime.now().isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Routing Keywords
# ─────────────────────────────────────────────────────────────────────────────

_POLICY_ACCESS = [
    "cấp quyền", "access level", "admin access", "level 1", "level 2",
    "level 3", "level 4", "quyền truy cập", "elevated access",
    "emergency access", "phê duyệt quyền",
]
_POLICY_REFUND = [
    "hoàn tiền", "refund", "flash sale", "flashsale", "store credit",
    "chính sách hoàn", "policy hoàn", "license", "bản quyền",
    "subscription", "kỹ thuật số", "digital", "kích hoạt",
]
_SLA_P1 = [
    "p1", "sla", "ticket", "escalation", "sự cố", "incident",
    "on-call", "pagerduty", "severity", "triage", "critical",
    "phản hồi ban đầu",
]
_HIGH_RISK = [
    "khẩn cấp", "emergency", "p1", "2am", "ngoài giờ",
    "tạm thời", "sự cố nghiêm trọng",
]


def _has(text: str, keywords: List[str]) -> bool:
    t = text.lower()
    return any(k in t for k in keywords)


def _has_error_code(text: str) -> bool:
    return bool(re.search(r'\b(err|error)-\d{3,}', text.lower()))


# ─────────────────────────────────────────────────────────────────────────────
# Supervisor Node
# ─────────────────────────────────────────────────────────────────────────────

def supervisor_node(state: AgentState) -> AgentState:
    """
    Supervisor: phân tích task, quyết định route.
    KHÔNG tự trả lời domain knowledge.
    """
    task = state.get("task", "")
    risk_high = _has(task, _HIGH_RISK)
    needs_tool = _has(task, ["contractor", "ticket", "access", "cấp quyền", "p1"])

    # Routing priority
    if _has(task, _POLICY_ACCESS):
        route = "policy_tool_worker"
        route_reason = (
            f"Task chứa từ khóa quyền truy cập → kiểm tra Access Control SOP "
            f"(risk_high={risk_high})"
        )
    elif _has(task, _POLICY_REFUND):
        route = "policy_tool_worker"
        route_reason = "Task chứa từ khóa hoàn tiền/policy → kiểm tra refund policy + exceptions"
        needs_tool = True
    elif _has(task, _POLICY_ACCESS + _POLICY_REFUND) and _has(task, _SLA_P1):
        # Multi-hop: cả policy lẫn SLA
        route = "policy_tool_worker"
        route_reason = "Multi-hop query: kết hợp policy + SLA → policy_tool_worker cross-reference"
        needs_tool = True
        risk_high = True
    elif _has(task, _SLA_P1):
        route = "retrieval_worker"
        route_reason = (
            f"Task chứa từ khóa SLA/P1/ticket → retrieval_worker tìm quy định "
            f"(risk_high={risk_high})"
        )
    elif _has_error_code(task):
        route = "retrieval_worker"
        route_reason = "Task chứa mã lỗi không rõ → retrieval trước, abstain nếu không có kết quả"
        risk_high = True
    else:
        route = "retrieval_worker"
        route_reason = "Default: retrieval_worker tìm kiếm tổng quát trong Knowledge Base"

    updated = dict(state)
    updated["supervisor_route"] = route
    updated["route_reason"] = route_reason
    updated["risk_high"] = risk_high
    updated["needs_tool"] = needs_tool
    updated.setdefault("history", [])
    updated.setdefault("workers_called", [])
    updated.setdefault("mcp_tools_used", [])
    updated.setdefault("worker_io_logs", [])

    updated["history"].append({
        "step": "supervisor",
        "route": route,
        "reason": route_reason,
        "risk_high": risk_high,
        "needs_tool": needs_tool,
        "timestamp": datetime.now().isoformat(),
    })

    print(f"\n[SUPERVISOR] Task: {task[:80]}...")
    print(f"[SUPERVISOR] → Route: {route}")
    print(f"[SUPERVISOR] → Reason: {route_reason}")
    print(f"[SUPERVISOR] → risk_high={risk_high}, needs_tool={needs_tool}")
    return updated


# ─────────────────────────────────────────────────────────────────────────────
# Route Decision
# ─────────────────────────────────────────────────────────────────────────────

def route_decision(state: AgentState) -> str:
    return state.get("supervisor_route", "retrieval_worker")


# ─────────────────────────────────────────────────────────────────────────────
# Human Review Node
# ─────────────────────────────────────────────────────────────────────────────

def human_review_node(state: AgentState) -> AgentState:
    """HITL fallback — log và trả placeholder answer."""
    updated = dict(state)
    updated["hitl_triggered"] = True
    updated["final_answer"] = (
        "[HUMAN REVIEW REQUIRED] Câu hỏi này cần xem xét thủ công. "
        "Không tìm thấy thông tin trong Knowledge Base hoặc câu hỏi chứa "
        "mã lỗi không xác định. Vui lòng liên hệ IT Helpdesk (ext. 9000)."
    )
    updated["confidence"] = 0.0
    updated["sources"] = []
    updated["retrieved_sources"] = []
    updated.setdefault("workers_called", [])
    updated["workers_called"].append("human_review")
    updated["history"].append({
        "step": "human_review",
        "reason": "HITL triggered",
        "timestamp": datetime.now().isoformat(),
    })
    print(f"[HUMAN_REVIEW] ⚠️  HITL triggered for: {state.get('task', '')[:60]}")
    return updated


# ─────────────────────────────────────────────────────────────────────────────
# run_graph — Entry Point
# ─────────────────────────────────────────────────────────────────────────────

def run_graph(task: str) -> Dict[str, Any]:
    """
    Entry point chính: Chạy toàn bộ pipeline với 1 câu hỏi.
    Returns dict state sau khi pipeline hoàn thành.
    """
    from workers.retrieval import run as retrieval_run
    from workers.policy_tool import run as policy_tool_run
    from workers.synthesis import run as synthesis_run

    t0 = time.time()
    state = make_initial_state(task)

    # Step 1: Supervisor
    state = supervisor_node(state)
    route = route_decision(state)

    # Step 2: Route to worker
    if route == "human_review":
        state = human_review_node(state)
    elif route == "policy_tool_worker":
        # Pre-fetch retrieval context for policy worker
        print(f"\n[GRAPH] Running retrieval_worker (pre-context)")
        state = retrieval_run(state)
        state.setdefault("workers_called", [])
        state["workers_called"].append("retrieval_worker")

        print(f"\n[GRAPH] Running policy_tool_worker")
        state = policy_tool_run(state)
        state["workers_called"].append("policy_tool_worker")
    else:
        print(f"\n[GRAPH] Running retrieval_worker")
        state = retrieval_run(state)
        state.setdefault("workers_called", [])
        state["workers_called"].append("retrieval_worker")

    # Step 3: Synthesis (trừ HITL)
    if not state.get("hitl_triggered", False):
        print(f"\n[GRAPH] Running synthesis_worker")
        state = synthesis_run(state)
        state["workers_called"].append("synthesis_worker")

    state["latency_ms"] = round((time.time() - t0) * 1000, 1)

    print(f"\n[GRAPH] ✅ Complete | Route={state.get('supervisor_route')} | "
          f"Workers={state.get('workers_called')} | "
          f"Conf={state.get('confidence', 0):.2f} | "
          f"Latency={state['latency_ms']}ms")
    return state


def save_trace(state: Dict, output_dir: str = "./artifacts/traces") -> str:
    """Lưu trace ra file JSON."""
    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"{state.get('run_id', 'run_unknown')}.json")
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, default=str)
    return filename


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 70)
    print("Day 09 Lab — Multi-Agent Orchestration (graph.py)")
    print("=" * 70)

    test_queries = [
        "SLA xử lý ticket P1 là bao lâu?",
        "Khách hàng Flash Sale yêu cầu hoàn tiền vì sản phẩm lỗi — được không?",
        "Ai phải phê duyệt để cấp quyền Level 3?",
        "Ticket P1 lúc 2am. Cần cấp Level 2 access tạm thời cho contractor. Nêu đủ cả hai quy trình.",
    ]

    for i, query in enumerate(test_queries, 1):
        print(f"\n{'='*70}")
        print(f"TEST {i}: {query}")
        print("=" * 70)
        result = run_graph(query)
        print(f"\n✅ FINAL ANSWER:\n{result.get('final_answer', '')[:300]}")
        print(f"\n   Sources: {result.get('retrieved_sources', [])}")
        print(f"   Route: {result.get('supervisor_route')} | Confidence: {result.get('confidence', 0):.2f}")

        trace_file = save_trace(result)
        print(f"   Trace → {trace_file}")
