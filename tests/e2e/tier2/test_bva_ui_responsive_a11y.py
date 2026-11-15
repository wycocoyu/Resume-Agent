"""Tier 2 Boundary & Corner Tests: Feature 16 (Modern UI Responsive, A11y & CSS Design System).

Authoritative specs:
- ORIGINAL_REQUEST §R3.4, Issue #58
- frontend/src/tailwind.css
- frontend/src/pages/Settings/index.tsx
- Boundaries: WCAG token palettes, status state badges, responsive cards, prefers-reduced-motion a11y, local SVG icons
"""
from __future__ import annotations

from pathlib import Path
import pytest

WORKTREE_ROOT = Path(__file__).resolve().parents[3]


def test_t2_f16_01_wcag_color_tokens_compliance():
    """TEST-T2-F16-01: Verify production CSS design system defines high-contrast semantic tokens."""
    css_path = WORKTREE_ROOT / "frontend" / "src" / "tailwind.css"
    assert css_path.exists(), f"Missing production stylesheet: {css_path}"
    content = css_path.read_text(encoding="utf-8")

    # Semantic design tokens in data-skin='fresh'
    assert "--chat-canvas: #f8fafc" in content  # slate-50 light background
    assert "--chat-ink: #0f172a" in content     # slate-900 high contrast dark text
    assert "--chat-surface: #ffffff" in content # pure white surface
    assert "--chat-ink-muted: #64748b" in content  # slate-500 secondary text


def test_t2_f16_02_settings_status_badge_tokens():
    """TEST-T2-F16-02: Verify Settings page implements semantic testing/ok/error status badges."""
    settings_path = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Settings" / "index.tsx"
    assert settings_path.exists(), f"Missing Settings page: {settings_path}"
    content = settings_path.read_text(encoding="utf-8")

    # Testing state: amber indicator
    assert "bg-amber-500/15 text-amber-600" in content
    # Success state: emerald indicator
    assert "bg-emerald-500/15 text-emerald-600" in content
    # Error state: red indicator
    assert "bg-red-500/15 text-red-600" in content


def test_t2_f16_03_responsive_card_and_overflow_classes():
    """TEST-T2-F16-03: Verify Settings layout has responsive wrap and dark-mode border tokens."""
    settings_path = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Settings" / "index.tsx"
    content = settings_path.read_text(encoding="utf-8")

    # Responsive card container with dark mode support
    assert "rounded-xl bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700" in content
    # Responsive flex wrapping
    assert "flex flex-wrap items-center justify-between" in content
    # Safe scrolling container
    assert "overflow-y-auto" in content


def test_t2_f16_04_reduced_motion_a11y_accessibility():
    """TEST-T2-F16-04: Verify stylesheet includes prefers-reduced-motion media query for WCAG A11y."""
    css_path = WORKTREE_ROOT / "frontend" / "src" / "tailwind.css"
    content = css_path.read_text(encoding="utf-8")

    # Accessibility guard for motion-sensitive users
    assert "@media (prefers-reduced-motion: reduce)" in content


def test_t2_f16_05_local_svg_icons_zero_remote_cdn():
    """TEST-T2-F16-05: Verify UI icons use local Lucide SVG components with zero remote CDN dependencies."""
    settings_path = WORKTREE_ROOT / "frontend" / "src" / "pages" / "Settings" / "index.tsx"
    content = settings_path.read_text(encoding="utf-8")

    # Local React/Lucide icon imports
    assert "from 'lucide-react'" in content
    assert "CheckCircle2" in content
    assert "KeyRound" in content

    # Zero unbundled external image assets or HTTP icons in settings components
    assert 'src="http://' not in content
    assert 'src="https://' not in content
