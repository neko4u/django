/* ==========================================================
   故障树前端逻辑 — 适配 Django
   基于 FastAPI 原版 app.js，修改 API 路由、权限、CSRF
   ========================================================== */

// ==================== 全局状态 ====================
const STATE = {
    isEditMode: false,
    currentDocId: null,
    currentDoc: null,
    nodes: [],
    edges: [],
    selectedNodeId: null,
    network: null,
};

// CSRF Token
function getCSRF() {
    const cookie = document.cookie.match(/csrftoken=([^;]+)/);
    return cookie ? cookie[1] : '';
}

// ==================== API 工具 ====================
function apiUrl(path) {
    return '/fault-tree/' + path.replace(/^\//, '');
}

async function apiGet(path) {
    const r = await fetch(apiUrl(path));
    if (!r.ok) throw new Error(r.statusText);
    return r.json();
}

async function apiPost(path, data) {
    const r = await fetch(apiUrl(path), {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRF(),
        },
        body: JSON.stringify(data),
    });
    if (!r.ok) {
        const e = await r.json().catch(() => ({}));
        throw new Error(e.detail || r.statusText);
    }
    return r.json();
}

async function apiPut(path, data) {
    const r = await fetch(apiUrl(path), {
        method: 'PUT',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRF(),
        },
        body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(r.statusText);
    return r.json();
}

async function apiDelete(path) {
    const r = await fetch(apiUrl(path), {
        method: 'DELETE',
        headers: { 'X-CSRFToken': getCSRF() },
    });
    if (!r.ok) throw new Error(r.statusText);
    return r.json();
}

// ==================== 权限检查 ====================
async function checkPermission() {
    try {
        const p = await apiGet('api/permission/');
        STATE.isEditMode = p.can_edit;
        updateModeUI();
    } catch (e) {
        STATE.isEditMode = false;
        updateModeUI();
    }
}

function updateModeUI() {
    const badge = document.getElementById('mode-badge');
    if (STATE.isEditMode) {
        badge.textContent = '编辑模式';
        badge.className = 'mode-badge edit';
        badge.onclick = toggleEditMode;
    } else {
        badge.textContent = '只读';
        badge.className = 'mode-badge view';
        badge.onclick = null;
    }
    // 显示/隐藏编辑专用元素
    document.querySelectorAll('.edit-only').forEach(el => {
        el.style.display = STATE.isEditMode ? '' : 'none';
    });
}

function toggleEditMode() {
    // 管理员可手动切换到查看模式
    STATE.isEditMode = !STATE.isEditMode;
    updateModeUI();
    if (STATE.currentDocId) loadGraph(STATE.currentDocId);
}

// ==================== 文档列表 ====================
async function loadDocList() {
    const list = document.getElementById('doc-list');
    try {
        const docs = await apiGet('api/docs/');
        if (docs.length === 0) {
            list.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-secondary)">暂无文档</div>';
            return;
        }
        list.innerHTML = docs.map(d => `
            <div class="ft-doc-item ${STATE.currentDocId === d.id ? 'active' : ''}" data-id="${d.id}">
                <span onclick="selectDoc(${d.id})">${escHtml(d.title)}</span>
            </div>
        `).join('');
    } catch (e) {
        list.innerHTML = '<div style="padding:20px;text-align:center;color:var(--danger)">加载失败</div>';
    }
}

function selectDoc(docId) {
    STATE.currentDocId = docId;
    loadDocList();
    loadGraph(docId);
}

// ==================== 图加载与渲染 ====================
async function loadGraph(docId) {
    try {
        const graph = await apiGet(`api/docs/${docId}/graph/`);
        STATE.currentDoc = graph.doc;
        STATE.nodes = graph.nodes;
        STATE.edges = graph.edges;
        renderGraph();
    } catch (e) {
        console.error('加载图失败', e);
    }
}

