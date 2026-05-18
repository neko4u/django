let currentConversationId = null;
let isStreaming = false;
let abortController = null;
let userPermissions = {};

document.addEventListener('DOMContentLoaded', () => {
    checkPermissions();
    setupEventListeners();
    loadConversations();
});

async function checkPermissions() {
    try {
        const resp = await fetch('/chat/permissions/');
        if (!resp.ok) throw new Error('权限检查失败');
        const data = await resp.json();
        userPermissions = data;
        if (!userPermissions.can_access_chat) {
            document.body.innerHTML = '<div style="color: var(--text-primary); text-align: center; margin-top: 100px;">您无权使用聊天功能</div>';
            return;
        }
        buildParamsPanel();
    } catch (e) {
        console.error('权限检查失败:', e);
    }
}

function setupEventListeners() {
    document.getElementById('new-chat-btn').addEventListener('click', createNewConversation);
    document.getElementById('send-btn').addEventListener('click', sendMessage);
    document.getElementById('stop-btn').addEventListener('click', stopGeneration);
    document.getElementById('toggle-sidebar').addEventListener('click', toggleSidebar);
    document.getElementById('toggle-params').addEventListener('click', toggleParams);

    const textarea = document.getElementById('user-input');
    textarea.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
}

function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('collapsed');
}

function toggleParams() {
    const panel = document.getElementById('params-panel');
    panel.classList.toggle('collapsed');
    const btn = document.getElementById('toggle-params');
    if (panel.classList.contains('collapsed')) {
        btn.innerHTML = '▶';
        btn.title = '展开面板';
    } else {
        btn.innerHTML = '◀';
        btn.title = '隐藏面板';
    }
}

async function loadConversations() {
    const resp = await fetch('/chat/list/');
    const conversations = await resp.json();
    const listEl = document.getElementById('conversation-list');
    listEl.innerHTML = '';
    conversations.forEach(conv => {
        const item = document.createElement('div');
        item.className = 'conversation-item';
        item.dataset.id = conv.id;
        item.innerHTML = `
            <div class="conversation-info">
                <div class="conversation-title">${escapeHtml(conv.title)}</div>
                <div class="conversation-time">${formatDate(conv.updated_at)}</div>
            </div>
            <button class="conversation-delete" title="删除对话">✕</button>
        `;
        item.querySelector('.conversation-info').addEventListener('click', () => loadConversation(conv.id));
        item.querySelector('.conversation-title').addEventListener('dblclick', (e) => {
            e.stopPropagation();
            renameConversation(conv.id, item.querySelector('.conversation-title'));
        });
        item.querySelector('.conversation-delete').addEventListener('click', (e) => {
            e.stopPropagation();
            deleteConversation(conv.id);
        });
        listEl.appendChild(item);
    });
}

async function loadConversation(id) {
    currentConversationId = id;
    document.querySelectorAll('.conversation-item').forEach(el => el.classList.remove('active'));
    const activeItem = document.querySelector(`.conversation-item[data-id="${id}"]`);
    if (activeItem) activeItem.classList.add('active');

    const resp = await fetch(`/chat/${id}/messages/`);
    const messages = await resp.json();
    const chatEl = document.getElementById('chat-messages');
    chatEl.innerHTML = '';
    messages.forEach(msg => addMessageToUI(msg.role, msg.content));
    chatEl.scrollTop = chatEl.scrollHeight;

    loadConfig(id);
}

async function createNewConversation() {
    const resp = await fetch('/chat/new/', { method: 'POST' });
    const data = await resp.json();
    if (data.conversation_id) {
        await loadConversations();
        loadConversation(data.conversation_id);
    }
}

async function deleteConversation(id) {
    if (!confirm('确定要删除这个对话吗？')) return;
    await fetch(`/chat/${id}/delete/`, { method: 'DELETE' });
    if (currentConversationId === id) {
        currentConversationId = null;
        document.getElementById('chat-messages').innerHTML = '';
    }
    loadConversations();
}

async function renameConversation(id, titleElement) {
    const oldTitle = titleElement.innerText;
    const input = document.createElement('input');
    input.value = oldTitle;
    input.style.width = '100%';
    input.style.padding = '2px';
    input.className = 'rename-input';
    titleElement.replaceWith(input);
    input.focus();
    input.addEventListener('blur', async () => {
        const newTitle = input.value.trim();
        if (newTitle && newTitle !== oldTitle) {
            await fetch(`/chat/${id}/rename/`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: newTitle }),
            });
        }
        loadConversations();
    });
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') input.blur();
    });
}

