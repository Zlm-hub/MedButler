/* ============================================================
   MedButler 管理后台：用户列表 + 禁用/启用
   视图壳与认证在 auth.js（window.MedShell），本文件自包含
   ============================================================ */
(function () {
    'use strict';

    const adminView = document.getElementById('adminView');
    const adminListEl = document.getElementById('adminUserList');
    const adminMsg = document.getElementById('adminMsg');
    const adminEntry = document.getElementById('adminEntry');
    const adminBack = document.getElementById('adminBack');

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, c => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
        ));
    }

    // 入口：admin 登录后显示「管理后台」
    function refreshEntry() {
        const u = (window.MedShell && window.MedShell.getUser && window.MedShell.getUser()) || null;
        if (adminEntry) adminEntry.style.display = (u && u.role === 'admin') ? '' : 'none';
    }

    // 包装登录态变化回调：刷新入口；若非 admin 却停在管理页则退回首页
    const origOnAuth = window.MedShell && window.MedShell.onAuthChanged;
    window.MedShell.onAuthChanged = function (user) {
        if (typeof origOnAuth === 'function') origOnAuth(user);
        refreshEntry();
        if (adminView && !adminView.classList.contains('hidden') &&
            (!user || user.role !== 'admin')) {
            window.MedShell.showView('app');
        }
    };

    if (adminEntry) {
        adminEntry.onclick = () => { window.MedShell.showView('admin'); loadUsers(); };
    }
    if (adminBack) {
        adminBack.onclick = () => window.MedShell.showView('app');
    }

    async function loadUsers() {
        if (adminMsg) adminMsg.textContent = '加载中…';
        try {
            const resp = await fetch('/api/auth/admin/users');
            if (!resp.ok) {
                if (adminMsg) adminMsg.textContent = '加载失败（' + resp.status + '）';
                return;
            }
            const data = await resp.json();
            renderList(data.items || []);
            if (adminMsg) adminMsg.textContent = '';
        } catch (e) {
            if (adminMsg) adminMsg.textContent = '网络异常';
        }
    }

    function renderList(items) {
        if (!adminListEl) return;
        adminListEl.innerHTML = '';
        items.forEach(it => {
            const row = document.createElement('div');
            row.className = 'admin-row';
            const status = it.is_active
                ? '<span class="badge ok">正常</span>'
                : '<span class="badge off">已禁用</span>';
            const btn = it.is_active
                ? '<button class="adm-btn danger" data-u="' + escapeHtml(it.username) + '" data-act="disable">禁用</button>'
                : '<button class="adm-btn primary" data-u="' + escapeHtml(it.username) + '" data-act="enable">启用</button>';
            row.innerHTML =
                '<span class="adm-name">' + escapeHtml(it.username) + '</span>' +
                '<span class="adm-role">' + (it.role === 'admin' ? '管理员' : '用户') + '</span>' +
                '<span class="adm-time">' + (it.created_at || '') + '</span>' +
                '<span class="adm-status">' + status + '</span>' +
                '<span class="adm-act">' + btn + '</span>';
            adminListEl.appendChild(row);
        });
        adminListEl.querySelectorAll('button[data-u]').forEach(b => {
            b.onclick = () => toggleUser(b.dataset.u, b.dataset.act);
        });
    }

    async function toggleUser(username, act) {
        if (act === 'disable' &&
            !confirm('禁用用户「' + username + '」？\n禁用后该用户将无法登录（已登录会话仍在线直到过期）。')) return;
        try {
            const resp = await fetch(
                '/api/auth/admin/users/' + encodeURIComponent(username) + '/' + act,
                { method: 'POST' }
            );
            const data = await resp.json().catch(() => ({}));
            if (!resp.ok) {
                if (adminMsg) adminMsg.textContent = data.detail || '操作失败';
                return;
            }
            loadUsers();
        } catch (e) {
            if (adminMsg) adminMsg.textContent = '网络异常';
        }
    }

    // 初始化兜底：登录态可能在 admin.js 加载前已确定
    refreshEntry();
})();