function renderGraph() {
    const container = document.getElementById('ft-network');
    if (!STATE.nodes.length) {
        container.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-secondary)">空文档，点击"+ 节点"添加</div>';
        return;
    }

    const hasPositions = STATE.nodes.some(n => n.pos_x !== 0 || n.pos_y !== 0);

    const nodesData = STATE.nodes.map(n => ({
        id: n.id,
        label: n.title,
        title: n.title,
        x: hasPositions ? n.pos_x : undefined,
        y: hasPositions ? n.pos_y : undefined,
    }));

    const edgesData = STATE.edges.map(e => ({
        id: e.id,
        from: e.source_node_id,
        to: e.target_node_id,
        label: e.label,
        arrows: 'to',
    }));

    const options = {
        nodes: {
            shape: 'box',
            margin: 10,
            widthConstraint: { minimum: 80, maximum: 220 },
            font: { size: 13, face: 'Segoe UI' },
            borderWidth: 2,
            color: {
                background: '#ffffff',
                border: '#d0d7e2',
                highlight: { background: '#e8f1fe', border: '#2b7de9' },
            },
        },
        edges: {
            font: { size: 11, face: 'Segoe UI' },
            color: { color: '#5f6b7a', highlight: '#2b7de9' },
            smooth: { type: 'cubicBezier', forceDirection: 'vertical', roundness: 0.5 },
        },
        physics: {
            stabilization: { iterations: 100 },
            solver: 'forceAtlas2Based',
        },
        interaction: {
            hover: true,
            dragNodes: true,
            dragView: true,
            zoomView: true,
            navigationButtons: true,
            keyboard: true,
        },
    };

    // 层级布局无位置时
    if (!hasPositions) {
        options.layout = { hierarchical: { direction: 'UD', sortMethod: 'directed' } };
        options.physics = false;
    }

    if (STATE.network) STATE.network.destroy();

    STATE.network = new vis.Network(container, { nodes: new vis.DataSet(nodesData), edges: new vis.DataSet(edgesData) }, options);

    // 事件绑定
    bindNetworkEvents();

    // 初始布局处理
    if (!hasPositions) {
        STATE.network.once('afterDrawing', () => {
            const positions = STATE.network.getPositions();
            STATE.network.setOptions({ layout: {}, physics: false });
            Object.entries(positions).forEach(([id, pos]) => {
                STATE.network.moveNode(id, pos.x, pos.y);
            });
            if (STATE.isEditMode) saveAllNodePositions();
        });
    } else {
        STATE.network.once('stabilized', () => {
            STATE.network.setOptions({ physics: false });
            if (STATE.isEditMode) saveAllNodePositions();
        });
    }

    // 自动选中根节点
    setTimeout(() => {
        const allIds = nodesData.map(n => n.id);
        const targets = new Set(edgesData.map(e => e.to));
        const roots = allIds.filter(id => !targets.has(id));
        if (roots.length > 0) selectNode(roots[0]);
    }, 500);
}

function bindNetworkEvents() {
    if (!STATE.network) return;

    STATE.network.on('click', (params) => {
        if (params.nodes.length > 0) {
            selectNode(params.nodes[0]);
        } else {
            STATE.selectedNodeId = null;
            updateDetailPanel();
        }
    });

    STATE.network.on('doubleClick', (params) => {
        if (params.nodes.length > 0 && STATE.isEditMode) {
            openEditNodeModal(params.nodes[0]);
        }
    });

    STATE.network.on('dragEnd', (params) => {
        if (params.nodes.length > 0 && STATE.isEditMode) {
            const pos = STATE.network.getPositions([params.nodes[0]]);
            const p = pos[params.nodes[0]];
            saveNodePosition(params.nodes[0], p.x, p.y);
        }
    });

    STATE.network.on('oncontext', (params) => {
        params.event.preventDefault();
        if (!STATE.isEditMode) return;
        const pointer = STATE.network.DOMtoCanvas({ x: params.event.offsetX, y: params.event.offsetY });
        if (params.nodes.length > 0) {
            showNodeContextMenu(params.nodes[0], pointer.x, pointer.y);
        } else if (params.edges.length > 0) {
            showEdgeContextMenu(params.edges[0], pointer.x, pointer.y);
        }
    });
}

