

document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
        const target = document.getElementById(item.dataset.target);
        target.scrollIntoView({ behavior: 'smooth' });
    });
});

        // 滚轮切换控制
// let isScrolling = false;
// const contentArea = document.getElementById('contentArea');
        
// contentArea.addEventListener('wheel', (e) => {
//     e.preventDefault();
//     if (isScrolling) return;
            
//     isScrolling = true;
//     const delta = Math.sign(e.deltaY);
//     const sections = Array.from(document.querySelectorAll('.content-section'));
//     const currentIndex = sections.findIndex(section => {
//         const rect = section.getBoundingClientRect();
//         return rect.top >= 0 && rect.bottom <= window.innerHeight;
//     });

//     let nextIndex = currentIndex + delta;
//     if (nextIndex < 0) nextIndex = 0;
//     if (nextIndex >= sections.length) nextIndex = sections.length - 1;

//     sections[nextIndex].scrollIntoView({
//         behavior: 'smooth',
//         block: 'start'
//     });

//     setTimeout(() => {
//         isScrolling = false;
//     }, 1000);
// }, { passive: false });

        // 自动更新导航激活状态
const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            const id = entry.target.id;
            document.querySelectorAll('.nav-item').forEach(item => {
                item.style.background = item.dataset.target === id ? '#34495e' : '';
            });
        }
    });
}, { threshold: 0.5 });

