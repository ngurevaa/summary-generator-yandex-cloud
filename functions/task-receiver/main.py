import json
import os
import uuid
import boto3
import requests
from botocore.config import Config
from datetime import datetime

def handler(event, context):
    """
    Принимает задачу от пользователя и кладет в очередь YMQ
    """
    print(f"=== Handler called ===")
    
    try:
        # 1. Парсим тело запроса
        body = event.get('body', '{}')
        if isinstance(body, str):
            body = json.loads(body) if body else {}
        
        print(f"Parsed body: {json.dumps(body, indent=2)}")
        
        # 2. Валидация
        validate_request(body)
        
        # 3. Проверка доступности файла на Яндекс.Диске через API (FR05)
        video_url = body['videoUrl'].strip()
        file_info = validate_yandex_disk_url(video_url)
        
        # 4. Создаем объект задачи с дополнительной информацией о файле
        task = create_task(body, file_info)
        print(f"Created task: {task['taskId']}")
        
        # 5. Отправляем в очередь (FR02)
        message_id = send_to_queue(task, os.environ)
        print(f"Message sent to queue: {message_id}")
        
        # 6. Возвращаем успешный ответ
        return create_success_response(task, message_id)
        
    except ValidationError as e:
        print(f"Validation error: {str(e)}")
        return create_error_response(400, str(e))
    except YandexDiskError as e:
        print(f"Yandex Disk error: {str(e)}")
        return create_error_response(400, str(e))
    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        import traceback
        traceback.print_exc()
        return create_error_response(500, f"Internal server error: {str(e)}")

# === Вспомогательные функции ===

def validate_request(body):
    """Валидация входящих данных (FR01)"""
    required_fields = ['lectureTitle', 'videoUrl']
    for field in required_fields:
        if not body.get(field):
            raise ValidationError(f"Поле '{field}' обязательно для заполнения")
    
    if not body['lectureTitle'].strip():
        raise ValidationError("Название лекции не может быть пустым")
    
    if not body['videoUrl'].strip():
        raise ValidationError("Ссылка на видео не может быть пустой")

def validate_yandex_disk_url(url):
    """
    Проверяет валидность публичной ссылки на Яндекс.Диске через API (FR05)
    Просто передаем всю ссылку как public_key!
    """
    print(f"=== Validating Yandex Disk URL ===")
    print(f"URL: {url}")
    
    # Используем ВЕСЬ URL как public_key
    return check_yandex_disk_api(url)

