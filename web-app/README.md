# Mémo · Flashcard Learn pour le web

Pour l'intégration HomeLab avec comptes individuels, HTTPS privé et stockage
persistant, consulter [le guide de déploiement](DEPLOYMENT.md). Chaque utilisateur
retrouve ses propres acquis ; les données et mots de passe restent hors Git.

Version web de l’application Tkinter, avec une nouvelle interface française en React/TypeScript. Le backend FastAPI utilise une **copie exacte du `study_engine.py` original**. Les 39 termes et définitions sont extraits de `FLASHCARDS` sans modifier leur contenu.

## Lancer l’application

Prérequis : Python 3.10+ avec `venv`, Node.js 22.12+ et npm.

Depuis ce dossier :

```bash
./start.sh
```

Le script installe les dépendances au premier lancement, compile le frontend et démarre l’application sur **http://localhost:8000**. Les polices, icônes et fichiers de l’interface sont servis localement. Après l’installation, aucune connexion à un service externe n’est nécessaire. `Ctrl+C` arrête le serveur.

Pour développer avec rechargement automatique de React et de Python :

```bash
./start.sh --dev
```

Interface : **http://localhost:5173**. Documentation de l’API : **http://localhost:8000/docs**.

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
