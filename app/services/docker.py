import httpx


class DockerMonitorUnavailableError(Exception):
    pass


def get_docker_status():
    try:
        with httpx.Client(timeout=5) as client:
            response = client.get("http://docker-monitor:9000/status")
            response.raise_for_status()
            payload = response.json()
        if payload.get("success") is not True or not isinstance(payload.get("data"), list):
            raise ValueError("Invalid Docker monitor response")
        return payload["data"]
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise DockerMonitorUnavailableError("Docker monitor unavailable") from exc
