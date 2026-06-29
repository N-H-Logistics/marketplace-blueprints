async function readJsonResponse(res, fallbackMessage) {
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || fallbackMessage);
  }
  return data;
}

export async function fetchKnowledgeBases() {
  const res = await fetch('/api/knowledge-bases');
  return readJsonResponse(res, 'Không lấy được thông tin Knowledge Base.');
}

export async function uploadKnowledgeBaseFile(knowledgeBaseUuid, file) {
  const query = new URLSearchParams({
    knowledge_base_uuid: knowledgeBaseUuid,
    file_name: file.name,
    file_size: String(file.size),
  });
  const res = await fetch(`/api/knowledge-bases/uploads/file?${query}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/octet-stream' },
    body: file,
  });
  return readJsonResponse(res, 'Không tải được tài liệu lên Knowledge Base.');
}

export async function deleteKnowledgeBaseDataSource(knowledgeBaseUuid, dataSourceUuid) {
  const kb = encodeURIComponent(knowledgeBaseUuid);
  const source = encodeURIComponent(dataSourceUuid);
  const res = await fetch(`/api/knowledge-bases/${kb}/data-sources/${source}`, { method: 'DELETE' });
  return readJsonResponse(res, 'Không xoá được tài liệu khỏi Knowledge Base.');
}

export async function fetchTaigaMetadata() {
  const res = await fetch('/api/taiga/metadata');
  return readJsonResponse(res, 'Không lấy được cấu hình Taiga.');
}

export async function createTaigaIssue(payload) {
  const res = await fetch('/api/taiga/issues', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  return readJsonResponse(res, 'Không tạo được báo lỗi Taiga.');
}

export function streamChat(message, history) {
  return fetch('/api/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, history }),
  });
}
