"""Wrapper autour du LLM local (Ollama) — seul point de contact avec Ollama."""

from ollama import Client

from berlue.params import BASE_TEMPERATURE, OLLAMA_HOST, OLLAMA_MODEL


class OllamaClient:
    """Client minimal pour générer une réponse depuis le modèle local via le SDK Python officiel."""

    def __init__(self, host: str = OLLAMA_HOST, model: str = OLLAMA_MODEL):
        self.host = host
        self.model = model
        # Instanciation du client officiel qui va gérer la connexion
        self.client = Client(host=self.host)

    def generate(self, prompt: str, temperature: float = BASE_TEMPERATURE) -> str:
        """Génère une réponse pour `prompt` à la température donnée."""
        try:
            # Appel natif via la librairie officielle
            response = self.client.generate(
                model=self.model,
                prompt=prompt,
                options={
                    "temperature": temperature
                }
            )
            # La librairie renvoie un dictionnaire, on extrait le texte généré
            return response.get("response", "")

        except Exception as e:
            print(f"❌ Erreur lors de la génération avec Ollama : {e}")
            raise RuntimeError(f"Échec de la génération Ollama : {e}") from e

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
        print(f"🤖 [Rép {idx+1}] : {rep.strip()}")
