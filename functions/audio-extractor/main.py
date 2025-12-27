import os
import json
import subprocess
import boto3
import tempfile
import uuid
import ydb
from botocore.config import Config

def handler(event, context):
    try:
        # 1. Парсинг сообщения из очереди
        message = event['messages'][0]['details']['message']
        data = json.loads(message['body'])
        task_id = data['task_id']

        # 2. Скачивание видео
        storage_url = data['storage_url']
        video_path = download_video(storage_url)

        # 3. Извлечение аудио
        audio_path = extract_audio(video_path)

        # 4. Загрузка аудио в Storage
        audio_url = upload_audio(audio_path)

        # 5. Отправка сообщения в очередь для извлечения текста
        queue_message = {
            'task_id': task_id,
            'storage_url': audio_url
        } 
        send_to_queue(queue_message)

        # 6. Удаление временных файлов
        os.remove(video_path)
        os.remove(audio_path)

    except Exception as e:
        update_task_status(task_id, 'Ошибка', 'Произошла ошибка во время извлечения аудио из видео')   

def download_video(url):
    bucket_name = url.split('.')[0].replace('https://', '')
    object_key = url.split(bucket_name + '.storage.yandexcloud.net/')[1]

    access_key = os.environ['AWS_ACCESS_KEY_ID']
    secret_key = os.environ['AWS_SECRET_ACCESS_KEY']
    
    s3 = boto3.client('s3',
        endpoint_url='https://storage.yandexcloud.net',
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key
    )
    
    with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as video_file:
        video_path = video_file.name
        s3.download_file(bucket_name, object_key, video_path)
    return video_path    

def extract_audio(path):
    audio_path = path.replace('.mp4', '.mp3')
    
    ffmpeg_cmd = [
        'ffmpeg',
        '-i', path,
        '-vn',
        '-acodec', 'libmp3lame',
        '-ab', '192k',
        '-ar', '44100',
        '-y', audio_path
    ]
    subprocess.run(ffmpeg_cmd, capture_output=True, text=True)
    return audio_path

def upload_audio(path):
    access_key = os.environ['AWS_ACCESS_KEY_ID']
    secret_key = os.environ['AWS_SECRET_ACCESS_KEY']
    bucket_name = os.environ['STORAGE_BUCKET']
    
    s3 = boto3.client('s3',
        endpoint_url='https://storage.yandexcloud.net',
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key
    )

    file_name = uuid.uuid4()
    object_key = f"audios/{file_name}"

    s3.upload_file(
        path, 
        bucket_name, 
        object_key,
        ExtraArgs={'ContentType': 'audio/mpeg'}
        )
    
    return f"https://{bucket_name}.storage.yandexcloud.net/{object_key}"

def update_task_status(task_id, status, error):
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

def send_to_queue(message):
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
        'MessageBody': json.dumps(message, ensure_ascii=False),
    }
    sqs.send_message(**send_params)