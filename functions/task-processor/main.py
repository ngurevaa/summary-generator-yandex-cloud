import json
import os
import boto3
import requests
import logging
import uuid
from botocore.config import Config
from io import BytesIO
from datetime import datetime

# Настройка логирования
logger = logging.getLogger()
logger.setLevel(logging.INFO)

def handler(event, context):
    """
    ГЛАВНАЯ функция-обработчик для Yandex Cloud Functions
    Вызывается автоматически при поступлении сообщения в очередь
    """
    logger.info("=== Task Processor Handler Started ===")
    logger.info(f"Event structure: {json.dumps(event, indent=2)[:500]}...")
    
    try:
        # 1. Извлекаем задачу из сообщения очереди
        task = extract_task_from_event(event)
        task_id = task.get('taskId', 'unknown')
        logger.info(f"Processing task: {task_id}")
        
        # 2. Скачиваем видео в Object Storage
        video_s3_path = download_video_to_s3(task)
        logger.info(f"Video downloaded to: {video_s3_path}")
        
        # 3. Здесь будет дальнейшая обработка:
        # - Извлечение аудио
        # - Распознавание речи через SpeechKit
        # - Генерация конспекта через YandexGPT
        # - Создание PDF
        # - Сохранение PDF в Object Storage
        
        # 4. Пока возвращаем успешный ответ
        return {
            'statusCode': 200,
            'body': json.dumps({
                'success': True,
                'message': f'Task {task_id} processing started',
                'video_path': video_s3_path,
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            }, ensure_ascii=False),
            'headers': {
                'Content-Type': 'application/json'
            }
        }
        
    except Exception as e:
        logger.error(f"Handler error: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'success': False,
                'error': f'Processing failed: {str(e)}'
            }, ensure_ascii=False)
        }

def extract_task_from_event(event):
    """
    Извлекает данные задачи из события триггера очереди
    """
    logger.info("Extracting task from event")
    
    # Формат сообщения от YMQ через Cloud Functions триггер
    if 'messages' in event and len(event['messages']) > 0:
        message = event['messages'][0]
        
        # Проверяем разные возможные форматы
        if 'details' in message and 'message' in message['details']:
            message_body = message['details']['message']['body']
        else:
            # Альтернативный формат
            message_body = message.get('body', message.get('message_body', '{}'))
        
        # Парсим JSON
        task = json.loads(message_body) if isinstance(message_body, str) else message_body
        
        logger.info(f"Task extracted: {task.get('taskId', 'unknown')}")
        return task
    
    raise ValueError("Invalid event format: no messages found")

def download_video_to_s3(task):
    """
    Скачивает видео с Яндекс.Диска в Object Storage
    """
    logger.info(f"Downloading video for task: {task.get('taskId', 'unknown')}")
    
    # 1. Проверяем обязательные поля
    if 'downloadUrl' not in task:
        raise ValueError("Task missing 'downloadUrl' field")
    
    download_url = task['downloadUrl']
    task_id = task.get('taskId', str(uuid.uuid4()))
    
    # 2. Получаем конфигурацию из переменных окружения
    aws_access_key = os.environ.get('AWS_ACCESS_KEY_ID')
    aws_secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
    bucket_name = os.environ.get('BUCKET_NAME')
    
    if not all([aws_access_key, aws_secret_key, bucket_name]):
        missing = []
        if not aws_access_key: missing.append('AWS_ACCESS_KEY_ID')
        if not aws_secret_key: missing.append('AWS_SECRET_ACCESS_KEY')
        if not bucket_name: missing.append('BUCKET_NAME')
        raise ValueError(f"Missing environment variables: {missing}")
    
    # 3. Настраиваем S3 клиент для Yandex Object Storage
    s3 = boto3.client(
        's3',
        endpoint_url='https://storage.yandexcloud.net',
        region_name='ru-central1',
        aws_access_key_id=aws_access_key,
        aws_secret_access_key=aws_secret_key,
        config=Config(signature_version='s3v4')
    )
    
    # 4. Генерируем уникальный ключ в S3
    s3_key = f"temp_videos/{task_id}/original_video.mp4"
    logger.info(f"Target S3 path: s3://{bucket_name}/{s3_key}")
    
    try:
        # 5. Начинаем потоковое скачивание
        logger.info(f"Starting download from: {download_url}")
        response = requests.get(download_url, stream=True, timeout=60)
        response.raise_for_status()
        
        # 6. Проверяем размер файла
        file_size = int(response.headers.get('content-length', 0))
        logger.info(f"File size: {file_size / 1024 / 1024:.2f} MB")
        
        # 7. Ограничение размера (можно настроить через переменные окружения)
        max_size_mb = int(os.environ.get('MAX_VIDEO_SIZE_MB', '500'))
        if file_size > max_size_mb * 1024 * 1024:
            raise ValueError(f"Video too large. Max: {max_size_mb} MB, got: {file_size / 1024 / 1024:.1f} MB")
        
        # 8. Загружаем в S3 (выбираем метод в зависимости от размера)
        if file_size > 100 * 1024 * 1024:  # > 100 MB
            logger.info("Using multipart upload for large file")
            result_path = upload_large_file(s3, bucket_name, s3_key, response, file_size)
        else:
            logger.info("Using simple upload")
            result_path = upload_simple(s3, bucket_name, s3_key, response, file_size)
        
        logger.info(f"Video successfully uploaded to: {result_path}")
        return result_path
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Download error: {str(e)}")
        raise Exception(f"Failed to download video: {str(e)}")
    except Exception as e:
        logger.error(f"S3 upload error: {str(e)}")
        raise

