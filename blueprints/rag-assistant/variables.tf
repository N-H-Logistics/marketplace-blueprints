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
  default     = "You are a helpful RAG assistant. Answer questions using the knowledge base context provided. If you don't know the answer, say so honestly."
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
