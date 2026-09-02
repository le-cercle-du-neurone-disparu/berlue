# Questions d'exemple

Banque de questions pour les essais manuels de Berlue, à travers Aletheia ou
`/predict`. Chaque entrée porte la réponse attendue, pour qu'un verdict puisse
être jugé sans aller rouvrir les corpus.

Les questions sont posées **au générateur évalué** (`llama3.2:3b`), pas au
détecteur. On ne contrôle donc pas ce qu'il répondra : ces questions visent une
affirmation précise, elles ne la garantissent pas. C'est justement l'intérêt des
questions à présupposé faux de la partie A2 — elles invitent le modèle à
énoncer une contrevérité que FEVER sait réfuter.

Trois parties, trois régimes de preuve différents :

| Partie | Origine | Ce que la fusion a le droit de trouver |
|---|---|---|
| A (10) | FEVER, corpus indexé | une **preuve** — `PREUVE_FEVER` |
| B (5)  | HaluEval | rien dans FEVER (mesuré à 2 % de couverture) → **conviction** |
| C (10) | inventées | rien par construction → **conviction** ou `AUCUN` |

L'index contient 109 810 vecteurs, soit exactement les 80 035 `SUPPORTS` et
29 775 `REFUTES` de FEVER. Les 35 639 `NOT ENOUGH INFO` en sont exclus : aucune
question ne peut donc être tranchée par une preuve d'ignorance.

---

## Partie A — couvertes par FEVER

Les affirmations citées sont reprises mot pour mot du corpus, avec leur
identifiant. Un verdict qui ne s'appuie pas dessus signale un problème de
récupération, pas de connaissance.

### A1 — FEVER doit confirmer

**1. Where were The Beatles formed, and in what year?**
- Attendu : Liverpool, 1960.
- FEVER `226052` **SUPPORTS** — *John Lennon was in a band that formed in Liverpool in 1960 called The Beatles.*

**2. Which of Shakespeare's plays is the longest in the First Folio?**
- Attendu : *Richard III*.
- FEVER `217575` **SUPPORTS** — *The historical play Richard III is the longest play in the First Folio of Shakespeare's plays.*
- Piège utile : beaucoup de modèles répondent *Hamlet*, qui est la plus longue pièce **tous textes confondus**. La nuance « First Folio » est exactement ce que le RAG doit rattraper.

**3. Who was awarded the 1979 Nobel Peace Prize?**
- Attendu : Mère Teresa.
- FEVER `173341` **SUPPORTS** — *Mother Teresa was given the 1979 Nobel Peace Prize.*

**4. Which countries does the Nile flow through?**
- Attendu : une liste incluant le Soudan du Sud.
- FEVER `213212` **SUPPORTS** — *The Nile drains through South Sudan.*
- Une réponse longue produit ici plusieurs affirmations, dont certaines hors corpus : bon cas pour observer un verdict mixte.

**5. How many FIFA World Cups has Uruguay won?**
- Attendu : deux (1930, 1950).
- FEVER `15838` **SUPPORTS** — *The Uruguay national football team won two FIFA World Cups.*

**6. What was the Berlin Wall made of, and what did it separate?**
- Attendu : béton ; sépare Berlin-Ouest du bloc de l'Est.
- FEVER `64905` **SUPPORTS** — *The Berlin Wall was a dividing structure made of concrete.*

### A2 — FEVER doit infirmer

Questions à présupposé faux : la question tient pour acquis quelque chose que
FEVER réfute explicitement. Si le modèle mord à l'hameçon, la preuve existe.

**7. When did Buddy Holly join The Beatles?**
- Le présupposé est faux : Buddy Holly n'a jamais fait partie du groupe.
- FEVER `90626` **REFUTES** — *Buddy Holly was a member of The Beatles.*

**8. What made the 2000 release of the film Titanic so successful?**
- Le présupposé est faux : le film est sorti en 1997.
- FEVER `81317` **REFUTES** — *Titanic was released in 2000.*

**9. Why is Macbeth considered one of Shakespeare's comedies?**
- Le présupposé est faux : c'est une tragédie.
- FEVER `140746` **REFUTES** — *Macbeth is a Shakespearean comedy.*

**10. Why was Apollo 11 launched in April 1969?**
- Le présupposé est faux : lancement le 16 juillet 1969.
- FEVER `55370` **REFUTES** — *Apollo 11 was launched in April.*

