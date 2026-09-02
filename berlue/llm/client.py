"""Wrapper autour du LLM local (Ollama) — seul point de contact avec Ollama."""

import logging
import os
import time

from httpx import TimeoutException
from ollama import Client, ResponseError

from berlue.params import BASE_TEMPERATURE, OLLAMA_HOST, OLLAMA_MODEL

logger = logging.getLogger(__name__)


def _running_on_cloud_run() -> bool:
    """Même détection que `gcp_result_store._running_on_cloud_run()` —
    dupliquée ici plutôt qu'importée pour ne pas coupler `berlue.llm` à
    `berlue.evaluation` (deux domaines indépendants)."""
    return bool(os.environ.get("K_SERVICE") or os.environ.get("CLOUD_RUN_JOB"))


def _cloud_run_auth_headers(target_url: str) -> dict:
    """Jeton d'identité OIDC pour appeler un service Cloud Run privé
    (`--no-allow-unauthenticated`, ex. le service Ollama) depuis un autre
    service/job Cloud Run — audience = l'URL cible elle-même. Dict vide en
    local (Ollama local n'a pas d'auth) : ne fait un appel réseau que sur
    Cloud Run, jamais en dev.

    `IDTokenCredentials` explicite plutôt que le helper générique
    `google.oauth2.id_token.fetch_id_token()` — ce dernier a produit un
    jeton vide sans lever d'exception en conditions réelles (Job Cloud Run
    appelant le service Ollama, jamais reproduit en local), constaté via
    les logs du service cible ("Empty Authorization header value").
    """
    if not _running_on_cloud_run():
        return {}
    import google.auth.compute_engine
    import google.auth.transport.requests

    credentials = google.auth.compute_engine.IDTokenCredentials(
        google.auth.transport.requests.Request(), target_audience=target_url, use_metadata_identity_endpoint=True
    )
    credentials.refresh(google.auth.transport.requests.Request())
    if not credentials.token:
        raise RuntimeError(f"❌ Jeton OIDC vide pour {target_url} après refresh() — IDTokenCredentials en échec.")
    return {"Authorization": f"Bearer {credentials.token}"}


class OllamaClient:
    """Client minimal pour générer une réponse depuis le modèle local via le SDK Python officiel."""

    def __init__(
        self,
        host: str = OLLAMA_HOST,
        model: str = OLLAMA_MODEL,
        timeout: float = 120.0,
        temperature: float = BASE_TEMPERATURE,
        verbose: bool = False,
    ):
        self.host = host
        self.model = model
        self.temperature = temperature
        self.verbose = verbose
        self.client = Client(host=self.host, timeout=timeout, headers=_cloud_run_auth_headers(self.host))

    def list_models(self) -> list[str]:
        """Liste les modèles disponibles sur le serveur Ollama ciblé (`self.host`) —
        passe par `self.client`, déjà configuré avec l'auth OIDC nécessaire si
        `self.host` est un service Cloud Run privé, contrairement au module
        `ollama` global (`ollama.list()`), qui l'ignore."""
        response = self.client.list()
        models = response.get("models", []) if isinstance(response, dict) else response.models
        names = []
        for m in models:
            name = m.get("name", m.get("model")) if isinstance(m, dict) else m.model
            names.append(name)
        return names

    def generate(self, prompt: str, temperature: float | None = None, num_predict: int | None = None) -> str:
        """Génère une réponse pour `prompt` à la température donnée. Chaque
        appel est indépendant (endpoint `/api/generate`, stateless) — pas
        d'historique de conversation entre deux appels, même consécutifs sur
        le même client.

        `num_predict` : borne dure sur le nombre de tokens générés (défaut
        Ollama = pas de limite). Sans elle, un modèle qui ne suit pas une
        consigne de longueur peut générer jusqu'à saturer `n_ctx_slot` puis
        continuer via un *context shift* (troncature + poursuite) répété,
        chacun coûtant plusieurs secondes — un appel peut alors dépasser
        largement le temps attendu, indépendamment de tout problème de
        charge ou de configuration serveur (observé en conditions réelles :
        un appel de génération resté bloqué plus de 120s de cette façon).
        À fixer à chaque appel dont la longueur attendue est connue."""

        # `None` (le défaut) veut dire « celle du client » ; une valeur explicite prime.
        # Avec `BASE_TEMPERATURE` en défaut de signature, `temperature` n'était jamais
        # `None` et `self.temperature` n'était jamais lue : la température passée au
        # constructeur — donc celle du payload de l'API — ne faisait rien.
        final_temp = temperature if temperature is not None else self.temperature
        options = {"temperature": final_temp}
        if num_predict is not None:
            options["num_predict"] = num_predict

        if self.verbose:
            logger.debug("📤 [Ollama:%s, temp=%s] Prompt :\n%s", self.model, final_temp, prompt)

        start = time.monotonic()

        try:
            response = self.client.generate(model=self.model, prompt=prompt, options=options)

        except TimeoutException as e:
            logger.error("⏳ Timeout : Ollama n'a pas répondu dans le temps imparti.")
            raise TimeoutError("Le serveur Ollama a expiré (Timeout).") from e

        except ResponseError as e:
            logger.error("❌ Erreur API Ollama : %s", e.error)
            raise RuntimeError(f"Erreur interne Ollama : {e.error}") from e

        except Exception as e:
            logger.error("❌ Erreur lors de la communication avec Ollama : %s", e)
            raise RuntimeError(f"Échec de la communication Ollama : {e}") from e

        elapsed = time.monotonic() - start

        resp_text = response.get("response")

        if not resp_text:
            raise RuntimeError(f"Ollama a généré une réponse vide ou nulle (modèle: {self.model}).")

        # `done_reason == "length"` signifie que `num_predict` a coupé la génération.
        # Le texte rendu est amputé — un JSON tronqué en plein milieu ne parse pas et
        # dégénère silencieusement en résultat vide en aval. On le signale plutôt que
        # de le subir : c'est un défaut de configuration, pas une réponse du modèle.
        if response.get("done_reason") == "length":
            logger.warning(
                "✂️ Génération tronquée par num_predict=%s (modèle: %s) — le résultat est amputé. "
                "Relever la borne pour ce type d'appel.",
                num_predict,
                self.model,
            )

        if self.verbose:
            logger.debug("📥 [Ollama:%s, %.2fs] Réponse :\n%s", self.model, elapsed, resp_text)

        return resp_text

    def warmup(self, prompt: str = "Bonjour", temperature: float = 0.0) -> float:
        """Force le chargement du modèle en mémoire (VRAM) via un appel jetable —
        la réponse générée n'est pas utilisée, seul le temps de chargement
        compte. À appeler avant de démarrer le chrono d'un benchmark : sans ça,
        le premier appel réel du run paierait ce chargement et fausserait sa
        mesure (le modèle reste chaud tant qu'`OLLAMA_KEEP_ALIVE` ne l'a pas
        déchargé — cf. docs/evaluation/execution-benchmark.md). Retourne le
        temps écoulé, pour affichage.
        """
        start = time.monotonic()
        self.generate(prompt=prompt, temperature=temperature)
        return time.monotonic() - start

    def generate_many(
        self, prompt: str, k: int, temperature_min: float, temperature_max: float, num_predict: int | None = None
    ) -> list[str]:
        """
        Génère `k` réponses indépendantes au même prompt, chacune à une température
        choisie dans `[temperature_min, temperature_max]`.
        """

        if k <= 0:
            return []

        # Stratégie : Répartition équilibrée des températures sur l'intervalle
        if k == 1:
            temperatures = [(temperature_min + temperature_max) / 2.0]
        else:
            step = (temperature_max - temperature_min) / (k - 1)
            temperatures = [temperature_min + (i * step) for i in range(k)]

        responses = []
        for temp in temperatures:
            logger.debug("🔄 Génération en cours (Température: %.2f)...", temp)
            # On réutilise notre méthode unitaire
            resp = self.generate(prompt, temperature=temp, num_predict=num_predict)
            responses.append(resp)
            logger.debug("   → %s", resp)
            logger.debug("-" * 60)
        return responses


