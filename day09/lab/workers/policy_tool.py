"""
workers/policy_tool.py — Policy & Tool Worker
Sprint 2+3: Kiểm tra policy dựa vào context, gọi MCP tools khi cần.

Input (từ AgentState):
    - task: câu hỏi
    - retrieved_chunks: context từ retrieval_worker
    - needs_tool: True nếu supervisor quyết định cần tool call
    - risk_high: True nếu câu hỏi có rủi ro cao

Output (vào AgentState):
    - policy_result: {policy_applies, policy_name, exceptions_found, source, rule}
    - mcp_tools_used: list of tool calls đã thực hiện
    - worker_io_logs: log (append)

Gọi độc lập để test:
    python workers/policy_tool.py
"""

from __future__ import annotations

import re
import sys
import io
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

# Force UTF-8 stdout/stderr tren Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

WORKER_NAME = "policy_tool_worker"

# ─────────────────────────────────────────────────────────────────────────────
# Keyword sets for exception detection
# ─────────────────────────────────────────────────────────────────────────────

_FLASH_SALE_KW = ["flash sale", "flashsale", "flash_sale"]
_DIGITAL_KW = [
    "license key", "license", "subscription", "kỹ thuật số", "digital",
    "bản quyền", "phần mềm", "software key",
]
_ACTIVATED_KW = [
    "đã kích hoạt", "đã đăng ký", "đã sử dụng", "already activated",
    "kích hoạt rồi", "activated",
]
_TEMPORAL_KW = [
    "31/01", "30/01", "29/01", "01/01", "trước 01/02", "before 01/02",
    "january", "tháng 1", "trước tháng 2",
]
_ACCESS_LEVEL_MAP = {
    "level 1": 1, "level1": 1, "cấp 1": 1,
    "level 2": 2, "level2": 2, "cấp 2": 2,
    "level 3": 3, "level3": 3, "cấp 3": 3,
    "level 4": 4, "level4": 4, "cấp 4": 4,
}
_EMERGENCY_KW = [
    "khẩn cấp", "emergency", "2am", "ngoài giờ", "tạm thời",
    "tạm thời", "on-call", "outside hours",
]


# ─────────────────────────────────────────────────────────────────────────────
# Helper: keyword detection
# ─────────────────────────────────────────────────────────────────────────────

def _has(text: str, keywords: List[str]) -> bool:
    t = text.lower()
    return any(k in t for k in keywords)


def _detect_access_level(text: str) -> Optional[int]:
    """Trả về access level số nếu tìm thấy trong text."""
    t = text.lower()
    for kw, lvl in _ACCESS_LEVEL_MAP.items():
        if kw in t:
            return lvl
    return None


def _detect_exceptions(task: str, context_text: str) -> List[Dict]:
    """
    Phát hiện các exception cases trong refund policy.
    Kiểm tra cả task lẫn retrieved context.
    """
    combined = (task + " " + context_text).lower()
    exceptions = []

    if _has(combined, _FLASH_SALE_KW):
        exceptions.append({
            "type": "flash_sale_exception",
            "rule": "Đơn hàng Flash Sale không được hoàn tiền theo Điều 3, Chính sách Hoàn tiền v4.",
            "source": "policy_refund_v4.txt",
            "severity": "hard_block",
        })

    if _has(combined, _DIGITAL_KW):
        exceptions.append({
            "type": "digital_product_exception",
            "rule": "Sản phẩm kỹ thuật số (license key, phần mềm, subscription) không được hoàn tiền theo Điều 3.",
            "source": "policy_refund_v4.txt",
            "severity": "hard_block",
        })

    if _has(combined, _ACTIVATED_KW):
        exceptions.append({
            "type": "activated_product_exception",
            "rule": "Sản phẩm đã kích hoạt hoặc đã đăng ký tài khoản không được hoàn tiền theo Điều 3.",
            "source": "policy_refund_v4.txt",
            "severity": "hard_block",
        })

    if _has(combined, _TEMPORAL_KW):
        exceptions.append({
            "type": "temporal_scope_mismatch",
            "rule": "Đơn hàng đặt trước 01/02/2026 áp dụng Chính sách Hoàn tiền v3 — không có trong tài liệu hiện tại.",
            "source": "policy_refund_v4.txt",
            "severity": "knowledge_gap",
        })

    return exceptions


