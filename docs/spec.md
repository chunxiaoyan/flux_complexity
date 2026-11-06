# flux_complexity — spécification du calcul (v0.6)

Ce document définit **précisément** chaque indicateur. Le code, les tests et l'affichage des pages suivent
ce document ; toute modification des règles de calcul commence par une modification de ce document.

**La version 1 ne porte que sur le flux et ne calcule que deux indicateurs : la taille et le poids du
flux.** La distance de dépendance (DD) et sa moyenne (MDD) ne sont pas calculées.

---

## 1. Entrées

| Source | Format | Schéma | Usage |
|---|---|---|---|
| Texte saisi par l'utilisateur | texte brut → analyse Stanza → CoNLL-U | toujours UD | page « Analyser un texte » |
| Fichier envoyé par l'utilisateur | `.conllu` | UD ou SUD, indiqué par l'utilisateur | page « Analyser un texte » (entrée secondaire) / page « Corpus et expériences » |
| Corpus de référence | `.conllu` (versions officielles UD / SUD) | UD ou SUD | calcul des normes |

- Chaque corpus a un `schéma ∈ {UD, SUD}`. Le schéma détermine : ① les transformations de prétraitement
  disponibles ; ② les normes avec lesquelles on compare.
- Un texte saisi est comparé uniquement à une **norme UD**. Un fichier SUD est comparé à une norme SUD.

## 2. Unité de base : le mot syntaxique