// ==================== 节点位置保存 ====================
function saveNodePosition(nodeId, x, y) {
    apiPut(`api/nodes/${nodeId}/update/`, { pos_x: x, pos_y: y }).catch(() => {});
    const node = STATE.nodes.find(n => n.id === nodeId);
    if (node) { node.pos_x = x; node.pos_y = y; }
}

async function saveAllNodePositions() {
    const positions = STATE.network.getPositions();
    for (const nodeId of Object.keys(positions)) {
        const pos = positions[nodeId];
        const node = STATE.nodes.find(n => n.id == nodeId);
        if (node && (Math.abs(node.pos_x - pos.x) > 0.5 || Math.abs(node.pos_y - pos.y) > 0.5)) {
            await apiPut(`api/nodes/${nodeId}/update/`, { pos_x: pos.x, pos_y: pos.y }).catch(() => {});
            node.pos_x = pos.x;
            node.pos_y = pos.y;
        }
    }
}

// ==================== 节点选择与详情 ====================
function selectNode(nodeId) {
    STATE.selectedNodeId = nodeId;
    STATE.network.selectNodes([nodeId]);
    STATE.network.focus(nodeId, { scale: 1, animation: { duration: 400, easingFunction: 'easeInOutQuad' } });
    updateDetailPanel();
}

async function updateDetailPanel() {
    const body = document.getElementById('detail-body');
    if (!STATE.selectedNodeId) {
        body.innerHTML = '<p style="color:var(--text-secondary);text-align:center;margin-top:80px;">点击节点查看详情</p>';
        return;
    }

    const node = STATE.nodes.find(n => n.id == STATE.selectedNodeId);
    if (!node) return;

    const outEdges = STATE.edges.filter(e => e.source_node_id == STATE.selectedNodeId);

    let html = `<h2>${escHtml(node.title)}</h2>`;
    html += `<div class="ft-detail-meta">ID: ${node.id} | 出边: ${outEdges.length} | 更新: ${node.updated_at}</div>`;

    // 节点内容
    html += `<div class="ft-detail-content">${renderContent(node.content)}</div>`;

    // 出边（决策路径）
    if (outEdges.length > 0) {
        html += `<div class="ft-out-edges"><h4>下一步路径</h4>`;
        outEdges.forEach(e => {
            const target = STATE.nodes.find(n => n.id == e.target_node_id);
            html += `<div class="ft-out-edge" onclick="selectNode(${e.target_node_id})">
                <span class="edge-label">${escHtml(e.label || '→')}</span>
                <span>${escHtml(target ? target.title : '节点#' + e.target_node_id)}</span>
            </div>`;
        });
        html += '</div>';
    }

    // 批注
    if (STATE.isEditMode) {
        html += `<div class="ft-comments"><h4>批注</h4>`;
        html += `<div id="comments-list">加载中...</div>`;
        html += `<div class="ft-comment-form" style="margin-top:10px;">
            <textarea id="comment-input" placeholder="添加批注..."></textarea>
            <button onclick="submitComment()">提交</button>
        </div></div>`;
    }

    body.innerHTML = html;

    if (STATE.isEditMode) loadComments(STATE.selectedNodeId);
}

function renderContent(content) {
    if (!content) return '<p style="color:var(--text-secondary)">暂无内容</p>';
    // 处理 doc:// 和 node:// 协议
    let html = content;
    html = html.replace(/doc:\/\/(\d+)\/(\d+)/g, '<a href="#doc-$1-node-$2" onclick="loadGraph($1);setTimeout(()=>selectNode($2),600);return false">📄 链接文档</a>');
    html = html.replace(/node:\/\/(\d+)/g, '<a href="#" onclick="selectNode($1);return false">🔗 跳转节点 $1</a>');
    return html;
}

