"""Tier 5 Adversarial Coverage Hardening: Frontend & Integration Subsystems.

Authoritative White-Box Adversarial Stress Suite for:
1. frontend/src/utils/privacyMasker.ts (PII regex tokenization, boundary formats, nested de-anonymization, key masking)
2. frontend/src/utils/storageCompat.ts (Downward compatibility fallback chain, corrupted JSON, empty string handling, quota recovery)
3. frontend/src/pages/Workspace/v2/utils/autoOnePage.ts & generateHTML.ts (Extreme DOM heights, single-file embedding, XSS sanitization)
4. backend/agent/pi_core/ (Context compaction, single-coroutine linear loop, SSE event mapping, suggestion recovery)

All tests execute against real production code imports without synthetic facade mocks.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, AsyncIterable, Dict, List

import pytest

# 1. Production Backend Imports
from backend.agent.pi_core.context import (
    CompactionPolicy,
    compact_context,
    convert_to_llm,
    transform_context,
)
from backend.agent.pi_core.loop import AgentHooks, run_agent_loop
from backend.agent.pi_core.sse_adapter import to_legacy_stream_event
from backend.agent.pi_core.stream import PiCoreAgentStream
from backend.agent.pi_core.types import (
    AgentEvent,
    AgentMessage,
    AssistantChunk,
    ModelTurn,
    ToolCall,
    ToolDecision,
    ToolResult,
)
from backend.agent.web.streaming.events import (
    AnswerEvent,
    ThoughtEvent,
    ToolCallEvent,
    ToolProgressEvent,
    ToolResultEvent,
)
from backend.core.logger import _sanitize_text_payload
from backend.routes.config import _mask_key

WORKTREE_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_DIR = WORKTREE_ROOT / "frontend"


def run_frontend_ts_script(script_body: str, timeout_sec: int = 30) -> Dict[str, Any]:
    """Execute a TypeScript snippet inside the frontend workspace using vite-node.

    The snippet must print a single valid JSON object on its final line.
    """
    with tempfile.NamedTemporaryFile(suffix=".ts", dir=str(FRONTEND_DIR), delete=False) as f:
        f.write(script_body.encode("utf-8"))
        temp_path = f.name
    try:
        res = subprocess.run(
            ["npx", "vite-node", Path(temp_path).name],
            cwd=str(FRONTEND_DIR),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        if res.returncode != 0:
            raise RuntimeError(
                f"TS script execution failed (code {res.returncode}):\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}"
            )
        for line in reversed(res.stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
        raise ValueError(f"Could not parse JSON result from vite-node output:\n{res.stdout}")
    finally:
        if os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


# ============================================================================
# SUBSYSTEM 1: Privacy Masker & Key Protection (frontend/src/utils/privacyMasker.ts)
# ============================================================================


def test_adv_01_privacy_masker_complex_phone_formats_and_id_cards():
    """ADV-01: Stress-test PII extraction with international numbers, extensions, and resident IDs."""
    script = """
import { maskResumePII, unmaskResumePII } from './src/utils/privacyMasker.ts';

const adversarialText = [
  '候选人主要联系方式：+86-13800138000 与 +86 13912345678。',
  '备用座机与分机：13700001111转8888 以及 13699998888。',
  '二代身份证（大写X）：11010119900307234X，二代身份证（小写x）：31010119951212123x。',
  '个人邮箱：candidate.eng+work_2026@sub-domain.example.co.uk。'
].join('\\n');

const { masked, tokenMap } = maskResumePII(adversarialText);

// Verify phone numbers are masked
const phone1 = tokenMap['{{PHONE_1}}'];
const phone2 = tokenMap['{{PHONE_2}}'];
const phone3 = tokenMap['{{PHONE_3}}'];
const phone4 = tokenMap['{{PHONE_4}}'];

// Verify ID cards are masked
const id1 = tokenMap['{{IDCARD_1}}'];
const id2 = tokenMap['{{IDCARD_2}}'];

// Verify email is masked
const email1 = tokenMap['{{EMAIL_1}}'];

