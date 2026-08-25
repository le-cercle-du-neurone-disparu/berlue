# 📚 Guide du Dataset FEVER

## 📖 1.Qu'est-ce que FEVER ?

```FEVER (Fact Extraction and VERification)```, créé en 2018 par des chercheurs de l'Université de Cambridge, est un dataset conçu pour la vérification automatique des faits.

### 🎯 Objectif

L'objetif est de développer des systèmes capables de :

Extraire des informations pertinentes depuis Wikipedia

Vérifier si une affirmation est vraie ou fausse

Justifier la décision avec des preuves

### Entrées et sorties

Input  : Une affirmation (claim)
Output : Label (SUPPORTS, REFUTES, NOT ENOUGH INFO) + Preuves

### 🌟 Pourquoi FEVER est important ?

Lutte contre la désinformation : Identifier les fausses nouvelles

Recherche en NLP : Combinaison de compréhension du langage et de raisonnement

Benchmark : Référence standard pour les systèmes de vérification

Transparence : Nécessite des preuves, pas juste une classification

## 📊 2. Structure du Dataset

### Format des Données
Chaque exemple dans FEVER est un objet JSON avec les champs suivants :

```json
{
    "id": 12345,
    "claim": "Nikolaj Coster-Waldau was born in Denmark",
    "label": "SUPPORTS",
    "evidence": [
        [
            [0, 1, "Nikolaj_Coster-Waldau", 2],
            [0, 2, "Denmark", 3]
        ]
    ]
}
```
### 📋 Description des Champs


| Champ| Type | Description | Exemple |
|:--------------------|:------:|-------:|-------:|
| `id`     | int/string | Identifiant unique du claim | 12345  |
| `Claim`       | string   | L'affirmation à vérifier    |  "Nikolaj Coster-Waldau was born in Denmark"  |
| `label`       | Test   | 123    | "SUPPORTS" |

## Les Labels

### Les 3 Classes Principales
		
| Label | Signification | Exemple |
|----------------|--------|----------|
| ✅ SUPPORTS | L'affirmation est vraie | "Paris est la capitale de la France" → VRAI" |
|  REFUTES | L'affirmation est fausse | "La capitale de la France est Berlin" → FAUX |
| NOT ENOUGH INFO	| Pas assez d'informations pour vérifier | "Le président de la France en 2050 sera..." → INCONNU |

### 📊 Distribution des 145,449 exemples :

SUPPORTS          : 80,035 (55.0%) ██████████████████████████████████

REFUTES           : 29,713 (20.4%) ████████████████

NOT ENOUGH INFO   : 35,701 (24.5%) ███████████████████

## 3. Chargement du Dataset

### Installation des dépendances

```python
!pip install requests datasets scikit-learn matplotlib numpy
```
### Chargement avec traitement par lots

```
python
import requests
import json
from datasets import Dataset
from sklearn.preprocessing import LabelEncoder
import numpy as np
import matplotlib.pyplot as plt
from collections import Counter
import re

def load_fever_batch():
    """
    Charge FEVER avec traitement en lots pour éviter les problèmes de mémoire
    """
    url = "https://fever.ai/download/fever/train.jsonl"
    response = requests.get(url)
    response.raise_for_status()
    
    batch = []
    batch_size = 10000
    
    for line in response.text.strip().split('\n'):
        if line:
            item = json.loads(line)
            # Nettoyer et convertir
            batch.append({
                'id': str(item.get('id', '')),
                'claim': item.get('claim', ''),
                'label': item.get('label', '')
            })
    
    dataset = Dataset.from_list(batch)
    return dataset

# Utilisation
data = load_fever_batch()
```
## 📈 4. Exploration des Données

### Aperçu des exemples

```python
print("Premiers exemples:")
for i in range(5):
    print(f"Exemple {i}: {data[i]}")
```
#### Output:

```
Exemple 0: {'id': '75397', 'claim': 'Nikolaj Coster-Waldau worked with the Fox Broadcasting Company.', 'label': 'SUPPORTS'}
Exemple 1: {'id': '150448', 'claim': 'Roman Atwood is a content creator.', 'label': 'SUPPORTS'}
Exemple 2: {'id': '214861', 'claim': 'History of art includes architecture, dance, sculpture, music, painting, poetry literature, theatre, narrative, film, photography and graphic arts.', 'label': 'SUPPORTS'}
Exemple 3: {'id': '156709', 'claim': 'Adrienne Bailon is an accountant.', 'label': 'REFUTES'}
Exemple 4: {'id': '83235', 'claim': 'System of a Down briefly disbanded in limbo.', 'label': 'NOT ENOUGH INFO'}
```
### Structure du Dataset

```
python
data
```

#### Output:

```text
Dataset({
    features: ['id', 'claim', 'label'],
    num_rows: 145449
})
```

## 📊 5. Statistiques et Visualisations
### Distribution des labels