// ==================== 批注 ====================
async function loadComments(nodeId) {
    try {
        const comments = await apiGet(`api/comments/?node_id=${nodeId}`);
        const el = document.getElementById('comments-list');
        if (!comments.length) {
            el.innerHTML = '<p style="color:var(--text-secondary);font-size:0.85rem">暂无批注</p>';
            return;
        }
        el.innerHTML = comments.map(c => `
            <div class="ft-comment">
                <div class="ft-comment-author">${escHtml(c.author)}</div>
                <div>${escHtml(c.content)}</div>
                <div class="ft-comment-time">${c.created_at}</div>
            </div>
        `).join('');
    } catch (e) {
        document.getElementById('comments-list').innerHTML = '<p style="color:var(--danger)">加载失败</p>';
    }
}

async function submitComment() {
    const input = document.getElementById('comment-input');
    const content = input.value.trim();
    if (!content) return;
    try {
        await apiPost('api/comments/create/', { node_id: STATE.selectedNodeId, content: content });
        input.value = '';
        loadComments(STATE.selectedNodeId);
    } catch (e) {
        alert('提交失败: ' + e.message);
    }
}

// ==================== 建造节点 ====================
function openCreateNodeModal() {
    if (!STATE.currentDocId) { alert('请先选择一个文档'); return; }
    showModal('新建节点', `
        <label>标题</label><input type="text" id="node-title" placeholder="节点标题">
        <label>内容</label><div class="editor-toolbar">
            <button type="button" onclick="execCmd('bold')">B</button>
            <button type="button" onclick="execCmd('italic')">I</button>
            <button type="button" onclick="execCmd('underline')">U</button>
            <button type="button">|</button>
            <button type="button" onclick="execCmd('insertUnorderedList')">列表</button>
            <button type="button" onclick="execCmd('insertOrderedList')">编号</button>
            <button type="button" onclick="execCmd('formatBlock','<pre>')">代码</button>
            <button type="button" onclick="toggleSourceMode()">源码</button>
        </div>
        <div class="editor-rich" id="editor-rich" contenteditable="true"></div>
        <textarea class="editor-source" id="editor-source" style="display:none;"></textarea>
    `, async () => {
        const title = document.getElementById('node-title').value.trim();
        const rich = document.getElementById('editor-rich');
        const source = document.getElementById('editor-source');
        const content = source.style.display === 'none' ? rich.innerHTML : source.value;
        if (!title) { alert('请输入标题'); return; }
        try {
            await apiPost('api/nodes/create/', { doc_id: STATE.currentDocId, title: title, content: content, pos_x: Math.random() * 400, pos_y: Math.random() * 300 });
            closeModal();
            loadGraph(STATE.currentDocId);
        } catch (e) { alert('创建失败: ' + e.message); }
    });
}

function openEditNodeModal(nodeId) {
    const node = STATE.nodes.find(n => n.id == nodeId);
    if (!node) return;
    showModal('编辑节点', `
        <label>标题</label><input type="text" id="node-title" value="${escAttr(node.title)}">
        <label>内容</label><div class="editor-toolbar">
            <button type="button" onclick="execCmd('bold')">B</button>
            <button type="button" onclick="execCmd('italic')">I</button>
            <button type="button" onclick="execCmd('underline')">U</button>
            <button type="button">|</button>
            <button type="button" onclick="execCmd('insertUnorderedList')">列表</button>
            <button type="button" onclick="execCmd('insertOrderedList')">编号</button>
            <button type="button" onclick="execCmd('formatBlock','<pre>')">代码</button>
            <button type="button" onclick="toggleSourceMode()">源码</button>
        </div>
        <div class="editor-rich" id="editor-rich" contenteditable="true">${node.content || ''}</div>
        <textarea class="editor-source" id="editor-source" style="display:none;">${escHtml(node.content || '')}</textarea>
    `, async () => {
        const title = document.getElementById('node-title').value.trim();
        const rich = document.getElementById('editor-rich');
        const source = document.getElementById('editor-source');
        const content = source.style.display === 'none' ? rich.innerHTML : source.value;
        if (!title) { alert('请输入标题'); return; }
        try {
            await apiPut(`api/nodes/${nodeId}/update/`, { title: title, content: content });
            closeModal();
            loadGraph(STATE.currentDocId);
        } catch (e) { alert('更新失败: ' + e.message); }
    });
}

