import os
import json
import boto3
import uuid
import ydb
from botocore.config import Config
import requests
import tempfile

def handler(event, context):
    try:
        # 1. Парсинг сообщения из очереди
        message = event['messages'][0]['details']['message']
        data = json.loads(message['body'])
        task_id = data['task_id']
        
        # 2. Получение статуса операции
        operation_id = data['operation_id']
        status = check_speech_recognize_status(operation_id)

        # 3.1. Распознавание завершено успешно
        if (status == "done"):
            # 4. Получение распознанного текста
            recognized_text_path = get_speechkit_result(operation_id)

            # 5. Сохранение текста в Storage
            storage_url = upload_recognized_text(recognized_text_path)

            # 6. Отправка сообщения в очередь для формирования конспекта
            queue_message = {
                'task_id': task_id,
                'storage_url': storage_url
            }
            # send_to_queue(queue_message)

            # 7. Удаление временных файлов
            os.remove(recognized_text_path)

        # 3.2. Распознавание в процессе
        elif (status == "running"):
            # 4. Отправка сообщения в очередь для проверки статуса распознавания
            message = {
                'task_id': task_id,
                'operation_id': operation_id,
                'attempt': data['attempt'] + 1
            }
            resend_to_queue_with_delay(message)

        # 3.3 Распознавание завершено с ошибкой    
        else:
            raise Exception("Recognition complete with error")
    except Exception as e:
        update_task_status(task_id, 'Ошибка')
    

def check_speech_recognize_status(operation_id):
    api_key = os.environ['API_KEY']
    folder_id = os.environ['FOLDER_ID']
    
    headers = {
        'Authorization': f'Api-Key {api_key}',
        'x-folder-id': folder_id
    }
    
    operation_url = f"https://operation.api.cloud.yandex.net/operations/{operation_id}"
    
    response = requests.get(operation_url, headers=headers)
    response.raise_for_status()
    
    result = response.json()
    
    if result.get('done', False):
        if 'error' in result:
            return 'error'
        return 'done'
    else:
        return 'running'    
    
def get_speechkit_result(operation_id):
    api_key = os.environ['API_KEY']
    folder_id = os.environ['FOLDER_ID']
    
    headers = {
        'Authorization': f'Api-Key {api_key}',
        'x-folder-id': folder_id,
        'Content-Type': 'application/json'
    }
    result_url = "https://stt.api.cloud.yandex.net/stt/v3/getRecognition"
    params = {'operationId': operation_id}
    
    response = requests.get(result_url, headers=headers, params=params)
    if response.status_code != 200:
        raise Exception(f"Failed to get recognition result: {response.status_code}")
    
    text = extract_full_text(response.content)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as temp_file:
        temp_file.write(text)
        temp_file_path = temp_file.name
    
    return temp_file_path
    
def extract_full_text(response_content, channel='0'):
    full_text = ""
    lines = response_content.decode('utf-8').strip().split('\n')
    
    results_by_index = {}
    
    for line in lines:
        data = json.loads(line)
        if 'result' not in data:
            continue
            
        result = data['result']
        
        if result.get('channelTag') != channel:
            continue
        
        if 'finalRefinement' in result:
            refinement = result['finalRefinement']
            final_index = str(refinement.get('finalIndex', '0'))
            
            if 'normalizedText' in refinement:
                for alt in refinement['normalizedText']['alternatives']:
                    if 'text' in alt:
                        if final_index not in results_by_index:
                            results_by_index[final_index] = alt['text']
        
        elif 'final' in result:
            final_data = result['final']
            final_index = str(final_data.get('finalIndex', '0'))
            
            for alt in final_data['alternatives']:
                if 'text' in alt:
                    if final_index not in results_by_index:
                        results_by_index[final_index] = alt['text']
    
    sorted_indices = sorted(results_by_index.keys(), key=int)
    full_text = " ".join(results_by_index[idx] for idx in sorted_indices)
    
    return full_text.strip()

def resend_to_queue_with_delay(message):
    queue_url = os.environ['SELF_QUEUE_URL']
    access_key = os.environ['AWS_ACCESS_KEY_ID']
    secret_key = os.environ['AWS_SECRET_ACCESS_KEY']
    
    sqs = boto3.client(
        'sqs',
        endpoint_url='https://message-queue.api.cloud.yandex.net',
        region_name='ru-central1',
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version='s3v4')
    )

    attempt = message['attempt']
    delay_seconds = min(2 ** attempt, 900)
    
    send_params = {
        'QueueUrl': queue_url,
        'MessageBody': json.dumps(message, ensure_ascii=False),
        'DelaySeconds': delay_seconds
    }
    sqs.send_message(**send_params)

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

def upload_recognized_text(path):
    access_key = os.environ['AWS_ACCESS_KEY_ID']
    secret_key = os.environ['AWS_SECRET_ACCESS_KEY']
    bucket_name = os.environ['STORAGE_BUCKET']
    
    s3 = boto3.client('s3',
        endpoint_url='https://storage.yandexcloud.net',
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key
    )

    file_name = uuid.uuid4()
    object_key = f"recognitions/{file_name}"

    s3.upload_file(
        path, 
        bucket_name, 
        object_key,
        ExtraArgs={
            'ContentType': 'text/plain; charset=utf-8',
            'ContentDisposition': 'inline'
        }
    )
    
    return f"https://{bucket_name}.storage.yandexcloud.net/{object_key}"        

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