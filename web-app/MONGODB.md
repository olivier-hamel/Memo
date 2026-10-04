# Ensembles et éditeur MongoDB

La bibliothèque stocke les questions/réponses, titres, descriptions et versions
dans la collection `memo_card_sets` d'une base MongoDB existante. Seul FastAPI se
connecte à MongoDB avec PyMongo. Les navigateurs utilisent les API authentifiées
de Mémo ; ils ne reçoivent ni l'URI ni les identifiants de la base.

Les comptes et sessions restent dans SQLite. Les acquis restent dans les fichiers
atomiques du volume `memo_data`, séparés par utilisateur, ensemble et version.
Le moteur d'étude et les cartes d'origine restent inchangés.

## Configurer Atlas ou un serveur existant

1. Créer un utilisateur de base dédié, avec `readWrite` sur la base `memo`, ou
   choisir un autre nom de base. Cet utilisateur est distinct du compte Atlas et
   des utilisateurs de Mémo.
2. Autoriser les connexions sortantes de votre serveur. Pour Atlas, ajouter son
   adresse IP publique à la liste d'accès du projet. Une IP LAN ou Tailscale ne
   correspond pas à l'adresse vue par Atlas. Pour un serveur privé, vérifier le
   routage et les règles d'accès au port MongoDB.
3. Récupérer l'URI du pilote Python. Atlas fournit une URI `mongodb+srv://...` avec
   TLS. Pour un serveur distant, activer TLS avec une autorité de confiance.
4. Copier `mongodb.env.example` dans le fichier **privé et ignoré**
   `.env.memo-mongodb` de HomeLab. Remplacer les valeurs et protéger le fichier
   avec `chmod 600 .env.memo-mongodb`. Encoder les caractères spéciaux du mot de
   passe dans l'URI. Ne pas copier ces valeurs dans Git, des tickets ou des logs.

```dotenv
MEMO_MONGODB_URI='mongodb+srv://MEMO_USER:ENCODED_PASSWORD@cluster.example.mongodb.net/?retryWrites=true&w=majority'
MEMO_MONGODB_DATABASE=memo
```

HomeLab charge ce fichier comme `env_file` facultatif pour le service `memo`.
`MEMO_MONGODB_ENV_FILE` peut définir un autre chemin privé. La syntaxe facultative
`required: false` nécessite Docker Compose 2.24 ou plus récent.
Le backend peut aussi lire une URI brute depuis `MEMO_MONGODB_URI_FILE`.

## Migrer et déployer

Sauvegarder les fichiers privés et le volume Mémo, puis récupérer les commits
validés des deux dépôts. Depuis HomeLab :

```sh
docker compose config --quiet
docker compose build memo
# Le conteneur ponctuel reçoit le fichier d'environnement et le volume existant.
docker compose run --rm --no-deps memo python -m backend.decks --owner oli
docker compose up -d --no-deps --wait memo
```

L'import initialise seulement l'ensemble partagé d'origine. Il conserve les
termes, réponses et identités des cartes, et refuse un contenu incompatible.
Relancer l'import ne remplace jamais un ensemble ou une version existante.
La première version réutilise `users/<id>/progress.json`, y compris l'import
desktop. Les autres acquis sont dans `users/<id>/sets/<ensemble>/v<version>.json`.

Sans configuration MongoDB, Mémo garde son mode existant. Une panne MongoDB
renvoie une erreur récupérable ; aucune progression n'est réinitialisée.

## Utiliser la bibliothèque

Après connexion, ouvrir **Mes ensembles**, puis **Nouvel ensemble**. Saisir un
titre, une description facultative et les questions/réponses. Ajouter ou retirer
des cartes, puis enregistrer. Chaque nouvel ensemble est privé à son créateur.
L'ensemble d'origine est partagé ; seul le propriétaire choisi lors de l'import
peut le modifier. Il n'y a pas de publication publique ni de suppression des
versions dans cette version de l'éditeur.

Modifier une question, une réponse ou l'ordre des cartes crée une nouvelle
version. Les études déjà commencées restent sur leur version ; choisir la
nouvelle version commence une progression séparée. Un simple changement de
titre ou de description conserve la version des cartes. Les versions précédentes
restent accessibles dans la bibliothèque et leurs progrès restent disponibles.
Le dernier choix d'ensemble/version est retenu dans le navigateur pour le compte.

L’éditeur permet aussi d’ajouter plusieurs documents de cours PDF, PPT ou PPTX et
de les lire à côté des cartes, avec zoom, navigation, notes du présentateur et
séparation redimensionnable. Voir [le lecteur intégré](README.md#lire-les-documents-de-cours-dans-léditeur).
Les `document_ids` sont enregistrés au niveau de l’ensemble, indépendamment des
versions des cartes. Les PDF convertis et les notes restent sur le volume
`memo_data/reference-documents`, avec des endpoints authentifiés. Les anciens
ensembles n’ont besoin d’aucune migration ; ils commencent sans document.

L'éditeur refuse les doublons exacts et les textes vides. Limites : 300 cartes par
ensemble, 100 ensembles personnels, requêtes d'édition de 2 Mio, document avec
historique limité à 12 Mio. Les sauvegardes concurrentes utilisent une révision
MongoDB atomique ; un onglet périmé ne peut pas écraser une édition plus récente.

Les endpoints sont `GET/POST /api/sets`, `GET/POST /api/sets/{id}` et les endpoints
d'étude existants avec `?set_id=<id>&version=<numéro>`. Les identités viennent des
sessions authentifiées, avec les mêmes protections HTTPS et d'origine. Les
formats des réponses d'étude restent identiques.

## Vérifier et sauvegarder

```sh
.venv/bin/python -m pip install -r backend/requirements-dev.txt
.venv/bin/python -m unittest discover -s backend/tests
cd frontend
npm run build
npm run test:e2e
npm run test:decks
```

Les tests de bibliothèque utilisent MongoDB en mémoire par défaut. Pour tester
un vrai serveur, définir `MEMO_TEST_MONGODB_URI` et `MEMO_TEST_DATABASE` dans un
environnement privé avant de lancer `test_decks.py`. Les tests créent des
collections `memo_validation_<uuid>` et suppriment seulement ces collections.
Les tests navigateur utilisent des comptes et une base temporaires isolés.

Sauvegarder la collection MongoDB **et** le volume `memo_data`. La collection
conserve les cartes/versionnements ; le volume conserve les identités, sessions
et acquis associés. Les sauvegardes Atlas ou les outils de sauvegarde MongoDB
peuvent protéger la collection selon le déploiement. Pour revenir à l'image
antérieure, garder les données et retirer la configuration MongoDB du service ;
la progression du deck d'origine reste compatible. Les ensembles créés dans
MongoDB redeviendront accessibles quand l'intégration sera réactivée.

Références : [pilote Python](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/connect/mongoclient/),
[utilisateurs Atlas](https://www.mongodb.com/docs/atlas/security-add-mongodb-users/),
[accès réseau Atlas](https://www.mongodb.com/docs/atlas/security/ip-access-list/).
