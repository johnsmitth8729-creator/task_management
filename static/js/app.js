/**
 * TASK MANAGEMENT — app.js  v4
 * Dark Mode | Confirmation Dialogs
 */

var THEME_KEY = 'tm_app_theme';

/* ─── THEME ──────────────────────────────────────────────── */

function _applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(THEME_KEY, theme);

    var icon = document.querySelector('#themeToggleBtn i');
    if (icon) {
        icon.className = (theme === 'dark')
            ? 'bi bi-sun-fill fs-5'
            : 'bi bi-moon-stars-fill fs-5';
    }
    var btn = document.getElementById('themeToggleBtn');
    if (btn) {
        btn.title = (theme === 'dark') ? 'Light mode' : 'Dark mode';
    }
}

/* Called from onclick="toggleAppTheme()" on the button AND from JS init */
function toggleAppTheme() {
    var current = document.documentElement.getAttribute('data-theme') || 'light';
    _applyTheme(current === 'dark' ? 'light' : 'dark');
}

/* ─── CONFIRMATION MODAL ─────────────────────────────────── */

function confirmAction(formOrOpts, message, yesLabel) {
    var form = null;
    var msg = message || 'Are you sure you want to perform this action?';
    var yes = yesLabel || 'Yes';
    var title = 'Confirm Action';
    var onConfirmCallback = null;
    var isDanger = true;

    if (formOrOpts && typeof formOrOpts === 'object' && !(formOrOpts instanceof HTMLElement)) {
        // Options object: { formId: '...', form: '...', message: '...', confirmText: '...', title: '...', onConfirm: fn }
        if (formOrOpts.formId) {
            form = document.getElementById(formOrOpts.formId);
        } else if (formOrOpts.form) {
            form = (typeof formOrOpts.form === 'string')
                ? document.getElementById(formOrOpts.form)
                : formOrOpts.form;
        }
        if (typeof formOrOpts.onConfirm === 'function') {
            onConfirmCallback = formOrOpts.onConfirm;
        }
        msg = formOrOpts.message || msg;
        title = formOrOpts.title || title;
        yes = formOrOpts.confirmText || formOrOpts.yesLabel || yes;
        if (formOrOpts.isDanger !== undefined) {
            isDanger = formOrOpts.isDanger;
        }
    } else if (typeof formOrOpts === 'string') {
        form = document.getElementById(formOrOpts) || document.querySelector(formOrOpts);
    } else if (formOrOpts instanceof HTMLElement) {
        form = (formOrOpts.tagName === 'FORM') ? formOrOpts : formOrOpts.closest('form');
    }

    // If form has invalid fields (e.g. required textarea is empty), report validity first
    if (form && typeof form.reportValidity === 'function') {
        if (!form.reportValidity()) {
            return;
        }
    }

    var modalEl = document.getElementById('confirmModal');
    if (!modalEl) {
        if (onConfirmCallback) {
            onConfirmCallback();
        } else if (form) {
            form.submit();
        }
        return;
    }

    var titleEl = document.getElementById('confirmModalLabel');
    var bodyEl  = document.getElementById('confirmModalBody');
    var yesBtnEl = document.getElementById('confirmModalYesBtn');

    if (titleEl) {
        titleEl.innerHTML = '<i class="bi bi-exclamation-triangle-fill text-warning me-2"></i>' + title;
    }
    if (bodyEl)   bodyEl.textContent = msg;
    if (yesBtnEl) {
        yesBtnEl.textContent = yes;
        yesBtnEl.className = isDanger ? 'btn btn-danger' : 'btn btn-primary';
    }

    /* clone to remove previous listeners */
    var fresh = yesBtnEl.cloneNode(true);
    yesBtnEl.parentNode.replaceChild(fresh, yesBtnEl);
    fresh.addEventListener('click', function () {
        fresh.disabled = true;
        var modalInst = bootstrap.Modal.getInstance(modalEl);
        if (modalInst) modalInst.hide();
        if (onConfirmCallback) {
            onConfirmCallback();
        } else if (form) {
            form.submit();
        }
    });

    bootstrap.Modal.getOrCreateInstance(modalEl).show();
}

/* ─── data-confirm auto-wiring ───────────────────────────── */

