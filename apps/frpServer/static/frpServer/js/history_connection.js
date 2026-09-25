/* apps/frpServer/static/frpServer/js/history_connection.js
 * 历史连接：连接事件流水的查询 / 渲染 / 分页 + 自定义日期区间选择器
 *
 * 数据源：GET {data-api}?preset=|start=&end=  &page=&page_size=
 *   -> {code, msg, items[], total, page, page_size, pages, has_next, has_prev, range{start,end}}
 *
 * 设计要点：
 *   - 不依赖任何第三方库；
 *   - 接口地址从容器 div 的 data-api 取（避免模板标签写在 <script> 里）；
 *   - 用 IIFE + readyState 双重判断，规避「脚本执行时机」类问题；
 *   - 后端返回非 JSON（如 DEBUG 调试页）时给出人话提示，不把裸 HTML 抛给用户；
 *   - 日期区间用自绘日历（单框 + 两次点击选区间 + 悬停预览高亮），
 *     预设与自定义互斥：点预设 -> 取消自定义；在日历里选完 -> 取消预设高亮。
 *   - 「查询」按钮任何时候都可用：预设就在预设里查，自定义就在区间里查，不弹错误。
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

    // 查询状态
    var state = {
        mode: 'preset',      // 'preset' | 'custom'
        preset: 'last7',
        start: '',           // YYYY-MM-DD，始终与当前生效的范围保持一致（供日历回显）
        end: '',
        page: 1,
        pageSize: 20,
        total: 0,
        pages: 1,
        loading: false
    };

    // 日历面板内部状态
    var pick = {
        open: false,
        y: 0,
        m: 0,                // 0-11
        picking: false,      // 已点第一次、正在等第二次
        anchor: '',          // 第一次点击的日期
        hover: ''            // 鼠标当前悬停日期（用于预览高亮）
    };

    var el = {};

    function byId(id) { return document.getElementById(id); }

    // ============================== 日期工具 ==============================

    function pad2(n) { return n < 10 ? '0' + n : '' + n; }

    function toYmd(d) {
        return d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
    }

    function parseYmd(v) {
        var p = String(v || '').split('-');
        if (p.length !== 3) { return null; }
        var y = parseInt(p[0], 10), m = parseInt(p[1], 10), dd = parseInt(p[2], 10);
        if (!y || !m || !dd) { return null; }
        var d = new Date(y, m - 1, dd);
        if (d.getFullYear() !== y || d.getMonth() !== m - 1 || d.getDate() !== dd) { return null; }
        return d;
    }

    function addDays(d, n) {
        var x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
        x.setDate(x.getDate() + n);
        return x;
    }

    function todayLocal() {
        var n = new Date();
        return new Date(n.getFullYear(), n.getMonth(), n.getDate());
    }

    // 'YYYY-MM-DD' 字典序即时间序，可直接比较
    function ymdCmp(a, b) { return a < b ? -1 : (a > b ? 1 : 0); }

    /** 预设 -> [start, end]，按浏览器本地日期换算；服务端返回后会再校准一次 */
    function presetRange(key) {
        var t = todayLocal();
        if (key === 'today') { return [toYmd(t), toYmd(t)]; }
        if (key === 'yesterday') { var y = addDays(t, -1); return [toYmd(y), toYmd(y)]; }
        if (key === 'last3') { return [toYmd(addDays(t, -2)), toYmd(t)]; }
        return [toYmd(addDays(t, -6)), toYmd(t)];     // last7 / 缺省
    }

    // ============================== 通用工具 ==============================

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

    // ============================== 状态层 ==============================

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

    function showEmpty() { showState('该时间段没有连接记录', false); }

    function showError(msg) { showState(esc(msg), true); }

    // ============================== 表格渲染 ==============================

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

    // ============================== 日历渲染 ==============================

    function renderCalendar() {
        var y = pick.y, m = pick.m;

        el.dpMonth.textContent = y + ' 年 ' + (m + 1) + ' 月';

        var first = new Date(y, m, 1);
        var gridStart = addDays(first, -first.getDay());   // 从周日开始铺 6 行
        var todayStr = toYmd(todayLocal());

        // 高亮范围：挑选中 -> anchor~hover（悬停预览）；否则 -> 已生效的区间
        var lo = '', hi = '';
        if (pick.picking && pick.anchor) {
            var a = pick.anchor;
            var h = pick.hover || pick.anchor;
            lo = ymdCmp(a, h) <= 0 ? a : h;
            hi = ymdCmp(a, h) <= 0 ? h : a;
        } else if (state.start && state.end) {
            lo = state.start;
            hi = state.end;
        }

        var html = '';
        for (var r = 0; r < 6; r++) {
            html += '<div class="hc-dp-row">';
            for (var c = 0; c < 7; c++) {
                var d = addDays(gridStart, r * 7 + c);
                var ymd = toYmd(d);
                var inMonth = (d.getMonth() === m);
                var cls = 'hc-dp-cell';

                if (!inMonth) {
                    cls += ' hc-dp-cell--muted';
                } else {
                    if (lo && ymdCmp(ymd, lo) >= 0 && ymdCmp(ymd, hi) <= 0) {
                        cls += ' hc-dp-cell--in';
                        if (ymd === lo) { cls += ' hc-dp-cell--start'; }
                        if (ymd === hi) { cls += ' hc-dp-cell--end'; }
                    }
                    if (ymd === todayStr) { cls += ' hc-dp-cell--today'; }
                }

                html += '<div class="' + cls + '" data-date="' + ymd + '">'
                     +  '<span class="hc-dp-day">' + d.getDate() + '</span></div>';
            }
            html += '</div>';
        }
        el.dpGrid.innerHTML = html;

        // 底部提示
        if (pick.picking && pick.anchor) {
            el.dpHint.textContent = '已选 ' + pick.anchor + '，请点击结束日期';
        } else if (state.start && state.end) {
            el.dpHint.textContent = '当前范围 ' + state.start + ' ~ ' + state.end;
        } else {
            el.dpHint.textContent = '请点击选择开始日期';
        }
    }

    function openPanel() {
        var base = parseYmd(state.end) || parseYmd(state.start) || todayLocal();
        pick.y = base.getFullYear();
        pick.m = base.getMonth();
        pick.picking = false;
        pick.anchor = '';
        pick.hover = '';
        el.dpPanel.classList.add('is-open');
        el.dpTrigger.setAttribute('aria-expanded', 'true');
        pick.open = true;
        renderCalendar();
    }

    function closePanel() {
        el.dpPanel.classList.remove('is-open');
        el.dpTrigger.setAttribute('aria-expanded', 'false');
        pick.open = false;
        pick.picking = false;
        pick.anchor = '';
        pick.hover = '';
    }

    function togglePanel() {
        if (pick.open) { closePanel(); } else { openPanel(); }
    }

    // ============================== 条件展示 ==============================

    /** 预设 chip 高亮；自定义时全部取消高亮 */
    function syncChips() {
        var chips = el.presets.querySelectorAll('.hc-chip');
        for (var i = 0; i < chips.length; i++) {
            var k = chips[i].getAttribute('data-preset');
            var on = (state.mode === 'preset' && k === state.preset);
            chips[i].className = 'hc-chip' + (on ? ' is-active' : '');
        }
    }

    /** 单框里的文案 = 当前生效的日期区间 */
    function syncRangeDisplay() {
        if (state.start && state.end) {
            el.dpText.textContent = state.start + ' ~ ' + state.end;
            el.dpText.className = 'hc-dp-text';
        } else {
            el.dpText.textContent = '选择日期区间';
            el.dpText.className = 'hc-dp-text is-placeholder';
        }
    }

    // ============================== 请求 ==============================

    function buildUrl() {
        var params = [];
        if (state.mode === 'custom' && state.start && state.end) {
            params.push('start=' + encodeURIComponent(state.start));
            params.push('end=' + encodeURIComponent(state.end));
        } else {
            params.push('preset=' + encodeURIComponent(state.preset || 'last7'));
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

        // 以服务端返回的区间为准（预设由服务端按服务器日期换算，避免本地时钟偏差）
        // 正在点选区间时不要打断用户操作
        if (d.range && d.range.start && d.range.end && !pick.picking) {
            state.start = d.range.start;
            state.end = d.range.end;
            syncRangeDisplay();
            if (pick.open) { renderCalendar(); }
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

    // ============================== 交互：预设 ==============================

    function buildPresets() {
        var html = '';
        for (var i = 0; i < PRESETS.length; i++) {
            html += '<button type="button" class="hc-chip" data-preset="'
                 +  PRESETS[i].key + '">' + PRESETS[i].label + '</button>';
        }
        el.presets.innerHTML = html;
    }

    function applyPreset(key, doQuery) {
        state.mode = 'preset';
        state.preset = key;
        var r = presetRange(key);
        state.start = r[0];
        state.end = r[1];
        state.page = 1;

        closePanel();
        syncChips();
        syncRangeDisplay();

        if (doQuery) { fetchData(); }
    }

    function onPresetClick(e) {
        var t = e.target;
        if (!t || !t.getAttribute) { return; }
        var key = t.getAttribute('data-preset');
        if (!key) { return; }
        applyPreset(key, true);
    }

    // ============================== 交互：日期区间 ==============================

    /** 从事件目标向上找到日历单元格（不用 closest，兼容性更稳） */
    function cellFrom(e) {
        var t = e.target;
        while (t && t !== el.dpGrid) {
            if (t.classList && t.classList.contains('hc-dp-cell')) { return t; }
            t = t.parentNode;
        }
        return null;
    }

    function onGridClick(e) {
        var cell = cellFrom(e);
        if (!cell) { return; }
        if (cell.classList.contains('hc-dp-cell--muted')) { return; }   // 相邻月份不可点

        var ymd = cell.getAttribute('data-date');
        if (!ymd) { return; }

        if (!pick.picking) {
            // 第一次点击：定起点，进入「等第二次」状态
            pick.picking = true;
            pick.anchor = ymd;
            pick.hover = ymd;
            renderCalendar();
            return;
        }

        // 第二次点击：定终点，完成选择并收起面板
        var a = pick.anchor, b = ymd;
        if (ymdCmp(a, b) > 0) { var tmp = a; a = b; b = tmp; }

        pick.picking = false;
        pick.anchor = '';
        pick.hover = '';

        state.mode = 'custom';
        state.start = a;
        state.end = b;
        state.page = 1;

        syncChips();           // 取消预设高亮
        syncRangeDisplay();
        closePanel();
        // 注意：这里不自动查询 —— 由用户点「查询」按钮触发
    }

    function onGridOver(e) {
        if (!pick.picking) { return; }
        var cell = cellFrom(e);
        if (!cell) { return; }
        var ymd = cell.getAttribute('data-date');
        if (!ymd || ymd === pick.hover) { return; }
        pick.hover = ymd;
        renderCalendar();      // 重绘出「起点 -> 悬停点」的预览高亮
    }

    function onNavClick(e) {
        var t = e.target;
        while (t && t !== el.dpPanel) {
            if (t.getAttribute && t.getAttribute('data-nav')) {
                var n = parseInt(t.getAttribute('data-nav'), 10) || 0;
                var d = new Date(pick.y, pick.m + n, 1);
                pick.y = d.getFullYear();
                pick.m = d.getMonth();
                renderCalendar();
                return;
            }
            t = t.parentNode;
        }
    }

    function onDocMouseDown(e) {
        if (!pick.open) { return; }
        if (el.dp && el.dp.contains(e.target)) { return; }
        closePanel();
    }

    function onDocKeyDown(e) {
        if (pick.open && (e.key === 'Escape' || e.keyCode === 27)) { closePanel(); }
    }

    // ============================== 交互：查询 / 分页 ==============================

    function onQueryClick() {
        // 预设 / 自定义都能查；永远不需要用户先补什么，因此不会弹错误
        state.page = 1;
        closePanel();
        fetchData();
    }

    function onReset() { applyPreset('last7', true); }

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

    // ============================== 启动 ==============================

    function bind() {
        el.presets.addEventListener('click', onPresetClick);
        el.query.addEventListener('click', onQueryClick);
        el.reset.addEventListener('click', onReset);
        el.refresh.addEventListener('click', fetchData);
        el.pager.addEventListener('click', onPagerClick);

        el.dpTrigger.addEventListener('click', togglePanel);
        el.dpPanel.addEventListener('click', onNavClick);
        el.dpGrid.addEventListener('click', onGridClick);
        el.dpGrid.addEventListener('mouseover', onGridOver);

        document.addEventListener('mousedown', onDocMouseDown);
        document.addEventListener('keydown', onDocKeyDown);

        el.pageSize.addEventListener('change', function () {
            var v = parseInt(el.pageSize.value, 10);
            if (PAGE_SIZES.indexOf(v) < 0) { v = PAGE_SIZES[0]; }
            state.pageSize = v;
            state.page = 1;
            fetchData();
        });
    }

    function init() {
        el.presets   = byId('hc-presets');
        el.dp        = byId('hc-dp');
        el.dpTrigger = byId('hc-dp-trigger');
        el.dpText    = byId('hc-dp-text');
        el.dpPanel   = byId('hc-dp-panel');
        el.dpMonth   = byId('hc-dp-month');
        el.dpGrid    = byId('hc-dp-grid');
        el.dpHint    = byId('hc-dp-hint');
        el.query     = byId('hc-query');
        el.reset     = byId('hc-reset');
        el.refresh   = byId('hc-refresh');
        el.tbody     = byId('hc-tbody');
        el.state     = byId('hc-state');
        el.pager     = byId('hc-pager');
        el.pageSize  = byId('hc-page-size');
        el.total     = byId('hc-total');

        // 结构不完整就直接退出，避免半路报错影响整个页面
        if (!el.presets || !el.tbody || !el.state || !el.pager
                || !el.dpTrigger || !el.dpPanel || !el.dpGrid || !el.dpText) {
            return;
        }

        el.pageSize.value = String(state.pageSize);

        // 初始 = 近 7 天，并把区间同步到「单框」里显示
        var r = presetRange(state.preset);
        state.start = r[0];
        state.end = r[1];

        buildPresets();
        syncChips();
        syncRangeDisplay();
        bind();
        fetchData();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
