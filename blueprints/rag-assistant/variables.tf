// =============================================================================
// API CONFIGURATION
// =============================================================================

variable "do_token" {
  type        = string
  description = "DigitalOcean API token"
  sensitive   = true
}

variable "_api_host" {
  type        = string
  default     = "https://api.digitalocean.com"
  description = "DigitalOcean API endpoint (internal use)"
}

// =============================================================================
// PROJECT CONFIGURATION
// =============================================================================

variable "project_uuid" {
  type        = string
  default     = ""
  description = "Existing project UUID (leave empty to create new project)"
}

variable "basename" {
  type        = string
  default     = "rag-assistant"
  description = "The base name used to auto-generate resource names."
}

variable "project_name" {
  type        = string
  default     = ""
  description = "Display name for the DO project. Defaults to basename if empty."
}

variable "region" {
  type        = string
  default     = "nyc3"
  description = "DigitalOcean region for all resources."
}

// =============================================================================
// MODEL CONFIGURATION
// =============================================================================

variable "default_model" {
  type        = string
  default     = "nvidia-nemotron-3-super-120b"
  description = "Serverless inference model internal name (for reference/display only)."
}

variable "model_uuid" {
  type        = string
  default     = ""
  description = "UUID of the serverless inference model. Resolved by do-terraform from the model internal name."
}

variable "embedding_model" {
  type        = string
  default     = "qwen3-embedding-0.6b"
  description = "Embedding model internal name (for reference/display only)."
}

variable "embedding_model_uuid" {
  type        = string
  description = "UUID of the embedding model. Resolved by do-terraform from the model internal name."
}

// =============================================================================
// APP PLATFORM CONFIGURATION
// =============================================================================

variable "app_instance_size" {
  type        = string
  default     = "apps-s-1vcpu-1gb"
  description = "App Platform instance size slug for the chat UI."
}

variable "_app_source_repo" {
  type        = string
  default     = "digitalocean/marketplace-blueprints"
  description = "GitHub repo for the app source code."
}

variable "_app_source_branch" {
  type        = string
  default     = "master"
  description = "Git branch for the app source code."
}

variable "taiga_base_url" {
  type        = string
  default     = ""
  description = "Taiga API base URL, for example https://api.taiga.io/api/v1. Leave empty to disable Taiga integration."
}

variable "taiga_username" {
  type        = string
  default     = ""
  description = "Taiga username for API authentication."
}

variable "taiga_password" {
  type        = string
  default     = ""
  description = "Taiga password for API authentication."
  sensitive   = true
}

variable "taiga_auth_token" {
  type        = string
  default     = ""
  description = "Optional Taiga auth token. When set, it is used instead of username/password."
  sensitive   = true
}

variable "taiga_project_id" {
  type        = string
  default     = ""
  description = "Taiga project ID to search. Preferred when known."
}

variable "taiga_project_slug" {
  type        = string
  default     = ""
  description = "Taiga project slug to resolve when project ID is not provided."
}

// =============================================================================
// AGENT CONFIGURATION
// =============================================================================

variable "existing_agent_uuid" {
  type        = string
  default     = ""
  description = "Existing GenAI agent UUID. When set, Terraform uses this agent instead of creating a new one."
}

variable "existing_agent_name" {
  type        = string
  default     = "RAG Assistant"
  description = "Display name for an existing GenAI agent used by the chat UI."
}

variable "agent_instruction" {
  type        = string
  default     = <<-EOT
    Bạn là trợ lý kỹ thuật chuyên hỗ trợ tích hợp Onflow OMS API.

    Mục tiêu của bạn là giúp lập trình viên triển khai đúng theo tài liệu Onflow: thiết lập môi trường, xác thực, cấu hình dữ liệu nền, sản phẩm, tồn kho, đơn hàng B2C/B2B, vận chuyển, nhập kho, hoàn hàng, đối tác vận chuyển, danh mục địa chỉ, mã trạng thái và webhook.

    Nguyên tắc trả lời:
    1. Chỉ hỗ trợ các câu hỏi liên quan trực tiếp đến tích hợp Onflow Open API. Với yêu cầu ngoài phạm vi, từ chối ngắn gọn và gợi ý một chủ đề API phù hợp.
    2. Trả lời bằng tiếng Việt, ngắn gọn nhưng đủ để triển khai; giữ nguyên tên field, endpoint, HTTP method và giá trị enum bằng tiếng Anh như tài liệu.
    3. Ưu tiên thông tin lấy từ knowledge base và đính kèm trích dẫn. Không tự tạo endpoint, field bắt buộc, mã trạng thái, payload hoặc quy tắc nghiệp vụ.
    4. Khi hướng dẫn gọi API, trình bày theo thứ tự: mục đích, môi trường/base URL, method và path, Authorization header, tham số hoặc payload bắt buộc, ví dụ request, cách đọc response, lỗi thường gặp.
    5. Dùng Staging để kiểm thử trước Production. Nhắc rằng API key của hai môi trường khác nhau và không bao giờ hiển thị API key thật trong ví dụ hoặc log.
    6. Với thao tác tạo hoặc cập nhật, khuyến nghị idempotency ở phía hệ thống tích hợp, timeout hợp lý, retry có exponential backoff chỉ cho lỗi tạm thời, và lưu log_id/tracking_code để đối soát. Không khuyến nghị retry mù các lỗi validation hoặc authentication.
    7. Với webhook, hướng dẫn xác thực nguồn theo cơ chế được tài liệu công bố, phản hồi nhanh, xử lý bất đồng bộ, chống xử lý trùng theo event_code và định danh đối tượng, đồng thời có cơ chế đối soát trạng thái qua API.
    8. Nếu câu hỏi thiếu dữ liệu quan trọng như loại đơn, môi trường, tracking code hay luồng fulfillment, nêu rõ giả định hoặc hỏi lại một câu ngắn trước khi đưa payload hoàn chỉnh.
    9. Nếu knowledge base không có câu trả lời hoặc tài liệu mâu thuẫn, nói rõ giới hạn, dẫn người dùng đến đúng trang tài liệu Onflow hoặc bộ phận Onflow Support; không suy đoán.

    Khi người dùng yêu cầu code, mặc định cung cấp cURL và thêm ngôn ngữ họ đang sử dụng nếu biết. Mọi ví dụ phải dùng biến môi trường hoặc placeholder như ONFLOW_API_KEY, không hard-code bí mật.
  EOT
  description = "System instruction for the managed agent."
}

variable "agent_temperature" {
  type        = number
  default     = 0
  description = "Temperature for inference (0.0 = deterministic, 1.0 = creative). Supplied by model preset."
}

variable "agent_max_tokens" {
  type        = number
  default     = 4096
  description = "Maximum tokens in the agent's response. Supplied by model preset."
}

variable "agent_k" {
  type        = number
  default     = 5
  description = "Number of knowledge base documents to retrieve per query."
}

variable "agent_retrieval_method" {
  type        = string
  default     = "RETRIEVAL_METHOD_SUB_QUERIES"
  description = "Knowledge base retrieval method for the managed agent."
}

// =============================================================================
// GUARDRAIL CONFIGURATION
// =============================================================================

variable "guardrail_jailbreak_uuid" {
  type        = string
  default     = ""
  description = "UUID of the jailbreak detection guardrail. Resolved by do-terraform."
}

variable "guardrail_content_mod_uuid" {
  type        = string
  default     = ""
  description = "UUID of the content moderation guardrail. Resolved by do-terraform."
}

variable "guardrail_sensitive_data_uuid" {
  type        = string
  default     = ""
  description = "UUID of the sensitive data detection guardrail. Resolved by do-terraform."
}