function _initConfirm() {
    document.querySelectorAll('[data-confirm]').forEach(function (el) {
        el.addEventListener('click', function (e) {
            var form = el.closest('form');
            if (!form) return;
            e.preventDefault();
            confirmAction({
                form: form,
                title: el.getAttribute('data-confirm-title') || 'Confirm Action',
                message: el.getAttribute('data-confirm'),
                confirmText: el.getAttribute('data-confirm-yes') || 'Yes'
            });
        });
    });
}

/* ─── SIDEBAR & NAVIGATION ───────────────────────────────── */

var SIDEBAR_COLLAPSED_KEY = 'tm_sidebar_collapsed';
var _sidebarTooltipInstances = [];

/**
 * Toggle desktop sidebar global collapse state
 */
function toggleSidebarCollapse() {
    var isCollapsed = document.documentElement.classList.toggle('sidebar-collapsed');
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, isCollapsed ? 'true' : 'false');

    var btn = document.getElementById('sidebarCollapseToggle');
    if (btn) {
        btn.setAttribute('aria-expanded', isCollapsed ? 'false' : 'true');
    }

    _initSidebarTooltips();
}

/**
 * Initialize tooltips on desktop icon-only sidebar (rail mode)
 */
function _initSidebarTooltips() {
    var isDesktop = window.innerWidth >= 992;
    var isCollapsed = document.documentElement.classList.contains('sidebar-collapsed');

    var targetEls = document.querySelectorAll(
        '.app-sidebar .sidebar-section-link[data-bs-title], ' +
        '.app-sidebar .sidebar-account-footer [data-bs-title]'
    );

    targetEls.forEach(function (el) {
        var inst = bootstrap.Tooltip.getInstance(el);
        if (!inst && typeof bootstrap.Tooltip === 'function') {
            inst = new bootstrap.Tooltip(el, {
                placement: 'right',
                trigger: 'hover focus',
                boundary: 'window'
            });
            _sidebarTooltipInstances.push(inst);
        }
        if (inst) {
            if (isDesktop && isCollapsed) {
                inst.enable();
            } else {
                inst.hide();
                inst.disable();
            }
        }
    });
}

/**
 * Initialize sidebar navigation elements and mobile offcanvas dismissal
 */
function _initSidebarNav() {

    // Mobile sidebar auto-close on link navigation
    var mobileSidebarEl = document.getElementById('mobileSidebar');
    if (mobileSidebarEl) {
        mobileSidebarEl.querySelectorAll('.nav-link').forEach(function (link) {
            if (!link._hasOffcanvasClose) {
                link._hasOffcanvasClose = true;
                link.addEventListener('click', function () {
                    var inst = bootstrap.Offcanvas.getInstance(mobileSidebarEl);
                    if (inst) {
                        inst.hide();
                    }
                });
            }
        });
    }

    var collapseBtn = document.getElementById('sidebarCollapseToggle');
    if (collapseBtn) {
        var isCol = document.documentElement.classList.contains('sidebar-collapsed');
        collapseBtn.setAttribute('aria-expanded', isCol ? 'false' : 'true');
    }

    _initSidebarTooltips();
}

/* ─── PASSWORD VISIBILITY TOGGLE ─────────────────────────── */

function _initPasswordToggle() {
    var btn = document.getElementById('togglePassword');
    if (!btn) return;
    btn.addEventListener('click', function () {
        var input = btn.closest('.input-group') ? btn.closest('.input-group').querySelector('input') : null;
        if (!input) return;
        var isPassword = input.type === 'password';
        input.type = isPassword ? 'text' : 'password';
        var icon = btn.querySelector('i');
        if (icon) {
            icon.className = isPassword ? 'bi bi-eye-slash' : 'bi bi-eye';
        }
    });
}

/* ─── INIT ───────────────────────────────────────────────── */

(function () {
    /* Apply saved theme on every page load — syncs icon too */
    var saved = localStorage.getItem(THEME_KEY) ||
                (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');

    function _runAll() {
        _applyTheme(saved);
        _initConfirm();
        _initSidebarNav();
        _initPasswordToggle();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _runAll);
    } else {
        /* DOM already ready (script deferred / at end of body) */
        _runAll();
    }

    window.addEventListener('resize', function () {
        _initSidebarTooltips();
    });
})();

