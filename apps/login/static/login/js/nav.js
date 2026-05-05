document.addEventListener('DOMContentLoaded', () => {
    const panel = document.getElementById('userPanel');
    const avatar = document.querySelector('.user-avatar');

    function toggleUserPanel(event) {
        event.stopPropagation();
        panel.classList.toggle('active');
    }

    // 绑定头像点击事件 (推荐用事件委托代替onclick属性)
    avatar.addEventListener('click', toggleUserPanel);

    // 全局点击监听（修复版）
    document.addEventListener('click', function(event) {
        if (!panel || !avatar) return;
        
        const isClickOnPanel = panel.contains(event.target);
        const isClickOnAvatar = event.target === avatar || avatar.contains(event.target);
        
        if (!isClickOnPanel && !isClickOnAvatar) {
            panel.classList.remove('active');
        }
    });

    // 阻止面板点击冒泡（修复版）
    if (panel) {
        panel.addEventListener('click', function(event) {
            event.stopPropagation();
        });
    }
});

function switchNav(e){
    const navItems = document.getElementsByClassName("left-nav-item");
    var switchButtonImg = document.getElementById("switchPanelButton");
    var containerGrid = document.querySelector(".main-container");
    if(navItems && navItems[0].style.display !== "none"){
        for (let i = 0; i < navItems.length; i++) {
            navItems[i].style.display =  "none";
        }
        containerGrid.style.gridTemplateColumns = "4% 96%";
        setTimeout(function() {
            switchButtonImg.src = "/media/urls/base/openNav.png";
        }, 400);
    }
    else {
        containerGrid.style.gridTemplateColumns = "7% 93%";
        setTimeout(function() {
            for (let i = 0; i < navItems.length; i++) {
                navItems[i].style.display =  "block";
            }
            switchButtonImg.src = "/media/urls/base/hideNav.png";
        },400);
    }
}