/* ============================================================
   MedButler 报告存档视图：历史报告列表 + 回看 + 删除
   视图壳与认证在 auth.js（window.MedShell），openConversation 在 script.js
   ============================================================ */
(function () {
    'use strict';

    const reportView = document.getElementById('reportArchiveView');
    const reportGrid = document.getElementById('reportGrid');
    const reportMsg = document.getElementById('reportMsg');
    const reportBack = document.getElementById('reportBack');
    const reportEntry = document.getElementById('reportEntry');

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, c => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
        ));
    }

    // 入口：登录后显示「报告存档」
    function refreshEntry() {
        const u = (window.MedShell && window.MedShell.getUser && window.MedShell.getUser()) || null;
        if (reportEntry) reportEntry.style.display = u ? '' : 'none';
    }

    // 包装登录态变化回调：刷新入口
    const origOnAuth = window.MedShell && window.MedShell.onAuthChanged;
    window.MedShell.onAuthChanged = function (user) {
        if (typeof origOnAuth === 'function') origOnAuth(user);
        refreshEntry();
    };

    if (reportEntry) {
        reportEntry.onclick = () => { window.MedShell.showView('reports'); loadReports(); };
    }
    if (reportBack) {
        reportBack.onclick = () => window.MedShell.showView('app');
    }

    async function loadReports() {
        if (reportMsg) reportMsg.textContent = '加载中…';
        try {
            const resp = await fetch('/api/chat/reports');
            if (!resp.ok) {
                if (reportMsg) reportMsg.textContent = '加载失败（' + resp.status + '）';
                return;
            }
            const data = await resp.json();
            renderReports(data.items || []);
            if (reportMsg) reportMsg.textContent = '';
        } catch (e) {
            if (reportMsg) reportMsg.textContent = '网络异常';
        }
    }

    function renderReports(items) {
        if (!reportGrid) return;
        reportGrid.innerHTML = '';
        if (!items.length) {
            reportGrid.innerHTML = '<div class="report-empty">还没有已解读的报告。去「健康对话」上传一张报告图片试试。</div>';
            return;
        }
        items.forEach(it => {
            const card = document.createElement('div');
            card.className = 'report-card';
            const thumb = it.thumb
                ? '<img class="report-thumb" src="/api/chat/media/' + encodeURI(it.thumb) + '" alt="报告缩略图" loading="lazy">'
                : '<div class="report-thumb report-thumb--empty">📄</div>';
            card.innerHTML =
                thumb +
                '<div class="report-meta">' +
                    '<div class="report-title">' + escapeHtml(it.title || '未命名报告') + '</div>' +
                    '<div class="report-date">' + escapeHtml(it.updated_at || '') + '</div>' +
                '</div>' +
                '<button class="report-del" title="删除该报告">×</button>';
            // 点击卡片（除删除按钮外）回看
            card.onclick = (e) => {
                if (e.target.classList.contains('report-del')) return;
                openReport(it.id);
            };
            card.querySelector('.report-del').onclick = (e) => {
                e.stopPropagation();
                deleteReport(it.id);
            };
            reportGrid.appendChild(card);
        });
    }

    function openReport(convId) {
        // 回到对话视图并加载该会话（原图 + 转录 + 解读）
        window.MedShell.showView('app');
        if (window.MedShell.openConversation) window.MedShell.openConversation(convId);
        else window.location.reload();
    }

    async function deleteReport(convId) {
        if (!confirm('删除这份报告及其解读？此操作不可恢复。')) return;
        try {
            const resp = await fetch('/api/chat/conversations/' + encodeURIComponent(convId), { method: 'DELETE' });
            if (!resp.ok) {
                if (reportMsg) reportMsg.textContent = '删除失败（' + resp.status + '）';
                return;
            }
            loadReports();
        } catch (e) {
            if (reportMsg) reportMsg.textContent = '网络异常';
        }
    }

    // 初始化兜底：登录态可能在 report.js 加载前已确定
    refreshEntry();
})();
