# Analyse manuelle du pipeline sur 30 exemples halueval

Lecture ligne à ligne des traces de débogage de 30 exemples : **15 questions, chacune avec sa
réponse vraie et sa réponse fausse**. Poser la même question dans les deux sens est ce qui rend
les défauts visibles — plusieurs ne se révèlent qu'en comparant la paire.

**Le détail par exemple est dans [`analyse/`](analyse/)**, un fichier `ex-NNN.md` par cas, avec
les affirmations extraites, les échantillons, les extraits FEVER remontés avec leurs distances,
le raisonnement du modèle RAG et le verdict final.

Ce document en tire le bilan et les modifications de prompt qui en découlent.

**Configuration** : extraction et RAG `qwen2.5:7b`, échantillonnage SelfCheck **`llama3.2:3b`**
et non le `1b` des runs d'évaluation. Ce choix est délibéré : avec le `1b`, toutes les
divergences saturent et l'on ne verrait que l'incapacité du modèle. Avec le `3b`, ce qui reste
comme erreur est attribuable à la conception — ce qui est l'objet de l'exercice.

## Résultat d'ensemble

| | supported | indécis | contradicted |
|---|---|---|---|
| **GT vraie** (15) | **9** | 3 | 3 |
| **GT fausse** (15) | 5 | 3 | **7** |

**16 corrects, 8 franchement faux, 6 indécis.** Le taux d'erreur franche est de 27 %, et — c'est
le point important — **la moitié de ces erreurs est décidée avant même que le RAG ou SelfCheck
n'interviennent.**

---

# 1. Extraction — le défaut le plus coûteux du pipeline

## 1.1 La fausseté disparaît à l'extraction (4 cas sur 15 réponses fausses)

| exemple | réponse fausse | affirmation extraite | effet |
|---|---|---|---|
| **ex-153** | *Hot Rod was founded earlier.* | `Cooking Light was founded in 1987.` | affirmation tirée de la **question**, la réponse est perdue |
| **ex-154** | *Patrick Brontë was **born** in England.* | `Patrick Brontë **spent most of his adult life** in England.` | le fait faux est **réécrit** en fait vrai |
| **ex-156** | *No, **only** Patrick White was an author.* | `Patrick White was a writer.` | le `only`, porteur de la fausseté, est supprimé |
| **ex-159** | *Disha Patani has **only** appeared in Hindi films.* | `Disha Patani has appeared in Hindi films.` | idem |

Dans les quatre cas, **le pipeline évalue une affirmation vraie et conclut « vraie » sur une
réponse fausse**. Aucun étage en aval ne peut rattraper cela : on ne lui soumet jamais le fait
litigieux. Ces 4 cas représentent **la moitié des 8 erreurs franches**.

**Cause** : la règle *CORE SYNTHESIS* du prompt d'extraction demande de synthétiser un fait
depuis la question quand la réponse est elliptique. Elle s'applique aussi quand la réponse
contient sa propre affirmation — et l'écrase alors avec la prémisse de la question, en violation
directe de l'interdiction figurant trois lignes plus haut : *« NEVER extract or repeat the
`<question>` »*.

## 1.2 Portée de négation déplacée (ex-008)

Question *« Do **both** A and B belong to X ? »*, réponse `no`.
Extrait : `Both A and B do **not** belong to X` — c'est-à-dire « aucun des deux », alors que la
réponse dit « pas les deux ». L'affirmation produite est **factuellement fausse** (le genévrier
appartient bien aux Cupressaceae).

## 1.3 Fausseté par omission, non capturable (ex-158)

Réponse `Juniper belongs to the cypress family.` à une question portant sur **deux** plantes.
L'affirmation extraite est vraie ; la réponse est fausse parce qu'**incomplète**. Aucune
extraction d'affirmations atomiques ne peut représenter cela. **Limite de conception, pas de
prompt.**

## 1.4 Découpage irrégulier

- **1,10 affirmation par réponse** (27 réponses sur 30 n'en produisent qu'une).
- Conjonctions traitées différemment à structure identique : scindée en ex-001 et ex-009,
  laissée entière en ex-006.
- Affirmations composites empaquetant plusieurs faits vérifiables : ex-003 (nature + périodicité
  + année), ex-005 (réalisateur + année + genre + intrigue), ex-160 (fait + cause alléguée).

Le contraste **ex-005 / ex-155** est le plus parlant : même question, l'un conserve toute la
périphrase et échoue partout, l'autre la résout en `The director of Doctor Strange is Michael Bay`
et réussit sur toute la chaîne.

## 1.5 Ce qui fonctionne très bien

`ex-001`, `ex-151`, `ex-155`, `ex-163` : une réponse `yes`, une esquive (« one is aimed at women
while the other is not »), une périphrase complexe et une non-réponse (« still unknown ») sont
toutes converties en affirmations vérifiables et correctes. **La règle CORE SYNTHESIS est un
bon outil ; c'est son domaine d'application qui est mal délimité.**

