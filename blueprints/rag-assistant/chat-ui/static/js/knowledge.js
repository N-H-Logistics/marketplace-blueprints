import {
  deleteKnowledgeBaseDataSource,
  fetchKnowledgeBases,
  uploadKnowledgeBaseFile,
} from './api.js';

export async function loadKnowledgeBases({
  kbOverviewMeta,
  kbOverviewBody,
  kbUploadButton,
  kbUploadInput,
  kbUploadStatus,
}) {
  if (!kbOverviewMeta || !kbOverviewBody) return;

  try {
    const data = await fetchKnowledgeBases();
    const knowledgeBases = data.knowledge_bases || [];
    renderKnowledgeBases(knowledgeBases, kbOverviewMeta, kbOverviewBody, kbUploadStatus);
    setupUpload({ knowledgeBases, kbOverviewMeta, kbOverviewBody, kbUploadButton, kbUploadInput, kbUploadStatus });
  } catch (err) {
    kbOverviewMeta.textContent = 'Không tải được';
    kbOverviewBody.innerHTML = '';
    const status = document.createElement('div');
    status.className = 'kb-status';
    status.textContent = err.message;
    kbOverviewBody.appendChild(status);
  }
}

function setupUpload(elements) {
  const { knowledgeBases, kbUploadButton, kbUploadInput, kbUploadStatus } = elements;
  if (!kbUploadButton || !kbUploadInput || knowledgeBases.length === 0) return;

  kbUploadButton.disabled = false;
  kbUploadButton.onclick = () => kbUploadInput.click();
  kbUploadInput.onchange = async () => {
    const file = kbUploadInput.files && kbUploadInput.files[0];
    kbUploadInput.value = '';
    if (!file) return;

    const kb = knowledgeBases[0];
    setUploadStatus(kbUploadStatus, `Đang tải ${file.name}...`, 'loading');
    kbUploadButton.disabled = true;
    try {
      await uploadKnowledgeBaseFile(kb.uuid, file);
      setUploadStatus(kbUploadStatus, 'Đã thêm tài liệu. Knowledge Base đang lập chỉ mục.', 'success');
      const refreshed = await fetchKnowledgeBases();
      renderKnowledgeBases(
        refreshed.knowledge_bases || [],
        elements.kbOverviewMeta,
        elements.kbOverviewBody,
        kbUploadStatus,
      );
    } catch (err) {
      setUploadStatus(kbUploadStatus, err.message, 'error');
    } finally {
      kbUploadButton.disabled = false;
    }
  };
}

function setUploadStatus(element, message, state) {
  if (!element) return;
  element.hidden = false;
  element.className = `kb-upload-status ${state}`;
  element.textContent = message;
}

function confirmDelete(fileName) {
  const modal = document.getElementById('kbDeleteModal');
  const name = document.getElementById('kbDeleteFileName');
  const cancel = document.getElementById('kbDeleteCancel');
  const confirm = document.getElementById('kbDeleteConfirm');
  if (!modal || !name || !cancel || !confirm) return Promise.resolve(false);

  const previousFocus = document.activeElement;
  name.textContent = fileName;
  modal.hidden = false;
  confirm.focus();

  return new Promise((resolve) => {
    const finish = (result) => {
      modal.hidden = true;
      cancel.removeEventListener('click', onCancel);
      confirm.removeEventListener('click', onConfirm);
      modal.removeEventListener('click', onBackdrop);
      document.removeEventListener('keydown', onKeydown);
      if (previousFocus instanceof HTMLElement) previousFocus.focus();
      resolve(result);
    };
    const onCancel = () => finish(false);
    const onConfirm = () => finish(true);
    const onBackdrop = (event) => {
      if (event.target === modal) finish(false);
    };
    const onKeydown = (event) => {
      if (event.key === 'Escape') finish(false);
    };

    cancel.addEventListener('click', onCancel);
    confirm.addEventListener('click', onConfirm);
    modal.addEventListener('click', onBackdrop);
    document.addEventListener('keydown', onKeydown);
  });
}

