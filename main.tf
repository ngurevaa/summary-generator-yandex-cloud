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
resource "yandex_resourcemanager_folder_iam_member" "storage_admin" {
  folder_id = var.folder_id
  role      = "storage.admin"
  member    = "serviceAccount:${yandex_iam_service_account.generator_sa.id}"
}

# 3. Создаем статический ключ
resource "yandex_iam_service_account_static_access_key" "sa_static_key" {
  service_account_id = yandex_iam_service_account.generator_sa.id
  description        = "Static key for bucket"
}

# 4. Создаем бакет ПРОСТОЕ ИМЯ
resource "yandex_storage_bucket" "generator_bucket" {
  bucket     = "generator-bucket"  # Простое имя
  access_key = yandex_iam_service_account_static_access_key.sa_static_key.access_key
  secret_key = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
  
  website {
    index_document = "index.html"
    error_document = "error.html"
  }
  
  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "POST", "PUT", "DELETE"]
    allowed_origins = ["*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3000
  }
  
  anonymous_access_flags {
    read = true    # Публичный доступ на чтение
    list = false   # Не показывать список файлов
  }
}

# 5. Загружаем index.html
resource "yandex_storage_object" "index_html" {
  bucket       = yandex_storage_bucket.generator_bucket.bucket
  key          = "index.html"
  source       = "index.html"
  content_type = "text/html; charset=utf-8"
  
  # Используем новую схему вместо acl
  access_key = yandex_iam_service_account_static_access_key.sa_static_key.access_key
  secret_key = yandex_iam_service_account_static_access_key.sa_static_key.secret_key
}

# 7. Выводим URL
output "website_url" {
  value = "http://${yandex_storage_bucket.generator_bucket.bucket}.website.yandexcloud.net"
}