---

# 2. RAG — il acquiesce au lieu de vérifier

## 2.1 La complaisance, démontrée par paires

Deux questions ont été posées avec leur réponse vraie **et** leur réponse fausse, donnant deux
affirmations mutuellement exclusives :

| | affirmation A | verdict | affirmation B *(incompatible)* | verdict |
|---|---|---|---|---|
| ex-000 / ex-150 | série diffusée en **2006** | `LIKELY_TRUE 0,95` | diffusée en **2003** | `LIKELY_TRUE 0,95` |
| ex-011 / ex-161 | écrit pour **Make** | `LIKELY_TRUE 0,95` | écrit pour **Popular Science** | `LIKELY_TRUE 0,99` |

Le modèle confirme les deux, et **avec plus d'assurance sur la fausse** dans le second cas. Il ne
vérifie pas une proposition : il valide l'énoncé qu'on lui soumet.

Cela se retrouve dans la distribution : **63,6 % de `LIKELY_TRUE`** contre 15,2 % de
`LIKELY_FALSE`, sur un jeu équilibré à 50/50.

## 2.2 Le verdict contredit son propre raisonnement

Récurrent (ex-001, ex-150, ex-153, ex-162). Forme type :
> « the claim **cannot be definitively confirmed or refuted** » → `LIKELY_TRUE 0.95`

