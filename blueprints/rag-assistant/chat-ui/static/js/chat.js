import { streamChat } from './api.js';
import { renderFormattedAnswer } from './render.js';

export function createChatUi({ el }) {
  function appendMessage(role, text, isError) {
    const div = document.createElement('div');
    div.className = 'message ' + role;
    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = role === 'user' ? 'Y' : 'AI';
    const bubble = document.createElement('div');
    bubble.className = 'bubble' + (isError ? ' error-bubble' : '');
    if (role === 'assistant') {
      renderFormattedAnswer(bubble, text);
    } else {
      bubble.textContent = text;
    }
    div.appendChild(avatar);
    if (role === 'assistant') {
      const content = document.createElement('div');
      content.className = 'assistant-content';
      content.appendChild(bubble);
      div.appendChild(content);
    } else {
      div.appendChild(bubble);
    }
    el.chatInner.appendChild(div);
    scrollToBottom();
    return div;
  }

  function appendTyping() {
    const div = document.createElement('div');
    div.className = 'message assistant';
    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = 'AI';
    const bubble = document.createElement('div');
    bubble.className = 'bubble';
    bubble.innerHTML = '<div class="typing-dots"><span></span><span></span><span></span></div>';
    div.appendChild(avatar);
    div.appendChild(bubble);
    el.chatInner.appendChild(div);
    scrollToBottom();
    return div;
  }

  function shouldAutoScroll() {
    const distanceFromBottom = el.chatContainer.scrollHeight - el.chatContainer.scrollTop - el.chatContainer.clientHeight;
    return distanceFromBottom < 120;
  }

  function scrollToBottom() {
    el.chatContainer.scrollTop = el.chatContainer.scrollHeight;
  }

  function showResponseDone(messageEl) {
    const content = messageEl.querySelector('.assistant-content');
    if (!content) return;

    const status = document.createElement('div');
    status.className = 'response-status';
    status.innerHTML = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M7.6 13.8 3.8 10l-1.2 1.2 5 5 9.8-9.8-1.2-1.2z"/></svg><span>Đã trả lời xong</span>';
    content.appendChild(status);
    requestAnimationFrame(() => {
      status.classList.add('visible');
      if (shouldAutoScroll()) {
        scrollToBottom();
      }
    });
  }

  function createStreamRenderer(bubble) {
    let pending = '';
    let visible = '';
    let timerId = null;
    let isRunning = false;
    let resolveDone = null;

    function getDelay(char) {
      if (!char) return 18;
      if ('.!?'.includes(char)) return 170;
      if (',;:'.includes(char)) return 90;
      if (char === '\n') return 120;
      if (char === ' ') return 18;
      return 14 + Math.floor(Math.random() * 18);
    }

    function getBatchSize() {
      if (pending.length > 600) return 12;
      if (pending.length > 240) return 8;
      if (pending.length > 80) return 4;
      return 1;
    }

    function renderNext() {
      if (pending.length === 0) {
        timerId = null;
        isRunning = false;
        if (resolveDone) {
          resolveDone();
          resolveDone = null;
        }
        return;
      }

      const batchSize = getBatchSize();
      const next = pending.slice(0, batchSize);
      pending = pending.slice(batchSize);
      visible += next;
      renderFormattedAnswer(bubble, visible);

      if (shouldAutoScroll()) {
        scrollToBottom();
      }

      const lastChar = next[next.length - 1];
      timerId = setTimeout(() => {
        requestAnimationFrame(renderNext);
      }, getDelay(lastChar));
    }

    function ensureRunning() {
      if (!isRunning) {
        isRunning = true;
        requestAnimationFrame(renderNext);
      }
    }

    return {
      push(chunk) {
        pending += chunk;
        ensureRunning();
      },
      finish() {
        if (pending.length === 0 && timerId === null && !isRunning) {
          return Promise.resolve();
        }
        return new Promise((resolve) => {
          resolveDone = resolve;
          ensureRunning();
        });
      },
    };
  }

  async function sendToAssistant(message, history) {
    const typingEl = appendTyping();
    let res;
    try {
      res = await streamChat(message, history);
    } catch (err) {
      typingEl.remove();
      throw err;
    }
    if (!res.body) {
      typingEl.remove();
      const data = await res.json();
      const content = data.content || data.error || 'Không nhận được phản hồi.';
      const assistantEl = appendMessage('assistant', content, !!data.error || res.status >= 400);
      if (!data.error && res.status < 400) {
        showResponseDone(assistantEl);
      }
      return content;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let assistantEl = null;
    let bubble = null;
    let renderer = null;
    let content = '';

    function ensureAssistantMessage() {
      if (assistantEl) return;
      typingEl.remove();
      assistantEl = appendMessage('assistant', '', res.status >= 400);
      bubble = assistantEl.querySelector('.bubble');
      bubble.classList.add('streaming');
      renderer = createStreamRenderer(bubble);
    }

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      if (!chunk) continue;
      ensureAssistantMessage();
      content += chunk;
      renderer.push(chunk);
    }
    const finalChunk = decoder.decode();
    if (finalChunk) {
      ensureAssistantMessage();
      content += finalChunk;
      renderer.push(finalChunk);
    }

    content = content.trim() || 'Không nhận được phản hồi.';
    ensureAssistantMessage();
    await renderer.finish();
    bubble.classList.remove('streaming');
    renderFormattedAnswer(bubble, content);
    if (res.status < 400) {
      showResponseDone(assistantEl);
    }
    return content;
  }

  return {
    appendMessage,
    sendToAssistant,
    showResponseDone,
  };
}
