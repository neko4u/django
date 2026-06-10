let currentConversationId = null;
let isStreaming = false;
let abortController = null;
let userPermissions = {};
let activeStreamConversationId = null;
let streamAbortControllers = {};
let userScrolledUp = false;
let scrollToBottomBtn = null;


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
    scrollToBottomBtn = document.getElementById('scroll-to-bottom-btn');

    if (scrollToBottomBtn) {
        scrollToBottomBtn.addEventListener('click', () => {
            const chatEl = document.getElementById('chat-messages');
            chatEl.scrollTop = chatEl.scrollHeight;
            userScrolledUp = false;
            scrollToBottomBtn.style.display = 'none';
        });
    }
    const chatMessages = document.getElementById('chat-messages');
    chatMessages.addEventListener('scroll', () => {
        const threshold = 50; // 容差像素
        const isAtBottom = chatMessages.scrollHeight - chatMessages.scrollTop - chatMessages.clientHeight < threshold;
        userScrolledUp = !isAtBottom;
        if (scrollToBottomBtn) {
            scrollToBottomBtn.style.display = userScrolledUp ? 'block' : 'none';
        }
    });
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
    showLoading();
    currentConversationId = id;
    document.querySelectorAll('.conversation-item').forEach(el => el.classList.remove('active'));
    const activeItem = document.querySelector(`.conversation-item[data-id="${id}"]`);
    if (activeItem) activeItem.classList.add('active');

    const resp = await fetch(`/chat/${id}/messages/`);
    const data = await resp.json();
    const messages = data.messages;
    const chatEl = document.getElementById('chat-messages');
    chatEl.innerHTML = '';
    messages.forEach(msg => addMessageToUI(msg.role, msg.content));
    chatEl.scrollTop = chatEl.scrollHeight;

    userScrolledUp = false;
    if (scrollToBottomBtn) scrollToBottomBtn.style.display = 'none';

    if (data.is_generating) {
        activeStreamConversationId = id;
        addMessageToUI('assistant', '思考中...');
    } else {
        if (activeStreamConversationId === id) activeStreamConversationId = null;
    }
    updateSendButton();

    loadConfig(id);
    hideLoading();
}

function updateSendButton() {
    const sendBtn = document.getElementById('send-btn');
    const stopBtn = document.getElementById('stop-btn');
    if (currentConversationId && activeStreamConversationId === currentConversationId) {
        sendBtn.style.display = 'none';
        stopBtn.style.display = 'inline-block';
    } else {
        sendBtn.style.display = 'inline-block';
        stopBtn.style.display = 'none';
    }
}

async function createNewConversation() {
    showLoading();
    const resp = await fetch('/chat/new/', { method: 'POST' });
    const data = await resp.json();
    if (data.conversation_id) {
        await loadConversations();
        loadConversation(data.conversation_id);
    }
    hideLoading();
}

