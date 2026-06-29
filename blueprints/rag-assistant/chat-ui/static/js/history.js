const storageKey = 'onflow-rag-chat-history';
const maxStoredMessages = 50;

export function createHistoryStore({ historyList, historyCount }) {
  const runtime = [];
  let saved = loadHistory();
  let lastSavedLength = 0;

  function loadHistory() {
    try {
      const parsed = JSON.parse(localStorage.getItem(storageKey) || '[]');
      if (!Array.isArray(parsed)) return [];
      return parsed
        .filter((item) => item && (item.role === 'user' || item.role === 'assistant') && typeof item.content === 'string')
        .slice(-maxStoredMessages);
    } catch (err) {
      return [];
    }
  }

  function render() {
    historyCount.textContent = String(saved.length);
    historyList.innerHTML = '';
    if (saved.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'history-empty';
      empty.textContent = 'Chưa có lịch sử chat được lưu trên trình duyệt này.';
      historyList.appendChild(empty);
      return;
    }

    saved.slice().reverse().forEach((message) => {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'history-item';
      item.addEventListener('click', function() {
        item.classList.toggle('expanded');
      });

      const role = document.createElement('div');
      role.className = 'history-role';
      role.textContent = message.role === 'user' ? 'Bạn' : 'AI';
      const text = document.createElement('div');
      text.className = 'history-text';
      text.textContent = message.content;
      item.appendChild(role);
      item.appendChild(text);
      historyList.appendChild(item);
    });
  }

  function push(role, content) {
    runtime.push({ role, content });
  }

  function saveNew() {
    const newMessages = runtime.slice(lastSavedLength);
    lastSavedLength = runtime.length;
    if (newMessages.length === 0) return;

    saved = saved.concat(newMessages).slice(-maxStoredMessages);
    try {
      localStorage.setItem(storageKey, JSON.stringify(saved));
    } catch (err) {
      console.warn('Could not save chat history', err);
    }
    historyCount.textContent = String(saved.length);
  }

  function clear() {
    saved = [];
    localStorage.removeItem(storageKey);
    render();
  }

  render();

  return {
    runtime,
    get saved() {
      return saved;
    },
    push,
    saveNew,
    render,
    clear,
  };
}