// ==================== 右键菜单 ====================
function showNodeContextMenu(nodeId, x, y) {
    const existing = document.getElementById('ctx-menu');
    if (existing) existing.remove();
    const node = STATE.nodes.find(n => n.id == nodeId);

    const menu = document.createElement('div');
    menu.id = 'ctx-menu';
    menu.style.cssText = `position:absolute;left:${x}px;top:${y}px;background:white;border:1px solid var(--border);border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,0.1);z-index:500;min-width:140px;padding:4px;font-size:0.85rem;`;
    menu.innerHTML = `
        <div style="padding:8px 12px;cursor:pointer;border-radius:4px;" onclick="openEditNodeModal(${nodeId});document.getElementById('ctx-menu').remove()">编辑</div>
        <div style="padding:8px 12px;cursor:pointer;border-radius:4px;color:var(--danger);" onclick="deleteNode(${nodeId});document.getElementById('ctx-menu').remove()">删除</div>
        <div style="padding:4px 12px;color:var(--text-secondary);font-size:0.75rem;">ID: ${nodeId} | ${escHtml(node ? node.title : '')}</div>
    `;
    document.getElementById('center-panel').appendChild(menu);

    const closeCtx = (e) => { if (!menu.contains(e.target)) { menu.remove(); document.removeEventListener('click', closeCtx); } };
    setTimeout(() => document.addEventListener('click', closeCtx), 0);
}

function showEdgeContextMenu(edgeId, x, y) {
    const existing = document.getElementById('ctx-menu');
    if (existing) existing.remove();

    const menu = document.createElement('div');
    menu.id = 'ctx-menu';
    menu.style.cssText = `position:absolute;left:${x}px;top:${y}px;background:white;border:1px solid var(--border);border-radius:8px;box-shadow:0 4px 16px rgba(0,0,0,0.1);z-index:500;min-width:140px;padding:4px;font-size:0.85rem;`;
    menu.innerHTML = `
        <div style="padding:8px 12px;cursor:pointer;border-radius:4px;" onclick="openEditEdgeModal(${edgeId});document.getElementById('ctx-menu').remove()">编辑标签</div>
        <div style="padding:8px 12px;cursor:pointer;border-radius:4px;color:var(--danger);" onclick="deleteEdge(${edgeId});document.getElementById('ctx-menu').remove()">删除连线</div>
    `;
    document.getElementById('center-panel').appendChild(menu);

    const closeCtx = (e) => { if (!menu.contains(e.target)) { menu.remove(); document.removeEventListener('click', closeCtx); } };
    setTimeout(() => document.addEventListener('click', closeCtx), 0);
}

// ==================== 节点/边 CRUD ====================
async function deleteNode(nodeId) {
    if (!confirm('确定删除此节点？相关连线也会被删除。')) return;
    try {
        await apiDelete(`api/nodes/${nodeId}/delete/`);
        if (STATE.selectedNodeId == nodeId) STATE.selectedNodeId = null;
        loadGraph(STATE.currentDocId);
    } catch (e) { alert('删除失败: ' + e.message); }
}

async function deleteEdge(edgeId) {
    if (!confirm('确定删除此连线？')) return;
    try {
        await apiDelete(`api/edges/${edgeId}/delete/`);
        loadGraph(STATE.currentDocId);
    } catch (e) { alert('删除失败: ' + e.message); }
}

