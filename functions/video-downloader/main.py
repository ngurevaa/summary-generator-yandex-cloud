import os
import ydb
import tempfile
import uuid
import boto3
import requests
from botocore.config import Config
import json

def handler(event, context):
    try:
        # 1. Парсинг сообщения из очереди
        message = event['messages'][0]['details']['message']
        data = json.loads(message['body'])

        # 2. Обновление статуса задачи
        task_id = data['task_id']
        update_task_status(task_id, 'В обработке')

        # 3. Валидация полей
        download_url = validate_request(data)

        # 4. Скачивание видео
        video_path = download_video(download_url)

        # 5. Загрузка видео в Storage
        storage_url = upload_video(video_path)

        # 6. Отправка сообщения в очередь для извлечения аудио
        queue_message = {
            'task_id': task_id,
            'storage_url': storage_url
        } 
        send_to_queue(queue_message)

        # 7. Удаление временных файлов
        os.remove(video_path)

    except ValidationError as e:
        update_task_status_with_error(task_id, 'Ошибка', str(e))
    except Exception as e:
        update_task_status_with_error(task_id, 'Ошибка', 'Произошла ошибка во время загрузки видео')

def validate_request(body):
    if not body['lecture_title'].strip():
        raise ValidationError("Название лекции не может быть пустым")
    
    video_url = body['video_url']
    if not video_url.strip():
        raise ValidationError("Ссылка на видео не может быть пустой")
    
    return validate_yandex_disk_url(video_url)

def validate_yandex_disk_url(url):
    api_url = "https://cloud-api.yandex.net/v1/disk/public/resources"
    
    params = {
        'public_key': url,
        'fields': 'name,mime_type,type,file'
    }
   
    response = requests.get(api_url, params=params, timeout=15)
        
    if response.status_code == 200:
        data = response.json()
        return analyze_api_response(data)
        
    elif response.status_code == 404:
        raise ValidationError("Файл не найден по указанной ссылке.")
        
    elif response.status_code == 403:
        raise ValidationError("Доступ к файлу запрещен.\nУбедитесь, что файл доступен по публичной ссылке.")

def analyze_api_response(data):
    resource_type = data.get('type', '')
    
    if resource_type == 'dir':
        raise ValidationError("Ссылка ведет на папку, а не на файл.\nПожалуйста, укажите ссылку на конкретный видеофайл.")
    
    elif resource_type != 'file':
        raise ValidationError("Неизвестный тип ресурса. Ожидается видеофайл.")
    
    mime_type = data.get('mime_type', '')
    video_mime_prefixes = ['video/', 'application/x-mpegURL', 'application/vnd.apple.mpegurl']
    
    if not any(mime_type.startswith(prefix) for prefix in video_mime_prefixes):
        raise ValidationError("Неизвестный тип ресурса. Ожидается видеофайл.")
    
    return data.get('file', '')

def update_task_status(task_id, status):
    query = f"""
    UPDATE tasks 
    SET status = '{status}'
    WHERE taskId = '{task_id}';
    """
    execute_query(query)

def update_task_status_with_error(task_id, status, error):
    query = f"""
    UPDATE tasks 
    SET status = '{status}', errorMessage = '{error}'
    WHERE taskId = '{task_id}';
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
        session.transaction().execute(query, commit_tx=True)

def download_video(url):
    temp_dir = tempfile.mkdtemp()
    file_name = "video.mp4"
    file_path = os.path.join(temp_dir, file_name)
    
    response = requests.get(url, stream=True, timeout=60)
    response.raise_for_status()
    
    with open(file_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)
    
    return file_path

def upload_video(file_path):
    bucket_name = os.environ['STORAGE_BUCKET']
    access_key = os.environ['AWS_ACCESS_KEY_ID']
    secret_key = os.environ['AWS_SECRET_ACCESS_KEY']
    
    s3_client = boto3.client(
        's3',
        endpoint_url='https://storage.yandexcloud.net',
        region_name='ru-central1',
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key
    )
    file_name = uuid.uuid4()
    object_key = f"videos/{file_name}"
    
    with open(file_path, 'rb') as f:
        s3_client.upload_fileobj(
            f,
            bucket_name,
            object_key,
            ExtraArgs={'ContentType': 'video/mp4'}
        )
    storage_url = f"https://{bucket_name}.storage.yandexcloud.net/{object_key}"
    return storage_url

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
    sqs.send_message(**send_params)    

class ValidationError(Exception):
    """Ошибка валидации входных данных"""
    pass    