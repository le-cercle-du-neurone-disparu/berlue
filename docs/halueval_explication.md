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
| `knowledge`     | string | Contexte ou connaissance de référence (généralement issu de Wikipedia) | `"Nikolaj Coster-Waldau is a Danish actor..."`  |
| `question` | string   | Question posée à laquelle le modèle doit répondre   |  `"Where was Nikolaj Coster-Waldau born?"`  |
| `right_answer` | string   | Réponse correcte et factuelle basée sur la connaissance  |  `"Denmark"`  |
| `hallucinated_answer`       | string  | Réponse générée automatiquement contenant une hallucination  | `"Norway"` |

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
| `user_query`     | string | La question ou requête posée par l'utilisateur | "What is the capital of France?"  |
| `chatgpt_response` | string   | La réponse générée par ChatGPT à la requête utilisateur   |  "The capital of France is Paris."  |
| `hallucination_label` | string   | Label indiquant si la réponse contient une hallucination   |  "`Yes`"  |

### 📊 Statistiques Globales

| Métrique | Valeur |
|:--------------------|:------:|
| Total d'échantillons	| 35 000 |
| Proportion des tâches	| 3x 10 000 (QA, Dialogue, Résumé) + 5 000 (Général) |
| Source des données | HotpotQA, OpenDialKG, CNN/Daily Mail, Alpaca |


## 3. Chargement du Dataset

### Installation des dépendances

```python
!pip install requests datasets scikit-learn matplotlib numpy
```

### Chargement direct depuis GitHub

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
### Aperçu des exemples
```python
print("Premiers exemples du sous-ensemble QA :")
for i in range(3):
    print(f"Exemple {i}: {qa_data[i]}")
```
#### Output attendu :
```text
Exemple 0: {'knowledge': 'Nikolaj Coster-Waldau is a Danish actor...', 'question': 'Where was Nikolaj Coster-Waldau born?', 'right_answer': 'Denmark', 'hallucinated_answer': 'Norway'}
Exemple 1: {'knowledge': '...', 'question': '...', 'right_answer': '...', 'hallucinated_answer': '...'}
```

### Structure du Dataset
```python
qa_data
```
#### Output :
```text
Dataset({
    features: ['knowledge', 'question', 'right_answer', 'hallucinated_answer'],
    num_rows: 10000
})
```
### Statistiques de base
```python
# Longueur des questions
import numpy as np

question_lengths = [len(item['question'].split()) for item in qa_data]
print(f"Longueur moyenne des questions : {np.mean(question_lengths):.1f} mots")
print(f"Longueur min : {np.min(question_lengths)} \nLongueur min {np.max(question_lengths)} mots")
```
#### Output

```text
Longueur moyenne des questions : 17.9 mots
Longueur min : 4 
Longueur min 100 mots
```

## 🧹 5. Prétraitement pour l'Évaluation
### Pipeline de prétraitement

```
python
def preprocess_halueval_for_evaluation(data, subset_type='qa'):
    """
    Prétraite les données HaluEval pour la tâche d'évaluation (YES/NO).
    """
    X = []  # Contexte + réponse à évaluer
    y = []  # Labels (0 pour factuel, 1 pour halluciné)
    
    for item in data:
        if subset_type == 'qa':
            context = item.get('knowledge', '')
            right_response = item.get('right_answer', '')
            hallucinated_response = item.get('hallucinated_answer', '')
        elif subset_type == 'dialogue':
            context = item.get('knowledge', '')
            right_response = item.get('right_response', '')
            hallucinated_response = item.get('hallucinated_response', '')
        elif subset_type == 'summarization':
            context = item.get('document', '')
            right_response = item.get('right_summary', '')
            hallucinated_response = item.get('hallucinated_summary', '')
        elif subset_type == 'general':
            context = item.get('user_query', '')
            right_response = ''  # Pas de réponse correcte fournie
            hallucinated_response = item.get('chatgpt_response', '')
            # Le label est déjà dans hallucination_label (Yes/No)
            label = 1 if item.get('hallucination_label', 'No') == 'Yes' else 0
            y.append(label)
            X.append({'context': context, 'response': hallucinated_response})
            continue
        
        # Ajouter la réponse correcte (label 0)
        X.append({'context': context, 'response': right_response})
        y.append(0)
        
        # Ajouter la réponse hallucinée (label 1)
        X.append({'context': context, 'response': hallucinated_response})
        y.append(1)
    
    return X, y

# Exemple d'utilisation
X, y = preprocess_halueval_for_evaluation(qa_data, 'qa')
print(f"Nombre total d'échantillons préparés : {len(X)}")
print(f"Distribution des labels : YES={sum(y)}, NO={len(y)-sum(y)}")
```
#### Output

```text
Nombre total d'échantillons préparés : 20000
Distribution des labels : YES=10000, NO=10000
```
### Encodage des labels
```
python
from sklearn.preprocessing import LabelEncoder

le = LabelEncoder()
y_encoded = le.fit_transform(y)  # 0 -> 'No', 1 -> 'Yes'
print(f"Classes : {le.classes_}")
```
## 🤖 6. Modèle Baseline avec LLM (via API)
Pour évaluer un LLM sur HaluEval, nous utilisons une approche zero-shot :

```
python
import requests
import json

def evaluate_with_llm(context, response, api_url, api_key, model_name="gpt-3.5-turbo"):
    """
    Évalue une réponse en utilisant un LLM via API.
    La sortie doit être 'YES' ou 'NO'.
    """
    prompt = f"""
Vous êtes un juge expert chargé d'évaluer si une réponse générée par une IA est fidèle au contexte fourni.

Contexte : {context}

Réponse à évaluer : {response}

Question : La réponse contient-elle des informations non vérifiables ou contredisant le contexte ?
Répondez uniquement par YES ou NO.
"""
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0  # Pour une sortie déterministe
    }
    
    try:
        response = requests.post(f"{api_url}/chat/completions", headers=headers, json=data)
        response.raise_for_status()
        result = response.json()
        return result['choices'][0]['message']['content'].strip()
    except Exception as e:
        print(f"Erreur lors de l'appel API : {e}")
        return None
```