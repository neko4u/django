/* apps/frpServer/static/frpServer/js/history_connection.js
 * 历史连接：连接事件流水的查询 / 渲染 / 分页
 *
 * 数据源：GET {data-api}?preset=|start=&end=  &page=&page_size=
 *   -> {code, msg, items[], total, page, page_size, pages, has_next, has_prev, range{start,end}}
 *
 * 设计要点：
 *   - 不依赖任何第三方库；
 *   - 接口地址从容器 div 的 data-api 取（避免模板标签写在 <script> 里）；
 *   - 用 IIFE + readyState 双重判断，规避「脚本执行时机」类问题；
 *   - 后端返回非 JSON（如 DEBUG 调试页）时给出人话提示，不把裸 HTML 抛给用户。
 */
(function () {
    'use strict';

    var root = document.getElementById('history-conn');
    if (!root) { return; }

    var API = root.getAttribute('data-api') || '';
    var PAGE_SIZES = [20, 50, 100];
    var PRESETS = [
        { key: 'today',     label: '今天' },
        { key: 'yesterday', label: '昨天' },
        { key: 'last3',     label: '近 3 天' },
        { key: 'last7',     label: '近 7 天' }
    ];

    var state = {
        preset: 'last7',
        start: '',
        end: '',
        page: 1,
        pageSize: 20,
        total: 0,
        pages: 1,
        loading: false,
        started: false
    };

    var el = {};

    function byId(id) { return document.getElementById(id); }

    // ------------------------------ 工具 ------------------------------

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function fmtDuration(sec) {
        sec = Math.max(0, parseInt(sec, 10) || 0);
        if (!sec) { return ''; }
        var d = Math.floor(sec / 86400),
            h = Math.floor((sec % 86400) / 3600),
            m = Math.floor((sec % 3600) / 60),
            s = sec % 60;
        if (d > 0) { return d + ' 天 ' + h + ' 时 ' + m + ' 分'; }
        if (h > 0) { return h + ' 时 ' + m + ' 分 ' + s + ' 秒'; }
        if (m > 0) { return m + ' 分 ' + s + ' 秒'; }
        return s + ' 秒';
    }

    function badgeClass(type) {
        if (type === 'CONNECT') { return 'hc-badge--connect'; }
        if (type === 'REUSE') { return 'hc-badge--reuse'; }
        return 'hc-badge--disconnect';
    }

    // ------------------------------ 状态层 ------------------------------

    function hideState() {
        el.state.className = 'hc-state';
        el.state.innerHTML = '';
    }

    function showState(html, isError) {
        el.state.className = 'hc-state is-show' + (isError ? ' is-error' : '');
        el.state.innerHTML = html;
    }

    function showSkeleton() {
        var rows = '';
        for (var i = 0; i < 5; i++) { rows += '<div class="hc-skeleton-row"></div>'; }
        el.state.className = 'hc-state is-show';
        el.state.innerHTML = '<div class="hc-skeleton">' + rows + '</div>';
    }

    function showEmpty() {
        showState('该时间段没有连接记录', false);
    }

    function showError(msg) {
        showState(esc(msg), true);
    }

    // ------------------------------ 渲染 ------------------------------

    function renderRows(items) {
        if (!items.length) { el.tbody.innerHTML = ''; return; }

        var html = '';
        for (var i = 0; i < items.length; i++) {
            var it = items[i];
            var ip = it.ip
                ? '<span class="hc-ip">' + esc(it.ip) + '</span>'
                : '<span class="hc-muted">—</span>';
            var dur = it.duration_seconds
                ? esc(fmtDuration(it.duration_seconds))
                : '<span class="hc-muted">—</span>';

            html += '<tr>'
                 +  '<td><span class="hc-badge ' + badgeClass(it.type) + '">'
                 +      esc(it.type_text || it.type) + '</span></td>'
                 +  '<td>' + esc(it.ts) + '</td>'
                 +  '<td>' + ip + '</td>'
                 +  '<td>' + esc(it.reason_text || it.reason || '') + '</td>'
                 +  '<td>' + dur + '</td>'
                 +  '</tr>';
        }
        el.tbody.innerHTML = html;
    }

    function pageNumbers(current, total) {
        var out = [], i;
        if (total <= 7) {
            for (i = 1; i <= total; i++) { out.push(i); }
            return out;
        }
        out.push(1);
        var s = Math.max(2, current - 1), e = Math.min(total - 1, current + 1);
        if (s > 2) { out.push('...'); }
        for (i = s; i <= e; i++) { out.push(i); }
        if (e < total - 1) { out.push('...'); }
        out.push(total);
        return out;
    }

    function renderPager() {
        var html = '';
        var total = state.pages || 1;
        var cur = state.page || 1;

        html += '<button type="button" class="hc-page-btn" data-page="' + (cur - 1) + '"'
             +  (cur <= 1 ? ' disabled' : '') + '>‹ 上一页</button>';

        var nums = pageNumbers(cur, total);
        for (var i = 0; i < nums.length; i++) {
            if (nums[i] === '...') {
                html += '<span class="hc-page-gap">…</span>';
            } else {
                html += '<button type="button" class="hc-page-btn'
                     +  (nums[i] === cur ? ' is-active' : '') + '" data-page="' + nums[i] + '">'
                     +  nums[i] + '</button>';
            }
        }

        html += '<button type="button" class="hc-page-btn" data-page="' + (cur + 1) + '"'
             +  (cur >= total ? ' disabled' : '') + '>下一页 ›</button>';

        el.pager.innerHTML = html;
    }

    // ------------------------------ 请求 ------------------------------

    function buildUrl() {
        var params = [];
        if (state.start && state.end) {
            params.push('start=' + encodeURIComponent(state.start));
            params.push('end=' + encodeURIComponent(state.end));
        } else {
            params.push('preset=' + encodeURIComponent(state.preset));
        }
        params.push('page=' + state.page);
        params.push('page_size=' + state.pageSize);
        return API + (API.indexOf('?') >= 0 ? '&' : '?') + params.join('&');
    }

    function setBusy(busy) {
        var btns = [el.query, el.reset, el.refresh];
        for (var i = 0; i < btns.length; i++) {
            if (btns[i]) { btns[i].disabled = !!busy; }
        }
    }

    function applyData(d) {
        state.total = d.total || 0;
        state.pages = d.pages || 1;
        state.page = d.page || 1;

        if (d.range && d.range.start && d.range.end) {
            el.rangeText.textContent = d.range.start + ' ~ ' + d.range.end;
        }

        var items = d.items || [];
        renderRows(items);

        if (items.length) { hideState(); } else { showEmpty(); }

        el.total.textContent = '共 ' + state.total + ' 条';
        renderPager();
    }

    function fetchData() {
        if (state.loading) { return; }
        state.loading = true;
        state.started = true;
        setBusy(true);
        showSkeleton();

        fetch(buildUrl(), {
            method: 'GET',
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        })
        .then(function (resp) {
            return resp.text().then(function (text) {
                var data = null;
                try { data = JSON.parse(text); } catch (e) { data = null; }
                return { status: resp.status, data: data };
            });
        })
        .then(function (r) {
            // 后端返回的不是 JSON（例如调试页 / 网关错误页）——只给用户人话
            if (!r.data) {
                showError('服务器返回异常（HTTP ' + r.status + '），请稍后重试');
                return;
            }
            if (r.data.code !== 0) {
                if (r.data.code === 401) {
                    showError('登录已过期，请重新登录');
                    return;
                }
                showError(r.data.msg || '查询失败，请稍后重试');
                return;
            }
            applyData(r.data);
        })
        .catch(function () {
            showError('网络错误，请检查网络后重试');
        })
        .then(function () {
            state.loading = false;
            setBusy(false);
        });
    }

    // ------------------------------ 交互 ------------------------------

    function syncPresetChips() {
        var chips = el.presets.querySelectorAll('.hc-chip');
        for (var i = 0; i < chips.length; i++) {
            var k = chips[i].getAttribute('data-preset');
            if (state.start || state.end) {
                chips[i].className = 'hc-chip';
            } else {
                chips[i].className = 'hc-chip' + (k === state.preset ? ' is-active' : '');
            }
        }
    }

    function buildPresets() {
        var html = '';
        for (var i = 0; i < PRESETS.length; i++) {
            html += '<button type="button" class="hc-chip" data-preset="'
                 +  PRESETS[i].key + '">' + PRESETS[i].label + '</button>';
        }
        el.presets.innerHTML = html;
        syncPresetChips();
    }

    function onPresetClick(e) {
        var t = e.target;
        if (!t || !t.getAttribute) { return; }
        var key = t.getAttribute('data-preset');
        if (!key) { return; }

        state.preset = key;
        state.start = '';
        state.end = '';
        state.page = 1;
        el.start.value = '';
        el.end.value = '';
        syncPresetChips();
        fetchData();
    }

    function onCustomQuery() {
        var s = (el.start.value || '').trim();
        var e = (el.end.value || '').trim();
        if (!s || !e) {
            showError('请先选择完整的开始日期和结束日期');
            return;
        }
        if (s > e) {
            var tmp = s; s = e; e = tmp;
            el.start.value = s;
            el.end.value = e;
        }
        state.start = s;
        state.end = e;
        state.page = 1;
        syncPresetChips();
        fetchData();
    }

    function onReset() {
        state.preset = 'last7';
        state.start = '';
        state.end = '';
        state.page = 1;
        el.start.value = '';
        el.end.value = '';
        syncPresetChips();
        fetchData();
    }

    function onPagerClick(e) {
        var t = e.target;
        if (!t || !t.getAttribute) { return; }
        var p = t.getAttribute('data-page');
        if (!p || t.disabled) { return; }
        p = parseInt(p, 10);
        if (!p || p === state.page || p < 1 || p > state.pages) { return; }
        state.page = p;
        fetchData();
    }

    function bind() {
        el.presets.addEventListener('click', onPresetClick);
        el.query.addEventListener('click', onCustomQuery);
        el.reset.addEventListener('click', onReset);
        el.refresh.addEventListener('click', fetchData);
        el.pager.addEventListener('click', onPagerClick);

        el.pageSize.addEventListener('change', function () {
            var v = parseInt(el.pageSize.value, 10);
            if (PAGE_SIZES.indexOf(v) < 0) { v = PAGE_SIZES[0]; }
            state.pageSize = v;
            state.page = 1;
            fetchData();
        });
    }

    // ------------------------------ 启动 ------------------------------

    function init() {
        el.presets   = byId('hc-presets');
        el.start     = byId('hc-start');
        el.end       = byId('hc-end');
        el.query     = byId('hc-query');
        el.reset     = byId('hc-reset');
        el.refresh   = byId('hc-refresh');
        el.rangeText = byId('hc-range-text');
        el.tbody     = byId('hc-tbody');
        el.state     = byId('hc-state');
        el.pager     = byId('hc-pager');
        el.pageSize  = byId('hc-page-size');
        el.total     = byId('hc-total');

        // 结构不完整就直接退出，避免半路报错影响整个页面
        if (!el.presets || !el.tbody || !el.state || !el.pager) { return; }

        el.pageSize.value = String(state.pageSize);
        buildPresets();
        bind();
        fetchData();          // 进页面即按「近 7 天」查一次
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
