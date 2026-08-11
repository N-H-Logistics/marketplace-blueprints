# Knowledge base for RAG document retrieval.
# Seeded with the complete Onflow API documentation. The site exposes developer
# guides, endpoint references, status codes, and webhook contracts below this URL.
# NOTE: Knowledge bases currently only support the tor1 region.
resource "digitalocean_gradientai_knowledge_base" "kb" {
  name                 = "${local.resource_name}-kb"
  project_id           = local.active_project_id
  region               = "tor1"
  embedding_model_uuid = var.embedding_model_uuid
  tags                 = [digitalocean_tag.tag.name]

  datasources {
    web_crawler_data_source {
      base_url        = "https://developers.onflow.vn/"
      crawling_option = "PATH"
    }
  }
}
