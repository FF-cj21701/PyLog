function parseToolCalls(content) {
            const tools = [];
            const toolPattern = /TOOL_CALL:\s*`([^`]+)`\s*(?:\[(.*?)\])?\s*\n\s*(SUCCESS|ERROR)\s*(.+?)(?=\n|$)/g;

            let match;
            while ((match = toolPattern.exec(content)) !== null) {
                const toolName = match[1];
                const displayArgs = match[2] || '';
                const statusWord = match[3];
                const statusText = match[4];
                const status = statusWord === 'SUCCESS' ? 'success' : 'error';

                // Parse lightweight display arguments.
                const params = {};
                if (displayArgs.includes('title:')) {
                    params.title = displayArgs.match(/title:\s*(.+?)(?:\]|$)/)?.[1] || '';
                } else if (displayArgs.includes('code:')) {
                    params.code = displayArgs.match(/code:\s*(.+?)(?:\]|$)/)?.[1] || '';
                } else if (displayArgs.includes('file:')) {
                    params.filepath = displayArgs.match(/file:\s*(.+?)(?:\]|$)/)?.[1] || '';
                }

                tools.push({
                    name: toolName,
                    status: status,
                    params: params,
                    result: statusText
                });
            }

            return tools;
        }

        // Remove legacy inline tool-call markers from plain message content.
        function removeToolCallMarkers(content) {
            return content.replace(/TOOL_CALL:\s*`([^`]+)`\s*(?:\[(.*?)\])?\s*\n\s*(SUCCESS|ERROR)\s*(.+?)(?=\n|$)/g, '')
                .replace(/\n{3,}/g, '\n\n')
                .trim();
        }

        function getActiveAiMessage() {
            if (window.__activeAiMessageEl && chatContainer.contains(window.__activeAiMessageEl)) {
                return window.__activeAiMessageEl;
            }
            const messages = Array.from(chatContainer.querySelectorAll('.message.ai-message'));
            return messages.length ? messages[messages.length - 1] : null;
        }


        // Append a message to the chat view
        function appendMessage(role, content, timestamp, reasoning = null, tools = null, summary = null, processLogs = null, steps = null, isHtml = false, cards = null) {
            dehydrateOldMessages(15);
            const msgWrapper = document.createElement('div');
            msgWrapper.className = role === 'system' ? 'system-message' : `message ${role}-message`;
            if (role === 'system') {
                const contentDiv = document.createElement('div');
                contentDiv.className = 'content';
                contentDiv.innerHTML = content;
                msgWrapper.appendChild(contentDiv);
                chatContainer.appendChild(msgWrapper);
                scrollToBottom(false);
                return;
            }
            const bubble = document.createElement('div');
            bubble.className = 'bubble';
            msgWrapper.appendChild(bubble);
            const meta = document.createElement('div');
            meta.className = 'meta';
            meta.innerText = timestamp;
            msgWrapper.appendChild(meta);
            if (role === 'ai') {
                window.__activeAiMessageEl = msgWrapper;
                bubble.dataset.runState = 'streaming';
                bubble.dataset.finalContent = content || '';
                bubble._latestRenderData = { reasoning, tools, summary, processLogs, steps, cards };
                const { answerBlock, contentDiv } = ensureAiBubbleStructure(bubble);
                contentDiv.innerHTML = processMessageContent(content, isHtml);
                renderAiDetails(bubble, reasoning, tools, summary, processLogs, steps, content || '', cards);
                answerBlock.classList.remove('is-hidden');
            } else {
                const contentDiv = document.createElement('div');
                contentDiv.className = 'content';
                contentDiv.innerHTML = processMessageContent(content, isHtml);
                bubble.appendChild(contentDiv);
            }
            chatContainer.appendChild(msgWrapper);
            scrollToBottom(role === 'user');
        }

        // Update the active AI message
        function updateLastMessage(content, reasoning = null, tools = null, summary = null, processLogs = null, steps = null, cards = null) {
            const lastMsg = getActiveAiMessage();
            if (!lastMsg || !lastMsg.classList.contains('ai-message')) return;
            const bubble = lastMsg.querySelector('.bubble');
            if (!bubble) return;
            bubble.dataset.finalContent = content || '';
            bubble._latestRenderData = { reasoning, tools, summary, processLogs, steps, cards };
            const { answerBlock, contentDiv } = ensureAiBubbleStructure(bubble);
            renderAiDetails(bubble, reasoning, tools, summary, processLogs, steps, content || '', cards);
            const runState = bubble.dataset.runState || 'streaming';
            const hasVisibleProcessContent =
                (Array.isArray(steps) && steps.length > 0) ||
                (Array.isArray(tools) && tools.length > 0) ||
                !!(reasoning && reasoning.trim()) ||
                !!summary;
            const showAnswerNow = !!content || hasVisibleProcessContent || runState === 'finalized' || runState === 'finished';
            answerBlock.classList.toggle('is-hidden', !showAnswerNow);
            if (!answerBlock.classList.contains('is-hidden')) contentDiv.innerHTML = processMessageContent(content, false);
            scrollToBottom(false);
        }

        // [OPTIMIZED] Append content with requestAnimationFrame throttling
        let pendingUpdate = null;
        function appendToLastMessage(contentDelta, reasoningDelta) {
            const lastMsg = getActiveAiMessage();
            if (!lastMsg || !lastMsg.classList.contains('ai-message')) return;
            const bubble = lastMsg.querySelector('.bubble');
            if (!bubble) return;
            bubble.dataset.finalContent = `${bubble.dataset.finalContent || ''}${contentDelta || ''}`;
            const answerBlock = bubble.querySelector('.answer-block');
            const contentDiv = answerBlock ? answerBlock.querySelector('.content') : null;
            if (contentDiv && !answerBlock.classList.contains('is-hidden')) contentDiv.innerHTML = processMessageContent(bubble.dataset.finalContent || '', false);
            scrollToBottom(false);
        }

        // [NEW] Smart Dehydration logic to save system handles
        function dehydrateOldMessages(limit = 15) {
            const messages = Array.from(chatContainer.querySelectorAll('.message'));
            if (messages.length <= limit) return;

            const toDehydrate = messages.slice(0, messages.length - limit);
            toDehydrate.forEach(msg => {
                if (msg.classList.contains('dehydrated')) return;

                msg.querySelectorAll('.tool-step-details').forEach(details => { details.innerHTML = ''; });
                msg.querySelectorAll('.tool-step-row').forEach(row => { row.classList.remove('expanded'); });
                msg.querySelectorAll('.thinking-inline').forEach(node => {
                    node.innerHTML = '<p><em>(Reasoning archived to save resources)</em></p>';
                    node.removeAttribute('data-raw');
                    node.classList.add('dehydrated');
                });
                msg.querySelectorAll('.content').forEach(content => content.removeAttribute('data-raw'));
                msg.querySelectorAll('.message-details').forEach(details => {
                    details.classList.remove('expanded');
                    details.style.display = 'none';
                    details.innerHTML = '';
                });
                msg.querySelectorAll('.message-meta-pill[data-action="toggle-details"]').forEach(pill => pill.classList.remove('is-active'));
                msg.classList.add('dehydrated');
            });
        }

        function createThinkingPanel(reasoning) {
            const panel = document.createElement('div');
            panel.className = 'thinking-panel expanded'; // Expanded by default

            const header = document.createElement('div');
            header.className = 'thinking-header';
            header.onclick = () => {
                panel.classList.toggle('collapsed');
                panel.classList.toggle('expanded');
            };

            const icon = '<svg class="thinking-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>';
            header.innerHTML = `${icon}<span>Reasoning</span>`;
            panel.appendChild(header);

            const content = document.createElement('div');
            content.className = 'thinking-content';
            content.innerHTML = marked.parse(reasoning);
            panel.appendChild(content);

            // Store the raw Markdown so streaming updates can rebuild the panel.
            panel.setAttribute('data-raw', reasoning);

            return panel;
        }

        // JSON syntax highlighting.
        function syntaxHighlightJson(json) {
            if (typeof json !== 'string') {
                json = JSON.stringify(json, null, 2);
            }

            // Escape HTML first to prevent injection and regex collisions.
            const escaped = json.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

            return escaped.replace(/("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+\-]?\d+)?)/g, function (match) {
                let cls = 'json-number';
                if (/^"/.test(match)) {
                    if (/:$/.test(match)) {
                        cls = 'json-key';
                    } else {
                        cls = 'json-string';
                    }
                } else if (/true|false/.test(match)) {
                    cls = 'json-boolean';
                } else if (/null/.test(match)) {
                    cls = 'json-null';
                }
                return '<span class="' + cls + '">' + match + '</span>';
            });
        }

        // Helper: check whether a string contains valid JSON.
        function isJsonString(str) {
            if (typeof str !== 'string' || str.trim() === '') return false;
            try {
                const item = JSON.parse(str);
                return typeof item === 'object' && item !== null;
            } catch (e) {
                return false;
            }
        }

        function summarizeScriptState(scriptState) {
            if (!scriptState || typeof scriptState !== 'object') return '';

            const parts = [];
            if (scriptState.script_path) {
                parts.push(`script: ${scriptState.script_path}`);
            } else if (scriptState.editor_id) {
                parts.push(`editor: ${scriptState.editor_id}`);
            }
            if (scriptState.is_preview_active) {
                parts.push('preview active');
            }
            if (scriptState.has_unsaved_changes) {
                parts.push('unsaved changes');
            }
            return parts.join(' | ');
        }

        function extractToolDisplayResult(rawResult, status) {
            const fallback = rawResult == null
                ? (status === 'pending' ? 'Waiting for result...' : 'No output')
                : (typeof rawResult === 'string' ? rawResult : JSON.stringify(rawResult, null, 2));
            const response = {
                displayResult: fallback,
                isFormatted: false
            };

            if (rawResult == null) {
                return response;
            }

            let jsonResult = rawResult;
            try {
                if (typeof rawResult === 'string') {
                    if (rawResult.trim() === '') {
                        return response;
                    }
                    jsonResult = JSON.parse(rawResult);
                }

                const scriptStateText = summarizeScriptState(jsonResult.script_state);
                let baseText = '';

                if (jsonResult.summary) {
                    baseText = String(jsonResult.summary);
                } else if (jsonResult.message) {
                    baseText = String(jsonResult.message);
                } else if (jsonResult.error) {
                    baseText = String(jsonResult.error);
                } else if (jsonResult.terminal) {
                    baseText = String(jsonResult.terminal);
                } else if (jsonResult.output) {
                    baseText = String(jsonResult.output);
                } else if (typeof jsonResult.content === 'string' && jsonResult.content.trim() !== '') {
                    baseText = jsonResult.content;
                } else if (jsonResult.ok === true) {
                    baseText = 'Operation successful';
                }

                if (baseText) {
                    if (scriptStateText) {
                        baseText = `${baseText}\n${scriptStateText}`;
                    }
                    response.displayResult = baseText;
                    return response;
                }

                if (typeof jsonResult === 'object' && jsonResult !== null) {
                    response.displayResult = JSON.stringify(jsonResult, null, 2);
                    response.isFormatted = true;
                    return response;
                }
            } catch (e) { }

            return response;
        }

        function getToolStatusText(status) {
            if (status === 'success') return 'Completed';
            if (status === 'error') return 'Failed';
            return 'Running';
        }

        function getToolSummaryText(tool) {
            const parsedResult = extractToolDisplayResult(tool?.result || '', tool?.status || 'pending');
            const resultText = String(parsedResult.displayResult || '').replace(/\s+/g, ' ').trim();
            if (resultText && resultText !== 'Waiting for result...' && resultText !== 'No output') {
                return resultText.length > 140 ? `${resultText.slice(0, 140)}...` : resultText;
            }

            const params = tool?.params || {};
            const summaryParts = [];
            Object.keys(params).forEach(key => {
                if (key === 'code') return;
                const value = params[key];
                if (value == null || value === '') return;
                summaryParts.push(`${key}: ${String(value)}`);
            });

            if (summaryParts.length) {
                const joined = summaryParts.join(' | ');
                return joined.length > 140 ? `${joined.slice(0, 140)}...` : joined;
            }
            return getToolStatusText(tool?.status);
        }

        function createToolDetailSection(label, text, options = {}) {
            if (!text || !String(text).trim()) return null;

            const section = document.createElement('div');
            section.className = 'tool-detail-section';

            const title = document.createElement('div');
            title.className = 'tool-detail-label';
            title.textContent = label;

            const body = document.createElement('pre');
            body.className = options.code ? 'tool-detail-code' : 'tool-detail-text';
            if (options.error) body.classList.add('is-error');
            body.textContent = String(text).trim();

            section.appendChild(title);
            section.appendChild(body);
            return section;
        }

        async function copyToClipboard(btn, event) {
            event.stopPropagation();
            const text = btn.nextElementSibling.innerText;
            try {
                await navigator.clipboard.writeText(text);
                btn.classList.add('copied');
                const originalInner = btn.innerHTML;
                btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>';
                setTimeout(() => {
                    btn.classList.remove('copied');
                    btn.innerHTML = originalInner;
                }, 2000);
            } catch (err) {
                console.error('Failed to copy: ', err);
            }
        }

        // Create a summary card
        function createSummaryCard(summary) {
            const card = document.createElement('div');
            card.className = 'summary-card';

            let sectionsHtml = '';
            if (summary.sections) {
                summary.sections.forEach(section => {
                    sectionsHtml += `
                        <div class="summary-section">
                            <div class="summary-section-title">${section.title}</div>
                            <div>${marked.parse(section.content)}</div>
                        </div>
                    `;
                });
            }

            card.innerHTML = `
                <div class="summary-header">
                    <svg class="summary-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
                    <span class="summary-title">Execution Summary</span>
                </div>
                <div class="summary-content">
                    ${summary.content ? marked.parse(summary.content) : ''}
                    ${sectionsHtml}
                </div>
            `;

            return card;
        }

        // Helper functions
        function processMessageContent(content, isHtml) {
            if (isHtml) return content || '';
            let processedContent = (content || '').replace(/@\[(file|plot|selection|curve|well|bubbles|track):([^:]+):([^\]]+)\]/g, (match, type, path, name) => {
                let dataAttrs = `data-type="${type}" data-path="${path}" data-name="${name}"`;
                let iconMarkup = "";

                if (type === 'bubbles') {
                    iconMarkup = '<svg class="tag-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><path d="M8 14s1.5 2 4 2 4-2 4-2"></path><line x1="9" y1="9" x2="9.01" y2="9"></line><line x1="15" y1="9" x2="15.01" y2="9"></line></svg>';
                } else if (type === 'curve' || type === 'plot') {
                    iconMarkup = '<svg class="tag-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"></path><path d="M18.7 8l-5.1 5.2-2.8-2.7L7 14.3"></path></svg>';
                    const parts = path.split('/');
                    if (parts.length === 2 && type === 'curve') {
                        dataAttrs += ` data-well-id="${parts[0]}" data-curve-id="${parts[1]}"`;
                    }
                } else {
                    iconMarkup = '<svg class="tag-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg>';
                }
                return `<span class="mention-pill" ${dataAttrs}>${iconMarkup}<span>${name}</span></span>`;
            });
            processedContent = renderMathMarkup(processedContent);
            return marked.parse(processedContent);
        }

        function renderMathMarkup(content) {
            if (!content) return content;

            let rendered = content;

            rendered = rendered.replace(/\\\[((?:.|\r?\n)*?)\\\]/g, (_, expr) => {
                return `\n<div class="math-block">${renderLatexExpression(expr)}</div>\n`;
            });

            rendered = rendered.replace(/\\\(((?:.|\r?\n)*?)\\\)/g, (_, expr) => {
                return `<span class="math-inline">${renderLatexExpression(expr)}</span>`;
            });

            return rendered;
        }

        function renderLatexExpression(expr) {
            let html = escapeHtml((expr || '').trim());

            html = html.replace(/\\left/g, '').replace(/\\right/g, '');
            html = html.replace(/\\cdot/g, '&middot;');
            html = html.replace(/\\times/g, '&times;');
            html = html.replace(/\\leq/g, '&le;');
            html = html.replace(/\\geq/g, '&ge;');
            html = html.replace(/\\neq/g, '&ne;');
            html = html.replace(/\\approx/g, '&asymp;');

            for (let i = 0; i < 6; i += 1) {
                html = html.replace(
                    /\\frac\{([^{}]+)\}\{([^{}]+)\}/g,
                    '<span class="math-frac"><span class="math-num">$1</span><span class="math-den">$2</span></span>'
                );
            }

            html = html.replace(/\\text\{([^{}]+)\}/g, '<span class="math-text">$1</span>');
            html = html.replace(/\^\{([^{}]+)\}/g, '<sup>$1</sup>');
            html = html.replace(/_\{([^{}]+)\}/g, '<sub>$1</sub>');
            html = html.replace(/\^([A-Za-z0-9]+)/g, '<sup>$1</sup>');
            html = html.replace(/_([A-Za-z0-9]+)/g, '<sub>$1</sub>');
            html = html.replace(/\\/g, '');

            return html;
        }

        function escapeHtml(text) {
            if (typeof text !== 'string') return text;
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        // Toggle a tool box between expanded and collapsed.
        function toggleToolBox(toolBox) {
            // Collapse sibling tool boxes first.
            const parent = toolBox.parentElement;
            if (parent) {
                parent.querySelectorAll('.tool-box').forEach(box => {
                    if (box !== toolBox) {
                        box.classList.remove('expanded');
                    }
                });
            }

            // Toggle the current tool box.
            toolBox.classList.toggle('expanded');
        }

        // Collapse all tool boxes.
        function collapseAllToolBoxes() {
            const allToolBoxes = document.querySelectorAll('.tool-box');
            allToolBoxes.forEach(box => {
                box.classList.remove('expanded');
            });
        }
        function scrollToBottom(force = false) {
            const threshold = 100;
            const isAtBottom = (chatContainer.scrollHeight - chatContainer.scrollTop - chatContainer.clientHeight) < threshold;
            if (force || isAtBottom) {
                chatContainer.scrollTop = chatContainer.scrollHeight;
            }
        }

        function clearChat() {
            window.__activeAiMessageEl = null;
            chatContainer.innerHTML = '';
            clearSelectionContext();
            if (bridge) bridge.clearChat();
        }

        // Tool panel actions
