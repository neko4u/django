document.addEventListener('DOMContentLoaded', function () {

    const closeButtons = document.querySelectorAll('.message-close');

    closeButtons.forEach(btn => {

        btn.addEventListener('click', function () {

            this.parentElement.remove();

        });

    });

});