# ─────────────────────────────────────────────────────────────────────────────
# MCP HTTP Client
# ─────────────────────────────────────────────────────────────────────────────

# URL của MCP HTTP server (Terminal 1: python mcp_server.py)
MCP_BASE_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8765")


def _call_mcp(tool_name: str, tool_input: Dict) -> Dict:
    """
    Gọi MCP tool qua HTTP REST API (http://localhost:8765/tools/{tool_name}).

    Yêu cầu: MCP Server phải đang chạy ở Terminal 1.
        Terminal 1: python day09/lab/mcp_server.py
        Terminal 2: python day09/lab/graph.py (hoặc eval_trace.py)

    Logs tool call với timestamp để trace.
    """
    import requests

    url = f"{MCP_BASE_URL}/tools/{tool_name}"
    try:
        resp = requests.post(url, json=tool_input, timeout=5)
        resp.raise_for_status()
        # Dat encoding ro rang truoc khi decode JSON
        # (tranh requests tu detect sai charset tren Windows)
        resp.encoding = 'utf-8'
        output = resp.json()
        return {
            "tool": tool_name,
            "input": tool_input,
            "output": output,
            "error": None,
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        }
    except requests.exceptions.ConnectionError:
        error_msg = (
            f"Không thể kết nối đến MCP Server tại {MCP_BASE_URL}. "
            f"Vui lòng mở Terminal 1 và chạy: python day09/lab/mcp_server.py"
        )
        print(f"[POLICY_TOOL] [ERROR] MCP CONNECTION ERROR: {error_msg}")
        return {
            "tool": tool_name,
            "input": tool_input,
            "output": None,
            "error": {"code": "MCP_CONNECTION_ERROR", "reason": error_msg},
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        }
    except requests.exceptions.Timeout:
        return {
            "tool": tool_name,
            "input": tool_input,
            "output": None,
            "error": {"code": "MCP_TIMEOUT", "reason": f"Request tới {url} timeout sau 5 giây."},
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        }
    except Exception as exc:
        return {
            "tool": tool_name,
            "input": tool_input,
            "output": None,
            "error": {"code": "MCP_HTTP_FAILED", "reason": str(exc)},
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Core Policy Analysis
# ─────────────────────────────────────────────────────────────────────────────

def analyze_policy(task: str, chunks: List[Dict]) -> Dict:
    """
    Phân tích policy dựa trên task và retrieved chunks.

    Logic:
    1. Phát hiện exceptions (flash sale, digital, activated, temporal)
    2. Xác định access level nếu có
    3. Xác định policy name và version
    4. Tính policy_applies dựa trên exceptions

    Returns:
        Dict: {policy_applies, policy_name, exceptions_found, sources,
               access_level_detected, is_emergency, policy_version_note}
    """
    task_lower = task.lower()
    context_text = " ".join(c.get("text", "") for c in chunks)

    exceptions_found = _detect_exceptions(task, context_text)

    # Temporal scope: if knowledge gap exception → policy_applies = None (unknown)
    has_knowledge_gap = any(e["type"] == "temporal_scope_mismatch" for e in exceptions_found)
    hard_blocks = [e for e in exceptions_found if e.get("severity") == "hard_block"]

    if hard_blocks:
        policy_applies = False
        policy_name = "refund_policy_v4"
    elif has_knowledge_gap:
        policy_applies = None   # Unknown — v3 not in docs
        policy_name = "refund_policy_v3_UNKNOWN"
    else:
        policy_applies = True
        policy_name = "refund_policy_v4"

    # Access level detection for access control queries
    access_level = _detect_access_level(task)
    is_emergency = _has(task, _EMERGENCY_KW)

    sources = list({c.get("source", "unknown") for c in chunks if c})

    return {
        "policy_applies": policy_applies,
        "policy_name": policy_name,
        "exceptions_found": exceptions_found,
        "sources": sources,
        "access_level_detected": access_level,
        "is_emergency": is_emergency,
        "policy_version_note": (
            "Đơn hàng trước 01/02/2026 áp dụng policy v3 — không có trong KB hiện tại."
            if has_knowledge_gap else ""
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Worker Entry Point — run(state)
# ─────────────────────────────────────────────────────────────────────────────

def run(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Policy Tool Worker — theo contract worker_contracts.yaml.
    Input:  task (str), retrieved_chunks (list), needs_tool (bool)
    Output: policy_result, mcp_tools_used, worker_io_logs (append)

    MCP tool call sequence:
    1. search_kb → nếu chunks chưa đủ
    2. check_access_permission → nếu task liên quan quyền truy cập
    3. get_ticket_info → nếu task đề cập P1/ticket cụ thể
    """
    task = state.get("task", "")
    chunks = state.get("retrieved_chunks", [])
    needs_tool = state.get("needs_tool", False)
    risk_high = state.get("risk_high", False)

    mcp_tools_used = list(state.get("mcp_tools_used", []))

    io_log = {
        "worker": WORKER_NAME,
        "input": {
            "task": task[:120],
            "chunks_count": len(chunks),
            "needs_tool": needs_tool,
            "risk_high": risk_high,
        },
        "timestamp_start": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }

    try:
        # ── Step 1: Supplement retrieval via MCP if chunks thin ──────────────
        if needs_tool and len(chunks) < 2:
            mcp_res = _call_mcp("search_kb", {"query": task, "top_k": 5})
            mcp_tools_used.append(mcp_res)
            if mcp_res.get("output") and mcp_res["output"].get("chunks"):
                extra_chunks = mcp_res["output"]["chunks"]
                # Merge deduplicated
                existing_ids = {c.get("text", "")[:50] for c in chunks}
                for c in extra_chunks:
                    if c.get("text", "")[:50] not in existing_ids:
                        chunks.append(c)
            print(f"[POLICY_TOOL] MCP search_kb → {len(mcp_tools_used[-1].get('output', {}).get('chunks', []))} chunks")

        # ── Step 2: Analyze policy ───────────────────────────────────────────
        policy_result = analyze_policy(task, chunks)

        # ── Step 3: check_access_permission via MCP ─────────────────────────
        access_level = policy_result.get("access_level_detected")
        if access_level is not None:
            is_emergency = policy_result.get("is_emergency", False)
            mcp_res = _call_mcp("check_access_permission", {
                "access_level": access_level,
                "requester_role": "contractor" if "contractor" in task.lower() else "employee",
                "is_emergency": is_emergency,
            })
            mcp_tools_used.append(mcp_res)
            # Enrich policy_result with MCP response
            if mcp_res.get("output") and not mcp_res["output"].get("error"):
                policy_result["access_permission"] = mcp_res["output"]
            print(f"[POLICY_TOOL] MCP check_access_permission(level={access_level}, emergency={is_emergency})"
                  f" → can_grant={mcp_res.get('output', {}).get('can_grant')}")

        # ── Step 4: get_ticket_info via MCP ─────────────────────────────────
        if risk_high and any(kw in task.lower() for kw in ["p1", "ticket", "incident", "sự cố"]):
            mcp_res = _call_mcp("get_ticket_info", {"ticket_id": "P1-LATEST"})
            mcp_tools_used.append(mcp_res)
            if mcp_res.get("output") and not mcp_res["output"].get("error"):
                policy_result["active_p1_ticket"] = mcp_res["output"]
            print(f"[POLICY_TOOL] MCP get_ticket_info → ticket={mcp_res.get('output', {}).get('ticket_id')}")

        io_log.update({
            "output": {
                "policy_applies": policy_result["policy_applies"],
                "exceptions_count": len(policy_result.get("exceptions_found", [])),
                "mcp_calls": len(mcp_tools_used),
                "access_level": access_level,
            },
            "status": "success",
            "timestamp_end": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        })

        print(f"[POLICY_TOOL] policy_applies={policy_result['policy_applies']} | "
              f"exceptions={len(policy_result.get('exceptions_found', []))} | "
              f"mcp_calls={len(mcp_tools_used)}")

        updated = dict(state)
        updated["retrieved_chunks"] = chunks
        updated["policy_result"] = policy_result
        updated["mcp_tools_used"] = mcp_tools_used
        updated.setdefault("worker_io_logs", [])
        updated["worker_io_logs"].append(io_log)
        return updated

    except Exception as exc:
        io_log.update({
            "status": "error",
            "error": {"code": "POLICY_TOOL_FAILED", "reason": str(exc)},
            "timestamp_end": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        })
        updated = dict(state)
        updated["policy_result"] = {"error": str(exc), "policy_applies": None, "exceptions_found": []}
        updated["mcp_tools_used"] = mcp_tools_used
        updated.setdefault("worker_io_logs", [])
        updated["worker_io_logs"].append(io_log)
        print(f"[POLICY_TOOL] ERROR: {exc}")
        return updated


# ─────────────────────────────────────────────────────────────────────────────
# Standalone Test
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("POLICY TOOL WORKER — Standalone Test")
    print("=" * 60)

    test_cases = [
        {
            "task": "Khách hàng Flash Sale yêu cầu hoàn tiền vì sản phẩm lỗi — được không?",
            "retrieved_chunks": [
                {"text": "Ngoại lệ: Đơn hàng Flash Sale không được hoàn tiền theo Điều 3, chính sách v4.",
                 "source": "policy_refund_v4.txt", "score": 0.91},
            ],
            "needs_tool": True,
        },
        {
            "task": "Ai phê duyệt để cấp quyền Level 2 khẩn cấp cho contractor lúc 2am?",
            "retrieved_chunks": [
                {"text": "Level 2: Line Manager + IT Admin. Emergency bypass được phép với approval đồng thời.",
                 "source": "access_control_sop.txt", "score": 0.88},
            ],
            "needs_tool": True,
            "risk_high": True,
        },
        {
            "task": "Ticket P1 lúc 2am. Cần cấp Level 2 access tạm thời cho contractor. Nêu đủ cả hai quy trình.",
            "retrieved_chunks": [
                {"text": "P1: phản hồi 15 phút, xử lý 4 giờ. Escalate sau 10 phút không có phản hồi.",
                 "source": "sla_p1_2026.txt", "score": 0.90},
                {"text": "Level 2 emergency bypass: Line Manager + IT Admin on-call đồng ý miệng là đủ.",
                 "source": "access_control_sop.txt", "score": 0.87},
            ],
            "needs_tool": True,
            "risk_high": True,
        },
        {
            "task": "Khách mua hàng ngày 15/01/2026 muốn hoàn tiền. Policy áp dụng?",
            "retrieved_chunks": [
                {"text": "Chính sách Hoàn tiền v4 có hiệu lực từ 01/02/2026.",
                 "source": "policy_refund_v4.txt", "score": 0.82},
            ],
            "needs_tool": False,
        },
    ]

    for tc in test_cases:
        print(f"\n{'─'*55}")
        print(f"▶ Task: {tc['task'][:70]}")
        state = tc.copy()
        state.setdefault("risk_high", False)
        result = run(state)
        pr = result.get("policy_result", {})
        print(f"  policy_applies  : {pr.get('policy_applies')}")
        print(f"  access_level    : {pr.get('access_level_detected')}")
        print(f"  is_emergency    : {pr.get('is_emergency')}")
        if pr.get("exceptions_found"):
            for ex in pr["exceptions_found"]:
                print(f"  exception [{ex['severity']}]: {ex['type']}")
        if pr.get("access_permission"):
            ap = pr["access_permission"]
            print(f"  can_grant={ap.get('can_grant')} approvers={ap.get('required_approvers')}")
        print(f"  MCP calls       : {len(result.get('mcp_tools_used', []))}")
        for call in result.get("mcp_tools_used", []):
            print(f"    → {call['tool']}({list(call['input'].keys())})")

    print("\n✅ policy_tool_worker test done.")
