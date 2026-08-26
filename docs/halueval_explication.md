# 📚 Guide du Dataset HaluEval

## 📖 1. Qu'est-ce que HaluEval ?

**HaluEval**, créé par des chercheurs de RUCAIBox, est un benchmark conçu pour évaluer et analyser les hallucinations dans les grands modèles de langage (LLMs).

### 🎯 Objectif

L'objectif est de développer des systèmes capables de :

- **Détecter** les hallucinations dans les réponses générées par des LLMs
- **Comprendre** les types d'hallucinations (factuelles, logiques, contextuelles)
- **Évaluer** la fiabilité des modèles de langage
- **Améliorer** la robustesse des systèmes de génération de texte

### Entrées et sorties

- **Input** : Un contexte (document, historique de dialogue, question) + une réponse générée par un LLM à juger.
- **Output** : Label (HALLUCINATION ou NON-HALLUCINATION)

### 🌟 Pourquoi HaluEval est important ?

- **Évaluation des LLMs** : Mesure la fiabilité des modèles de langage
- **Détection d'hallucinations** : Identifie les informations factuellement incorrectes
- **Transparence** : Nécessite des preuves pour justifier les décisions
- **Benchmark** : Référence standard pour l'évaluation de la véracité des LLMs

## 📊 2. Structure du Dataset

Le dataset HaluEval se compose de 35 000 échantillons, répartis en deux grandes catégories.

### 2.1. Échantillons Générés Automatiquement (30 000)
Ces échantillons sont créés à partir de datasets existants et couvrent trois tâches principales. Chaque exemple est stocké dans un fichier JSON dédié.

#### 📁 Fichiers de données

| Fichier | Sous-ensemble | Nombre | Description |
|:--------------------|:------:|-------:|-------:|
|`qa_data.json`	| `qa_samples` | 10 000 | Hallucinations dans des réponses à des questions (source : HotpotQA)|
|`dialogue_data.json`	| `dialogue_samples` | 10 000 | Hallucinations dans des réponses conversationnelles (source : OpenDialKG)|
|`summarization_data.json`	| `summarization_samples` | 10 000 | Hallucinations dans des résumés de documents (source : CNN/Daily Mail)|

#### Format des données (exemple pour qa_data.json)

```json
{
    "knowledge": "Nikolaj Coster-Waldau is a Danish actor...",
    "question": "Where was Nikolaj Coster-Waldau born?",
    "right_answer": "Denmark",
    "hallucinated_answer": "Norway"
}
```
#### 📋 Description des Champs


| Champ| Type | Description | Exemple |
|:--------------------|:------:|-------:|-------:|
| `id`     | int/string | Identifiant unique du claim | 12345  |
| `question` | string   | La question posée    |  "What is the capital of France?"  |
| `response` | string   | La réponse générée par un LLM   |  "Paris is the capital of France."  |
| `label`       | string  | Classification de l'hallucination   | "NON-HALLUCINATION" |
| `explanation`       | string  | Justification de la classification   | "Paris is indeed the capital of France." |

### 2.2. Échantillons Annotés par des Humains (5 000)

Ces données proviennent de requêtes générales issues du dataset Alpaca, auxquelles ChatGPT a répondu. Les réponses ont ensuite été annotées manuellement pour identifier la présence d'hallucinations.

#### 📁 Fichiers de données

| Fichier | Sous-ensemble | Nombre | Description |
|:--------------------|:------:|-------:|-------:|
|`general_data.json`	| `general_samples` | 5 000 | Requêtes générales d'Alpaca + réponses ChatGPT + label humain (YES/NO)|

#### Format des données (exemple pour general_data.json)

```json
{
    "user_query": "What is the capital of France?",
    "chatgpt_response": "The capital of France is Paris.",
    "hallucination_label": "No"
}
```

#### 📋 Description des Champs


| Champ| Type | Description | Exemple |
|:--------------------|:------:|-------:|-------:|
| `user_query`     | int/string | Identifiant unique du claim | 12345  |
| `chatgpt_response` | string   | La question posée    |  "What is the capital of France?"  |
| `hallucination_label` | string   | La réponse générée par un LLM   |  "Paris is the capital of France."  |

### 📊 Statistiques Globales

| Métrique | Valeur |
|:--------------------|:------:|
| Total d'échantillons	| 35 000 |
| Proportion des tâches	| 3x 10 000 (QA, Dialogue, Résumé) + 5 000 (Général) |
| Source des données | HotpotQA, OpenDialKG, CNN/Daily Mail, Alpaca |


## 3. Chargement du Dataset

### 3.1 Installation des dépendances

```python
!pip install requests datasets scikit-learn matplotlib numpy
```

### 3.2 Chargement direct depuis GitHub

```python
import requests
import json
from datasets import Dataset

def load_halueval_subset(subset_url):
    """
    Charge un sous-ensemble de HaluEval depuis l'URL GitHub.
    """
    response = requests.get(subset_url)
    response.raise_for_status()
    
    # Le fichier est au format JSON Lines (chaque ligne est un JSON)
    data = []
    for line in response.text.strip().split('\n'):
        if line:
            item = json.loads(line)
            data.append(item)
    
    return Dataset.from_list(data)

# URLs des fichiers de données HaluEval
qa_url = "https://raw.githubusercontent.com/RUCAIBox/HaluEval/main/data/qa_data.json"
dialogue_url = "https://raw.githubusercontent.com/RUCAIBox/HaluEval/main/data/dialogue_data.json"
summarization_url = "https://raw.githubusercontent.com/RUCAIBox/HaluEval/main/data/summarization_data.json"
general_url = "https://raw.githubusercontent.com/RUCAIBox/HaluEval/main/data/general_data.json"

# Exemple pour QA :
# Chargement
qa_data = load_halueval_subset(qa_url)
print(f"QA data: {len(qa_data)} exemples")
```

## 📈 4. Exploration des Données
### 4.1 Aperçu des exemples
```python
print("Premiers exemples du sous-ensemble QA :")
for i in range(3):
    print(f"Exemple {i}: {qa_data[i]}")
```