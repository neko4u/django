document.addEventListener('DOMContentLoaded', function () {

    const form = document.getElementById('exchangeForm');

    const submitBtn = document.getElementById('submitBtn');

    form.addEventListener('submit', async function (e) {

        e.preventDefault();

        submitBtn.classList.add('loading');

        const formData = new FormData(form);

        try {

            const response = await fetch(window.location.href, {

                method: 'POST',

                body: formData,

                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }

            });

            const data = await response.json();

            if (data.success) {

                showToast(data.message, 'success');

                updatePointsBalance(
                    data.points_balance
                );

                form.reset();

            } else {

                showToast(data.message, 'error');

            }

        } catch (error) {

            showToast(
                '网络错误，请稍后重试',
                'error'
            );

        } finally {

            submitBtn.classList.remove('loading');

        }

    });

});


function showToast(message, type) {

    const container = document.getElementById(
        'toastContainer'
    );

    const toast = document.createElement('div');

    toast.className = `toast toast-${type}`;

    toast.innerText = message;

    container.appendChild(toast);

    setTimeout(() => {

        toast.remove();

    }, 3000);

}


function updatePointsBalance(balance) {

    const items = document.querySelectorAll(
        '.detail-item strong'
    );

    if (items.length > 0) {

        items[0].innerText = balance;

    }

}