from __future__ import annotations

import os
import re
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RESOURCES_DIR = os.path.join(PROJECT_ROOT, "plugins", "ai_assistant", "ui", "resources")
CHAT_TEMPLATE = os.path.join(RESOURCES_DIR, "chat_template.html")
CHAT_BOOTSTRAP = os.path.join(RESOURCES_DIR, "chat_bootstrap.js")
CHAT_PLAN = os.path.join(RESOURCES_DIR, "chat_plan.js")
CHAT_STYLES = os.path.join(RESOURCES_DIR, "chat_styles.css")
CHAT_DETAILS = os.path.join(RESOURCES_DIR, "chat_details.js")
CHAT_MESSAGE = os.path.join(RESOURCES_DIR, "chat_message.js")
CHAT_INPUT = os.path.join(RESOURCES_DIR, "chat_input.js")
REVIEW_TEMPLATE = os.path.join(RESOURCES_DIR, "review_template.html")
AGENT_PAGE_TEMPLATE = os.path.join(RESOURCES_DIR, "agent_page_template.html")


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


class ChatTemplateRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = _read(CHAT_TEMPLATE)
        cls.bootstrap = _read(CHAT_BOOTSTRAP)
        cls.plan_js = _read(CHAT_PLAN)
        cls.styles = _read(CHAT_STYLES)
        cls.details_js = _read(CHAT_DETAILS)
        cls.message_js = _read(CHAT_MESSAGE)
        cls.input_js = _read(CHAT_INPUT)

    def test_template_has_no_inline_dom_event_handlers(self):
        self.assertNotRegex(self.template, r"\bonclick\s*=")
        self.assertNotRegex(self.template, r"\bonchange\s*=")
        self.assertNotRegex(self.template, r"\boninput\s*=")

    def test_template_keeps_js_bound_control_ids(self):
        required_ids = [
            "mode-btn",
            "settings-btn",
            "clear-chat-btn",
            "send-btn",
            "planProgressHeader",
            "planProgressCollapseBtn",
        ]
        for element_id in required_ids:
            self.assertIn(f'id="{element_id}"', self.template)

    def test_toolbar_buttons_use_custom_themeable_tooltips(self):
        self.assertIn('id="mode-btn" data-tooltip="Reasoning Mode"', self.template)
        self.assertIn('id="settings-btn" data-tooltip="Settings"', self.template)
        self.assertIn('id="clear-chat-btn" data-tooltip="Clear Chat"', self.template)
        self.assertIn('btn.dataset.tooltip = "Reasoning mode on";', self.bootstrap)
        self.assertIn('btn.dataset.tooltip = "Turn on reasoning mode";', self.bootstrap)
        self.assertIn('.toolbar .icon-btn[data-tooltip]::after {', self.styles)

    def test_bootstrap_binds_template_controls(self):
        bindings = [
            "document.getElementById('mode-btn')",
            "document.getElementById('settings-btn')",
            "document.getElementById('clear-chat-btn')",
            "document.getElementById('send-btn')",
            "document.getElementById('planProgressHeader')",
            "document.getElementById('planProgressCollapseBtn')",
            ".addEventListener('click'",
        ]
        for snippet in bindings:
            self.assertIn(snippet, self.bootstrap)

    def test_card_actions_use_shared_global_bridge(self):
        self.assertIn("window.pyBridge = null;", self.bootstrap)
        self.assertIn("window.pyBridge = bridge;", self.bootstrap)
        self.assertIn("const activeBridge = window.pyBridge || (typeof bridge !== 'undefined' ? bridge : null);", self.details_js)
        self.assertIn("encodeURIComponent(JSON.stringify({ action: action.id, payload: action.payload || {} }))", self.details_js)
        self.assertIn("activeBridge.onMessageCardAction(decodeURIComponent(btn.dataset.cardAction || ''));", self.details_js)

    def test_message_card_section_renders_summary_header(self):
        self.assertIn("message-cards-header", self.details_js)
        self.assertIn("Edited file", self.details_js)
        self.assertIn("File changed in this reply", self.details_js)
        self.assertIn("Files changed in this reply", self.details_js)
        self.assertIn(".message-cards-header {", self.styles)

    def test_plan_header_stats_do_not_render_domain(self):
        self.assertNotIn("Domain:", self.plan_js)
        self.assertNotIn("plan_domain", self.plan_js)

    def test_plan_step_meta_only_renders_status_pill(self):
        self.assertIn("if (step.status) metaPills.push(step.status);", self.plan_js)
        self.assertNotIn("metaPills.push(step.kind)", self.plan_js)

    def test_template_still_loads_split_chat_scripts(self):
        expected_scripts = [
            "chat_bootstrap.js",
            "chat_tools.js",
            "chat_details.js",
            "chat_plan.js",
            "chat_input.js",
            "chat_message.js",
        ]
        for script_name in expected_scripts:
            self.assertRegex(self.template, rf'<script src="{re.escape(script_name)}"></script>')

    def test_template_uses_external_chat_stylesheet(self):
        self.assertIn('<link rel="stylesheet" href="chat_styles.css">', self.template)
        self.assertIn('<style id="dynamic-theme-vars">', self.template)
        self.assertEqual(self.template.count("<style"), 1)
        self.assertIn(".plan-progress-container {", self.styles)

    def test_plan_stats_start_empty_and_are_js_rendered(self):
        self.assertIn('<div class="plan-progress-stats" id="topPlanProgressStats"></div>', self.template)
        self.assertIn('statsElement.innerHTML = `', self.plan_js)

    def test_plan_container_is_hidden_by_default_in_stylesheet(self):
        self.assertRegex(
            self.styles,
            r"(?s)\.plan-progress-container\s*\{.*?display:\s*none;"
        )

    def test_content_pre_uses_subtle_code_block_surface(self):
        self.assertRegex(
            self.styles,
            r"(?s)\.content pre\s*\{.*?background:\s*var\(--bg-secondary\);.*?color:\s*inherit;.*?border:\s*1px solid var\(--border-color\);"
        )
        self.assertIn(".content pre .hljs {", self.styles)
        inline_code_match = re.search(
            r"(?s)\.content :not\(pre\)>code\s*\{(.*?)\}",
            self.styles
        )
        self.assertIsNotNone(inline_code_match)
        inline_code_block = inline_code_match.group(1)
        self.assertIn("background: var(--bg-tertiary);", inline_code_block)
        self.assertNotIn("border: 1px solid var(--border-color);", inline_code_block)

    def test_reasoning_mode_button_uses_theme_colored_active_state(self):
        self.assertRegex(
            self.styles,
            r"(?s)\.icon-btn\.active\s*\{.*?background-color:\s*var\(--bg-secondary\);.*?color:\s*var\(--primary-color\);"
        )
        self.assertIn("html.dark-mode .icon-btn.active {", self.styles)

    def test_react_round_break_is_rendered_and_styled(self):
        self.assertIn("step.kind === 'round_break'", self.details_js)
        self.assertIn("react-round-break", self.details_js)
        self.assertIn(".react-round-break {", self.styles)
        self.assertNotIn("Next React Round", self.details_js)
        self.assertRegex(
            self.styles,
            r"(?s)\.react-round-break\s*\{.*?height:\s*2px;.*?margin:\s*2px 0;"
        )

    def test_math_markup_is_preprocessed_before_marked(self):
        self.assertIn("processedContent = renderMathMarkup(processedContent);", self.message_js)
        self.assertIn("function renderMathMarkup(content) {", self.message_js)
        self.assertIn("function renderLatexExpression(expr) {", self.message_js)
        self.assertIn(".math-block {", self.styles)
        self.assertIn(".math-frac {", self.styles)
        self.assertRegex(
            self.styles,
            r"(?s)\.math-block\s*\{.*?border:\s*none;.*?box-shadow:\s*none;"
        )

    def test_streaming_tool_history_spacing_is_compact(self):
        self.assertIn("historyContainer.style.gap = '6px';", self.details_js)
        self.assertIn("historyContainer.style.marginBottom = '6px';", self.details_js)
        self.assertRegex(
            self.styles,
            r"(?s)\.tool-step-row\s*\{.*?margin:\s*8px 0;"
        )
        self.assertRegex(
            self.styles,
            r"(?s)\.history-container>\.tool-step-row\s*\{.*?margin:\s*0;"
        )

    def test_user_message_is_rendered_optimistically_before_python_round_trip(self):
        self.assertIn("shouldRenderOptimistically", self.input_js)
        self.assertIn("appendMessage('user', displayMsg", self.input_js)
        self.assertIn("rendered: shouldRenderOptimistically", self.input_js)
        self.assertIn("setSendingState(true);", self.input_js)

    def test_metadata_popover_escapes_preview_html_content(self):
        self.assertIn("function escapePopoverHtml(value)", self.input_js)
        self.assertIn("const previewText = escapePopoverHtml(finalContent.substring(0, 500))", self.input_js)
        self.assertNotIn("popover-content-preview\">${finalContent.substring(0, 500)}", self.input_js)


class ReviewTemplateRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = _read(REVIEW_TEMPLATE)

    def test_template_has_no_inline_dom_event_handlers(self):
        self.assertNotRegex(self.template, r"\bonclick\s*=")
        self.assertNotRegex(self.template, r"\bonchange\s*=")
        self.assertNotRegex(self.template, r"\boninput\s*=")

    def test_template_exposes_review_content_slots(self):
        required_ids = [
            "contentPanel",
            "pathPill",
            "summaryText",
            "footerNote",
        ]
        for element_id in required_ids:
            self.assertIn(f'id="{element_id}"', self.template)
        self.assertNotIn("Recent AI Change", self.template)

    def test_template_uses_dynamic_theme_override_and_hides_footer_copy(self):
        self.assertLess(self.template.index("</style>"), self.template.index('<style id="dynamic-theme-vars">'))
        self.assertIn(".footer {", self.template)
        self.assertIn("display: none;", self.template)
        self.assertNotIn("This review is a saved change record. Rollback can be added later on top of this record.", self.template)

    def test_template_supports_payload_rendering_and_theme_bridge(self):
        self.assertIn("window.setPagePayload = function(payload)", self.template)
        self.assertIn('pageBridge.log("Agent page ready")', self.template)
        self.assertIn('<style id="dynamic-theme-vars">', self.template)
        self.assertIn("window.setTheme = function(theme)", self.template)
        self.assertIn("::-webkit-scrollbar-thumb", self.template)


class AgentPageTemplateRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = _read(AGENT_PAGE_TEMPLATE)

    def test_template_has_no_inline_dom_event_handlers(self):
        self.assertNotRegex(self.template, r"\bonclick\s*=")
        self.assertNotRegex(self.template, r"\bonchange\s*=")
        self.assertNotRegex(self.template, r"\boninput\s*=")

    def test_template_exposes_generic_agent_page_slots(self):
        required_ids = [
            "eyebrow",
            "headline",
            "summary",
            "metaRow",
            "contentTitle",
            "contentBody",
            "sectionsCard",
            "sectionsList",
        ]
        for element_id in required_ids:
            self.assertIn(f'id="{element_id}"', self.template)

    def test_template_supports_payload_rendering(self):
        self.assertIn("window.setPagePayload = function(payload)", self.template)
        self.assertIn("renderRichText(document.getElementById(\"contentBody\")", self.template)
        self.assertIn("sectionsCard.style.display = sections.length ? \"block\" : \"none\";", self.template)
        self.assertIn('bridge.log("Agent page ready")', self.template)
        self.assertIn('<style id="dynamic-theme-vars">', self.template)
        self.assertIn("window.setTheme = function(theme)", self.template)
        self.assertIn("::-webkit-scrollbar-thumb", self.template)


if __name__ == "__main__":
    unittest.main()
