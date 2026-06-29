# Chat UI deployed on App Platform.
# Serves a simple web interface that calls the managed agent's chat API.
# The app self-discovers the agent's deployment URL and API key at startup.
resource "digitalocean_app" "chat_ui" {
  depends_on = [null_resource.agent_post_setup]

  spec {
    name   = "${local.resource_name}-chat"
    region = var.region

    domain {
      name = "ai.onflow.vn"
      type = "PRIMARY"
    }

    database {
      name         = "genai-seahorse"
      engine       = "OPENSEARCH"
      version      = "2.19"
      production   = true
      cluster_name = "genai-seahorse"
    }

    ingress {
      rule {
        component {
          name = "chat-ui"
        }
        match {
          path {
            prefix = "/"
          }
        }
      }
    }

    service {
      name               = "chat-ui"
      instance_count     = 1
      instance_size_slug = var.app_instance_size
      http_port          = 8080

      git {
        repo_clone_url = "https://github.com/${var._app_source_repo}.git"
        branch         = var._app_source_branch
      }

      source_dir      = "blueprints/rag-assistant/chat-ui"
      dockerfile_path = "blueprints/rag-assistant/chat-ui/Dockerfile"

      env {
        key   = "AGENT_UUID"
        value = local.active_agent_uuid
        scope = "RUN_TIME"
      }

      env {
        key   = "DO_API_TOKEN"
        value = var.do_token
        scope = "RUN_TIME"
        type  = "SECRET"
      }

      env {
        key   = "AGENT_NAME"
        value = local.active_agent_name
        scope = "RUN_TIME"
      }

      env {
        key   = "DATABASE_URL"
        value = "$${genai-seahorse.DATABASE_URL}"
        scope = "RUN_TIME"
      }

      env {
        key   = "TAIGA_BASE_URL"
        value = var.taiga_base_url
        scope = "RUN_TIME"
      }

      env {
        key   = "TAIGA_USERNAME"
        value = var.taiga_username
        scope = "RUN_TIME"
      }

      env {
        key   = "TAIGA_PASSWORD"
        value = var.taiga_password
        scope = "RUN_TIME"
        type  = "SECRET"
      }

      env {
        key   = "TAIGA_AUTH_TOKEN"
        value = var.taiga_auth_token
        scope = "RUN_TIME"
        type  = "SECRET"
      }

      env {
        key   = "TAIGA_PROJECT_ID"
        value = var.taiga_project_id
        scope = "RUN_TIME"
      }

      env {
        key   = "TAIGA_PROJECT_SLUG"
        value = var.taiga_project_slug
        scope = "RUN_TIME"
      }
    }
  }
}
