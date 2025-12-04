/**
 * TechChang 3D Interactive Effects - OPTIMIZED
 * Performance-optimized particle system with spatial partitioning
 */

(function() {
    'use strict';

    // GSAP ScrollTrigger setup
    if (typeof gsap !== 'undefined' && gsap.registerPlugin) {
        gsap.registerPlugin(ScrollTrigger);
    }

    // ============================================
    // Spatial Grid for O(n) particle connection optimization
    // ============================================
    class SpatialGrid {
        constructor(cellSize) {
            this.cellSize = cellSize;
            this.grid = new Map();
        }

        clear() {
            this.grid.clear();
        }

        insert(particle) {
            const cellX = Math.floor(particle.x / this.cellSize);
            const cellY = Math.floor(particle.y / this.cellSize);
            const key = `${cellX},${cellY}`;

            if (!this.grid.has(key)) this.grid.set(key, []);
            this.grid.get(key).push(particle);
        }

        getNearby(particle) {
            const cellX = Math.floor(particle.x / this.cellSize);
            const cellY = Math.floor(particle.y / this.cellSize);
            const nearby = [];

            // Check 9 surrounding cells (including current)
            for (let dx = -1; dx <= 1; dx++) {
                for (let dy = -1; dy <= 1; dy++) {
                    const key = `${cellX + dx},${cellY + dy}`;
                    if (this.grid.has(key)) {
                        nearby.push(...this.grid.get(key));
                    }
                }
            }
            return nearby;
        }
    }

    // ============================================
    // Interactive Particle Network - OPTIMIZED
    // ============================================
    function initParticleNetwork() {
        const hero = document.querySelector('.hero-section, .neo-hero, .game-hero');
        if (!hero) return;

        // GPU optimization hint
        hero.style.willChange = 'transform';
        hero.style.transform = 'translateZ(0)';

        // Create canvas
        const canvas = document.createElement('canvas');
        canvas.style.position = 'absolute';
        canvas.style.top = '0';
        canvas.style.left = '0';
        canvas.style.width = '100%';
        canvas.style.height = '100%';
        canvas.style.zIndex = '1';
        canvas.style.pointerEvents = 'none';
        hero.style.position = 'relative';
        hero.insertBefore(canvas, hero.firstChild);

        const ctx = canvas.getContext('2d', { alpha: true });
        let width = hero.clientWidth;
        let height = hero.clientHeight;
        canvas.width = width;
        canvas.height = height;

        // Particle settings - OPTIMIZED (80 → 50)
        const particles = [];
        const particleCount = 50;
        const maxDistance = 150;
        const mouse = { x: width / 2, y: height / 2, active: false };
        const spatialGrid = new SpatialGrid(maxDistance);

        // FPS limiter variables
        const targetFPS = 30; // 60fps → 30fps for better performance
        const frameInterval = 1000 / targetFPS;
        let lastFrameTime = 0;

        // Viewport visibility tracking
        let isVisible = false;
        let animationId = null;

        // Particle class
        class Particle {
            constructor() {
                this.x = Math.random() * width;
                this.y = Math.random() * height;
                this.vx = (Math.random() - 0.5) * 0.5;
                this.vy = (Math.random() - 0.5) * 0.5;
                this.radius = Math.random() * 2 + 1;
            }

            update() {
                // Move particle
                this.x += this.vx;
                this.y += this.vy;

                // Bounce off edges
                if (this.x < 0 || this.x > width) this.vx *= -1;
                if (this.y < 0 || this.y > height) this.vy *= -1;

                // Mouse attraction - only if mouse is active
                if (mouse.active) {
                    const dx = mouse.x - this.x;
                    const dy = mouse.y - this.y;
                    const distSquared = dx * dx + dy * dy;

                    if (distSquared < 40000) { // 200px squared
                        const dist = Math.sqrt(distSquared);
                        const force = (200 - dist) / 200;
                        this.vx += (dx / dist) * force * 0.03;
                        this.vy += (dy / dist) * force * 0.03;
                    }
                }

                // Limit velocity
                const speedSquared = this.vx * this.vx + this.vy * this.vy;
                if (speedSquared > 4) { // 2 squared
                    const speed = Math.sqrt(speedSquared);
                    this.vx = (this.vx / speed) * 2;
                    this.vy = (this.vy / speed) * 2;
                }
            }

            draw() {
                ctx.beginPath();
                ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
                ctx.fillStyle = 'rgba(8, 145, 178, 0.6)';
                ctx.fill();
            }
        }

        // Initialize particles
        for (let i = 0; i < particleCount; i++) {
            particles.push(new Particle());
        }

        // Throttled mouse tracking
        let mouseMoveTimeout = null;
        hero.addEventListener('mousemove', (e) => {
            if (mouseMoveTimeout) return;
            mouseMoveTimeout = setTimeout(() => mouseMoveTimeout = null, 16); // ~60fps throttle

            const rect = hero.getBoundingClientRect();
            mouse.x = e.clientX - rect.left;
            mouse.y = e.clientY - rect.top;
            mouse.active = true;
        });

        hero.addEventListener('mouseleave', () => {
            mouse.active = false;
        });

        // Animation loop with FPS limiter
        function animate(currentTime) {
            if (!isVisible) return;

            animationId = requestAnimationFrame(animate);

            // FPS limiter
            const deltaTime = currentTime - lastFrameTime;
            if (deltaTime < frameInterval) return;

            lastFrameTime = currentTime - (deltaTime % frameInterval);

            // Clear canvas
            ctx.clearRect(0, 0, width, height);

            // Clear spatial grid
            spatialGrid.clear();

            // Update and insert into grid
            particles.forEach(particle => {
                particle.update();
                spatialGrid.insert(particle);
            });

            // Draw particles
            particles.forEach(particle => particle.draw());

            // Draw connections using spatial grid (O(n) instead of O(n²))
            const drawnConnections = new Set();

            particles.forEach(particle => {
                const nearby = spatialGrid.getNearby(particle);

                nearby.forEach(other => {
                    if (particle === other) return;

                    // Avoid drawing same connection twice
                    const connectionKey = particle.x < other.x
                        ? `${particle.x},${particle.y}-${other.x},${other.y}`
                        : `${other.x},${other.y}-${particle.x},${particle.y}`;

                    if (drawnConnections.has(connectionKey)) return;
                    drawnConnections.add(connectionKey);

                    const dx = particle.x - other.x;
                    const dy = particle.y - other.y;
                    const distSquared = dx * dx + dy * dy;

                    if (distSquared < maxDistance * maxDistance) {
                        const dist = Math.sqrt(distSquared);
                        const opacity = (1 - dist / maxDistance) * 0.3;
                        ctx.strokeStyle = `rgba(8, 145, 178, ${opacity})`;
                        ctx.lineWidth = 1;
                        ctx.beginPath();
                        ctx.moveTo(particle.x, particle.y);
                        ctx.lineTo(other.x, other.y);
                        ctx.stroke();
                    }
                });
            });
        }

        // Intersection Observer for viewport detection
        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                isVisible = entry.isIntersecting;
                if (isVisible && !animationId) {
                    lastFrameTime = performance.now();
                    animationId = requestAnimationFrame(animate);
                } else if (!isVisible && animationId) {
                    cancelAnimationFrame(animationId);
                    animationId = null;
                }
            });
        }, { threshold: 0.1 });

        observer.observe(hero);

        // Debounced resize handler
        let resizeTimeout = null;
        window.addEventListener('resize', () => {
            clearTimeout(resizeTimeout);
            resizeTimeout = setTimeout(() => {
                width = hero.clientWidth;
                height = hero.clientHeight;
                canvas.width = width;
                canvas.height = height;
            }, 250);
        });

        // Start animation if visible
        if (isVisible) {
            lastFrameTime = performance.now();
            animationId = requestAnimationFrame(animate);
        }
    }

    // ============================================
    // Scroll Animations - OPTIMIZED
    // ============================================
    function initScrollAnimations() {
        if (typeof gsap === 'undefined') return;

        // Batch process fade-in elements
        const fadeElements = gsap.utils.toArray('.fade-in');
        if (fadeElements.length > 0) {
            fadeElements.forEach((elem) => {
                gsap.from(elem, {
                    scrollTrigger: {
                        trigger: elem,
                        start: 'top 80%',
                        end: 'bottom 20%',
                        toggleActions: 'play none none reverse'
                    },
                    opacity: 0,
                    y: 50,
                    duration: 1,
                    ease: 'power3.out'
                });
            });
        }

        // Stagger animations
        for (let i = 1; i <= 10; i++) {
            const staggerElements = gsap.utils.toArray(`.stagger-${i}`);
            if (staggerElements.length > 0) {
                staggerElements.forEach((elem) => {
                    gsap.from(elem, {
                        scrollTrigger: {
                            trigger: elem,
                            start: 'top 80%'
                        },
                        opacity: 0,
                        y: 30,
                        duration: 0.8,
                        delay: i * 0.1,
                        ease: 'power2.out'
                    });
                });
            }
        }

        // 3D card tilts with throttling
        const cards = gsap.utils.toArray('.bento-item, .stat-card, .game-card');
        cards.forEach((card) => {
            let tiltTimeout = null;

            card.addEventListener('mousemove', (e) => {
                if (tiltTimeout) return;
                tiltTimeout = setTimeout(() => tiltTimeout = null, 50);

                const rect = card.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;

                const centerX = rect.width / 2;
                const centerY = rect.height / 2;

                const rotateX = (y - centerY) / 20;
                const rotateY = (centerX - x) / 20;

                gsap.to(card, {
                    duration: 0.3,
                    rotateX: rotateX,
                    rotateY: rotateY,
                    transformPerspective: 1000,
                    ease: 'power2.out'
                });
            });

            card.addEventListener('mouseleave', () => {
                gsap.to(card, {
                    duration: 0.5,
                    rotateX: 0,
                    rotateY: 0,
                    ease: 'power2.out'
                });
            });
        });
    }

    // ============================================
    // Magnetic Buttons - OPTIMIZED
    // ============================================
    function initMagneticButtons() {
        if (typeof gsap === 'undefined') return;

        const buttons = document.querySelectorAll('.btn-primary, .magnet-btn');
        buttons.forEach((btn) => {
            let magnetTimeout = null;

            btn.addEventListener('mousemove', (e) => {
                if (magnetTimeout) return;
                magnetTimeout = setTimeout(() => magnetTimeout = null, 50);

                const rect = btn.getBoundingClientRect();
                const x = e.clientX - rect.left - rect.width / 2;
                const y = e.clientY - rect.top - rect.height / 2;

                gsap.to(btn, {
                    duration: 0.3,
                    x: x * 0.2,
                    y: y * 0.2,
                    ease: 'power2.out'
                });
            });

            btn.addEventListener('mouseleave', () => {
                gsap.to(btn, {
                    duration: 0.5,
                    x: 0,
                    y: 0,
                    ease: 'elastic.out(1, 0.5)'
                });
            });
        });
    }

    // ============================================
    // Parallax Effect - OPTIMIZED with throttling
    // ============================================
    function initParallax() {
        const parallaxElements = document.querySelectorAll('.bg-blob, .orb');
        if (parallaxElements.length === 0) return;

        let parallaxTimeout = null;
        window.addEventListener('mousemove', (e) => {
            if (parallaxTimeout) return;
            parallaxTimeout = setTimeout(() => parallaxTimeout = null, 50);

            parallaxElements.forEach((el, index) => {
                const speed = (index + 1) * 0.02;
                const x = (window.innerWidth - e.clientX * speed) / 100;
                const y = (window.innerHeight - e.clientY * speed) / 100;

                el.style.transform = `translate(${x}px, ${y}px)`;
            });
        });
    }

    // ============================================
    // Ripple Effect - OPTIMIZED
    // ============================================
    function initRippleEffect() {
        const rippleElements = document.querySelectorAll('.btn-primary, .category-pill, .bento-item');

        rippleElements.forEach((elem) => {
            elem.addEventListener('click', function(e) {
                const ripple = document.createElement('span');
                ripple.classList.add('ripple');
                this.appendChild(ripple);

                const rect = this.getBoundingClientRect();
                const size = Math.max(rect.width, rect.height);
                const x = e.clientX - rect.left - size / 2;
                const y = e.clientY - rect.top - size / 2;

                ripple.style.width = ripple.style.height = size + 'px';
                ripple.style.left = x + 'px';
                ripple.style.top = y + 'px';

                setTimeout(() => ripple.remove(), 600);
            });
        });
    }

    // ============================================
    // Initialize all effects
    // ============================================
    function init() {
        // Wait for DOM to be ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', init);
            return;
        }

        // Delayed initialization to prevent blocking page load
        setTimeout(() => {
            initParticleNetwork();
            // Three.js removed - was causing duplicate rendering overhead
            initScrollAnimations();
            initMagneticButtons();
            initParallax();
            initRippleEffect();
        }, 100);
    }

    init();
})();
