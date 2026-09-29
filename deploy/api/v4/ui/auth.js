/* MedButler 认证模块：登录 / 注册 / 退出（自包含，不碰报告解读逻辑） */
(function () {
    'use strict';

    const authArea = document.getElementById('authArea');

    function renderAuth(user) {
        authArea.innerHTML = '';
        if (user) {
            const info = document.createElement('span');
            info.className = 'auth-user';
            info.textContent = user.username + (user.role === 'admin' ? '（管理员）' : '');
            const btn = document.createElement('button');
            btn.className = 'auth-btn';
            btn.textContent = '退出';
            btn.onclick = async () => {
                await fetch('/api/auth/logout', { method: 'POST' });
                renderAuth(null);
            };
            authArea.appendChild(info);
            authArea.appendChild(btn);
        } else {
            const loginBtn = document.createElement('button');
            loginBtn.className = 'auth-btn';
            loginBtn.textContent = '登录';
            loginBtn.onclick = () => openModal('login');
            const regBtn = document.createElement('button');
            regBtn.className = 'auth-btn auth-btn-primary';
            regBtn.textContent = '注册';
            regBtn.onclick = () => openModal('register');
            authArea.appendChild(loginBtn);
            authArea.appendChild(regBtn);
        }
    }

    function openModal(mode) {
        const old = document.getElementById('authModal');
        if (old) old.remove();

        const overlay = document.createElement('div');
        overlay.id = 'authModal';
        overlay.className = 'auth-overlay';
        overlay.innerHTML = `
            <div class="auth-modal">
                <button class="auth-close" id="authClose">×</button>
                <div class="auth-tabs">
                    <button data-mode="login">登录</button>
                    <button data-mode="register">注册</button>
                </div>
                <div class="auth-form">
                    <input type="text" id="authUsername" placeholder="用户名（3-32 位）" autocomplete="username">
                    <input type="password" id="authPassword" placeholder="密码（至少 6 位）" autocomplete="current-password">
                    <div class="auth-error" id="authError"></div>
                    <button class="auth-submit" id="authSubmit">登 录</button>
                </div>
            </div>`;

        const submit = overlay.querySelector('#authSubmit');
        const errEl = overlay.querySelector('#authError');
        let mode_ = mode;

        function setMode(m) {
            mode_ = m;
            overlay.querySelectorAll('.auth-tabs button').forEach(b =>
                b.classList.toggle('active', b.dataset.mode === m)
            );
            submit.textContent = m === 'login' ? '登 录' : '注 册';
        }
        setMode(mode);

        overlay.querySelectorAll('.auth-tabs button').forEach(b => {
            b.onclick = () => { errEl.textContent = ''; setMode(b.dataset.mode); };
        });
        overlay.querySelector('#authClose').onclick = () => overlay.remove();
        overlay.onclick = e => { if (e.target === overlay) overlay.remove(); };

        async function doSubmit() {
            const username = overlay.querySelector('#authUsername').value.trim();
            const password = overlay.querySelector('#authPassword').value;
            if (!username || !password) { errEl.textContent = '请填写用户名和密码'; return; }
            submit.disabled = true;
            errEl.textContent = '';
            try {
                const resp = await fetch('/api/auth/' + mode_, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password }),
                });
                const data = await resp.json().catch(() => ({}));
                if (!resp.ok) {
                    errEl.textContent = data.detail || '操作失败，请重试';
                } else {
                    overlay.remove();
                    renderAuth({ username: data.username, role: data.role });
                }
            } catch (e) {
                errEl.textContent = '网络异常，请重试';
            }
            submit.disabled = false;
        }
        submit.onclick = doSubmit;
        overlay.querySelector('#authPassword').addEventListener('keydown', e => {
            if (e.key === 'Enter') doSubmit();
        });

        document.body.appendChild(overlay);
    }

    // 初始化：查询当前登录状态
    fetch('/api/auth/me')
        .then(r => (r.ok ? r.json() : null))
        .then(renderAuth)
        .catch(() => renderAuth(null));
})();
