/**
 * AL-KHWARIZMI UNIVERSITY — TASK MANAGEMENT LANDING PAGE
 * Lightweight Vanilla JS animations and interactions
 */

document.addEventListener('DOMContentLoaded', function () {
    // 1. Scroll Entrance Reveal using IntersectionObserver
    if ('IntersectionObserver' in window) {
        const revealElements = document.querySelectorAll('.reveal-on-scroll');
        const revealObserver = new IntersectionObserver(
            (entries, observer) => {
                entries.forEach((entry) => {
                    if (entry.isIntersecting) {
                        entry.target.classList.add('is-revealed');
                        observer.unobserve(entry.target);
                    }
                });
            },
            {
                root: null,
                threshold: 0.12,
                rootMargin: '0px 0px -40px 0px',
            }
        );

        revealElements.forEach((el) => revealObserver.observe(el));
    } else {
        // Fallback for browsers without IntersectionObserver
        document.querySelectorAll('.reveal-on-scroll').forEach((el) => {
            el.classList.add('is-revealed');
        });
    }

    // 2. Smooth Scroll for in-page anchor links
    document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
        anchor.addEventListener('click', function (e) {
            const targetId = this.getAttribute('href');
            if (targetId && targetId !== '#') {
                const targetElement = document.querySelector(targetId);
                if (targetElement) {
                    e.preventDefault();
                    targetElement.scrollIntoView({
                        behavior: 'smooth',
                        block: 'start',
                    });
                }
            }
        });
    });
});
