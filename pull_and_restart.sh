#!/bin/sh
set -eu

# Pull the latest omnilingua image from GHCR and recreate the container.
# Run from the directory that holds docker-compose.yml + .env on the server.
#
# If the image is private, run once on the server:
#   docker login ghcr.io -u <github-user> -p <PAT-with-read:packages>

SERVICE_NAME="${SERVICE_NAME:-omnilingua}"

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
else
    echo "Docker Compose is not installed."
    exit 1
fi

echo "Pulling latest image for ${SERVICE_NAME}..."
$COMPOSE_CMD pull "${SERVICE_NAME}"

echo "Recreating ${SERVICE_NAME} with the pulled image..."
$COMPOSE_CMD up -d "${SERVICE_NAME}"

echo "Pruning dangling images..."
docker image prune -f

echo "Current status:"
$COMPOSE_CMD ps "${SERVICE_NAME}"

echo "Done."