# ==============================================================================
# TESTS LOCAUX
# ==============================================================================
if __name__ == "__main__":
    import sys

    from ollama import Client as OllamaNativeClient

    host_url = "http://127.0.0.1:11434"
    print("🔍 Recherche du serveur Ollama local...")

    # 1. Vérifier que le serveur tourne et récupérer la liste des modèles
    try:
        temp_client = OllamaNativeClient(host=host_url)
        response = temp_client.list()

        # Selon la version du package, response est un objet ou un dictionnaire
        # (Réécrit sur plusieurs lignes pour respecter la limite des 120 caractères)
        if hasattr(response, "models"):
            available_models = getattr(response, "models", [])
        else:
            available_models = response.get("models", [])

    except Exception:
        print("❌ Erreur : Impossible de contacter le serveur Ollama.")
        print("💡 Assure-toi qu'il est lancé (via `make ollama_setup` ou `ollama serve`).")
        sys.exit(1)

    # 2. Vérifier qu'au moins un modèle est téléchargé
    if not available_models:
        print("❌ Erreur : Le serveur tourne, mais AUCUN modèle n'est installé.")
        print("💡 Lance `ollama pull qwen2.5:0.5b` dans ton terminal d'abord.")
        sys.exit(1)

    # 3. Récupérer le nom du modèle de façon robuste
    first_model = available_models[0]
    if hasattr(first_model, "model"):
        # Versions récentes (objet Pydantic)
        auto_model = first_model.model
    elif isinstance(first_model, dict):
        # Anciennes versions (dictionnaire)
        auto_model = first_model.get("model", first_model.get("name"))
    else:
        # Fallback de dernier recours
        auto_model = str(first_model)

    print(f"✅ Serveur OK ! Modèle sélectionné automatiquement : {auto_model}")
    print("🚀 Initialisation du client...\n")

    # 4. Lancer les tests avec ce modèle auto-détecté
    client = OllamaClient(host=host_url, model=auto_model)

    question = "Pourquoi l'eau mouille-t-elle ? Réponds en une courte phrase."

    print("--- TEST 1 : generate() ---")
    reponse = client.generate(prompt=question, temperature=0.3)
    print(f"🤖 [Temp 0.3] : {reponse.strip()}\n")

    print("--- TEST 2 : generate_many() ---")
    reponses_multi = client.generate_many(question, k=3, temperature_min=0.2, temperature_max=0.8)

    for idx, rep in enumerate(reponses_multi):
        print(f"🤖 [Rép {idx + 1}] : {rep.strip()}")