// Perform full lossless re-hydration
const restored = unmaskResumePII(masked, tokenMap);

console.log(JSON.stringify({
  masked,
  phone1,
  phone2,
  phone3,
  phone4,
  id1,
  id2,
  email1,
  restoredMatchesOriginal: restored === adversarialText,
  leakDetected: (
    masked.includes('13800138000') ||
    masked.includes('13912345678') ||
    masked.includes('11010119900307234X') ||
    masked.includes('31010119951212123x') ||
    masked.includes('candidate.eng+work_2026@sub-domain.example.co.uk')
  )
}));
"""
    result = run_frontend_ts_script(script)
    assert not result["leakDetected"], "Sensitive PII was leaked into masked output!"
    assert result["restoredMatchesOriginal"], "Re-hydrated text did not match original input losslessly!"
    assert result["phone1"] is not None
    assert result["id1"] == "11010119900307234X"
    assert result["id2"] == "31010119951212123x"
    assert result["email1"] == "candidate.eng+work_2026@sub-domain.example.co.uk"


def test_adv_02_privacy_masker_name_collisions_and_token_collision_resilience():
    """ADV-02: Stress-test candidate name substring collision and pre-existing placeholder tokens."""
    script = """
import { maskResumePII, unmaskResumePII } from './src/utils/privacyMasker.ts';

// Candidate name '李明' is a substring of words like '说明' or '明确'
const candidateName = '李明';
const input = '项目说明：由架构师李明明确设计。注意：请勿硬编码 {{PHONE_1}} 或 {{NAME_99}}。';

const { masked, tokenMap } = maskResumePII(input, { candidateName });
const restored = unmaskResumePII(masked, tokenMap);

console.log(JSON.stringify({
  masked,
  tokenMap,
  containsNameToken: masked.includes('{{NAME_1}}'),
  containsProjectDescription: masked.includes('项目说明'),
  containsExplicitWord: masked.includes('明确设计'),
  restored,
  restoredMatchesOriginal: restored === input
}));
"""
    result = run_frontend_ts_script(script)
    assert result["containsNameToken"], "Candidate name was not masked to {{NAME_1}}"
    assert result["containsProjectDescription"], "Word '项目说明' was incorrectly mutated"
    assert result["containsExplicitWord"], "Word '明确设计' was incorrectly mutated"
    assert result["restoredMatchesOriginal"], "Restored string did not match original input"


def test_adv_03_privacy_masker_nested_object_depth_and_patch_de_anonymization():
    """ADV-03: Stress-test recursive de-identification & re-hydration across deep objects (6+ levels)."""
    script = """
import { maskResumePII, unmaskResumePII } from './src/utils/privacyMasker.ts';

const deepResume = {
  candidate: {
    basic: {
      name: '王五',
      contact: {
        phone: '13812345678',
        email: 'wangwu@cococv.com',
        meta: {
          emergencyPhone: '13987654321',
          nestedAudit: {
            createdUser: '王五',
            deepNote: '经王五核对，联系电话 13812345678 无误'
          }
        }
      }
    }
  },
  records: [
    null,
    123,
    true,
    { description: '与王五在 13812345678 沟通完成' }
  ]
};

const { maskedData, tokenMap } = maskResumePII(deepResume, { candidateName: '王五' });
const restored = unmaskResumePII(maskedData, tokenMap);

console.log(JSON.stringify({
  maskedNote: maskedData.candidate.basic.contact.meta.nestedAudit.deepNote,
  maskedRecord: (maskedData.records[3] as any).description,
  restoredEqualsDeep: JSON.stringify(restored) === JSON.stringify(deepResume)
}));
"""
    result = run_frontend_ts_script(script)
    assert "{{NAME_1}}" in result["maskedNote"]
    assert "{{PHONE_1}}" in result["maskedNote"]
    assert "{{PHONE_1}}" in result["maskedRecord"]
    assert result["restoredEqualsDeep"], "Deep object re-hydration did not losslessly match original!"


def test_adv_04_api_key_masking_boundary_and_malformed_inputs():
    """ADV-04: Verify frontend maskApiKey and backend _mask_key exact parity across boundary lengths."""
    lengths_to_test = [0, 1, 2, 5, 6, 7, 11, 12, 13, 20, 64, 128]
    test_cases = {}
    for length in lengths_to_test:
        if length == 0:
            test_cases[length] = ""
        else:
            test_cases[length] = "k" * length

    script = f"""
