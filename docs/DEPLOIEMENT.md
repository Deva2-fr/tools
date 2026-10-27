# Mise en production (CI/CD) – pas à pas

Ce guide met le Hub en production **automatiquement à chaque merge sur `main`**, avec le même principe que `ice-theaters` : GitHub Actions teste, construit les images Docker, ouvre le **VPN Freebox**, se connecte en **SSH** au serveur, sauvegarde la base, déploie et vérifie que tout fonctionne (retour automatique à la version précédente sinon).

```
Pull request ─▶ CI (lint, tests, build, migrations)        ─▶ merge possible si tout est vert
Merge sur main ─▶ CI ─▶ images sur GHCR ─▶ VPN ─▶ SSH ─▶ sauvegarde de la base ─▶ docker compose up
                                                          ─▶ test de santé ─▶ (échec ⇒ retour à la version précédente)
```

| Fichier | Rôle |
|---|---|
| `.github/workflows/ci.yml` | contrôles : lint + 54 tests (backend), typage + build (frontend), validation Docker Compose |
| `.github/workflows/deploy.yml` | appelle la CI, construit/publie les images, vérifie les migrations sur PostgreSQL, déploie |
| `docker-compose.prod.yml` | la production : utilise les images publiées, aucun port 80/443 |
| `caddy/Caddyfile.proxy` | Caddy du Hub en HTTP interne (le HTTPS est géré par votre reverse proxy existant) |
| `scripts/deploy.sh` | exécuté sur le serveur : sauvegarde → déploiement → test de santé → rollback |

> **Les ports 80 et 443 de votre serveur sont déjà utilisés** (ice-theaters). Le Hub ne les touche pas : il écoute **uniquement en local** sur un port interne (par défaut **`31847`**, modifiable) et votre reverse proxy actuel relaie le nouveau domaine vers ce port.

---

## Étape 1 – Vérifier le port interne (2 min)

Sur le serveur (en SSH) :

```bash
ss -ltn | grep 31847 || echo "31847 est libre"
```

S'il est déjà pris, choisissez un autre nombre entre 10000 et 60000 (ex. `ss -ltn | grep 42177`) : vous le mettrez dans `HUB_PORT` à l'étape 3.

## Étape 2 – Domaine et reverse proxy existant (10 min)

1. **DNS** : créez chez votre registrar un enregistrement pour le Hub (ex. `hub.deva2.fr`) vers **la même IP publique** que ice-theaters.
2. Dans le **reverse proxy qui occupe déjà 80/443**, ajoutez un site qui relaie ce domaine vers `127.0.0.1:31847` (votre port). Choisissez l'exemple qui correspond à votre outil :

