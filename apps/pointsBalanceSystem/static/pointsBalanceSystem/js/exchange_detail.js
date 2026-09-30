document.addEventListener('DOMContentLoaded', function () {

    const form = document.getElementById('exchangeForm');
    if (!form) return;                                   // 页面上没有兑换组件时跳过

    const submitBtn     = document.getElementById('submitBtn');
    const quantityInput = document.getElementById('id_quantity');

    const POINTS_REQUIRED = Number(window.POINTS_REQUIRED || 0);
    const REWARD_SECONDS  = Number(window.REWARD_SECONDS  || 0);

    const totalPointsEl   = document.getElementById('totalPoints');
    const totalSecondsEl  = document.getElementById('totalSeconds');
    const pointsBalanceEl = document.getElementById('pointsBalance');

    /* ---------------- 实时计算 ---------------- */
    function recalc() {
        let q = parseInt(quantityInput && quantityInput.value, 10);
        if (isNaN(q) || q < 1) q = 1;
        if (totalPointsEl)  totalPointsEl.innerText  = POINTS_REQUIRED * q;
        if (totalSecondsEl) totalSecondsEl.innerText = REWARD_SECONDS  * q;
    }

    if (quantityInput) {
        quantityInput.addEventListener('input', recalc);
        quantityInput.addEventListener('change', recalc);
        recalc();
    }

    /* ---------------- 提交兑换 ---------------- */
    form.addEventListener('submit', async function (e) {

        e.preventDefault();

        if (submitBtn.classList.contains('loading')) return;   // 防连点重复提交
        submitBtn.classList.add('loading');

        // 【关键】内嵌到 /findex/ 后不能用 window.location.href，
        // 否则 POST 会打到 findex 视图（返回 HTML），JSON 解析失败 → 恒报「网络错误」
        const url = form.getAttribute('action') || window.location.href;

        try {

            const response = await fetch(url, {
                method: 'POST',
                body: new FormData(form),          // 已含 csrfmiddlewaretoken
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                credentials: 'same-origin'
            });

            let data;
            try {
                data = await response.json();
            } catch (parseErr) {
                showToast('服务返回异常，请刷新页面重试', 'error');
                return;
            }

            if (data.success) {
                showToast(data.message, 'success');
                updatePointsBalance(data.points_balance);
                form.reset();
                recalc();
            } else {
                showToast(data.message, 'error');
            }

        } catch (error) {

            showToast('网络错误，请稍后重试', 'error');

        } finally {

            submitBtn.classList.remove('loading');

        }

    });

    /* ---------------- Django messages：点 × 关闭 + 到点自动消失 ---------------- */
    (function () {
        const AUTO_HIDE_MS = 5000;
        const boxes = document.querySelectorAll('.message-area .message');

        function hide(box) {
            if (!box || box.dataset.hiding === '1') { return; }
            box.dataset.hiding = '1';
            box.style.transition = 'opacity .4s ease, transform .4s ease';
            box.style.opacity = '0';
            box.style.transform = 'translateY(-8px)';
            setTimeout(() => {
                const area = box.parentElement;
                box.remove();
                if (area && !area.querySelector('.message')) { area.remove(); }
            }, 400);
        }

        boxes.forEach(function (box, i) {
            const btn = box.querySelector('.message-close');
            if (btn) {
                btn.addEventListener('click', function () { hide(box); });
            }
            // 多条消息错开一点，避免同时消失
            setTimeout(() => hide(box), AUTO_HIDE_MS + i * 400);
        });
    })();
});


function showToast(message, type) {

    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerText = message;
    container.appendChild(toast);

    setTimeout(() => toast.remove(), 3000);
}


function updatePointsBalance(balance) {

    const el = document.getElementById('pointsBalance');
    if (el && balance !== undefined && balance !== null) {
        el.innerText = balance;
    }
}