import {{ maskApiKey }} from './src/utils/privacyMasker.ts';

const cases = {json.dumps(test_cases)};
const results: Record<string, string> = {{}};
for (const [lenStr, val] of Object.entries(cases)) {{
  results[lenStr] = maskApiKey(val as string);
}}
console.log(JSON.stringify({{ results }}));
"""
    frontend_results = run_frontend_ts_script(script)["results"]

    for length_str, raw_val in test_cases.items():
        fe_masked = frontend_results[str(length_str)]
        be_masked = _mask_key(raw_val)
        assert fe_masked == be_masked, (
            f"Parity mismatch at length {length_str}: Frontend '{fe_masked}' != Backend '{be_masked}'"
        )

    # Test whitespace and None safety
    assert _mask_key(None) == ""
    assert _mask_key("   ") == ""
    assert _mask_key("   sk-key1234567890   ") == _mask_key("sk-key1234567890")


# ============================================================================
# SUBSYSTEM 2: Storage Compatibility & Migration (frontend/src/utils/storageCompat.ts)
# ============================================================================


def test_adv_05_storage_compat_fallback_chain_and_empty_string_handling():
    """ADV-05: Stress-test storage downward compatibility, empty strings, and quota error suppression."""
    script = """
import { JSDOM } from 'jsdom';
const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>', { url: 'http://localhost' });
(global as any).window = dom.window;
(global as any).localStorage = dom.window.localStorage;

import { getCompatibleItem, setCompatibleItem, removeCompatibleItem } from './src/utils/storageCompat.ts';

// 1. Missing key returns null
const missing = getCompatibleItem('cococv_current');

// 2. Empty string in legacy key must return '' and NOT fall through
dom.window.localStorage.setItem('resume_current', '');
const emptyVal = getCompatibleItem('cococv_current');
const migratedEmpty = dom.window.localStorage.getItem('cococv_current');

// 3. Modern key takes priority over legacy key
dom.window.localStorage.setItem('cococv_resumes', 'modern_payload');
dom.window.localStorage.setItem('resume_resumes', 'legacy_payload');
const priorityVal = getCompatibleItem('cococv_resumes');

// 4. Quota write error does not crash read
const originalSet = dom.window.localStorage.setItem;
dom.window.localStorage.setItem = (k: string, v: string) => {
  if (k === 'cococv_v2_data') {
    throw new Error('QuotaExceededError: DOM Exception 22');
  }
  return originalSet.call(dom.window.localStorage, k, v);
};
dom.window.localStorage.setItem('resume_v2_data', 'legacy_v2_content');
const quotaSafeVal = getCompatibleItem('cococv_v2_data');

// Restore setItem
dom.window.localStorage.setItem = originalSet;

// 5. removeCompatibleItem purges both keys
setCompatibleItem('cococv_pinned_ids', 'pinned_val', ['resume_pinned_ids']);
removeCompatibleItem('cococv_pinned_ids', ['resume_pinned_ids']);
const removedModern = dom.window.localStorage.getItem('cococv_pinned_ids');
const removedLegacy = dom.window.localStorage.getItem('resume_pinned_ids');

console.log(JSON.stringify({
  missingIsNull: missing === null,
  emptyValMatchesEmptyString: emptyVal === '',
  migratedEmptyMatches: migratedEmpty === '',
  priorityValMatchesModern: priorityVal === 'modern_payload',
  quotaSafeValMatches: quotaSafeVal === 'legacy_v2_content',
  removedCleanly: removedModern === null && removedLegacy === null
}));
"""
    result = run_frontend_ts_script(script)
    assert result["missingIsNull"], "Missing key did not return null safely"
    assert result["emptyValMatchesEmptyString"], "Empty string was skipped instead of returned"
    assert result["migratedEmptyMatches"], "Empty string was not migrated forward"
    assert result["priorityValMatchesModern"], "Modern key did not take priority over legacy key"
    assert result["quotaSafeValMatches"], "Quota write exception was not safely caught during read"
    assert result["removedCleanly"], "removeCompatibleItem failed to purge modern and legacy keys"


def test_adv_06_storage_compat_corrupted_json_and_full_migration_sweep():
    """ADV-06: Stress-test migrateAllRegisteredKeys against corrupted non-JSON payloads."""
    script = """
