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
        lecture_title = body['lectureTitle'].strip()
        video_url = body['videoUrl'].strip()

        # 2. Сохранение метаинформации о задаче
        task_info = {
            'task_id': str(uuid.uuid4()),
            'lecture_title': lecture_title,
            'video_url': video_url,
        }
        save_task_info(task_info)

        # 3. Отправка сообщения в очередь для загрузки видео
        queue_message = {
            'task_id': task_info['task_id'],
            'lecture_title': lecture_title,
            'video_url': video_url,
        } 
        send_to_queue(queue_message)
        
        # 4. Возврат успешного ответа
        return {
            'statusCode': 302,
            'headers': {
                'Location': '/tasks'
            }
        }
    
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': "Произошла неожиданная ошибка.\nПопробуйте позднее."
            }, ensure_ascii=False),
            'headers': {
                'Content-Type': 'application/json; charset=utf-8'
            }
        }
    
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
        session.transaction().execute(query, commit_tx=True)

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