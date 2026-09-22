#!/usr/bin/env bash
# Pull one immutable ECR tag on EC2, start Nginx + Django, and verify public HTTP.
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 <tag> <aws-account-id> <ecr-repository>" >&2
  exit 64
fi

tag="$1"
account_id="$2"
repository="$3"
region="ap-northeast-2"
registry="${account_id}.dkr.ecr.${region}.amazonaws.com"
image="${registry}/${repository}:${tag}"
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="$project_root/.env"
release_file="$project_root/deploy/release.env"
previous_release_file="$project_root/deploy/previous-release.env"
temporary_release="$(mktemp "$project_root/deploy/.release.XXXXXX")"
compose=(docker compose --project-name picare-aws --env-file "$env_file" --env-file "$temporary_release" -f "$project_root/deploy/compose.aws.yaml")

cleanup() { rm -f "$temporary_release"; }
trap cleanup EXIT

[[ "$account_id" =~ ^[0-9]{12}$ ]] || { echo "AWS account ID must have 12 digits." >&2; exit 64; }
[[ "$tag" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || { echo "Invalid image tag." >&2; exit 64; }
[[ "$repository" =~ ^[a-z0-9][a-z0-9._/-]*$ ]] || { echo "Invalid ECR repository name." >&2; exit 64; }
[[ -f "$env_file" ]] || { echo "Missing $env_file. Copy deploy/aws.env.example first." >&2; exit 78; }

for required in AI_API_URL AI_API_TOKEN DJANGO_SECRET_KEY DJANGO_DB_NAME DJANGO_DB_USER DJANGO_DB_PASSWORD DJANGO_DB_HOST; do
  if ! grep -Eq "^${required}=.+" "$env_file"; then
    echo "Missing required value in .env: ${required}" >&2
    exit 78
  fi
done

printf 'PICARE_WEB_IMAGE=%s\n' "$image" > "$temporary_release"

"${compose[@]}" config --quiet
aws ecr get-login-password --region "$region" | docker login --username AWS --password-stdin "$registry"
"${compose[@]}" pull
"${compose[@]}" up -d --wait --wait-timeout 180

base_url="${PUBLIC_BASE_URL:-http://127.0.0.1}"
curl --fail --location --max-time 10 "$base_url/" >/dev/null
curl --fail --location --max-time 10 "$base_url/accounts/login/" >/dev/null
health_json="$(curl --fail --max-time 10 "$base_url/health/")"
python3 -c 'import json, sys; data=json.loads(sys.argv[1]); assert data.get("status") == "ok" and data.get("ready") is True' "$health_json"

if [[ -f "$release_file" ]]; then
  cp "$release_file" "$previous_release_file"
  chmod 600 "$previous_release_file"
fi
cp "$temporary_release" "$release_file"
chmod 600 "$release_file"

echo "Release is healthy: $image"
echo "Rollback with: bash deploy/aws-release.sh <previous-tag> $account_id $repository"
