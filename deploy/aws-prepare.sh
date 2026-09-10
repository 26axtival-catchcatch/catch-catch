#!/bin/bash
set -euo pipefail
export HOME="${HOME:-/root}"
cd "$(dirname "$0")/.."
apt-get install -y -qq python3-boto3
python3 - <<'PY'
import os, sys, urllib.request
import boto3
sys.path.insert(0, 'scripts')
from compose import write_environment, read_env, write_private, LOCAL
os.environ['AGENT_MODE'] = 'fixture'
write_environment()
request = urllib.request.Request('http://169.254.169.254/latest/api/token', method='PUT', headers={'X-aws-ec2-metadata-token-ttl-seconds':'60'})
token = urllib.request.urlopen(request).read().decode()
request = urllib.request.Request('http://169.254.169.254/latest/meta-data/public-ipv4', headers={'X-aws-ec2-metadata-token':token})
ip = urllib.request.urlopen(request).read().decode()
password = boto3.client('ssm', region_name='us-east-1').get_parameter(Name='/catch-catch-hackathon/langfuse-admin-password', WithDecryption=True)['Parameter']['Value']
settings = read_env(LOCAL / 'stack.env')
settings.update({'APP_PORT':'80', 'APP_URL':f'http://{ip}', 'LANGFUSE_URL':f'http://{ip}:3210', 'MINIO_URL':f'http://{ip}:3290', 'LANGFUSE_USER_EMAIL':'4bit@catchcatch.local', 'LANGFUSE_USER_PASSWORD':password})
write_private(LOCAL / 'stack.env', settings)
backend = read_env(LOCAL / 'backend.env')
backend.update({'AGENT_MODE':'bedrock', 'AWS_REGION':'us-east-1', 'BEDROCK_MODEL':'us.anthropic.claude-opus-4-6-v1', 'BEDROCK_INVESTIGATOR_MODEL':'us.anthropic.claude-sonnet-4-6', 'LANGFUSE_TRACING_ENVIRONMENT':'aws-hackathon', 'LANGSMITH_TRACING':'false'})
write_private(LOCAL / 'backend.env', backend)
write_private(LOCAL / 'langfuse-login.txt', {'URL':settings['LANGFUSE_URL'], 'EMAIL':settings['LANGFUSE_USER_EMAIL'], 'PASSWORD':password})
print('EC2 runtime configured; Bedrock uses the instance role.')
PY
sh deploy/aws-compose.sh config --quiet
sh deploy/aws-compose.sh up --build -d
sh deploy/aws-compose.sh restart gateway
sh deploy/aws-compose.sh up -d --wait --wait-timeout 600
sh deploy/aws-compose.sh ps
