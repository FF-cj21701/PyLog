(function () {
    let bridge = null;
    let state = {
        profiles: [],
        current_profile: "",
        behavior: {},
        whitelist: [],
        mcp_servers: {},
        disabled_skills: [],
        skills: [],
        tools: { total: 0, categories: [] },
        theme: "dark"
    };

    const panelTitles = {
        connection: ["Connection", "Configure AI provider profiles."],
        behavior: ["Behavior", "Tune chat loop and history behavior."],
        extensions: ["Extensions", "Manage local file access and optional MCP servers."],
        tools: ["Tools", "Browse built-in local AI tools."],
        skills: ["Expert Skills", "Manage project-local AI skills."]
    };

    function $(id) {
        return document.getElementById(id);
    }

    function callBridge(method, ...args) {
        return new Promise((resolve) => {
            if (!bridge || typeof bridge[method] !== "function") {
                resolve({ ok: false, error: `Bridge method unavailable: ${method}` });
                return;
            }
            bridge[method](...args, (raw) => {
                try {
                    resolve(JSON.parse(raw || "{}"));
                } catch (err) {
                    resolve({ ok: false, error: String(err), raw });
                }
            });
        });
    }

    function setStatus(text, isError) {
        const el = $("status-text");
        if (!el) return;
        el.textContent = text || "";
        el.style.color = isError ? "var(--danger-color)" : "var(--text-secondary)";
    }

    function activeProfile() {
        return state.profiles.find((profile) => profile.name === state.current_profile) || state.profiles[0] || null;
    }

    function syncProfileFromInputs() {
        const profile = activeProfile();
        if (!profile) return;
        profile.api_key = $("api-key-input").value.trim();
        profile.base_url = $("base-url-input").value.trim();
        profile.model = $("model-input").value.trim();
        profile.provider = profile.provider || "Custom / Other";
    }

    function syncBehaviorFromInputs() {
        state.behavior.max_rounds = Number($("max-rounds-input").value || 1);
        state.behavior.max_history = Number($("max-history-input").value || 1);
        state.behavior.auto_load = $("auto-load-input").checked;
        state.behavior.mcp_enabled = $("mcp-enabled-input").checked;
    }

    function collectStateForSave() {
        syncProfileFromInputs();
        syncBehaviorFromInputs();
        return {
            profiles: state.profiles,
            current_profile: state.current_profile,
            behavior: state.behavior,
            whitelist: state.whitelist,
            mcp_servers: state.mcp_servers,
            disabled_skills: state.disabled_skills
        };
    }

    function renderAll() {
        renderProfiles();
        renderBehavior();
        renderWhitelist();
        renderMcpServers();
        renderTools();
        renderSkills();
    }

    function renderProfiles() {
        const select = $("profile-select");
        select.innerHTML = "";
        state.profiles.forEach((profile) => {
            const option = document.createElement("option");
            option.value = profile.name;
            option.textContent = profile.name;
            select.appendChild(option);
        });
        if (!state.current_profile && state.profiles[0]) state.current_profile = state.profiles[0].name;
        select.value = state.current_profile;

        const profile = activeProfile();
        $("api-key-input").value = profile ? profile.api_key || "" : "";
        $("base-url-input").value = profile ? profile.base_url || "" : "";
        $("model-input").value = profile ? profile.model || "" : "";
    }

    function renderBehavior() {
        $("max-rounds-input").value = state.behavior.max_rounds || 5;
        $("max-history-input").value = state.behavior.max_history || 10;
        $("auto-load-input").checked = Boolean(state.behavior.auto_load);
        $("mcp-enabled-input").checked = Boolean(state.behavior.mcp_enabled);
    }

    function renderWhitelist() {
        const list = $("whitelist-list");
        list.innerHTML = "";
        state.whitelist.forEach((path, index) => {
            const row = document.createElement("div");
            row.className = "list-row";
            row.innerHTML = `
                <div title="${escapeHtml(path)}">
                    <strong>${escapeHtml(pathBaseName(path))}</strong>
                    <div class="small-text">${escapeHtml(path)}</div>
                </div>
            `;
            const remove = document.createElement("button");
            remove.className = "danger-btn";
            remove.textContent = "Remove";
            remove.addEventListener("click", () => {
                state.whitelist.splice(index, 1);
                renderWhitelist();
            });
            row.appendChild(remove);
            list.appendChild(row);
        });
    }

    function renderMcpServers() {
        const list = $("mcp-list");
        list.innerHTML = "";
        Object.entries(state.mcp_servers || {}).forEach(([name, conf]) => {
            const row = document.createElement("div");
            row.className = "list-row";
            const body = document.createElement("div");
            body.innerHTML = `
                <strong>${escapeHtml(name)}</strong>
                <div class="small-text" title="${escapeHtml(`${conf.command || ""} ${(conf.args || []).join(" ")}`)}">${escapeHtml(conf.command || "")} ${escapeHtml((conf.args || []).join(" "))}</div>
            `;
            const actions = document.createElement("div");
            actions.className = "row-actions";
            const test = document.createElement("button");
            test.className = "secondary-btn";
            test.textContent = "Test";
            test.addEventListener("click", () => testMcpServer(name, conf));
            const remove = document.createElement("button");
            remove.className = "danger-btn";
            remove.textContent = "Remove";
            remove.addEventListener("click", () => {
                delete state.mcp_servers[name];
                renderMcpServers();
            });
            actions.append(test, remove);
            row.append(body, actions);
            list.appendChild(row);
        });
    }

    function renderTools() {
        const search = ($("tools-search").value || "").toLowerCase();
        const container = $("tools-container");
        const tools = state.tools || { total: 0, categories: [] };
        $("tools-summary").textContent = `Local tools: ${tools.total || 0}`;
        container.innerHTML = "";

        (tools.categories || []).forEach((category) => {
            const rows = (category.tools || []).filter((tool) => {
                const text = `${tool.name} ${tool.description} ${(tool.tags || []).join(" ")} ${(tool.keywords || []).join(" ")}`.toLowerCase();
                return !search || text.includes(search);
            });
            if (!rows.length) return;

            const wrap = document.createElement("div");
            wrap.className = "tool-category";
            const title = document.createElement("div");
            title.className = "tool-category-title";
            title.textContent = `${category.name} (${rows.length})`;
            wrap.appendChild(title);

            const header = document.createElement("div");
            header.className = "tool-row tool-row-header";
            header.innerHTML = `
                <div>Tool</div>
                <div>Description</div>
                <div>Tags</div>
                <div>Risk</div>
            `;
            wrap.appendChild(header);

            rows.forEach((tool) => {
                const row = document.createElement("div");
                row.className = "tool-row";
                row.title = tool.usage_hint || tool.description || "";
                row.innerHTML = `
                    <div class="tool-name">${escapeHtml(tool.name)}</div>
                    <div class="tool-description">${escapeHtml(compactText(tool.description || "", 190))}</div>
                    <div class="tool-tags">${escapeHtml((tool.tags || []).join(", "))}</div>
                    <div class="risk-pill">${escapeHtml(tool.risk || "low")}</div>
                `;
                wrap.appendChild(row);
            });
            container.appendChild(wrap);
        });
    }

    function renderSkills() {
        const container = $("skills-container");
        container.innerHTML = "";
        (state.skills || []).forEach((skill) => {
            const card = document.createElement("article");
            card.className = "skill-card";
            const disabled = state.disabled_skills.includes(skill.id);
            card.innerHTML = `
                <div class="skill-summary">
                    <div class="skill-copy">
                        <div class="skill-title">${escapeHtml(skill.title || skill.id)}</div>
                        <div class="small-text">ID: ${escapeHtml(skill.id)} | Aliases: ${escapeHtml((skill.aliases || []).join(", ") || "-")}</div>
                        <p class="skill-description">${escapeHtml(skill.description || "")}</p>
                    </div>
                    <label class="skill-enabled"><input type="checkbox" ${disabled ? "" : "checked"} data-skill-toggle="${escapeHtml(skill.id)}"> Enabled</label>
                </div>
                <details class="skill-editor">
                    <summary>Edit instruction</summary>
                    <textarea data-skill-body="${escapeHtml(skill.id)}">${escapeHtml(skill.instruction || "")}</textarea>
                    <div class="row-actions">
                        <button class="secondary-btn" data-skill-save="${escapeHtml(skill.id)}">Save Skill</button>
                        <button class="danger-btn" data-skill-delete="${escapeHtml(skill.id)}">Delete Skill</button>
                    </div>
                </details>
            `;
            container.appendChild(card);
        });

        container.querySelectorAll("[data-skill-toggle]").forEach((input) => {
            input.addEventListener("change", () => {
                const id = input.dataset.skillToggle;
                state.disabled_skills = state.disabled_skills.filter((item) => item !== id);
                if (!input.checked) state.disabled_skills.push(id);
            });
        });
        container.querySelectorAll("[data-skill-save]").forEach((button) => {
            button.addEventListener("click", () => saveSkill(button.dataset.skillSave));
        });
        container.querySelectorAll("[data-skill-delete]").forEach((button) => {
            button.addEventListener("click", () => deleteSkill(button.dataset.skillDelete));
        });
    }

    async function loadPayload() {
        setStatus("Loading...");
        const response = await callBridge("getSettingsPayload");
        if (!response.ok) {
            setStatus(response.error || "Failed to load settings.", true);
            return;
        }
        state = response.payload || state;
        renderAll();
        setStatus("");
    }

    async function saveSettings() {
        const response = await callBridge("saveSettings", JSON.stringify(collectStateForSave()));
        if (!response.ok) {
            setStatus(response.error || "Save failed.", true);
            return;
        }
        state = response.payload || state;
        renderAll();
        setStatus("Saved.");
    }

    async function refreshTools() {
        const response = await callBridge("refreshTools");
        if (!response.ok) {
            setStatus(response.error || "Tool refresh failed.", true);
            return;
        }
        state.tools = response.tools;
        renderTools();
        setStatus("Tools refreshed.");
    }

    async function choosePath(kind) {
        const response = await callBridge(kind === "folder" ? "chooseFolder" : "chooseFile");
        if (response.ok && response.path) {
            state.whitelist.push(response.path);
            renderWhitelist();
        }
    }

    async function fetchModels() {
        syncProfileFromInputs();
        const profile = activeProfile();
        const response = await callBridge("fetchModels", JSON.stringify(profile || {}));
        if (!response.ok) {
            setStatus(response.error || "Model fetch failed.", true);
            return;
        }
        const list = $("model-list");
        list.innerHTML = "";
        (response.models || []).slice(0, 50).forEach((model) => {
            const pill = document.createElement("button");
            pill.className = "model-pill";
            pill.textContent = model;
            pill.addEventListener("click", () => {
                $("model-input").value = model;
                syncProfileFromInputs();
            });
            list.appendChild(pill);
        });
        setStatus(`Fetched ${(response.models || []).length} model(s).`);
    }

    async function testMcpServer(name, conf) {
        const response = await callBridge("testMcpServer", name, JSON.stringify(conf || {}));
        if (!response.ok) {
            setStatus(response.error || "MCP test failed.", true);
            return;
        }
        setStatus(`MCP '${name}' OK: ${(response.tools || []).length} tool(s).`);
    }

    async function saveSkill(skillId) {
        const skill = (state.skills || []).find((item) => item.id === skillId);
        const body = document.querySelector(`[data-skill-body="${cssEscape(skillId)}"]`);
        const response = await callBridge("updateSkill", JSON.stringify({
            id: skillId,
            title: skill ? skill.title : skillId,
            description: skill ? skill.description : "",
            instruction: body ? body.value : ""
        }));
        if (!response.ok) {
            setStatus(response.error || "Skill save failed.", true);
            return;
        }
        state.skills = response.skills || state.skills;
        renderSkills();
        setStatus("Skill saved.");
    }

    async function deleteSkill(skillId) {
        if (!confirm(`Delete skill '${skillId}'?`)) return;
        const response = await callBridge("deleteSkill", skillId);
        if (!response.ok) {
            setStatus(response.error || "Skill delete failed.", true);
            return;
        }
        state.skills = response.skills || [];
        renderSkills();
        setStatus("Skill deleted.");
    }

    async function createSkill() {
        const skillId = prompt("Skill ID (e.g., custom/my-skill):", "");
        if (!skillId) return;
        const response = await callBridge("createSkill", skillId);
        if (!response.ok) {
            setStatus(response.error || "Skill create failed.", true);
            return;
        }
        state.skills = response.skills || [];
        renderSkills();
        setStatus("Skill created.");
    }

    function bindEvents() {
        document.querySelectorAll(".nav-item").forEach((button) => {
            button.addEventListener("click", () => switchPanel(button.dataset.panel));
        });
        $("profile-select").addEventListener("change", () => {
            syncProfileFromInputs();
            state.current_profile = $("profile-select").value;
            renderProfiles();
        });
        $("profile-add-btn").addEventListener("click", () => {
            const name = prompt("Profile name:", "New Profile");
            if (!name) return;
            syncProfileFromInputs();
            state.profiles.push({ name, provider: "Custom / Other", api_key: "", base_url: "", model: "" });
            state.current_profile = name;
            renderProfiles();
        });
        $("profile-rename-btn").addEventListener("click", () => {
            const profile = activeProfile();
            if (!profile) return;
            const name = prompt("New profile name:", profile.name);
            if (!name) return;
            profile.name = name;
            state.current_profile = name;
            renderProfiles();
        });
        $("profile-delete-btn").addEventListener("click", () => {
            if (state.profiles.length <= 1) {
                setStatus("Cannot delete the last profile.", true);
                return;
            }
            const profile = activeProfile();
            if (!profile || !confirm(`Delete profile '${profile.name}'?`)) return;
            state.profiles = state.profiles.filter((item) => item !== profile);
            state.current_profile = state.profiles[0].name;
            renderProfiles();
        });
        $("save-btn").addEventListener("click", saveSettings);
        $("refresh-btn").addEventListener("click", loadPayload);
        $("close-btn").addEventListener("click", () => bridge && bridge.closeSettingsPage());
        $("fetch-models-btn").addEventListener("click", fetchModels);
        $("add-folder-btn").addEventListener("click", () => choosePath("folder"));
        $("add-file-btn").addEventListener("click", () => choosePath("file"));
        $("add-mcp-btn").addEventListener("click", addMcpServer);
        $("tools-search").addEventListener("input", renderTools);
        $("create-skill-btn").addEventListener("click", createSkill);
    }

    function addMcpServer() {
        const name = prompt("Local MCP server name:", "");
        if (!name) return;
        const command = prompt("Command:", "");
        if (!command) return;
        const argsText = prompt("Arguments (space separated, one per line, or JSON list):", "") || "";
        callBridge("parseMcpArgs", argsText).then((response) => {
            if (!response.ok) {
                setStatus(response.error || "Invalid MCP args.", true);
                return;
            }
            state.mcp_servers[name] = { name, command, args: response.args || [], env: {}, enabled: true };
            renderMcpServers();
        });
    }

    function switchPanel(name) {
        document.querySelectorAll(".nav-item").forEach((button) => {
            button.classList.toggle("active", button.dataset.panel === name);
        });
        document.querySelectorAll(".panel").forEach((panel) => {
            panel.classList.toggle("active", panel.id === `panel-${name}`);
        });
        const meta = panelTitles[name] || [name, ""];
        $("panel-title").textContent = meta[0];
        $("panel-subtitle").textContent = meta[1];
    }

    function escapeHtml(value) {
        return String(value || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    function compactText(value, maxLen) {
        const text = String(value || "").replace(/\s+/g, " ").trim();
        if (text.length <= maxLen) return text;
        return `${text.slice(0, maxLen - 1).trim()}…`;
    }

    function pathBaseName(path) {
        const parts = String(path || "").replace(/\\/g, "/").split("/").filter(Boolean);
        return parts[parts.length - 1] || path || "(path)";
    }

    function cssEscape(value) {
        if (window.CSS && window.CSS.escape) return window.CSS.escape(value);
        return String(value || "").replace(/"/g, '\\"');
    }

    window.setTheme = function () {};
    window.setPagePayload = function () {
        loadPayload();
    };

    document.addEventListener("DOMContentLoaded", () => {
        bindEvents();
        new QWebChannel(qt.webChannelTransport, (channel) => {
            bridge = channel.objects.pageBridge;
            if (bridge && bridge.log) bridge.log("Agent page ready");
            loadPayload();
        });
    });
})();
