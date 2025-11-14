(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {
        // Auto-dismiss and stagger removal after 5s
        setTimeout(() => {
            const flashMessages = document.querySelectorAll('.flash-message');
            flashMessages.forEach((message, index) => {
                setTimeout(() => {
                    message.style.transition = 'opacity 300ms, transform 300ms';
                    message.style.opacity = '0';
                    message.style.transform = 'translateY(-20px)';
                    setTimeout(() => {
                        if (message.parentNode) message.parentNode.removeChild(message);
                    }, 300);
                }, index * 200);
            });
        }, 5000);

        // Sidebar link feedback
        const sidebarLinks = document.querySelectorAll('.sidebar-item[href]');
        sidebarLinks.forEach(link => {
            link.addEventListener('click', function () {
                if (!this.classList.contains('active-nav')) {
                    const icon = this.querySelector('.nav-icon i');
                    if (icon) {
                        icon.classList.add('fa-spin');
                        setTimeout(() => icon.classList.remove('fa-spin'), 1000);
                    }
                }
            });
        });

        // Manual close buttons: smooth hide
        document.querySelectorAll('.flash-message .close').forEach(btn => {
            btn.addEventListener('click', () => {
                const alert = btn.closest('.flash-message');
                if (!alert) return;
                alert.style.transition = 'opacity 300ms, transform 300ms';
                alert.style.opacity = '0';
                alert.style.transform = 'translateY(-20px)';
                setTimeout(() => {
                    if (alert.parentNode) alert.parentNode.removeChild(alert);
                }, 300);
            });
        });
    });
})();