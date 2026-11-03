/* apps/rag/static/rag/js/ask.js */
(function () {
    'use strict';

    var URLS = window.RAG_URLS || {};
    var $ = function (s, r) { return (r || document).querySelector(s); };

    var input = $('#w-input');
    var sendBtn = $('#w-send');
    var thread = $('#w-thread');
    var empty = $('#w-empty');
    var modeEl = $('#w-mode');

    var busy = false;

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function citeMarkup(text, citations) {
        if (!citations || !citations.length) return text;
        var valid = {};
        citations.forEach(function (c) { valid[c.index] = true; });
        return text.replace(/\[(\d{1,2})\]/g, function (m, n) {
            return valid[Number(n)] ? '<sup class="cite" data-n="' + n + '">[' + n + ']</sup>' : m;
        });
    }

    function renderStreaming(text, citations) {
        return '<p>' + citeMarkup(esc(text), citations).replace(/\n/g, '<br>') +
            '<span class="w-caret"></span></p>';
    }

    function renderFinal(text, citations) {
        var html;
        if (window.marked) {
            try {
                html = marked.parse(citeMarkup(text, citations), { breaks: true, gfm: true });
            } catch (e) { html = '<p>' + esc(text).replace(/\n/g, '<br>') + '</p>'; }
        } else {
            html = '<p>' + citeMarkup(esc(text), citations).replace(/\n/g, '<br>') + '</p>';
        }
        return html;
    }

    function scrollDown() {
        window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
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

    function renderCitations(ui, citations) {
        if (!citations || !citations.length) { ui.cites.style.display = 'none'; return; }
        ui.citeList.innerHTML = citations.map(function (c) {
            var img = c.image
                ? '<img src="' + esc(c.image) + '" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.display=\'none\'">'
                : '<div style="width:40px;height:40px;flex:0 0 40px;background:#f6f1e4;border-radius:6px"></div>';
            var path = (c.header_path || '').replace(/^[^>]*>\s*/, '');
            return '<a class="w-cite" id="w-cite-' + c.index + '" href="' + esc(c.wiki_url || '#') +
                '" target="_blank" rel="noopener" title="' + esc(c.snippet || '') + '">' +
                img +
                '<div class="w-cite-txt">' +
                '<div class="w-cite-idx">[' + c.index + ']</div>' +
                '<div class="w-cite-name">' + esc(c.title) + '</div>' +
                (path ? '<div class="w-cite-path">' + esc(path) + '</div>' : '') +
                '</div></a>';
        }).join('');
        ui.cites.style.display = '';
    }

    function bindCiteClick(ui) {
        ui.body.addEventListener('click', function (e) {
            var sup = e.target.closest && e.target.closest('sup.cite');
            if (!sup) return;
            var el = document.getElementById('w-cite-' + sup.dataset.n);
            if (!el) return;
            el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            el.style.borderColor = '#6aa35b';
            el.style.boxShadow = '0 0 0 3px rgba(106,163,91,.25)';
            setTimeout(function () { el.style.borderColor = ''; el.style.boxShadow = ''; }, 1400);
        });
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
            var v = Number(btn.dataset.v);
            fetch(URLS.feedback, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ log_id: logId, value: v })
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

    async function ask(question) {
        if (busy || !question.trim()) return;
        busy = true;
        setSend(false);
        if (empty) empty.style.display = 'none';

        addQuestion(question);
        var ui = addAnswer();
        bindCiteClick(ui);

        var answer = '';
        var citations = [];
        var logId = 0;
        var started = false;
        var stats = null;

        function handle(ev) {
            if (ev.type === 'meta') {
                citations = ev.citations || [];
                renderCitations(ui, citations);
                if (ev.mode && modeEl) modeEl.textContent = ev.mode === 'hybrid' ? '向量+关键词' : '关键词检索';
                ui.meta.innerHTML = '<span class="w-badge">命中 ' + (ev.hit_count || 0) + ' 条资料</span>';
            } else if (ev.type === 'delta') {
                if (!started) { started = true; ui.body.innerHTML = ''; }
                answer += ev.text || '';
                ui.body.innerHTML = renderStreaming(answer, citations);
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
                        try { handle(JSON.parse(raw)); } catch (e) { /* 忽略半包 */ }
                    }
                }
            }
        } catch (e) {
            ui.body.insertAdjacentHTML('beforeend',
                '<div class="w-err">请求失败：' + esc(e.message || e) + '</div>');
        } finally {
            if (answer) ui.body.innerHTML = renderFinal(answer, citations);
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

    /* ---------------- 事件绑定 ---------------- */
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

    [].forEach.call(document.querySelectorAll('.w-sample'), function (btn) {
        btn.addEventListener('click', function () { ask(btn.dataset.q); });
    });

    input.focus();
})();
