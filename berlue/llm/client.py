"""Wrapper autour du LLM local (Ollama) — seul point de contact avec Ollama."""

from httpx import TimeoutException
from ollama import Client, ResponseError

from berlue.params import BASE_TEMPERATURE, OLLAMA_HOST, OLLAMA_MODEL


class OllamaClient:
    """Client minimal pour générer une réponse depuis le modèle local via le SDK Python officiel."""

    def __init__(
        self,
        host: str = OLLAMA_HOST,
        model: str = OLLAMA_MODEL,
        timeout: float = 120.0,
        temperature: float = BASE_TEMPERATURE,
    ):
        self.host = host
        self.model = model
        self.temperature = temperature
        self.client = Client(host=self.host, timeout=timeout)

    def generate(self, prompt: str, temperature: float = BASE_TEMPERATURE) -> str:
        """Génère une réponse pour `prompt` à la température donnée."""

        final_temp = temperature if temperature is not None else self.temperature

        try:
            response = self.client.generate(model=self.model, prompt=prompt, options={"temperature": final_temp})

        except TimeoutException as e:
            print("⏳ Timeout : Ollama n'a pas répondu dans le temps imparti.")
            raise TimeoutError("Le serveur Ollama a expiré (Timeout).") from e

        except ResponseError as e:
            print(f"❌ Erreur API Ollama : {e.error}")
            raise RuntimeError(f"Erreur interne Ollama : {e.error}") from e

        except Exception as e:
            print(f"❌ Erreur lors de la communication avec Ollama : {e}")
            raise RuntimeError(f"Échec de la communication Ollama : {e}") from e

        resp_text = response.get("response")

        if not resp_text:
            raise RuntimeError(f"Ollama a généré une réponse vide ou nulle (modèle: {self.model}).")

        return resp_text

    def generate_many(self, prompt: str, k: int, temperature_min: float, temperature_max: float) -> list[str]:
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
            print(f"🔄 Génération en cours (Température: {temp:.2f})...")
            # On réutilise notre méthode unitaire
            resp = self.generate(prompt, temperature=temp)
            responses.append(resp)
            print(f"   → {resp}")
            print("-" * 60)

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