function openEditEdgeModal(edgeId) {
    const edge = STATE.edges.find(e => e.id == edgeId);
    if (!edge) return;
    showModal('编辑连线标签', `
        <label>标签</label><input type="text" id="edge-label" value="${escAttr(edge.label || '')}" placeholder="如: 是/否/通过">
    `, async () => {
        const label = document.getElementById('edge-label').value.trim();
        try {
            await apiPut(`api/edges/${edgeId}/update/`, { label: label });
            closeModal();
            loadGraph(STATE.currentDocId);
        } catch (e) { alert('更新失败: ' + e.message); }
    });
}

function openCreateEdgeModal() {
    if (!STATE.currentDocId || STATE.nodes.length < 2) { alert('至少需要两个节点'); return; }
    const options = STATE.nodes.map(n => `<option value="${n.id}">[${n.id}] ${escHtml(n.title)}</option>`).join('');
    showModal('新建连线', `
        <label>源节点</label><select id="edge-source">${options}</select>
        <label>目标节点</label><select id="edge-target">${options}</select>
        <label>标签</label><input type="text" id="edge-label" placeholder="如: 是/否/下一步">
    `, async () => {
        const source = parseInt(document.getElementById('edge-source').value);
        const target = parseInt(document.getElementById('edge-target').value);
        const label = document.getElementById('edge-label').value.trim();
        if (source === target) { alert('源和目标不能相同'); return; }
        try {
            await apiPost('api/edges/create/', { doc_id: STATE.currentDocId, source_node_id: source, target_node_id: target, label: label });
            closeModal();
            loadGraph(STATE.currentDocId);
        } catch (e) { alert('创建失败: ' + e.message); }
    });
}

// ==================== 新建文档 ====================
function openCreateDocModal() {
    showModal('新建文档', `
        <label>标题</label><input type="text" id="doc-title" placeholder="文档标题">
        <label>描述</label><textarea id="doc-desc" placeholder="简述此故障树..."></textarea>
    `, async () => {
        const title = document.getElementById('doc-title').value.trim();
        const desc = document.getElementById('doc-desc').value.trim();
        if (!title) { alert('请输入标题'); return; }
        try {
            const doc = await apiPost('api/docs/create/', { title: title, description: desc });
            closeModal();
            loadDocList();
            selectDoc(doc.id);
        } catch (e) { alert('创建失败: ' + e.message); }
    });
}

// ==================== 自动布局 ====================
function autoLayout() {
    if (!STATE.network) return;
    STATE.network.setOptions({ layout: { hierarchical: { direction: 'UD', sortMethod: 'directed' } }, physics: false });
    setTimeout(() => {
        const positions = STATE.network.getPositions();
        STATE.network.setOptions({ layout: {} });
        Object.entries(positions).forEach(([id, pos]) => {
            STATE.network.moveNode(id, pos.x, pos.y);
        });
        STATE.network.fit({ animation: true });
        if (STATE.isEditMode) saveAllNodePositions();
    }, 600);
}

