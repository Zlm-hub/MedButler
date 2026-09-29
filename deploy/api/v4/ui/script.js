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
    let history = [];          // 文字问答历史 [{role, content}]，供 /chat 多轮
    let busy = false;

    /* ---------- 工具 ---------- */
    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, c => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
        ));
    }

    function convertMarkdownToHtml(md) {
        let html = escapeHtml(md);
        html = html.replace(/^### (.*$)/gm, '<h3>$1</h3>')
                   .replace(/^## (.*$)/gm, '<h3>$1</h3>')
                   .replace(/^# (.*$)/gm, '<h3>$1</h3>');
        html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        // 列表项
        html = html.replace(/^- (.*)$/gm, '<li>$1</li>');
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

    function addUserMsg(text) {
        const div = document.createElement('div');
        div.className = 'msg user';
        div.innerHTML = `<div class="bubble">${escapeHtml(text).replace(/\n/g, '<br>')}</div>`;
        chatScroll.appendChild(div);
        scrollBottom();
    }

    function addAssistantMsg() {
        const div = document.createElement('div');
        div.className = 'msg assistant';
        div.innerHTML = `<div class="bubble"><p class="thinking-hint" style="color:#9fb5b0">思考中…</p></div>`;
        chatScroll.appendChild(div);
        scrollBottom();
        return div.querySelector('.bubble');
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
    };

    // 欢迎卡片 / 顶栏标签：聚焦输入框
    document.querySelectorAll('.feature-card[data-feature]').forEach(card => {
        card.onclick = () => textInput.focus();
    });
    document.querySelectorAll('.topbar-tabs .tab').forEach(tab => {
        tab.onclick = () => {
            document.querySelectorAll('.topbar-tabs .tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            textInput.focus();
        };
    });

    /* ---------- 发送入口 ---------- */
    function sendMessage() {
        if (busy) return;
        const text = textInput.value.trim();
        if (imageData) { sendImage(); }
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
    }

    /* ============ 报告解读（/image） ============ */
    async function sendImage() {
        busy = true;
        refreshSendState();
        hideWelcome();
        addUserMsg('（上传了一张报告图片）');
        textInput.value = '';

        const bubble = addAssistantMsg();
        let analysisText = '';
        let suggestionText = '';
        let recSection = null;

        try {
            const formData = new FormData();
            formData.append('files', imageData, imageData.name || 'report.jpg');

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