```
python
labels = data['label']
label_counts = Counter(labels)

print("\nDistribution des labels:")
for label, count in label_counts.items():
    print(f"  {label}: {count} ({count/len(data)*100:.1f}%)")

print(f"\nNombre total d'exemples: {len(data)}")
print(f"Colonnes disponibles: {data.column_names}")
print(f"Types des colonnes: {data.features}")
```

#### Output:

```
text
Distribution des labels:
  SUPPORTS: 80035 (55.0%)
  REFUTES: 29775 (20.5%)
  NOT ENOUGH INFO: 35639 (24.5%)

Nombre total d'exemples: 145449
Colonnes disponibles: ['id', 'claim', 'label']
Types des colonnes: {'id': Value('string'), 'claim': Value('string'), 'label': Value('string')}
```

### Visualisation de la Distribution

```
python
plt.figure(figsize=(10, 6))
colors = ['green', 'red', 'orange']
plt.bar(label_counts.keys(), label_counts.values(), color=colors)
plt.title('Distribution des Labels dans FEVER', fontsize=16)
plt.xlabel('Labels', fontsize=12)
plt.ylabel("Nombre d'exemples", fontsize=12)
plt.show()
```
<img src="/opt/wagon/src/berlue/labels.png" alt="Description" width="300" height="200">

### Chargement de tous les splits

```
python
def load_all_splits():
    """
    Charge tous les splits de FEVER
    """
    splits = {
        "train": "https://fever.ai/download/fever/train.jsonl",
        "validation": "https://fever.ai/download/fever/shared_task_dev.jsonl",
        "test": "https://fever.ai/download/fever/shared_task_test.jsonl"
    }
    
    datasets = {}
    
    for name, url in splits.items():
        print(f"📥 Chargement de {name}...")
        response = requests.get(url)
        response.raise_for_status()
        
        data = []
        for line in response.text.strip().split('\n'):
            if line:
                item = json.loads(line)
                data.append({
                    'id': str(item.get('id', '')),
                    'claim': item.get('claim', ''),
                    'label': item.get('label', '')
                })
        
        datasets[name] = Dataset.from_list(data)
        print(f"✅ {name}: {len(data)} exemples")
    
    return datasets

# Charger tous les splits
all_splits = load_all_splits()
train_data = all_splits["train"]
validation_data = all_splits["validation"]
test_data = all_splits["test"]

print(f"\nLes données sont au nombre de: {len(train_data) + len(validation_data) + len(test_data)} et réparties en : ")
print(f"\nTrain: {len(train_data)}")
print(f"Validation: {len(validation_data)}")
print(f"Test: {len(test_data)}")
```

#### Output:

```text
📥 Chargement de train...
✅ train: 145449 exemples
📥 Chargement de validation...
✅ validation: 19998 exemples
📥 Chargement de test...
✅ test: 19998 exemples

Les données sont au nombre de: 185445 et réparties en :

Train: 145449
Validation: 19998
Test: 19998
```
### Répartition des Splits


| Split | Exemples | Source |
|----------------|--------|----------|
| Train	| 145,449 | [Train](fever.ai/download/fever/train.jsonl) |
| Validation | 19,998| [Validation](fever.ai/download/fever/shared_task_dev.jsonl) |
| Test | 19,998 | [Test](fever.ai/download/fever/shared_task_test.jsonl)|

### Longueur des Claims
```
python
# Longueur des claims
claim_lengths = [len(claim.split()) for claim in data['claim']]
print(f"\n📝 Longueur des claims:")
print(f"  Moyenne : {np.mean(claim_lengths):.1f} mots")
print(f"  Min     : {np.min(claim_lengths)} mots")
print(f"  Max     : {np.max(claim_lengths)} mots")
```

#### Output:

```
text
📝 Longueur des claims:
  Moyenne : 8.1 mots
  Min     : 2 mots
  Max     : 65 mots
```
## 🧹 7. Prétraitement

### Pipeline de prétraitement complet
```
python
from sklearn.preprocessing import LabelEncoder

def preprocess_fever_complete(data, validation_data):
    """
    Prétraite les données FEVER pour l'entraînement et la validation
    """
    def filter_valid_labels(dataset):
        valid_labels = ['SUPPORTS', 'REFUTES', 'NOT ENOUGH INFO']
        return dataset.filter(lambda x: x['label'] in valid_labels)
    
    # Filtrage des données
    train_filtered = filter_valid_labels(data)
    val_filtered = filter_valid_labels(validation_data)
    
    # Encodage des labels
    le = LabelEncoder()
    
    # Extraction des claims et labels
    def clean_claim(claim):
        # Conversion en minuscule
        claim = claim.lower()
        # Suppression de la ponctuation
        claim = re.sub(r'[^\w\s]', '', claim)
        return claim
    
    X_train = [clean_claim(x['claim']) for x in train_filtered]
    y_train = [x['label'] for x in train_filtered]
    
    X_val = [clean_claim(x['claim']) for x in val_filtered]
    y_val = [x['label'] for x in val_filtered]
    
    # Encoder les labels
    le.fit(y_train)
    y_train_encoded = le.transform(y_train)
    y_val_encoded = le.transform(y_val)
    
    return X_train, y_train_encoded, X_val, y_val_encoded, le

# Utilisation
X_train, y_train, X_val, y_val, le = preprocess_fever_complete(train_data, validation_data)

print(f"Train: {len(X_train)} exemples")
print(f"Validation: {len(X_val)} exemples")
print(f"Classes: {le.classes_}")
```