// ==================== 图内搜索 ====================
function setupGraphSearch() {
    const input = document.getElementById('graph-search');
    const results = document.getElementById('search-results');
    let searchIndex = -1;

    input.addEventListener('input', () => {
        const q = input.value.trim().toLowerCase();
        if (!q) { results.classList.remove('active'); return; }
        const matches = STATE.nodes.filter(n =>
            n.title.toLowerCase().includes(q) || (n.content && n.content.toLowerCase().includes(q))
        );
        if (matches.length === 0) {
            results.innerHTML = '<div class="search-item" style="color:var(--text-secondary)">无匹配结果</div>';
        } else {
            results.innerHTML = matches.map((m, i) =>
                `<div class="search-item" data-id="${m.id}" data-idx="${i}">[${m.id}] ${escHtml(m.title)}</div>`
            ).join('');
        }
        results.classList.add('active');
        searchIndex = -1;
    });

    input.addEventListener('keydown', (e) => {
        const items = results.querySelectorAll('.search-item[data-id]');
        if (!items.length) return;
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            searchIndex = Math.min(searchIndex + 1, items.length - 1);
            highlightSearchItem(items, searchIndex);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            searchIndex = Math.max(searchIndex - 1, 0);
            highlightSearchItem(items, searchIndex);
        } else if (e.key === 'Enter' && searchIndex >= 0) {
            selectNode(parseInt(items[searchIndex].dataset.id));
            results.classList.remove('active');
        }
    });

    results.addEventListener('click', (e) => {
        const item = e.target.closest('.search-item[data-id]');
        if (item) { selectNode(parseInt(item.dataset.id)); results.classList.remove('active'); input.value = ''; }
    });

    document.addEventListener('click', (e) => {
        if (!input.contains(e.target) && !results.contains(e.target)) results.classList.remove('active');
    });

    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            input.focus();
            input.select();
        }
    });
}

function highlightSearchItem(items, idx) {
    items.forEach((el, i) => el.classList.toggle('active', i === idx));
    items[idx].scrollIntoView({ block: 'nearest' });
}

// ==================== 模态框 ====================
let modalCallback = null;

function showModal(title, bodyHtml, onConfirm) {
    const overlay = document.getElementById('modal-overlay');
    const box = document.getElementById('modal-box');
    box.innerHTML = `
        <div class="modal-header"><h3>${title}</h3><button class="modal-close" onclick="closeModal()">✕</button></div>
        <div class="modal-body">${bodyHtml}</div>
        <div class="modal-footer">
            <button class="btn-secondary" onclick="closeModal()">取消</button>
            <button class="btn-primary" id="modal-confirm">确认</button>
        </div>
    `;
    overlay.style.display = 'flex';
    modalCallback = onConfirm;
    document.getElementById('modal-confirm').onclick = () => { if (modalCallback) modalCallback(); };
}

function closeModal() {
    document.getElementById('modal-overlay').style.display = 'none';
    modalCallback = null;
}

// ==================== 富文本编辑 ====================
window.execCmd = function(cmd, value) {
    document.execCommand(cmd, false, value || null);
};

window.toggleSourceMode = function() {
    const rich = document.getElementById('editor-rich');
    const source = document.getElementById('editor-source');
    if (source.style.display === 'none') {
        source.value = rich.innerHTML;
        source.style.display = '';
        rich.style.display = 'none';
    } else {
        rich.innerHTML = source.value;
        source.style.display = 'none';
        rich.style.display = '';
    }
};

// ==================== 面板拖拽 ====================
function setupResizeHandle() {
    const handle = document.getElementById('resize-handle');
    const rightPanel = document.getElementById('right-panel');
    let isDragging = false, startX, startWidth;

    handle.addEventListener('mousedown', (e) => {
        isDragging = true;
        startX = e.clientX;
        startWidth = rightPanel.offsetWidth;
        handle.classList.add('dragging');
        document.body.style.userSelect = 'none';
        document.body.style.cursor = 'col-resize';
    });

    document.addEventListener('mousemove', (e) => {
        if (!isDragging) return;
        const diff = startX - e.clientX;
        const newWidth = Math.min(600, Math.max(200, startWidth + diff));
        rightPanel.style.width = newWidth + 'px';
        localStorage.setItem('fault_tree_right_width', newWidth);
        if (STATE.network) STATE.network.redraw();
    });

    document.addEventListener('mouseup', () => {
        if (isDragging) {
            isDragging = false;
            handle.classList.remove('dragging');
            document.body.style.userSelect = '';
            document.body.style.cursor = '';
        }
    });

    const saved = localStorage.getItem('fault_tree_right_width');
    if (saved) rightPanel.style.width = saved + 'px';
}