**nginx** (à côté de la config d'ice-theaters, certificat comme pour les autres sites) :
```nginx
server {
    listen 443 ssl;
    server_name hub.deva2.fr;
    # ssl_certificate / ssl_certificate_key : comme pour vos autres domaines (certbot…)
    client_max_body_size 20m;                       # téléversement de documents (15 Mo max côté Hub)

    location / {
        proxy_pass http://127.0.0.1:31847;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**Caddy** (HTTPS automatique) :
```caddy
hub.deva2.fr {
    reverse_proxy 127.0.0.1:31847
}
```

**Traefik** : ajoutez un routeur `Host(\`hub.deva2.fr\`)` avec un service `http://127.0.0.1:31847` (fournisseur « file »).

> Si votre reverse proxy tourne **dans un conteneur Docker**, `127.0.0.1` désigne alors le conteneur lui-même : utilisez l'IP de l'hôte (ou `host.docker.internal`) et mettez `HUB_BIND=0.0.0.0` à l'étape 3 (le port reste protégé par le pare-feu : ne l'ouvrez pas vers Internet).

3. Rechargez le proxy (`sudo nginx -t && sudo systemctl reload nginx`, ou équivalent).

## Étape 3 – Préparer le secret `ENV_FILE` (10 min)

C'est le contenu du fichier `.env` de production. Sur votre poste, générez des secrets :

```bash
openssl rand -hex 32   # à lancer 4 fois : POSTGRES_PASSWORD, SECRET_KEY, ENCRYPTION_KEY, WEBHOOK_TOKEN
```

(Windows PowerShell : `-join ((48..57)+(97..102) | Get-Random -Count 64 | % {[char]$_})`.)

Puis préparez ce texte en remplaçant les valeurs :

```ini
DOMAIN=hub.deva2.fr
BASE_URL=https://hub.deva2.fr
POSTGRES_PASSWORD=<secret 1>
SECRET_KEY=<secret 2>
ENCRYPTION_KEY=<secret 3>
WEBHOOK_TOKEN=<secret 4>
ADMIN_EMAIL=vous@deva2.fr
ADMIN_PASSWORD=<mot de passe de 12 caractères minimum>
COOKIE_SECURE=true
TIMEZONE=Europe/Paris
HUB_PORT=31847
HUB_BIND=127.0.0.1
```

| Variable | À remplir avec |
|---|---|
| `DOMAIN`, `BASE_URL` | votre domaine ; `BASE_URL` commence par `https://` (sert aux redirections Microsoft) |
| `POSTGRES_PASSWORD` | un secret aléatoire (la base n'est jamais exposée) |
| `SECRET_KEY` | un secret aléatoire (signe les sessions de connexion) |
| `ENCRYPTION_KEY` | un secret aléatoire. **Copiez-le dans votre gestionnaire de mots de passe : le perdre rend illisibles les clés saisies dans le Hub** |
| `WEBHOOK_TOKEN` | un secret aléatoire (alertes envoyées par des outils externes) |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | votre compte administrateur, **créé au tout premier démarrage uniquement** |
| `COOKIE_SECURE` | `true` (le site est servi en HTTPS par votre proxy) |
| `HUB_PORT` / `HUB_BIND` | le port interne de l'étape 1 ; `127.0.0.1` sauf cas du proxy dans un conteneur |

## Étape 4 – Secrets GitHub (5 min)

Dépôt `Deva2-fr/tools` → **Settings → Secrets and variables → Actions → New repository secret**.

Ce sont **les mêmes noms que pour ice-theaters** : si ces secrets sont définis au niveau de l'**organisation** `Deva2-fr` et ouverts au dépôt `tools`, vous n'avez presque rien à créer ; sinon recopiez-les.

| Secret | Valeur |
|---|---|
| `VPN_SERVER`, `VPN_USER`, `VPN_PASSWORD` | identiques à ice-theaters (VPN Freebox IKEv2) |
| `SSH_HOST`, `SSH_USER`, `SSH_KEY` | identiques à ice-theaters (même serveur ; `SSH_KEY` = clé **privée** complète, avec les lignes `BEGIN/END`) |
| `DEPLOY_PATH` | **un dossier différent d'ice-theaters**, ex. `/opt/deva2-hub` (créé automatiquement). Utilisez un chemin absolu |
| `ENV_FILE` | le texte de l'étape 3 |

> **`ENV_FILE` n'est lu qu'une seule fois** : le workflow ne crée `.env` sur le serveur que s'il n'existe pas (comme pour ice-theaters). Pour modifier un réglage plus tard, éditez `$DEPLOY_PATH/.env` **sur le serveur**, puis `docker compose -f docker-compose.prod.yml up -d` (ou relancez un déploiement).

Vérifiez aussi **Settings → Actions → General → Workflow permissions** : « Read and write permissions » (nécessaire pour publier les images).

## Étape 5 – Protéger la branche `main` (5 min, recommandé)

**Settings → Branches → Add branch ruleset / protection rule** pour `main` :
- ✅ *Require a pull request before merging*
- ✅ *Require status checks to pass* : cochez les contrôles `checks / Backend (lint + tests)`, `checks / Frontend (typage + build)`, `checks / Docker Compose (validation)`, `check-migrations` (ils n'apparaissent qu'après la première exécution de la CI : revenez ici après l'étape 6.1)
- ✅ *Block force pushes*

Ainsi, **rien n'arrive en production sans que les tests soient verts**.

---

## Étape 6 – Première mise en production

### 6.1 Ouvrir la Pull Request
1. Sur GitHub, ouvrez le dépôt → bandeau jaune **« Compare & pull request »** pour la branche `claude/adoring-wozniak-74avhv` (sinon : *Pull requests → New pull request*, base `main`, compare `claude/adoring-wozniak-74avhv`).
2. Donnez un titre (« Mise en production du Hub ») → **Create pull request**.
3. Onglet **Checks** / **Actions** : la CI tourne (≈ 3 à 5 min) et les images sont **construites sans être publiées** (c'est un test). Corrigez tout échec avant de continuer.

### 6.2 Fusionner
Quand tout est vert : **Merge pull request**. Le déploiement démarre tout seul.

### 6.3 Suivre le déploiement
Onglet **Actions** → workflow **« Build and Deploy (VPN) »** : `checks` → `build` + `check-migrations` → `deploy`. Dans `deploy`, ouvrez l'étape *Deploy via SSH* : vous voyez la sauvegarde, le téléchargement des images, « Attente de l'API… » puis **« Déploiement réussi »**.

### 6.4 Vérifier
1. `https://hub.deva2.fr/api/health` → `{"status":"ok"}`.
2. Ouvrez `https://hub.deva2.fr`, connectez-vous avec `ADMIN_EMAIL` / `ADMIN_PASSWORD`.
3. **Paramètres → Mon compte** : activez la **2FA**.
4. Remplissez les paramètres (ma société, alertes, Outlook, Google…) : voir [`DEMARRAGE.md`](DEMARRAGE.md), section 6. Pour Outlook, l'URI de redirection Microsoft est `https://hub.deva2.fr/api/mail/callback`.
5. Ajoutez le Hub lui-même dans **Projets & serveurs** pour qu'il surveille son propre site.

**Checklist de première mise en service :** DNS ✓ · bloc du reverse proxy rechargé ✓ · port interne libre ✓ · 5 secrets GitHub ✓ · PR verte ✓ · `/api/health` ✓ · connexion ✓ · 2FA ✓ · sauvegarde `ENCRYPTION_KEY` ✓.

---

## Au quotidien

1. `git checkout -b ma-modif` → modifications → `git push -u origin ma-modif`.
2. Ouvrez une **Pull Request** vers `main` : la CI vérifie tout.
3. **Merge** : déploiement automatique, sauvegarde de la base incluse.
4. Les mises à jour de dépendances arrivent seules sous forme de PR (Dependabot, chaque semaine).

Un changement des **modèles de données** (`backend/app/models.py`) doit toujours s'accompagner d'une migration, sinon le job `check-migrations` échoue :
```bash
cd backend && alembic revision --autogenerate -m "ajout du champ X"
```
Les migrations s'appliquent toutes seules au démarrage de l'API.

## Revenir en arrière (rollback)

- **Automatique** : si l'API n'est pas saine 4 minutes après le déploiement, le script redémarre la version précédente et le workflow passe en rouge.
- **Manuel, code** : sur le serveur
  ```bash
  cd /opt/deva2-hub
  cat .last_tag                                   # dernière version saine
  IMAGE_TAG=<sha-d-une-ancienne-version> docker compose -f docker-compose.prod.yml up -d
  ```
  (les images de chaque déploiement restent sur GHCR, taguées par leur identifiant de commit). Le plus propre ensuite : annuler (`Revert`) la PR fautive sur GitHub, ce qui redéploie.
- **Base de données** (seulement si une migration a mal tourné). Les 10 dernières sauvegardes sont dans `$DEPLOY_PATH/backups/` :
  ```bash
  cd /opt/deva2-hub
  docker compose -f docker-compose.prod.yml stop api worker
  docker compose -f docker-compose.prod.yml exec -T db psql -U hub -d postgres -c "DROP DATABASE hub;" -c "CREATE DATABASE hub;"
  gunzip -c backups/db-AAAAMMJJ-HHMMSS.sql.gz | docker compose -f docker-compose.prod.yml exec -T db psql -U hub -d hub
  docker compose -f docker-compose.prod.yml up -d
  ```

## Sauvegardes, surveillance, maintenance

- Le déploiement sauvegarde la base **avant chaque mise à jour**. Pour une sauvegarde quotidienne en plus, ajoutez au `crontab -e` du serveur :
  ```cron
  0 3 * * * cd /opt/deva2-hub && docker compose -f docker-compose.prod.yml exec -T db pg_dump -U hub hub | gzip > backups/daily-$(date +\%F).sql.gz && find backups -name 'daily-*' -mtime +14 -delete
  ```
  **Copiez ces sauvegardes hors du serveur** (autre machine, stockage objet) : une sauvegarde sur le disque qui tombe en panne ne sert à rien.
- Fichiers téléversés (documents, PDF de notes de frais) : volume Docker `deva2-hub_hub_data` ; sauvegardez-le aussi (`docker run --rm -v deva2-hub_hub_data:/d -v $PWD:/b alpine tar czf /b/hub_data.tgz -C /d .`).
- Journaux : `docker compose -f docker-compose.prod.yml logs -f --tail=100 api`.
- État : `docker compose -f docker-compose.prod.yml ps`.

## Dépannage

| Symptôme | Cause probable / solution |
|---|---|
| L'étape **VPN** échoue | Mêmes causes que pour ice-theaters : identifiants `VPN_*`, VPN Freebox désactivé, serveur injoignable. Essayez de relancer le job (*Re-run*) |
| `Permission denied (publickey)` | `SSH_KEY` incomplète (il faut la clé privée entière) ou `SSH_USER` incorrect |
| `denied` / `unauthorized` au `docker pull` | Le paquet GHCR n'autorise pas le dépôt : GitHub → *Packages* → `tools/backend` (et `frontend`) → *Package settings* → *Manage Actions access* → ajoutez le dépôt `tools` en **Read** |
| `POSTGRES_PASSWORD manquant dans .env` | `.env` absent ou incomplet sur le serveur : éditez `$DEPLOY_PATH/.env` (rappel : il n'est créé qu'une fois depuis `ENV_FILE`) |
| « L'API n'est pas devenue saine » | Lisez les journaux affichés dans l'étape *Deploy via SSH* (migration en échec, variable manquante). Le script a déjà remis l'ancienne version |
| `502 Bad Gateway` depuis le proxy | Le Hub ne répond pas sur le port : `docker compose -f docker-compose.prod.yml ps`, `curl -s http://127.0.0.1:31847/api/health` sur le serveur ; vérifiez `HUB_PORT` / `HUB_BIND` et la cible du proxy |
| `bind: address already in use` | Le `HUB_PORT` est déjà pris : choisissez-en un autre dans `.env` (et dans le proxy), puis redéployez |
| Connexion impossible / déconnexions en boucle | Le site doit être servi en **HTTPS** (cookies `Secure`) et le proxy doit envoyer `X-Forwarded-Proto` ; vérifiez `BASE_URL` et `COOKIE_SECURE=true` |
| Tout le monde semble venir de la même IP | Le proxy n'envoie pas `X-Forwarded-For` (voir le bloc nginx de l'étape 2) |
| `check-migrations` en rouge | Un modèle a changé sans migration : `cd backend && alembic revision --autogenerate -m "…"` puis commit |
| Le mot de passe admin ne marche pas | `ADMIN_PASSWORD` n'est lu qu'à la création de la base. Changez-le dans le Hub (Paramètres → Mon compte) |
| Outlook : « redirect URI mismatch » | L'URI chez Microsoft doit être exactement `https://<votre-domaine>/api/mail/callback` |