async function sendMessage() {
    if (isStreaming) return;
    const textarea = document.getElementById('user-input');
    const message = textarea.value.trim();
    if (!message) return;

    if (!currentConversationId) {
        const resp = await fetch('/chat/new/', { method: 'POST' });
        const data = await resp.json();
        if (!data.conversation_id) {
            alert('创建新对话失败，请刷新页面重试');
            return;
        }
        currentConversationId = data.conversation_id;
        await loadConversations();
        document.querySelectorAll('.conversation-item').forEach(el => el.classList.remove('active'));
        const newItem = document.querySelector(`.conversation-item[data-id="${currentConversationId}"]`);
        if (newItem) newItem.classList.add('active');
    }

    textarea.value = '';

    addMessageToUI('user', message);

    const assistantMsgDiv = addMessageToUI('assistant', '');
    assistantMsgDiv.innerHTML = '<div class="content"><span class="thinking">思考中...</span></div>';

    isStreaming = true;
    document.getElementById('send-btn').style.display = 'none';
    document.getElementById('stop-btn').style.display = 'inline-block';

    abortController = new AbortController();
    let assistantContent = '';

    try {
        const response = await fetch(`/chat/${currentConversationId}/send/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: message }),
            signal: abortController.signal,
        });

        if (!response.ok) {
            isStreaming = false;
            document.getElementById('send-btn').style.display = 'inline-block';
            document.getElementById('stop-btn').style.display = 'none';
            assistantMsgDiv.innerHTML = '<div class="content" style="color:var(--danger);">请求失败，请重试</div>';
            return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop();
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    const jsonStr = line.slice(6);
                    try {
                        const data = JSON.parse(jsonStr);
                        if (data.error) {
                            assistantMsgDiv.innerHTML = `<div class="content" style="color:var(--danger);">${escapeHtml(data.error)}</div>`;
                            break;
                        }
                        if (data.stopped) break;
                        if (data.content) {
                            assistantContent += data.content;
                            assistantMsgDiv.innerHTML = `<div class="content">${marked.parse(assistantContent)}</div>`;
                            document.querySelectorAll('pre code').forEach(block => hljs.highlightElement(block));
                        }
                        if (data.need_title) {
                            generateTitle(currentConversationId);
                        }
                    } catch (e) {}
                }
            }
            const chatEl = document.getElementById('chat-messages');
            chatEl.scrollTop = chatEl.scrollHeight;
        }
    } catch (err) {
        if (err.name !== 'AbortError') {
            console.error(err);
            assistantMsgDiv.innerHTML = '<div class="content" style="color:var(--danger);">网络错误，请重试</div>';
        }
    } finally {
        isStreaming = false;
        document.getElementById('send-btn').style.display = 'inline-block';
        document.getElementById('stop-btn').style.display = 'none';
        abortController = null;
    }
}

async function stopGeneration() {
    if (abortController) abortController.abort();
    await fetch('/chat/stop/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ conversation_id: currentConversationId }),
    });
    isStreaming = false;
    document.getElementById('send-btn').style.display = 'inline-block';
    document.getElementById('stop-btn').style.display = 'none';
}

async function generateTitle(conversationId) {
    const resp = await fetch(`/chat/${conversationId}/generate_title/`, { method: 'POST' });
    const data = await resp.json();
    if (data.title) loadConversations();
}

async function loadConfig(conversationId) {
    const resp = await fetch(`/chat/${conversationId}/config/`);
    const config = await resp.json();
    if (!config || config.error) return;
    const setVal = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
    setVal('model-select', config.model_name);
    setVal('temperature', config.temperature);
    document.getElementById('temperature-value').innerText = config.temperature;
    setVal('max_tokens', config.max_tokens);
    document.getElementById('max_tokens-value').innerText = config.max_tokens;
    setVal('top_p', config.top_p);
    document.getElementById('top_p-value').innerText = config.top_p;
    setVal('presence_penalty', config.presence_penalty);
    document.getElementById('presence_penalty-value').innerText = config.presence_penalty;
    setVal('frequency_penalty', config.frequency_penalty);
    document.getElementById('frequency_penalty-value').innerText = config.frequency_penalty;

    const webSearchToggle = document.getElementById('web-search-toggle');
    if (webSearchToggle) {
        webSearchToggle.checked = config.web_search_enabled || false;
    }
    updateWebSearchToggle();
}

async function saveConfig() {
    if (!currentConversationId) return;
    const getVal = (id) => document.getElementById(id).value;
    const webSearchToggle = document.getElementById('web-search-toggle');
    const payload = {
        model_name: getVal('model-select'),
        temperature: parseFloat(getVal('temperature')),
        max_tokens: parseInt(getVal('max_tokens')),
        top_p: parseFloat(getVal('top_p')),
        presence_penalty: parseFloat(getVal('presence_penalty')),
        frequency_penalty: parseFloat(getVal('frequency_penalty')),
        web_search_enabled: webSearchToggle ? webSearchToggle.checked : false,
    };
    await fetch(`/chat/${currentConversationId}/config/update/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
    });
    alert('配置已保存');
}

