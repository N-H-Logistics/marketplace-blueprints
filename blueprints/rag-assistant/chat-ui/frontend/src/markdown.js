export function escapeHTML(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function renderInlineMarkdown(value) {
  return escapeHTML(value)
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>');
}

function statusClass(value) {
  const normalized = (value || '').toLowerCase();
  if (normalized.includes('done') || normalized.includes('đã đóng')) return 'status-done';
  if (normalized.includes('reject')) return 'status-reject';
  if (normalized.includes('progress') || normalized.includes('prioritized')) return 'status-progress';
  return 'status-open';
}

function renderTaigaCountAnswer(text) {
  const match = text.match(/có\s+(\d+)\s+mục phù hợp:\s+(\d+)\s+đang mở\/chưa hoàn tất và\s+(\d+)\s+đã đóng/i);
  if (!match) return '';
  return `
    <div class="taiga-answer">
      <div class="taiga-summary">
        <div class="taiga-stat">
          <div class="taiga-stat-value">${escapeHTML(match[1])}</div>
          <div class="taiga-stat-label">Tổng mục</div>
        </div>
        <div class="taiga-stat">
          <div class="taiga-stat-value">${escapeHTML(match[2])}</div>
          <div class="taiga-stat-label">Đang mở</div>
        </div>
        <div class="taiga-stat">
          <div class="taiga-stat-value">${escapeHTML(match[3])}</div>
          <div class="taiga-stat-label">Đã đóng</div>
        </div>
      </div>
    </div>
  `;
}

function renderTaigaListAnswer(text) {
  const lines = text.split('\n').map((line) => line.trim()).filter(Boolean);
  if (!lines.length || !lines[0].toLowerCase().includes('taiga')) return '';

  const cards = [];
  let moreText = '';
  let pendingCard = null;

  function pushPendingCard() {
    if (!pendingCard) return;
    cards.push(`
      <article class="taiga-card">
        <div class="taiga-card-head">
          <span class="taiga-ref">${escapeHTML(pendingCard.type)} #${escapeHTML(pendingCard.ref)}</span>
          <div class="taiga-title">${escapeHTML(pendingCard.subject)}</div>
        </div>
        <div class="taiga-meta">
          <span class="taiga-pill ${statusClass(pendingCard.status)}">${escapeHTML(pendingCard.status)}</span>
          <span class="taiga-pill">${escapeHTML(pendingCard.assignee)}</span>
          <span class="taiga-pill ${statusClass(pendingCard.state)}">${escapeHTML(pendingCard.state)}</span>
        </div>
        ${pendingCard.description ? `<p class="taiga-description">${escapeHTML(pendingCard.description)}</p>` : ''}
        ${pendingCard.url ? `
          <div class="taiga-card-foot">
            <a class="taiga-link" href="${escapeHTML(pendingCard.url)}" target="_blank" rel="noopener noreferrer">
              <span>Xem chi tiết</span>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3h7v7h-2V6.41l-9.29 9.3-1.42-1.42 9.3-9.29H14V3ZM5 5h6v2H7v10h10v-4h2v6H5V5Z"/></svg>
            </a>
          </div>
        ` : ''}
      </article>
    `);
    pendingCard = null;
  }

  for (const line of lines.slice(1)) {
    const item = line.match(/^-\s+([a-z_]+)\s+#?([^:]+):\s+(.+?)\s+\|\s+(.+?)\s+\|\s+(.+?)\s+\|\s+(.+?)(?:\s+\|\s+(https?:\/\/\S+))?$/i);
    const detail = line.match(/^Chi tiết:\s+(.+)$/i);
    const more = line.match(/^Còn\s+(.+)$/i);
    if (item) {
      pushPendingCard();
      pendingCard = {
        type: item[1].replace('_', ' '),
        ref: item[2],
        subject: item[3],
        status: item[4],
        assignee: item[5],
        state: item[6],
        url: item[7] || '',
        description: '',
      };
    } else if (detail && pendingCard) {
      pendingCard.description = detail[1];
    } else if (more) {
      pushPendingCard();
      moreText = more[0];
    }
  }
  pushPendingCard();

  if (!cards.length) return '';
  return `
    <div class="taiga-answer">
      <h3>${renderInlineMarkdown(lines[0].replace(/:$/, ''))}</h3>
      <div class="taiga-list">${cards.join('')}</div>
      ${moreText ? `<div class="taiga-more">${escapeHTML(moreText)}</div>` : ''}
    </div>
  `;
}

function renderTaigaAnswer(text) {
  return renderTaigaCountAnswer(text) || renderTaigaListAnswer(text);
}

export function renderFormattedAnswer(bubble, text) {
  const trimmed = (text || '').trim();
  if (!trimmed) {
    bubble.textContent = '';
    return;
  }

  const taigaHTML = renderTaigaAnswer(trimmed);
  if (taigaHTML) {
    bubble.innerHTML = taigaHTML;
    return;
  }

  const blocks = [];
  let listType = null;
  let listItems = [];
  let paragraphLines = [];

  function flushParagraph() {
    if (paragraphLines.length === 0) return;
    blocks.push('<p>' + paragraphLines.map(renderInlineMarkdown).join('<br>') + '</p>');
    paragraphLines = [];
  }

  function flushList() {
    if (!listType) return;
    blocks.push('<' + listType + '>' + listItems.map((item) => '<li>' + renderInlineMarkdown(item) + '</li>').join('') + '</' + listType + '>');
    listType = null;
    listItems = [];
  }

  trimmed.split('\n').forEach((rawLine) => {
    const line = rawLine.trim();
    const ordered = line.match(/^\d+[.)]\s+(.+)$/);
    const unordered = line.match(/^[-*]\s+(.+)$/);
    const heading = line.match(/^#{1,3}\s+(.+)$/);

    if (!line) {
      flushParagraph();
      flushList();
      return;
    }

    if (heading) {
      flushParagraph();
      flushList();
      blocks.push('<h3>' + renderInlineMarkdown(heading[1]) + '</h3>');
      return;
    }

    if (ordered || unordered) {
      const nextType = ordered ? 'ol' : 'ul';
      flushParagraph();
      if (listType && listType !== nextType) {
        flushList();
      }
      listType = nextType;
      listItems.push((ordered || unordered)[1]);
      return;
    }

    flushList();
    paragraphLines.push(line);
  });

  flushParagraph();
  flushList();
  bubble.innerHTML = '<div class="formatted-answer">' + blocks.join('') + '</div>';
}
