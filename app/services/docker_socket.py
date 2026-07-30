import json
import socket

from services.logger import logger


DOCKER_SOCKET = "/var/run/docker.sock"
CONTAINER_NAMES = ("dashboard", "collector", "telegram-bot")


class DockerUnavailableError(Exception):
    pass


def read_container_status():
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.settimeout(5)
        client.connect(DOCKER_SOCKET)
        client.sendall(
            b"GET /containers/json?all=true HTTP/1.1\r\n"
            b"Host: docker\r\nConnection: close\r\n\r\n"
        )
        response = b""
        while chunk := client.recv(65536):
            response += chunk
    except OSError as exc:
        logger.exception("Docker socket unavailable")
        raise DockerUnavailableError("Docker socket unavailable") from exc
    finally:
        client.close()

    try:
        _, body = response.split(b"\r\n\r\n", 1)
        containers = json.loads(body)
        by_name = {
            name.lstrip("/"): container
            for container in containers
            for name in container.get("Names", [])
        }
        return [
            {"name": name, "status": by_name.get(name, {}).get("State", "unavailable")}
            for name in CONTAINER_NAMES
        ]
    except (ValueError, json.JSONDecodeError, TypeError, AttributeError) as exc:
        logger.exception("Invalid Docker response")
        raise DockerUnavailableError("Invalid Docker response") from exc
