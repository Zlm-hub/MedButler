document.addEventListener('DOMContentLoaded', function() {
    // 获取DOM元素
    const chatContainer = document.getElementById('chatContainer');
    const imageInput = document.getElementById('imageInput');
    const sendButton = document.getElementById('sendButton');
    const imagePreviewContainer = document.getElementById('imagePreviewContainer');
    const imagePreview = document.getElementById('imagePreview');
    const removeImageBtn = document.getElementById('removeImageBtn');

    let selectedImage = null;
    let timerInterval = null;

    // 选择图片事件
    imageInput.addEventListener('change', function(e) {
        if (e.target.files && e.target.files[0]) {
            const file = e.target.files[0];
            selectedImage = file;

            // 显示预览
            const reader = new FileReader();
            reader.onload = function(event) {
                imagePreview.src = event.target.result;
                imagePreviewContainer.style.display = 'inline-block';
                sendButton.disabled = false;
            };
            reader.readAsDataURL(file);
        }
    });

    // 移除图片事件
    removeImageBtn.addEventListener('click', function() {
        imageInput.value = '';
        selectedImage = null;
        imagePreviewContainer.style.display = 'none';
        sendButton.disabled = true;
    });

    // 发送图片事件
    sendButton.addEventListener('click', function() {
        if (selectedImage) {
            sendImageToServer(selectedImage);
        }
    });

    // 发送图片到服务器（流式：NDJSON 事件逐行消费，无整体超时限制）
    async function sendImageToServer(imageFile) {
        // 在聊天窗口显示用户发送的图片
        displayUserImage(imageFile);

        // 清除选择的图片
        imageInput.value = '';
        selectedImage = null;
        imagePreviewContainer.style.display = 'none';
        sendButton.disabled = true;

        // 显示等待动画
        const loadingMessageId = displayLoadingMessage();

        const formData = new FormData();
        formData.append('files', imageFile);

        // 流式渲染上下文
        let analysisBox = null;      // 分析消息框
        let thinkingEl = null;       // 思考过程区（浅色小字）
        let analysisEl = null;       // 分析结论区
        let analysisText = '';       // 分析结论累计文本
        let recBox = null;           // 建议消息框（惰性创建）
        let recEl = null;            // 建议内容区
        let recText = '';            // 建议累计文本

        const stopTimer = function() {
            if (timerInterval) {
                clearInterval(timerInterval);
                timerInterval = null;
            }
        };

        const ensureAnalysisBox = function() {
            if (analysisBox) return;
            stopTimer();
            removeMessageById(loadingMessageId);

            analysisBox = document.createElement('div');
            analysisBox.className = 'message server-message';

            const section = document.createElement('div');
            section.className = 'analysis-section';

            const title = document.createElement('h3');
            title.textContent = '检测结果分析';

            thinkingEl = document.createElement('div');
            thinkingEl.className = 'thinking-content';
            thinkingEl.textContent = '模型读图分析中…';

            analysisEl = document.createElement('div');
            analysisEl.className = 'markdown-content';

            section.appendChild(title);
            section.appendChild(thinkingEl);
            section.appendChild(analysisEl);
            analysisBox.appendChild(section);
            chatContainer.appendChild(analysisBox);
            scrollToBottom();
        };

        const ensureRecBox = function() {
            if (recBox) return;
            recBox = document.createElement('div');
            recBox.className = 'message server-message';

            const section = document.createElement('div');
            section.className = 'recommendation-section';

            const title = document.createElement('h3');
            title.textContent = '健康建议';

            recEl = document.createElement('div');
            recEl.className = 'markdown-content';

            section.appendChild(title);
            section.appendChild(recEl);
            recBox.appendChild(section);
            chatContainer.appendChild(recBox);
            scrollToBottom();
        };

        // 处理单个流式事件
        function handleEvent(ev) {
            switch (ev.stage) {
                case 'start':
                    ensureAnalysisBox();
                    break;

                case 'vl_thinking':
                    ensureAnalysisBox();
                    // 思考过程实时滚动（浅色小字）
                    thinkingEl.classList.remove('thinking-hidden');
                    thinkingEl.textContent = (thinkingEl.dataset.raw || '') + ev.text;
                    thinkingEl.dataset.raw = thinkingEl.textContent;
                    thinkingEl.scrollTop = thinkingEl.scrollHeight;
                    scrollToBottom();
                    break;

                case 'analysis_delta':
                    ensureAnalysisBox();
                    // 结论开始输出：收起思考过程
                    if (!analysisEl.dataset.started) {
                        analysisEl.dataset.started = '1';
                        thinkingEl.classList.add('thinking-hidden');
                        analysisEl.textContent = '';
                    }
                    analysisText += ev.text;
                    analysisEl.textContent = analysisText;
                    scrollToBottom();
                    break;

                case 'vl_retry':
                    // 本次尝试未采纳：清空半成品，重新分析
                    if (analysisBox) {
                        analysisText = '';
                        delete analysisEl.dataset.started;
                        analysisEl.textContent = '';
                        thinkingEl.classList.remove('thinking-hidden');
                        thinkingEl.textContent = `结论未达预期，自动重试第 ${ev.attempt} 次…`;
                        thinkingEl.dataset.raw = thinkingEl.textContent;
                    }
                    scrollToBottom();
                    break;

                case 'analysis':
                    // 最终提纯结论：定格渲染
                    ensureAnalysisBox();
                    thinkingEl.classList.add('thinking-hidden');
                    analysisText = ev.data || '';
                    analysisEl.innerHTML = convertMarkdownToHtml(analysisText);
                    scrollToBottom();
                    break;

                case 'recommendations_delta':
                    ensureRecBox();
                    recText += ev.text;
                    recEl.innerHTML = convertMarkdownToHtml(recText);
                    scrollToBottom();
                    break;

                case 'recommendations':
                    ensureRecBox();
                    recText = ev.data || '';
                    recEl.innerHTML = convertMarkdownToHtml(recText);
                    scrollToBottom();
                    break;

                case 'done':
                    stopTimer();
                    removeMessageById(loadingMessageId);
                    break;

                case 'error':
                    stopTimer();
                    removeMessageById(loadingMessageId);
                    displayErrorMessage(ev.detail || '未知错误');
                    break;
            }
        }

        try {
            const resp = await fetch('/image', { method: 'POST', body: formData });
            if (!resp.ok || !resp.body) {
                let detail = `HTTP ${resp.status}`;
                try {
                    const j = await resp.json();
                    detail = j.detail || j.error || detail;
                } catch (e) { /* ignore */ }
                stopTimer();
                removeMessageById(loadingMessageId);
                displayErrorMessage(detail);
                return;
            }

            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();  // 末行可能不完整，留到下一轮
                for (const line of lines) {
                    const s = line.trim();
                    if (!s) continue;
                    try {
                        handleEvent(JSON.parse(s));
                    } catch (e) {
                        console.warn('跳过无法解析的事件行:', s);
                    }
                }
            }
            // 流结束：确保计时器停了
            stopTimer();
            removeMessageById(loadingMessageId);
        } catch (err) {
            stopTimer();
            removeMessageById(loadingMessageId);
            displayErrorMessage('网络错误，请检查连接。如果您使用的是本地服务器，请确保服务器正在运行并且您是通过服务器访问此页面的。');
        }
    }

    // 在聊天窗口显示用户发送的图片
    function displayUserImage(imageFile) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message user-message image-message';

        const img = document.createElement('img');
        img.src = URL.createObjectURL(imageFile);
        img.alt = 'User uploaded image';

        // 限制图片显示大小
        img.style.maxWidth = '200px';
        img.style.maxHeight = '200px';

        img.onload = function() {
            URL.revokeObjectURL(img.src);
        };

        messageDiv.appendChild(img);
        chatContainer.appendChild(messageDiv);
        scrollToBottom();
    }

    // 显示加载消息
    function displayLoadingMessage() {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message server-message loading-message';
        messageDiv.id = 'loading-' + Date.now(); // 为加载消息分配唯一ID

        const loadingDots = document.createElement('div');
        loadingDots.className = 'loading-dots';
        loadingDots.innerHTML = '<span></span><span></span><span></span>';

        const timerDiv = document.createElement('div');
        timerDiv.className = 'timer';
        timerDiv.textContent = '0秒';

        messageDiv.appendChild(loadingDots);
        messageDiv.appendChild(timerDiv);
        chatContainer.appendChild(messageDiv);
        scrollToBottom();

        // 开始计时
        let seconds = 0;
        timerInterval = setInterval(function() {
            seconds++;
            timerDiv.textContent = `${seconds}秒`;
        }, 1000);

        return messageDiv.id;
    }

    // 移除指定ID的消息
    function removeMessageById(messageId) {
        const messageElement = document.getElementById(messageId);
        if (messageElement) {
            messageElement.remove();
        }
    }

    // 简单的Markdown到HTML转换器
    function convertMarkdownToHtml(markdown) {
        // 处理标题 (# H1, ## H2, ### H3, #### H4)
        let html = markdown.replace(/^###### (.*$)/gm, '<h6>$1</h6>')
                           .replace(/^##### (.*$)/gm, '<h5>$1</h5>')
                           .replace(/^#### (.*$)/gm, '<h4>$1</h4>')
                           .replace(/^### (.*$)/gm, '<h3>$1</h3>')
                           .replace(/^## (.*$)/gm, '<h2>$1</h2>')
                           .replace(/^# (.*$)/gm, '<h1>$1</h1>');

        // 处理粗体 (**text** 或 __text__)
        html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                   .replace(/__(.*?)__/g, '<strong>$1</strong>');

        // 处理斜体 (*text* 或 _text_)
        html = html.replace(/\*(.*?)\*/g, '<em>$1</em>')
                   .replace(/_(.*?)_/g, '<em>$1</em>');

        // 处理无序列表 (- item 或 * item)
        html = html.replace(/^[\s]*[-\*][\s]+(.+)$/gm, '<li>$1</li>');
        html = html.replace(/(<li>.*<\/li>)/gs, '<ul>$1</ul>');

        // 处理数字列表 (1. item)
        html = html.replace(/^[\s]*\d+\.[\s]+(.+)$/gm, '<li>$1</li>');
        html = html.replace(/(<li>.*<\/li>)/gs, '<ol>$1</ol>');

        // 处理换行
        html = html.replace(/\n/g, '<br>');

        return html;
    }

    // 显示错误消息
    function displayErrorMessage(message) {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'message server-message';
        errorDiv.textContent = `错误: ${message}`;
        chatContainer.appendChild(errorDiv);
        scrollToBottom();
    }

    // 滚动到底部
    function scrollToBottom() {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }
});
