import { createChatUi } from './js/chat.js';
import { el, defaultHint, sendIcon } from './js/dom.js';
import { createHistoryStore } from './js/history.js';
import { loadKnowledgeBases } from './js/knowledge.js';
import { createTaigaIssueForm, isCreateTaigaIssueIntent } from './js/taiga-form.js';

let isComposing = false;
let isLoading = false;

const historyStore = createHistoryStore({
  historyList: el.historyList,
  historyCount: el.historyCount,
});
const chatUi = createChatUi({ el });
const taigaForm = createTaigaIssueForm({
  el,
  onCloseFocus() {
    el.textarea.focus();
  },
  onCreated(content) {
    const assistantEl = chatUi.appendMessage('assistant', content);
    chatUi.showResponseDone(assistantEl);
    historyStore.push('assistant', content);
    historyStore.saveNew();
    historyStore.render();
  },
});

loadKnowledgeBases({
  kbOverviewMeta: el.kbOverviewMeta,
  kbOverviewBody: el.kbOverviewBody,
  kbUploadButton: el.kbUploadButton,
  kbUploadInput: el.kbUploadInput,
  kbUploadStatus: el.kbUploadStatus,
});

function setInputLocked(locked) {
  isLoading = locked;
  el.textarea.readOnly = locked;
  el.inputArea.classList.toggle('waiting', locked);
  el.inputHint.classList.toggle('waiting', locked);
  el.inputHint.innerHTML = locked ? '<span class="input-hint-dot"></span><span>AI đang trả lời...</span>' : defaultHint;
  el.sendBtn.disabled = locked;
  el.sendBtn.classList.toggle('is-loading', locked);
  el.sendBtn.innerHTML = locked ? '<span class="send-spinner" aria-hidden="true"></span>' : sendIcon;
  el.sendBtn.title = locked ? 'Đang chờ AI trả lời' : 'Gửi tin nhắn';
  el.sendBtn.setAttribute('aria-busy', locked ? 'true' : 'false');
  document.querySelectorAll('.prompt-btn').forEach((btn) => {
    btn.disabled = locked;
  });
  el.textarea.placeholder = locked ? 'Đợi AI trả lời xong...' : 'Hỏi về tài liệu của bạn...';
}

function setSystemMenuOpen(open) {
  el.systemMenu.hidden = !open;
  el.systemMenuToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
}

function setHistoryPanelOpen(open) {
  el.historyPanel.classList.toggle('open', open);
  el.historyPanel.setAttribute('aria-hidden', 'false');
  if (open) historyStore.render();
}

function setRailTab(tab) {
  const showDocs = tab === 'docs';
  el.docsTab.classList.toggle('active', showDocs);
  el.historyTab.classList.toggle('active', !showDocs);
  el.docsTab.setAttribute('aria-selected', showDocs ? 'true' : 'false');
  el.historyTab.setAttribute('aria-selected', showDocs ? 'false' : 'true');
  el.docsPanel.classList.toggle('active', showDocs);
  el.historyPanelContent.classList.toggle('active', !showDocs);
  if (!showDocs) historyStore.render();
}

async function sendMessage() {
  if (isLoading) return;

  const message = el.textarea.value.trim();
  if (!message) return;

  const empty = document.getElementById('empty');
  if (empty) empty.remove();

  chatUi.appendMessage('user', message);
  historyStore.push('user', message);

  el.textarea.value = '';
  el.textarea.style.height = 'auto';

  if (isCreateTaigaIssueIntent(message)) {
    historyStore.saveNew();
    historyStore.render();
    taigaForm.open(message);
    return;
  }

  setInputLocked(true);
  try {
    const content = await chatUi.sendToAssistant(message, historyStore.runtime.slice(0, -1));
    historyStore.push('assistant', content);
    historyStore.saveNew();
    historyStore.render();
  } catch (err) {
    const errorContent = 'Lỗi kết nối: ' + err.message;
    chatUi.appendMessage('assistant', errorContent, true);
    historyStore.push('assistant', errorContent);
    historyStore.saveNew();
    historyStore.render();
  } finally {
    setInputLocked(false);
    el.textarea.focus();
  }
}

function usePrompt(btn) {
  if (isLoading) return;
  el.textarea.value = btn.textContent;
  el.textarea.focus();
  sendMessage();
}

el.textarea.addEventListener('input', function() {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 120) + 'px';
});
el.textarea.addEventListener('compositionstart', function() {
  isComposing = true;
});
el.textarea.addEventListener('compositionend', function() {
  isComposing = false;
});
el.textarea.addEventListener('keydown', function(e) {
  if (e.key === 'Enter' && !e.shiftKey && !isComposing && !e.isComposing && e.keyCode !== 229) {
    e.preventDefault();
    sendMessage();
  }
});
el.sendBtn.addEventListener('click', sendMessage);
document.querySelectorAll('.prompt-btn').forEach((btn) => {
  btn.addEventListener('click', function() {
    usePrompt(btn);
  });
});
el.systemMenuToggle.addEventListener('click', function(e) {
  e.stopPropagation();
  setSystemMenuOpen(el.systemMenu.hidden);
});
document.addEventListener('click', function(e) {
  if (!el.systemMenu.hidden && !el.systemMenu.contains(e.target) && !el.systemMenuToggle.contains(e.target)) {
    setSystemMenuOpen(false);
  }
});
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    setSystemMenuOpen(false);
    if (!el.taigaIssueModal.hidden && !taigaForm.isCreating) {
      taigaForm.close();
    }
  }
});
el.docsTab.addEventListener('click', function() {
  setRailTab('docs');
});
el.historyTab.addEventListener('click', function() {
  setRailTab('history');
});
el.historyClose.addEventListener('click', function() {
  setHistoryPanelOpen(false);
});
el.clearHistoryBtn.addEventListener('click', function() {
  if (isLoading) return;
  if (historyStore.saved.length > 0 && !confirm('Xóa toàn bộ lịch sử chat đã lưu trên trình duyệt này?')) return;
  historyStore.clear();
  setHistoryPanelOpen(false);
  el.textarea.focus();
});