#### Output:

```
text
Train: 145449 exemples
Validation: 19998 exemples
Classes: ['NOT ENOUGH INFO' 'REFUTES' 'SUPPORTS']
```

## 🤖 8. Modèle Baseline

### Logistic Regression avec TF-IDF

```
python
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report

# 1. Vectorisation
vectorizer = TfidfVectorizer(
    max_features=10000,
    stop_words='english',
    ngram_range=(1, 2)  # Unigrammes et bigrammes
)
X_train_vec = vectorizer.fit_transform(X_train)
X_val_vec = vectorizer.transform(X_val)

# 2. Entraînement
log = LogisticRegression(max_iter=1000, random_state=42)
log.fit(X_train_vec, y_train)

# 3. Évaluation
y_pred = log.predict(X_val_vec)
print(classification_report(
    y_val, y_pred,
    target_names=le.classes_
))
```

#### Output:

```
text
                 precision    recall  f1-score   support

NOT ENOUGH INFO       0.49      0.21      0.29      6666
        REFUTES       0.67      0.26      0.37      6666
       SUPPORTS       0.39      0.86      0.54      6666

       accuracy                           0.44     19998
      macro avg       0.52      0.44      0.40     19998
   weighted avg       0.52      0.44      0.40     19998
```

## 📝 9. Guide d'Utilisation Complet

### Étape 1: Installation
```
bash
pip install requests datasets scikit-learn matplotlib numpy
```
### Étape 2: Chargement et Exploration
```
python
import requests
import json
from datasets import Dataset
import matplotlib.pyplot as plt
from collections import Counter

# Chargement des données
data = load_fever_batch()

# Exploration de la distribution
labels = data['label']
label_counts = Counter(labels)
```
### Étape 3: Prétraitement
```
python
from sklearn.preprocessing import LabelEncoder
import re

def clean_data(dataset):
    valid_labels = ['SUPPORTS', 'REFUTES', 'NOT ENOUGH INFO']
    filtered = dataset.filter(lambda x: x['label'] in valid_labels)
    
    def clean_claim(claim):
        claim = claim.lower()
        claim = re.sub(r'[^\w\s]', '', claim)
        return claim
    
    X = [clean_claim(x['claim']) for x in filtered]
    y = [x['label'] for x in filtered]
    
    le = LabelEncoder()
    y_enc = le.fit_transform(y)
    
    return X, y_enc, le
```
### Étape 4: Entraînement du Modèle
```
python
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

# Vectorisation
vectorizer = TfidfVectorizer(max_features=10000, stop_words='english')
X_vec = vectorizer.fit_transform(X_train)

# Entraînement
model = LogisticRegression(max_iter=1000, random_state=42)
model.fit(X_vec, y_train)
Étape 5: Évaluation
python
from sklearn.metrics import classification_report

X_val_vec = vectorizer.transform(X_val)
y_pred = model.predict(X_val_vec)

print(classification_report(y_val, y_pred, target_names=le.classes_))
```

## 🔍 10. Analyse et Insights

### Forces du Dataset
- Benchmark standard pour la vérification des faits

- Transparence - nécessite des preuves, pas juste une classification

- Défi combiné - compréhension du langage et raisonnement

- Application réelle - lutte contre la désinformation

### Défis
- Déséquilibre des classes - SUPPORTS domine (55%)

- Ambiguïté NEI - NOT ENOUGH INFO peut être subjectif

- Raisonnement requis - La simple correspondance de mots-clés est insuffisante

## 📦 11. Dépendances Complètes

``` txt
# requirements.txt
requests==2.31.0
datasets==2.14.0
scikit-learn==1.3.0
matplotlib==3.7.0
numpy==1.24.0
```
## 🌐 12. Ressources

Site Officiel: [Cliquez ici pour voir la documentation](https://huggingface.co/datasets/fever/fever)

Telechargement des datasets : 
- [train](https://fever.ai/download/fever/train.jsonl)
- [validation](https://fever.ai/download/fever/shared_task_dev.jsonl)
- [test](https://fever.ai/download/fever/shared_task_test.jsonl)

Code Source: [GitHub](https://github.com/le-cercle-du-neurone-disparu/berlue/blob/datafever/notebooks/api_usage.ipynb)

## 🔄 13. Flux de Travail Recommandé
graph TD
    A[Charger les données] --> B[Explorer les données]
    B --> C[Prétraiter les claims]
    C --> D[Vectorisation TF-IDF]
    D --> E[Entraîner le modèle]
    E --> F[Évaluer sur validation]
    F --> G[Optimiser les hyperparamètres]
    G --> H[Tester sur test set]










