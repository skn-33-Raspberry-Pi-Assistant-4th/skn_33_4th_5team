#!/usr/bin/env bash
# Build an Apple-silicon-safe linux/amd64 Django image and publish it to ECR.
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

[[ "$account_id" =~ ^[0-9]{12}$ ]] || { echo "AWS account ID must have 12 digits." >&2; exit 64; }
[[ "$tag" =~ ^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$ ]] || { echo "Invalid image tag." >&2; exit 64; }
[[ "$repository" =~ ^[a-z0-9][a-z0-9._/-]*$ ]] || { echo "Invalid ECR repository name." >&2; exit 64; }

cd "$project_root"
docker buildx build --platform linux/amd64 --load -f Dockerfile.aws -t "$image" .
aws ecr get-login-password --region "$region" | docker login --username AWS --password-stdin "$registry"
docker push "$image"

echo "Published image: $image"
