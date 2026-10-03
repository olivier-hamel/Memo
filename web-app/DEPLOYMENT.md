# Déployer Mémo dans HomeLab

Mémo fonctionne comme un service Docker indépendant. Caddy, dans le frontend
HomeLab, sert le tableau de bord et transmet `/memo/*` à Mémo en retirant ce
préfixe. Le frontend Mémo est compilé avec `VITE_MEMO_BASE=/memo/` et Uvicorn
reçoit `--root-path /memo`. Les API HomeLab `/api/*` conservent leur routage.

## Sources et configuration

Placer les deux dépôts côte à côte : `homelab/` et `memo/`. La variable Compose
`MEMO_SOURCE_DIR` permet de choisir un autre emplacement. Le build de Mémo
utilise son propre Dockerfile, Node 24 pour la compilation et Python 3.12 pour
le serveur. Aucun port du backend Mémo n'est publié.

Dans le `.env` privé de HomeLab, adapter ces paramètres à son serveur :

```dotenv
MEMO_SOURCE_DIR=../memo
FRONTEND_BIND_ADDRESS=192.168.1.10
FRONTEND_PORT=3000
FRONTEND_HTTPS_PORT=3443
TAILSCALE_BIND_ADDRESS=100.64.0.10
TAILSCALE_PORT=3000
TAILSCALE_HTTPS_PORT=3443
HTTPS_LAN_HOST=192.168.1.10
HTTPS_TAILSCALE_HOST=100.64.0.10
```

`8443` et `8444` sont les ports internes Caddy pour LAN et Tailscale ;
`3443` est le port du navigateur pour les deux adresses du serveur. Le script
de démarrage choisit un certificat par listener pour les clients IP sans SNI.
Les valeurs ci-dessus sont des exemples. Ne pas ajouter de configuration
réelle ou de données personnelles à Git. Conserver les variables HomeLab et
les fichiers d'environnement du backend existants.

Depuis HomeLab :

```sh
docker compose config --quiet
docker compose build memo frontend
docker compose run --rm --no-deps frontend caddy validate --config /config/runtime.json
docker compose up -d --no-deps --wait memo
# Créer le premier compte et importer sa progression avant sa première étude.
docker compose exec memo python -m backend.accounts create oli --display-name Oli --generate-password
# Après avoir copié une sauvegarde privée dans le conteneur sous /tmp/import.json :
docker compose exec memo python -m backend.accounts import-progress oli /tmp/import.json
docker compose up -d --no-deps --wait frontend
```

Les comptes sont activés et HTTPS est obligatoire dans l'image de production.
Le mode local historique sans comptes est réservé à `./start.sh` ; il ne peut
pas être activé avec `MEMO_ENV=production`.

## Certificats privés

Caddy utilise `tls internal`. Le volume `caddy_data` conserve son autorité et
ses clés afin qu'une nouvelle image ne change pas l'autorité de confiance.
Exporter seulement le certificat **public** de l'autorité :

```sh
docker compose cp frontend:/data/caddy/pki/authorities/local/root.crt ./homelab-root.crt
openssl x509 -in homelab-root.crt -noout -fingerprint -sha256
```

Distribuer ce certificat et son empreinte par un canal de confiance. Ne jamais
distribuer les fichiers `.key` ni installer une autorité provenant d'une source
inconnue. Le certificat exporté reste hors Git.

- Ubuntu/Debian : copier le certificat dans
  `/usr/local/share/ca-certificates/homelab-root.crt`, puis exécuter
  `sudo update-ca-certificates`. Selon le navigateur, importer également le
  certificat dans son magasin d'autorités.
- Firefox : Paramètres → Vie privée et sécurité → Certificats → Afficher les
  certificats → Autorités → Importer ; autoriser l'identification des sites web.
- Windows : importer dans « Autorités de certification racines de confiance »
  du magasin de l'utilisateur.
- macOS : importer dans Trousseaux d'accès et autoriser la confiance pour SSL.
- iOS : installer le profil de certificat puis activer la confiance complète
  dans les réglages de confiance des certificats. Android : importer comme
  certificat d'autorité dans les paramètres de sécurité du navigateur/appareil.

Ouvrir ensuite le tableau de bord HTTPS. Le choix de Mémo depuis le tableau de
bord HTTP ouvre le tableau de bord HTTPS avec `?section=memo`. La version HTTP
continue de servir les autres sections. Les clients natifs Fire TV ne sont pas
modifiés par cette intégration.

## Comptes et progression

Les commandes suivantes se lancent depuis HomeLab. Sans `--generate-password`,
les commandes demandent le mot de passe deux fois, sans l'afficher :

```sh
docker compose exec memo python -m backend.accounts create nouvel_utilisateur --display-name "Nom affiché"
docker compose exec memo python -m backend.accounts reset-password nouvel_utilisateur
```

Un mot de passe initial doit être remplacé à la première connexion. Pour
retrouver un mot de passe généré, lire le fichier indiqué par :

```sh
docker compose exec memo python -m backend.accounts credential-path oli
```

Ce fichier est privé, avec des permissions `0600`, et disparaît après le
changement de mot de passe. Ne pas copier sa valeur dans Git ou dans les logs.
Les mots de passe définitifs utilisent Argon2 ; les sessions opaques expirent
après sept jours, sont révocables et utilisent des cookies Secure, HttpOnly et
SameSite Strict. Un changement de mot de passe révoque toutes les anciennes
sessions. Les requêtes d'écriture vérifient l'origine et un en-tête dédié.
Après dix connexions échouées pour une adresse ou un identifiant, attendre
quinze minutes.

Le volume `memo_data` contient `accounts.sqlite3` et
`users/<identifiant-interne>/progress.json`. Chaque compte dispose de sa
session d'étude et de son verrou ; plusieurs onglets d'un même compte partagent
la progression. Utiliser un seul worker Uvicorn. Le moteur et les cartes restent
identiques à la version desktop.

L'import de progression est explicite, valide le fichier avant de l'utiliser,
et refuse de remplacer une progression existante. La version déployée n'importe
jamais automatiquement un fichier desktop dans un nouveau compte. Ne pas lancer
l'import pendant qu'une personne utilise déjà sa session d'étude.

## Sauvegarde et retour arrière

Conserver des copies privées du `.env`, de la configuration Compose et des
images précédentes avant une mise à jour. Sauvegarder les volumes `memo_data`
et `caddy_data` lorsque Mémo et le frontend sont arrêtés, pour obtenir une copie
cohérente de SQLite et des fichiers. Redémarrer ensuite les deux services.

Pour revenir en arrière, restaurer les fichiers de configuration et l'image
frontend précédente, puis recréer seulement le frontend. Une panne de Mémo ne
doit pas nécessiter de reconstruire ni de redémarrer le backend cinéma.
Ne jamais utiliser `docker compose down --volumes` pour une mise à jour ou un
retour arrière : cette commande effacerait les comptes, les progrès et l'autorité.

Vérifier `/healthz`, `/api/health` et `/memo/api/health`, puis ouvrir le navigateur
avec l'autorité installée. Vérifier la connexion, deux comptes indépendants,
une reprise après redémarrage, le rendu mobile et TV & Movies. Les contrôles
automatiques utilisent des données temporaires, jamais la progression importée.
