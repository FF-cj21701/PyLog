const chatContainer = document.getElementById('chat-container');
        const input = document.getElementById('message-input');
        const sendBtn = document.getElementById('send-btn');
        let bridge = null;
        window.pyBridge = null;

        // Initialize the web channel bridge
        new QWebChannel(qt.webChannelTransport, function (channel) {
            bridge = channel.objects.pyBridge;
            window.pyBridge = bridge;
            bridge.log("Web interface ready");
            input.disabled = false;
            input.innerHTML = ''; // Ensure input is empty on start
            updateSendButton();
        });

        // Configure marked.js
        marked.setOptions({
            highlight: function (code, lang) {
                if (typeof hljs === 'undefined') return code;
                const language = hljs.getLanguage(lang) ? lang : 'plaintext';
                return hljs.highlight(code, { language }).value;
            },
            langPrefix: 'hljs language-',
            breaks: true,
            gfm: true
        });

        // Auto-resize the input area
        input.addEventListener('input', function () {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 200) + 'px';
            updateSendButton();
        });

        const modeBtn = document.getElementById('mode-btn');
        const settingsBtn = document.getElementById('settings-btn');
        const clearChatBtn = document.getElementById('clear-chat-btn');
        const planProgressHeader = document.getElementById('planProgressHeader');
        const planProgressCollapseBtn = document.getElementById('planProgressCollapseBtn');

        if (modeBtn) {
            modeBtn.addEventListener('click', function () {
                toggleMode();
            });
        }

        if (settingsBtn) {
            settingsBtn.addEventListener('click', function () {
                if (bridge && bridge.openSettings) bridge.openSettings();
            });
        }

        if (clearChatBtn) {
            clearChatBtn.addEventListener('click', function () {
                clearChat();
            });
        }

        if (sendBtn) {
            sendBtn.addEventListener('click', function () {
                sendMessage();
            });
        }

        if (planProgressHeader) {
            planProgressHeader.addEventListener('click', function () {
                togglePlanProgressCollapse();
            });
        }

        if (planProgressCollapseBtn) {
            planProgressCollapseBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                togglePlanProgressCollapse();
            });
        }

        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });

        // [NEW] Force pasted content to plain text to avoid rich-text artifacts
        input.addEventListener('paste', function (e) {
            e.preventDefault();
            const text = (e.originalEvent || e).clipboardData.getData('text/plain');
            // Use insertText so the contenteditable field keeps a clean text structure
            document.execCommand('insertText', false, text);
        });

        function toggleMode() { if (bridge) bridge.toggleMode(); }

        // Python -> JS bridge hooks
        function setMode(mode) {
            const btn = document.getElementById('mode-btn');
            if (mode === 'reason') {
                btn.classList.add('active');
                btn.dataset.tooltip = "Reasoning mode on";
                btn.setAttribute('aria-label', "Reasoning mode on");
            } else {
                btn.classList.remove('active');
                btn.dataset.tooltip = "Turn on reasoning mode";
                btn.setAttribute('aria-label', "Turn on reasoning mode");
            }
        }

        function setModelName(name) {
            const modelEl = document.getElementById('model-display');
            modelEl.innerText = name;

            // Fix: Use getComputedStyle to reliably check visibility if inline style is not yet set
            const contextEl = document.getElementById('context-info');
            const contextVisible = window.getComputedStyle(contextEl).display !== 'none';

            if (contextVisible) {
                modelEl.style.display = 'none';
            } else {
                modelEl.style.display = 'block';
            }
        }

        function setContextInfo(contextData) {
            const contextEl = document.getElementById('context-info');
            const modelEl = document.getElementById('model-display');

            if (contextData) {
                try {
                    const items = JSON.parse(contextData);
                    if (items.length > 0) {
                        const first = items[0];
                        let combinedName = "";
                        const name = first.display_name || first.name || "Unknown";
                        if (first.type === 'curve') {
                            const trackN = first.track_name || "";
                            const folderN = first.folder || "";
                            if (trackN) combinedName = `Curve: ${trackN}/${name}`;
                            else if (folderN) combinedName = `Curve: ${folderN}/${name}`;
                            else combinedName = `Curve: ${name}`;
                        }
                        else if (first.type === 'well') combinedName = `Well: ${name}`;
                        else if (first.type === 'plot') combinedName = `Plot: ${name}`;
                        else if (first.type === 'track') combinedName = `Track: ${name}`;
                        else combinedName = name;

                        if (items.length > 1) {
                            combinedName += " | ...";
                        }

                        // Store for popover
                        contextEl.dataset.type = 'bubbles';
                        contextEl.dataset.name = combinedName;
                        contextEl.dataset.context = contextData;

                        const iconMarkup = '<svg class="tag-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"></circle><path d="M8 14s1.5 2 4 2 4-2 4-2"></path><line x1="9" y1="9" x2="9.01" y2="9"></line><line x1="15" y1="9" x2="15.01" y2="9"></line></svg>';

                        contextEl.innerHTML = `${iconMarkup}<span>${combinedName}</span>`;
                        contextEl.style.display = 'flex'; // Use flex for icon alignment

                        // Hide model name when context is active
                        modelEl.style.display = 'none';
                    } else {
                        contextEl.style.display = 'none';
                        modelEl.style.display = 'block';
                    }
                } catch (e) {
                    // Fallback for plain text if any
                    contextEl.textContent = contextData;
                    contextEl.style.display = 'block';
                    modelEl.style.display = 'none';
                }
            } else {
                contextEl.style.display = 'none';
                modelEl.style.display = 'block';
            }
        }

        function setInputEnabled(enabled) {
            input.disabled = !enabled;
            if (enabled) {
                input.focus();
                if (!isSendingState) {
                    updateSendButton();
                }
            }
        }

        let isSendingState = false;

        function setSendingState(isSending) {
            const btn = document.getElementById('send-btn');
            isSendingState = isSending;
            if (isSending) {
                btn.className = 'stop-btn';
                btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12"/></svg>';
                btn.disabled = false;
                btn.title = "Stop generating";
            } else {
                btn.className = 'send-btn';
                btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>';
                const text = input.innerText.trim();
                const hasPills = input.querySelector('.mention-pill') !== null;
                btn.disabled = (text.length === 0 && !hasPills && selectedContexts.length === 0);
                btn.title = "Send message";
            }
        }

        // Theme updates pushed from Python
        window.setTheme = function (theme) {
            theme = (theme || 'light').toLowerCase();

            // Remove all existing theme classes
            document.documentElement.classList.remove('dark-mode', 'sakura-mode', 'manga-mode');

            // Add current theme class
            if (theme === 'dark' || theme === 'sakura') {
                document.documentElement.classList.add('dark-mode');
            }

            if (theme === 'sakura') {
                document.documentElement.classList.add('sakura-mode');
            } else if (theme === 'manga') {
                document.documentElement.classList.add('manga-mode');
            }
        };
