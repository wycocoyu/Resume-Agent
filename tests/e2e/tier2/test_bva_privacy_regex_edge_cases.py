"""Tier 2 Boundary & Corner Tests: Feature 15 (Privacy Regex & Masking Edge Cases).

Authoritative specs:
- ORIGINAL_REQUEST §R3.4, Issue #56
- backend/routes/config.py (_mask_key)
- backend/core/logger.py (_sanitize_text_payload)
- frontend/src/utils/privacyMasker.ts (Scheduled for M6)
- Boundaries: exact boundary length slicing (6, 7, 12, 13), unicode keys, multiple redaction targets, multiline text
"""
from __future__ import annotations

from pathlib import Path
import pytest

from backend.routes.config import _mask_key
from backend.core.logger import _sanitize_text_payload

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t2_f15_01_api_key_exact_boundary_lengths():
    """TEST-T2-F15-01: Verify _mask_key slicing at boundary lengths: 1, 6, 7, 12, 13."""
    # 1 char: short path (len <= 6) -> prefix[:2] + "•••"
    assert _mask_key("a") == "a•••"

    # Exactly 6 chars: short path (len <= 6) -> prefix[:2] + "•••"
    assert _mask_key("abcdef") == "ab•••"

    # Exactly 7 chars: medium path (7..12) -> prefix[:4] + "••••" + suffix[-2:]
    res_7 = _mask_key("1234567")
    assert res_7 == "1234••••67"

    # Exactly 12 chars: medium path (7..12) -> prefix[:4] + "••••" + suffix[-2:]
    res_12 = _mask_key("123456789012")
    assert res_12 == "1234••••12"

    # Exactly 13 chars: long path (> 12) -> prefix[:8] + "••••••" + suffix[-4:]
    res_13 = _mask_key("1234567890123")
    assert res_13 == "12345678••••••0123"


def test_t2_f15_02_unicode_and_special_character_keys():
    """TEST-T2-F15-02: Verify _mask_key safely handles non-ASCII unicode and symbol keys."""
    unicode_key = "密钥_abcdef_测试私钥_123456"
    masked = _mask_key(unicode_key)
    assert len(masked) > 0
    assert "••••••" in masked
    assert "测试私钥" not in masked


def test_t2_f15_03_logger_sanitize_multiple_keys_and_multiline():
    """TEST-T2-F15-03: Verify _sanitize_text_payload sanitizes multiple tokens across multiline text."""
    multiline_payload = (
        "Line 1: username=user_alpha started operation.\n"
        "Line 2: author_name=reviewer_beta approved.\n"
        "Line 3: body=confidential financial figures here."
    )
    sanitized = _sanitize_text_payload(multiline_payload)
    assert "user_alpha" not in sanitized
    assert "reviewer_beta" not in sanitized
    assert "confidential financial figures" not in sanitized
    assert "username=[REDACTED]" in sanitized
    assert "author_name=[REDACTED]" in sanitized
    assert "body=[REDACTED]" in sanitized


def test_t2_f15_04_logger_sanitize_preserves_safe_text():
    """TEST-T2-F15-04: Verify _sanitize_text_payload does not alter text without sensitive keywords."""
    clean_message = "System booted successfully in 234ms. Workers: 4. Port: 9000."
    sanitized = _sanitize_text_payload(clean_message)
    assert sanitized == clean_message


def test_t2_f15_05_client_privacy_masker_boundary_spec_contract():
    """TEST-T2-F15-05: Verify client-side privacyMasker module exists (Scheduled for M6)."""
    masker_path = WORKTREE_ROOT / "frontend" / "src" / "utils" / "privacyMasker.ts"
    assert masker_path.exists(), f"M6 deliverable {masker_path} is not yet implemented"
