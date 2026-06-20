function ensureAiBubbleStructure(bubble) {
            bubble.classList.add('has-structured-layout');
            let metaStrip = bubble.querySelector('.message-meta-strip');
            if (!metaStrip) {
                metaStrip = document.createElement('div');
                metaStrip.className = 'message-meta-strip';
                bubble.prepend(metaStrip);
                metaStrip.style.display = 'none';
            }
            let details = bubble.querySelector('.message-details');
            if (!details) {
                details = document.createElement('div');
                details.className = 'message-details';
                if (metaStrip.nextSibling) bubble.insertBefore(details, metaStrip.nextSibling);
                else bubble.appendChild(details);
                details.style.display = 'none';
            }
            let answerDivider = bubble.querySelector('.answer-divider');
            if (!answerDivider) {
                answerDivider = document.createElement('div');
                answerDivider.className = 'answer-divider';
                answerDivider.textContent = 'Final Message';
                bubble.appendChild(answerDivider);
            }
            answerDivider.classList.add('is-hidden');
            let answerBlock = bubble.querySelector('.answer-block');
            if (!answerBlock) {
                answerBlock = document.createElement('div');
                answerBlock.className = 'answer-block';

                const historyContainer = document.createElement('div');
                historyContainer.className = 'history-container';
                answerBlock.appendChild(historyContainer);

                const cardsContainer = document.createElement('div');
                cardsContainer.className = 'message-cards-container';
                answerBlock.appendChild(cardsContainer);

                const contentDiv = document.createElement('div');
                contentDiv.className = 'content live-content';
                answerBlock.appendChild(contentDiv);

                bubble.appendChild(answerBlock);
            }

            const historyContainer = answerBlock.querySelector('.history-container');
            const cardsContainer = answerBlock.querySelector('.message-cards-container');
            const contentDiv = answerBlock.querySelector('.live-content');

            return { answerBlock, historyContainer, cardsContainer, contentDiv, metaStrip, details };
        }

        function rebuildBubbleDetails(bubble) {
            if (!bubble || !bubble._latestRenderData) return;
            bubble._forceDetailsRebuild = true;
            renderAiDetails(
                bubble,
                bubble._latestRenderData.reasoning,
                bubble._latestRenderData.tools,
                bubble._latestRenderData.summary,
                bubble._latestRenderData.processLogs,
                bubble._latestRenderData.steps,
                bubble.dataset.finalContent || '',
                bubble._latestRenderData.cards
            );
        }

        function toggleMessageDetails(target) {
            const bubble = target.closest('.bubble');
            if (!bubble) return;
            const details = bubble.querySelector('.message-details');
            if (!details) return;
            const expanded = !details.classList.contains('expanded');
            if (expanded) {
                details.classList.add('expanded');
                if (!details.childElementCount) {
                    rebuildBubbleDetails(bubble);
                } else {
                    details.style.display = 'flex';
                    bubble.querySelectorAll('.message-meta-pill[data-action="toggle-details"]').forEach(pill => pill.classList.add('is-active'));
                }
            } else {
                details.classList.remove('expanded');
                details.style.display = 'none';
                details.innerHTML = '';
                bubble.querySelectorAll('.message-meta-pill[data-action="toggle-details"]').forEach(pill => pill.classList.remove('is-active'));
            }
        }

        function setBubbleDetailsExpanded(bubble, expanded) {
            if (!bubble) return;
            const details = bubble.querySelector('.message-details');
            if (!details) return;
            if (expanded) {
                details.classList.add('expanded');
                if (!details.childElementCount) {
                    rebuildBubbleDetails(bubble);
                } else {
                    details.style.display = 'flex';
                    bubble.querySelectorAll('.message-meta-pill[data-action="toggle-details"]').forEach(pill => pill.classList.add('is-active'));
                }
            } else {
                details.classList.remove('expanded');
                details.style.display = 'none';
                details.innerHTML = '';
                bubble.querySelectorAll('.message-meta-pill[data-action="toggle-details"]').forEach(pill => pill.classList.remove('is-active'));
            }
        }

        function createMetaPill(label, options = {}) {
            const pill = document.createElement('button');
            pill.className = 'message-meta-pill';
            pill.type = 'button';
            if (options.action === 'toggle-details') {
                pill.innerHTML = `<span>${escapeHtml(label)}</span><svg class="details-trigger-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 18 15 12 9 6"></polyline></svg>`;
            } else {
                pill.textContent = label;
            }
            if (options.interactive) {
                pill.classList.add('interactive');
                pill.dataset.action = options.action || 'toggle-details';
                pill.onclick = (event) => {
                    event.stopPropagation();
                    if (typeof options.onClick === 'function') options.onClick(pill);
                };
            } else {
                pill.disabled = true;
            }
            if (options.active) pill.classList.add('is-active');
            return pill;
        }

        function createDetailsSection(title, badgeLabel = null) {
            const section = document.createElement('div');
            section.className = 'message-details-section';
            const header = document.createElement('div');
            header.className = 'message-details-title';
            header.appendChild(document.createTextNode(title));
            if (badgeLabel) {
                const badge = document.createElement('span');
                badge.className = 'message-meta-pill';
                badge.textContent = badgeLabel;
                header.appendChild(badge);
            }
            section.appendChild(header);
            const body = document.createElement('div');
            section.appendChild(body);
            return { section, body };
        }

        function createThinkingInline(reasoning) {
            const node = document.createElement('div');
            node.className = 'thinking-inline';
            node.innerHTML = marked.parse(reasoning || '');
            node.setAttribute('data-raw', reasoning || '');
            return node;
        }

        function createFallbackToolStepRow(tool, error) {
            const row = document.createElement('div');
            row.className = 'tool-step-row expanded';
            const summary = document.createElement('div');
            summary.className = 'tool-step-summary';
            summary.innerHTML = `
                <span class="tool-step-main">
                    <span class="tool-step-name">${escapeHtml(tool?.name || 'Tool')}</span>
                    <span class="tool-step-status tool-step-status--failed">Render failed</span>
                    <span class="tool-step-summary-text">${escapeHtml((error && error.message) || 'Unable to render tool step')}</span>
                </span>
            `;
            const details = document.createElement('div');
            details.className = 'tool-step-details';
            details.style.display = 'block';
            details.innerHTML = `<div class="tool-detail-block"><div class="tool-detail-section"><div class="tool-detail-label">Output</div><pre class="tool-detail-code is-error">${escapeHtml(JSON.stringify(tool || {}, null, 2))}</pre></div></div>`;
            row.appendChild(summary);
            row.appendChild(details);
            return row;
        }

        function buildToolStepRow(tool, rowKey) {
            try {
                return createToolStepRow(tool, rowKey);
            } catch (error) {
                console.error('Failed to render tool step row', error, tool);
                return createFallbackToolStepRow(tool, error);
            }
        }


        function createMessageCard(card) {
            if (!card || card.type !== 'file_change') return null;

            const node = document.createElement('div');
            node.className = 'message-card message-card-file-change';

            const stats = [];
            if (typeof card.added === 'number') stats.push(`<span class="message-card-delta positive">+${card.added}</span>`);
            if (typeof card.removed === 'number') stats.push(`<span class="message-card-delta negative">-${card.removed}</span>`);

            const actionsHtml = Array.isArray(card.actions)
                ? card.actions.map((action) => {
                    const encoded = encodeURIComponent(JSON.stringify({ action: action.id, payload: action.payload || {} }));
                    return `<button class="message-card-action" type="button" data-card-action="${encoded}">${escapeHtml(action.label || action.id)}</button>`;
                }).join('')
                : '';

            node.innerHTML = `
                <div class="message-card-main">
                    <div class="message-card-icon">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg>
                    </div>
                    <div class="message-card-copy">
                        <div class="message-card-title">${escapeHtml(card.title || 'Edited file')}</div>
                        <div class="message-card-subtitle">${escapeHtml(card.path || card.subtitle || '')}</div>
                        <div class="message-card-stats">${stats.join(' ')}</div>
                    </div>
                </div>
                <div class="message-card-actions">${actionsHtml}</div>
            `;

            node.querySelectorAll('[data-card-action]').forEach((btn) => {
                btn.addEventListener('click', function(event) {
                    event.stopPropagation();
                    const activeBridge = window.pyBridge || (typeof bridge !== 'undefined' ? bridge : null);
                    if (activeBridge && activeBridge.onMessageCardAction) {
                        activeBridge.onMessageCardAction(decodeURIComponent(btn.dataset.cardAction || ''));
                    }
                });
            });

            return node;
        }

        function renderMessageCards(cardsContainer, cards) {
            if (!cardsContainer) return;
            cardsContainer.innerHTML = '';
            const list = Array.isArray(cards) ? cards : [];
            cardsContainer.style.display = list.length ? 'flex' : 'none';
            if (list.length) {
                const header = document.createElement('div');
                header.className = 'message-cards-header';
                header.textContent = list.length === 1 ? 'File changed in this reply' : `Files changed in this reply (${list.length})`;
                cardsContainer.appendChild(header);
            }
            list.forEach((card) => {
                const node = createMessageCard(card);
                if (node) cardsContainer.appendChild(node);
            });
        }

        function renderAiDetails(bubble, reasoning, tools, summary, processLogs = null, steps = null, liveContent = '', cards = null) {
            const runState = bubble.dataset.runState || 'idle';
            const { details, answerBlock, historyContainer, cardsContainer, contentDiv, metaStrip } = ensureAiBubbleStructure(bubble);
            const normalizedSteps = Array.isArray(steps) ? steps : [];
            const isFinished = runState === 'finished' || runState === 'finalized';
            const expandedToolStepKeys = getExpandedToolStepKeys(bubble);
            const forceDetailsRebuild = bubble._forceDetailsRebuild === true;
            const structureSignature = JSON.stringify({
                runState,
                reasoning: reasoning || '',
                tools: tools || null,
                summary: summary || null,
                steps: normalizedSteps,
                cards: cards || null
            });

            bubble._latestRenderData = { reasoning, tools, summary, processLogs, steps, cards };
            syncExpandedToolStepKeys(bubble);

            if (bubble._structureRenderSignature === structureSignature && !forceDetailsRebuild) {
                answerBlock.classList.remove('is-hidden');
                const hasVisibleStreamingContent = historyContainer.childElementCount > 0 || !!(liveContent || '').trim();
                renderMessageCards(cardsContainer, cards);
                contentDiv.innerHTML = hasVisibleStreamingContent
                    ? processMessageContent(liveContent, false)
                    : '<div class="ai-loading-placeholder">Working...</div>';
                return;
            }

            bubble._forceDetailsRebuild = false;
            bubble._structureRenderSignature = structureSignature;
            historyContainer.innerHTML = '';
            details.innerHTML = '';
            metaStrip.innerHTML = '';

            if (!isFinished) {
                // 1. STREAMING MODE: inline history within text block, no details container
                details.style.display = 'none';
                metaStrip.style.display = 'none';
                answerBlock.classList.remove('is-hidden');

                historyContainer.style.display = 'flex';
                historyContainer.style.flexDirection = 'column';
                historyContainer.style.gap = '6px';
                historyContainer.style.marginBottom = '6px';

                if (normalizedSteps.length > 0) {
                    normalizedSteps.forEach((step, index) => {
                        if (!step || !step.kind) return;
                        if (step.kind === 'tool') {
                            const rowKey = getToolStepKey(step, index);
                            const row = buildToolStepRow(step, rowKey);
                            if (expandedToolStepKeys.has(rowKey)) row.classList.add('expanded');
                            historyContainer.appendChild(row);
                        } else if (step.kind === 'round_break') {
                            const divider = document.createElement('div');
                            divider.className = 'react-round-break';
                            historyContainer.appendChild(divider);
                        } else if (step.kind === 'text' || step.kind === 'live_text' || step.kind === 'reasoning') {
                            const div = document.createElement('div');
                            div.className = 'historical-text content';
                            div.innerHTML = processMessageContent(step.content, false);
                            historyContainer.appendChild(div);
                        }
                    });
                } else if (tools && tools.length) {
                    tools.forEach((tool, index) => {
                        const rowKey = getToolStepKey(tool, index);
                        const row = buildToolStepRow(tool, rowKey);
                        if (expandedToolStepKeys.has(rowKey)) row.classList.add('expanded');
                        historyContainer.appendChild(row);
                    });
                }

                if (reasoning && (!normalizedSteps.length || !normalizedSteps.some(s => s.kind === 'reasoning'))) {
                    historyContainer.appendChild(createThinkingInline(reasoning));
                }

                if (summary) {
                    historyContainer.appendChild(createSummaryCard(summary));
                }

                renderMessageCards(cardsContainer, cards);
                const hasVisibleStreamingContent = historyContainer.childElementCount > 0 || !!(liveContent || '').trim();
                contentDiv.innerHTML = hasVisibleStreamingContent
                    ? processMessageContent(liveContent, false)
                    : '<div class="ai-loading-placeholder">Working...</div>';

            } else {
                // 2. FINISHED MODE: Steps encapsulated into details, leaving ONLY final text outside
                historyContainer.style.display = 'none';

                let hasDetails = false;

                if (normalizedSteps.length > 0) {
                    hasDetails = true;
                    const section = document.createElement('div');
                    section.className = 'message-details-section';
                    const list = document.createElement('div');
                    list.className = 'steps-list';

                    normalizedSteps.forEach((step, index) => {
                        if (!step || !step.kind) return;
                        const item = document.createElement('div');
                        item.className = 'step-item';
                        if (step.kind === 'round_break') {
                            const divider = document.createElement('div');
                            divider.className = 'react-round-break';
                            item.appendChild(divider);
                        } else if (step.kind === 'text' || step.kind === 'live_text' || step.kind === 'reasoning') {
                            item.appendChild(createThinkingInline(step.content));
                        } else if (step.kind === 'tool') {
                            const rowKey = getToolStepKey(step, index);
                            const row = buildToolStepRow(step, rowKey);
                            if (expandedToolStepKeys.has(rowKey)) row.classList.add('expanded');
                            item.appendChild(row);
                        }
                        list.appendChild(item);
                    });
                    section.appendChild(list);
                    details.appendChild(section);

                } else if (tools && tools.length) {
                    hasDetails = true;
                    const { section, body } = createDetailsSection('Tools');
                    tools.forEach((tool, index) => {
                        const rowKey = getToolStepKey(tool, index);
                        const row = buildToolStepRow(tool, rowKey);
                        if (expandedToolStepKeys.has(rowKey)) row.classList.add('expanded');
                        body.appendChild(row);
                    });
                    details.appendChild(section);
                }

                if (summary) {
                    hasDetails = true;
                    const { section, body } = createDetailsSection('Metadata');
                    body.appendChild(createSummaryCard(summary));
                    details.appendChild(section);
                }

                if (hasDetails) {
                    const isExpanded = details.classList.contains('expanded');
                    details.style.display = isExpanded ? 'flex' : 'none';
                    metaStrip.style.display = 'flex';
                    metaStrip.appendChild(createMetaPill('View Details', {
                        interactive: true,
                        active: isExpanded,
                        action: 'toggle-details',
                        onClick: toggleMessageDetails
                    }));
                } else {
                    details.style.display = 'none';
                    metaStrip.style.display = 'none';
                }

                renderMessageCards(cardsContainer, cards);
                // Append Final Content
                answerBlock.classList.remove('is-hidden');
                if (liveContent) {
                    contentDiv.innerHTML = processMessageContent(liveContent, false);
                } else {
                    contentDiv.innerHTML = processMessageContent('Task completed successfully.', false);
                }
            }
        }

        function setLastAiMessageState(state) {
            const lastMsg = (typeof getActiveAiMessage === 'function') ? getActiveAiMessage() : chatContainer.lastElementChild;
            if (!lastMsg || !lastMsg.classList.contains('ai-message')) return;
            const bubble = lastMsg.querySelector('.bubble');
            if (!bubble) return;
            bubble.dataset.runState = state || 'idle';
            if (bubble._latestRenderData) {
                renderAiDetails(
                    bubble,
                    bubble._latestRenderData.reasoning,
                    bubble._latestRenderData.tools,
                    bubble._latestRenderData.summary,
                    bubble._latestRenderData.processLogs,
                    bubble._latestRenderData.steps,
                    bubble.dataset.finalContent,
                    bubble._latestRenderData.cards
                );
            }
            if (state === 'finished' || state === 'finalized') {
                setBubbleDetailsExpanded(bubble, false);
                dehydrateOldMessages(15);
            }
        }



