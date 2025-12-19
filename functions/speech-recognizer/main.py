import os
import json
import boto3
import ydb
from botocore.config import Config
import requests

def handler(event, context):
    try:
        # 1. Парсинг сообщения из очереди
        message = event['messages'][0]['details']['message']
        data = json.loads(message['body'])
        task_id = data['task_id']

        # 2. Генерация подписанной ссылки на аудио
        storage_url = data['storage_url']
        presigned_url = generate_presigned_url(storage_url)

        # 3. Отправка запроса на SpeechKit
        operation_id = send_to_speechkit(presigned_url)

        # 4. Отправка сообщения в очередь для проверки статуса распознавания
        queue_message = {
            'task_id': task_id,
            'operation_id': operation_id,
            'attempt': 1
        } 
        send_to_queue(queue_message)

    except Exception as e:
        update_task_status(task_id, 'Ошибка')   

def generate_presigned_url(url):
    bucket_name = url.split('.')[0].replace('https://', '')
    object_key = url.split(bucket_name + '.storage.yandexcloud.net/')[1]
    
    access_key = os.environ['AWS_ACCESS_KEY_ID']
    secret_key = os.environ['AWS_SECRET_ACCESS_KEY']
    
    s3 = boto3.client('s3',
        endpoint_url='https://storage.yandexcloud.net',
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key
    )
   
    presigned_url = s3.generate_presigned_url(
        'get_object',
        Params={
            'Bucket': bucket_name,
            'Key': object_key,
            'ResponseContentDisposition': 'attachment'
        },
        ExpiresIn=3600
    )
    return presigned_url
    
def send_to_speechkit(url):
    api_key = os.environ['API_KEY']
    folder_id = os.environ['FOLDER_ID']
    
    api_url = "https://stt.api.cloud.yandex.net:443/stt/v3/recognizeFileAsync"
    
    headers = {
        'Authorization': f'Api-Key {api_key}',
        'x-folder-id': folder_id,
        'Content-Type': 'application/json'
    }
    
    request_body = {
        "uri": url, 
        "recognition_model": {
            "model": "general",
            "audio_format": {
                "container_audio": {
                    "container_audio_type": "MP3"
                }
            }
        }
    }

    response = requests.post(api_url, json=request_body, headers=headers)
    result = response.json()
    return result['id'] 

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