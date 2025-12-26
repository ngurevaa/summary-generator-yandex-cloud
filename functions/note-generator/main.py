import os
import json
import boto3
import uuid
import ydb
import requests
from markdown_pdf import MarkdownPdf, Section
import io

def handler(event, context):
    try:
        # 1. Парсинг сообщения из очереди
        message = event['messages'][0]['details']['message']
        data = json.loads(message['body'])
        task_id = data['task_id']
        
        # 2. Загрузка текста из Storage
        storage_url = data['storage_url']
        text_content = download_text_from_storage(storage_url)
        
        # 3. Генерация конспекта через YandexGPT
        lecture_title = get_lecture_title(task_id)
        note_md_content = generate_note_with_yagpt(text_content, lecture_title)
        
        # 4. Конвертация конспекта в PDF
        pdf_path = convert_markdown_to_pdf(note_md_content)
        
        # 5. Загрузка PDF в Storage
        storage_url = upload_pdf_to_storage(pdf_path)
        
        # 6. Обновление статуса задачи в YDB
        update_task_with_result(task_id, storage_url)
        
        # 7. Удаление временных файлов
        os.remove(pdf_path)
        
    except Exception as e:
        update_task_status(task_id, 'Ошибка')

def download_text_from_storage(storage_url):
    bucket_name = storage_url.split('//')[1].split('.')[0]
    object_key = storage_url.split(bucket_name + '.storage.yandexcloud.net/')[1]
    
    access_key = os.environ['AWS_ACCESS_KEY_ID']
    secret_key = os.environ['AWS_SECRET_ACCESS_KEY']
    
    s3 = boto3.client('s3',
        endpoint_url='https://storage.yandexcloud.net',
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key
    )
    
    response = s3.get_object(Bucket=bucket_name, Key=object_key)
    content = response['Body'].read().decode('utf-8')
    
    return content

def generate_note_with_yagpt(text_content, lecture_title):
    prompt = f"""
    Создай конспект лекции "{lecture_title}" на основе текста ниже.
    
    Текст лекции:
    {text_content}

    Формат Markdown:
    # {lecture_title}
    - Основные идеи
    - Ключевые термины  
    - Выводы

    Будь кратким."""

    folder_id = os.environ['FOLDER_ID']
    api_key = os.environ['API_KEY'] 
    
    headers = {
        'Authorization': f'Api-Key {api_key}',
        'x-folder-id': folder_id,
        'Content-Type': 'application/json'
    }
    
    payload = {
        "modelUri": f"gpt://{folder_id}/yandexgpt-lite",
        "completionOptions": {
            "stream": False,
            "temperature": 0.3,
            "maxTokens": 4000
        },
        "messages": [
            {
                "role": "system",
                "text": "Ты - профессиональный преподаватель, который создает качественные учебные материалы и конспекты."
            },
            {
                "role": "user",
                "text": prompt
            }
        ]
    }
    
    response = requests.post(
        "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
        headers=headers,
        json=payload,
        timeout=60
    )
    
    if response.status_code != 200:
        raise Exception(f"YandexGPT error: {response.status_code} - {response.text}")
    
    result = response.json()
    note = result['result']['alternatives'][0]['message']['text']
    
    return note

def convert_markdown_to_pdf(markdown_content):    
    pdf = MarkdownPdf()
    
    pdf.add_section(Section(markdown_content))
    
    out = io.BytesIO()
    pdf.save_bytes(out)
    return out.getvalue() 
        

def upload_pdf_to_storage(pdf_bytes):
    access_key = os.environ['AWS_ACCESS_KEY_ID']
    secret_key = os.environ['AWS_SECRET_ACCESS_KEY']
    bucket_name = os.environ['STORAGE_BUCKET']
    
    s3 = boto3.client('s3',
        endpoint_url='https://storage.yandexcloud.net',
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key
    )
    
    file_name = f"{uuid.uuid4()}.pdf"
    object_key = f"notes/{file_name}"
    
    s3.put_object(
        Bucket=bucket_name,
        Key=object_key,
        Body=pdf_bytes,
        ContentType='application/pdf',
        ContentDisposition=f'inline; filename="{file_name}"'
    )
    
    return f"https://{bucket_name}.storage.yandexcloud.net/{object_key}"

def update_task_with_result(task_id, pdf_url):
    query = f"""
    UPDATE tasks 
    SET 
        status = 'Успешно завершено',
        pdfUrl = '{pdf_url}'
    WHERE taskId = '{task_id}';
    """
    execute_query(query)

def update_task_status(task_id, status):
    query = f"""
    UPDATE tasks 
    SET status = '{status}'
    WHERE taskId = '{task_id}';
    """
    execute_query(query)

def get_lecture_title(task_id):
    query = f"""
    SELECT lectureTitle 
    FROM tasks 
    WHERE taskId = '{task_id}';
    """
    result = execute_query(query)
    row = result[0].rows[0]
    return row.lectureTitle

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
        result = session.transaction().execute(query, commit_tx=True)
        return result