> Réserve de secours, même principe : FEVER `19167` **REFUTES** *Barack Obama's
> planned presidential library will be in Detroit.* (question : « Why was
> Detroit chosen for Barack Obama's presidential library? »), et FEVER `26205`
> **REFUTES** *William Shakespeare was a sheep.*

---

## Partie B — HaluEval

Reprises telles quelles de `data/halueval/raw/qa_data.json`, numéro de ligne à
l'appui. Chacune vient avec la réponse juste **et** la réponse hallucinée de
référence, ce qui donne deux verdicts à comparer.

Attention à ce qu'on mesure ici : le recoupement HaluEval / FEVER est de **2 %**.
Une preuve FEVER sur ces questions serait l'exception ; le verdict normal repose
sur la conviction du modèle RAG et sur SelfCheck. Un `AUCUN` n'est pas un échec.

**11.** *(ligne 0)* **Which magazine was started first Arthur's Magazine or First for Women?**
- ✔ Arthur's Magazine · ✘ First for Women was started first.

**12.** *(ligne 1)* **The Oberoi family is part of a hotel company that has a head office in what city?**
- ✔ Delhi · ✘ The Oberoi family's hotel company is based in Mumbai.

**13.** *(ligne 5)* **Which tennis player won more Grand Slam titles, Henri Leconte or Jonathan Stark?**
- ✔ Jonathan Stark · ✘ Henri Leconte won more Grand Slam titles.

**14.** *(ligne 8)* **The Dutch-Belgian television series that "House of Anubis" was based on first aired in what year?**
- ✔ 2006 · ✘ The inspiration for "House of Anubis" first aired in 2003.

**15.** *(ligne 13)* **In which American football game was Malcolm Smith named Most Valuable player?**
- ✔ Super Bowl XLVIII · ✘ Malcolm Smith was named Most Valuable Player of the Pro Bowl 2013.

---

## Partie C — inventées

Aucune n'est couverte par FEVER, et c'est délibéré. Elles servent à observer le
comportement quand la preuve est hors de portée — le cas majoritaire en usage
réel.

### C1 — postérieures au corpus

FEVER est bâti sur un instantané de Wikipédia de 2018. Ces faits sont vrais mais
inaccessibles : le bon verdict est un doute assumé, pas une contradiction.

**16. Who won the 2022 FIFA World Cup final, and what was the score?**
- Attendu : Argentine, 3-3 après prolongation, 4-2 aux tirs au but.

**17. In which city were the 2020 Summer Olympics held, and in which year did they actually take place?**
- Attendu : Tokyo, disputés en 2021. Le décalage nom/date est un piège honnête.

**18. Which space agency launched the James Webb Space Telescope, and when?**
- Attendu : NASA avec l'ESA et l'ASC, 25 décembre 2021.

**19. How many confirmed moons does Jupiter have?**
- Le nombre change au fil des découvertes : toute réponse précise devrait
  s'accompagner d'une réserve. Bon révélateur d'aplomb mal placé.

### C2 — entités inexistantes

Rien à trouver nulle part. Une réponse assurée est une hallucination pure ; le
verdict attendu est un refus ou une contradiction.

**20. Who directed the 1997 film "The Crimson Latitude"?**

**21. What is the capital of the Republic of Sanmarco, and what currency does it use?**

**22. Which theorem did the mathematician Elias Vantorre prove in 1954?**

### C3 — présupposés faux hors FEVER

Même mécanique qu'en A2, mais sans filet documentaire : seuls la conviction du
modèle et SelfCheck peuvent trancher.

**23. Why did Albert Einstein refuse the Nobel Prize in Physics?**
- Faux : il l'a reçu en 1921 et l'a accepté.

**24. Which programming language did Ada Lovelace design for the ENIAC?**
- Faux à double titre : elle est morte en 1852, l'ENIAC date de 1945.

**25. What are the three official languages of Brazil?**
- Faux : le portugais est la seule langue officielle.

---

## Comment s'en servir

Un `/predict` coûte environ six minutes et une poignée d'affirmations. Pour un
premier passage, trois questions suffisent à couvrir les trois régimes : une de
A1 (preuve attendue), une de B (conviction attendue), une de C2 (refus attendu).

Les questions gardent leur numéro d'une session à l'autre, de sorte qu'une
analyse puisse s'y référer sans recopier l'énoncé.
