import { useEffect, useRef, useState } from 'react';
import {
  createTaigaIssue,
  deleteKnowledgeBaseDataSource,
  fetchKnowledgeBases,
  fetchTaigaMetadata,
  streamChat,
  uploadKnowledgeBaseFile,
} from './api.js';
import { renderFormattedAnswer } from './markdown.js';

const STORAGE_KEY = 'onflow-rag-chat-history';
const MAX_HISTORY = 50;
const FILE_TYPES = '.pdf,.txt,.md,.markdown,.html,.csv,.docx';

function createClientId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  if (globalThis.crypto?.getRandomValues) {
    const values = new Uint32Array(4);
    globalThis.crypto.getRandomValues(values);
    return Array.from(values, (value) => value.toString(16).padStart(8, '0')).join('-');
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function createTypewriter(onUpdate) {
  let pending = '';
  let visible = '';
  let running = false;
  let finishResolver = null;

  const delayFor = (character) => {
    if ('.!?'.includes(character)) return 120;
    if (',;:'.includes(character)) return 65;
    if (character === '\n') return 80;
    return 12 + Math.floor(Math.random() * 12);
  };
  const batchSize = () => {
    if (pending.length > 600) return 14;
    if (pending.length > 240) return 8;
    if (pending.length > 80) return 4;
    return 1;
  };
  const next = () => {
    if (!pending) {
      running = false;
      if (finishResolver) {
        finishResolver();
        finishResolver = null;
      }
      return;
    }
    const count = batchSize();
    const chunk = pending.slice(0, count);
    pending = pending.slice(count);
    visible += chunk;
    onUpdate(visible);
    window.setTimeout(() => window.requestAnimationFrame(next), delayFor(chunk[chunk.length - 1]));
  };
  const start = () => {
    if (running) return;
    running = true;
    window.requestAnimationFrame(next);
  };

  return {
    push(chunk) {
      pending += chunk;
      start();
    },
    finish() {
      if (!pending && !running) return Promise.resolve();
      return new Promise((resolve) => {
        finishResolver = resolve;
        start();
      });
    },
  };
}

function Logo() {
  return <svg viewBox="0 0 512 512" aria-hidden="true">
    <path d="M151 116c9-16 24-16 33 0l68 122c7 12 7 24 0 36l-68 122c-9 16-24 16-33 0L77 274c-7-12-7-24 0-36l74-122z"/>
    <path d="M178 90h148c28 0 45 10 59 35l61 113c7 12 7 24 0 36l-61 113c-14 25-31 35-59 35H178c24-16 38-33 52-58l47-84c10-17 10-31 0-48l-47-84c-14-25-28-42-52-58z"/>
  </svg>;
}

function Header({ agentName }) {
  const [open, setOpen] = useState(false);
  const menuRef = useRef(null);
  useEffect(() => {
    const close = (event) => {
      if (event.key === 'Escape' || (menuRef.current && !menuRef.current.contains(event.target))) setOpen(false);
    };
    document.addEventListener('click', close);
    document.addEventListener('keydown', close);
    return () => {
      document.removeEventListener('click', close);
      document.removeEventListener('keydown', close);
    };
  }, []);
  const systems = [
    ['https://oms.onflow.vn', 'Hệ thống đơn hàng'],
    ['https://wms.onflow.vn', 'Hệ thống kho'],
    ['https://ops.onflow.vn', 'Hệ thống vận hành'],
  ];
  return <header>
    <div className="header-logo"><Logo /></div>
    <span className="header-title">{agentName}</span>
    <span className="header-badge">Vận hành bởi Onflow.vn GenAI</span>
    <div className="header-actions" ref={menuRef}>
      <button className="header-action system-toggle" type="button" aria-expanded={open} onClick={(e) => {
        e.stopPropagation();
        setOpen((value) => !value);
      }}>
        <span>Đăng nhập</span><span className="system-caret" aria-hidden="true" />
      </button>
      {!open ? null : <nav className="system-menu" aria-label="Liên kết hệ thống">
        {systems.map(([url, label]) => <a key={url} href={url} target="_blank" rel="noreferrer">
          <span className="system-menu-icon"><Logo /></span><span>{label}</span>
          <span className="system-menu-open">↗</span>
        </a>)}
      </nav>}
    </div>
  </header>;
}

function formatBytes(bytes) {
  if (!bytes) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(value >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

function DeleteModal({ source, onCancel, onConfirm, busy }) {
  useEffect(() => {
    const close = (event) => event.key === 'Escape' && !busy && onCancel();
    document.addEventListener('keydown', close);
    return () => document.removeEventListener('keydown', close);
  }, [busy, onCancel]);
  return <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !busy && onCancel()}>
    <div className="kb-delete-modal" role="dialog" aria-modal="true">
      <div className="kb-delete-modal-icon"><span>×</span></div>
      <div className="kb-delete-modal-content">
        <h2>Xoá tài liệu?</h2>
        <p>Tài liệu <strong>{source.name}</strong> sẽ bị loại khỏi Knowledge Base. Hành động này không thể hoàn tác.</p>
        <div className="kb-delete-modal-note">Thao tác xoá không tạo indexing job nên sẽ không có phần trăm tiến trình.</div>
        <div className="kb-delete-modal-actions">
          <button className="taiga-action" type="button" disabled={busy} onClick={onCancel}>Hủy</button>
          <button className="taiga-action danger" type="button" disabled={busy} onClick={onConfirm}>
            {busy ? 'Đang xoá...' : 'Xoá tài liệu'}
          </button>
        </div>
      </div>
    </div>
  </div>;
}

function KnowledgePanel() {
  const [knowledgeBases, setKnowledgeBases] = useState([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const fileRef = useRef(null);

  const load = async () => {
    setLoading(true);
    try {
      const data = await fetchKnowledgeBases();
      setKnowledgeBases(data.knowledge_bases || []);
    } catch (error) {
      setStatus({ type: 'error', text: error.message });
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => { load(); }, []);

  const sources = knowledgeBases.flatMap((kb) => (kb.datasources || []).map((source) => ({
    ...source, kbUuid: kb.uuid, kbName: kb.name,
  })));

  const upload = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || !knowledgeBases[0]) return;
    setStatus({ type: 'loading', text: `Đang tải ${file.name}...` });
    try {
      await uploadKnowledgeBaseFile(knowledgeBases[0].uuid, file);
      setStatus({ type: 'success', text: 'Đã thêm tài liệu. Knowledge Base đang lập chỉ mục.' });
      await load();
    } catch (error) {
      setStatus({ type: 'error', text: error.message });
    }
  };

  const remove = async () => {
    setDeleteBusy(true);
    setStatus({ type: 'loading', text: `Đang xoá ${deleting.name} khỏi Knowledge Base...` });
    try {
      await deleteKnowledgeBaseDataSource(deleting.kbUuid, deleting.uuid);
      setDeleting(null);
      setStatus({ type: 'success', text: 'Đã xoá tài liệu khỏi Knowledge Base. Không cần chờ re-index.' });
      await load();
    } catch (error) {
      setStatus({ type: 'error', text: error.message });
    } finally {
      setDeleteBusy(false);
    }
  };

  return <>
    <div className="kb-overview">
      <div className="kb-overview-header">
        <div><div className="kb-overview-title">Tài liệu hiện có</div>
          <div className="kb-overview-meta">{loading ? 'Đang tải...' : `${sources.length} tài liệu`}</div>
        </div>
        <button className="kb-upload-btn" type="button" disabled={!knowledgeBases.length || status?.type === 'loading'} onClick={() => fileRef.current?.click()}>+ Thêm tài liệu</button>
        <input ref={fileRef} type="file" accept={FILE_TYPES} hidden onChange={upload} />
      </div>
      {status && <div className={`kb-upload-status ${status.type}`} role="status">{status.text}</div>}
      <div className="kb-overview-body">
        {loading ? <div className="kb-status">Đang lấy thông tin từ Knowledge Base.</div>
          : sources.length === 0 ? <div className="kb-status">Chưa có datasource nào trong Knowledge Base đang gắn với agent.</div>
            : <div className="kb-list">{sources.map((source) => <div className="kb-item" key={source.uuid}>
              <div className={`kb-file-icon ${source.type === 'web' ? 'web' : source.name?.toLowerCase().endsWith('.pdf') ? 'pdf' : 'file'}`}>▤</div>
              <div className="kb-item-main">
                <div className="kb-item-name" title={source.name}>{source.name}</div>
                <div className="kb-item-meta">{[source.type === 'web' ? 'Web' : 'Tệp', formatBytes(source.size_bytes)].filter(Boolean).join(' · ')}</div>
              </div>
              <button className="kb-delete-btn" type="button" title={`Xoá ${source.name}`} onClick={() => setDeleting(source)}>×</button>
            </div>)}</div>}
      </div>
      <div className="kb-delete-note">Khi xoá tài liệu, Knowledge Base sẽ loại bỏ datasource trực tiếp. Thao tác này không tạo indexing job nên sẽ không có phần trăm tiến trình.</div>
    </div>
    {deleting && <DeleteModal source={deleting} busy={deleteBusy} onCancel={() => setDeleting(null)} onConfirm={remove} />}
  </>;
}

function HistoryPanel({ history, onClear }) {
  return <><div className="history-panel-header">
    <div className="history-panel-title">Lịch sử chat</div>
    <div className="history-panel-actions"><button className="history-panel-btn" onClick={onClear}>Xóa</button></div>
  </div>
  <div className="history-list">{history.length === 0
    ? <div className="history-empty">Chưa có lịch sử chat được lưu trên trình duyệt này.</div>
    : [...history].reverse().map((message, index) => <details className="history-item" key={`${index}-${message.content}`}>
      <summary className="history-role">{message.role === 'user' ? 'Bạn' : 'AI'}</summary>
      <div className="history-text">{message.content}</div>
    </details>)}
  </div></>;
}

function Sidebar({ history, onClear }) {
  const [tab, setTab] = useState('docs');
  return <aside className="history-panel" aria-label="Tài liệu và lịch sử chat">
    <div className="rail-tabs" role="tablist">
      <button className={`rail-tab ${tab === 'docs' ? 'active' : ''}`} onClick={() => setTab('docs')}>Tài liệu</button>
      <button className={`rail-tab ${tab === 'history' ? 'active' : ''}`} onClick={() => setTab('history')}>
        <span>Lịch sử</span><span className="history-count">{history.length}</span>
      </button>
    </div>
    <section className="rail-section active">{tab === 'docs' ? <KnowledgePanel /> : <HistoryPanel history={history} onClear={onClear} />}</section>
  </aside>;
}

function Markdown({ text }) {
  const ref = useRef(null);
  useEffect(() => { if (ref.current) renderFormattedAnswer(ref.current, text); }, [text]);
  return <div ref={ref} />;
}

function Message({ message }) {
  return <div className={`message ${message.role}`}>
    <div className="avatar">{message.role === 'user' ? 'Y' : 'AI'}</div>
    {message.role === 'assistant' ? <div className="assistant-content">
      <div className={`bubble ${message.error ? 'error-bubble' : ''} ${message.streaming ? 'streaming' : ''}`}>
        <Markdown text={message.content} />
        {message.streaming && <span className="typing-dots" role="status" aria-label="AI đang trả lời">
          <span /><span /><span />
        </span>}
      </div>
      {!message.streaming && !message.error && <div className="response-status visible"><span>✓ Đã trả lời xong</span></div>}
    </div> : <div className="bubble">{message.content}</div>}
  </div>;
}

function EmptyState({ onPrompt, disabled }) {
  const groups = [
    ['Cần tra cứu chính sách?', 'Tìm nhanh quy định nội bộ, quyền lợi, trách nhiệm và các điểm cần lưu ý khi làm việc.',
      ['Tôi muốn tìm quy định liên quan đến nhân sự', 'Tóm tắt các điểm quan trọng trong chính sách nội bộ']],
    ['Không chắc phải làm bước nào?', 'Hỏi để biết quy trình cần theo, biểu mẫu cần dùng và bộ phận nào liên quan.',
      ['Tôi cần xử lý một yêu cầu mới thì bắt đầu từ đâu?', 'Quy trình này cần biểu mẫu nào và ai phụ trách?']],
    ['Cần báo lỗi hệ thống?', 'Tạo issue Taiga sau khi kiểm tra lại nội dung.', ['Tạo báo lỗi Taiga']],
  ];
  return <div className="empty-state"><div className="empty-header">
    <div className="empty-icon"><Logo /></div><div className="empty-copy"><h2>Trợ lý tri thức Onflow.vn</h2>
      <p>Chọn đúng nhóm câu hỏi hoặc nhập trực tiếp nội dung cần tra cứu. Trợ lý sẽ ưu tiên trả lời dựa trên kho tri thức đã cấu hình.</p>
    </div></div>
    <div className="prompt-sections">{groups.map(([title, copy, prompts]) => <section className="prompt-section" key={title}>
      <h3>{title}</h3><p>{copy}</p><div className="prompt-list">{prompts.map((prompt) =>
        <button className="prompt-btn" disabled={disabled} key={prompt} onClick={() => onPrompt(prompt)}>{prompt}</button>)}</div>
    </section>)}</div>
  </div>;
}

function PlusIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>;
}

function SendIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 11 6-6 6 6M12 5v14" /></svg>;
}

function SparkIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 1.2 3.8L17 8l-3.8 1.2L12 13l-1.2-3.8L7 8l3.8-1.2L12 3ZM6 14l.8 2.2L9 17l-2.2.8L6 20l-.8-2.2L3 17l2.2-.8L6 14Zm11 0 1 2.8 3 1.2-3 1.2L17 22l-1-2.8-3-1.2 3-1.2L17 14Z" /></svg>;
}