def upload_simple(s3_client, bucket, key, response, total_size):
    """
    Простая загрузка для файлов < 100 MB
    """
    # Собираем данные в памяти (для небольших файлов это нормально)
    data = BytesIO()
    downloaded = 0
    
    for chunk in response.iter_content(chunk_size=8192):
        if chunk:
            data.write(chunk)
            downloaded += len(chunk)
            
            # Логируем прогресс каждые 5 MB
            if downloaded % (5 * 1024 * 1024) < 8192:
                progress = (downloaded / total_size * 100) if total_size > 0 else 0
                logger.info(f"Download progress: {progress:.1f}% ({downloaded / 1024 / 1024:.1f} MB)")
    
    # Загружаем в S3
    data.seek(0)
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=data,
        ContentType='video/mp4',
        Metadata={
            'task_id': key.split('/')[1],
            'uploaded_at': datetime.utcnow().isoformat()
        }
    )
    
    return f"s3://{bucket}/{key}"

def upload_large_file(s3_client, bucket, key, response, total_size):
    """
    Multipart upload для больших файлов (>100 MB)
    """
    # 1. Инициируем multipart upload
    mpu = s3_client.create_multipart_upload(
        Bucket=bucket,
        Key=key,
        ContentType='video/mp4',
        Metadata={
            'task_id': key.split('/')[1],
            'upload_method': 'multipart'
        }
    )
    upload_id = mpu['UploadId']
    logger.info(f"Multipart upload started. Upload ID: {upload_id}")
    
    try:
        parts = []
        part_number = 1
        
        # 2. Загружаем части
        for chunk in response.iter_content(chunk_size=10 * 1024 * 1024):  # 10 MB chunks
            if not chunk:
                continue
                
            logger.info(f"Uploading part {part_number} ({len(chunk) / 1024 / 1024:.1f} MB)")
            
            part = s3_client.upload_part(
                Bucket=bucket,
                Key=key,
                PartNumber=part_number,
                UploadId=upload_id,
                Body=chunk
            )
            
            parts.append({
                'PartNumber': part_number,
                'ETag': part['ETag']
            })
            part_number += 1
        
        # 3. Завершаем upload
        s3_client.complete_multipart_upload(
            Bucket=bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={'Parts': parts}
        )
        
        logger.info(f"Multipart upload completed. Parts: {len(parts)}")
        return f"s3://{bucket}/{key}"
        
    except Exception as e:
        # Отменяем upload при ошибке
        logger.error(f"Multipart upload failed, aborting. Error: {str(e)}")
        try:
            s3_client.abort_multipart_upload(
                Bucket=bucket,
                Key=key,
                UploadId=upload_id
            )
        except:
            pass
        raise