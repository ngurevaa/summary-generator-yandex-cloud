terraform {
  required_providers {
    yandex = {
      source  = "yandex-cloud/yandex"
    }
  }
  required_version = ">= 0.13"
}

provider "yandex" {
  cloud_id  = var.cloud_id
  folder_id = var.folder_id
  zone      = "ru-central1-a"
  token = var.yandex_oauth_token
}

# 1. Создаем сервисный аккаунт
resource "yandex_iam_service_account" "generator_sa" {
  name        = "generator-sa"
  description = "Service account for Summary Generator"
  folder_id = var.folder_id
}

# 2. Даем права на Object Storage
resource "yandex_resourcemanager_folder_iam_member" "storage_editor" {
  folder_id = var.folder_id
  role      = "storage.editor"
  member    = "serviceAccount:${yandex_iam_service_account.generator_sa.id}"
}

# 3. Создаем статический ключ
resource "yandex_iam_service_account_static_access_key" "sa_static_key" {
  service_account_id = yandex_iam_service_account.generator_sa.id
  description        = "Service account static key"
}

# 4. Создаем бакет 
resource "yandex_storage_bucket" "generator_bucket" {
  bucket     = "generator-bucket"  
  access_key = yandex_iam_service_account_static_access_key.sa_static_key.access_key
  secret_key = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
}

# 5. Загружаем input.html
resource "yandex_storage_object" "input_html" {
  bucket       = yandex_storage_bucket.generator_bucket.bucket
  key          = "input.html"
  source       = "../frontend/input.html"
  content_type = "text/html; charset=utf-8"
  
  # Используем новую схему вместо acl
  access_key = yandex_iam_service_account_static_access_key.sa_static_key.access_key
  secret_key = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
}

# Загружаем tasks.html
resource "yandex_storage_object" "tasks_html" {
  bucket       = yandex_storage_bucket.generator_bucket.bucket
  key          = "tasks.html"
  source       = "../frontend/tasks.html"
  content_type = "text/html; charset=utf-8"
  
  access_key = yandex_iam_service_account_static_access_key.sa_static_key.access_key
  secret_key = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
}

# 8. Даем права на Message Queue
resource "yandex_resourcemanager_folder_iam_member" "queue_admin" {
  folder_id = var.folder_id
  role      = "ymq.admin"  
  member    = "serviceAccount:${yandex_iam_service_account.generator_sa.id}"
}

# 9. Создаем FIFO очередь для задач 
resource "yandex_message_queue" "tasks_queue" {
  name                        = "summary-generator-tasks"
  visibility_timeout_seconds  = 300
  receive_wait_time_seconds   = 20
  message_retention_seconds   = 1209600
  
  # Используем ключи от уже созданного SA
  access_key = yandex_iam_service_account_static_access_key.sa_static_key.access_key
  secret_key = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
}

resource "yandex_function_trigger" "queue_trigger" {
  name        = "queue-trigger"
  description = "Trigger for processing messages from YMQ"
  
  message_queue {
    queue_id           = yandex_message_queue.tasks_queue.arn
    service_account_id = yandex_iam_service_account.generator_sa.id
    batch_size         = 1  # Обрабатываем по одному сообщению
    batch_cutoff       = 10
  }
  
  function {
    id = yandex_function.task_processor.id
    service_account_id = yandex_iam_service_account.generator_sa.id
  }
}

# 10. Архивация 
data "archive_file" "task_receiver" {
  type        = "zip"
  source_dir  = "${path.module}/../functions/task-receiver"
  output_path = "${path.module}/../functions/task-receiver.zip"
}

data "archive_file" "task_processor" {
  type        = "zip"
  source_dir  = "${path.module}/../functions/task-processor"
  output_path = "${path.module}/../functions/task-processor.zip"
}

# 11. Cloud Function для создания задачи
resource "yandex_function" "task_receiver" {
  name               = "task-receiver"
  description        = "Get task and send it to queue"
  user_hash          = data.archive_file.task_receiver.output_base64sha256
  runtime            = "python39"
  entrypoint         = "main.handler"
  memory             = 128
  execution_timeout  = 15 
  service_account_id = yandex_iam_service_account.generator_sa.id
  
  environment = {
    QUEUE_URL              = yandex_message_queue.tasks_queue.id
    AWS_ACCESS_KEY_ID      = yandex_iam_service_account_static_access_key.sa_static_key.access_key
    AWS_SECRET_ACCESS_KEY  = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
    PYTHONUNBUFFERED       = "1"
  }
  
  content {
    zip_filename = data.archive_file.task_receiver.output_path
  }
}

resource "yandex_function" "task_processor" {
  name               = "task-processor"
  description        = "Process tasks from queue: download video, generate summary, create PDF"
  user_hash          = data.archive_file.task_processor.output_base64sha256
  runtime            = "python39"
  entrypoint         = "main.handler"
  memory             = 512  
  execution_timeout  = 600 
  service_account_id = yandex_iam_service_account.generator_sa.id
  
  environment = {
    AWS_ACCESS_KEY_ID      = yandex_iam_service_account_static_access_key.sa_static_key.access_key
    AWS_SECRET_ACCESS_KEY  = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
    BUCKET_NAME            = yandex_storage_bucket.generator_bucket.bucket
    FOLDER_ID              = var.folder_id
    PYTHONUNBUFFERED       = "1"
  }
  
  content {
    zip_filename = data.archive_file.task_processor.output_path
  }
}

# 12. Даем права на исполнение функции
resource "yandex_resourcemanager_folder_iam_member" "sa_function_invoker" {
  folder_id = var.folder_id
  role      = "serverless.functions.invoker"
  member    = "serviceAccount:${yandex_iam_service_account.generator_sa.id}"
}

# 13. API Gateway
resource "yandex_api_gateway" "summary_generator_api" {
  name = "summary-generator-api-gateway"
  
  spec = <<-EOT
openapi: 3.0.0
info:
  title: Summary Generator API
  version: 1.0.0
paths:
  /:
    get:
      x-yc-apigateway-integration:
        type: object_storage
        bucket: ${yandex_storage_bucket.generator_bucket.bucket}
        object: input.html
        service_account_id: ${yandex_iam_service_account.generator_sa.id}
  /tasks:
    get:
      x-yc-apigateway-integration:
        type: object_storage
        bucket: ${yandex_storage_bucket.generator_bucket.bucket}
        object: tasks.html
        service_account_id: ${yandex_iam_service_account.generator_sa.id}
  /api/tasks:
    options:
      x-yc-apigateway-integration:
        type: dummy
        content:
          '*': ""
        http_headers:
          Access-Control-Allow-Origin: "*"
          Access-Control-Allow-Methods: "POST, OPTIONS, GET"
          Access-Control-Allow-Headers: "Content-Type, Authorization, X-Requested-With"
          Access-Control-Max-Age: "86400"
        http_code: 200
    post:
      x-yc-apigateway-integration:
        type: cloud-functions
        function_id: ${yandex_function.task_receiver.id}
        service_account_id: ${yandex_iam_service_account.generator_sa.id}
        tag: $latest
EOT
}

# 14. Вывод API Gateway URL
output "api_gateway_url" {
  value = "https://${yandex_api_gateway.summary_generator_api.domain}"
  description = "URL API Gateway"
}