function renderKnowledgeBases(knowledgeBases, kbOverviewMeta, kbOverviewBody, kbUploadStatus) {
  const allSources = knowledgeBases.flatMap((kb) => (
    (kb.datasources || []).map((source) => ({ ...source, kbName: kb.name, kbUuid: kb.uuid }))
  ));
  kbOverviewBody.innerHTML = '';

  if (allSources.length === 0) {
    kbOverviewMeta.textContent = '0 tài liệu';
    const status = document.createElement('div');
    status.className = 'kb-status';
    status.textContent = 'Chưa có datasource nào trong Knowledge Base đang gắn với agent.';
    kbOverviewBody.appendChild(status);
    return;
  }

  kbOverviewMeta.textContent = `${allSources.length} tài liệu`;
  const list = document.createElement('div');
  list.className = 'kb-list';

  allSources.forEach((source) => {
    const item = document.createElement('div');
    item.className = 'kb-item';

    const icon = document.createElement('div');
    icon.className = 'kb-file-icon ' + getSourceIconClass(source);
    icon.innerHTML = getSourceIcon(source);

    const main = document.createElement('div');
    main.className = 'kb-item-main';

    const name = document.createElement('div');
    name.className = 'kb-item-name';
    name.title = source.name;
    name.textContent = source.name;

    const meta = document.createElement('div');
    meta.className = 'kb-item-meta';
    meta.textContent = formatSourceMeta(source, knowledgeBases.length > 1);

    main.appendChild(name);
    main.appendChild(meta);
    item.appendChild(icon);
    item.appendChild(main);

    if (source.uuid && source.kbUuid) {
      const deleteButton = document.createElement('button');
      deleteButton.className = 'kb-delete-btn';
      deleteButton.type = 'button';
      deleteButton.title = `Xoá ${source.name}`;
      deleteButton.setAttribute('aria-label', `Xoá ${source.name}`);
      deleteButton.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 3h6l1 2h4v2H4V5h4l1-2Zm-2 6h10l-1 12H8L7 9Zm3 2v8h2v-8h-2Zm4 0v8h2v-8h-2Z"/></svg>';
      deleteButton.onclick = async () => {
        if (!await confirmDelete(source.name)) return;

        deleteButton.disabled = true;
        setUploadStatus(
          kbUploadStatus,
          `Đang xoá ${source.name} khỏi Knowledge Base (thao tác này không tạo indexing job)...`,
          'loading',
        );
        try {
          await deleteKnowledgeBaseDataSource(source.kbUuid, source.uuid);
          item.remove();
          const remaining = list.childElementCount;
          kbOverviewMeta.textContent = `${remaining} tài liệu`;
          if (remaining === 0) {
            renderKnowledgeBases(knowledgeBases.map((kb) => ({ ...kb, datasources: [] })), kbOverviewMeta, kbOverviewBody, kbUploadStatus);
          }
          setUploadStatus(
            kbUploadStatus,
            'Đã xoá tài liệu khỏi Knowledge Base. Không cần chờ re-index.',
            'success',
          );
        } catch (err) {
          deleteButton.disabled = false;
          setUploadStatus(kbUploadStatus, err.message, 'error');
        }
      };
      item.appendChild(deleteButton);
    }
    list.appendChild(item);
  });

  kbOverviewBody.appendChild(list);
}

function formatSourceMeta(source, showKbName) {
  const parts = [];
  if (source.type === 'file') {
    parts.push('PDF');
  } else if (source.type === 'web') {
    parts.push('Web');
  }
  if (source.size_bytes) {
    parts.push(formatBytes(source.size_bytes));
  }
  if (showKbName && source.kbName) {
    parts.push(source.kbName);
  }
  return parts.join(' · ') || 'Nguồn dữ liệu';
}

function getSourceIconClass(source) {
  if (source.type === 'web') return 'web';
  const name = (source.name || '').toLowerCase();
  if (name.endsWith('.pdf')) return 'pdf';
  return 'file';
}

function getSourceIcon(source) {
  if (source.type === 'web') {
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm6.93 9h-3.1a15.5 15.5 0 0 0-1.08-5.1A8.04 8.04 0 0 1 18.93 11ZM12 4.04c.68.98 1.52 3.04 1.77 6.96h-3.54C10.48 7.08 11.32 5.02 12 4.04ZM4.26 13h3.91c.12 1.95.45 3.69.96 5.1A8.04 8.04 0 0 1 4.26 13Zm3.91-2H4.26A8.04 8.04 0 0 1 9.13 5.9 15.5 15.5 0 0 0 8.17 11ZM12 19.96c-.68-.98-1.52-3.04-1.77-6.96h3.54c-.25 3.92-1.09 5.98-1.77 6.96Zm2.87-1.86c.51-1.41.84-3.15.96-5.1h3.1a8.04 8.04 0 0 1-4.06 5.1Z"/></svg>';
  }
  return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6Zm-1 7V4l5 5h-5Zm-6 5h10v2H7v-2Zm0 4h7v2H7v-2Zm0-8h4v2H7v-2Z"/></svg>';
}

function formatBytes(bytes) {
  if (!bytes) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}
