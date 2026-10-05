# Mémo · Flashcard Learn pour le web

Pour l'intégration HomeLab avec comptes individuels, HTTPS privé et stockage
persistant, consulter [le guide de déploiement](DEPLOYMENT.md). Chaque utilisateur
retrouve ses propres acquis ; les données et mots de passe restent hors Git.

La bibliothèque MongoDB ajoute des ensembles privés, un éditeur de questions et
réponses et des versions indépendantes. Voir [la configuration MongoDB](MONGODB.md).

## Importer un ensemble Quizlet

Dans **Nouvel ensemble → Importer depuis Quizlet**, colle le lien HTTPS d’un
ensemble public, puis clique sur **Importer les cartes**. Mémo récupère le texte,
la structure HTML et les données embarquées de la page, puis utilise
**Gemini 3.5 Flash-Lite** (`gemini-3.5-flash-lite`) pour extraire les termes et
définitions dans leur langue et leur ordre d’origine. Les champs se remplissent
automatiquement et restent modifiables avant **Créer l’ensemble**. Les cartes
déjà saisies sont conservées ; seuls les emplacements entièrement vides sont
remplacés. Un titre ou une description déjà saisis sont conservés.

La clé Gemini reste sur le backend. Configure `MEMO_GEMINI_API_KEY` ou
`MEMO_GEMINI_API_KEY_FILE` (chemin vers un fichier secret lisible par le serveur).
En local, le backend lit aussi `.gemini-api-key` à la racine de `web-app/` ; ce
fichier est exclu de Git et du contexte Docker. En conteneur, monte le secret en
lecture seule et définis `MEMO_GEMINI_API_KEY_FILE` sur son chemin dans le
conteneur. Ne mets jamais la clé dans une variable `VITE_*`.

Le modèle dispose d’un [quota gratuit](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.5-flash-lite),
avec les limites du projet Google associé à la clé. Utilise un projet sans
facturation pour rester sur le niveau gratuit. Le contenu public de la page est
envoyé à Google pour l’extraction. La bibliothèque MongoDB et un compte connecté
sont nécessaires, comme pour la création manuelle d’un ensemble.

La récupération utilise une connexion HTTPS compatible avec Chrome, afin de
lire les pages publiques que Quizlet refuse aux clients HTTP standards. Le
backend valide chaque redirection et conserve la vérification des certificats.
`MEMO_QUIZLET_BROWSER_HTTP=0` permet de revenir au client HTTP standard pour le
diagnostic. Gemini lit aussi les cartes stockées dans les données JSON imbriquées
de Quizlet, même quand seules les premières cartes figurent dans le texte visible.

L’import accepte jusqu’à 300 cartes textuelles. Les pages privées, les
vérifications anti-robot, les pages dont les cartes nécessitent JavaScript et
les ensembles incomplets produisent une erreur sans modifier le brouillon.
Mémo n’exécute pas les scripts Quizlet, n’automatise pas les CAPTCHA et ne se
connecte pas à un compte Quizlet.
Les erreurs de quota, de connexion et de configuration sont affichées dans
l’éditeur ; aucun ensemble n’est enregistré avant ta validation.

Version web de l’application Tkinter, avec une nouvelle interface française en React/TypeScript. Le backend FastAPI utilise le moteur `study_engine.py`, avec des réglages d’apprentissage persistants. Les 39 termes et définitions sont extraits de `FLASHCARDS` sans modifier leur contenu.

## Configurer l’apprentissage

Pendant une session, le bouton de configuration à côté du mode concentration
ouvre les paramètres d’apprentissage ; **Paramètres** dans la barre latérale
ouvre la même fenêtre. On peut ajuster la taille des groupes, les réussites
consécutives nécessaires pour les états familière et maîtrisée, le score minimum,
les rappels espacés et actifs, les modes de réponse (écrite, choix multiples et
sens inversé), ainsi que l’espacement, les délais, les priorités de sélection et
la pénalité après une erreur.

Clique sur **Enregistrer** pour appliquer les changements.
Les réponses et les compteurs sont conservés. La taille des groupes réorganise
le parcours ; les critères de maîtrise réévaluent le groupe actif et préservent
les acquis des groupes terminés. Les réglages sont sauvegardés avec la
progression de l’utilisateur, pour cet ensemble et cette version.
**Rétablir les paramètres par défaut**, puis **Enregistrer**,
réapplique les valeurs d’origine : groupes de 10, familiarité après 1 réussite,
au moins 3 réussites consécutives, 2 rappels espacés, 1 rappel actif et un score
de 85 % pour la maîtrise. Les réponses écrites, choix multiples et sens inversé
sont désactivés par défaut. **Annuler** ferme la fenêtre sans appliquer le brouillon.

