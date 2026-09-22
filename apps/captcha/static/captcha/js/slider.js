/* apps/captcha/static/captcha/js/slider.js
 *
 * 滑块验证码前端组件（纯原生 JS，无依赖）。
 *
 * 前端只做三件事：渲染图片、采集拖动轨迹、把偏移量提交给服务端。
 * **验证结果一律以服务端为准**，前端不缓存任何"已通过"状态。
 *
 * 用法：
 *   内联（推荐用于注册 / 修改信息 / 修改密码页）
 *     SliderCaptcha.mount('#sliderBox', {
 *         onSuccess: function (ticket) { ... },
 *         onFail:    function (msg) { ... }
 *     });
 *
 *   弹窗（推荐用于登录页）
 *     SliderCaptcha.open({ onSuccess: function (ticket) { ... } });
 *     SliderCaptcha.close();
 */

(function (global) {
    'use strict';

    var DEFAULT_URLS = {
        generate: '/api/slider-captcha/',
        verify: '/api/verify-slider/'
    };

    var TEXT = {
        title: '安全验证',
        hint: '按住滑块，拖动到缺口位置',
        loading: '正在加载验证图片...',
        refreshing: '正在刷新...',
        verifying: '正在验证...',
        pass: '验证通过',
        fail: '验证失败，请重新拖动',
        expired: '验证已失效，正在刷新...',
        netErr: '网络错误，请稍后重试'
    };

    var SAMPLE_INTERVAL = 50;   // 拖动轨迹采样间隔（毫秒）

    function getCookie(name) {
        var m = document.cookie.match(new RegExp('(^|;\\s*)' + name + '=([^;]*)'));
        return m ? decodeURIComponent(m[2]) : '';
    }

    function now() {
        return (global.performance && global.performance.now)
            ? global.performance.now()
            : Date.now();
    }

    function genClientToken() {
        var rnd = null;
        try {
            if (global.crypto && global.crypto.randomUUID) {
                rnd = global.crypto.randomUUID();
            } else if (global.crypto && global.crypto.getRandomValues) {
                var buf = new Uint8Array(16);
                global.crypto.getRandomValues(buf);
                rnd = Array.prototype.map.call(buf, function (b) {
                    return ('0' + b.toString(16)).slice(-2);
                }).join('');
            }
        } catch (e) {
            rnd = null;
        }
        return (rnd || String(Math.random()).slice(2)) + '-' + Date.now();
    }

    function clearNode(node) {
        while (node && node.firstChild) {
            node.removeChild(node.firstChild);
        }
    }

    var SKELETON = [
        '<div class="sc-panel">',
        '  <div class="sc-header">',
        '    <span class="sc-title">' + TEXT.title + '</span>',
        '    <span class="sc-actions">',
        '      <button type="button" class="sc-icon-btn sc-refresh" title="换一张">&#8635;</button>',
        '      <button type="button" class="sc-icon-btn sc-close" title="关闭">&times;</button>',
        '    </span>',
        '  </div>',
        '  <div class="sc-stage">',
        '    <img class="sc-image" alt="验证码背景" draggable="false">',
        '    <img class="sc-tile" alt="" draggable="false">',
        '    <div class="sc-loading">' + TEXT.loading + '</div>',
        '  </div>',
        '  <div class="sc-track-wrap">',
        '    <div class="sc-fill"></div>',
        '    <div class="sc-hint">' + TEXT.hint + '</div>',
        '    <div class="sc-handle" role="button" tabindex="0" aria-label="拖动滑块">',
        '      <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor"',
        '           stroke-width="2" stroke-linecap="round" stroke-linejoin="round">',
        '        <path d="M9 6 4 12l5 6"/><path d="M15 6l5 6-5 6"/>',
        '      </svg>',
        '    </div>',
        '  </div>',
        '  <div class="sc-msg"></div>',
        '</div>'
    ].join('');

    function create(options) {
        var urls = options.urls || DEFAULT_URLS;

        var root = document.createElement('div');
        root.className = 'sc-root ' + (options.inline ? 'sc-inline' : 'sc-modal');
        root.innerHTML = SKELETON;

        var panel = root.querySelector('.sc-panel');
        var imgEl = root.querySelector('.sc-image');
        var tileEl = root.querySelector('.sc-tile');
        var loadingEl = root.querySelector('.sc-loading');
        var trackWrap = root.querySelector('.sc-track-wrap');
        var fillEl = root.querySelector('.sc-fill');
        var hintEl = root.querySelector('.sc-hint');
        var handleEl = root.querySelector('.sc-handle');
        var msgEl = root.querySelector('.sc-msg');
        var refreshBtn = root.querySelector('.sc-refresh');
        var closeBtn = root.querySelector('.sc-close');

        if (options.inline) {
            closeBtn.style.display = 'none';
        }

        var state = {
            meta: null,
            ready: false,
            busy: false,
            solved: false,
            dragging: false,
            scale: 1,
            trackMax: 0,
            offsetCss: 0,
            startClientX: 0,
            startOffsetCss: 0,
            lastSample: 0,
            track: [],
            t0: 0,
            clientToken: '',
            destroyed: false
        };

        var bound = [];
        function on(el, type, fn, opts) {
            el.addEventListener(type, fn, opts);
            bound.push([el, type, fn, opts]);
        }

        function setMsg(text, kind) {
            msgEl.textContent = text || '';
            msgEl.className = 'sc-msg' + (kind ? ' sc-' + kind : '');
        }

        function setBusy(flag) {
            state.busy = !!flag;
            root.classList.toggle('sc-busy', !!flag);
        }

        function render() {
            var left = state.offsetCss;
            tileEl.style.left = left + 'px';
            handleEl.style.left = left + 'px';
            fillEl.style.width = (left + handleEl.offsetWidth / 2) + 'px';
            hintEl.style.opacity = left > 2 ? '0' : '1';
        }

        function logicalX() {
            return state.scale ? state.offsetCss / state.scale : 0;
        }

        function layout() {
            if (state.meta === null) return;
            var cssW = imgEl.getBoundingClientRect().width;
            if (!cssW) return;
            state.scale = cssW / state.meta.width;
            var ts = state.meta.tile_size * state.scale;
            tileEl.style.width = ts + 'px';
            tileEl.style.height = ts + 'px';
            tileEl.style.top = (state.meta.y * state.scale) + 'px';
            state.trackMax = Math.max(0, trackWrap.clientWidth - handleEl.offsetWidth);
            if (state.offsetCss > state.trackMax) state.offsetCss = state.trackMax;
            render();
        }

        function pushPoint(clientX, clientY) {
            state.track.push({
                t: Math.round(now() - state.t0),
                x: Math.round(logicalX()),
                y: Math.round(clientY)
            });
        }

        // ---------------- 拉取验证码 ----------------
        function load() {
            if (state.destroyed) return;
            state.ready = false;
            state.solved = false;
            state.offsetCss = 0;
            state.track = [];
            state.clientToken = genClientToken();
            state.meta = null;
            setBusy(true);
            setMsg('', '');
            render();

            loadingEl.style.display = 'flex';
            loadingEl.textContent = TEXT.loading;
            tileEl.style.opacity = '0';

            fetch(urls.generate + '?t=' + Date.now(), {
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                credentials: 'same-origin'
            })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    if (!data || !data.success) {
                        throw new Error((data && data.message) || '验证码加载失败');
                    }
                    state.meta = data;

                    imgEl.onload = function () {
                        if (state.destroyed) return;
                        state.ready = true;
                        setBusy(false);
                        loadingEl.style.display = 'none';
                        tileEl.style.opacity = '1';
                        layout();
                    };
                    imgEl.onerror = function () {
                        setBusy(false);
                        loadingEl.textContent = '图片加载失败';
                        setMsg('图片加载失败，请点击刷新', 'err');
                    };

                    imgEl.src = data.bg;
                    tileEl.src = data.tile;
                    if (imgEl.complete && imgEl.naturalWidth) {
                        imgEl.onload();
                    }
                })
                .catch(function (err) {
                    setBusy(false);
                    loadingEl.textContent = '加载失败';
                    setMsg((err && err.message) || TEXT.netErr, 'err');
                });
        }

        // ---------------- 拖动 ----------------
        function onPointerDown(e) {
            if (!state.ready || state.busy || state.solved) return;
            if (e.button !== undefined && e.button !== 0) return;
            e.preventDefault();

            try { handleEl.setPointerCapture(e.pointerId); } catch (err) { /* 忽略 */ }

            state.dragging = true;
            state.startClientX = e.clientX;
            state.startOffsetCss = state.offsetCss;
            state.t0 = now();
            state.lastSample = state.t0;
            state.track = [];
            handleEl.classList.add('sc-active');
            pushPoint(e.clientX, e.clientY);
        }

        function onPointerMove(e) {
            if (!state.dragging) return;
            var t = now();
            if (t - state.lastSample >= SAMPLE_INTERVAL) {
                state.lastSample = t;
                pushPoint(e.clientX, e.clientY);
            }
            var next = state.startOffsetCss + (e.clientX - state.startClientX);
            if (next < 0) next = 0;
            if (next > state.trackMax) next = state.trackMax;
            state.offsetCss = next;
            render();
        }

        function onPointerUp(e) {
            if (!state.dragging) return;
            state.dragging = false;
            handleEl.classList.remove('sc-active');
            try { handleEl.releasePointerCapture(e.pointerId); } catch (err) { /* 忽略 */ }
            pushPoint(e.clientX, e.clientY);

            if (state.offsetCss <= 2) {
                // 基本没拖，直接复位，不算一次失败
                state.offsetCss = 0;
                render();
                return;
            }
            submit();
        }

        // ---------------- 提交校验 ----------------
        function submit() {
            setBusy(true);
            setMsg(TEXT.verifying, '');

            fetch(urls.verify, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                credentials: 'same-origin',
                body: JSON.stringify({
                    token: state.meta ? state.meta.token : '',
                    x: Math.round(logicalX()),
                    y: state.meta ? state.meta.y : 0,
                    timestamp: Date.now(),
                    clientToken: state.clientToken,
                    track: state.track
                })
            })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    setBusy(false);
                    if (data && data.valid && data.ticket) {
                        state.solved = true;
                        setMsg(TEXT.pass, 'ok');
                        handleEl.classList.add('sc-disabled');
                        if (typeof options.onSuccess === 'function') {
                            options.onSuccess(data.ticket);
                        }
                        if (!options.inline) {
                            setTimeout(close, 420);
                        }
                        return;
                    }
                    var msg = (data && data.message) || TEXT.fail;
                    setMsg(msg, 'err');
                    if (typeof options.onFail === 'function') options.onFail(msg);
                    // 失败自动换一张
                    setTimeout(load, 900);
                })
                .catch(function () {
                    setBusy(false);
                    setMsg(TEXT.netErr, 'err');
                });
        }

        // ---------------- 事件绑定 ----------------
        on(handleEl, 'pointerdown', onPointerDown);
        on(handleEl, 'pointermove', onPointerMove);
        on(handleEl, 'pointerup', onPointerUp);
        on(handleEl, 'pointercancel', onPointerUp);
        on(handleEl, 'keydown', function (e) {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                if (state.ready && !state.busy && !state.solved) submit();
            }
        });
        on(refreshBtn, 'click', function () { load(); });
        on(closeBtn, 'click', function () { close(); });
        on(global, 'resize', layout);

        if (!options.inline) {
            on(root, 'mousedown', function (e) {
                if (e.target === root) close();
            });
            on(document, 'keydown', function (e) {
                if (e.key === 'Escape') close();
            });
        }

        function close() {
            if (typeof options.onClose === 'function') options.onClose();
            destroy();
            if (currentModal && currentModal.root === root) currentModal = null;
        }

        function destroy() {
            if (state.destroyed) return;
            state.destroyed = true;
            bound.forEach(function (item) {
                try { item[0].removeEventListener(item[1], item[2], item[3]); } catch (e) { /* 忽略 */ }
            });
            bound = [];
            if (root.parentNode) root.parentNode.removeChild(root);
        }

        var instance = {
            root: root,
            load: load,
            destroy: destroy,
            close: close,
            reset: function () {
                handleEl.classList.remove('sc-disabled');
                state.solved = false;
                load();
            },
            isSolved: function () { return state.solved; }
        };

        // 首次布局兜底（弹窗挂载后图片还没加载时也能算对轨道宽度）
        requestAnimationFrame(layout);

        return instance;
    }

    var currentModal = null;

    function mount(element, options) {
        var target = typeof element === 'string'
            ? document.querySelector(element)
            : element;
        if (!target) return null;
        clearNode(target);
        var opts = Object.assign({}, options || {}, { inline: true });
        var inst = create(opts);
        target.appendChild(inst.root);
        inst.load();
        return inst;
    }

    function open(options) {
        close();
        var opts = Object.assign({}, options || {}, { inline: false });
        var inst = create(opts);
        document.body.appendChild(inst.root);
        currentModal = inst;
        inst.load();
        return inst;
    }

    function close() {
        if (currentModal) {
            var inst = currentModal;
            currentModal = null;
            inst.destroy();
        }
    }

    global.SliderCaptcha = {
        mount: mount,
        open: open,
        close: close,
        defaults: DEFAULT_URLS,
        texts: TEXT
    };
}(window));