// ==================== 界面切换 ====================
function setupPanelToggles() {
    document.getElementById('btn-toggle-left').onclick = () => {
        document.getElementById('left-panel').classList.toggle('collapsed');
        document.getElementById('left-panel').classList.toggle('open');
        setTimeout(() => { if (STATE.network) STATE.network.redraw(); }, 300);
    };

    document.getElementById('btn-toggle-right').onclick = () => {
        const panel = document.getElementById('right-panel');
        panel.classList.toggle('collapsed');
        if (!panel.classList.contains('collapsed')) panel.classList.add('open');
        else panel.classList.remove('open');
        setTimeout(() => { if (STATE.network) STATE.network.redraw(); }, 300);
    };

    document.getElementById('btn-close-right').onclick = () => {
        document.getElementById('right-panel').classList.add('collapsed');
        setTimeout(() => { if (STATE.network) STATE.network.redraw(); }, 300);
    };
}

// ==================== 图片上传（粘贴支持） ====================
function setupImagePaste() {
    document.addEventListener('paste', async (e) => {
        const rich = document.getElementById('editor-rich');
        if (!rich || document.activeElement !== rich) return;
        const items = e.clipboardData.items;
        for (const item of items) {
            if (item.type.startsWith('image/')) {
                e.preventDefault();
                const file = item.getAsFile();
                const formData = new FormData();
                formData.append('file', file);
                try {
                    const r = await fetch(apiUrl('api/upload/image/'), {
                        method: 'POST',
                        headers: { 'X-CSRFToken': getCSRF() },
                        body: formData,
                    });
                    const data = await r.json();
                    document.execCommand('insertImage', false, data.url);
                } catch (e) { console.error('上传失败', e); }
                break;
            }
        }
    });
}

// ==================== 工具函数 ====================
function escHtml(s) {
    const div = document.createElement('div');
    div.textContent = s;
    return div.innerHTML;
}

function escAttr(s) {
    return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// ==================== 搜索文档 ====================
function setupDocSearch() {
    const input = document.getElementById('doc-search');
    let timer;
    input.addEventListener('input', () => {
        clearTimeout(timer);
        timer = setTimeout(async () => {
            const q = input.value.trim();
            if (!q) { loadDocList(); return; }
            try {
                const docs = await apiGet(`api/docs/search/?q=${encodeURIComponent(q)}`);
                const list = document.getElementById('doc-list');
                if (docs.length === 0) {
                    list.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-secondary)">无匹配文档</div>';
                } else {
                    list.innerHTML = docs.map(d => `
                        <div class="ft-doc-item ${STATE.currentDocId === d.id ? 'active' : ''}" data-id="${d.id}">
                            <span onclick="selectDoc(${d.id})">${escHtml(d.title)}</span>
                        </div>
                    `).join('');
                }
            } catch (e) { console.error(e); }
        }, 300);
    });
}

// ==================== 按钮绑定 ====================
function bindButtons() {
    document.getElementById('btn-new-doc').onclick = openCreateDocModal;
    document.getElementById('btn-add-node').onclick = openCreateNodeModal;
    document.getElementById('btn-add-edge').onclick = openCreateEdgeModal;
    document.getElementById('btn-auto-layout').onclick = autoLayout;
    document.getElementById('btn-fit').onclick = () => { if (STATE.network) STATE.network.fit({ animation: true }); };
}

// ==================== 初始化 ====================
async function init() {
    bindButtons();
    setupGraphSearch();
    setupResizeHandle();
    setupPanelToggles();
    setupImagePaste();
    setupDocSearch();

    await checkPermission();

    await loadDocList();
    if (STATE.nodes.length === 0 && STATE.currentDocId === null) {
        // 尝试加载第一个文档
        const docs = await apiGet('api/docs/').catch(() => []);
        if (docs.length > 0) selectDoc(docs[0].id);
    }
}

document.addEventListener('DOMContentLoaded', init);
