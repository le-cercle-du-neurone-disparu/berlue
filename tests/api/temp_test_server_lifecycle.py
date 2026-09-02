"""Vérifie que le serveur démarre et répond réellement — en local (`make
run_api_local`), en conteneur Docker (`make docker_build_local` +
`docker_run_local`), via docker-compose (`make compose_up`) et que le build de
production réussit (`make docker_build_prod`) — contrairement à
`test_endpoints.py` qui teste l'app FastAPI en mémoire et ne peut pas détecter
un crash au démarrage (config manquante, port non transmis au conteneur,
etc.)."""

import shutil
import subprocess
import time
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

DOCKER_CONTAINER_NAME = "berlue-api-test-lifecycle"
# Tag dédié (jamais `dev`) : évite d'écraser l'image que vous utilisez peut-être
# en parallèle (docker_run_local, docker-compose) pendant que ce test tourne.
DOCKER_TEST_TAG = "test-lifecycle"


def _get_make_recipe_command(target: str, extra_vars: list[str] | None = None) -> str:
    """Récupère la commande shell réelle qu'exécuterait `make <target>` (via
    `make -n`, dry-run) — pour tester la config Make réelle plutôt qu'une copie
    codée en dur dans le test, qui pourrait diverger silencieusement de
    `make/docker.mk` sans que ce test s'en aperçoive. `extra_vars` : surcharges
    de variables Make (ex. `["DOCKER_TAG=test-lifecycle"]`).

    Si `target` a des prérequis (ex. `compose_up: docker_build_local`), `make
    -n` liste aussi leurs recettes avant celle de `target` — on ne garde que le
    dernier bloc de commande (repéré par les lignes de continuation `\\`), donc
    celui de `target` lui-même."""
    # --no-print-directory : évite les bannières "Entering/Leaving directory"
    # que make ajoute quand ce sous-process make est lui-même lancé depuis un
    # `make` parent (ex. `make test_functional` → pytest → ce test) — sans ce
    # flag, ces bannières se glissaient dans la commande reconstruite ci-dessous.
    result = subprocess.run(
        ["make", "--no-print-directory", "-n", target, *(extra_vars or [])],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    command_lines = [line for line in result.stdout.splitlines() if not line.strip().startswith("echo")]

    blocks: list[list[str]] = []
    for line in command_lines:
        if blocks and blocks[-1][-1].rstrip().endswith("\\"):
            blocks[-1].append(line)
        else:
            blocks.append([line])

    return " ".join(line.rstrip("\\").strip() for line in blocks[-1])


def _wait_for_server(url: str, timeout: float) -> None:
    """Interroge `url` jusqu'à obtenir une réponse, ou lève `TimeoutError`."""
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            httpx.get(url, timeout=1)
            return
        except httpx.HTTPError as e:
            last_error = e
            time.sleep(0.3)
    raise TimeoutError(f"Le serveur n'a pas répondu sur {url} après {timeout}s") from last_error


@pytest.mark.functional
def test_uvicorn_starts_and_responds_locally():
    """Lance un vrai process uvicorn (équivalent à `make run_api_local`) et
    vérifie qu'il répond sur /."""
    port = 8123
    process = subprocess.Popen(
        ["uvicorn", "berlue.api.fast:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_server(f"http://127.0.0.1:{port}/", timeout=15)
        response = httpx.get(f"http://127.0.0.1:{port}/", timeout=5)
        assert response.status_code == 200
        assert response.json()["greeting"] == "Hello from Berlue API"
    finally:
        process.terminate()
        process.wait(timeout=10)


@pytest.mark.functional
@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker non installé")
def test_docker_container_starts_and_responds():
    """Build (`make docker_build_local`) puis lance le conteneur avec la
    commande réelle de `make docker_run_local` (récupérée via `make -n`, `-it`
    remplacé par `-d --name ...` pour pouvoir l'automatiser sans TTY) et vérifie
    qu'il répond sur / — capte notamment une variable d'env requise au
    démarrage (ex. PORT) qui ne serait pas transmise au conteneur par la cible
    Make, ce qu'un `docker run` codé en dur dans le test ne détecterait pas.

    Utilise `DOCKER_TAG=test-lifecycle` (jamais le tag `dev` par défaut) pour ne
    pas écraser une image `:dev` utilisée en parallèle."""
    tag_override = f"DOCKER_TAG={DOCKER_TEST_TAG}"
    subprocess.run(["make", "docker_build_local", tag_override], cwd=REPO_ROOT, check=True, capture_output=True)
    subprocess.run(["docker", "rm", "-f", DOCKER_CONTAINER_NAME], capture_output=True)

    run_command = _get_make_recipe_command("docker_run_local", extra_vars=[tag_override]).replace(
        "docker run -it", f"docker run -d --name {DOCKER_CONTAINER_NAME}"
    )

    try:
        subprocess.run(run_command, shell=True, cwd=REPO_ROOT, check=True, capture_output=True, text=True)
        _wait_for_server("http://localhost:8000/", timeout=30)
        response = httpx.get("http://localhost:8000/", timeout=5)
        assert response.status_code == 200
        assert response.json()["greeting"] == "Hello from Berlue API"
    finally:
        subprocess.run(["docker", "rm", "-f", DOCKER_CONTAINER_NAME], capture_output=True)


@pytest.mark.functional
@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker non installé")
def test_compose_up_starts_and_responds():
    """Vérifie que `make compose_up` (docker-compose : montage de volume +
    `--reload`, cf. `docker-compose.yml`) démarre et répond sur /. Ne teste
    pas le rechargement à chaud lui-même, seulement que le service démarre
    correctement (résolution de `GAR_IMAGE`, montage du volume, etc.).

    Lance `make compose_up` directement (pas une commande extraite via
    `make -n`, contrairement aux autres tests de ce module) : `${GAR_IMAGE}`
    dans `docker-compose.yml` est résolu par `docker compose` au moment de
    l'exécution, via les variables exportées par le `make` parent — pas au
    moment du dry-run `make -n`, qui ne le voit donc pas."""
    subprocess.run(["docker", "compose", "down"], cwd=REPO_ROOT, capture_output=True)

    process = subprocess.Popen(["make", "compose_up"], cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        _wait_for_server("http://localhost:8000/", timeout=30)
        response = httpx.get("http://localhost:8000/", timeout=5)
        assert response.status_code == 200
        assert response.json()["greeting"] == "Hello from Berlue API"
    finally:
        subprocess.run(["docker", "compose", "down"], cwd=REPO_ROOT, capture_output=True)
        process.terminate()
        process.wait(timeout=10)


@pytest.mark.functional
@pytest.mark.skipif(shutil.which("docker") is None, reason="Docker non installé")
def test_docker_build_prod_succeeds():
    """Vérifie que `make docker_build_prod` (image de production, linux/amd64,
    sans dépendances [dev]) build sans erreur. Ne pousse ni ne déploie rien —
    juste que le build local réussit (chemin de build différent de
    `docker_build_local` : autres build-args, autre plateforme)."""
    build_command = _get_make_recipe_command("docker_build_prod")
    tag = build_command.split(" -t ", 1)[1].split()[0]

    try:
        subprocess.run(build_command, shell=True, cwd=REPO_ROOT, check=True, capture_output=True, text=True)
        result = subprocess.run(["docker", "image", "inspect", tag], capture_output=True)
        assert result.returncode == 0, f"Image {tag} introuvable après le build"
    finally:
        subprocess.run(["docker", "rmi", tag], capture_output=True)