## Lancer l’application

Prérequis : Python 3.10+ avec `venv`, Node.js 22.12+ et npm.

Depuis ce dossier :

```bash
./start.sh
```

Le script installe les dépendances au premier lancement, compile le frontend et démarre l’application sur **http://localhost:8000**. Les polices, icônes et fichiers de l’interface sont servis localement. Le mode personnel utilise les cartes locales ; la bibliothèque connectée nécessite MongoDB. `Ctrl+C` arrête le serveur.

Pour développer avec rechargement automatique de React et de Python :

```bash
./start.sh --dev
```

Interface : **http://localhost:5173**. Documentation de l’API : **http://localhost:8000/docs**.

## Lire les documents de cours dans l’éditeur

Dans **Nouvel ensemble** ou dans un ensemble modifiable, utilise **Ajouter des
documents** pour joindre plusieurs `.pdf`, `.ppt` ou `.pptx`, puis **Afficher le
lecteur**. **Choisir un document** ouvre une fenêtre avec tous les documents
de l’ensemble, leur format et leur nombre de pages ou de slides. Clique sur un
document pour le consulter ; la corbeille permet de le retirer de l’ensemble,
avec un bouton **Annuler**. Enregistre l’ensemble pour conserver les suppressions.
Tu peux continuer à
écrire les cartes pendant l’ajout ou la conversion ; l’enregistrement de
l’ensemble devient disponible une fois les documents prêts.

Le lecteur permet de faire défiler les pages, de passer à une page précise et
de zoomer de 50 à 200 %. Les PowerPoint sont convertis en PDF sur le serveur et
leurs notes textuelles sont conservées séparément, slide par slide, puis
affichées directement dans le lecteur, sous leur diapositive. Les commentaires classiques et modernes,
leurs auteurs et les réponses s’affichent aussi pour la slide consultée lorsqu’ils
sont présents. Les slides masquées sont incluses pour conserver
l’alignement des notes et commentaires. Les animations et médias interactifs deviennent un
rendu statique. Un PDF existant ne contient pas les notes du PowerPoint source.

Sur grand écran, le document occupe toute la hauteur et rejoint le bord droit
de la fenêtre. Les commandes et le sélecteur restent à gauche ; les notes et
commentaires suivent les diapositives dans le lecteur à droite.
Le bouton **Fermer le lecteur de documents** masque le lecteur en conservant les
documents liés à l’ensemble. Glisse la séparation verticale pour ajuster les panneaux entre
30/70 et 70/30. Un double clic rétablit 50/50 ; les flèches du clavier ajustent
la séparation lorsqu’elle a le focus. Sur petit écran, les boutons **Cartes**
et **Document** alternent entre les panneaux et conservent le brouillon.
La largeur, le document sélectionné, la page et le zoom sont mémorisés dans le
navigateur pour le compte. Le lecteur fonctionne sans service externe ni CDN.

Limites : **20 documents par ensemble, 30 Mio par fichier, 500 pages/slides**.
Les PDF protégés par mot de passe et les fichiers endommagés sont refusés avec
un message dans l’éditeur. Les documents restent privés et suivent l’accès à
l’ensemble lorsqu’il est partagé. Ajouter ou retirer un document ne crée pas
une nouvelle version des cartes et ne réinitialise pas leur progression.

La bibliothèque MongoDB et un compte connecté sont nécessaires. LibreOffice
est inclus dans l’image Docker. Pour un lancement local, installe LibreOffice
Impress (par exemple `sudo apt install libreoffice-impress` sous Debian/Ubuntu)
ou configure `MEMO_LIBREOFFICE_BIN` avec le chemin de `soffice`. Les PDF restent
utilisables si LibreOffice est absent. Les dépendances Python et PDF.js sont
installées par les fichiers de dépendances habituels.

Les PDF et leurs notes sont stockés dans
`$FLASHCARD_WEB_DATA/reference-documents/` (ou `backend/data/reference-documents/`
par défaut), et leurs liens dans MongoDB. Sauvegarde le volume de données avec
MongoDB. Fermer le lecteur conserve les fichiers liés à l’ensemble.
Un brouillon abandonné peut également laisser des fichiers sur ce volume.

## Valider la couverture des cartes

Dans l’éditeur, **Validation**, à côté de l’enregistrement, compare les cartes
actuelles (y compris les modifications non enregistrées) avec tous les documents
joints. Le backend téléverse les PDF complets, sans découpage, puis les transmet
ensemble à Gemini avec toutes les questions/réponses et les notes/commentaires
des PowerPoint associés à leurs diapositives. La clé et le modèle sont ceux de
l’import Quizlet.