async function buildParamsPanel() {
    let models = [];
    try {
        const resp = await fetch('/chat/models/');
        if (resp.ok) models = await resp.json();
    } catch (e) {
        console.error('获取模型列表失败', e);
    }
    if (models.length === 0) {
        models = [{ id: 'moonshot-v1-8k', name: 'Moonshot 8K' }];
    }

    const optionsHTML = models.map(m => `<option value="${m.id}">${m.name}</option>`).join('');

    const container = document.getElementById('params-content');
    container.innerHTML = `
        <div class="param-group">
            <label>模型</label>
            <select id="model-select">${optionsHTML}</select>
        </div>
        <div class="param-group">
            <label>Temperature</label>
            <input type="range" id="temperature" min="0" max="2" step="0.1" ${userPermissions.can_set_temperature ? '' : 'disabled'}>
            <span class="range-value" id="temperature-value">0.7</span>
        </div>
        <div class="param-group">
            <label>Max Tokens</label>
            <input type="number" id="max_tokens" min="1" max="4096" ${userPermissions.can_set_max_tokens ? '' : 'disabled'}>
            <span class="range-value" id="max_tokens-value">1024</span>
        </div>
        <div class="param-group">
            <label>Top P</label>
            <input type="range" id="top_p" min="0" max="1" step="0.05" ${userPermissions.can_set_top_p ? '' : 'disabled'}>
            <span class="range-value" id="top_p-value">1.0</span>
        </div>
        <div class="param-group">
            <label>Presence Penalty</label>
            <input type="range" id="presence_penalty" min="0" max="2" step="0.1" ${userPermissions.can_set_presence_penalty ? '' : 'disabled'}>
            <span class="range-value" id="presence_penalty-value">0.0</span>
        </div>
        <div class="param-group">
            <label>Frequency Penalty</label>
            <input type="range" id="frequency_penalty" min="0" max="2" step="0.1" ${userPermissions.can_set_frequency_penalty ? '' : 'disabled'}>
            <span class="range-value" id="frequency_penalty-value">0.0</span>
        </div>
        <div class="param-group">
            <label>联网搜索</label>
            <div class="toggle-switch">
                <input type="checkbox" id="web-search-toggle" disabled>
                <label for="web-search-toggle" class="toggle-label"></label>
                <span id="web-search-status" style="margin-left: 8px; font-size: 13px; color: var(--text-secondary);"></span>
            </div>
        </div>
        <button onclick="saveConfig()" class="btn-save">保存配置</button>
    `;

    ['temperature', 'top_p', 'presence_penalty', 'frequency_penalty'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('input', () => {
            document.getElementById(`${id}-value`).innerText = el.value;
        });
    });
    document.getElementById('max_tokens')?.addEventListener('input', function() {
        document.getElementById('max_tokens-value').innerText = this.value;
    });

    const modelSelect = document.getElementById('model-select');
    if (modelSelect) {
        modelSelect.addEventListener('change', updateWebSearchToggle);
    }
    updateWebSearchToggle();
}

async function updateWebSearchToggle() {
    const model = document.getElementById('model-select')?.value;
    const toggle = document.getElementById('web-search-toggle');
    const statusSpan = document.getElementById('web-search-status');
    if (!model || !toggle) return;

    try {
        const resp = await fetch(`/chat/web_search_check/?model_name=${encodeURIComponent(model)}`);
        if (resp.ok) {
            const data = await resp.json();
            if (data.supported) {
                toggle.disabled = false;
                statusSpan.textContent = '可用';
                statusSpan.style.color = 'var(--accent)';
            } else {
                toggle.disabled = true;
                toggle.checked = false;
                statusSpan.textContent = '不支持';
                statusSpan.style.color = 'var(--text-secondary)';
            }
        }
    } catch (e) {
        toggle.disabled = true;
        statusSpan.textContent = '检查失败';
        statusSpan.style.color = 'var(--danger)';
    }
}

function addMessageToUI(role, content) {
    const chatEl = document.getElementById('chat-messages');
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${role}`;
    if (content) {
        msgDiv.innerHTML = `<div class="content">${role === 'assistant' ? marked.parse(content) : escapeHtml(content)}</div>`;
    } else {
        msgDiv.innerHTML = `<div class="content"></div>`;
    }
    chatEl.appendChild(msgDiv);
    if (role === 'assistant') {
        document.querySelectorAll('pre code').forEach(block => hljs.highlightElement(block));
    }
    chatEl.scrollTop = chatEl.scrollHeight;
    return msgDiv;
}

function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

function formatDate(isoString) {
    if (!isoString) return '';
    const date = new Date(isoString);
    return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}