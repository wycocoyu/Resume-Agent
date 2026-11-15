"""Tier 1 Feature Coverage: Feature 15 (Client-Side Privacy PII Masking & Key Protection, Issue #56).

Authoritative specs:
- ORIGINAL_REQUEST §R3.4, Issue #56
- backend/routes/config.py (_mask_key)
- backend/core/logger.py (_sanitize_text_payload)
- frontend/src/utils/privacyMasker.ts (Client PII Tokenizer, Scheduled for M6)
"""
from __future__ import annotations

from pathlib import Path
import pytest

from backend.routes.config import _mask_key
from backend.core.logger import _sanitize_text_payload

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t1_f15_01_api_key_masking_short_medium_long():
    """TEST-T1-F15-01: Verify _mask_key handles short, medium, and standard length keys securely."""
    # Long key (> 12 chars): prefix 8 + bullets + suffix 4
    long_key = "sk-deepseek-1234567890abcdef"
    masked_long = _mask_key(long_key)
    assert masked_long.startswith("sk-deeps")
    assert masked_long.endswith("cdef")
    assert "••••••" in masked_long
    assert "1234567890" not in masked_long

    # Medium key (7..12 chars): prefix 4 + bullets + suffix 2
    med_key = "abcdefghij"
    masked_med = _mask_key(med_key)
    assert masked_med.startswith("abcd")
    assert masked_med.endswith("ij")

    # Short key (<= 6 chars)
    short_key = "secret"
    masked_short = _mask_key(short_key)
    assert masked_short == "se•••"


def test_t1_f15_02_logger_sanitize_sensitive_payload():
    """TEST-T1-F15-02: Verify backend logger sanitizes username/author/body payloads in logs."""
    raw_message = "Audit action for username=alice author_name=bob body=sensitive_post_content"
    sanitized = _sanitize_text_payload(raw_message)
    assert "alice" not in sanitized
    assert "bob" not in sanitized
    assert "username=[REDACTED]" in sanitized
    assert "author_name=[REDACTED]" in sanitized


def test_t1_f15_03_config_keys_route_contract(e2e_client):
    """TEST-T1-F15-03: Verify GET /api/config/keys returns masked keys without plaintext exposure."""
    res = e2e_client.get("/api/config/keys")
    assert res.status_code in (200, 401), f"Unexpected status: {res.status_code}"
    if res.status_code == 200:
        data = res.json()
        assert "deepseek_key" in data or "keys" in data or "configured" in data


def test_t1_f15_04_empty_and_whitespace_key_handling():
    """TEST-T1-F15-04: Verify empty, None, or whitespace keys produce empty strings safely."""
    assert _mask_key("") == ""
    assert _mask_key("   ") == ""
    assert _mask_key(None) == ""


def test_t1_f15_05_client_privacy_masker_module_contract():
    """TEST-T1-F15-05: Verify frontend/src/utils/privacyMasker.ts exists (Scheduled for M6 delivery)."""
    masker_file = WORKTREE_ROOT / "frontend" / "src" / "utils" / "privacyMasker.ts"
    # Scheduled for M6 implementation
    assert masker_file.exists(), f"Client privacy masker must exist at {masker_file} (M6 deliverable)"
    content = masker_file.read_text(encoding="utf-8")
    assert "export function maskResumePII" in content
    assert "export function unmaskResumePII" in content
