import { useEffect, useRef, useState } from 'react';
import { streamChat } from './api.js';
import { renderFormattedAnswer } from './markdown.js';

const STORAGE_KEY = 'onflow-rag-chat-history';
const MAX_HISTORY = 50;

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

function Header() {
  return <header id="top">
    <a className="brand" href="#top" aria-label="Onflow Open API">
      <span className="header-logo"><Logo /></span>
      <span className="brand-name"><strong>Onflow</strong> Open API</span>
    </a>
    <nav className="main-nav" aria-label="Tài nguyên tích hợp Open API">
      <a href="https://developers.onflow.vn/doc-611811" target="_blank" rel="noreferrer">Bắt đầu</a>
      <a href="https://developers.onflow.vn/api-9196579" target="_blank" rel="noreferrer">API Reference</a>
      <a href="https://developers.onflow.vn/doc-794649" target="_blank" rel="noreferrer">Webhooks</a>
      <a className="active" href="#assistant">Trợ lý API <span className="nav-spark">✦</span></a>
    </nav>
    <div className="header-actions">
      <a className="header-action system-toggle" href="https://developers.onflow.vn/" target="_blank" rel="noreferrer">
        Mở tài liệu <span aria-hidden="true">↗</span>
      </a>
    </div>
  </header>;
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
    ['Bắt đầu tích hợp',
      ['Hướng dẫn xác thực Onflow API trên môi trường staging', 'Giải thích cấu trúc response và các lỗi API thường gặp']],
    ['Đơn hàng & vận chuyển',
      ['Tạo đơn B2C cần endpoint và các field bắt buộc nào?', 'Viết ví dụ cURL lấy chi tiết shipment theo tracking_code']],
    ['Webhook & trạng thái',
      ['Thiết kế consumer an toàn cho webhook cập nhật đơn hàng', 'Giải thích các mã trạng thái shipment và bước xử lý tiếp theo']],
  ];
  return <div className="empty-state">
    <div className="prompt-sections">{groups.map(([title, prompts]) => <section className="prompt-section" key={title}>
      <h3>{title}</h3><div className="prompt-list">{prompts.map((prompt) =>
        <button className="prompt-btn" disabled={disabled} key={prompt} onClick={() => onPrompt(prompt)}>
          <span className="prompt-search" aria-hidden="true" />{prompt}
        </button>)}</div>
    </section>)}</div>
  </div>;
}

function SendIcon() {
  return <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 4 15 8-15 8 3-8-3-8Zm3 8h12" /></svg>;
}

function Composer({ input, setInput, loading, send, inputRef, landing = false }) {
  return <div className={`input-area ${landing ? 'landing-composer' : ''} ${loading ? 'waiting' : ''}`}>
    <div className="composer-shell">
      <textarea className="composer-input" ref={inputRef} rows="1" value={input} readOnly={loading} autoFocus
        aria-label="Nhập câu hỏi về Onflow Open API"
        placeholder={loading ? 'Đợi trợ lý trả lời xong...' : 'Hỏi về endpoint, payload, trạng thái hoặc webhook...'}
        onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault(); send();
          }
        }} />
      <button className="send-btn" type="button" aria-label="Gửi câu hỏi"
        disabled={loading || !input.trim()} onClick={() => send()}>
        {loading ? <span className="send-spinner" /> : <SendIcon />}
      </button>
    </div>
    {!landing && <div className="input-hint">{loading ? 'Trợ lý API đang trả lời...' : 'Enter để gửi · Shift + Enter để xuống dòng'}</div>}
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

export default function App() {
  const [messages, setMessages] = useState([]);
  const [history, setHistory] = useState(loadHistory);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const chatRef = useRef(null);
  const inputRef = useRef(null);
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
  const send = async (value = input) => {
    const content = value.trim();
    if (!content || loading) return;
    const user = { role: 'user', content };
    setMessages((items) => [...items, user]);
    setInput('');
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
    <Header />
    <main id="assistant" className={`workspace ${messages.length ? 'chatting' : 'landing-mode'}`}>
      <div className="chat-container" ref={chatRef}><div className="chat-inner">
        {messages.length === 0 ? <>
          <div className="welcome-title"><span>✦</span><h1>Trợ lý tích hợp Onflow Open API</h1></div>
          <p className="welcome-subtitle">Hỗ trợ tra cứu endpoint, payload, mã trạng thái, webhook và viết mã tích hợp dựa trên tài liệu Onflow.</p>
          <Composer landing input={input} setInput={setInput} loading={loading} send={send} inputRef={inputRef} />
          <EmptyState disabled={loading} onPrompt={send} />
        </> : messages.map((message, index) => <Message key={message.id || index} message={message} />)}
      </div></div>
      {messages.length > 0 && <Composer input={input} setInput={setInput} loading={loading} send={send} inputRef={inputRef} />}
    </main>
  </>;
}
