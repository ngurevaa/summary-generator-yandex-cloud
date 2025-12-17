import json
import os
import uuid
import boto3
import requests
from botocore.config import Config
from datetime import datetime
import ydb

def handler(event, context):
    try:
        # 1. Парсинг тела запроса
        body = json.loads(event['body'])
        
        # 2. Валидация полей
        validate_request(body)
        
        # 3. Проверка доступности файла на Яндекс.Диске через API
        video_url = body['videoUrl'].strip()
        download_url = validate_yandex_disk_url(video_url)

        # 4. Сохранение метаинформации о задаче
        task_info = {
            'task_id': str(uuid.uuid4()),
            'lecture_title': body['lectureTitle'].strip(),
            'video_url': body['videoUrl'].strip(),
        }
        save_task_info(task_info)

        # 5. Отправка сообщения в очередь для загрузки видео
        queue_message = {
            'task_id': task_info['task_id'],
            'download_url': download_url
        } 
        send_to_queue(queue_message)
        
        # 6. Возврат успешного ответа
        return {
            'statusCode': 302,
            'headers': {
                'Location': '/tasks'
            }
        }
        
    except ValidationError as e:
        return create_error_response(400, str(e))
    except YandexDiskError as e:
        return create_error_response(400, str(e))
    except Exception as e:
        return create_error_response(500, "Произошла неожиданная ошибка.\nПопробуйте позднее.")

# === Вспомогательные функции ===

def validate_request(body):
    required_fields = ['lectureTitle', 'videoUrl']
    for field in required_fields:
        if not body.get(field):
            raise ValidationError(f"Поле '{field}' обязательно для заполнения")
    
    if not body['lectureTitle'].strip():
        raise ValidationError("Название лекции не может быть пустым")
    
    if not body['videoUrl'].strip():
        raise ValidationError("Ссылка на видео не может быть пустой")

def validate_yandex_disk_url(url):
    api_url = "https://cloud-api.yandex.net/v1/disk/public/resources"
    
    params = {
        'public_key': url,
        'fields': 'name,mime_type,type,file'
    }
   
    try:
        response = requests.get(api_url, params=params, timeout=15)
        
        if response.status_code == 200:
            data = response.json()
            return analyze_api_response(data)
            
        elif response.status_code == 404:
            raise YandexDiskError("Файл не найден по указанной ссылке.")
            
        elif response.status_code == 403:
            raise YandexDiskError("Доступ к файлу запрещен.\nУбедитесь, что файл доступен по публичной ссылке.")
    except Exception as e:
        raise YandexDiskError("Произошла неожиданная ошибка.\nПопробуйте позднее.")

def analyze_api_response(data):
    resource_type = data.get('type', '')
    
    if resource_type == 'dir':
        raise YandexDiskError("Ссылка ведет на папку, а не на файл.\nПожалуйста, укажите ссылку на конкретный видеофайл.")
    
    elif resource_type != 'file':
        raise YandexDiskError("Неизвестный тип ресурса. Ожидается видеофайл.")
    
    mime_type = data.get('mime_type', '')
    video_mime_prefixes = ['video/', 'application/x-mpegURL', 'application/vnd.apple.mpegurl']
    
    if not any(mime_type.startswith(prefix) for prefix in video_mime_prefixes):
        raise YandexDiskError("Неизвестный тип ресурса. Ожидается видеофайл.")
    
    return data.get('file', '')
    
def save_task_info(task_info):
    query = f"""
    UPSERT INTO tasks (taskId, lectureTitle, videoUrl, status, createdAt)
    VALUES ("{task_info['task_id']}", "{task_info['lecture_title']}", "{task_info['video_url']}", "В очереди", CurrentUtcTimestamp());
    """
    execute_query(query)

def execute_query(query):
    endpoint = f"grpcs://{os.environ['YDB_ENDPOINT']}"
    database = os.environ['YDB_DATABASE']
    
    driver_config = ydb.DriverConfig(
        endpoint=endpoint,
        database=database,
        credentials=ydb.credentials_from_env_variables(),
        root_certificates=ydb.load_ydb_root_certificate()
    )
    
    with ydb.Driver(driver_config) as driver:
        driver.wait(timeout=30, fail_fast=True)
        session = driver.table_client.session().create()
        result_sets = session.transaction().execute(query, commit_tx=True)

def send_to_queue(task):
    access_key = os.environ['AWS_ACCESS_KEY_ID']
    secret_key = os.environ['AWS_SECRET_ACCESS_KEY']
    queue_url = os.environ['QUEUE_URL']
    
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

    send_params = {
        'QueueUrl': queue_url,
        'MessageBody': json.dumps(task, ensure_ascii=False),
    }
    response = sqs.send_message(**send_params)
    message_id = response.get('MessageId')

def create_error_response(status_code, message):
    return {
        'statusCode': status_code,
        'body': json.dumps({
            'error': message
        }, ensure_ascii=False),
        'headers': {
            'Content-Type': 'application/json; charset=utf-8'
        }
    }

# === Кастомные исключения ===
class ValidationError(Exception):
    """Исключение для ошибок валидации"""
    pass

class YandexDiskError(Exception):
    """Исключение для ошибок Яндекс.Диска"""
    pass