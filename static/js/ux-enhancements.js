/**
 * UX Enhancements - 전역 로딩 & 토스트 알림 시스템
 * 사용자 경험 개선을 위한 유틸리티
 */

class UXEnhancements {
    constructor() {
        this.init();
    }

    init() {
        this.createLoadingIndicator();
        this.createToastContainer();
        this.initImageLazyLoading();
        this.setupFormEnhancements();
    }

    /**
     * 전역 로딩 인디케이터
     */
    createLoadingIndicator() {
        // 로딩 오버레이 생성
        const loadingHTML = `
            <div id="global-loading" class="global-loading">
                <div class="loading-spinner">
                    <div class="spinner-ring"></div>
                    <div class="spinner-ring"></div>
                    <div class="spinner-ring"></div>
                    <div class="loading-text">로딩 중...</div>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', loadingHTML);

        // 전역 함수 등록
        window.showLoading = (message = '로딩 중...') => {
            const loading = document.getElementById('global-loading');
            const text = loading.querySelector('.loading-text');
            text.textContent = message;
            loading.classList.add('active');
        };

        window.hideLoading = () => {
            const loading = document.getElementById('global-loading');
            loading.classList.remove('active');
        };

        // AJAX 요청 자동 감지
        this.interceptAjaxRequests();
    }

    /**
     * AJAX 요청 자동 로딩 표시
     */
    interceptAjaxRequests() {
        let activeRequests = 0;
        let loadingTimer = null;

        // XMLHttpRequest 인터셉트
        const originalOpen = XMLHttpRequest.prototype.open;
        const originalSend = XMLHttpRequest.prototype.send;

        XMLHttpRequest.prototype.open = function(...args) {
            this._startTime = Date.now();
            return originalOpen.apply(this, args);
        };

        XMLHttpRequest.prototype.send = function(...args) {
            activeRequests++;

            // 500ms 이상 걸리면 로딩 표시
            loadingTimer = setTimeout(() => {
                if (activeRequests > 0) {
                    window.showLoading();
                }
            }, 500);

            this.addEventListener('loadend', () => {
                activeRequests--;
                if (activeRequests === 0) {
                    clearTimeout(loadingTimer);
                    window.hideLoading();
                }
            });

            return originalSend.apply(this, args);
        };

        // Fetch API 인터셉트
        const originalFetch = window.fetch;
        window.fetch = async (...args) => {
            activeRequests++;

            loadingTimer = setTimeout(() => {
                if (activeRequests > 0) {
                    window.showLoading();
                }
            }, 500);

            try {
                const response = await originalFetch(...args);
                return response;
            } finally {
                activeRequests--;
                if (activeRequests === 0) {
                    clearTimeout(loadingTimer);
                    window.hideLoading();
                }
            }
        };
    }

    /**
     * 토스트 알림 시스템
     */
    createToastContainer() {
        const toastHTML = `
            <div id="toast-container" class="toast-container"></div>
        `;
        document.body.insertAdjacentHTML('beforeend', toastHTML);

        // 전역 함수 등록
        window.showToast = (message, type = 'success', duration = 3000) => {
            const container = document.getElementById('toast-container');
            const toastId = 'toast-' + Date.now();

            const icons = {
                success: '✓',
                error: '✕',
                warning: '⚠',
                info: 'ℹ'
            };

            const toast = document.createElement('div');
            toast.id = toastId;
            toast.className = `toast toast-${type}`;
            toast.innerHTML = `
                <div class="toast-icon">${icons[type] || icons.info}</div>
                <div class="toast-message">${message}</div>
                <button class="toast-close" onclick="this.parentElement.remove()">×</button>
            `;

            container.appendChild(toast);

            // 애니메이션
            setTimeout(() => toast.classList.add('show'), 10);

            // 자동 제거
            if (duration > 0) {
                setTimeout(() => {
                    toast.classList.remove('show');
                    setTimeout(() => toast.remove(), 300);
                }, duration);
            }

            return toastId;
        };

        // 편의 함수
        window.showSuccess = (message, duration) => window.showToast(message, 'success', duration);
        window.showError = (message, duration) => window.showToast(message, 'error', duration);
        window.showWarning = (message, duration) => window.showToast(message, 'warning', duration);
        window.showInfo = (message, duration) => window.showToast(message, 'info', duration);
    }

    /**
     * 이미지 Lazy Loading
     */
    initImageLazyLoading() {
        // Intersection Observer로 이미지 지연 로딩
        const imageObserver = new IntersectionObserver((entries, observer) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const img = entry.target;

                    // data-src가 있으면 실제 이미지 로드
                    if (img.dataset.src) {
                        img.src = img.dataset.src;
                        img.removeAttribute('data-src');
                    }

                    // srcset도 처리
                    if (img.dataset.srcset) {
                        img.srcset = img.dataset.srcset;
                        img.removeAttribute('data-srcset');
                    }

                    img.classList.add('lazy-loaded');
                    observer.unobserve(img);
                }
            });
        }, {
            rootMargin: '50px' // 뷰포트 50px 전에 미리 로드
        });

        // 기존 이미지에 lazy loading 적용
        document.querySelectorAll('img[data-src]').forEach(img => {
            imageObserver.observe(img);
        });

        // 네이티브 lazy loading도 활성화
        document.querySelectorAll('img:not([loading])').forEach(img => {
            img.loading = 'lazy';
        });
    }

    /**
     * 폼 제출 자동 피드백
     */
    setupFormEnhancements() {
        // 모든 폼에 제출 시 로딩 표시
        document.addEventListener('submit', (e) => {
            const form = e.target;

            // 이미 처리 중이면 중복 제출 방지
            if (form.classList.contains('submitting')) {
                e.preventDefault();
                return;
            }

            form.classList.add('submitting');

            // 제출 버튼 찾기
            const submitBtn = form.querySelector('button[type="submit"]');
            if (submitBtn && !submitBtn.dataset.originalText) {
                submitBtn.dataset.originalText = submitBtn.innerHTML;
                submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>처리 중...';
                submitBtn.disabled = true;
            }

            window.showLoading('처리 중입니다...');
        });

        // 페이지 이동 시 자동으로 로딩 숨김
        window.addEventListener('beforeunload', () => {
            window.hideLoading();
        });
    }
}

// Django 메시지를 토스트로 변환
document.addEventListener('DOMContentLoaded', () => {
    // Django messages를 토스트로 표시
    const djangoMessages = document.querySelectorAll('.alert[role="alert"]');
    djangoMessages.forEach(alert => {
        const type = alert.className.includes('alert-success') ? 'success' :
                     alert.className.includes('alert-danger') ? 'error' :
                     alert.className.includes('alert-warning') ? 'warning' : 'info';

        const message = alert.textContent.trim();
        if (message) {
            window.showToast(message, type);
            alert.style.display = 'none'; // 원본 숨김
        }
    });
});

// 자동 초기화
const uxEnhancements = new UXEnhancements();

// Export
window.UXEnhancements = UXEnhancements;
