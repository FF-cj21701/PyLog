function parseToolResultObject(rawResult) {
            if (rawResult == null) return null;
            if (typeof rawResult === 'object') return rawResult;
            if (typeof rawResult !== 'string') return null;
            if (!rawResult.trim()) return null;
            try {
                return JSON.parse(rawResult);
            } catch (e) {
                return null;
            }
        }

        function getTerminalMeta(tool) {
            const resultObj = parseToolResultObject(tool?.result);
            if (!resultObj || typeof resultObj !== 'object') return null;

            const isTerminalLike = resultObj.display_type === 'terminal'
                || Object.prototype.hasOwnProperty.call(resultObj, 'terminal')
                || Object.prototype.hasOwnProperty.call(resultObj, 'stdout')
                || Object.prototype.hasOwnProperty.call(resultObj, 'stderr');

            if (!isTerminalLike) return null;

            const mode = String(resultObj.terminal_mode || '').trim();
            const command = String(resultObj.command || tool?.params?.command || '').trim();
            const stdout = String(resultObj.stdout || '').trim();
            const stderr = String(resultObj.stderr || '').trim();
            const terminal = String(resultObj.terminal || '').trim();
            const exitCode = typeof resultObj.exit_code === 'number' ? resultObj.exit_code : null;

            let output = terminal;
            if (!output) {
                output = [stdout, stderr].filter(Boolean).join('\n').trim();
            }

            return {
                mode,
                command,
                output,
                stderr,
                exitCode
            };
        }

        function createTerminalDetail(tool, terminalMeta) {
            const section = document.createElement('div');
            section.className = 'tool-detail-section';

            const title = document.createElement('div');
            title.className = 'tool-detail-label';
            title.textContent = terminalMeta?.mode === 'python' ? 'Python' : 'Shell';

            const modeLabel = terminalMeta?.mode === 'shell'
                ? 'Shell'
                : terminalMeta?.mode === 'python'
                    ? 'Python'
                    : terminalMeta?.mode === 'history'
                        ? 'History'
                        : 'Terminal';

            const promptChar = terminalMeta?.mode === 'python' ? '>>>' : '$';
            const commandText = terminalMeta?.command || tool?.name || 'Terminal';
            const outputText = terminalMeta?.output || 'Done (No Output)';
            const hasError = tool?.status === 'error' || Boolean(terminalMeta?.stderr) || (terminalMeta?.exitCode != null && terminalMeta.exitCode !== 0);
            const exitCode = terminalMeta?.exitCode;
            const statusText = hasError ? 'Failed' : 'Success';
            const exitText = exitCode == null ? '' : `Exit ${exitCode}`;

            const body = document.createElement('div');
            body.className = 'terminal-inline';
            body.innerHTML = `
                <div class="terminal-inline-command">${escapeHtml(promptChar)} ${escapeHtml(commandText)}</div>
                <div class="terminal-inline-output ${hasError ? 'is-error' : ''}">${escapeHtml(outputText)}</div>
                <div class="terminal-inline-status">
                    ${exitText ? `<span>${escapeHtml(exitText)}</span> ` : ''}<span>${escapeHtml(statusText)}</span>
                </div>
            `;

            section.appendChild(title);
            section.appendChild(body);
            return section;
        }

        function createToolDetailBlock(tool) {
            const block = document.createElement('div');
            block.className = 'tool-detail-block';

            const terminalMeta = getTerminalMeta(tool);

            const displayParams = { ...(tool?.params || {}) };
            delete displayParams.code;
            if (!terminalMeta && Object.keys(displayParams).length > 0) {
                const inputSection = createToolDetailSection('Input', JSON.stringify(displayParams, null, 2), { code: true });
                if (inputSection) block.appendChild(inputSection);
            }

            if (!terminalMeta && tool?.params?.code) {
                const codeSection = createToolDetailSection('Code', tool.params.code, { code: true });
                if (codeSection) block.appendChild(codeSection);
            }

            if (terminalMeta) {
                block.appendChild(createTerminalDetail(tool, terminalMeta));
                return block;
            }

            const parsedResult = extractToolDisplayResult(tool?.result || '', tool?.status || 'pending');
            const outputText = parsedResult.displayResult || '';
            if (outputText && outputText !== 'Waiting for result...' && outputText !== 'No output') {
                const label = (tool?.name === 'run_terminal_command' || tool?.name === 'tool_get_terminal_content' || tool?.name === 'run_script' || tool?.name === 'run_shell_command')
                    ? 'Terminal'
                    : 'Output';
                const outputSection = createToolDetailSection(label, outputText, {
                    code: true,
                    error: tool?.status === 'error'
                });
                if (outputSection) block.appendChild(outputSection);
            }

            if (!block.childElementCount) {
                const emptySection = createToolDetailSection('Status', getToolStatusText(tool?.status), {
                    error: tool?.status === 'error'
                });
                if (emptySection) block.appendChild(emptySection);
            }

            return block;
        }

        // 创建工具调用信息框 [MODERNIZED]
        function createToolBox(tool) {
            const box = document.createElement('div');
            box.className = 'tool-box';

            const statusClass = tool.status === 'success' ? 'pill-success' :
                tool.status === 'error' ? 'pill-error' : 'pill-pending';
            const statusText = tool.status === 'success' ? 'Success' :
                tool.status === 'error' ? 'Failed' : 'Running';

            let contentHtml = '';

            // 输入参数部分
            if (tool.params && Object.keys(tool.params).length > 0) {
                let displayParams = { ...tool.params };
                delete displayParams.code; // 跳过代码参数

                if (Object.keys(displayParams).length > 0) {
                    contentHtml += `
                        <div class="tool-section">
                            <div class="tool-section-title">Input</div>
                            <div class="tool-data-block">
                                <div class="copy-btn" onclick="copyToClipboard(this, event)" title="Copy input">
                                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                                </div>
                                <pre>${syntaxHighlightJson(displayParams)}</pre>
                            </div>
                        </div>
                    `;
                }
            }

            // 结果部分
            if (tool.result || tool.status !== 'pending') {
                const resultClass = tool.status === 'error' ? 'tool-result-error' : 'tool-result-success';
                const parsedResult = extractToolDisplayResult(tool.result || '', tool.status);
                const displayResult = parsedResult.displayResult;
                const isFormatted = parsedResult.isFormatted;

                const finalOutput = isFormatted ? syntaxHighlightJson(displayResult) : escapeHtml(displayResult);

                contentHtml += `
                    <div class="tool-section">
                        <div class="tool-section-title">Output</div>
                        <div class="tool-data-block ${resultClass}">
                            <div class="copy-btn" onclick="copyToClipboard(this, event)" title="Copy result">
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                            </div>
                            <pre>${finalOutput}</pre>
                        </div>
                    </div>
                `;
            }

            box.innerHTML = `
                <div class="tool-header" onclick="toggleToolBox(this.parentElement)">
                    <div class="tool-icon-wrapper">
                        <svg class="tool-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path>
                        </svg>
                    </div>
                    <span class="tool-name">${tool.name}</span>
                    <div class="status-pill ${statusClass}">
                        <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor">
                            ${tool.status === 'success' ? '<path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>' :
                    tool.status === 'error' ? '<path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>' :
                        '<circle cx="12" cy="12" r="10"/>'}
                        </svg>
                        <span>${statusText}</span>
                    </div>
                    <svg class="tool-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"></polyline></svg>
                </div>
                <div class="tool-content">${contentHtml}</div>
            `;

            return box;
        }

        function getToolStepStatusInfo(status) {
            // "?????????????ompleted"
            if (status === 'success') return { text: '', cls: 'tool-step-status--completed', icon: `` };
            if (status === 'error') return { text: 'Failed', cls: 'tool-step-status--failed', icon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="10" height="10"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg> ` };
            // pending / running
            return { text: 'Running', cls: 'tool-step-status--running', icon: `<svg class="tool-step-spinner" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M21 12a9 9 0 1 1-6.219-8.56"></path></svg> ` };
        }

        function getToolStepKey(tool, fallbackIndex = 0) {
            const params = tool?.params ? JSON.stringify(tool.params) : '';
            const command = tool?.command || tool?.params?.command || '';
            const title = tool?.title || '';
            const stepId = tool?.id || tool?.step_id || '';
            return [
                tool?.name || tool?.kind || 'tool',
                stepId,
                title,
                command,
                params,
                fallbackIndex
            ].join('::');
        }

        function getExpandedToolStepKeys(bubble) {
            if (!bubble) return new Set();
            if (!bubble._expandedToolStepKeys) bubble._expandedToolStepKeys = new Set();
            return bubble._expandedToolStepKeys;
        }

        function syncExpandedToolStepKeys(bubble) {
            if (!bubble) return;
            const expandedKeys = new Set();
            bubble.querySelectorAll('.tool-step-row.expanded[data-tool-step-key]').forEach(row => {
                expandedKeys.add(row.dataset.toolStepKey);
            });
            bubble._expandedToolStepKeys = expandedKeys;
        }

        function createToolStepRow(tool, rowKey = '') {
            const row = document.createElement('div');
            row.className = 'tool-step-row';
            if (rowKey) row.dataset.toolStepKey = rowKey;

            const summary = document.createElement('button');
            summary.type = 'button';
            summary.className = 'tool-step-summary';

            const summaryText = escapeHtml(getToolSummaryText(tool));
            const { text: statusText, cls: statusCls, icon: statusIcon } = getToolStepStatusInfo(tool?.status);
            summary.innerHTML = `
                <svg class="tool-step-leading" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path>
                </svg>
                <span class="tool-step-main">
                    <span class="tool-step-name">${escapeHtml(tool?.name || 'Tool')}</span>
                    <span class="tool-step-status ${statusCls}">${statusIcon}${escapeHtml(statusText)}</span>
                    <span class="tool-step-summary-text">${summaryText}</span>
                </span>
                <svg class="tool-step-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"></polyline></svg>
            `;

            const details = document.createElement('div');
            details.className = 'tool-step-details';
            details.appendChild(createToolDetailBlock(tool));

            summary.onclick = (event) => {
                event.stopPropagation();
                row.classList.toggle('expanded');
                syncExpandedToolStepKeys(row.closest('.bubble'));
            };

            row.appendChild(summary);
            row.appendChild(details);
            return row;
        }

