/**
 * Operations Console (/control/) Vanilla JS Helper
 * - Responsive & Desktop sidebar toggle
 * - Alert dismissal
 * - CSRF token configuration for HTMX
 */

document.addEventListener("DOMContentLoaded", function () {
    // 1. Sidebar Toggle for Mobile & Desktop
    const sidebarToggle = document.getElementById("sidebarToggle") || document.getElementById("sidebar-toggle");
    const sidebar = document.getElementById("controlSidebar") || document.getElementById("control-sidebar");
    const overlay = document.getElementById("sidebarBackdrop") || document.getElementById("sidebar-overlay");
    const layout = document.querySelector(".control-layout") || document.querySelector(".app-container");

    // Restore desktop collapsed state if saved
    if (layout && localStorage.getItem("control_sidebar_collapsed") === "true") {
        layout.classList.add("sidebar-collapsed");
    }

    if (sidebarToggle && sidebar) {
        sidebarToggle.addEventListener("click", function () {
            const isMobile = window.innerWidth <= 992;
            if (isMobile) {
                const isExpanded = sidebar.classList.toggle("open");
                if (overlay) overlay.classList.toggle("active", isExpanded);
                sidebarToggle.setAttribute("aria-expanded", isExpanded ? "true" : "false");
            } else if (layout) {
                const isCollapsed = layout.classList.toggle("sidebar-collapsed");
                localStorage.setItem("control_sidebar_collapsed", isCollapsed ? "true" : "false");
            }
        });

        if (overlay) {
            overlay.addEventListener("click", function () {
                sidebar.classList.remove("open");
                overlay.classList.remove("active");
                sidebarToggle.setAttribute("aria-expanded", "false");
            });
        }
    }

    // 2. Alert Dismissal
    document.querySelectorAll(".alert-dismiss").forEach(function (btn) {
        btn.addEventListener("click", function () {
            const alert = btn.closest(".alert");
            if (alert) {
                alert.style.opacity = "0";
                setTimeout(function () {
                    alert.remove();
                }, 200);
            }
        });
    });

    // 3. Helper to read CSRF Cookie
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== "") {
            const cookies = document.cookie.split(";");
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + "=")) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    // 4. Inject CSRF Token into all HTMX requests
    document.body.addEventListener("htmx:configRequest", function (evt) {
        const csrfToken = getCookie("csrftoken") || (document.querySelector("[name=csrfmiddlewaretoken]") ? document.querySelector("[name=csrfmiddlewaretoken]").value : "");
        if (csrfToken) {
            evt.detail.headers["X-CSRFToken"] = csrfToken;
        }
    });

    // 5. HTMX Global Error Boundary Handler (ADM-10.6)
    document.body.addEventListener("htmx:responseError", function (evt) {
        const status = evt.detail.xhr ? evt.detail.xhr.status : 0;
        let msg = "حدث خطأ غير متوقع أثناء معالجة الطلب.";
        if (status === 400) {
            msg = "خطأ في البيانات المدخلة. يرجى مراجعة الحقول والمحاولة مجدداً.";
        } else if (status === 403) {
            msg = "ليس لديك الصلاحية الكافية لإتمام هذه العملية (403 Forbidden).";
        } else if (status === 404) {
            msg = "العنصر المطلوب غير موجود أو تم حذفه مسبقاً (404 Not Found).";
        } else if (status >= 500) {
            msg = "تعذر إتمام العملية بسبب خطأ في الخادم. تم توثيق الحدث للمراجعة.";
        }

        const container = document.querySelector(".messages-container") || document.querySelector(".control-content");
        if (container) {
            const alertDiv = document.createElement("div");
            alertDiv.className = "alert alert-error";
            alertDiv.style.margin = "1rem 0";
            alertDiv.innerHTML = '<div class="alert-content">' + msg + '</div><button type="button" class="alert-dismiss" aria-label="إغلاق">&times;</button>';
            container.prepend(alertDiv);
            alertDiv.querySelector(".alert-dismiss").addEventListener("click", function () {
                alertDiv.remove();
            });
        }
    });
});