Un appel `countTokens` mesure d’abord la taille de cette demande complète. Si
elle tient dans les limites, **un seul appel de génération** analyse le cours,
compare le sens des informations avec les cartes existantes et rédige directement
les cartes nécessaires pour les informations absentes ou incomplètes. La réponse
est un objet JSON conforme à un schéma ; elle ne contient ni inventaire
intermédiaire ni citations des cartes existantes. Chaque proposition indique
l’information manquante, son document et sa page. Les informations déjà
enseignées dans plusieurs cartes ensemble sont prises en compte.

Un projet dépassant **250 000 tokens d’entrée**, **1 000 pages au total**,
**50 Mio par PDF converti**, **20 documents** ou **300 cartes existantes** affiche
**« Ce projet est trop gros pour la validation »**. Une limite de tokens
configurée plus basse s’applique également. Aucun document ou texte n’est
tronqué, et aucun découpage automatique n’est tenté. Une réponse qui ne peut
pas contenir toutes les cartes nécessaires (maximum 300 propositions et 65 536
tokens de sortie) produit le même message. Une réponse incomplète, une référence
invalide ou un doublon produit une erreur sans confirmer la couverture.
La compréhension du cours et l’exhaustivité des manques restent évaluées par
l’IA ; les contrôles du serveur vérifient le format et la cohérence du résultat.

La validation tourne en arrière-plan. L’encart **Validations** affiche la
préparation, l’envoi des documents, la vérification de la taille, puis l’analyse
et la rédaction. Tu peux continuer à modifier des cartes, étudier, naviguer ou
fermer l’onglet. Une notification signale le résultat ou une erreur ; si l’onglet
était fermé, elle apparaît à ton retour. Le calcul est limité à 20 minutes.

La fenêtre affiche **Aucun manque détecté** si l’analyse complète ne propose
aucune carte, ou les propositions à accepter/refuser individuellement ou en
bloc. Les cartes acceptées rejoignent le brouillon ; **Enregistrer les
modifications** les conserve. Les cartes existantes restent intactes. L’analyse
utilise l’instantané capturé au lancement ; les modifications ultérieures ne
sont pas écrasées. Un brouillon non enregistré peut être retrouvé depuis son
résultat. Créer l’ensemble pendant la validation relie le résultat à cet ensemble.

Les instantanés et résultats sont privés par compte et conservés sept jours
(maximum 20 résultats récents par compte) dans
`$FLASHCARD_WEB_DATA/validation-jobs/`. Une seule validation par compte est
active à la fois, avec deux analyses simultanées au maximum sur le serveur.
Un redémarrage du serveur interrompt le calcul ; le résultat permet de réessayer.

