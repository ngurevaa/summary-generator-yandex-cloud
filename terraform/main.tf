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
  zone      = var.zone
  token = var.YC_TOKEN
}

# 1. Создаем сервисный аккаунт
resource "yandex_iam_service_account" "generator_sa" {
  name        = "${var.prefix}-generator-sa"
  description = "Service account for Summary Generator"
  folder_id = var.folder_id
}

# 2. Даем права на Object Storage
resource "yandex_resourcemanager_folder_iam_member" "storage_editor" {
  folder_id = var.folder_id
  role      = "storage.admin"
  member    = "serviceAccount:${yandex_iam_service_account.generator_sa.id}"
}

resource "yandex_resourcemanager_folder_iam_member" "ydb_editor" {
  folder_id = var.folder_id
  role      = "ydb.admin"
  member    = "serviceAccount:${yandex_iam_service_account.generator_sa.id}"
}

resource "yandex_resourcemanager_folder_iam_member" "speechkit_access" {
  folder_id = var.folder_id
  role      = "ai.speechkit-stt.user" 
  member    = "serviceAccount:${yandex_iam_service_account.generator_sa.id}"
}

resource "yandex_resourcemanager_folder_iam_member" "function_invoker" {
  folder_id = var.folder_id
  role      = "serverless.functions.invoker"
  member    = "serviceAccount:${yandex_iam_service_account.generator_sa.id}"
}

# 3. Создаем статический ключ
resource "yandex_iam_service_account_static_access_key" "sa_static_key" {
  service_account_id = yandex_iam_service_account.generator_sa.id
  description        = "Service account static key"
}

resource "yandex_iam_service_account_api_key" "sa_api_key" {
  service_account_id = yandex_iam_service_account.generator_sa.id
  description        = "Service account API key"
}

# 4. Создаем бакет 
resource "yandex_storage_bucket" "generator_bucket" {
  bucket     = "${var.prefix}-generator-bucket"  
  access_key = yandex_iam_service_account_static_access_key.sa_static_key.access_key
  secret_key = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
}

