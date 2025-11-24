/**
 * TechChang Interactive Library
 * Framer-inspired interactive effects for dynamic web experiences
 *
 * Features:
 * - Scroll-based animations
 * - Parallax effects
 * - Custom cursor
 * - Magnetic buttons
 * - Reveal animations
 * - Smooth page transitions
 */

class TechChangInteractive {
    constructor() {
        this.init();
    }

    init() {
        // Initialize when DOM is ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.initAll());
        } else {
            this.initAll();
        }
    }

    initAll() {
        this.initScrollAnimations();
        this.initParallax();
        this.initCustomCursor();
        this.initMagneticButtons();
        this.initSmoothScroll();
        this.initRevealOnScroll();
        this.initTiltCards();
        this.initPageTransitions();
        this.initFloatingElements();
    }

    /**
     * Scroll-based Animations
     * Elements fade in and move as user scrolls
     */
    initScrollAnimations() {
        const observerOptions = {
            threshold: 0.1,
            rootMargin: '0px 0px -100px 0px'
        };

        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('is-visible');
                    // Optionally unobserve after animation
                    // observer.unobserve(entry.target);
                }
            });
        }, observerOptions);

        // Observe elements with scroll-reveal class
        document.querySelectorAll('.scroll-reveal').forEach(el => {
            observer.observe(el);
        });

        // Auto-add scroll-reveal to fade-in elements
        document.querySelectorAll('.fade-in-up, .fade-in-down, .fade-in-left, .fade-in-right').forEach(el => {
            if (!el.classList.contains('scroll-reveal')) {
                el.classList.add('scroll-reveal');
                observer.observe(el);
            }
        });
    }

    /**
     * Parallax Effects
     * Elements move at different speeds on scroll
     */
    initParallax() {
        const parallaxElements = document.querySelectorAll('[data-parallax]');

        if (parallaxElements.length === 0) return;

        let ticking = false;

        const updateParallax = () => {
            const scrollY = window.pageYOffset;

            parallaxElements.forEach(el => {
                const speed = parseFloat(el.dataset.parallax) || 0.5;
                const yPos = -(scrollY * speed);
                el.style.transform = `translate3d(0, ${yPos}px, 0)`;
            });

            ticking = false;
        };

        window.addEventListener('scroll', () => {
            if (!ticking) {
                window.requestAnimationFrame(updateParallax);
                ticking = true;
            }
        }, { passive: true });
    }

    /**
     * Custom Cursor
     * Interactive cursor that follows mouse
     */
    initCustomCursor() {
        // Only on desktop
        if (window.innerWidth < 768) return;

        // Create cursor elements
        const cursor = document.createElement('div');
        cursor.className = 'custom-cursor';
        const cursorDot = document.createElement('div');
        cursorDot.className = 'custom-cursor-dot';

        document.body.appendChild(cursor);
        document.body.appendChild(cursorDot);

        let mouseX = 0, mouseY = 0;
        let cursorX = 0, cursorY = 0;
        let dotX = 0, dotY = 0;

        // Track mouse position
        document.addEventListener('mousemove', (e) => {
            mouseX = e.clientX;
            mouseY = e.clientY;
        });

        // Smooth cursor animation
        const animateCursor = () => {
            // Smooth follow for main cursor
            cursorX += (mouseX - cursorX) * 0.15;
            cursorY += (mouseY - cursorY) * 0.15;
            cursor.style.left = cursorX + 'px';
            cursor.style.top = cursorY + 'px';

            // Faster follow for dot
            dotX += (mouseX - dotX) * 0.25;
            dotY += (mouseY - dotY) * 0.25;
            cursorDot.style.left = dotX + 'px';
            cursorDot.style.top = dotY + 'px';

            requestAnimationFrame(animateCursor);
        };
        animateCursor();

        // Hover effects
        const hoverElements = document.querySelectorAll('a, button, .btn, .card, [data-cursor="pointer"]');
        hoverElements.forEach(el => {
            el.addEventListener('mouseenter', () => {
                cursor.classList.add('cursor-hover');
                cursorDot.classList.add('cursor-hover');
            });
            el.addEventListener('mouseleave', () => {
                cursor.classList.remove('cursor-hover');
                cursorDot.classList.remove('cursor-hover');
            });
        });
    }

    /**
     * Magnetic Buttons
     * Buttons that follow the mouse cursor
     */
    initMagneticButtons() {
        const magneticElements = document.querySelectorAll('.magnet-btn, [data-magnetic]');

        magneticElements.forEach(el => {
            el.addEventListener('mousemove', (e) => {
                const rect = el.getBoundingClientRect();
                const x = e.clientX - rect.left - rect.width / 2;
                const y = e.clientY - rect.top - rect.height / 2;

                const strength = el.dataset.magneticStrength || 0.3;
                el.style.transform = `translate(${x * strength}px, ${y * strength}px)`;
            });

            el.addEventListener('mouseleave', () => {
                el.style.transform = 'translate(0, 0)';
            });
        });
    }

    /**
     * Smooth Scroll
     * Smooth scrolling for anchor links
     */
    initSmoothScroll() {
        document.querySelectorAll('a[href^="#"]').forEach(anchor => {
            anchor.addEventListener('click', function (e) {
                const href = this.getAttribute('href');
                if (href === '#') return;

                const target = document.querySelector(href);
                if (target) {
                    e.preventDefault();
                    target.scrollIntoView({
                        behavior: 'smooth',
                        block: 'start'
                    });
                }
            });
        });
    }

    /**
     * Reveal on Scroll
     * Advanced scroll reveal with stagger effects
     */
    initRevealOnScroll() {
        const revealElements = document.querySelectorAll('[data-reveal]');

        const revealObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const delay = entry.target.dataset.revealDelay || 0;
                    setTimeout(() => {
                        entry.target.classList.add('revealed');
                    }, delay);
                    revealObserver.unobserve(entry.target);
                }
            });
        }, {
            threshold: 0.15
        });

        revealElements.forEach(el => {
            revealObserver.observe(el);
        });

        // Auto-reveal for stagger groups
        document.querySelectorAll('[data-stagger]').forEach(container => {
            const children = container.children;
            const staggerDelay = parseInt(container.dataset.stagger) || 100;

            Array.from(children).forEach((child, index) => {
                child.dataset.reveal = 'true';
                child.dataset.revealDelay = index * staggerDelay;
                child.style.opacity = '0';
                child.style.transform = 'translateY(30px)';
                child.style.transition = 'opacity 0.6s ease, transform 0.6s ease';

                revealObserver.observe(child);
            });
        });
    }

    /**
     * Tilt Cards
     * 3D tilt effect on mouse move
     */
    initTiltCards() {
        const tiltCards = document.querySelectorAll('.card-tilt, [data-tilt]');

        tiltCards.forEach(card => {
            card.addEventListener('mousemove', (e) => {
                const rect = card.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;

                const centerX = rect.width / 2;
                const centerY = rect.height / 2;

                const rotateX = ((y - centerY) / centerY) * 10;
                const rotateY = ((x - centerX) / centerX) * 10;

                card.style.transform = `perspective(1000px) rotateX(${-rotateX}deg) rotateY(${rotateY}deg) scale3d(1.02, 1.02, 1.02)`;
            });

            card.addEventListener('mouseleave', () => {
                card.style.transform = 'perspective(1000px) rotateX(0) rotateY(0) scale3d(1, 1, 1)';
            });

            // Set initial transition
            card.style.transition = 'transform 0.3s ease';
        });
    }

    /**
     * Page Transitions
     * Smooth transitions between pages
     */
    initPageTransitions() {
        // Create overlay
        const overlay = document.createElement('div');
        overlay.className = 'page-transition-overlay';
        document.body.appendChild(overlay);

        // Intercept navigation links
        document.querySelectorAll('a:not([target="_blank"]):not([href^="#"])').forEach(link => {
            // Skip external links and special links
            if (link.hostname === window.location.hostname &&
                !link.hasAttribute('data-no-transition')) {

                link.addEventListener('click', (e) => {
                    const href = link.href;

                    // Skip if it's a form submission or download
                    if (link.download || link.closest('form')) return;

                    e.preventDefault();

                    // Animate overlay
                    overlay.classList.add('active');

                    // Navigate after animation
                    setTimeout(() => {
                        window.location.href = href;
                    }, 400);
                });
            }
        });

        // Fade in on page load
        window.addEventListener('load', () => {
            overlay.classList.remove('active');
        });
    }

    /**
     * Floating Elements
     * Gentle floating animation
     */
    initFloatingElements() {
        const floatingElements = document.querySelectorAll('.float, [data-float]');

        floatingElements.forEach((el, index) => {
            const duration = 3 + (index % 3);
            const delay = (index % 4) * 0.5;

            el.style.animation = `float ${duration}s ease-in-out ${delay}s infinite`;
        });
    }
}

// Auto-initialize
const techChangInteractive = new TechChangInteractive();

// Export for manual control if needed
window.TechChangInteractive = TechChangInteractive;
