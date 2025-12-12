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

# 8. Даем SA права на работу с очередью
resource "yandex_resourcemanager_folder_iam_member" "mq_writer" {
  folder_id = var.folder_id
  role      = "ymq.writer"
  member    = "serviceAccount:${yandex_iam_service_account.generator_sa.id}"
}

resource "yandex_resourcemanager_folder_iam_member" "mq_reader" {
  folder_id = var.folder_id
  role      = "ymq.reader"
  member    = "serviceAccount:${yandex_iam_service_account.generator_sa.id}"
}

# 9. Создаем FIFO очередь для задач 
resource "yandex_message_queue" "tasks_queue" {
  name                        = "summary-generator-tasks.fifo"
  visibility_timeout_seconds  = 300
  receive_wait_time_seconds   = 20
  message_retention_seconds   = 1209600
  fifo_queue                  = true
  
  # Используем ключи от уже созданного SA
  access_key = yandex_iam_service_account_static_access_key.sa_static_key.access_key
  secret_key = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
}

# 10. Архивация
data "archive_file" "task_receiver" {
  type        = "zip"
  source_dir  = "${path.module}/../functions/task-receiver"
  output_path = "${path.module}/../functions/task-receiver.zip"
}

# 11. Cloud Function с boto3
resource "yandex_function" "task_receiver" {
  name               = "task-receiver"
  description        = "Get task and send it to queue"
  user_hash          = data.archive_file.task_receiver.output_base64sha256
  runtime            = "python39"
  entrypoint         = "main.handler"  # main.py -> функция handler
  memory             = 128
  execution_timeout  = 15 
  service_account_id = yandex_iam_service_account.generator_sa.id
  
  # Переменные окружения для boto3
  environment = {
    QUEUE_URL              = yandex_message_queue.tasks_queue.id
    AWS_ACCESS_KEY_ID      = yandex_iam_service_account_static_access_key.sa_static_key.access_key
    AWS_SECRET_ACCESS_KEY  = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
    PYTHONUNBUFFERED       = "1"
  }
  
  # Содержимое функции
  content {
    zip_filename = data.archive_file.task_receiver.output_path
  }
}

# 3. Разрешаем публичный доступ (для теста)
resource "yandex_function_iam_binding" "receiver_invoker" {
  function_id = yandex_function.task_receiver.id
  role        = "serverless.functions.invoker"
  
  members = [
    "system:allUsers",  # Позже заменить на API Gateway
  ]
}

# 4. Output URL функции
output "receiver_function_url" {
  value = "https://functions.yandexcloud.net/${yandex_function.task_receiver.id}"
  description = "URL для вызова функции приема задач"
}

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

# 2. Output API Gateway URL
output "api_gateway_url" {
  value = "https://${yandex_api_gateway.summary_generator_api.domain}"
  description = "URL API Gateway"
}