# 5. Загружаем input.html
resource "yandex_storage_object" "input_html" {
  bucket       = yandex_storage_bucket.generator_bucket.bucket
  key          = "input.html"
  source       = "../frontend/input.html"
  content_type = "text/html; charset=utf-8"
  
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

resource "yandex_storage_object" "audio_extractor_zip" {
  bucket       = yandex_storage_bucket.generator_bucket.bucket
  key          = "audio-extractor.zip"
  source       = data.archive_file.audio_extractor.output_path
  content_type = "application/zip"

  access_key   = yandex_iam_service_account_static_access_key.sa_static_key.access_key
  secret_key   = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
}

# 8. Даем права на Message Queue
resource "yandex_resourcemanager_folder_iam_member" "queue_admin" {
  folder_id = var.folder_id
  role      = "ymq.admin"  
  member    = "serviceAccount:${yandex_iam_service_account.generator_sa.id}"
}

resource "yandex_resourcemanager_folder_iam_member" "gpt_user" {
  folder_id = var.folder_id  # или yandex_resourcemanager_folder.folder.id
  role      = "ai.languageModels.user"
  member    = "serviceAccount:${yandex_iam_service_account.generator_sa.id}"
}

# 9. Создаем очередь для задач 
resource "yandex_message_queue" "video_downloader_queue" {
  name                        = "${var.prefix}-video-downloader-queue"
  visibility_timeout_seconds  = 300
  receive_wait_time_seconds   = 20
  message_retention_seconds   = 1209600
  
  access_key = yandex_iam_service_account_static_access_key.sa_static_key.access_key
  secret_key = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
}

resource "yandex_message_queue" "audio_extractor_queue" {
  name                        = "${var.prefix}-audio-extractor-queue"
  visibility_timeout_seconds  = 300
  receive_wait_time_seconds   = 20
  message_retention_seconds   = 1209600
  
  access_key = yandex_iam_service_account_static_access_key.sa_static_key.access_key
  secret_key = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
}

resource "yandex_message_queue" "speech_recognizer_queue" {
  name                        = "${var.prefix}-speech-recognizer-queue"
  visibility_timeout_seconds  = 300
  receive_wait_time_seconds   = 20
  message_retention_seconds   = 1209600
  
  access_key = yandex_iam_service_account_static_access_key.sa_static_key.access_key
  secret_key = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
}

resource "yandex_message_queue" "speech_recognizer_checker_queue" {
  name                        = "${var.prefix}-speech-recognizer-checker-queue"
  visibility_timeout_seconds  = 300
  receive_wait_time_seconds   = 20
  message_retention_seconds   = 1209600
  
  access_key = yandex_iam_service_account_static_access_key.sa_static_key.access_key
  secret_key = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
}

resource "yandex_message_queue" "note_generator_queue" {
  name                        = "${var.prefix}-note-generator-queue"
  visibility_timeout_seconds  = 300
  receive_wait_time_seconds   = 20
  message_retention_seconds   = 1209600
  
  access_key = yandex_iam_service_account_static_access_key.sa_static_key.access_key
  secret_key = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
}

resource "yandex_function_trigger" "video_downloader_trigger" {
  name        = "${var.prefix}-video-downloader-queue-trigger"
  description = "Trigger for processing messages from video_downloader queue"
  
  message_queue {
    queue_id           = yandex_message_queue.video_downloader_queue.arn
    service_account_id = yandex_iam_service_account.generator_sa.id
    batch_size         = 1
    batch_cutoff       = 10
  }
  
  function {
    id = yandex_function.video_downloader.id
    service_account_id = yandex_iam_service_account.generator_sa.id
  }
}

resource "yandex_function_trigger" "audio_extractor_trigger" {
  name        = "${var.prefix}-audio-extractor-queue-trigger"
  description = "Trigger for processing messages from audio_extractor queue"
  
  message_queue {
    queue_id           = yandex_message_queue.audio_extractor_queue.arn
    service_account_id = yandex_iam_service_account.generator_sa.id
    batch_size         = 1
    batch_cutoff       = 10
  }
  
  function {
    id = yandex_function.audio_extractor.id
    service_account_id = yandex_iam_service_account.generator_sa.id
  }
}

resource "yandex_function_trigger" "speech_recognizer_trigger" {
  name        = "${var.prefix}-speech-recognizer-queue-trigger"
  description = "Trigger for processing messages from speech_recognizer_queue"
  
  message_queue {
    queue_id           = yandex_message_queue.speech_recognizer_queue.arn
    service_account_id = yandex_iam_service_account.generator_sa.id
    batch_size         = 1
    batch_cutoff       = 10
  }
  
  function {
    id = yandex_function.speech_recognizer.id
    service_account_id = yandex_iam_service_account.generator_sa.id
  }
}

resource "yandex_function_trigger" "speech_recognizer_checker_trigger" {
  name        = "${var.prefix}-speech-recognizer-checker-queue-trigger"
  description = "Trigger for processing messages from speech_recognizer_checker_queue"
  
  message_queue {
    queue_id           = yandex_message_queue.speech_recognizer_checker_queue.arn
    service_account_id = yandex_iam_service_account.generator_sa.id
    batch_size         = 1
    batch_cutoff       = 10
  }
  
  function {
    id = yandex_function.speech_recognizer_checker.id
    service_account_id = yandex_iam_service_account.generator_sa.id
  }
}

resource "yandex_function_trigger" "note_generator_trigger" {
  name        = "${var.prefix}-note-generator-queue-trigger"
  description = "Trigger for processing messages from note_generator_queue"
  
  message_queue {
    queue_id           = yandex_message_queue.note_generator_queue.arn
    service_account_id = yandex_iam_service_account.generator_sa.id
    batch_size         = 1
    batch_cutoff       = 10
  }
  
  function {
    id = yandex_function.note_generator.id
    service_account_id = yandex_iam_service_account.generator_sa.id
  }
}

# 10. Архивация 
data "archive_file" "task_receiver" {
  type        = "zip"
  source_dir  = "${path.module}/../functions/task-receiver"
  output_path = "${path.module}/../functions/task-receiver.zip"
}

data "archive_file" "video_downloader" {
  type        = "zip"
  source_dir  = "${path.module}/../functions/video-downloader"
  output_path = "${path.module}/../functions/video-downloader.zip"
}

data "archive_file" "audio_extractor" {
  type        = "zip"
  source_dir  = "${path.module}/../functions/audio-extractor"
  output_path = "${path.module}/../functions/audio-extractor.zip"
}

data "archive_file" "speech_recognizer" {
  type        = "zip"
  source_dir  = "${path.module}/../functions/speech-recognizer"
  output_path = "${path.module}/../functions/speech-recognizer.zip"
}

data "archive_file" "speech_recognizer_checker" {
  type        = "zip"
  source_dir  = "${path.module}/../functions/speech-recognizer-checker"
  output_path = "${path.module}/../functions/speech-recognizer-checker.zip"
}

data "archive_file" "note_generator" {
  type        = "zip"
  source_dir  = "${path.module}/../functions/note-generator"
  output_path = "${path.module}/../functions/note-generator.zip"
}

# 11. Cloud Function для создания задачи
resource "yandex_function" "task_receiver" {
  name               = "${var.prefix}-task-receiver"
  description        = "Create task"
  user_hash          = data.archive_file.task_receiver.output_base64sha256
  runtime            = "python39"
  entrypoint         = "main.handler"
  memory             = 128
  execution_timeout  = 15 
  service_account_id = yandex_iam_service_account.generator_sa.id
  
  environment = {
    QUEUE_URL              = yandex_message_queue.video_downloader_queue.id
    AWS_ACCESS_KEY_ID      = yandex_iam_service_account_static_access_key.sa_static_key.access_key
    AWS_SECRET_ACCESS_KEY  = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
    YDB_ENDPOINT = yandex_ydb_database_serverless.tasks_database.ydb_api_endpoint
    YDB_DATABASE = yandex_ydb_database_serverless.tasks_database.database_path
    PYTHONUNBUFFERED       = "1"
  }
  
  content {
    zip_filename = data.archive_file.task_receiver.output_path
  }
}

resource "yandex_function" "video_downloader" {
  name               = "${var.prefix}-video-downloader"
  description        = "Download video to Storage"
  user_hash          = data.archive_file.video_downloader.output_base64sha256
  runtime            = "python39"
  entrypoint         = "main.handler"
  memory             = 1024  
  execution_timeout  = 600 
  service_account_id = yandex_iam_service_account.generator_sa.id
  
  environment = {
    QUEUE_URL              = yandex_message_queue.audio_extractor_queue.id
    AWS_ACCESS_KEY_ID      = yandex_iam_service_account_static_access_key.sa_static_key.access_key
    AWS_SECRET_ACCESS_KEY  = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
    STORAGE_BUCKET            = yandex_storage_bucket.generator_bucket.bucket
    YDB_ENDPOINT = yandex_ydb_database_serverless.tasks_database.ydb_api_endpoint
    YDB_DATABASE = yandex_ydb_database_serverless.tasks_database.database_path
    PYTHONUNBUFFERED       = "1"
  }
  
  content {
    zip_filename = data.archive_file.video_downloader.output_path
  }
}

resource "yandex_function" "audio_extractor" {
  name               = "${var.prefix}-audio-extractor"
  description        = "Extracting audio form video using ffmpeg"
  user_hash          = data.archive_file.audio_extractor.output_base64sha256
  runtime            = "python39"
  entrypoint         = "main.handler"
  memory             = 2048    # 2GB для ffmpeg
  execution_timeout  = 600     # 10 минут
  service_account_id = yandex_iam_service_account.generator_sa.id

  environment = {
    QUEUE_URL             = yandex_message_queue.speech_recognizer_queue.id
    STORAGE_BUCKET        = yandex_storage_bucket.generator_bucket.bucket
    AWS_ACCESS_KEY_ID     = yandex_iam_service_account_static_access_key.sa_static_key.access_key
    AWS_SECRET_ACCESS_KEY = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
    YDB_ENDPOINT          = yandex_ydb_database_serverless.tasks_database.ydb_api_endpoint
    YDB_DATABASE          = yandex_ydb_database_serverless.tasks_database.database_path
    PYTHONUNBUFFERED      = "1"
  }

  package {
    bucket_name = yandex_storage_object.audio_extractor_zip.bucket
    object_name = yandex_storage_object.audio_extractor_zip.key
  }

  depends_on = [yandex_storage_object.audio_extractor_zip]
}

resource "yandex_function" "speech_recognizer" {
  name               = "${var.prefix}-speech-recognizer"
  description        = "Recognize speech"
  user_hash          = data.archive_file.speech_recognizer.output_base64sha256
  runtime            = "python39"
  entrypoint         = "main.handler"
  memory             = 2048    # 2GB для ffmpeg
  execution_timeout  = 600     # 10 минут
  service_account_id = yandex_iam_service_account.generator_sa.id
  
  environment = {
    QUEUE_URL             = yandex_message_queue.speech_recognizer_checker_queue.id
    AWS_ACCESS_KEY_ID     = yandex_iam_service_account_static_access_key.sa_static_key.access_key
    AWS_SECRET_ACCESS_KEY = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
    YDB_ENDPOINT          = yandex_ydb_database_serverless.tasks_database.ydb_api_endpoint
    YDB_DATABASE          = yandex_ydb_database_serverless.tasks_database.database_path
    FOLDER_ID             = var.folder_id
    API_KEY               = yandex_iam_service_account_api_key.sa_api_key.secret_key
    PYTHONUNBUFFERED      = "1"
  }
  
  content {
    zip_filename = data.archive_file.speech_recognizer.output_path
  }
}

resource "yandex_function" "speech_recognizer_checker" {
  name               = "${var.prefix}-speech-recognizer-checker"
  description        = "Check recognize speech status"
  user_hash          = data.archive_file.speech_recognizer_checker.output_base64sha256
  runtime            = "python39"
  entrypoint         = "main.handler"
  memory             = 2048    # 2GB для ffmpeg
  execution_timeout  = 600     # 10 минут
  service_account_id = yandex_iam_service_account.generator_sa.id
  
  environment = {
    SELF_QUEUE_URL         = yandex_message_queue.speech_recognizer_checker_queue.id
    QUEUE_URL             = yandex_message_queue.note_generator_queue.id
    AWS_ACCESS_KEY_ID     = yandex_iam_service_account_static_access_key.sa_static_key.access_key
    AWS_SECRET_ACCESS_KEY = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
    STORAGE_BUCKET        = yandex_storage_bucket.generator_bucket.bucket
    YDB_ENDPOINT          = yandex_ydb_database_serverless.tasks_database.ydb_api_endpoint
    YDB_DATABASE          = yandex_ydb_database_serverless.tasks_database.database_path
    FOLDER_ID             = var.folder_id
    API_KEY               = yandex_iam_service_account_api_key.sa_api_key.secret_key
    PYTHONUNBUFFERED      = "1"
  }
  
  content {
    zip_filename = data.archive_file.speech_recognizer_checker.output_path
  }
}

resource "yandex_function" "note_generator" {
  name               = "${var.prefix}-note-generator"
  description        = "Generate note using GPT"
  user_hash          = data.archive_file.note_generator.output_base64sha256
  runtime            = "python39"
  entrypoint         = "main.handler"
  memory             = 2048    # 2GB для ffmpeg
  execution_timeout  = 600     # 10 минут
  service_account_id = yandex_iam_service_account.generator_sa.id
  
  environment = {
    QUEUE_URL             = yandex_message_queue.speech_recognizer_checker_queue.id
    AWS_ACCESS_KEY_ID     = yandex_iam_service_account_static_access_key.sa_static_key.access_key
    AWS_SECRET_ACCESS_KEY = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
    STORAGE_BUCKET        = yandex_storage_bucket.generator_bucket.bucket
    YDB_ENDPOINT          = yandex_ydb_database_serverless.tasks_database.ydb_api_endpoint
    YDB_DATABASE          = yandex_ydb_database_serverless.tasks_database.database_path
    FOLDER_ID             = var.folder_id
    API_KEY               = yandex_iam_service_account_api_key.sa_api_key.secret_key
    PYTHONUNBUFFERED      = "1"
  }
  
  content {
    zip_filename = data.archive_file.note_generator.output_path
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
  name = "${var.prefix}-summary-generator-api-gateway"
  
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
      responses:
        '302':
          description: Redirect to tasks page
          headers:
            Location:
              description: Redirect URL
              schema:
                type: string
          content: {}  
EOT
}

# 14. Вывод API Gateway URL
output "api_gateway_url" {
  value = "https://${yandex_api_gateway.summary_generator_api.domain}"
  description = "URL API Gateway"
}

resource "yandex_ydb_database_serverless" "tasks_database" {
  name      = "${var.prefix}-tasks-db"
  folder_id = var.folder_id

  serverless_database {
    storage_size_limit = 1
  }
}

resource "yandex_ydb_table" "tasks" {
  path = "tasks"
  connection_string = yandex_ydb_database_serverless.tasks_database.ydb_full_endpoint
  
  column {
    name = "taskId"
    type = "Utf8"
    not_null = true
  }
  column {
    name = "lectureTitle"
    type = "Utf8"
    not_null = true
  }
  column {
    name = "videoUrl"
    type = "Utf8"
    not_null = true
  }
  column {
    name = "status"
    type = "Utf8"
    not_null = true
  }
  column {
    name = "createdAt"
    type = "Timestamp"
    not_null = true
  }
  column {
    name = "pdfUrl"
    type = "Utf8"
  }
  column {
    name = "errorMessage"
    type = "Utf8"
  }
  
  primary_key = ["taskId"]
}