- Le calcul porte sur les **mots syntaxiques** (lignes CoNLL-U dont l'ID est un entier).
- **Mots composés** (MWT, ID de la forme `3-4`, par ex. *du* = *de* + *le*) : ils n'interviennent pas dans le
  calcul ; ils servent seulement, à l'affichage, à rattacher les mots syntaxiques à la forme de surface.
- **Nœuds vides** (ID de la forme `8.1`, dépendances enrichies) : ignorés.
- Seules les colonnes HEAD et DEPREL (dépendances de base) sont utilisées ; la colonne DEPS est ignorée.

## 3. Prétraitement (chaîne de transformations appliquées dans l'ordre)

Le prétraitement est une chaîne de transformations interchangeables. Chaque transformation indique les
schémas auxquels elle s'applique. Chaîne par défaut de la version 1 :

| Ordre | Transformation | Schémas | État en v1 |
|---|---|---|---|
| 1 | retrait de la ponctuation | UD, SUD | ✅ toujours active |
| 2 | coupure de `parataxis` | UD, SUD | ✅ active par défaut |
| 3 | retrait des mots grammaticaux | **UD seulement** | ⏸ interface prévue, non implémentée ; désactivée pour les corpus SUD |

### 3.1 Retrait de la ponctuation
- **Critère** : `UPOS == PUNCT`.
- **Ponctuation ayant des dépendants** (le plus souvent une erreur d'analyse) : ces dépendants sont
  rattachés au gouverneur de la ponctuation (si ce gouverneur est lui-même une ponctuation, on remonte
  jusqu'à un mot qui n'en est pas une, ou jusqu'à la racine), et un avertissement est enregistré (ID de
  la phrase et mots concernés). **La phrase n'est pas écartée.**
- Après le retrait, les mots syntaxiques restants sont **renumérotés** de 1 à n, et la correspondance
  « nouveau numéro ↔ numéro d'origine » est conservée.
- Toutes les positions de flux sont ensuite définies sur les **nouveaux numéros** (la ponctuation n'occupe
  aucune position).
- À l'affichage, les numéros d'origine permettent de replacer les résultats dans la phrase d'origine ;
  la ponctuation est affichée normalement.

### 3.2 Coupure de `parataxis`
- **Règle par défaut** : toute dépendance dont la relation est **exactement `parataxis`** est retirée et ne
  compte dans aucun flux ; **les sous-types comme `parataxis:insert` sont conservés** et comptent
  normalement.
- Le dépendant de la relation coupée reste dans la phrase ; l'ordre et la numérotation des mots ne
  changent pas.
- Origine : c'est le comportement de l'ancienne fonction `update_parataxis_gov`. Son code source est perdu,
  mais cette règle reproduit exactement, ligne par ligne, les 8 fichiers `experimental_data_*.xlsx` de la
  thèse (tests de non-régression). Cette règle a été retenue comme valeur par défaut.
- Deux autres modes sont proposés pour comparer (option `--parataxis` de la ligne de commande) :
  - `exact` (**par défaut**) : on coupe seulement `parataxis` sans sous-type ;
  - `all` : on coupe `parataxis` et tous ses sous-types ;
  - `keep` : on ne coupe rien.

## 4. Dépendances prises en compte dans le flux

- Une dépendance est un couple (gouverneur g, dépendant d), où g et d sont les numéros après retrait de la
  ponctuation.
- Elle **exclut** l'arc de la racine (HEAD = 0) et les relations `parataxis` coupées.
- Pour chaque dépendance, on enregistre aussi la relation (DEPREL) et le sens (g à gauche ou à droite de d) :
  ils servent aux recherches par relation et à l'affichage du contenu du flux sur la page « Corpus et
  expériences », **mais n'entrent pas dans le calcul des indicateurs.**

## 5. Le flux : taille et poids

- **Position i** (1 ≤ i ≤ n−1) : l'espace entre les mots syntaxiques i et i+1.
- **flux(i)** = l'ensemble des dépendances telles que `min(g,d) ≤ i < max(g,d)`.
- **Flux vide** : si flux(i) est vide, la position **n'est pas enregistrée** et n'entre dans aucune moyenne
  ni aucune distribution. (Cela n'arrive qu'après une coupure de `parataxis` ou s'il y a plusieurs racines.)
- **taille(i) = |flux(i)|**.
- **poids(i)** = le plus grand nombre de dépendances de flux(i) qui **ne partagent deux à deux aucune
  extrémité**.
  - Calcul : **couplage maximum** dans le graphe biparti entre l'ensemble des extrémités gauches et celui des
    extrémités droites. (Dans flux(i), un mot ne peut pas être à la fois extrémité gauche et extrémité
    droite ; « ne partager aucune extrémité » revient donc à un couplage dans ce graphe biparti.)
  - Sur les arbres, la méthode d'élimination des feuilles de l'ancien code donne exactement le même
    résultat que le couplage maximum (vérifié sur 14 fichiers de corpus) ; le nouveau code utilise
    directement le couplage maximum, qui est correct pour toute entrée.
- **Résumé par phrase** : taille maximale, taille moyenne, poids maximal, poids moyen (moyennes calculées sur
  les positions non vides seulement).
- **Résumé par corpus** : distribution des deux indicateurs sur toutes les positions de flux non vides
  (moyenne, écart type, effectif de chaque valeur).

## 6. Exemples calculés à la main (qui servent aussi de tests unitaires)

Les chiffres ci-dessous ont été vérifiés par un script indépendant.

### Exemple 1 : cas de base
`Le chat de ma sœur dort .`

| ID | Mot | UPOS | HEAD | DEPREL |
|---|---|---|---|---|
| 1 | Le | DET | 2 | det |
| 2 | chat | NOUN | 6 | nsubj |
| 3 | de | ADP | 5 | case |
| 4 | ma | DET | 5 | det |
| 5 | sœur | NOUN | 2 | nmod |
| 6 | dort | VERB | 0 | root |
| 7 | . | PUNCT | 6 | punct |

Après retrait de la ponctuation, n = 6 : il y a 5 positions.

| Position | Entre | Flux | Taille | Poids |
|---|---|---|---|---|
| 1 | Le \| chat | (1,2) | 1 | 1 |
| 2 | chat \| de | (2,6) (2,5) | 2 | 1 |
| 3 | de \| ma | (2,6) (2,5) (3,5) | 3 | **2** |
| 4 | ma \| sœur | (2,6) (2,5) (3,5) (4,5) | 4 | **2** |
| 5 | sœur \| dort | (2,6) | 1 | 1 |

Phrase : taille maximale = 4, taille moyenne = 11/5 = 2,2 ; poids maximal = 2, poids moyen = 7/5 = 1,4.

### Exemple 2 : coupure de `parataxis` et flux vide
`Il pleut , je reste .` (*reste* —parataxis→ *pleut*)

Après retrait de la ponctuation : Il(1) pleut(2) je(3) reste(4). La relation `parataxis` est coupée.

| Position | Entre | Taille | Poids |
|---|---|---|---|
| 1 | Il \| pleut | 1 | 1 |
| 2 | pleut \| je | — | **flux vide, exclu** |
| 3 | je \| reste | 1 | 1 |

Phrase : les moyennes portent seulement sur les positions 1 et 3 ; taille moyenne = poids moyen = 1,0.

### Exemple 3 : ponctuation ayant un dépendant (erreur d'analyse)
`Il dit : « non »`, où *non* est rattaché par erreur à `:`.

→ Avertissement : « le gouverneur de non est la ponctuation :, rattaché à dit ». Après retrait de la
ponctuation : Il(1) dit(2) non(3) ; aux positions 1 et 2, taille = poids = 1.

## 7. Normes (distributions de référence)

- **Corpus** : trois treebanks du français, chacun en version UD et en version SUD, tous de la même
  version, dont le numéro est inscrit dans le fichier de norme :

  | Treebank | Type | UD | SUD |
  |---|---|---|---|
  | French-Sequoia | écrit (plusieurs domaines) | UD_French-Sequoia | SUD_French-Sequoia |
  | French-ParisStories | oral (récits) | UD_French-ParisStories | SUD_French-ParisStories |
  | French-Rhapsodie | oral (plusieurs genres) | UD_French-Rhapsodie | SUD_French-Rhapsodie |

- Un fichier JSON par couple (schéma, treebank), plus, pour chaque schéma, une norme qui réunit les trois
  treebanks : 8 fichiers en tout. Chaque fichier contient :
  - pour la **taille** et le **poids** (valeurs entières) : l'effectif de chaque valeur k et la proportion
    `P(X ≥ k)`, pour k = 1..max ;
  - des métadonnées : nom du corpus, version, nombre de phrases, nombre de positions de flux non vides,
    chaîne de prétraitement, date de création, version du code.
- L'outil ne contient que les fichiers JSON des normes, pas les corpus eux-mêmes ; une commande permet de
  les recalculer à partir des corpus d'origine.

## 8. Règles de coloration de la page « Analyser un texte » (v1)

| Élément | Critère | Couleur |
|---|---|---|
| Position entre deux mots (flux) | proportion `P(X ≥ valeur)` pour l'indicateur choisi, X étant le poids ou la taille | seuils propres à chaque indicateur (voir ci-dessous) |
| Phrase entière | proportion dans la norme du poids (ou de la taille) maximal de la phrase | texte d'explication, par ex. « Dans cette phrase, une position atteint un poids de 3 ; dans le corpus de référence, seules 2 % des positions atteignent cette valeur. » |

**Seuils de couleur** (une position prend la couleur dès que `P(X ≥ valeur)` est inférieure ou égale au
seuil) :

| Indicateur | Rouge clair | Rouge moyen | Rouge foncé | Effet avec la norme par défaut UD Sequoia |
|---|---|---|---|---|
| poids | ≤ 40 % | ≤ 5 % | ≤ 1 % | poids 2 rouge clair, 3 rouge moyen, ≥ 4 rouge foncé |
| taille | ≤ 10 % | ≤ 5 % | ≤ 2 % | taille 5 rouge clair, 6 rouge moyen, ≥ 7 rouge foncé |

- Pourquoi des seuils à part pour le poids : le poids prend peu de valeurs. Dans UD Sequoia,
  P(poids ≥ 2) = 38 % et P(poids ≥ 3) = 4,3 % ; avec un premier seuil à 10 %, le rouge clair n'apparaîtrait
  jamais.
- Les seuils dépendent de la norme choisie. Dans SUD Sequoia, P(poids ≥ 2) = 41,3 % et P(poids ≥ 3) = 5,09 %,
  juste au-dessus des seuils : un poids de 2 n'est pas coloré et un poids de 3 n'est qu'en rouge clair.
  C'est une propriété des données, pas une erreur du programme.
- Au survol d'une position : affichage de la taille et du poids, et mise en évidence dans la phrase des
  dépendances de ce flux.
- Les seuils sont réglables, avec un texte d'explication dans la page.
- Si une position se trouve à l'intérieur d'un mot composé (par ex. entre de|le dans *du*), la couleur est
  appliquée à la forme de surface.

## 9. Décisions retenues

1. Norme par défaut de la page « Analyser un texte » : **UD Sequoia** ; on peut choisir ParisStories,
   Rhapsodie ou la réunion des trois.
2. La coloration se fait par défaut selon le **poids**, avec un bouton pour passer à la taille ; au survol,
   les deux valeurs sont affichées.
3. Seuils de couleur (réglables) : 10 % / 5 % / 2 % pour la taille ; **40 % / 5 % / 1 %** pour le poids,
   fixés après examen des distributions des normes.
4. L'interface web est **uniquement en français** : boutons, explications, phrases d'interprétation et
   messages d'erreur. La ligne de commande reste en anglais.
