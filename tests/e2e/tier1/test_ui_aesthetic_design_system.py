"""Tier 1 Feature Coverage: Feature 16 (Modern UI Aesthetic & Design System, Issue #58).

Authoritative specs:
- ORIGINAL_REQUEST §R3.4, Issue #58
- frontend/src/pages/Settings/index.tsx (Settings credential cards, test states)
- frontend/src/tailwind.css (Design system tokens, skin palettes, a11y)
- frontend/src/pages/Workspace/v2/SidePanel/SettingsDrawer.tsx
- scripts/tabbit-pr-verify.mjs (Visual verification stages)
"""
from __future__ import annotations

from pathlib import Path
import pytest

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t1_f16_01_settings_page_production_contract():
    """TEST-T1-F16-01: Verify Settings/index.tsx implements credential cards for deepseek and zhipu."""
    settings_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Settings" / "index.tsx"
    assert settings_file.exists(), f"Settings page must exist at {settings_file}"
    content = settings_file.read_text(encoding="utf-8")

    assert "deepseek" in content
    assert "zhipu" in content
    assert "ProviderKeyStatus" in content or "configured" in content
    assert "ProviderTestState" in content or "testing" in content


def test_t1_f16_02_tailwind_design_tokens_and_skins():
    """TEST-T1-F16-02: Verify tailwind.css defines fresh skin semantic tokens."""
    css_file = WORKTREE_ROOT / "frontend" / "src" / "tailwind.css"
    assert css_file.exists(), f"Tailwind stylesheet must exist at {css_file}"
    content = css_file.read_text(encoding="utf-8")

    assert "[data-skin='fresh']" in content or 'data-skin="fresh"' in content
    assert "--chat-canvas" in content
    assert "--chat-ink" in content
    assert "--chat-accent" in content
    assert "--chat-surface" in content


def test_t1_f16_03_settings_drawer_in_workspace():
    """TEST-T1-F16-03: Verify SettingsDrawer exists in Workspace v2."""
    drawer_file = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Workspace" / "v2" / "SidePanel" / "SettingsDrawer.tsx"
    assert drawer_file.exists(), f"SettingsDrawer must exist at {drawer_file}"


def test_t1_f16_04_prefers_reduced_motion_accessibility():
    """TEST-T1-F16-04: Verify a11y reduced motion query is defined in design system."""
    css_file = WORKTREE_ROOT / "frontend" / "src" / "tailwind.css"
    content = css_file.read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in content


def test_t1_f16_05_tabbit_verification_script_covers_skins():
    """TEST-T1-F16-05: Verify scripts/tabbit-pr-verify.mjs includes skin-picker screenshot stage."""
    script_file = WORKTREE_ROOT / "scripts" / "tabbit-pr-verify.mjs"
    assert script_file.exists()
    content = script_file.read_text(encoding="utf-8")
    assert "03-skin-picker.png" in content
