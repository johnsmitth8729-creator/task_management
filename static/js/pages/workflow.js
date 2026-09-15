/**
 * Phase 4 — Workflow JS
 * Progress slider, assign employee modal, confirmation wiring
 */

/* ─── Progress slider live update ───────────────────────────── */
function initProgressSlider() {
    var slider = document.getElementById('progressSlider');
    var display = document.getElementById('progressDisplay');
    var hiddenInput = document.getElementById('progressValue');
    if (!slider) return;

    function update(val) {
        val = Math.max(0, Math.min(100, parseInt(val)));
        display.textContent = val + '%';
        hiddenInput.value = val;

        var fill = document.getElementById('progressBarFill');
        if (fill) {
            fill.style.width = val + '%';
            fill.className = 'wf-progress-bar-fill';
            if (val === 100) fill.classList.add('fill-complete');
            else if (val >= 50) fill.classList.add('fill-warning');
        }
    }

    slider.addEventListener('input', function () { update(this.value); });
    update(slider.value);
}

/* ─── Employee search in assign modal ───────────────────────── */
function initEmployeeSearch() {
    var searchInput = document.getElementById('employeeSearch');
    if (!searchInput) return;
    searchInput.addEventListener('input', function () {
        var term = this.value.toLowerCase();
        document.querySelectorAll('.employee-assign-item').forEach(function (item) {
            var name = (item.dataset.name || '').toLowerCase();
            var pos  = (item.dataset.position || '').toLowerCase();
            item.style.display = (name.includes(term) || pos.includes(term)) ? '' : 'none';
        });
    });
}

/* ─── Select All employees in modal ─────────────────────────── */
function initSelectAll() {
    var selectAll = document.getElementById('selectAllEmployees');
    if (!selectAll) return;
    selectAll.addEventListener('change', function () {
        document.querySelectorAll('.employee-checkbox:not([disabled])').forEach(function (cb) {
            cb.checked = selectAll.checked;
        });
    });
}

/* ─── INIT ───────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', function () {
    initProgressSlider();
    initEmployeeSearch();
    initSelectAll();
});
