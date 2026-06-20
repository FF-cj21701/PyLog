import os

from .widgets.agent_page_host import AgentPageBridge, open_agent_page


_REVIEW_RECORDS = {}


def _normalize_script_path(script_path):
    if not script_path:
        return None
    return os.path.normpath(os.path.abspath(str(script_path))).replace("\\", "/").lower()


def register_review_record(record_payload):
    if not isinstance(record_payload, dict):
        return None
    script_path = record_payload.get("script_path")
    key = _normalize_script_path(script_path)
    if not key:
        return None
    _REVIEW_RECORDS[key] = dict(record_payload)
    return key


def get_review_record(script_path):
    key = _normalize_script_path(script_path)
    if not key:
        return None
    return _REVIEW_RECORDS.get(key)


def open_review_page(script_path, parent=None, payload=None):
    review_payload = payload or get_review_record(script_path)
    if not review_payload:
        return None

    bridge = AgentPageBridge(parent)
    session_id = review_payload.get("session_id") or _normalize_script_path(review_payload.get("script_path")) or "review"
    page = open_agent_page(
        page_id=f"review-record:{session_id}",
        title="AI Review",
        template="review_template.html",
        payload=review_payload,
        mode="mdi",
        size=(1040, 760),
        bridge=bridge,
        parent=parent,
    )
    return page