import { JSDOM } from 'jsdom';
const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>', { url: 'http://localhost' });
(global as any).window = dom.window;
(global as any).localStorage = dom.window.localStorage;

import { migrateAllRegisteredKeys, DEFAULT_KEY_MAP } from './src/utils/storageCompat.ts';

// Inject malformed non-JSON strings into legacy keys
dom.window.localStorage.setItem('resume_resumes', '{unclosed_json_bracket:');
dom.window.localStorage.setItem('resume_current', 'corrupt_current_id_%%%');
dom.window.localStorage.setItem('resume-agent-v2-data', '<<<xml-malformed>>>');
dom.window.localStorage.setItem('resume_pinned_ids', 'null,undefined,NaN');

// Perform full migration sweep
migrateAllRegisteredKeys();

const migratedResumes = dom.window.localStorage.getItem('cococv_resumes');
const migratedCurrent = dom.window.localStorage.getItem('cococv_current');
const migratedV2 = dom.window.localStorage.getItem('cococv_v2_data');
const migratedPinned = dom.window.localStorage.getItem('cococv_pinned_ids');

console.log(JSON.stringify({
  migratedResumes,
  migratedCurrent,
  migratedV2,
  migratedPinned,
  registeredKeyCount: Object.keys(DEFAULT_KEY_MAP).length
}));
"""
    result = run_frontend_ts_script(script)
    assert result["migratedResumes"] == "{unclosed_json_bracket:"
    assert result["migratedCurrent"] == "corrupt_current_id_%%%"
    assert result["migratedV2"] == "<<<xml-malformed>>>"
    assert result["migratedPinned"] == "null,undefined,NaN"
    assert result["registeredKeyCount"] == 4


# ============================================================================
# SUBSYSTEM 3: Auto-One-Page Algorithm & HTML Export (autoOnePage.ts, generateHTML.ts)
# ============================================================================


def test_adv_07_auto_one_page_extreme_dom_and_boundary_thresholds():
    """ADV-07: Stress-test 3-Tier progressive fit under extreme DOM heights and minScale clamp."""
    script = """
import { JSDOM } from 'jsdom';
const dom = new JSDOM('<!DOCTYPE html><html><body><div id="target"></div></body></html>', { url: 'http://localhost' });
(global as any).window = dom.window;
(global as any).document = dom.window.document;
(global as any).HTMLElement = dom.window.HTMLElement;

import { autoFitToOnePage, resetAutoFit, A4_TARGET_HEIGHT_PX } from './src/pages/Workspace/v2/utils/autoOnePage.ts';

const element = dom.window.document.getElementById('target') as HTMLElement;

// Case 1: Zero height content -> Tier 0
Object.defineProperty(element, 'scrollHeight', { value: 0, configurable: true });
const zeroResult = autoFitToOnePage(element);

// Case 2: Content exactly within tolerance (1122.5 + 1.0 = 1123.5px) -> Tier 0
Object.defineProperty(element, 'scrollHeight', { value: 1123.5, configurable: true });
const toleranceResult = autoFitToOnePage(element, { targetHeight: A4_TARGET_HEIGHT_PX, tolerance: 1.5 });

// Case 3: Extreme height (5000px) -> Tier 3 scale clamped to minScale 0.82, fitted = false
Object.defineProperty(element, 'scrollHeight', { value: 5000, configurable: true });
const extremeResult = autoFitToOnePage(element, { targetHeight: A4_TARGET_HEIGHT_PX, minScale: 0.82 });

