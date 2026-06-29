import { createTaigaIssue, fetchTaigaMetadata } from './api.js';

let metadataCache = null;

export function isCreateTaigaIssueIntent(message) {
  const text = (message || '').toLowerCase();
  const createWords = ['tạo', 'tao', 'thêm', 'them', 'ghi nhận', 'ghi nhan'];
  const issueWords = ['báo lỗi', 'bao loi', 'lỗi', 'bug', 'issue', 'ticket'];
  return createWords.some((word) => text.includes(word)) && issueWords.some((word) => text.includes(word));
}

function extractTaigaIssueSubject(message) {
  return (message || '')
    .trim()
    .replace(/^(hãy|hay|vui lòng|vui long)\s+/i, '')
    .replace(/^(tạo|tao|thêm|them|ghi nhận|ghi nhan)\s+/i, '')
    .replace(/^(một|mot|1)\s+/i, '')
    .replace(/^(báo lỗi|bao loi|bug|issue|ticket)\s*/i, '')
    .replace(/^trên\s+taiga\s*/i, '')
    .replace(/^taiga\s*/i, '')
    .replace(/^[:：,\-\s]+/, '')
    .trim();
}

function fillSelect(select, options, selectedId, blankLabel) {
  select.innerHTML = '';
  if (blankLabel) {
    const blank = document.createElement('option');
    blank.value = '';
    blank.textContent = blankLabel;
    select.appendChild(blank);
  }
  (options || []).forEach((option) => {
    const item = document.createElement('option');
    item.value = String(option.id);
    item.textContent = option.username ? `${option.name} (${option.username})` : option.name;
    if (String(option.id) === String(selectedId || '')) {
      item.selected = true;
    }
    select.appendChild(item);
  });
}

function formatCreatedIssueContent(issue) {
  const ref = issue.ref ? `#${issue.ref}` : `id ${issue.id}`;
  const status = issue.status || 'New';
  const assignee = issue.assigned_to || 'chưa gán';
  const state = issue.is_closed ? 'đã đóng' : 'đang mở';
  let content = `Đã tạo báo lỗi Taiga:\n- issue ${ref}: ${issue.subject || ''} | ${status} | ${assignee} | ${state}`;
  if (issue.url) {
    content += ` | ${issue.url}`;
  }
  if (issue.description) {
    content += `\n  Chi tiết: ${issue.description}`;
  }
  return content;
}

export function createTaigaIssueForm({ el, onCreated, onCloseFocus }) {
  let isCreating = false;

  function setError(message) {
    el.taigaIssueError.hidden = !message;
    el.taigaIssueError.textContent = message || '';
  }

  function setBusy(busy) {
    isCreating = busy;
    el.taigaIssueSubmit.disabled = busy;
    el.taigaIssueCancel.disabled = busy;
    el.taigaIssueClose.disabled = busy;
    el.taigaIssueSubmit.textContent = busy ? 'Đang tạo...' : 'Tạo báo lỗi';
    Array.from(el.taigaIssueForm.elements).forEach((field) => {
      if (field !== el.taigaIssueCancel && field !== el.taigaIssueClose) {
        field.disabled = busy;
      }
    });
  }

  async function loadMetadata() {
    if (metadataCache) return metadataCache;
    metadataCache = await fetchTaigaMetadata();
    return metadataCache;
  }

  async function open(message) {
    el.taigaIssueModal.hidden = false;
    setError('');
    el.taigaIssueSubject.value = extractTaigaIssueSubject(message);
    el.taigaIssueDescription.value = '';
    el.taigaIssueSubmit.disabled = true;
    el.taigaIssueSubmit.textContent = 'Đang tải...';

    try {
      const metadata = await loadMetadata();
      const defaults = metadata.defaults || {};
      fillSelect(el.taigaIssueType, metadata.types, defaults.type);
      fillSelect(el.taigaIssueStatus, metadata.statuses, defaults.status);
      fillSelect(el.taigaIssuePriority, metadata.priorities, defaults.priority);
      fillSelect(el.taigaIssueSeverity, metadata.severities, defaults.severity);
      fillSelect(el.taigaIssueAssignee, metadata.members, '', 'Chưa gán');
      el.taigaIssueSubmit.disabled = false;
      el.taigaIssueSubmit.textContent = 'Tạo báo lỗi';
      el.taigaIssueSubject.focus();
      el.taigaIssueSubject.select();
    } catch (err) {
      setError(err.message);
      el.taigaIssueSubmit.textContent = 'Tạo báo lỗi';
    }
  }

  function close() {
    if (isCreating) return;
    el.taigaIssueModal.hidden = true;
    setError('');
    el.taigaIssueForm.reset();
    onCloseFocus();
  }

  async function submit(e) {
    e.preventDefault();
    setError('');

    const subject = el.taigaIssueSubject.value.trim();
    if (!subject) {
      setError('Vui lòng nhập tiêu đề báo lỗi.');
      el.taigaIssueSubject.focus();
      return;
    }

    setBusy(true);
    try {
      const data = await createTaigaIssue({
        subject,
        description: el.taigaIssueDescription.value.trim(),
        type: el.taigaIssueType.value,
        status: el.taigaIssueStatus.value,
        priority: el.taigaIssuePriority.value,
        severity: el.taigaIssueSeverity.value,
        assigned_to: el.taigaIssueAssignee.value,
      });

      const content = formatCreatedIssueContent(data.issue || {});
      onCreated(content);
      setBusy(false);
      close();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  el.taigaIssueClose.addEventListener('click', close);
  el.taigaIssueCancel.addEventListener('click', close);
  el.taigaIssueModal.addEventListener('click', function(e) {
    if (e.target === el.taigaIssueModal && !isCreating) {
      close();
    }
  });
  el.taigaIssueForm.addEventListener('submit', submit);

  return {
    open,
    close,
    get isCreating() {
      return isCreating;
    },
  };
}