Un résultat complet et vérifié est mis en cache pendant 30 jours dans
`$FLASHCARD_WEB_DATA/validation-cache/`, avec fichiers privés et écritures
atomiques. Une validation identique peut ainsi éviter tous les appels Gemini.
Le contenu des PDF, les notes/commentaires, les cartes, le modèle, les
instructions et la limite de tokens déterminent si le résultat reste utilisable.
Une modification relance la demande complète. Les anciennes étapes de
l’algorithme découpé ne sont plus utilisées. La clé API et les liens temporaires
Google ne sont jamais stockés dans le cache.
Les copies envoyées via la [Files API de Gemini](https://ai.google.dev/api/files)
font l’objet d’une demande de suppression après l’analyse, même en cas d’échec.

Les validations partagent **10 requêtes par minute** et un budget de
**250 000 tokens d’entrée par minute**, avec réservation du nombre mesuré par
`countTokens` pour la génération. Les requêtes de comptage sont également
espacées ; les téléversements utilisent la Files API. Configure
`MEMO_GEMINI_RPM` et `MEMO_GEMINI_TPM` pour modifier ces réglages.
Une limite temporaire Gemini par minute peut déclencher jusqu’à deux nouvelles
tentatives du même appel après le délai indiqué par Google. Les quotas
quotidiens épuisés ou nuls produisent une erreur sans nouvelle tentative.
Les quotas Google sont par projet et se consultent dans
[Google AI Studio](https://aistudio.google.com/usage?tab=rate-limit).

## Moteur d’étude conservé

- Groupes fixes de 10 cartes, puis un dernier groupe de 9. Toutes les cartes du groupe doivent être maîtrisées avant de débloquer le suivant.
- Premier passage dans l’ordre, puis sélection adaptative des cartes fragiles avec espacement des répétitions.
- Mêmes seuils de maîtrise, pénalités et rappels espacés. Comme dans la version Python actuelle, les questions commencent par le terme ; les anciens prompts inversés reprennent la même carte dans ce sens.
- Maîtrise finale séparée sur l’ensemble mélangé. La progression globale compte pour moitié les groupes et pour moitié cette phase finale.
- Mode Révisions explicite, disponible après le premier groupe terminé. Ses résultats n’altèrent pas la maîtrise initiale ou finale.
- Même autoévaluation : « À revoir » correspond à **Incorrect**, « Bien retenu » à **Bon**. Retourner la carte est nécessaire avant de l’évaluer. Une évaluation passe à la carte suivante.
- Historique de navigation limité au groupe, à la phase et au mode courants. Parcourir ou passer une carte ne l’évalue jamais ; une ancienne carte ne peut pas être évaluée une seconde fois.
- Réponse écrite facultative dans les paramètres. La vérification ignore la casse et les espaces, puis exige le même texte. Révéler une réponse écrite permet de passer à l’autoévaluation. Après la correction écrite, Continuer passe à la carte suivante.

Les paramètres pédagogiques restent dans `backend/study_engine.py`, classe `StudyConfig`. L’adaptateur web ne change pas les calculs du moteur.

## Progression

Au premier démarrage, si `backend/data/progress.json` n’existe pas, le backend reprend le fichier `../flashcard_progress.json` s’il est disponible. Les anciennes versions reconnues par le moteur sont migrées, et une question à choix multiples est affichée comme une flashcard, comme dans l’application desktop.

La version web écrit ensuite uniquement dans **`backend/data/progress.json`**. Réinitialiser depuis les paramètres efface la progression web. La sauvegarde Python d’origine reste intacte et ne sera pas réimportée tant que la sauvegarde web existe.

Chaque action est sauvegardée avec remplacement atomique du fichier. En cas d’erreur d’écriture, l’action est annulée. Une révision de session protège des doubles clics et des actions provenant d’un onglet périmé. Un rafraîchissement du navigateur conserve aussi l’historique tant que le backend tourne ; un redémarrage du backend reprend la question en attente et les acquis sauvegardés, avec un nouvel historique de navigation.

Une sauvegarde web invalide arrête le démarrage au lieu d’être écrasée. Pour repartir à zéro dans ce cas, déplacer ce fichier hors de `backend/data/`, puis lancer avec `FLASHCARD_WEB_IMPORT_DESKTOP=0`.

Variables facultatives :

```bash
# Choisir un autre fichier de progression
FLASHCARD_WEB_PROGRESS=/tmp/memo-test.json ./start.sh

# Créer une progression neuve sans importer la version desktop
FLASHCARD_WEB_IMPORT_DESKTOP=0 ./start.sh
```

L’application est prévue pour un espace personnel local : **un seul processus Uvicorn**, sans compte utilisateur. Tous les onglets du même serveur partagent la session et sa sauvegarde.

## Raccourcis

| Touche | Action |
| --- | --- |
| Espace | Retourner la carte |
| ← / → | Carte précédente / suivante, sans notation |
| 1 | À revoir, après révélation |
| 2 | Bien retenu, après révélation |
| Entrée | Vérifier la réponse écrite |
| Maj + Entrée | Nouvelle ligne dans une réponse écrite |
| Échap | Fermer la fenêtre de paramètres ou d’aide |

Dans le champ de réponse, les chiffres, espaces et flèches servent à écrire. Les boutons de navigation restent disponibles. Un mode concentration masque les panneaux latéraux.

## Structure

```text
web-app/
├── start.sh                    # Installation et lancement
├── dev.py                      # Deux serveurs en développement
├── backend/
│   ├── study_engine.py         # Moteur original, inchangé
│   ├── controller.py           # Cartes, navigation, sauvegarde
│   ├── main.py                 # API FastAPI et frontend compilé
│   ├── requirements.txt         # Dépendances directes
│   ├── requirements.lock.txt    # Versions vérifiées
│   ├── data/flashcards.json    # Contenu original
│   └── tests/                  # Tests originaux du moteur + API
├── frontend/
│   ├── src/                    # React, TypeScript et CSS
│   ├── package-lock.json
│   ├── playwright.config.ts
│   └── tests/study.spec.ts      # Scénarios navigateur
└── .gitignore
```

## Vérifier

Depuis `web-app/`, après installation :

```bash
.venv/bin/python -m unittest discover -s backend/tests -v
cd frontend
npm run build
npx playwright install chromium
npm run test:e2e
```

Les tests navigateur démarrent leurs propres serveurs sur 8880 et 8881. Ils utilisent une sauvegarde de test dans `/tmp`, indépendante de tes données. Pour utiliser Chrome déjà installé : `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/google-chrome npm run test:e2e`.

Les tests couvrent les règles du moteur, le rappel écrit, la navigation sans notation, la reprise de progression, les phases initiale/finale, les révisions indépendantes, les écritures atomiques, les onglets concurrents, les raccourcis clavier et le rendu mobile.