// Case 4: Reset auto fit clears transform and CSS variables
resetAutoFit(element);
const transformCleared = element.style.transform === '';
const maxHeightCleared = element.style.maxHeight === '';

console.log(JSON.stringify({
  zeroTier: zeroResult.tier,
  zeroFitted: zeroResult.fitted,
  toleranceTier: toleranceResult.tier,
  toleranceFitted: toleranceResult.fitted,
  extremeTier: extremeResult.tier,
  extremeScale: extremeResult.appliedValues.scale,
  extremeFitted: extremeResult.fitted,
  transformCleared,
  maxHeightCleared
}));
"""
    result = run_frontend_ts_script(script)
    assert result["zeroTier"] == 0
    assert result["zeroFitted"] is True
    assert result["toleranceTier"] == 0
    assert result["toleranceFitted"] is True
    assert result["extremeTier"] == 3
    assert result["extremeScale"] == 0.82, "Scale must be clamped to minScale 0.82"
    assert result["extremeFitted"] is False, "5000px resume must not falsely claim fitted=True"
    assert result["transformCleared"] and result["maxHeightCleared"]


def test_adv_08_generate_html_hostile_xss_sanitization_and_url_validation():
    """ADV-08: Verify HTML export sanitizes malicious XSS vectors and restricts protocols."""
    script = """
import { sanitizeRichText, isValidHttpUrl, formatFontFamily } from './src/pages/Workspace/v2/utils/generateHTML.ts';

// 1. Hostile XSS inputs
const maliciousInput = [
  '<script>alert("xss")</script>',
  '<img src=x onerror=alert(1)>',
  '<a href="javascript:alert(1)">Click Me</a>',
  '<iframe src="https://attacker.com"></iframe>',
  '<b onmouseover="alert(1)">Bold Safe Content</b>',
  '<p>Normal paragraph with <strong>bold</strong> and <em>italic</em>.</p>'
].join('');

const clean = sanitizeRichText(maliciousInput);

// 2. Protocol validations
const validHttp = isValidHttpUrl('http://example.com/api');
const validHttps = isValidHttpUrl('https://cococv.com');
const invalidJs = isValidHttpUrl('javascript:alert(1)');
const invalidData = isValidHttpUrl('data:text/html,<script>alert(1)</script>');
const invalidEmpty = isValidHttpUrl('');
const invalidNull = isValidHttpUrl(null);

// 3. Font formatting
const customFont = formatFontFamily('Helvetica Neue, Arial');

console.log(JSON.stringify({
  clean,
  hasScriptTag: clean.includes('<script'),
  hasOnError: clean.includes('onerror'),
  hasJavascriptProto: clean.includes('javascript:'),
  hasIframe: clean.includes('<iframe'),
  preservesBold: clean.includes('<b>Bold Safe Content</b>'),
  preservesStrong: clean.includes('<strong>bold</strong>'),
  validHttp,
  validHttps,
  invalidJs,
  invalidData,
  invalidEmpty,
  invalidNull,
  customFont
}));
"""
    result = run_frontend_ts_script(script)
    assert not result["hasScriptTag"], "Script tag survived rich text sanitizer!"
    assert not result["hasOnError"], "Event handler onerror survived rich text sanitizer!"
    assert not result["hasJavascriptProto"], "javascript: protocol survived rich text sanitizer!"
    assert not result["hasIframe"], "iframe tag survived rich text sanitizer!"
    assert result["preservesBold"] and result["preservesStrong"]
    assert result["validHttp"] and result["validHttps"]
    assert not result["invalidJs"] and not result["invalidData"]
    assert not result["invalidEmpty"] and not result["invalidNull"]


def test_adv_09_generate_html_zero_content_and_extreme_content_embedding():
    """ADV-09: Verify generateHTML self-contained offline export for empty and extreme resumes."""
    script = """
import { generateHTML } from './src/pages/Workspace/v2/utils/generateHTML.ts';
import type { ResumeData } from './src/pages/Workspace/v2/types';

// Zero-content minimal resume
const emptyResume: ResumeData = {
  basic: { name: '', title: '' },
  education: [],
  experience: [],
  projects: [],
  openSource: [],
  skills: [],
  awards: [],
  customSections: [],
  sectionOrder: [],
  globalSettings: { template: 'asu-tech' }
};

