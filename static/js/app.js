document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.querySelector('#togglePassword');
    const password = document.querySelector('#id_password');

    if (!toggle || !password) {
        return;
    }

    toggle.addEventListener('click', () => {
        const isPassword = password.getAttribute('type') === 'password';
        password.setAttribute('type', isPassword ? 'text' : 'password');
        const icon = toggle.querySelector('i');
        if (icon) {
            icon.className = isPassword ? 'bi bi-eye-slash' : 'bi bi-eye';
        }
    });
});

