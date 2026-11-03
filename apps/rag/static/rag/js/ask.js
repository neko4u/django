/* apps/rag/static/rag/js/ask.js
   - 引用角标 [n] 改为 hover 浮层（14px 安全区），点击打开右侧资料抽屉
   - 不再直接跳外站（zh.stardewvalleywiki.com 后端故障会 503）
   - 引用数据按「轮次」隔离，修掉多轮对话里点最新一轮 [2] 却跳回上面那轮的问题
*/
(function () {
    'use strict';

    var URLS = window.RAG_URLS || {};
    var $ = function (s, r) { return (r || document).querySelector(s); };

    var input       = $('#w-input');
    var sendBtn     = $('#w-send');
    var thread      = $('#w-thread');
    var threadWrap  = $('#w-thread-wrap');
    var empty       = $('#w-empty');
    var modeEl      = $('#w-mode');

    var pop         = $('#w-pop');
    var drawer      = $('#w-drawer');
    var mask        = $('#w-mask');
    var dTitle      = $('#w-drawer-title');
    var dPath       = $('#w-drawer-path');
    var dBody       = $('#w-drawer-body');
    var dFoot       = $('#w-drawer-foot');

    var TURNS = {};          // turnId -> citations[]
    var turnSeq = 0;
    var busy = false;

    var POP_PAD = 14;        // 安全区：指针离角标或浮层 14px 以内都算「还在看」
    var popOpen = false, popTimer = null, popAnchor = null;

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    /* ================= 引用标记 ================= */
    function citeMarkup(text, citations, turnId) {
        if (!citations || !citations.length) return text;
        var valid = {};
        citations.forEach(function (c) { valid[c.index] = true; });
        return text.replace(/\[(\d{1,2})\]/g, function (m, n) {
            if (!valid[Number(n)]) return m;
            return '<sup class="cite" data-turn="' + turnId + '" data-n="' + n +
                '" tabindex="0" role="button" aria-label="查看来源 ' + n + '">' + n + '</sup>';
        });
    }

    function renderStreaming(text, citations, turnId) {
        return '<p>' + citeMarkup(esc(text), citations, turnId).replace(/\n/g, '<br>') +
            '<span class="w-caret"></span></p>';
    }

    function renderFinal(text, citations, turnId) {
        if (window.marked) {
            try {
                return marked.parse(citeMarkup(text, citations, turnId), { breaks: true, gfm: true });
            } catch (e) { /* 落到下面 */ }
        }
        return '<p>' + citeMarkup(esc(text), citations, turnId).replace(/\n/g, '<br>') + '</p>';
    }

    function citeOf(turn, n) {
        var list = TURNS[turn] || [];
        for (var i = 0; i < list.length; i++) {
            if (list[i].index === Number(n)) return list[i];
        }
        return null;
    }

    /* ================= 引用浮层 ================= */
    function popHtml(c) {
        var img = c.image
            ? '<img src="' + esc(c.image) + '" alt="" referrerpolicy="no-referrer" ' +
              'onerror="this.outerHTML=\'<div class=&quot;pop-ph&quot;></div>\'">'
            : '<div class="pop-ph"></div>';
        var path = (c.header_path || '').replace(/^[^>]*>\s*/, '');
        return '<div class="pop-head">' + img +
            '<div class="pop-main"><div class="pop-title">' + esc(c.title) + '</div>' +
            (path ? '<div class="pop-path">' + esc(path) + '</div>' : '') +
            '</div></div>' +
            '<div class="pop-snip">' + esc(c.snippet || '') + '</div>' +
            '<div class="pop-foot"><span>查看完整资料 →</span><span>[' + c.index + ']</span></div>';
    }

    function placePop(rect) {
        pop.style.visibility = 'hidden';
        pop.hidden = false;
        var pw = pop.offsetWidth, ph = pop.offsetHeight;
        var left = rect.left + rect.width / 2 - pw / 2;
        left = Math.max(12, Math.min(left, window.innerWidth - pw - 12));
        var top = rect.top - ph - 10;
        if (top < 12) top = rect.bottom + 10;
        pop.style.left = left + 'px';
        pop.style.top = top + 'px';
        pop.style.visibility = '';
    }

    function clearHide() {
        if (popTimer) { clearTimeout(popTimer); popTimer = null; }
    }

    function scheduleHide() {
        if (popTimer) return;
        popTimer = setTimeout(function () { popTimer = null; hidePop(); }, 170);
    }

    function showPop(sup) {
        var c = citeOf(sup.getAttribute('data-turn'), sup.getAttribute('data-n'));
        if (!c) return;
        clearHide();
        if (popAnchor && popAnchor !== sup) popAnchor.classList.remove('on');
        popAnchor = sup;
        sup.classList.add('on');
        pop.innerHTML = popHtml(c);
        pop.setAttribute('data-turn', sup.getAttribute('data-turn'));
        pop.setAttribute('data-n', sup.getAttribute('data-n'));
        placePop(sup.getBoundingClientRect());
        popOpen = true;
    }

    function hidePop() {
        if (!popOpen) return;
        popOpen = false;
        pop.hidden = true;
        if (popAnchor) popAnchor.classList.remove('on');
        popAnchor = null;
    }

    function inRect(x, y, r, pad) {
        return x >= r.left - pad && x <= r.right + pad &&
               y >= r.top - pad && y <= r.bottom + pad;
    }

    /* 指针在角标 / 浮层周围 14px 内都保持打开 —— 移动过程中不会闪掉 */
    document.addEventListener('mousemove', function (e) {
        if (!popOpen) return;
        var keep = false;
        if (popAnchor && inRect(e.clientX, e.clientY, popAnchor.getBoundingClientRect(), POP_PAD)) keep = true;
        else if (!pop.hidden && inRect(e.clientX, e.clientY, pop.getBoundingClientRect(), POP_PAD)) keep = true;
        if (keep) clearHide();
        else scheduleHide();
    });

    pop.addEventListener('mouseenter', clearHide);
    pop.addEventListener('mouseleave', scheduleHide);

    thread.addEventListener('mouseover', function (e) {
        var sup = e.target.closest && e.target.closest('sup.cite');
        if (sup) showPop(sup);
    });
    thread.addEventListener('focusin', function (e) {
        var sup = e.target.closest && e.target.closest('sup.cite');
        if (sup) showPop(sup);
    });

    /* ================= 资料抽屉 ================= */
    function openDrawer(c) {
        if (!c) return;
        hidePop();
        var path = (c.header_path || '').replace(/^[^>]*>\s*/, '');
        dTitle.textContent = c.title || '';
        dPath.textContent = path;

        var imgs = (c.images && c.images.length) ? c.images : (c.image ? [c.image] : []);
        var html = '';
        if (imgs.length) {
            html += '<div class="d-imgs">' + imgs.slice(0, 6).map(function (u) {
                return '<img src="' + esc(u) + '" alt="" referrerpolicy="no-referrer" loading="lazy" ' +
                       'onerror="this.style.display=\'none\'">';
            }).join('') + '</div>';
        }
        html += '<div>' + esc(c.content || c.snippet || '') + '</div>';
        dBody.innerHTML = html;
        dBody.scrollTop = 0;

        dFoot.innerHTML = '<span>资料 [' + c.index + ']' + (c.type ? ' · ' + esc(c.type) : '') + '</span>' +
            (c.wiki_url ? '<a href="' + esc(c.wiki_url) + '" target="_blank" rel="noopener">在原站查看 ↗</a>' : '');

        drawer.hidden = false;
        mask.hidden = false;
    }

    function closeDrawer() {
        drawer.hidden = true;
        mask.hidden = true;
    }

    mask.addEventListener('click', closeDrawer);
    $('#w-drawer-x').addEventListener('click', closeDrawer);

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') { closeDrawer(); hidePop(); }
    });

    /* 点击角标 / 浮层 / 来源卡片 → 打开抽屉（不再跳外站） */
    thread.addEventListener('click', function (e) {
        var t = e.target;
        var sup = t.closest && t.closest('sup.cite');
        if (sup) {
            openDrawer(citeOf(sup.getAttribute('data-turn'), sup.getAttribute('data-n')));
            return;
        }
        var card = t.closest && t.closest('.w-cite');
        if (card) {
            openDrawer(citeOf(card.getAttribute('data-turn'), card.getAttribute('data-n')));
        }
    });
    thread.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter' && e.key !== ' ') return;
        var sup = e.target.closest && e.target.closest('sup.cite');
        if (!sup) return;
        e.preventDefault();
        openDrawer(citeOf(sup.getAttribute('data-turn'), sup.getAttribute('data-n')));
    });
    pop.addEventListener('click', function () {
        openDrawer(citeOf(pop.getAttribute('data-turn'), pop.getAttribute('data-n')));
    });

    /* ================= 渲染 ================= */
    function scrollDown() {
        if (threadWrap) threadWrap.scrollTop = threadWrap.scrollHeight;
    }

    function addQuestion(q) {
        var div = document.createElement('div');
        div.className = 'w-q';
        div.textContent = q;
        thread.appendChild(div);
        scrollDown();
    }

    function addAnswer() {
        var wrap = document.createElement('div');
        wrap.className = 'w-a';
        wrap.innerHTML =
            '<div class="w-a-meta"></div>' +
            '<div class="w-body"><div class="w-skel"><span></span><span></span><span></span></div></div>' +
            '<div class="w-cites" style="display:none"><div class="w-cites-title">信息来源</div>' +
            '<div class="w-cite-list"></div></div>' +
            '<div class="w-actions" style="display:none"></div>';
        thread.appendChild(wrap);
        scrollDown();
        return {
            root: wrap,
            meta: $('.w-a-meta', wrap),
            body: $('.w-body', wrap),
            cites: $('.w-cites', wrap),
            citeList: $('.w-cite-list', wrap),
            actions: $('.w-actions', wrap)
        };
    }

    function renderCitations(ui, citations, turnId) {
        if (!citations || !citations.length) { ui.cites.style.display = 'none'; return; }
        ui.citeList.innerHTML = citations.map(function (c) {
            var img = c.image
                ? '<img src="' + esc(c.image) + '" alt="" loading="lazy" referrerpolicy="no-referrer" ' +
                  'onerror="this.style.display=\'none\'">'
                : '<div class="w-cite-ph"></div>';
            var path = (c.header_path || '').replace(/^[^>]*>\s*/, '');
            return '<div class="w-cite" data-turn="' + turnId + '" data-n="' + c.index + '" ' +
                'role="button" tabindex="0" title="' + esc(c.snippet || '') + '">' +
                img + '<div class="w-cite-txt">' +
                '<div class="w-cite-idx">[' + c.index + ']</div>' +
                '<div class="w-cite-name">' + esc(c.title) + '</div>' +
                (path ? '<div class="w-cite-path">' + esc(path) + '</div>' : '') +
                '</div></div>';
        }).join('');
        ui.cites.style.display = '';
    }

    function showActions(ui, logId, stats) {
        if (!logId) return;
        ui.actions.style.display = '';
        ui.actions.innerHTML =
            '<button class="w-act" data-v="1">👍 有用</button>' +
            '<button class="w-act" data-v="-1">👎 没用</button>' +
            '<span>' + (stats ? '首字 ' + stats.first + 'ms · 总 ' + stats.total + 'ms' : '') + '</span>';

        ui.actions.addEventListener('click', function (e) {
            var btn = e.target.closest && e.target.closest('.w-act');
            if (!btn) return;
            fetch(URLS.feedback, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ log_id: logId, value: Number(btn.dataset.v) })
            }).then(function (r) { return r.json(); }).then(function (j) {
                if (j.status === 'ok') {
                    [].forEach.call(ui.actions.querySelectorAll('.w-act'), function (b) { b.classList.remove('on'); });
                    btn.classList.add('on');
                }
            }).catch(function () {});
        });
    }

    function setSend(enabled) {
        sendBtn.disabled = !enabled;
        sendBtn.textContent = enabled ? '发送' : '思考中…';
    }

    /* ================= 提问 ================= */
    async function ask(question) {
        if (busy || !question.trim()) return;
        busy = true;
        setSend(false);
        if (empty) empty.style.display = 'none';

        var turnId = 't' + (++turnSeq);
        TURNS[turnId] = [];

        addQuestion(question);
        var ui = addAnswer();

        var answer = '';
        var citations = [];
        var logId = 0;
        var started = false;
        var stats = null;

        function handle(ev) {
            if (ev.type === 'meta') {
                citations = ev.citations || [];
                TURNS[turnId] = citations;
                renderCitations(ui, citations, turnId);
                if (ev.mode && modeEl) modeEl.textContent = ev.mode === 'hybrid' ? '向量+关键词' : '关键词检索';
                ui.meta.innerHTML = '<span class="t-badge">命中 ' + (ev.hit_count || 0) + ' 条资料</span>';
            } else if (ev.type === 'delta') {
                if (!started) { started = true; ui.body.innerHTML = ''; }
                answer += ev.text || '';
                ui.body.innerHTML = renderStreaming(answer, citations, turnId);
                scrollDown();
            } else if (ev.type === 'error') {
                ui.body.insertAdjacentHTML('beforeend',
                    '<div class="w-err">' + esc(ev.message || '生成失败') + '</div>');
            } else if (ev.type === 'done') {
                logId = ev.log_id || 0;
                stats = { first: ev.first_token_ms || 0, total: ev.latency_ms || 0 };
            }
        }

        try {
            var resp = await fetch(URLS.ask, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ question: question })
            });

            if (!resp.ok) {
                var msg = 'HTTP ' + resp.status;
                try { var j = await resp.json(); msg = j.message || msg; } catch (e) {}
                throw new Error(msg);
            }

            var reader = resp.body.getReader();
            var decoder = new TextDecoder('utf-8');
            var buf = '';

            while (true) {
                var chunk = await reader.read();
                if (chunk.done) break;
                buf += decoder.decode(chunk.value, { stream: true });

                var idx;
                while ((idx = buf.indexOf('\n\n')) >= 0) {
                    var frame = buf.slice(0, idx);
                    buf = buf.slice(idx + 2);
                    var lines = frame.split('\n');
                    for (var i = 0; i < lines.length; i++) {
                        var line = lines[i];
                        if (line.indexOf('data:') !== 0) continue;
                        var raw = line.slice(5).trim();
                        if (!raw) continue;
                        try { handle(JSON.parse(raw)); } catch (e) { /* 半包，等下一帧 */ }
                    }
                }
            }
        } catch (e) {
            ui.body.insertAdjacentHTML('beforeend',
                '<div class="w-err">请求失败：' + esc(e.message || e) + '</div>');
        } finally {
            if (answer) ui.body.innerHTML = renderFinal(answer, citations, turnId);
            else if (!ui.body.querySelector('.w-err')) {
                ui.body.innerHTML = '<div class="w-err">没有收到任何内容</div>';
            }
            if (stats) ui.meta.innerHTML += '<span>首字 ' + stats.first + 'ms · 总 ' + stats.total + 'ms</span>';
            showActions(ui, logId, stats);
            busy = false;
            setSend(true);
            scrollDown();
        }
    }

    /* ================= 交互绑定 ================= */
    sendBtn.addEventListener('click', function () {
        var q = input.value.trim();
        if (!q) return;
        input.value = '';
        input.style.height = 'auto';
        ask(q);
    });

    input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
            e.preventDefault();
            sendBtn.click();
        }
    });

    input.addEventListener('input', function () {
        this.style.height = 'auto';
        this.style.height = Math.min(this.scrollHeight, 140) + 'px';
    });

    [].forEach.call(document.querySelectorAll('.sample'), function (btn) {
        btn.addEventListener('click', function () { ask(btn.getAttribute('data-q')); });
    });

    var newBtn = $('#w-new');
    if (newBtn) {
        newBtn.addEventListener('click', function () {
            thread.innerHTML = '';
            TURNS = {};
            closeDrawer();
            hidePop();
            if (empty) empty.style.display = '';
            input.focus();
        });
    }

    var foldBtn = $('#w-toggle-side');
    if (foldBtn) {
        foldBtn.addEventListener('click', function () {
            $('#w-sidebar').classList.toggle('collapsed');
        });
    }

    input.focus();
})();