def check_yandex_disk_api(url):
    """
    Вызывает API Яндекс.Диска для проверки файла (FR05)
    Просто передаем всю ссылку как public_key!
    """
    api_url = "https://cloud-api.yandex.net/v1/disk/public/resources"
    
    params = {
        'public_key': url,  # ВСЯ ССЫЛКА!
        'fields': 'name,size,mime_type,type,file,media_type'
    }
    
    print(f"=== API Request ===")
    print(f"API URL: {api_url}")
    print(f"Public key (full URL): {url}")
    
    try:
        response = requests.get(api_url, params=params, timeout=15)
        print(f"API Response Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"API Response Success!")
            print(f"File name: {data.get('name', 'N/A')}")
            print(f"File size: {data.get('size', 0)} bytes")
            print(f"MIME type: {data.get('mime_type', 'N/A')}")
            
            return analyze_api_response(data, url)
            
        elif response.status_code == 404:
            error_msg = (
                "❌ Файл не найден по указанной ссылке.\n\n"
                "Что проверить:\n"
                "1. Правильность ссылки\n"
                "2. Что файл существует\n"
                "3. Что файл доступен по публичной ссылке (опубликован)\n\n"
                f"Ссылка: {url}"
            )
            raise YandexDiskError(error_msg)
            
        elif response.status_code == 403:
            error_msg = (
                "❌ Доступ к файлу запрещен.\n\n"
                "Убедитесь, что:\n"
                "1. Файл опубликован (доступен по публичной ссылке)\n"
                "2. Ссылка не требует пароля или дополнительного подтверждения\n\n"
                f"Ссылка: {url}"
            )
            raise YandexDiskError(error_msg)
            
        else:
            error_msg = f"Ошибка Яндекс.Диска (код {response.status_code})"
            try:
                error_data = response.json()
                if 'message' in error_data:
                    error_msg += f": {error_data['message']}"
                elif 'description' in error_data:
                    error_msg += f": {error_data['description']}"
            except:
                pass
            raise YandexDiskError(error_msg)
            
    except requests.exceptions.Timeout:
        error_msg = (
            "❌ Таймаут при проверке файла.\n\n"
            "Яндекс.Диск не ответил вовремя. Попробуйте:\n"
            "1. Проверить интернет-соединение\n"
            "2. Попробовать позже\n"
            "3. Использовать другую ссылку"
        )
        raise YandexDiskError(error_msg)
        
    except requests.exceptions.RequestException as e:
        error_msg = f"❌ Ошибка сети при проверке файла: {str(e)}"
        raise YandexDiskError(error_msg)

def analyze_api_response(data, url):
    """
    Анализирует ответ API Яндекс.Диска и проверяет что файл подходит
    """
    print(f"=== Analyzing API Response ===")
    
    # Проверяем тип ресурса
    resource_type = data.get('type', '')
    print(f"Resource type: {resource_type}")
    
    if resource_type == 'dir':
        raise YandexDiskError(
            "❌ Ссылка ведет на папку, а не на файл.\n\n"
            "Пожалуйста, укажите ссылку на конкретный видеофайл.\n\n"
            f"Ссылка: {url}"
        )
    
    elif resource_type != 'file':
        raise YandexDiskError(
            f"❌ Неизвестный тип ресурса: {resource_type}. Ожидается видеофайл.\n\n"
            f"Ссылка: {url}"
        )
    
    # Проверяем что файл доступен для скачивания
    if not data.get('file'):
        raise YandexDiskError(
            "❌ Файл существует, но не доступен для скачивания.\n"
            "Возможно, владелец ограничил доступ.\n\n"
            f"Ссылка: {url}"
        )
    
    # Проверяем размер файла
    file_size = data.get('size', 0)
    if file_size <= 0:
        raise YandexDiskError(f"❌ Не удалось определить размер файла.\n\nСсылка: {url}")
    
    # Ограничение размера (опционально)
    MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB
    if file_size > MAX_FILE_SIZE:
        size_mb = file_size // (1024 * 1024)
        max_mb = MAX_FILE_SIZE // (1024 * 1024)
        raise YandexDiskError(
            f"❌ Файл слишком большой ({size_mb} MB).\n"
            f"Максимальный поддерживаемый размер: {max_mb} MB.\n\n"
            f"Ссылка: {url}"
        )
    
    # Проверяем MIME-тип (предупреждение, но не блокируем)
    mime_type = data.get('mime_type', '')
    media_type = data.get('media_type', '')
    
    video_mime_prefixes = ['video/', 'application/x-mpegURL', 'application/vnd.apple.mpegurl']
    video_media_types = ['video', 'audio']
    
    is_video = any(mime_type.startswith(prefix) for prefix in video_mime_prefixes)
    is_media = media_type in video_media_types
    
    if not is_video and not is_media:
        print(f"⚠️ Warning: File may not be video. MIME type: '{mime_type}', media type: '{media_type}'")
    
    # Возвращаем информацию о файле
    return {
        'name': data.get('name', ''),
        'size': file_size,
        'mime_type': mime_type,
        'media_type': media_type,
        'download_url': data.get('file', ''),
        'original_url': url
    }

def create_task(body, file_info):
    """Создает объект задачи с информацией о файле"""
    task_id = str(uuid.uuid4())
    
    task = {
        'taskId': task_id,
        'lectureTitle': body['lectureTitle'].strip(),
        'originalUrl': body['videoUrl'].strip(),
        'createdAt': datetime.utcnow().isoformat() + 'Z',
        'status': 'queued',
        'source': 'web-form'
    }
    
    # Добавляем информацию из API Яндекс.Диска
    if file_info:
        task.update({
            'fileName': file_info.get('name', ''),
            'fileSize': file_info.get('size', 0),
            'mimeType': file_info.get('mime_type', ''),
            'downloadUrl': file_info.get('download_url', ''),
            'originalUrl': file_info.get('original_url', body['videoUrl'].strip())
        })
    
    return task

def send_to_queue(task, env_vars):
    """Отправляет задачу в Yandex Message Queue (YMQ) (FR02)"""
    access_key = env_vars.get('AWS_ACCESS_KEY_ID')
    secret_key = env_vars.get('AWS_SECRET_ACCESS_KEY')
    queue_url = env_vars.get('QUEUE_URL')
    
    if not all([access_key, secret_key, queue_url]):
        raise Exception("Missing queue configuration")
    
    sqs = boto3.client(
        'sqs',
        endpoint_url='https://message-queue.api.cloud.yandex.net',
        region_name='ru-central1',
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            signature_version='s3v4',
            s3={'addressing_style': 'virtual'}
        )
    )
    
    is_fifo = queue_url.endswith('.fifo')
    
    send_params = {
        'QueueUrl': queue_url,
        'MessageBody': json.dumps(task, ensure_ascii=False),
    }
    
    if is_fifo:
        send_params.update({
            'MessageGroupId': 'summary-generator-tasks',
            'MessageDeduplicationId': task['taskId']
        })
    
    response = sqs.send_message(**send_params)
    return response.get('MessageId', 'unknown')

def create_success_response(task, message_id):
    """Создает успешный HTTP ответ"""
    return {
        'statusCode': 200,
        'body': json.dumps({
            'success': True,
            'message': '✅ Задача успешно создана и поставлена в очередь',
            'task': {
                'id': task['taskId'],
                'lectureTitle': task['lectureTitle'],
                'status': task['status'],
                'createdAt': task['createdAt'],
                'queueMessageId': message_id
            }
        }, ensure_ascii=False),
        'headers': {
            'Content-Type': 'application/json; charset=utf-8',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type'
        }
    }

def create_error_response(status_code, message):
    """Создает HTTP ответ с ошибкой"""
    return {
        'statusCode': status_code,
        'body': json.dumps({
            'success': False,
            'error': message
        }, ensure_ascii=False),
        'headers': {
            'Content-Type': 'application/json; charset=utf-8',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type'
        }
    }

# === Кастомные исключения ===
class ValidationError(Exception):
    """Исключение для ошибок валидации"""
    pass

class YandexDiskError(Exception):
    """Исключение для ошибок Яндекс.Диска"""
    pass