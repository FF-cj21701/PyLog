function updateSendButton() {
            const text = input.innerText.trim();
            const hasPills = input.querySelector('.mention-pill') !== null;
            sendBtn.disabled = (text.length === 0 && !hasPills && selectedContexts.length === 0);
        }

        let allFiles = [];
        let filteredItems = [];
        let selectedMentionIndex = 0;
        let mentionQuery = "";
        let isMentioning = false;
        let mentionMode = 'root'; // 'root' | 'file' | 'folder' | 'code' | 'terminal' | 'conversation' | 'wells' | 'well_curves'
        let currentWell = null; // Store selected well for well_curves mode
        let selectedContexts = [];
        let isComposing = false;

        const MENTION_CATEGORIES = [
            { id: 'opened', label: 'Opened Windows', icon: '<svg class="mention-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="9" y1="3" x2="9" y2="21"></line></svg>', description: 'Reference any currently open script or plot' },
            { id: 'wells', label: 'Wells', icon: '<svg class="mention-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 21h10"></path><path d="M12 21V10"></path><path d="M12 10l5 5"></path><path d="M12 10l-5 5"></path><path d="M12 3l5 5-5 5-5-5 5-5z"></path></svg>', description: 'Reference wells and curves from database' },
            { id: 'file', label: 'Files', icon: '<svg class="mention-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg>', description: 'Search and reference project files' },
            { id: 'folder', label: 'Directories', icon: '<svg class="mention-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>', description: 'Reference entire folders' },
            { id: 'conversation', label: 'Conversation', icon: '<svg class="mention-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path></svg>', description: 'Reference previous messages' },
            { id: 'bubbles', label: 'Bubbles', icon: '<svg class="mention-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><path d="M8 14s1.5 2 4 2 4-2 4-2"></path><line x1="9" y1="9" x2="9.01" y2="9"></line><line x1="15" y1="9" x2="15.01" y2="9"></line></svg>', description: 'Reference all active context items' }
        ];

        // Handle input events
        input.addEventListener('compositionstart', () => { isComposing = true; });
        input.addEventListener('compositionend', () => {
            isComposing = false;
            // Trigger input processing once composition is finished
            input.dispatchEvent(new Event('input'));
        });

        input.addEventListener('input', function (e) {
            if (isComposing) return;
            // Contenteditable handles height automatically

            const selection = window.getSelection();
            if (!selection.rangeCount) return;

            const range = selection.getRangeAt(0);
            const node = range.startContainer;

            if (node.nodeType === Node.TEXT_NODE) {
                const textBeforeCursor = node.textContent.substring(0, range.startOffset);
                const mentionMatch = textBeforeCursor.match(/@(?:(\w+):)?([\w./-]*)$/);

                if (mentionMatch) {
                    isMentioning = true;
                    const modeStr = mentionMatch[1] ? mentionMatch[1].toLowerCase() : null;
                    mentionQuery = mentionMatch[2].toLowerCase();

                    if (modeStr === 'wells' && mentionQuery.includes('/')) {
                        mentionMode = 'well_curves';
                        const parts = mentionQuery.split('/');
                        mentionQuery = parts[1] || "";
                    } else if (modeStr) {
                        mentionMode = modeStr;
                    } else {
                        const partialMatch = MENTION_CATEGORIES.find(c => c.id.startsWith(mentionQuery));
                        if (mentionQuery.length > 0 && !partialMatch) {
                            mentionMode = 'file';
                        } else {
                            mentionMode = 'root';
                        }
                    }
                    showMentionMenu();
                    return;
                }
            }

            hideMentionMenu();
            updateSendButton();
        });

        input.addEventListener('keydown', function (e) {
            if (isMentioning) {
                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    if (filteredItems.length > 0) {
                        do {
                            selectedMentionIndex = (selectedMentionIndex + 1) % filteredItems.length;
                        } while (filteredItems[selectedMentionIndex].type === 'header');
                        renderMentionMenu();
                    }
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    if (filteredItems.length > 0) {
                        do {
                            selectedMentionIndex = (selectedMentionIndex - 1 + filteredItems.length) % filteredItems.length;
                        } while (filteredItems[selectedMentionIndex].type === 'header');
                        renderMentionMenu();
                    }
                } else if (e.key === 'Enter' || e.key === 'Tab') {
                    e.preventDefault();
                    const item = filteredItems[selectedMentionIndex];
                    if (item) {
                        if (item.type === 'category') {
                            drillDown(item.id);
                        } else {
                            selectMentionByIdx(selectedMentionIndex);
                        }
                    }
                } else if (e.key === 'Backspace') {
                    // Check if we should revert from @mode: back to @
                    const selection = window.getSelection();
                    if (!selection.rangeCount) return;
                    const range = selection.getRangeAt(0);
                    const node = range.startContainer;

                    if (node.nodeType === Node.TEXT_NODE && mentionQuery === "") {
                        const text = node.textContent;
                        const offset = range.startOffset;
                        const textBefore = text.substring(0, offset);

                        // Priority 1: From @wells:well-name/ back to @wells:
                        if (mentionMode === 'well_curves' && textBefore.endsWith('/')) {
                            e.preventDefault();
                            mentionMode = 'wells';
                            currentWell = null;
                            const newText = textBefore.substring(0, textBefore.length - 1) + text.substring(offset);
                            node.textContent = newText;
                            range.setStart(node, offset - 1);
                            range.setEnd(node, offset - 1);
                            showMentionMenu();
                            return;
                        }

                        // Priority 2: From @mode: back to @
                        if (mentionMode !== 'root' && /@\w+:$/.test(textBefore)) {
                            e.preventDefault();
                            mentionMode = 'root';
                            currentWell = null;
                            const newTextBefore = textBefore.replace(/@\w+:$/, '@');
                            const newText = newTextBefore + text.substring(offset);
                            node.textContent = newText;
                            range.setStart(node, newTextBefore.length);
                            range.setEnd(node, newTextBefore.length);
                            showMentionMenu();
                            return;
                        }

                        // Priority 3: If backspace deleted the last char of @ and it became empty
                        if (text === "" && mentionMode !== 'root') {
                            e.preventDefault();
                            mentionMode = 'root';
                            node.textContent = "@";
                            range.setStart(node, 1);
                            range.setEnd(node, 1);
                            showMentionMenu();
                            return;
                        }
                    }
                } else if (e.key === 'Escape') {
                    hideMentionMenu();
                }
                return;
            }

            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        async function showMentionMenu() {
            const menu = document.getElementById('mention-menu');

            if (mentionMode === 'root') {
                filteredItems = MENTION_CATEGORIES.map(c => ({
                    type: 'category',
                    id: c.id,
                    label: c.label,
                    icon: c.icon,
                    description: c.description
                })).filter(c => c.id.includes(mentionQuery) || c.label.toLowerCase().includes(mentionQuery));
            } else if (mentionMode === 'opened' || mentionMode === 'active') {
                // Fetch opened windows info from bridge
                if (bridge && bridge.getOpenedWindowsInfo) {
                    try {
                        const infoStr = await bridge.getOpenedWindowsInfo();
                        const info = JSON.parse(infoStr);
                        if (info.ok) {
                            filteredItems = (info.data || []).map(win => ({
                                type: 'opened_item',
                                window_type: win.type,
                                file: win.path || win.name,
                                name: win.name,
                                is_active: win.is_active,
                                curves: win.curves || [],
                                tracks: win.tracks || []
                            }));

                            if (filteredItems.length === 0) {
                                filteredItems = [{ type: 'header', label: 'No windows open' }];
                            }
                        } else {
                            filteredItems = [{ type: 'header', label: info.error || 'No windows open' }];
                        }
                    } catch (e) {
                        filteredItems = [{ type: 'header', label: 'Error fetching windows' }];
                    }
                }
            } else if (mentionMode === 'wells') {
                if (bridge && bridge.getWellsForMention) {
                    try {
                        const wellsStr = await bridge.getWellsForMention();
                        const wells = JSON.parse(wellsStr);
                        filteredItems = wells.map(w => ({
                            type: 'well',
                            id: w.id,
                            name: w.name,
                            db_path: w.db_path,
                            file: w.db_path
                        })).filter(w => w.name.toLowerCase().includes(mentionQuery));

                        if (filteredItems.length === 0) {
                            filteredItems = [{ type: 'header', label: 'No wells found' }];
                        }
                    } catch (e) {
                        filteredItems = [{ type: 'header', label: 'Error fetching wells' }];
                    }
                }
            } else if (mentionMode === 'well_curves') {
                if (bridge && bridge.getCurvesForWell && currentWell) {
                    try {
                        const curvesStr = await bridge.getCurvesForWell(currentWell.id, currentWell.db_path);
                        const curves = JSON.parse(curvesStr);
                        if (curves.error) throw new Error(curves.error);

                        filteredItems = curves.map(c => ({
                            type: 'well_curve',
                            id: c.id,
                            name: c.name,
                            unit: c.unit,
                            is_2d: c.is_2d,
                            well_id: c.well_id,
                            well_name: currentWell.name,
                            db_path: c.db_path,
                            file: c.db_path
                        })).filter(c => c.name.toLowerCase().includes(mentionQuery));

                        if (filteredItems.length === 0) {
                            filteredItems = [{ type: 'header', label: 'No curves found' }];
                        }
                    } catch (e) {
                        filteredItems = [{ type: 'header', label: 'Error fetching curves' }];
                    }
                }
            } else if (mentionMode === 'file' || mentionMode === 'folder') {
                if (allFiles.length === 0 && bridge) {
                    try {
                        allFiles = await bridge.getProjectFiles();
                    } catch (e) {
                        console.error("Failed to get project files:", e);
                        allFiles = [];
                    }
                }

                const matchedFiles = (allFiles || []).filter(f => f.toLowerCase().includes(mentionQuery));

                if (mentionMode === 'folder') {
                    // Extract directories
                    const dirs = [...new Set(matchedFiles.map(f => {
                        const parts = f.split(/[\\/]/);
                        return parts.slice(0, -1).join('/') || '.';
                    }))].filter(d => d !== '.');

                    filteredItems = dirs.map(d => ({ type: 'file', file: d, isDir: true }));
                } else {
                    // Files mode - Group them
                    const categories = {
                        "User Scripts (Scripts)": matchedFiles.filter(f => f.includes('scripts_user/')),
                        "Templates": matchedFiles.filter(f => f.includes('data/templates/')),
                        "Database Files (Database)": matchedFiles.filter(f => f.endsWith('.db') || f.includes('data/') && !f.includes('templates/')),
                        "Other Files (Others)": []
                    };

                    const categorizedPaths = new Set([
                        ...categories["User Scripts (Scripts)"],
                        ...categories["Templates"],
                        ...categories["Database Files (Database)"]
                    ]);
                    categories["Other Files (Others)"] = matchedFiles.filter(f => !categorizedPaths.has(f));

                    filteredItems = [];
                    for (const [catName, files] of Object.entries(categories)) {
                        if (files.length > 0) {
                            filteredItems.push({ type: 'header', label: catName });
                            files.forEach(f => filteredItems.push({ type: 'file', file: f }));
                        }
                    }
                }
            } else if (mentionMode === 'bubbles') {
                filteredItems = [{
                    type: 'bubbles_all',
                    name: 'Active Context Bubbles',
                    description: 'Insert all currently selected items as pills'
                }];
            } else {
                // Other modes (Not implemented yet or empty)
                filteredItems = [{ type: 'header', label: 'Feature coming soon...' }];
            }

            if (filteredItems.length === 0) {
                hideMentionMenu();
                return;
            }

            // Pick first non-header as active
            selectedMentionIndex = filteredItems.findIndex(item => item.type !== 'header');
            if (selectedMentionIndex === -1) selectedMentionIndex = 0;

            renderMentionMenu();
            menu.style.display = 'block';
        }

        function hideMentionMenu() {
            isMentioning = false;
            mentionMode = 'root';
            document.getElementById('mention-menu').style.display = 'none';
        }

        function drillDown(categoryId) {
            mentionMode = categoryId;
            const selection = window.getSelection();
            const range = selection.getRangeAt(0);
            const node = range.startContainer;

            if (node.nodeType === Node.TEXT_NODE) {
                const text = node.textContent;
                const offset = range.startOffset;
                const before = text.substring(0, offset);
                const after = text.substring(offset);

                const mentionMatch = before.match(/@(\w*)$/);
                if (mentionMatch) {
                    const newBefore = before.substring(0, mentionMatch.index) + `@${categoryId}:`;
                    node.textContent = newBefore + after;
                    range.setStart(node, newBefore.length);
                    range.setEnd(node, newBefore.length);
                }
            }

            input.dispatchEvent(new Event('input'));
        }

        function renderMentionMenu() {
            const menu = document.getElementById('mention-menu');
            menu.innerHTML = filteredItems.map((item, index) => {
                const isActive = index === selectedMentionIndex;

                if (item.type === 'header') {
                    return `<div class="mention-group-header">${item.label}</div>`;
                }

                if (item.type === 'category') {
                    return `
                        <div class="mention-item ${isActive ? 'active' : ''}" onmousedown="event.preventDefault(); drillDown('${item.id}')">
                            ${item.icon}
                            <div style="display: flex; flex-direction: column;">
                                <span style="font-weight: 500;">${item.label}</span>
                                <span style="font-size: 0.7rem; opacity: 0.6;">${item.description}</span>
                            </div>
                            <span class="file-path" style="opacity: 0.3;">@${item.id}:</span>
                        </div>
                    `;
                }

                const isPlot = item.window_type === 'plot' || item.type === 'well' || item.type === 'well_curve';
                const file = item.file || "";
                const basename = item.name || (file ? file.split(/[\\/]/).pop() : "");
                let dir = '';
                if (item.type === 'well') dir = 'Database Well';
                else if (item.type === 'well_curve') {
                    const folderPart = item.folder ? ` / ${item.folder}` : "";
                    dir = `${item.well_name}${folderPart} - ${item.is_2d ? '2D' : '1D'}${item.unit ? ' (' + item.unit + ')' : ''}`;
                }
                else if (item.type === 'bubbles_item') dir = 'Active Context';
                else dir = isPlot ? `Log Plot - ${(item.tracks || []).length} Tracks` : (file.split(/[\\/]/).slice(0, -1).join('/') || './');

                let icon = '';
                if (item.window_type === 'plot') {
                    icon = '<svg class="mention-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"></path><path d="M18.7 8l-5.1 5.2-2.8-2.7L7 14.3"></path></svg>';
                } else if (item.type === 'well') {
                    icon = '<svg class="mention-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 21h10"></path><path d="M12 21V10"></path><path d="M12 10l5 5"></path><path d="M12 10l-5 5"></path><path d="M12 3l5 5-5 5-5-5 5-5z"></path></svg>';
                } else if (item.type === 'well_curve') {
                    icon = '<svg class="mention-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"></path><path d="M18.7 8l-5.1 5.2-2.8-2.7L7 14.3"></path></svg>';
                } else {
                    icon = item.isDir ?
                        '<svg class="mention-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>' :
                        '<svg class="mention-item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg>';
                }

                return `
                    <div class="mention-item ${isActive ? 'active' : ''}" onmousedown="event.preventDefault(); selectMentionByIdx(${index})">
                        ${icon}
                        <div style="display: flex; flex-direction: column; overflow: hidden;">
                            <span style="font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${basename}</span>
                            <span class="file-path">${dir}</span>
                        </div>
                    </div>
                `;
            }).join('');

            const activeItem = menu.querySelector('.active');
            if (activeItem) {
                activeItem.scrollIntoView({ block: 'nearest' });
            }
        }

        async function selectMentionByIdx(idx) {
            const item = filteredItems[idx];
            if (!item) return;

            if (item.type === 'well') {
                currentWell = item;
                mentionMode = 'well_curves';
                mentionQuery = "";

                const selection = window.getSelection();
                if (!selection.rangeCount) return;
                const range = selection.getRangeAt(0);
                const node = range.startContainer;
                if (node.nodeType === Node.TEXT_NODE) {
                    const text = node.textContent;
                    const offset = range.startOffset;
                    const before = text.substring(0, offset);
                    const after = text.substring(offset);
                    const newBefore = before.replace(/@wells:.*$/, `@wells:${item.name}/`);
                    node.textContent = newBefore + after;
                    range.setStart(node, newBefore.length);
                    range.setEnd(node, newBefore.length);
                }
                showMentionMenu();
                return;
            }

            if (item.type === 'bubbles_all') {
                if (bridge && bridge.getActiveContextBubbles) {
                    const resStr = await bridge.getActiveContextBubbles();
                    const res = JSON.parse(resStr);
                    if (res.ok && res.data && res.data.length > 0) {
                        // Delete @bubbles:
                        const selection = window.getSelection();
                        if (selection.rangeCount) {
                            const range = selection.getRangeAt(0);
                            const node = range.startContainer;
                            if (node.nodeType === Node.TEXT_NODE) {
                                const text = node.textContent;
                                const offset = range.startOffset;
                                const before = text.substring(0, offset);
                                const after = text.substring(offset);
                                const newBefore = before.replace(/@bubbles:.*$/, '');
                                node.textContent = newBefore + after;
                                range.setStart(node, newBefore.length);
                                range.collapse(true);
                            }

                            // Calculate abbreviated name from active context
                            let combinedName = "";
                            if (res.data.length > 0) {
                                const first = res.data[0];
                                const name = first.display_name || first.name || "Unknown";
                                if (first.type === 'curve') combinedName = `Curve: ${name}`;
                                else if (first.type === 'well') combinedName = `Well: ${name}`;
                                else combinedName = name;

                                if (res.data.length > 1) {
                                    combinedName += " | ...";
                                }
                            }

                            const pill = document.createElement('span');
                            pill.className = 'mention-pill';
                            pill.contentEditable = "false";
                            pill.dataset.type = 'bubbles';
                            pill.dataset.name = combinedName;
                            // Store the entire data array for sendMessage to expand later
                            pill.dataset.context = JSON.stringify(res.data);

                            const iconMarkup = '<svg class="tag-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><path d="M8 14s1.5 2 4 2 4-2 4-2"></path><line x1="9" y1="9" x2="9.01" y2="9"></line><line x1="15" y1="9" x2="15.01" y2="9"></line></svg>';
                            pill.innerHTML = `${iconMarkup}<span>${combinedName}</span>`;

                            const fragment = document.createDocumentFragment();
                            fragment.appendChild(pill);
                            const spaceNode = document.createTextNode(' ');
                            fragment.appendChild(spaceNode);

                            range.insertNode(fragment);
                            selection.removeAllRanges();
                            const caretRange = document.createRange();
                            caretRange.setStart(spaceNode, 1);
                            caretRange.collapse(true);
                            selection.addRange(caretRange);
                        }
                    }
                }
                hideMentionMenu();
                updateSendButton();
                return;
            }

            // 1. Prepare data (async if needed)
            let content = "";
            let type = 'file';
            const filePath = item.file;
            const isCurve = item.type === 'well_curve';
            const isPlot = item.window_type === 'plot';
            let name = item.name || (filePath ? filePath.split(/[/\\]/).pop() : "Unknown");
            let dataProps = null;

            if (isCurve) {
                type = 'curve';
                const wellName = item.well_name || (item.db_path ? item.db_path.split(/[/\\]/).pop().replace('.db', '') : 'Unknown Well');
                const folderName = item.folder || '';
                const displayPath = folderName ? `${wellName}/${folderName}/${item.name}` : `${wellName}/${item.name}`;

                dataProps = {
                    type: 'curve',
                    name: item.name,
                    folder: folderName,
                    display_name: displayPath,
                    well_id: item.well_id,
                    well_name: wellName,
                    id: item.id,
                    db_path: item.db_path,
                    content: `Well: ${wellName}\nFolder: ${folderName || 'ROOT'}\nCurve: ${item.name} (${item.is_2d ? '2D' : '1D'})\nUnit: ${item.unit || '-'}\nDatabase Path: ${item.db_path || ''}`,
                    breadcrumbs: [
                        { type: 'database', name: item.db_path || '' },
                        { type: 'well', name: wellName },
                        { type: 'folder', name: folderName || 'ROOT' },
                        { type: 'curve', name: item.name }
                    ],
                    attributes: [
                        { label: 'Well', value: wellName },
                        { label: 'Folder', value: folderName || 'ROOT' },
                        { label: 'Curve', value: item.is_2d ? '2D' : '1D' },
                        { label: 'Unit', value: item.unit || '-' }
                    ]
                };
                name = dataProps.display_name;
            } else if (isPlot) {
                type = 'plot';
                const groups = [];
                (item.tracks || []).forEach(track => {
                    const curvesStr = (track.curves || []).map(c => c.name).join(', ');
                    groups.push(`Track "${track.name}": ${curvesStr || '(no curves)'}`);
                });

                const wellName = item.well_name || 'Unknown Well';
                const wellInfo = item.well_name ? ` (Well: ${item.well_name})` : '';
                content = groups.length === 0
                    ? `Plot: ${item.name}${wellInfo}\n(No track details available)`
                    : `Plot: ${item.name}${wellInfo}\n${groups.join('\n')}`;

                dataProps = {
                    type: 'plot',
                    name: item.name,
                    well_name: wellName,
                    tracks: item.tracks || [],
                    content: content,
                    breadcrumbs: [
                        { type: 'well', name: wellName },
                        { type: 'plot', name: item.name }
                    ],
                    attributes: [
                        { label: 'Well', value: wellName },
                        { label: 'Track Count', value: (item.tracks || []).length }
                    ]
                };
            } else {
                if (bridge && filePath) {
                    content = await bridge.readFileContent(filePath);
                }
                dataProps = {
                    type: 'file',
                    name: name,
                    path: filePath,
                    content: content,
                    breadcrumbs: [
                        { type: 'file', name: filePath }
                    ],
                    attributes: [
                        { label: 'Path', value: filePath }
                    ]
                };
            }

            // 2. DOM Modification Block (Synchronous)
            input.focus();
            const sel = window.getSelection();
            if (!sel.rangeCount) return;
            const range = sel.getRangeAt(0);
            const node = range.startContainer;

            // 2a. Remove @query part
            if (node.nodeType === Node.TEXT_NODE) {
                const text = node.textContent;
                const offset = range.startOffset;
                const before = text.substring(0, offset);
                const after = text.substring(offset);
                const mentionMatch = before.match(/@(?:\w+:)?([\w./-]*)$/);
                if (mentionMatch) {
                    const head = before.substring(0, mentionMatch.index);
                    node.textContent = head + after;
                    range.setStart(node, head.length);
                    range.collapse(true);
                }
            }

            if (selectedContexts.some(c => c.path === filePath && c.type !== 'curve')) {
                hideMentionMenu();
                return;
            }

            if (dataProps) selectedContexts.push(dataProps);
            else selectedContexts.push({ type, name, path: filePath, content });

            // 2b. Insert Pill & Space
            const pill = document.createElement('span');
            pill.className = 'mention-pill';
            pill.contentEditable = "false";
            pill.dataset.type = type;
            pill.dataset.path = filePath || "";
            pill.dataset.name = name;
            pill.dataset.content = content || ""; // [NEW] Persist for history
            if (isCurve) {
                pill.dataset.wellId = item.well_id;
                pill.dataset.wellName = item.well_name;
                pill.dataset.curveId = item.id;
                if (item.folder) pill.dataset.folder = item.folder;
            }
            if (dataProps) {
                if (dataProps.breadcrumbs) pill.dataset.breadcrumbs = JSON.stringify(dataProps.breadcrumbs);
                if (dataProps.attributes) pill.dataset.attributes = JSON.stringify(dataProps.attributes);
            }

            const iconMarkup = (isPlot || isCurve) ?
                '<svg class="tag-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"></path><path d="M18.7 8l-5.1 5.2-2.8-2.7L7 14.3"></path></svg>' :
                '<svg class="tag-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg>';
            pill.innerHTML = `${iconMarkup}<span>${name}</span>`;

            const fragment = document.createDocumentFragment();
            fragment.appendChild(pill);
            const spaceNode = document.createTextNode(' ');
            fragment.appendChild(spaceNode);

            range.insertNode(fragment);

            // 2c. Force caret inside the space text node
            sel.removeAllRanges();
            const caretRange = document.createRange();
            caretRange.setStart(spaceNode, 1);
            caretRange.collapse(true);
            sel.addRange(caretRange);

            hideMentionMenu();
            updateSendButton();
            input.focus();
        }

        async function selectMention(filePath) {
            // Legacy for old calls
            const idx = filteredItems.findIndex(i => i.file === filePath);
            if (idx >= 0) selectMentionByIdx(idx);
        }

        function hidePopover() {
            document.getElementById('mention-popover').style.display = 'none';
        }

        function escapePopoverHtml(value) {
            return String(value == null ? '' : value)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }

        function showPopover(pill) {
            const popover = document.getElementById('mention-popover');
            const body = document.getElementById('popover-body');
            const titleIcon = document.querySelector('#popover-title .tag-icon');

            const type = pill.dataset.type;
            const name = pill.dataset.name;
            const path = pill.dataset.path;

            const getTypeLabel = (contextType) => {
                if (contextType === 'curve') return 'Curve';
                if (contextType === 'well') return 'Well';
                if (contextType === 'plot') return 'Plot';
                if (contextType === 'track') return 'Track';
                if (contextType === 'file') return 'File';
                if (contextType === 'folder') return 'Folder';
                if (contextType === 'selection') return 'Selection';
                if (contextType === 'bubbles') return 'Bubbles';
                if (contextType === 'effective_context') return 'Effective Context';
                return contextType || 'Unknown';
            };

            let html = '';

            if (type === 'effective_context') {
                html = `
                    <div class="popover-meta-row">
                        <span class="popover-meta-label">Category</span>
                        <span class="popover-meta-value">Effective Prompt Context</span>
                    </div>
                    <div class="popover-meta-label" style="margin-top:12px">Sections</div>
                    <div class="popover-content-preview" style="max-height: 400px; overflow-y: auto; white-space: normal;">
                `;
                try {
                    const summary = JSON.parse(pill.dataset.context || '{}');
                    const groups = Array.isArray(summary.groups) ? summary.groups : [];
                    groups.forEach(group => {
                        const lines = Array.isArray(group.lines) ? group.lines : [];
                        html += `
                            <div style="margin-bottom:10px; padding-bottom:10px; border-bottom:1px solid var(--border-color);">
                                <div style="font-size:12px;"><strong>${escapePopoverHtml(group.title || group.id || 'Context')}</strong></div>
                                <div style="color:var(--text-secondary); font-size:11px; margin-top:4px; line-height:1.5; white-space:pre-wrap;">
                                    ${escapePopoverHtml(lines.join('\n') || '-')}
                                </div>
                            </div>
                        `;
                    });
                } catch (e) {
                    html += `<div style="color:var(--error-color)">Failed to parse effective context payload.</div>`;
                }
                html += `</div>`;
            } else if (type === 'bubbles') {
                html = `
                    <div class="popover-meta-row">
                        <span class="popover-meta-label">Category</span>
                        <span class="popover-meta-value">Active Context (Bubbles)</span>
                    </div>
                    <div class="popover-meta-label" style="margin-top:12px">Contents</div>
                    <div class="popover-content-preview" style="max-height: 400px; overflow-y: auto; white-space: normal;">
                `;
                try {
                    const ctxs = JSON.parse(pill.dataset.context || '[]');
                    ctxs.forEach(c => {
                        const cType = getTypeLabel(c.type);
                        const displayName = escapePopoverHtml((c.type === 'curve' && c.track_name) ? `${c.track_name}/${c.name}` : (c.display_name || c.name));

                        let details = '';
                        if (c.breadcrumbs && c.attributes) {
                            const pathStr = c.breadcrumbs.map(b => escapePopoverHtml(b.name)).join(' <span style="opacity:0.5; margin:0 2px;">/</span> ');
                            const attrsStr = c.attributes.map(a => `<div style="margin-top:2px;"><strong>${escapePopoverHtml(a.label)}:</strong> ${escapePopoverHtml(a.value)}</div>`).join('');
                            details = `
                                <div style="color:var(--text-secondary); font-size:11px; margin-top:4px; line-height:1.4;">
                                    <div style="opacity: 0.8; margin-bottom: 4px; padding-bottom: 4px; border-bottom: 1px dashed var(--border-color); word-break: break-all;">
                                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:10px; height:10px; opacity:0.6; margin-right:2px; vertical-align: baseline;"><polyline points="9 18 15 12 9 6"></polyline></svg>
                                        ${pathStr}
                                    </div>
                                    ${attrsStr}
                                </div>
                            `;
                        } else if (c.type === 'curve') {
                            const dbPath = c.db_path || c.path || '';
                            const wellName = escapePopoverHtml(c.well_name || (dbPath ? dbPath.split(/[/\\]/).pop().replace('.db', '') : 'Unknown Well'));
                            details = `
                                <div style="color:var(--text-secondary); font-size:11px; margin-top:2px; line-height:1.4;">
                                    <strong>Well</strong> ${wellName}<br>
                                    <strong>Unit</strong> ${escapePopoverHtml(c.unit || '-')}<br>
                                    <strong>Curve ID</strong> ${escapePopoverHtml(c.id || '-')}<br>
                                    <strong>Well ID</strong> ${escapePopoverHtml(c.well_id || '-')}<br>
                                    <strong>Database Path</strong> <span style="word-break: break-all;">${escapePopoverHtml(dbPath)}</span>
                                </div>
                            `;
                        } else if (c.type === 'plot') {
                            details = `
                                <div style="color:var(--text-secondary); font-size:11px; margin-top:2px; line-height:1.4;">
                                    <strong>Well</strong> ${escapePopoverHtml(c.well_name || 'Unknown Well')}<br>
                                    <strong>Track Count</strong> ${escapePopoverHtml((c.tracks || []).length)}
                                </div>
                            `;
                        } else if (c.type === 'track') {
                            details = `
                                <div style="color:var(--text-secondary); font-size:11px; margin-top:2px; line-height:1.4;">
                                    <strong>Well</strong> ${escapePopoverHtml(c.well_name || 'Unknown Well')}<br>
                                    <strong>Included Curves</strong> ${escapePopoverHtml((c.curves || []).join(', ') || '-')}
                                </div>
                            `;
                        } else if (c.path) {
                            details = `<div style="color:var(--text-secondary); font-size:11px; margin-top:2px; word-break: break-all;"><strong>Path</strong> ${escapePopoverHtml(c.path)}</div>`;
                        }

                        html += `
                            <div style="margin-bottom:10px; padding-bottom:10px; border-bottom:1px solid var(--border-color);">
                                <div style="font-size:12px;"><strong>${displayName}</strong> (${cType})</div>
                                ${details}
                            </div>
                        `;
                    });
                } catch (e) {
                    html += `<div style="color:var(--error-color)">Failed to parse active context payload.</div>`;
                }
                html += `</div>`;
            } else {
                const ctx = selectedContexts.find(c => c.path === path && c.name === name);
                const breadcrumbsStr = pill.dataset.breadcrumbs || (ctx ? JSON.stringify(ctx.breadcrumbs || []) : '[]');
                const attributesStr = pill.dataset.attributes || (ctx ? JSON.stringify(ctx.attributes || []) : '[]');

                let breadcrumbs = [];
                let attributes = [];
                try {
                    breadcrumbs = JSON.parse(breadcrumbsStr);
                    attributes = JSON.parse(attributesStr);
                } catch (e) {}

                if (breadcrumbs.length > 0 || attributes.length > 0) {
                    if (breadcrumbs.length > 0) {
                        const pathStr = breadcrumbs.map(b => escapePopoverHtml(b.name)).join(' <span style="opacity:0.5; margin:0 2px;">/</span> ');
                        html += `
                            <div class="popover-meta-row" style="margin-bottom: 8px;">
                                <span class="popover-meta-value" style="word-break: break-all; font-size: 11px;">
                                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="width:12px; height:12px; opacity:0.6; margin-right:4px; vertical-align: middle;"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><polyline points="9 22 9 12 15 12 15 22"></polyline></svg>
                                    ${pathStr}
                                </span>
                            </div>
                        `;
                    }

                    html += `
                        <div class="popover-meta-row" style="margin-top: 4px; padding-top: 4px; border-top: 1px solid var(--border-color);">
                            <span class="popover-meta-label">Name:</span>
                            <span class="popover-meta-value">${escapePopoverHtml(name)}</span>
                        </div>
                        <div class="popover-meta-row">
                            <span class="popover-meta-label">Type:</span>
                            <span class="popover-meta-value">${escapePopoverHtml(getTypeLabel(type))}</span>
                        </div>
                    `;

                    attributes.forEach(attr => {
                        html += `
                            <div class="popover-meta-row">
                                <span class="popover-meta-label">${escapePopoverHtml(attr.label)}:</span>
                                <span class="popover-meta-value">${escapePopoverHtml(attr.value)}</span>
                            </div>
                        `;
                    });

                    const finalContent = (ctx && ctx.content) ? ctx.content : (pill.dataset.content || '');
                    if (finalContent) {
                        const previewText = escapePopoverHtml(finalContent.substring(0, 500)) + (finalContent.length > 500 ? '...' : '');
                        html += `
                            <div class="popover-meta-label" style="margin-top:12px">Preview</div>
                            <div class="popover-content-preview">${previewText}</div>
                        `;
                    }
                } else {
                    html = `
                        <div class="popover-meta-row">
                            <span class="popover-meta-label">Name:</span>
                            <span class="popover-meta-value">${escapePopoverHtml(name)}</span>
                        </div>
                        <div class="popover-meta-row">
                            <span class="popover-meta-label">Type:</span>
                            <span class="popover-meta-value">${escapePopoverHtml(getTypeLabel(type))}</span>
                        </div>
                    `;

                    if (path) {
                        html += `
                            <div class="popover-meta-row">
                                <span class="popover-meta-label">Path</span>
                                <span class="popover-meta-value">${escapePopoverHtml(path)}</span>
                            </div>
                        `;
                    }

                    if (type === 'curve' && pill.dataset.wellId) {
                        html += `
                            <div class="popover-meta-row">
                                <span class="popover-meta-label">Well ID</span>
                                <span class="popover-meta-value">${escapePopoverHtml(pill.dataset.wellId)}</span>
                            </div>
                        `;
                    }

                    const finalContent = (ctx && ctx.content) ? ctx.content : (pill.dataset.content || '');
                    if (type === 'track') {
                        const curvesArr = pill.dataset.curves ? pill.dataset.curves.split(',') : [];
                        const curvesText = escapePopoverHtml(curvesArr.join(', ') || '-');
                        html += `
                            <div class="popover-meta-label" style="margin-top:12px">Included Curves</div>
                            <div class="popover-content-preview">${curvesText}</div>
                        `;
                    } else if (finalContent) {
                        const previewText = escapePopoverHtml(finalContent.substring(0, 500)) + (finalContent.length > 500 ? '...' : '');
                        html += `
                            <div class="popover-meta-label" style="margin-top:12px">Preview</div>
                            <div class="popover-content-preview">${previewText}</div>
                        `;
                    }
                }
            }

            if (titleIcon) {
                titleIcon.setAttribute('data-type', type || 'file');
            }
            body.innerHTML = html;

            const rect = pill.getBoundingClientRect();
            popover.style.display = 'flex';

            let top = rect.bottom + 8;
            let left = rect.left;

            if (left + 320 > window.innerWidth) left = window.innerWidth - 330;
            if (top + 300 > window.innerHeight) top = rect.top - popover.offsetHeight - 8;

            popover.style.top = top + 'px';
            popover.style.left = left + 'px';
        }

        // Global click listener for pills and popover
        document.addEventListener('click', function (e) {
            const pill = e.target.closest('.mention-pill') || e.target.closest('.context-tag');
            const closeBtn = e.target.closest('.popover-close') || e.target.closest('.tag-close');

            if (closeBtn) {
                if (e.target.closest('.popover-close')) {
                    hidePopover();
                }
                return; 
            }

            if (pill) {
                e.preventDefault();
                e.stopPropagation();
                showPopover(pill);
            } else if (!e.target.closest('.mention-popover')) {
                hidePopover();
            }
        });

        function renderContextTags() {
            const container = document.getElementById('context-tags-container');
            container.innerHTML = '';

            // Group contexts: files are separate, curves/wells/plots are consolidated
            const consolidatedTypes = ['curve', 'well', 'plot'];
            const consolidatedItems = selectedContexts.filter(ctx => consolidatedTypes.includes(ctx.type));
            const individualItems = selectedContexts.filter(ctx => !consolidatedTypes.includes(ctx.type));
            
            // [MOD] Skip "selection" types as they are now handled as pills in the input box
            const visibleIndividualItems = individualItems.filter(ctx => ctx.type !== 'selection');

            const hasTags = consolidatedItems.length > 0 || visibleIndividualItems.length > 0;
            if (!hasTags) {
                container.classList.remove('has-tags');
                return;
            }

            container.classList.add('has-tags');

            // Render consolidated tag if exists
            if (consolidatedItems.length > 0) {
                const first = consolidatedItems[0];
                const tag = document.createElement('div');
                tag.className = 'context-tag tag-selection';
                
                let combinedName = "";
                const name = first.display_name || first.name || "Unknown";
                if (first.type === 'curve') combinedName = `Curve: ${name}`;
                else if (first.type === 'well') combinedName = `Well: ${name}`;
                else if (first.type === 'plot') combinedName = `Plot: ${name}`;
                else combinedName = name;

                if (consolidatedItems.length > 1) {
                    combinedName += " | ...";
                }

                // Add metadata for popover support (as a 'bubbles' type)
                tag.dataset.type = 'bubbles';
                tag.dataset.name = combinedName;
                tag.dataset.context = JSON.stringify(consolidatedItems);

                const icon = '<svg class="tag-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><path d="M8 14s1.5 2 4 2 4-2 4-2"></path><line x1="9" y1="9" x2="9.01" y2="9"></line><line x1="15" y1="9" x2="15.01" y2="9"></line></svg>';
                
                tag.innerHTML = `
                    ${icon}
                    <span>${combinedName}</span>
                    <span class="tag-meta">#Active</span>
                    <span class="tag-close" onclick="removeConsolidatedContexts()">&times;</span>
                `;
                container.appendChild(tag);
            }

            // Render individual tags (files, etc.)
            visibleIndividualItems.forEach((ctx) => {
                // Find original index in selectedContexts for correct removal
                const originalIndex = selectedContexts.indexOf(ctx);
                const tag = document.createElement('div');
                tag.className = `context-tag ${ctx.type === 'file' ? 'tag-file' : 'tag-selection'}`;
                
                // Add metadata for popover support
                tag.dataset.type = ctx.type || 'file';
                tag.dataset.name = ctx.name || '';
                tag.dataset.path = ctx.path || '';
                
                let icon = '';
                let label = ctx.name;
                let meta = '';

                if (ctx.type === 'file') {
                    icon = '<svg class="tag-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"></path><polyline points="13 2 13 9 20 9"></polyline></svg>';
                    meta = '<span class="tag-meta">#File</span>';
                } else {
                    icon = '<svg class="tag-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"></polyline><polyline points="8 6 2 12 8 18"></polyline></svg>';
                    const lineText = ctx.lines === "Code" ? "" : ` #${ctx.lines}`;
                    meta = `<span class="tag-meta">${lineText}</span>`;
                }

                tag.innerHTML = `
                    ${icon}
                    <span>${label}</span>
                    ${meta}
                    <span class="tag-close" onclick="removeContext(${originalIndex})">&times;</span>
                `;
                container.appendChild(tag);
            });

            // Sync contexts to Python backend via bridge
            syncContexts();
        }

        function syncContexts() {
            if (typeof bridge !== 'undefined' && bridge.onUpdateChatContexts) {
                bridge.onUpdateChatContexts(JSON.stringify(selectedContexts));
            }
        }

        function removeContext(index) {
            selectedContexts.splice(index, 1);
            renderContextTags();
            updateSendButton();
        }

        // Scroll to the bottom of the chat window
        function scrollToBottom() {
            chatContainer.scrollTop = chatContainer.scrollHeight;
        }


        // Core message sending flow
        function sendMessage() {
            if (isSendingState) {
                if (bridge) bridge.sendMessage('');
                return;
            }

            // Extract content and inline mentions
            let actualMsg = "";
            let displayMsg = ""; // For rendering in history

            // Collect all contexts (both old pills and new inline ones)
            const inlineContexts = [];
            const addInlineContext = (ctx) => {
                if (!ctx) return;
                const key = [
                    ctx.type || '',
                    ctx.path || ctx.db_path || '',
                    ctx.name || ctx.display_name || '',
                    ctx.id || ctx.curve_id || ''
                ].join('|');
                if (!inlineContexts.some(ic => [
                    ic.type || '',
                    ic.path || ic.db_path || '',
                    ic.name || ic.display_name || '',
                    ic.id || ic.curve_id || ''
                ].join('|') === key)) {
                    inlineContexts.push(ctx);
                }
            };
            const appendMention = (node) => {
                const type = node.dataset.type || 'file';
                const path = node.dataset.path || "";
                const name = node.dataset.name || node.textContent.trim() || "";
                const wellId = node.dataset.wellId || "";
                const curveId = node.dataset.curveId || "";

                if (type === 'bubbles' && node.dataset.context) {
                    try {
                        const bubbleContexts = JSON.parse(node.dataset.context);
                        bubbleContexts.forEach(ctx => addInlineContext(ctx));
                    } catch (e) {
                        console.error("Error parsing bubble context:", e);
                    }
                    displayMsg += node.outerHTML;
                    return;
                }

                const markerPath = path || (wellId && curveId ? `${wellId}/${curveId}` : "");
                const ctx = selectedContexts.find(c => c.type === type && c.path === path);
                addInlineContext(ctx || { type, path: markerPath, name });
                displayMsg += node.outerHTML;
            };
            const walk = (node) => {
                if (node.nodeType === Node.TEXT_NODE) {
                    actualMsg += node.textContent;
                    displayMsg += node.textContent;
                } else if (node.nodeType === Node.ELEMENT_NODE) {
                    if (node.classList.contains('mention-pill')) {
                        appendMention(node);
                    } else if (node.nodeName === 'DIV' || node.nodeName === 'P') {
                        actualMsg += "\n";
                        displayMsg += "<br>";
                        for (let child of node.childNodes) walk(child);
                    } else if (node.nodeName === 'BR') {
                        actualMsg += "\n";
                        displayMsg += "<br>";
                    } else {
                        for (let child of node.childNodes) walk(child);
                    }
                }
            };

            for (let child of input.childNodes) walk(child);

            if (actualMsg.trim().length === 0 && selectedContexts.length === 0) return;

            const contextsToInclude = [...new Set(inlineContexts)];
            const fullMsg = actualMsg;

            const planActions = new Set([
                "执行计划",
                "修改计划",
                "取消计划",
                "Run Plan",
                "Edit Plan",
                "Cancel Plan"
            ]);
            const shouldRenderOptimistically = !planActions.has(fullMsg.trim());
            if (shouldRenderOptimistically && typeof appendMessage === 'function') {
                const now = new Date();
                const timestamp = now.toTimeString().slice(0, 8);
                appendMessage('user', displayMsg, timestamp, null, null, null, null, null, true);
                setSendingState(true);
                setInputEnabled(false);
            }

            // Send both versions to Python
            if (bridge) {
                bridge.sendMessage(JSON.stringify({
                    actual: fullMsg,
                    display: displayMsg,
                    rendered: shouldRenderOptimistically,
                    contexts: contextsToInclude
                }));
            }

            // Clear context after sending
            clearSelectionContext();

            input.innerHTML = '';
            updateSendButton();
        }

        let currentContextText = "";

        function setSelectionContext(filename, lines, text) {
            if (!text) return;

            const uniquePath = `${filename}#${lines}`;
            
            // 1. Prepare data
            const dataProps = {
                type: 'selection',
                name: filename,
                lines: lines,
                content: text,
                path: uniquePath
            };

            // [MOD] Instead of just checking selectedContexts, check if it's currently in the input DOM
            const existingPill = input.querySelector(`.mention-pill[data-path="${uniquePath.replace(/[#]/g, '\\#')}"]`);
            if (existingPill) {
                // Already in input, just focus it or do nothing
                input.focus();
                return;
            }

            // Sync with selectedContexts source of truth
            if (!selectedContexts.some(c => c.type === 'selection' && c.path === uniquePath)) {
                selectedContexts.push(dataProps);
            }

            // 2. Insert Pill into Input Box
            // [MOD] Aggressively clear to fix placeholder ghosting
            if (input.textContent.trim() === "") {
                input.innerHTML = "";
            }
            input.focus();

            const sel = window.getSelection();
            
            // If focused outside input, move to end of input
            if (!input.contains(sel.anchorNode)) {
                const range = document.createRange();
                if (input.childNodes.length > 0) {
                    range.selectNodeContents(input);
                    range.collapse(false);
                } else {
                    range.setStart(input, 0);
                    range.collapse(true);
                }
                sel.removeAllRanges();
                sel.addRange(range);
            }

            const range = sel.getRangeAt(0);
            
            const pill = document.createElement('span');
            pill.className = 'mention-pill';
            pill.contentEditable = "false";
            pill.dataset.type = 'selection';
            pill.dataset.name = filename;
            pill.dataset.path = uniquePath; 
            pill.dataset.lines = lines;
            pill.dataset.content = text;

            const iconMarkup = '<svg class="tag-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"></polyline><polyline points="8 6 2 12 8 18"></polyline></svg>';
            const lineLabel = lines === "Code" ? "" : ` #${lines}`;
            pill.innerHTML = `${iconMarkup}<span>${filename}${lineLabel}</span>`;

            const fragment = document.createDocumentFragment();
            fragment.appendChild(pill);
            const spaceNode = document.createTextNode(' ');
            fragment.appendChild(spaceNode);

            range.insertNode(fragment);

            // Move caret after the pill
            sel.removeAllRanges();
            const caretRange = document.createRange();
            caretRange.setStart(spaceNode, 1);
            caretRange.collapse(true);
            sel.addRange(caretRange);

            renderContextTags();
            updateSendButton();
            // [MOD] Force layout update and placeholder sync
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.focus();
        }

        function clearSelectionContext() {
            selectedContexts = [];
            renderContextTags();
            updateSendButton();
        }

        // Parse tool call markers from message content