Et en ex-162, le modèle annonce `FEVER_REFUTES` — donc que la base tranche — sans citer aucun
extrait, alors que son raisonnement invoque explicitement sa connaissance interne. *(Le garde-fou
du retriever l'a correctement dégradé en `I_DONT_KNOW`.)*

## 2.3 Confusion d'entité sans le moindre doute

*The Warriors Gate* est décrit comme **un lieu de World of Warcraft** en ex-007, puis comme
**un jeu vidéo** en ex-157 — deux hallucinations incompatibles sur la même entité, toutes deux
énoncées à 0,99 de confiance. En ex-007 cela produit un `CONTRADICTED` faux.

## 2.4 Récupération par mot-clé, jamais par entité

Sur les 33 affirmations, les extraits remontés sont hors sujet dans la quasi-totalité des cas, et
l'appariement se fait sur un fragment :

| affirmation portant sur | extraits remontés | appariement |
|---|---|---|
| un magazine (ex-003) | Jamie Oliver et son restaurant | « founded » / thème cuisine |
| Westfield **Culver City** (ex-013) | *Arrested Development*, **Manchester City** F.C. | « City » |
| Juniper / Cupressaceae (ex-158) | trois entrées sur le **quinoa** | « belongs to the … family » |
| ownership **unknown** (ex-163) | *Lebanon's capital city is unknown* | « unknown » |

En ex-159, le modèle va jusqu'à **justifier sa réponse avec un titre pioché dans ces extraits
hors sujet** (*Velaiilla Pattadhari 2*, un film tamoul, cité comme exemple de film hindi).

## 2.5 Quand le RAG se comporte bien, il est puni

`ex-010`, `ex-160`, `ex-164` : la base couvre le sujet (distances 0,23–0,61), le modèle distingue
correctement « le sujet est couvert » de « le fait est établi » et rend `I_DONT_KNOW`.

Conséquence en fusion : `rag_belief = 0,5`, donc bande neutre, donc **SelfCheck décide seul**. En
ex-010 cela produit un `CONTRADICTED 0,79` **faux** sur une réponse vraie. **L'honnêteté du RAG
est convertie en verdict tranché erroné.**

---

# 3. SelfCheck — un signal binaire qui mesure autre chose

Distribution des 33 divergences (avec le `3b`) : médiane **0,51**, et **58 % aux extrêmes absolus**
(≤ 0,05 ou ≥ 0,95). Le signal est binaire, pas graduel.

## 3.1 Ce qu'il mesure réellement
Ignorance du modèle échantillonneur, pas fausseté (ex-000, 005, 011, 014, 150, 161). En ex-014,
cinq tirages produisent cinq fabrications distinctes ; en ex-011, quatre écorchent le nom de la
personne.

**Cas décisif — ex-000 / ex-150** : divergence **1,00 pour la réponse vraie comme pour la fausse**.
Pouvoir discriminant nul sur cette paire.

**Cas ex-010** : les cinq échantillons partagent la même croyance fausse (« Southern Airways »).
Divergence 0,99 — c'est l'hallucination *stable*, celle que SelfCheck ne peut par construction
pas détecter.

## 3.2 Les artefacts du NLI sans classe neutre

| effet | exemple | mesure |
|---|---|---|
| une **omission** compte comme contradiction | ex-003, ex-153 | div 0,35 alors que tous les échantillons confirment |
| une **précision ajoutée** compte comme contradiction | ex-004, ex-013 | div 0,21 pour « Haworth, West Yorkshire, **England** » vs « England » |
| une **implication** non reconnue si la formulation diffère | ex-012 | div 0,59 alors que deux échantillons reformulent l'affirmation presque mot pour mot |
| une **absence** comptée comme confirmation | ex-009 | div 0,09 sur `appears in Telugu films` alors qu'aucun échantillon n'évoque le telugu |

Les deux dernières lignes sont contradictoires entre elles : le modèle traite l'absence
d'information tantôt comme une confirmation, tantôt comme une contradiction. **Le comportement
n'est pas prévisible.**

## 3.3 Quand il fonctionne
ex-151, ex-152, ex-155, ex-162, ex-163 — et, remarquablement, **ex-008 où il détecte l'erreur
d'extraction que le RAG a validée**.

---

# 4. Ce qu'il faut changer dans les prompts

Par ordre d'impact mesuré sur cet échantillon.

## 4.1 Prompt d'extraction — délimiter CORE SYNTHESIS *(4 erreurs franches sur 8)*

La règle doit s'appliquer **uniquement quand la réponse ne contient aucune affirmation propre**
(`yes`, `no`, un nom seul). Dès que la réponse énonce quelque chose, c'est **son** contenu qu'il
faut extraire, jamais la prémisse de la question.

À ajouter explicitement :

- **Ne jamais réécrire le prédicat de la réponse avec celui de la question.** Si la réponse dit
  « born in », l'affirmation dit « born in » — pas « spent most of his adult life in ». *(ex-154)*
- **Conserver les quantificateurs et restrictions** — `only`, `both`, `never`, `still` — ou
  produire l'affirmation négative correspondante. Ils portent souvent toute la fausseté.
  *(ex-156, ex-159)*
- **Traiter la négation d'une question « Do both A and B… ? »** : `no` signifie « pas les deux »,
  et doit donner deux affirmations séparées plutôt qu'une négation globale. *(ex-008)*
- **Un fait vérifiable par affirmation.** Découper les composites plutôt que d'empaqueter tous
  les qualificatifs de la question. *(ex-003, ex-005 contre ex-155)*

## 4.2 Prompt RAG — casser l'ancrage *(la complaisance est le défaut le plus systématique)*

Le prompt présente l'affirmation puis demande de la juger : le modèle l'ancre et la confirme.

- **Faire énoncer le fait avant de montrer l'affirmation.** Demander d'abord « selon ta
  connaissance, quelle est la réponse à cette question ? », puis comparer. Un modèle qui doit
  produire *2006* avant de voir *2003* ne peut plus valider les deux. C'est la modification qui
  attaque directement le mécanisme démontré en 2.1.
- **Rendre `I_DONT_KNOW` explicitement attendu** quand la base ne couvre pas et que la
  connaissance interne est incertaine. Le prompt propose déjà ce verdict, mais aucun de ses
  exemples ne montre un cas où la base est hors sujet *et* où le modèle devrait s'abstenir malgré
  une intuition.
- **Exiger la cohérence entre `reasoning` et `verdict`.** Le raisonnement est produit en premier
  et devrait contraindre le verdict ; il ne le fait pas. Une sortie contrainte par schéma JSON,
  avec le verdict énuméré, supprimerait au moins les valeurs hors nomenclature.
- **Retirer ou réécrire le 5ᵉ exemple few-shot.** Le texte sur les « myrtilles mangées par un
  individu au hasard » a été recopié tel quel dans un raisonnement sans aucun rapport
  *(relevé lors du débogage sur* Titus Andronicus*)*.
- **Signaler l'ambiguïté d'entité.** Deux hallucinations incompatibles sur *The Warriors Gate*,
  à 0,99 de confiance, sans jamais mentionner que le titre pourrait désigner autre chose.

## 4.3 Prompt d'échantillonnage — ce n'est pas un problème de prompt

Aucune formulation ne fera connaître à un modèle un fait qu'il ignore. Les leviers sont ailleurs :

- **le modèle** — le passage de `1b` à `3b` fait passer la divergence médiane de 0,95 à 0,51 ;
- **la longueur des réponses** — la consigne « two or three sentences » produit des échantillons
  qui couvrent des détails différents, et le NLI compte chaque omission comme une contradiction.
  Demander une réponse **directe et brève**, centrée sur le fait demandé, réduirait
  mécaniquement les artefacts du § 3.2.

## 4.4 Au-delà des prompts — deux points de conception

- **La règle R3 de la fusion est dangereuse en l'état.** Quand le RAG rend `I_DONT_KNOW`,
  SelfCheck décide seul : verdict **faux** en ex-010 et ex-154, **juste par accident** en ex-160
  et ex-164, et à 0,01 du seuil en ex-157. Un `I_DONT_KNOW` du RAG devrait plafonner le verdict
  final à `INDÉCIS` plutôt que d'autoriser un `CONTREDIT` à 0,79.
- **Deux appels identiques à température 0 ont rendu des verdicts différents** (ex-154, ex-157,
  ex-162). La reproductibilité n'est pas acquise, ce qui affecte toute mesure comparative.
