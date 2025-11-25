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

    // AI & Human Hands SVG Animation - Professional Quality
    function initHandsAnimation() {
        const hero = document.querySelector('.hero-section, .neo-hero, .game-hero');
        if (!hero) return;

        const handsHTML = `
            <div id="hands-container" style="
                position: absolute;
                bottom: 5%;
                right: 5%;
                width: 500px;
                height: 400px;
                opacity: 0.85;
                pointer-events: none;
                z-index: 1;
            ">
                <svg viewBox="0 0 500 400" xmlns="http://www.w3.org/2000/svg" style="width: 100%; height: 100%; filter: drop-shadow(0 10px 30px rgba(0,0,0,0.5));">
                    <defs>
                        <linearGradient id="robotMetal" x1="0%" y1="0%" x2="100%" y2="100%">
                            <stop offset="0%" style="stop-color:#0ea5e9;stop-opacity:1" />
                            <stop offset="50%" style="stop-color:#0891b2;stop-opacity:1" />
                            <stop offset="100%" style="stop-color:#0e7490;stop-opacity:1" />
                        </linearGradient>
                        <linearGradient id="robotShine" x1="0%" y1="0%" x2="100%" y2="0%">
                            <stop offset="0%" style="stop-color:#ffffff;stop-opacity:0.6" />
                            <stop offset="50%" style="stop-color:#ffffff;stop-opacity:0.2" />
                            <stop offset="100%" style="stop-color:#ffffff;stop-opacity:0.6" />
                        </linearGradient>
                        <linearGradient id="humanSkin" x1="0%" y1="0%" x2="0%" y2="100%">
                            <stop offset="0%" style="stop-color:#fde4cf;stop-opacity:1" />
                            <stop offset="100%" style="stop-color:#f0cba8;stop-opacity:1" />
                        </linearGradient>
                        <radialGradient id="energyGlow" cx="50%" cy="50%">
                            <stop offset="0%" style="stop-color:#0ea5e9;stop-opacity:1" />
                            <stop offset="50%" style="stop-color:#0891b2;stop-opacity:0.6" />
                            <stop offset="100%" style="stop-color:#0891b2;stop-opacity:0" />
                        </radialGradient>
                    </defs>

                    <!-- Robot Hand (Left) -->
                    <g id="robot-hand">
                        <rect x="80" y="180" width="80" height="100" rx="8" fill="url(#robotMetal)" stroke="#0e7490" stroke-width="2"/>
                        <rect x="85" y="185" width="25" height="90" rx="4" fill="url(#robotShine)" opacity="0.3"/>
                        <circle cx="100" cy="190" r="6" fill="#0e7490" stroke="#0891b2" stroke-width="2"/>
                        <circle cx="120" cy="195" r="6" fill="#0e7490" stroke="#0891b2" stroke-width="2"/>
                        <circle cx="140" cy="200" r="6" fill="#0e7490" stroke="#0891b2" stroke-width="2"/>
                        <path d="M 160 200 L 180 190 L 195 185 L 205 180" stroke="url(#robotMetal)" stroke-width="16" fill="none" stroke-linecap="round"/>
                        <circle cx="180" cy="190" r="5" fill="#0e7490"/>
                        <circle cx="195" cy="185" r="5" fill="#0e7490"/>
                        <path d="M 160 215 L 180 205 L 195 197 L 210 190" stroke="url(#robotMetal)" stroke-width="18" fill="none" stroke-linecap="round"/>
                        <circle cx="180" cy="205" r="6" fill="#0e7490"/>
                        <circle cx="195" cy="197" r="6" fill="#0e7490"/>
                        <path d="M 160 235 L 178 228 L 192 222 L 205 216" stroke="url(#robotMetal)" stroke-width="16" fill="none" stroke-linecap="round"/>
                        <circle cx="178" cy="228" r="5" fill="#0e7490"/>
                        <path d="M 160 255 L 175 250 L 188 245 L 198 240" stroke="url(#robotMetal)" stroke-width="14" fill="none" stroke-linecap="round"/>
                        <circle cx="175" cy="250" r="4" fill="#0e7490"/>
                        <path d="M 95 270 L 108 260 L 125 250 L 145 240" stroke="url(#robotMetal)" stroke-width="18" fill="none" stroke-linecap="round"/>
                        <circle cx="108" cy="260" r="7" fill="#0e7490"/>
                        <circle cx="125" cy="250" r="7" fill="#0e7490"/>
                    </g>

                    <!-- Human Hand (Right) -->
                    <g id="human-hand">
                        <ellipse cx="380" cy="230" rx="45" ry="55" fill="url(#humanSkin)" stroke="#d4a373" stroke-width="1.5"/>
                        <path d="M 340 200 L 320 190 L 305 185 L 295 180" stroke="url(#humanSkin)" stroke-width="14" fill="none" stroke-linecap="round"/>
                        <ellipse cx="320" cy="190" rx="5" ry="6" fill="#d4a373" opacity="0.3"/>
                        <path d="M 293 178 Q 291 180 293 182" stroke="#f0cba8" stroke-width="7" fill="none" stroke-linecap="round"/>
                        <path d="M 340 215 L 318 205 L 302 197 L 290 190" stroke="url(#humanSkin)" stroke-width="16" fill="none" stroke-linecap="round"/>
                        <ellipse cx="318" cy="205" rx="6" ry="7" fill="#d4a373" opacity="0.3"/>
                        <path d="M 287 188 Q 285 190 287 192" stroke="#f0cba8" stroke-width="8" fill="none" stroke-linecap="round"/>
                        <path d="M 340 235 L 320 228 L 305 222 L 295 216" stroke="url(#humanSkin)" stroke-width="14" fill="none" stroke-linecap="round"/>
                        <ellipse cx="320" cy="228" rx="5" ry="6" fill="#d4a373" opacity="0.3"/>
                        <path d="M 340 255 L 323 250 L 310 245 L 302 240" stroke="url(#humanSkin)" stroke-width="12" fill="none" stroke-linecap="round"/>
                        <ellipse cx="323" cy="250" rx="4" ry="5" fill="#d4a373" opacity="0.3"/>
                        <path d="M 405 270 L 390 260 L 372 250 L 355 240" stroke="url(#humanSkin)" stroke-width="16" fill="none" stroke-linecap="round"/>
                        <ellipse cx="390" cy="260" rx="7" ry="8" fill="#d4a373" opacity="0.3"/>
                    </g>

                    <!-- Energy Connection -->
                    <g id="connection-point">
                        <circle cx="250" cy="200" r="40" fill="url(#energyGlow)" opacity="0.3">
                            <animate attributeName="r" values="35;45;35" dur="3s" repeatCount="indefinite"/>
                        </circle>
                        <circle cx="250" cy="200" r="8" fill="#0ea5e9" opacity="0.9">
                            <animate attributeName="r" values="6;12;6" dur="2.5s" repeatCount="indefinite"/>
                        </circle>
                        <circle cx="245" cy="195" r="2" fill="#ffffff" opacity="0.8">
                            <animate attributeName="cy" values="195;185;195" dur="2s" repeatCount="indefinite"/>
                        </circle>
                        <circle cx="255" cy="205" r="2" fill="#ffffff" opacity="0.8">
                            <animate attributeName="cy" values="205;215;205" dur="1.8s" repeatCount="indefinite"/>
                        </circle>
                    </g>
                </svg>
            </div>
        `;

        hero.insertAdjacentHTML('beforeend', handsHTML);

        // Enhanced smooth cursor interaction
        const handsContainer = document.getElementById('hands-container');
        let targetX = 0, targetY = 0, currentX = 0, currentY = 0;

        hero.addEventListener('mousemove', (e) => {
            const rect = hero.getBoundingClientRect();
            targetX = ((e.clientX - rect.left - rect.width / 2) / rect.width) * 40;
            targetY = ((e.clientY - rect.top - rect.height / 2) / rect.height) * 40;
        });

        function animateHands() {
            currentX += (targetX - currentX) * 0.1;
            currentY += (targetY - currentY) * 0.1;
            if (handsContainer) {
                handsContainer.style.transform = `translate(${currentX}px, ${currentY}px)`;
            }
            requestAnimationFrame(animateHands);
        }
        animateHands();
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
