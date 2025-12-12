variable "cloud_id" {
  type        = string
  description = "Yandex Cloud ID"
  sensitive   = true
}

variable "folder_id" {
  type        = string
  description = "Yandex Folder ID"
  sensitive   = true
}

variable "yandex_oauth_token" {
  type        = string
  description = "Yandex OAuth Token"
  sensitive   = true
}