function QuickPromptIcon({ type }) {
  const paths = {
    policy: <><path d="M6 3.5h9l3 3V20H6z" /><path d="M15 3.5V7h3M9 11h6M9 15h6" /></>,
    process: <><circle cx="6" cy="6" r="2" /><circle cx="18" cy="12" r="2" /><circle cx="6" cy="18" r="2" /><path d="M8 6h3a3 3 0 0 1 3 3v0a3 3 0 0 0 3 3M16 12h-2a3 3 0 0 0-3 3v0a3 3 0 0 1-3 3" /></>,
    summary: <><path d="M5 4h14v16H5z" /><path d="M8.5 8H16M8.5 12H16M8.5 16H13" /></>,
    bug: <><path d="M8 9h8v7a4 4 0 0 1-8 0zM10 9V7a2 2 0 0 1 4 0v2M4 12h4M16 12h4M5 18l3-2M19 18l-3-2M6 7l2 2M18 7l-2 2" /></>,
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true">{paths[type]}</svg>;
}

function isTaigaIntent(message) {
  const text = message.toLowerCase();
  return ['tạo', 'tao', 'thêm', 'them', 'ghi nhận'].some((word) => text.includes(word))
    && ['báo lỗi', 'bao loi', 'lỗi', 'bug', 'issue', 'ticket'].some((word) => text.includes(word));
}

function TaigaModal({ initialSubject, onClose, onCreated }) {
  const [metadata, setMetadata] = useState(null);
  const [form, setForm] = useState({ subject: initialSubject, description: '', type: '', status: '', priority: '', severity: '', assigned_to: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    fetchTaigaMetadata().then((data) => {
      setMetadata(data);
      setForm((value) => ({ ...value, ...data.defaults, assigned_to: '' }));
    }).catch((err) => setError(err.message));
  }, []);
  const fields = [['type', 'Loại', 'types'], ['status', 'Trạng thái', 'statuses'], ['priority', 'Ưu tiên', 'priorities'], ['severity', 'Mức độ', 'severities']];
  const submit = async (event) => {
    event.preventDefault();
    if (!form.subject.trim()) return setError('Vui lòng nhập tiêu đề báo lỗi.');
    setBusy(true);
    setError('');
    try {
      const data = await createTaigaIssue(form);
      const issue = data.issue || {};
      onCreated(`Đã tạo báo lỗi Taiga:\n- issue #${issue.ref || issue.id}: ${issue.subject || form.subject} | ${issue.status || 'New'} | ${issue.assigned_to || 'chưa gán'}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };
  return <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
    <div className="taiga-modal" role="dialog" aria-modal="true">
      <div className="taiga-modal-header"><div><div className="taiga-modal-title">Tạo báo lỗi Taiga</div>
        <div className="taiga-modal-subtitle">Kiểm tra lại nội dung trước khi tạo issue trên Taiga.</div></div>
        <button className="taiga-modal-close" disabled={busy} onClick={onClose}>×</button></div>
      <form className="taiga-modal-body" onSubmit={submit}>
        {error && <div className="taiga-form-error">{error}</div>}
        <div className="taiga-form-grid">
          <div className="taiga-field full"><label>Tiêu đề lỗi</label><input value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} maxLength="500" /></div>
          <div className="taiga-field full"><label>Mô tả chi tiết</label><textarea value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></div>
          {fields.map(([name, label, key]) => <div className="taiga-field" key={name}><label>{label}</label>
            <select value={form[name] || ''} onChange={(e) => setForm({ ...form, [name]: e.target.value })}>
              {(metadata?.[key] || []).map((option) => <option key={option.id} value={option.id}>{option.name}</option>)}
            </select></div>)}
          <div className="taiga-field full"><label>Người phụ trách</label><select value={form.assigned_to} onChange={(e) => setForm({ ...form, assigned_to: e.target.value })}>
            <option value="">Chưa gán</option>{(metadata?.members || []).map((option) => <option key={option.id} value={option.id}>{option.name}</option>)}
          </select></div>
        </div>
        <div className="taiga-modal-actions"><button className="taiga-action" type="button" disabled={busy} onClick={onClose}>Hủy</button>
          <button className="taiga-action primary" disabled={busy || !metadata}>{busy ? 'Đang tạo...' : 'Tạo báo lỗi'}</button></div>
      </form>
    </div>
  </div>;
}

function loadHistory() {
  try {
    const data = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
    return Array.isArray(data) ? data.slice(-MAX_HISTORY) : [];
  } catch {
    return [];
  }
}

export default function App({ agentName }) {
  const [messages, setMessages] = useState([]);
  const [history, setHistory] = useState(loadHistory);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [taigaSubject, setTaigaSubject] = useState(null);
  const chatRef = useRef(null);
  const inputRef = useRef(null);
  const quickPrompts = [
    { label: 'Tra cứu chính sách', icon: 'policy' },
    { label: 'Hướng dẫn quy trình', icon: 'process' },
    { label: 'Tóm tắt tài liệu', icon: 'summary' },
    { label: 'Tạo báo lỗi', icon: 'bug' },
  ];

  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [messages]);
  useEffect(() => {
    const textarea = inputRef.current;
    if (!textarea) return;
    textarea.style.height = 'auto';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 132)}px`;
  }, [input]);
  const save = (items) => {
    const next = [...history, ...items].slice(-MAX_HISTORY);
    setHistory(next);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  };
  const appendCreated = (content) => {
    const message = { role: 'assistant', content };
    setMessages((items) => [...items, message]);
    save([message]);
    setTaigaSubject(null);
  };
  const send = async (value = input) => {
    const content = value.trim();
    if (!content || loading) return;
    const user = { role: 'user', content };
    setMessages((items) => [...items, user]);
    setInput('');
    if (isTaigaIntent(content)) {
      save([user]);
      setTaigaSubject(content.replace(/^(tạo|thêm)\s+(báo lỗi|bug|issue)\s*/i, ''));
      return;
    }
    setLoading(true);
    const assistantId = createClientId();
    setMessages((items) => [...items, { id: assistantId, role: 'assistant', content: '', streaming: true }]);
    try {
      const response = await streamChat(content, messages.map(({ role, content: text }) => ({ role, content: text })));
      if (!response.ok && !response.body) throw new Error('Không nhận được phản hồi.');
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let answer = '';
      const typewriter = createTypewriter((visible) => {
        setMessages((items) => items.map((item) => item.id === assistantId ? { ...item, content: visible } : item));
      });
      while (true) {
        const { value: chunk, done } = await reader.read();
        if (done) break;
        const text = decoder.decode(chunk, { stream: true });
        answer += text;
        typewriter.push(text);
      }
      const finalChunk = decoder.decode();
      answer += finalChunk;
      if (finalChunk) typewriter.push(finalChunk);
      await typewriter.finish();
      answer = answer.trim() || 'Không nhận được phản hồi.';
      const assistant = { id: assistantId, role: 'assistant', content: answer };
      setMessages((items) => items.map((item) => item.id === assistantId ? assistant : item));
      save([user, assistant]);
    } catch (error) {
      const assistant = { id: assistantId, role: 'assistant', content: `Lỗi kết nối: ${error.message}`, error: true };
      setMessages((items) => items.map((item) => item.id === assistantId ? assistant : item));
      save([user, assistant]);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  return <>
    <Header agentName={agentName} />
    <Sidebar history={history} onClear={() => {
      if (history.length && !window.confirm('Xóa toàn bộ lịch sử chat đã lưu trên trình duyệt này?')) return;
      localStorage.removeItem(STORAGE_KEY);
      setHistory([]);
    }} />
    <div className="chat-container" ref={chatRef}><div className="chat-inner">
      {messages.length === 0 ? <EmptyState disabled={loading} onPrompt={send} /> : messages.map((message, index) => <Message key={message.id || index} message={message} />)}
    </div></div>
    <div className={`input-area ${loading ? 'waiting' : ''}`}>
      <div className="composer-shell">
        <textarea className="composer-input" ref={inputRef} rows="1" value={input} readOnly={loading} autoFocus
          aria-label="Nhập câu hỏi"
          placeholder={loading ? 'Đợi AI trả lời xong...' : 'Giao việc hoặc nhập câu hỏi của bạn...'}
          onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault(); send();
            }
          }} />
        <div className="composer-toolbar">
          <button className="composer-tool" type="button" title="Thêm nội dung" aria-label="Thêm nội dung"
            onClick={() => inputRef.current?.focus()}><PlusIcon /></button>
          <span className="composer-label"><SparkIcon /> Trợ lý tri thức</span>
          <button className="send-btn" type="button" aria-label="Gửi câu hỏi"
            disabled={loading || !input.trim()} onClick={() => send()}>
            {loading ? <span className="send-spinner" /> : <SendIcon />}
          </button>
        </div>
      </div>
      <div className="quick-prompts" aria-label="Câu hỏi gợi ý">
        {quickPrompts.map((prompt) => <button type="button" key={prompt.label} disabled={loading}
          onClick={() => send(prompt.label)}>
          <QuickPromptIcon type={prompt.icon} /><span>{prompt.label}</span>
        </button>)}
      </div>
      <div className="input-hint">{loading ? 'AI đang trả lời...' : 'Enter để gửi · Shift + Enter để xuống dòng'}</div>
    </div>
    {taigaSubject !== null && <TaigaModal initialSubject={taigaSubject} onClose={() => setTaigaSubject(null)} onCreated={appendCreated} />}
  </>;
}
