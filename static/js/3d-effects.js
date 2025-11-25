/**
 * TechChang 3D Interactive Effects
 * Framer-inspired 3D backgrounds and animations
 */

(function() {
    'use strict';

    // GSAP ScrollTrigger setup
    if (typeof gsap !== 'undefined' && gsap.registerPlugin) {
        gsap.registerPlugin(ScrollTrigger);
    }

    // AI & Human Hands SVG Animation
    function initHandsAnimation() {
        const hero = document.querySelector('.hero-section, .neo-hero, .game-hero');
        if (!hero) return;

        const handsHTML = `
            <div id="hands-container" style="
                position: absolute;
                bottom: 10%;
                right: 5%;
                width: 350px;
                height: 350px;
                opacity: 0.5;
                pointer-events: none;
                z-index: 1;
                transition: transform 0.3s ease;
            ">
                <svg viewBox="0 0 300 300" xmlns="http://www.w3.org/2000/svg" style="width: 100%; height: 100%;">
                    <g id="robot-hand" style="transform-origin: 150px 150px;">
                        <path d="M 80 180 Q 100 160 120 150" stroke="#0891b2" stroke-width="14" fill="none" stroke-linecap="round"/>
                        <path d="M 120 138 L 138 133 M 120 150 L 142 150 M 120 162 L 138 167" stroke="#0891b2" stroke-width="9" fill="none" stroke-linecap="round"/>
                        <circle cx="128" cy="150" r="17" fill="rgba(8, 145, 178, 0.3)" stroke="#0891b2" stroke-width="3"/>
                    </g>
                    <g id="human-hand" style="transform-origin: 150px 150px;">
                        <path d="M 220 180 Q 200 160 180 150" stroke="#f7fafc" stroke-width="12" fill="none" stroke-linecap="round"/>
                        <path d="M 180 138 L 162 133 M 180 150 L 158 150 M 180 162 L 162 167" stroke="#f7fafc" stroke-width="7" fill="none" stroke-linecap="round"/>
                        <circle cx="172" cy="150" r="15" fill="rgba(247, 250, 252, 0.2)" stroke="#f7fafc" stroke-width="2"/>
                    </g>
                    <circle id="spark" cx="150" cy="150" r="8" fill="#0891b2" opacity="0">
                        <animate attributeName="r" values="0;15;0" dur="2.5s" repeatCount="indefinite"/>
                        <animate attributeName="opacity" values="0;0.8;0" dur="2.5s" repeatCount="indefinite"/>
                    </circle>
                </svg>
            </div>
        `;

        hero.insertAdjacentHTML('beforeend', handsHTML);

        // Cursor interaction
        const handsContainer = document.getElementById('hands-container');
        hero.addEventListener('mousemove', (e) => {
            const rect = hero.getBoundingClientRect();
            const x = (e.clientX - rect.left - rect.width / 2) / rect.width;
            const y = (e.clientY - rect.top - rect.height / 2) / rect.height;

            if (handsContainer) {
                handsContainer.style.transform = `translate(${x * 30}px, ${y * 30}px)`;
            }
        });
    }

    // 3D Particle Background
    function init3DBackground() {
        const hero = document.querySelector('.hero-section, .neo-hero, .game-hero');
        if (!hero || typeof THREE === 'undefined') return;

        // Create canvas
        const canvas = document.createElement('canvas');
        canvas.style.position = 'absolute';
        canvas.style.top = '0';
        canvas.style.left = '0';
        canvas.style.width = '100%';
        canvas.style.height = '100%';
        canvas.style.zIndex = '0';
        canvas.style.pointerEvents = 'none';
        hero.style.position = 'relative';
        hero.insertBefore(canvas, hero.firstChild);

        // Setup Three.js
        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(75, hero.clientWidth / hero.clientHeight, 0.1, 1000);
        const renderer = new THREE.WebGLRenderer({
            canvas,
            alpha: true,
            antialias: true
        });

        renderer.setSize(hero.clientWidth, hero.clientHeight);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        camera.position.z = 5;

        // Create particles
        const particlesGeometry = new THREE.BufferGeometry();
        const particlesCount = 1000;
        const posArray = new Float32Array(particlesCount * 3);

        for (let i = 0; i < particlesCount * 3; i++) {
            posArray[i] = (Math.random() - 0.5) * 10;
        }

        particlesGeometry.setAttribute('position', new THREE.BufferAttribute(posArray, 3));

        const particlesMaterial = new THREE.PointsMaterial({
            size: 0.02,
            color: 0x0891b2,
            transparent: true,
            opacity: 0.6,
            blending: THREE.AdditiveBlending
        });

        const particlesMesh = new THREE.Points(particlesGeometry, particlesMaterial);
        scene.add(particlesMesh);

        // Animation
        let mouseX = 0;
        let mouseY = 0;

        document.addEventListener('mousemove', (e) => {
            mouseX = (e.clientX / window.innerWidth) * 2 - 1;
            mouseY = -(e.clientY / window.innerHeight) * 2 + 1;
        });

        function animate() {
            requestAnimationFrame(animate);

            // Rotate particles
            particlesMesh.rotation.y += 0.0005;
            particlesMesh.rotation.x = mouseY * 0.1;
            particlesMesh.rotation.y = mouseX * 0.1;

            renderer.render(scene, camera);
        }

        animate();

        // Handle resize
        window.addEventListener('resize', () => {
            camera.aspect = hero.clientWidth / hero.clientHeight;
            camera.updateProjectionMatrix();
            renderer.setSize(hero.clientWidth, hero.clientHeight);
        });
    }

    // Scroll Animations
    function initScrollAnimations() {
        if (typeof gsap === 'undefined') return;

        // Fade in elements
        gsap.utils.toArray('.fade-in').forEach((elem) => {
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

        // Stagger animations
        for (let i = 1; i <= 10; i++) {
            gsap.utils.toArray(`.stagger-${i}`).forEach((elem) => {
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

        // 3D card tilts
        gsap.utils.toArray('.bento-item, .stat-card, .game-card').forEach((card) => {
            card.addEventListener('mousemove', (e) => {
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

    // Magnetic buttons
    function initMagneticButtons() {
        if (typeof gsap === 'undefined') return;

        document.querySelectorAll('.btn-primary, .magnet-btn').forEach((btn) => {
            btn.addEventListener('mousemove', (e) => {
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

    // Parallax effect
    function initParallax() {
        const parallaxElements = document.querySelectorAll('.bg-blob, .orb');

        window.addEventListener('mousemove', (e) => {
            const mouseX = e.clientX / window.innerWidth;
            const mouseY = e.clientY / window.innerHeight;

            parallaxElements.forEach((el, index) => {
                const speed = (index + 1) * 0.02;
                const x = (window.innerWidth - e.clientX * speed) / 100;
                const y = (window.innerHeight - e.clientY * speed) / 100;

                el.style.transform = `translate(${x}px, ${y}px)`;
            });
        });
    }

    // Ripple effect
    function initRippleEffect() {
        document.querySelectorAll('.btn-primary, .category-pill, .bento-item').forEach((elem) => {
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

    // Initialize all effects
    function init() {
        // Wait for DOM to be ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', init);
            return;
        }

        setTimeout(() => {
            initHandsAnimation();
            init3DBackground();
            initScrollAnimations();
            initMagneticButtons();
            initParallax();
            initRippleEffect();
        }, 100);
    }

    init();
})();
