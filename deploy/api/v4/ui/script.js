/* ============================================================
   MedButler 对话逻辑：健康问答（/chat）+ 报告解读（/image）
   视图壳与认证在 auth.js（window.MedShell）
   ============================================================ */
(function () {
    'use strict';

    const chatScroll = document.getElementById('chatScroll');
    const welcomeBlock = document.getElementById('welcomeBlock');
    const textInput = document.getElementById('textInput');
    const sendBtn = document.getElementById('sendBtn');
    const attachBtn = document.getElementById('attachBtn');
    const imageInput = document.getElementById('imageInput');
    const previewRow = document.getElementById('previewRow');
    const previewImg = document.getElementById('previewImg');
    const removeImageBtn = document.getElementById('removeImageBtn');

    let imageData = null;      // 选中的图片 File
    let history = [];          // 未登录时的前端内存记忆 [{role, content}]
    let busy = false;
    let currentConvId = '';    // 登录用户的当前会话 ID（服务端记忆）

    /* ---------- 工具 ---------- */
    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, c => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
        ));
    }

    function convertMarkdownToHtml(md) {
        let html = escapeHtml(md);
        html = html.replace(/^###\s*(.*$)/gm, '<h3>$1</h3>')
                   .replace(/^##\s*(.*$)/gm, '<h3>$1</h3>')
                   .replace(/^#\s*(.*$)/gm, '<h3>$1</h3>');
        html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        // 列表项（容错：模型偶尔漏掉 - 后的空格）
        html = html.replace(/^\s*-\s*(.*)$/gm, '<li>$1</li>');
        html = html.replace(/(<li>[\s\S]*?<\/li>)(?!\s*<li>)/g, '<ul>$1</ul>');
        html = html.replace(/(<\/ul>)\s*<ul>/g, '$1');
        // 换行 -> <br>
        html = html.replace(/ {2}\n/g, '<br>').replace(/\n/g, '<br>');
        return html;
    }

    function scrollBottom() { chatScroll.scrollTop = chatScroll.scrollHeight; }

    function hideWelcome() { if (welcomeBlock) welcomeBlock.style.display = 'none'; }

    function showWelcome() {
        if (welcomeBlock) welcomeBlock.style.display = '';
        chatScroll.querySelectorAll('.msg').forEach(m => m.remove());
        history = [];
    }

    function userInitial() {
        const u = (window.MedShell && window.MedShell.getUser && window.MedShell.getUser()) || null;
        const name = (u && u.username) || '';
        return name ? name.charAt(0).toUpperCase() : '我';
    }

    /* ---------- 会话记录（登录用户） ---------- */
    const convSection = document.getElementById('convSection');
    const convList = document.getElementById('convList');

    function loggedIn() {
        return !!(window.MedShell && window.MedShell.getUser && window.MedShell.getUser());
    }

    function markActiveConv(convId) {
        convList.querySelectorAll('.conv-item').forEach(el => {
            el.classList.toggle('active', el.dataset.conv === convId);
        });
    }

    async function refreshConvList() {
        if (!loggedIn()) {
            convSection.style.display = 'none';
            convList.innerHTML = '';
            return;
        }
        convSection.style.display = '';
        let items = [];
        try {
            const resp = await fetch('/api/chat/conversations');
            if (resp.ok) items = (await resp.json()).items || [];
        } catch (e) { return; }
        convList.innerHTML = '';
        if (!items.length) {
            const tip = document.createElement('div');
            tip.className = 'conv-empty';
            tip.textContent = '还没有会话记录';
            convList.appendChild(tip);
            return;
        }
        items.forEach(it => {
            const div = document.createElement('div');
            div.className = 'conv-item';
            div.dataset.conv = it.id;
            div.title = it.title + ' · ' + (it.updated_at || '');
            div.innerHTML = `<span class="conv-title">${escapeHtml(it.title)}</span><span class="conv-del" title="删除会话">×</span>`;
            div.onclick = (e) => {
                if (e.target.classList.contains('conv-del')) return;
                openConversation(it.id);
            };
            div.querySelector('.conv-del').onclick = () => deleteConversation(it.id);
            convList.appendChild(div);
        });
        markActiveConv(currentConvId);
    }

    async function deleteConversation(convId) {
        if (busy) return;
        if (!confirm('删除这条会话及其全部消息？')) return;
        try {
            const resp = await fetch(`/api/chat/conversations/${convId}`, { method: 'DELETE' });
            if (resp.ok && convId === currentConvId) {
                currentConvId = '';
                showWelcome();
            }
        } catch (e) {}
        refreshConvList();
    }

    async function openConversation(convId) {
        if (busy || convId === currentConvId) return;
        let data = null;
        try {
            const resp = await fetch(`/api/chat/conversations/${convId}/messages`);
            if (!resp.ok) { refreshConvList(); return; }
            data = await resp.json();
        } catch (e) { return; }
        currentConvId = convId;
        history = [];  // 登录态下服务端记忆接管
        clearImage();
        hideWelcome();
        chatScroll.querySelectorAll('.msg').forEach(m => m.remove());
        (data.messages || []).forEach(m => {
            if (m.role === 'user') addUserMsg(m.content, m.image_path ? '/api/chat/media/' + m.image_path : '');
            else if (m.role === 'assistant') addAssistantText(m.content);
        });
        markActiveConv(convId);
        scrollBottom();
    }

    // 登录态变化（auth.js 通知）：刷新侧栏会话区；登出则清空本地状态
    window.MedShell.onAuthChanged = (user) => {
        currentConvId = '';
        if (!user) showWelcome();
        refreshConvList();
    };

    function addUserMsg(text, imageUrl) {
        const div = document.createElement('div');
        div.className = 'msg user';
        let inner = '';
        if (imageUrl) inner += `<img class="chat-img" src="${imageUrl}" alt="上传的报告图片">`;
        if (text) inner += `<div class="msg-text">${escapeHtml(text).replace(/\n/g, '<br>')}</div>`;
        if (!inner) inner = '<div class="msg-text">（上传了一张报告图片）</div>';
        div.innerHTML = `<div class="bubble">${inner}</div><div class="avatar user-av">${escapeHtml(userInitial())}</div>`;
        chatScroll.appendChild(div);
        scrollBottom();
    }

    function addAssistantMsg() {
        const div = document.createElement('div');
        div.className = 'msg assistant';
        div.innerHTML = `<div class="avatar ai"><img src="logo-mark.png" alt="MedButler"></div><div class="bubble"><p class="thinking-hint" style="color:#9fb5b0">思考中…</p></div>`;
        chatScroll.appendChild(div);
        scrollBottom();
        return div.querySelector('.bubble');
    }

    function addAssistantText(text) {
        const div = document.createElement('div');
        div.className = 'msg assistant';
        div.innerHTML = `<div class="avatar ai"><img src="logo-mark.png" alt="MedButler"></div><div class="bubble">${convertMarkdownToHtml(text)}</div>`;
        chatScroll.appendChild(div);
    }

    function setCount(key, inc) {
        localStorage.setItem(key, String(parseInt(localStorage.getItem(key) || '0', 10) + (inc ? 1 : 0)));
    }

    /* ---------- 输入状态 ---------- */
    function refreshSendState() {
        sendBtn.disabled = busy || !(textInput.value.trim() || imageData);
    }

    textInput.addEventListener('input', refreshSendState);
    textInput.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); sendMessage(); }
    });
    sendBtn.onclick = sendMessage;
    attachBtn.onclick = () => imageInput.click();
    removeImageBtn.onclick = clearImage;
    imageInput.addEventListener('change', () => {
        const file = imageInput.files && imageInput.files[0];
        if (!file) return;
        imageData = file;
        previewImg.src = URL.createObjectURL(file);
        previewRow.style.display = '';
        attachBtn.classList.add('has-image');
        refreshSendState();
    });
    function clearImage() {
        imageData = null;
        imageInput.value = '';
        previewRow.style.display = 'none';
        attachBtn.classList.remove('has-image');
        refreshSendState();
    }

    document.getElementById('newChatBtn').onclick = () => {
        if (busy) return;
        clearImage();
        textInput.value = '';
        refreshSendState();
        showWelcome();
        currentConvId = '';   // 下一条消息自动开新会话（懒创建，避免空会话占位）
        markActiveConv('');
    };

    // 欢迎卡片：聚焦输入框
    document.querySelectorAll('.feature-card[data-feature]').forEach(card => {
        card.onclick = () => textInput.focus();
    });

    /* ---------- 发送入口 ---------- */
    function sendMessage() {
        if (busy) return;
        const text = textInput.value.trim();
        if (imageData) { sendImage(text); }
        else if (text) { sendChat(text); }
    }

    /* ============ 健康问答（/chat） ============ */
    async function sendChat(message) {
        busy = true;
        refreshSendState();
        hideWelcome();
        addUserMsg(message);
        textInput.value = '';
        const bubble = addAssistantMsg();

        try {
            const resp = await fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message,
                    history: history.slice(-10),
                    conversation_id: currentConvId,
                }),
            });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);

            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '', answer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();
                for (const line of lines) {
                    if (!line.trim()) continue;
                    let ev;
                    try { ev = JSON.parse(line); } catch (e) { continue; }
                    if (ev.stage === 'delta' && ev.text) {
                        if (!answer) bubble.innerHTML = '';
                        answer += ev.text;
                        bubble.innerHTML = convertMarkdownToHtml(answer);
                        scrollBottom();
                    } else if (ev.stage === 'reset') {
                        // 后端检测到复读循环换温度重试：清掉半成品，给出提示而不是让内容突然变报错
                        answer = '';
                        bubble.innerHTML = '<p class="thinking-hint" style="color:#9fb5b0">回答出现循环，正在换个思路重试…</p>';
                    } else if (ev.stage === 'conv' && ev.id) {
                        currentConvId = ev.id;
                        markActiveConv(ev.id);
                    } else if (ev.stage === 'error') {
                        bubble.innerHTML = `<span style="color:#dc2626">出错了：${escapeHtml(ev.detail || '未知错误')}</span>`;
                    }
                }
            }

            if (answer) {
                history.push({ role: 'user', content: message });
                history.push({ role: 'assistant', content: answer });
                setCount('medbutler_stat_chats', true);
            }
        } catch (e) {
            bubble.innerHTML = `<span style="color:#dc2626">网络异常：${escapeHtml(String(e))}</span>`;
        }
        busy = false;
        refreshSendState();
        if (loggedIn()) refreshConvList();
    }

    /* ============ 报告解读（/image） ============ */
    async function sendImage(caption) {
        busy = true;
        refreshSendState();
        hideWelcome();
        addUserMsg(caption || '', URL.createObjectURL(imageData));
        textInput.value = '';

        const bubble = addAssistantMsg();
        let analysisText = '';
        let suggestionText = '';
        let recSection = null;

        try {
            const formData = new FormData();
            formData.append('files', imageData, imageData.name || 'report.jpg');
            formData.append('conversation_id', currentConvId);

            const resp = await fetch('/image', { method: 'POST', body: formData });
            if (!resp.ok) throw new Error('HTTP ' + resp.status);

            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();
                for (const line of lines) {
                    if (!line.trim()) continue;
                    let ev;
                    try { ev = JSON.parse(line); } catch (e) { continue; }

                    switch (ev.stage) {
                        case 'analysis_delta':
                            if (!analysisText) bubble.innerHTML = '';
                            analysisText += ev.text;
                            bubble.innerHTML = convertMarkdownToHtml(analysisText);
                            scrollBottom();
                            break;
                        case 'analysis':
                            analysisText = ev.data || '';
                            bubble.innerHTML = convertMarkdownToHtml(analysisText);
                            scrollBottom();
                            break;
                        case 'vl_retry':
                            analysisText = '';
                            bubble.innerHTML = `<p class="thinking-hint" style="color:#9fb5b0">识别不理想，自动重试第 ${ev.attempt} 次…</p>`;
                            break;
                        case 'recommendations_delta':
                            if (!recSection) {
                                recSection = document.createElement('div');
                                recSection.className = 'section-title';
                                recSection.textContent = '💡 解读与建议';
                                bubble.appendChild(recSection);
                                suggestionText = '';
                            }
                            suggestionText += ev.text;
                            renderSuggestion(bubble, suggestionText);
                            scrollBottom();
                            break;
                        case 'recommendations':
                            suggestionText = ev.data || '';
                            renderSuggestion(bubble, suggestionText);
                            scrollBottom();
                            break;
                        case 'conv':
                            if (ev.id) {
                                currentConvId = ev.id;
                                markActiveConv(ev.id);
                            }
                            break;
                        case 'error':
                            if (!analysisText && !suggestionText) {
                                bubble.innerHTML = `<span style="color:#dc2626">出错了：${escapeHtml(ev.detail || '未知错误')}</span>`;
                            } else {
                                const errLine = document.createElement('div');
                                errLine.style.color = '#dc2626';
                                errLine.style.fontSize = '12px';
                                errLine.textContent = ev.detail || '处理出错';
                                bubble.appendChild(errLine);
                            }
                            break;
                        case 'done':
                            break;
                    }
                }
            }

            if (suggestionText) {
                history.push({ role: 'user', content: '（我上传了一张报告图片，以下是解读）' });
                history.push({ role: 'assistant', content: suggestionText });
                setCount('medbutler_stat_reports', true);
            }
            clearImage();
        } catch (e) {
            bubble.innerHTML = `<span style="color:#dc2626">网络异常：${escapeHtml(String(e))}</span>`;
            clearImage();
        }
        busy = false;
        refreshSendState();
        if (loggedIn()) refreshConvList();
    }

    function renderSuggestion(bubble, text) {
        let el = bubble.querySelector('.suggestion-body');
        if (!el) {
            el = document.createElement('div');
            el.className = 'suggestion-body';
            bubble.appendChild(el);
        }
        el.innerHTML = convertMarkdownToHtml(text);
    }
})();