async function deleteConversation(id) {
    if (!confirm('确定要删除这个对话吗？')) return;
    showLoading();
    await fetch(`/chat/${id}/delete/`, { method: 'DELETE' });
    if (currentConversationId === id) {
        currentConversationId = null;
        document.getElementById('chat-messages').innerHTML = '';
    }
    loadConversations();
    hideLoading();
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
    const textarea = document.getElementById('user-input');
    const message = textarea.value.trim();
    if (!message) return;
    
    // 固化当前会话 ID，防止切换时污染
    let sendingConversationId = currentConversationId;

    // 如果目标会话正在生成，禁止重复发送
    if (activeStreamConversationId === sendingConversationId) return;

    // 若无会话，新建一个
    if (!sendingConversationId) {
        const resp = await fetch('/chat/new/', { method: 'POST' });
        const data = await resp.json();
        if (!data.conversation_id) {
            alert('创建新对话失败，请刷新页面重试');
            return;
        }
        sendingConversationId = data.conversation_id;
        currentConversationId = sendingConversationId;
        await loadConversations();
        document.querySelectorAll('.conversation-item').forEach(el => el.classList.remove('active'));
        const newItem = document.querySelector(`.conversation-item[data-id="${sendingConversationId}"]`);
        if (newItem) newItem.classList.add('active');
    }

    textarea.value = '';

    // 添加用户消息和占位 assistant 消息
    addMessageToUI('user', message);
    addMessageToUI('assistant', '思考中...');
    const chatEl = document.getElementById('chat-messages');
    chatEl.scrollTop = chatEl.scrollHeight;

    userScrolledUp = false;
    // 标记该会话为生成中
    activeStreamConversationId = sendingConversationId;
    updateSendButton();

    const abortController = new AbortController();
    streamAbortControllers[sendingConversationId] = abortController;

    let assistantContent = '';
    const toolCallEnabled = document.getElementById('tool-calls-toggle')?.checked || false;
    try {
        const response = await fetch(`/chat/${sendingConversationId}/send/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: message, enable_tool_calls: toolCallEnabled }),
            signal: abortController.signal,
        });

        if (!response.ok) throw new Error('请求失败');

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
                        // 错误处理
                        if (data.error) {
                            if (currentConversationId === sendingConversationId) {
                                const chatEl = document.getElementById('chat-messages');
                                const lastAssistant = chatEl.querySelector('.message.assistant:last-child .content');
                                if (lastAssistant) lastAssistant.innerHTML = `<span style="color:var(--danger);">${escapeHtml(data.error)}</span>`;
                                if (!userScrolledUp) {
                                    chatEl.scrollTop = chatEl.scrollHeight;
                                }
                            }
                            throw new Error(data.error);
                        }
                        // 用户停止
                        if (data.stopped) {
                            if (currentConversationId === sendingConversationId) {
                                const chatEl = document.getElementById('chat-messages');
                                const lastAssistant = chatEl.querySelector('.message.assistant:last-child .content');
                                if (lastAssistant) lastAssistant.innerHTML += '<br><span style="color:var(--danger);">已停止生成</span>';
                            }
                            break;
                        }
                        // 正常内容流
                        if (data.content) {
                            assistantContent += data.content;
                            // 仅当用户正在查看该会话时才更新 UI
                            if (currentConversationId === sendingConversationId) {
                                const chatEl = document.getElementById('chat-messages');
                                const lastAssistant = chatEl.querySelector('.message.assistant:last-child .content');
                                if (lastAssistant) {
                                    lastAssistant.innerHTML = marked.parse(assistantContent);
                                    document.querySelectorAll('pre code').forEach(block => hljs.highlightElement(block));
                                    if (!userScrolledUp) {
                                        chatEl.scrollTop = chatEl.scrollHeight;
                                    }
                                }
                            }
                        }
                        // 需要自动生成标题
                        if (data.need_title) {
                            generateTitle(sendingConversationId);
                        }
                    } catch (e) {
                        // 忽略 JSON 解析错误或内部抛出的中断信号
                    }
                }
            }
        }
    } catch (err) {
        // 网络错误或请求中断
        if (err.name !== 'AbortError' && currentConversationId === sendingConversationId) {
            const chatEl = document.getElementById('chat-messages');
            const lastAssistant = chatEl.querySelector('.message.assistant:last-child .content');
            if (lastAssistant) lastAssistant.innerHTML = '<span style="color:var(--danger);">网络错误，请重试</span>';
        }
    } finally {
        // 清理状态，使用固化的会话 ID
        delete streamAbortControllers[sendingConversationId];
        if (activeStreamConversationId === sendingConversationId) {
            activeStreamConversationId = null;
        }
        updateSendButton();
    }
}

async function stopGeneration() {
    const convoId = currentConversationId;
    if (!convoId) return;

    if (streamAbortControllers[convoId]) {
        streamAbortControllers[convoId].abort();
        delete streamAbortControllers[convoId];
    }

    await fetch('/chat/stop/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ conversation_id: currentConversationId }),
    });
    if (activeStreamConversationId === convoId) {
        activeStreamConversationId = null;
    }
    updateSendButton();
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
    const tavilySearchToggle = document.getElementById('tavily-search-toggle');
    if (tavilySearchToggle) {
        tavilySearchToggle.checked = config.tavily_search_enabled || false;
    }
    const toolCallsToggle = document.getElementById('tool-calls-toggle');
    if (toolCallsToggle) {
        toolCallsToggle.checked = config.tools_enabled || false;
    }
    updateWebSearchToggle();
    updateTavilySearchToggle();
    updateToolCallsToggle();
}

async function saveConfig() {
    if (!currentConversationId) return;
    const getVal = (id) => document.getElementById(id).value;
    const payload = {
        model_name: getVal('model-select'),
        temperature: parseFloat(getVal('temperature')),
        max_tokens: parseInt(getVal('max_tokens')) || 102400,
        top_p: parseFloat(getVal('top_p')),
        presence_penalty: parseFloat(getVal('presence_penalty')),
        frequency_penalty: parseFloat(getVal('frequency_penalty')),
        web_search_enabled: document.getElementById('web-search-toggle')?.checked || false,
        tavily_search_enabled: document.getElementById('tavily-search-toggle')?.checked || false,
        tools_enabled: document.getElementById('tool-calls-toggle')?.checked || false,
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
            <label>原生联网搜索</label>
            <div class="toggle-switch">
                <input type="checkbox" id="web-search-toggle" disabled>
                <label for="web-search-toggle" class="toggle-label"></label>
                <span id="web-search-status" style="margin-left: 8px; font-size: 13px; color: var(--text-secondary);"></span>
            </div>
            <label>T联网搜索</label>
            <div class="toggle-switch">
                <input type="checkbox" id="tavily-search-toggle" disabled>
                <label for="tavily-search-toggle" class="toggle-label"></label>
                <span id="tavily-search-status" style="margin-left: 8px; font-size: 13px; color: var(--text-secondary);"></span>
            </div>
            <label>高级功能</label>
            <div class="toggle-switch">
                <input type="checkbox" id="tool-calls-toggle" disabled>
                <label for="tool-calls-toggle" class="toggle-label"></label>
                <span id="tool-calls-status" style="margin-left: 8px; font-size: 13px; color: var(--text-secondary);"></span>
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
        modelSelect.addEventListener('change', updateToolCallToggle);
        modelSelect.addEventListener('change', updateTavilySearchToggle); 
        modelSelect.addEventListener('change', updateToolCallsToggle); 
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

async function updateTavilySearchToggle() {
    const model = document.getElementById('model-select')?.value;
    const toggle = document.getElementById('tavily-search-toggle');
    const statusSpan = document.getElementById('tavily-search-status');
    if (!model || !toggle) return;

    try {
        const resp = await fetch(`/chat/tavily_search_check/?model_name=${encodeURIComponent(model)}`);
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


async function updateToolCallsToggle() {
    const model = document.getElementById('model-select')?.value;
    const toggle = document.getElementById('tool-calls-toggle');
    const statusSpan = document.getElementById('tool-calls-status');
    if (!model || !toggle) return;

    try {
        const resp = await fetch(`/chat/tool_calls_check/?model_name=${encodeURIComponent(model)}`);
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

async function updateToolCallToggle() {
    const model = document.getElementById('model-select')?.value;
    const toggle = document.getElementById('tool-call-toggle');
    const statusSpan = document.getElementById('tool-call-status');
    if (!model || !toggle) return;

    try {
        const resp = await fetch(`/chat/tool_call_check/?model_name=${encodeURIComponent(model)}`);
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
    // chatEl.scrollTop = chatEl.scrollHeight;
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

function showLoading() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) overlay.style.display = 'flex';
}
function hideLoading() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) overlay.style.display = 'none';
}