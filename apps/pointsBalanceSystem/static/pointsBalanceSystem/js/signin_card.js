/* apps/pointsBalanceSystem/static/pointsBalanceSystem/js/signin_card.js
   签到卡片（findex 的「获取积分」页 #sec2-content）

   接口：
     GET  /points/api/sign-in/status/   查状态
     POST /points/api/sign-in/          签到

   约定（和 signin_views.py 对齐）：
     - 两个接口 HTTP 200 都可能是「业务成功」也可能是「业务失败」，看 body 里的 `code`
     - ALREADY_SIGNED 是**正常状态**，不是错误
     - 401 / 403 / 500 走 resp.ok 分支
     - 任何情况下都不把内部细节（堆栈、连接串）显示给用户
*/
(function () {
    'use strict';

    var URLS = window.SIGNIN_URLS || {};

    var card = document.getElementById('signin-card');
    if (!card) { return; }                  // 页面上没有这张卡，直接收工

    var loadingEl = document.getElementById('si-loading');
    var mainEl    = document.getElementById('si-main');
    var emptyEl   = document.getElementById('si-empty');
    var retryBtn  = document.getElementById('si-retry');

    var nameEl    = document.getElementById('si-name');
    var descEl    = document.getElementById('si-desc');
    var pointsEl  = document.getElementById('si-points');
    var balanceEl = document.getElementById('si-balance');
    var todayEl   = document.getElementById('si-today');
    var rangeEl   = document.getElementById('si-range');
    var btn       = document.getElementById('si-btn');
    var tipEl     = document.getElementById('si-tip');

    var busy = false;
    var signed = false;

    // 这几种结果说明「活动/账户本身不可用」，很可能刚被管理员停用或已过期，
    // 所以要顺手刷新一次状态（但刷新必须**在提示之前**，否则提示会被刷新的清屏动作抹掉）
    var REFRESH_CODES = {
        NO_ACTIVITY: 1,
        ACTIVITY_DISABLED: 1,
        ACTIVITY_NOT_STARTED: 1,
        ACTIVITY_ENDED: 1,
        ACCOUNT_DISABLED: 1,
        USER_INVALID: 1
    };

    /* ---------------- 小工具 ---------------- */

    function csrf() {
        var el = document.querySelector('#signin-csrf input[name=csrfmiddlewaretoken]')
              || document.querySelector('[name=csrfmiddlewaretoken]');
        if (el && el.value) { return el.value; }
        var m = document.cookie.match(/csrftoken=([^;]+)/);
        return m ? decodeURIComponent(m[1]) : '';
    }

    // 统一成 { http, ok, data }；非 JSON（网关 502 / 登录页 HTML）时 data = null
    function request(url, opts) {
        opts = opts || {};
        return fetch(url, {
            method: opts.method || 'GET',
            body: opts.body || null,
            credentials: 'same-origin',
            headers: opts.headers || {}
        }).then(function (resp) {
            return resp.text().then(function (t) {
                var d = null;
                try {
                    d = JSON.parse(t);
                } catch (e) {
                    console.warn('[签到] 接口返回的不是 JSON：', resp.status, t.slice(0, 300));
                }
                return { http: resp.status, ok: resp.ok, data: d };
            });
        });
    }

    function showLoading(text) {
        loadingEl.textContent = text || '正在加载签到活动…';
        loadingEl.hidden = false;
        mainEl.hidden = true;
        emptyEl.hidden = true;
    }

    function showMain() {
        loadingEl.hidden = true;
        emptyEl.hidden = true;
        mainEl.hidden = false;
    }

    function showEmpty(title, text, canRetry) {
        loadingEl.hidden = true;
        mainEl.hidden = true;
        emptyEl.hidden = false;
        document.getElementById('si-empty-title').textContent = title;
        document.getElementById('si-empty-text').textContent = text;
        retryBtn.hidden = !canRetry;
    }

    function tip(text, cls) {
        tipEl.textContent = text || '';
        tipEl.className = 'si-tip' + (cls ? ' ' + cls : '');
    }

    function setBtn(text, disabled, isSigned) {
        btn.textContent = text;
        btn.disabled = !!disabled;
        btn.classList.toggle('is-signed', !!isSigned);
    }

    function markSignedState(balance, points, tipText, withPop) {
        signed = true;
        if (balance !== null && balance !== undefined) {
            balanceEl.textContent = String(balance);
        }
        todayEl.textContent = '已签到';
        setBtn('今天已签到，明天再来', true, true);
        if (points !== null && points !== undefined) {
            pointsEl.textContent = '+' + points;
        }
        pointsEl.classList.add('is-signed');
        if (withPop) {
            pointsEl.classList.add('is-pop');
            setTimeout(function () { pointsEl.classList.remove('is-pop'); }, 500);
        }
        tip(tipText || '', 'ok');
    }

    /* ---------------- 渲染 ---------------- */

    function render(data) {
        var act = data && data.activity;

        if (!act) {
            showEmpty('暂时没有签到活动', '活动开启后会在这里出现。', false);
            return;
        }

        showMain();

        nameEl.textContent = act.name || '签到活动';
        descEl.textContent = act.description || '';
        descEl.hidden = !act.description;

        pointsEl.textContent = '+' + (act.points_per_sign_in || 0);
        pointsEl.classList.remove('is-signed');
        balanceEl.textContent = String(data.balance === null || data.balance === undefined
            ? 0 : data.balance);
        rangeEl.textContent = '活动时间：' + (act.start_at || '') + ' ～ ' + (act.end_at || '');

        if (data.account_enable === false) {
            signed = false;
            todayEl.textContent = '不可用';
            setBtn('积分账户已停用', true, false);
            tip('积分账户已被停用，暂时无法签到。', 'err');
            return;
        }

        if (data.signed_today) {
            markSignedState(data.balance,
                            data.today_points,
                            '今天已签到，获得 ' + (data.today_points || 0) + ' 积分' +
                            (data.sign_time ? '（' + data.sign_time + '）' : ''),
                            false);
        } else {
            signed = false;
            todayEl.textContent = '未签到';
            setBtn('立即签到', false, false);
            tip('');
        }
    }

    /* ---------------- 拉状态 ---------------- */

    function loadStatus() {
        showLoading();
        tip('');
        return request(URLS.status).then(function (r) {
            if (r.data && r.data.status === 'success') {
                render(r.data);
                return;
            }
            if (r.http === 401) {
                showEmpty('请先登录', '登录后即可参与签到。', false);
                return;
            }
            showEmpty('加载失败',
                      (r.data && r.data.message) || ('HTTP ' + r.http + '，请稍后重试'),
                      true);
        }, function (err) {
            console.error('[签到] 加载状态失败：', err);
            showEmpty('加载失败', '请求未送达，请检查网络后重试。', true);
        });
    }

    /* ---------------- 签到 ---------------- */

    function doSignin() {
        if (busy || signed || btn.disabled) { return; }
        busy = true;
        btn.classList.add('is-busy');
        setBtn('签到中…', true, false);

        var fd = new FormData();
        fd.append('csrfmiddlewaretoken', csrf());

        request(URLS.signin, {
            method: 'POST',
            body: fd,
            headers: {
                'X-CSRFToken': csrf(),
                'X-Requested-With': 'XMLHttpRequest'
            }
        }).then(function (r) {
            if (r.http === 401) {
                setBtn('立即签到', false, false);
                tip('登录状态已失效，请重新登录。', 'err');
                return;
            }
            if (!r.data) {
                setBtn('立即签到', false, false);
                tip('签到失败（HTTP ' + r.http + '），请稍后重试', 'err');
                return;
            }

            var code = r.data.code;

            if (code === 'SUCCESS') {
                markSignedState(r.data.balance, r.data.points,
                                '签到成功！获得 ' + (r.data.points || 0) + ' 积分', true);
                return;
            }

            if (code === 'ALREADY_SIGNED') {
                // 正常状态，不是错误
                markSignedState(r.data.balance, r.data.today_points,
                                '今天已经签到过了，明天再来。', false);
                return;
            }

            // 其余都是「活动不可用 / 账户不可用」。
            // ⚠️ 顺序很重要：loadStatus() 会先清空提示并显示"加载中"，
            //    所以必须**先刷新、后提示**，否则用户根本看不到那句话。
            var msg = r.data.message || '签到失败，请稍后重试';
            setBtn('立即签到', false, false);

            if (REFRESH_CODES[code]) {
                loadStatus().then(function () {
                    // 刷新后如果已经切到空态（没有活动了），空态本身就说清楚了，不再叠一句错误
                    if (mainEl.hidden === false) { tip(msg, 'err'); }
                });
                return;
            }

            tip(msg, 'err');
        }, function (err) {
            console.error('[签到] 请求未完成：', err);
            setBtn('立即签到', false, false);
            tip('签到失败：请求未送达，请检查网络后重试。', 'err');
        }).then(function () {
            busy = false;
            btn.classList.remove('is-busy');
            // 被 markSignedState 改成禁用态时，上面那句 setBtn 已经把文案摆好了
            if (!signed && btn.disabled && btn.textContent === '签到中…') {
                setBtn('立即签到', false, false);
            }
        });
    }

    /* ---------------- 绑定 ---------------- */

    btn.addEventListener('click', doSignin);
    retryBtn.addEventListener('click', function () { loadStatus(); });

    loadStatus();
})();
