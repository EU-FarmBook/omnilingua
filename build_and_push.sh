#!/bin/sh
set -eu

# Build the omnilingua image and push it to GHCR.
#
# Usage:
#   ./build_and_push.sh          # tag = latest
#   ./build_and_push.sh v1       # tag = v1
#
# Prerequisites (one-time):
#   docker login ghcr.io -u <github-user> -p <PAT-with-write:packages>
#
# The image is built for linux/amd64 explicitly so it runs on x86_64 servers
# regardless of the local CPU architecture (for example, Apple Silicon Macs).

REGISTRY="${REGISTRY:-ghcr.io/eu-farmbook}"
IMAGE_NAME="${IMAGE_NAME:-${REGISTRY}/omnilingua}"
TAG="${1:-latest}"
PLATFORM="${PLATFORM:-linux/amd64}"

echo "Building image: ${IMAGE_NAME}:${TAG} (${PLATFORM})"
docker build --platform "${PLATFORM}" -t "${IMAGE_NAME}:${TAG}" .

echo "Pushing image: ${IMAGE_NAME}:${TAG}"
docker push "${IMAGE_NAME}:${TAG}"

echo "Done."
echo "Image: ${IMAGE_NAME}:${TAG}"
