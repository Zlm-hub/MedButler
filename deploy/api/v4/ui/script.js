document.addEventListener('DOMContentLoaded', function() {
    // 获取DOM元素
    const chatContainer = document.getElementById('chatContainer');
    const imageInput = document.getElementById('imageInput');
    const imageInputLabel = document.getElementById('imageInputLabel');
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
    
    // 发送图片到服务器
    function sendImageToServer(imageFile) {
        // 在聊天窗口显示用户发送的图片
        displayUserImage(imageFile);
        
        // 清除选择的图片
        imageInput.value = '';
        selectedImage = null;
        imagePreviewContainer.style.display = 'none';
        sendButton.disabled = true;
        
        // 显示等待动画
        const loadingMessageId = displayLoadingMessage();
        
        // 创建FormData对象
        const formData = new FormData();
        formData.append('files', imageFile);
        
        // 发送请求到服务器
        const xhr = new XMLHttpRequest();
        // 使用正确的服务器地址和端口
        // xhr.open('POST', 'http://101.32.126.91:80/analyze_medical_report', true);
        xhr.open('POST', '/image', true);
        
        xhr.onload = function() {
            // 停止计时器
            if (timerInterval) {
                clearInterval(timerInterval);
                timerInterval = null;
            }
            
            // 移除加载消息
            removeMessageById(loadingMessageId);
            
            if (xhr.status === 200) {
                try {
                    const response = JSON.parse(xhr.responseText);
                    displayServerResponse(response);
                } catch (e) {
                    displayErrorMessage('解析服务器响应时出错: ' + e.message);
                }
            } else {
                try {
                    const errorResponse = JSON.parse(xhr.responseText);
                    displayErrorMessage(`服务器错误: ${xhr.status} - ${errorResponse.error}`);
                } catch (e) {
                    displayErrorMessage(`服务器错误: ${xhr.status} - ${xhr.responseText}`);
                }
            }
        };
        
        xhr.onerror = function() {
            // 停止计时器
            if (timerInterval) {
                clearInterval(timerInterval);
                timerInterval = null;
            }
            
            // 移除加载消息
            removeMessageById(loadingMessageId);
            displayErrorMessage('网络错误，请检查连接。如果您使用的是本地服务器，请确保服务器正在运行并且您是通过服务器访问此页面的。');
        };
        
        xhr.ontimeout = function() {
            // 停止计时器
            if (timerInterval) {
                clearInterval(timerInterval);
                timerInterval = null;
            }
            
            // 移除加载消息
            removeMessageById(loadingMessageId);
            displayErrorMessage('请求超时，请稍后重试。');
        };
        
        // 设置超时时间（毫秒）：VL+LLM 串联响应常需 20-40 秒，给 120 秒余量
        xhr.timeout = 120000; // 120秒
        
        xhr.send(formData);
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
    
    // 显示服务器响应
    function displayServerResponse(response) {
        // 显示分析结果
        const analysisMessage = document.createElement('div');
        analysisMessage.className = 'message server-message';
        
        const analysisSection = document.createElement('div');
        analysisSection.className = 'analysis-section';
        
        const analysisTitle = document.createElement('h3');
        analysisTitle.textContent = '检测结果分析';
        
        const analysisContent = document.createElement('div');
        analysisContent.className = 'markdown-content';
        analysisContent.innerHTML = convertMarkdownToHtml(response.analysis_result);
        
        analysisSection.appendChild(analysisTitle);
        analysisSection.appendChild(analysisContent);
        analysisMessage.appendChild(analysisSection);
        
        chatContainer.appendChild(analysisMessage);
        scrollToBottom();
        
        // 显示健康建议
        const recommendationMessage = document.createElement('div');
        recommendationMessage.className = 'message server-message';
        
        const recommendationSection = document.createElement('div');
        recommendationSection.className = 'recommendation-section';
        
        const recommendationTitle = document.createElement('h3');
        recommendationTitle.textContent = '健康建议';
        
        const recommendationContent = document.createElement('div');
        recommendationContent.className = 'markdown-content';
        recommendationContent.innerHTML = convertMarkdownToHtml(response.health_recommendations);
        
        recommendationSection.appendChild(recommendationTitle);
        recommendationSection.appendChild(recommendationContent);
        recommendationMessage.appendChild(recommendationSection);
        
        chatContainer.appendChild(recommendationMessage);
        scrollToBottom();
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