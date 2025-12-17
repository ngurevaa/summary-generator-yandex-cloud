variable "YC_TOKEN" {
  description = "Yandex Cloud OAuth token"
  type        = string
  sensitive   = true
}
variable "cloud_id" {
  description = "Yandex Cloud ID"
  type        = string
  sensitive   = true
}

variable "folder_id" {
  description = "Yandex Cloud Folder ID"
  type        = string
  sensitive   = true
}

variable "zone" {
  description = "Yandex Cloud Zone"
  type        = string
  default     = "ru-central1-d"
}

variable "prefix" {
  description = "Prefix for names"
  type        = string
  default     = "vvot13"
}