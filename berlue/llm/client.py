"""Wrapper autour du LLM local (Ollama) — seul point de contact avec Ollama."""

from berlue.params import BASE_TEMPERATURE, OLLAMA_HOST, OLLAMA_MODEL


class OllamaClient:
    """Client minimal pour générer une réponse depuis le modèle local."""

    def __init__(self, host: str = OLLAMA_HOST, model: str = OLLAMA_MODEL):
        self.host = host
        self.model = model

    def generate(self, prompt: str, temperature: float = BASE_TEMPERATURE) -> str:
        """Génère une réponse pour `prompt` à la température donnée."""
        # TODO(llm)
        raise NotImplementedError

    def generate_many(self, prompt: str, k: int, temperature: float) -> list[str]:
        """Génère `k` réponses indépendantes au même prompt."""
        return [self.generate(prompt, temperature=temperature) for _ in range(k)]
