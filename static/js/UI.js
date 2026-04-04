(function () {
    'use strict';

    document.addEventListener('DOMContentLoaded', function () {
        function removeFlashMessage(message) {
            if (message && message.parentNode) {
                message.parentNode.removeChild(message);
            }
        }

        // Auto-dismiss and stagger removal after 5s
        setTimeout(() => {
            const flashMessages = document.querySelectorAll('.flash-message');
            flashMessages.forEach((message, index) => {
                setTimeout(() => {
                    // Keep full opacity for readability; use a slight lift before removal.
                    message.style.transition = 'transform 200ms ease';
                    message.style.transform = 'translateY(-10px)';
                    setTimeout(() => {
                        removeFlashMessage(message);
                    }, 200);
                }, index * 120);
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
                // Keep full opacity for readability; use a slight lift before removal.
                alert.style.transition = 'transform 200ms ease';
                alert.style.transform = 'translateY(-10px)';
                setTimeout(() => {
                    removeFlashMessage(alert);
                }, 200);
            });
        });
    });
})();