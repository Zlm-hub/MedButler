/* ============================================================
   MedButler 视图壳：主界面 / 登录注册 / 个人中心 + 认证逻辑
   （对话与报告逻辑在 script.js，通过 window.MedShell 通信）
   ============================================================ */
(function () {
    'use strict';

    const views = {
        app: document.getElementById('appView'),
        auth: document.getElementById('authView'),
        profile: document.getElementById('profileView'),
    };
    let currentUser = null;
    let authMode = 'login';

    /* ---------- 视图切换 ---------- */
    function showView(name) {
        Object.entries(views).forEach(([k, el]) => el.classList.toggle('hidden', k !== name));
        if (name === 'profile') renderProfile();
    }
    window.MedShell = { showView, getUser: () => currentUser };

    // 登录态变更时通知下游（script.js 挂 window.MedShell.onAuthChanged）
    function notifyAuthChanged() {
        if (typeof window.MedShell.onAuthChanged === 'function') {
            window.MedShell.onAuthChanged(currentUser);
        }
    }

    /* ---------- 侧栏用户区 ---------- */
    function renderSidebarUser() {
        const box = document.getElementById('sidebarUser');
        if (currentUser) {
            box.innerHTML = `
                <div class="user-line">
                    <div class="user-avatar">🙂</div>
                    <div class="user-info">
                        <span class="user-name">${escapeHtml(currentUser.username)}</span>
                        <span class="user-role">${currentUser.role === 'admin' ? '管理员' : '普通用户'}</span>
                    </div>
                </div>`;
        } else {
            box.innerHTML = `
                <div class="auth-links">
                    <a id="sideLogin">登录</a>
                    <a id="sideRegister">注册</a>
                </div>`;
            box.querySelector('#sideLogin').onclick = () => openAuth('login');
            box.querySelector('#sideRegister').onclick = () => openAuth('register');
        }
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, c => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
        ));
    }

    /* ---------- 登录 / 注册页 ---------- */
    function openAuth(mode) {
        authMode = mode;
        document.getElementById('authError').textContent = '';
        document.getElementById('authUsername').value = '';
        document.getElementById('authPassword').value = '';
        setAuthMode(mode);
        showView('auth');
        document.getElementById('authUsername').focus();
    }

    function setAuthMode(mode) {
        authMode = mode;
        document.getElementById('tabLogin').classList.toggle('active', mode === 'login');
        document.getElementById('tabRegister').classList.toggle('active', mode === 'register');
        document.getElementById('authSubmit').textContent = mode === 'login' ? '登 录' : '注 册';
    }

    async function doAuthSubmit() {
        const username = document.getElementById('authUsername').value.trim();
        const password = document.getElementById('authPassword').value;
        const errEl = document.getElementById('authError');
        const btn = document.getElementById('authSubmit');
        if (!username || !password) { errEl.textContent = '请填写用户名和密码'; return; }
        btn.disabled = true;
        errEl.textContent = '';
        try {
            const resp = await fetch('/api/auth/' + authMode, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password }),
            });
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                errEl.textContent = data.detail || '操作失败，请重试';
            } else {
                currentUser = { username: data.username, role: data.role };
                renderSidebarUser();
                showView('app');
                notifyAuthChanged();
            }
        } catch (e) {
            errEl.textContent = '网络异常，请重试';
        }
        btn.disabled = false;
    }

    /* ---------- 个人中心 ---------- */
    async function renderProfile() {
        const box = document.getElementById('sidebarUser');
        box.innerHTML = '';  // 占位，保持布局稳定
        let user = currentUser;
        if (!user) {
            const resp = await fetch('/api/auth/me').catch(() => null);
            if (resp && resp.ok) {
                user = currentUser = await resp.json();
            }
        }
        if (!user) { showView('auth'); return; }

        document.getElementById('profileUsername').textContent = user.username;
        document.getElementById('profileRole').textContent = user.role === 'admin' ? '管理员' : '普通用户';
        document.getElementById('profileMeta').textContent =
            '注册时间：' + (user.created_at || '未知');
        document.getElementById('statReports').textContent = localStorage.getItem('medbutler_stat_reports') || '0';
        document.getElementById('statChats').textContent = localStorage.getItem('medbutler_stat_chats') || '0';
        renderSidebarUser();
    }

    async function logout() {
        await fetch('/api/auth/logout', { method: 'POST' }).catch(() => {});
        currentUser = null;
        renderSidebarUser();
        notifyAuthChanged();
        openAuth('login');
    }

    /* ---------- 事件绑定 ---------- */
    document.getElementById('tabLogin').onclick = () => setAuthMode('login');
    document.getElementById('tabRegister').onclick = () => setAuthMode('register');
    document.getElementById('authSubmit').onclick = doAuthSubmit;
    document.getElementById('authPassword').addEventListener('keydown', e => {
        if (e.key === 'Enter') doAuthSubmit();
    });
    document.getElementById('authBack').onclick = () => showView('app');
    document.getElementById('profileBack').onclick = () => showView('app');
    document.getElementById('profileLogout').onclick = logout;
    document.getElementById('profileEntry').onclick = () => showView('profile');

    /* ---------- 初始化 ---------- */
    fetch('/api/auth/me')
        .then(r => (r.ok ? r.json() : null))
        .then(user => {
            currentUser = user;
            renderSidebarUser();
            notifyAuthChanged();
            // 深链：#/auth 直接打开登录页（未登录时）
            if (location.hash === '#auth' && !user) openAuth('login');
        })
        .catch(() => renderSidebarUser());
})();
