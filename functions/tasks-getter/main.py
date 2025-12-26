import json
import ydb
import os
from datetime import datetime
import boto3

def handler(event, context):
    # Получаем все задачи из таблицы с сортировкой по дате
    query = """
    SELECT 
        taskId,
        lectureTitle,
        videoUrl,
        status,
        createdAt,
        pdfUrl,
        errorMessage
    FROM tasks
    ORDER BY createdAt DESC
    """
    
    try:
        rows = execute_query(query)[0].rows
        
        tasks = []
        for row in rows:
            created_at = None
            if row.createdAt:
                timestamp_micro = row.createdAt
                timestamp_sec = timestamp_micro / 1000000
                dt = datetime.fromtimestamp(timestamp_sec)
                created_at = dt.isoformat()
            
            tasks.append({
                'taskId': row.taskId,
                'lectureTitle': row.lectureTitle,
                'videoUrl': row.videoUrl,
                'status': row.status,
                'createdAt': created_at,
                'pdfUrl': generate_presigned_url(row.pdfUrl),
                'errorMessage': row.errorMessage
            })
        
        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(tasks, ensure_ascii=False)
        }
        
    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }

def generate_presigned_url(url):
    if not url:
        return None
    
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