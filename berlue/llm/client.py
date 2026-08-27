"""Wrapper autour du LLM local (Ollama) — seul point de contact avec Ollama."""

from httpx import TimeoutException
from ollama import Client, ResponseError

from berlue.params import BASE_TEMPERATURE, OLLAMA_HOST, OLLAMA_MODEL


class OllamaClient:
    """Client minimal pour générer une réponse depuis le modèle local via le SDK Python officiel."""

    def __init__(self, host: str = OLLAMA_HOST, model: str = OLLAMA_MODEL, timeout: float = 120.0):
        self.host = host
        self.model = model
        # Instanciation du client officiel avec gestion du timeout
        self.client = Client(host=self.host, timeout=timeout)

    def generate(self, prompt: str, temperature: float = BASE_TEMPERATURE) -> str:
        """Génère une réponse pour `prompt` à la température donnée."""
        try:
            # Appel natif via la librairie officielle
            response = self.client.generate(model=self.model, prompt=prompt, options={"temperature": temperature})

        except TimeoutException as e:
            # On attrape proprement le timeout du client HTTP sous-jacent
            print("⏳ Timeout : Ollama n'a pas répondu dans le temps imparti.")
            raise TimeoutError("Le serveur Ollama a expiré (Timeout).") from e

        except ResponseError as e:
            # On attrape l'exception native d'Ollama (ex: le modèle n'existe pas)
            print(f"❌ Erreur API Ollama : {e.error}")
            raise RuntimeError(f"Erreur interne Ollama : {e.error}") from e

        except Exception as e:
            print(f"❌ Erreur lors de la communication avec Ollama : {e}")
            raise RuntimeError(f"Échec de la communication Ollama : {e}") from e

        # Extraction de la réponse (sera None si la clé vaut None ou n'existe pas)
        resp_text = response.get("response")

        # Vérification stricte : si c'est None ou une chaîne vide ("")
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

        return responses
