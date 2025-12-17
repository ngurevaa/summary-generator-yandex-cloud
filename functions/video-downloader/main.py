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
        message_body = json.loads(message['body'])

        # 2. Обновление статуса задачи
        task_id = message_body['task_id']
        update_task_status(task_id, 'В обработке')

        # 3. Скачивание видео
        download_url = message_body['download_url']
        file_path = download_video(download_url)

        # 4. Загрузка видео в Storage
        storage_url = upload_video(file_path)

    except Exception as e:
        update_task_status(task_id, 'Ошибка')

def update_task_status(task_id, status):
    query = f"""
    UPDATE tasks 
    SET status = '{status}'
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
    bucket_name = os.environ.get('STORAGE_BUCKET')
    access_key = os.environ.get('AWS_ACCESS_KEY_ID')
    secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
    
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
            ExtraArgs={
                'ContentType': 'video/mp4'
            }
        )
    storage_url = f"https://{bucket_name}.storage.yandexcloud.net/{object_key}"
    return storage_url