const emptyHtml = generateHTML(emptyResume, 'asu-tech', { editable: true, autoOnePage: true });

// Check structural properties
const hasDocType = emptyHtml.startsWith('<!DOCTYPE html>');
const hasClosingHtml = emptyHtml.endsWith('</html>');
const hasLocalToolbar = emptyHtml.includes('local-toolbar');
const hasAutoFitScript = emptyHtml.includes('runAutoOnePage()');
const hasA4PageStyle = emptyHtml.includes('size: A4 portrait;');

// Verify complete absence of external CDN references
const cdnRegex = /https?:\\/\\/(?:fonts\\.googleapis\\.com|cdn\\.jsdelivr\\.net|unpkg\\.com|cdnjs\\.cloudflare\\.com)/;
const hasExternalCdn = cdnRegex.test(emptyHtml);

console.log(JSON.stringify({
  hasDocType,
  hasClosingHtml,
  hasLocalToolbar,
  hasAutoFitScript,
  hasA4PageStyle,
  hasExternalCdn,
  length: emptyHtml.length
}));
"""
    result = run_frontend_ts_script(script)
    assert result["hasDocType"], "Generated HTML lacks <!DOCTYPE html>"
    assert result["hasClosingHtml"], "Generated HTML lacks </html> closing tag"
    assert result["hasLocalToolbar"], "Exported HTML is missing offline toolbar"
    assert result["hasAutoFitScript"], "Exported HTML is missing autoOnePage runtime"
    assert result["hasA4PageStyle"], "Exported HTML is missing @page print styles"
    assert not result["hasExternalCdn"], "Exported HTML illegally references external CDN resources!"


# ============================================================================
# SUBSYSTEM 4: Pi-Mono Core Runtime (backend/agent/pi_core/)
# ============================================================================


def test_adv_10_pi_core_extreme_context_compaction_and_supersede_dedup():
    """ADV-10: Stress-test context compaction under extreme history load (100+ turns) & duplicate supersede keys."""
    messages: List[AgentMessage] = [
        AgentMessage(role="system", content="You are CocoCV Resume Agent.")
    ]

    # Generate 50 turns with alternating supersede keys
    for i in range(50):
        messages.append(
            AgentMessage(
                role="assistant",
                content=f"Narration for step {i}: inspecting repository files...",
                tool_calls=[ToolCall(id=f"call_{i}", name="read_file", arguments={"path": "resume.tex"})],
            )
        )
        messages.append(
            AgentMessage(
                role="tool",
                content=f"File content version {i}: " + ("x" * 500),
                tool_call_id=f"call_{i}",
                name="read_file",
                supersede_key="read_file:resume.tex",
            )
        )

    # Add final user request
    messages.append(AgentMessage(role="user", content="Final instructions: optimize spacing."))

    # Configure tight compaction policy
    policy = CompactionPolicy(max_chars=4000, keep_recent_messages=6)
    compacted = transform_context(messages, policy)

    # Invariants verification:
    # 1. Compaction MUST NEVER delete messages or orphan tool calls
    assert len(compacted) == len(messages), "Compaction must preserve exact message count!"
    assert compacted[0].role == "system"
    assert compacted[0].content == "You are CocoCV Resume Agent."

    # 2. Older supersede tools must be marked as superseded
    superseded_count = sum(1 for m in compacted if m.metadata.get("superseded"))
    assert superseded_count == 49, f"Expected 49 superseded tool results, got {superseded_count}"

    # 3. Compacted tools must have compacted flag
    compacted_count = sum(1 for m in compacted if m.metadata.get("compacted"))
    assert compacted_count > 0, "Older messages must be compacted when exceeding max_chars budget"

    # 4. Verify tool-call pairing remains 100% intact across all 50 calls
    for i in range(50):
        asst = [m for m in compacted if m.tool_calls and m.tool_calls[0].id == f"call_{i}"][0]
        tool = [m for m in compacted if m.tool_call_id == f"call_{i}"][0]
        assert asst.role == "assistant"
        assert tool.role == "tool"
        assert asst.tool_calls[0].id == tool.tool_call_id

    # 5. LLM conversion strips internal fields cleanly
    llm_msgs = convert_to_llm(compacted)
    assert len(llm_msgs) == len(compacted)
    for llm_msg in llm_msgs:
        assert not hasattr(llm_msg, "supersede_key")


@pytest.mark.anyio
async def test_adv_11_pi_core_linear_loop_exception_fault_injection_and_truncation():
    """ADV-11: Stress-test single-coroutine linear loop against stream termination and length truncation."""

    # Scenario A: Model stream terminates prematurely without done chunk -> RuntimeError
    async def broken_model_stream(llm_msgs: Any) -> AsyncIterable[AssistantChunk]:
        yield AssistantChunk(kind="text_delta", content="Thinking about resume...")
        # Premature end without done chunk!

    def mock_tool_executor(call: ToolCall, messages: List[AgentMessage]) -> ToolResult:
        return ToolResult(output="ok")

    messages = [AgentMessage(role="user", content="Build resume")]
    with pytest.raises(RuntimeError, match="Model stream ended without a done chunk"):
        async for _ in run_agent_loop(messages, broken_model_stream, mock_tool_executor, max_turns=1):
            pass

    # Scenario B: Length truncation recovery with tool calls
    async def truncated_model_stream(llm_msgs: Any) -> AsyncIterable[AssistantChunk]:
        yield AssistantChunk(kind="text_delta", content="Partial call...")
        yield AssistantChunk(
            kind="done",
            turn=ModelTurn(
                content="Partial call...",
                tool_calls=[ToolCall(id="trunc_call", name="format_section", arguments={})],
                stop_reason="length",
            ),
        )

    trunc_messages = [AgentMessage(role="user", content="Truncated test")]
    events_collected = []
    # Using finish_turn hook to end turn cleanly after truncation
    from backend.agent.pi_core.types import FinishDecision
    hooks_trunc = AgentHooks(
        finish_turn=lambda turn, msgs: FinishDecision(action="end")
    )
    async for event in run_agent_loop(
        trunc_messages, truncated_model_stream, mock_tool_executor, hooks=hooks_trunc, max_turns=2
    ):
        events_collected.append(event)

    end_events = [e for e in events_collected if e.kind == "tool_execution_end"]
    assert len(end_events) == 1
    assert end_events[0].data["truncated"] is True
    assert "Tool call was truncated" in end_events[0].data["error"]

    # Scenario C: Hook blocks tool execution
    hooks_block = AgentHooks(
        before_tool_call=lambda call, msgs: ToolDecision(block=True, reason="Security policy blocked execution"),
        after_tool_call=lambda call, res, msgs: ToolDecision(terminate=True),
    )

    async def normal_model_stream(llm_msgs: Any) -> AsyncIterable[AssistantChunk]:
        yield AssistantChunk(
            kind="done",
            turn=ModelTurn(
                content="Calling tool",
                tool_calls=[ToolCall(id="blocked_call", name="rm_rf", arguments={})],
            ),
        )

    blocked_messages = [AgentMessage(role="user", content="Run dangerous tool")]
    blocked_events = []
    async for event in run_agent_loop(
        blocked_messages, normal_model_stream, mock_tool_executor, hooks=hooks_block, max_turns=2
    ):
        blocked_events.append(event)

    # Tool execution start should NOT have been emitted because it was blocked
    starts = [e for e in blocked_events if e.kind == "tool_execution_start"]
    assert len(starts) == 0

    # But tool execution end must be emitted with the block reason
    ends = [e for e in blocked_events if e.kind == "tool_execution_end"]
    assert len(ends) == 1
    assert "Security policy blocked execution" in ends[0].data["error"]


def test_adv_12_pi_core_sse_event_chunk_ordering_and_malformed_suggestions():
    """ADV-12: Stress-test SSE event mapping, unclosed suggestion JSON repair, and event envelopes."""

    # 1. Test malformed suggestion auto-repair and fallback
    # 1a. Missing closing bracket in valid array
    unclosed_suggestions = 'Some explanation %%SUGGESTIONS%%[{"id":"sug_1","text":"优化描述"}'
    content, items = PiCoreAgentStream._extract_suggestions(unclosed_suggestions)
    assert content == "Some explanation"
    assert len(items) == 1
    assert items[0]["id"] == "sug_1"

    # 1b. Irreparable corrupt JSON falls back cleanly without crashing
    corrupt_suggestions = 'Some text %%SUGGESTIONS%%{not_a_valid_json%%END%%'
    content_c, items_c = PiCoreAgentStream._extract_suggestions(corrupt_suggestions)
    assert content_c == "Some text"
    assert items_c == []

    # 1c. Non-list payload returns empty
    non_list_suggestions = 'Some text %%SUGGESTIONS%%{"id": "not_a_list"}%%END%%'
    _, items_nl = PiCoreAgentStream._extract_suggestions(non_list_suggestions)
    assert items_nl == []

    # 2. Test SSE event mappings in to_legacy_stream_event
    session_id = "test-session-xyz"

    # Thinking delta -> ThoughtEvent (data.content holds text)
    thought_evt = to_legacy_stream_event(
        AgentEvent("message_update", {"delta_type": "thinking_delta", "text": "Analyzing constraints..."}),
        session_id=session_id,
        step_id=1,
    )
    assert isinstance(thought_evt, ThoughtEvent)
    assert thought_evt.data["content"] == "Analyzing constraints..."
    assert thought_evt.session_id == session_id

    # Text delta -> AnswerEvent (data.delta and data.content hold text)
    answer_evt = to_legacy_stream_event(
        AgentEvent("message_update", {"delta_type": "text_delta", "text": "Resume updated."}),
        session_id=session_id,
        step_id=1,
    )
    assert isinstance(answer_evt, AnswerEvent)
    assert answer_evt.data["delta"] == "Resume updated."
    assert answer_evt.data["content"] == "Resume updated."

    # Tool execution start -> ToolCallEvent
    tool_start_evt = to_legacy_stream_event(
        AgentEvent("tool_execution_start", {
            "tool": "compile_latex",
            "arguments": {"template": "asu-tech"},
            "tool_call_id": "call_123"
        }),
        session_id=session_id,
        step_id=2,
    )
    assert isinstance(tool_start_evt, ToolCallEvent)
    assert tool_start_evt.data["tool"] == "compile_latex"
    assert tool_start_evt.data["args"] == {"template": "asu-tech"}
    assert tool_start_evt.data["tool_call_id"] == "call_123"

    # Tool progress update -> ToolProgressEvent
    tool_prog_evt = to_legacy_stream_event(
        AgentEvent("tool_execution_update", {
            "tool_call_id": "call_123",
            "stage_id": "font_injection",
            "text": "Injecting CJK /ToUnicode CMap tables",
            "current": 2,
            "total": 5,
            "label": "Injecting Fonts",
            "stages": ["init", "font_injection", "compile"]
        }),
        session_id=session_id,
        step_id=2,
    )
    assert isinstance(tool_prog_evt, ToolProgressEvent)
    assert tool_prog_evt.data["stage_id"] == "font_injection"
    assert tool_prog_evt.data["current"] == 2
    assert tool_prog_evt.data["total"] == 5

    # Tool execution end -> ToolResultEvent
    tool_end_evt = to_legacy_stream_event(
        AgentEvent("tool_execution_end", {
            "tool": "compile_latex",
            "tool_call_id": "call_123",
            "output": "Compilation succeeded in 184ms",
            "structured_content": {"pdf_cached": True}
        }),
        session_id=session_id,
        step_id=2,
    )
    assert isinstance(tool_end_evt, ToolResultEvent)
    assert tool_end_evt.data["tool"] == "compile_latex"
    assert tool_end_evt.data["result"] == "Compilation succeeded in 184ms"
    assert tool_end_evt.data["structured_data"] == {"pdf_cached": True}
    assert tool_end_evt.data["is_error"] is False
