# Lancer Deva2 Hub sur votre poste

Ce guide part de zéro : il suffit d'un ordinateur (Windows, Mac ou Linux). Comptez 15 minutes pour le démarrage, puis le temps de remplir vos informations.

---

## 1. Installer les 2 outils nécessaires

| Outil | À quoi il sert | Où le télécharger |
|---|---|---|
| **Docker Desktop** | fait tourner tout le Hub (base de données, API, site) | <https://www.docker.com/products/docker-desktop/> |
| **Git** | récupère le code | <https://git-scm.com/downloads> |

Après l'installation de Docker Desktop, **lancez-le** et attendez que la petite baleine indique « Docker Desktop is running ». Sous Windows, acceptez l'activation de WSL 2 si on vous le propose, puis redémarrez.

> Vérification : ouvrez un terminal (*PowerShell* sous Windows, *Terminal* sous Mac/Linux) et tapez `docker --version` puis `git --version`. Les deux doivent afficher un numéro de version.

---

## 2. Récupérer le projet

```bash
git clone https://github.com/Deva2-fr/tools.git
cd tools
git checkout claude/adoring-wozniak-74avhv
```

(La dernière ligne sert tant que le projet n'est pas fusionné dans la branche principale.)

---

## 3. Créer le fichier de configuration `.env`

### Sur Mac / Linux

```bash
make secrets
```

Cela crée `.env` avec des mots de passe aléatoires. (Si `make` n'existe pas : `cp .env.example .env` puis faites comme sous Windows.)

### Sur Windows (PowerShell)

```powershell
Copy-Item .env.example .env
# Génère 4 secrets aléatoires et les écrit dans .env
function Secret($n) { -join ((48..57)+(97..102) | Get-Random -Count $n | ForEach-Object {[char]$_}) }
(Get-Content .env) `
  -replace '^POSTGRES_PASSWORD=.*', "POSTGRES_PASSWORD=$(Secret 32)" `
  -replace '^SECRET_KEY=.*',        "SECRET_KEY=$(Secret 32)$(Secret 32)" `
  -replace '^ENCRYPTION_KEY=.*',    "ENCRYPTION_KEY=$(Secret 32)$(Secret 32)" `
  -replace '^WEBHOOK_TOKEN=.*',     "WEBHOOK_TOKEN=$(Secret 32)" | Set-Content .env
```

### Puis ouvrez `.env` dans un éditeur (Bloc-notes, VS Code…) et modifiez ces lignes

| Ligne | Pour un test sur votre poste | Pour un vrai serveur en ligne |
|---|---|---|
| `DOMAIN` | `localhost` | `hub.deva2.fr` (votre nom de domaine) |
| `BASE_URL` | `https://localhost` | `https://hub.deva2.fr` |
| `ADMIN_EMAIL` | votre e-mail (ce sera votre identifiant) | idem |
| `ADMIN_PASSWORD` | un mot de passe de **12 caractères minimum** | idem |
| `COOKIE_SECURE` | `true` (laissez tel quel) | `true` |
| `TIMEZONE` | `Europe/Paris` | `Europe/Paris` |

**Ne touchez pas** à `POSTGRES_PASSWORD`, `SECRET_KEY`, `ENCRYPTION_KEY`, `WEBHOOK_TOKEN` (déjà remplis).

> ⚠️ **Copiez `ENCRYPTION_KEY` dans votre gestionnaire de mots de passe.** Si vous la perdez, les clés enregistrées dans le Hub (Microsoft, Google, SMTP…) deviennent illisibles. Ne publiez jamais le fichier `.env`.

---

## 4. Démarrer

```bash
docker compose up -d --build
```

La première fois, c'est long (5 à 10 min : téléchargement et construction). Suivez l'avancement avec :

```bash
docker compose logs -f --tail=50
```

(`Ctrl + C` pour quitter l'affichage, le Hub continue de tourner.) Quand `docker compose ps` montre `api`, `db` et `caddy` en `running` / `healthy`, c'est prêt.

> **Ports 80 et 443 déjà utilisés ?** (un autre serveur web, Skype…) Fermez l'autre programme, puis relancez `docker compose up -d`.

## 5. Ouvrir le Hub

Allez sur **<https://localhost>**.

Votre navigateur affiche un avertissement (« connexion non privée ») : c'est normal en local, le certificat est généré par votre propre machine. Cliquez sur *Paramètres avancés → Continuer vers localhost*.

Connectez-vous avec `ADMIN_EMAIL` et `ADMIN_PASSWORD`.

**Premières minutes, dans l'ordre :**
1. **Paramètres → Mon compte** : activez la **double authentification** (QR code à scanner avec Google Authenticator, Authy ou 1Password).
2. Changez votre mot de passe si vous le souhaitez.

---

## 6. Tout ce qu'il y a à remplir, dans l'ordre conseillé

Cochez au fur et à mesure. **Rien n'est obligatoire d'un coup** : chaque module fonctionne dès que sa partie est remplie.

### A. Indispensable pour facturer — *Paramètres → Intégrations → Ma société*

| Champ | Exemple |
|---|---|
| Raison sociale | Deva2 |
| Forme juridique & capital | SAS au capital de 1 000 € |
| SIRET | 123 456 789 00012 |
| N° de TVA intracommunautaire | FR12345678901 |
| Adresse complète | 1 rue de la Paix, 75002 Paris |
| E-mail / Téléphone | contact@deva2.fr |
| IBAN / BIC | affichés sur les factures pour le virement |
| Délai de paiement par défaut | 30 (jours) |
| Mentions légales additionnelles | ex. « TVA non applicable, art. 293 B du CGI » si franchise de TVA |

→ Sans ça, vos PDF afficheront « Votre société ».

### B. Vos sites — *Projets & serveurs*

Les trois sites (**deva2.fr**, **formasyl.org**, **dev.icetheaters.deva2.fr**) sont déjà créés. Pour chacun, ouvrez-le et ajoutez :
- **Serveurs** : hébergeur, adresse IP, système, localisation. ⚠️ jamais de mot de passe, seulement « SSH par clé, utilisateur deploy ».
- **Technologies avec leur version** (ex. `nginx 1.24`, `php 8.3`, `wordpress 6.6`) : c'est ce qui permet de détecter les failles de sécurité.
- Si le site de dev est protégé par mot de passe : « Code HTTP attendu » = `401`.
- Cochez « page de statut publique » pour les sites que vos clients peuvent voir sur `/statut`.

### C. Recevoir les alertes — *Alertes & sécurité → + Canal*

Au moins un canal, puis **Envoyer un test** :

| Canal | Ce qu'il faut copier |
|---|---|
| **Slack** | l'URL d'un *Incoming Webhook* (api.slack.com/apps) |
| **Discord** | Paramètres du salon → Intégrations → Webhooks → Copier l'URL |
| **Telegram** | le jeton du bot (via @BotFather) + votre Chat ID (via @userinfobot) |
| **E-mail** | d'abord la section D ci-dessous, puis l'adresse destinataire |

### D. E-mail d'envoi des alertes (facultatif) — *Intégrations → E-mail (SMTP)*

| Champ | Exemple |
|---|---|
| Serveur SMTP | `smtp.office365.com` (Microsoft 365) ou `smtp.gmail.com` (Google) |
| Port | `587` |
| Utilisateur | votre adresse e-mail |
| Mot de passe | un **mot de passe d'application** (pas votre mot de passe habituel) |
| Adresse d'expédition | hub@deva2.fr |

Bouton **Tester la connexion** → doit afficher ✅.

### E. Mails (facultatif) — *Intégrations → Boîtes mail (IMAP)*

Les mêmes réglages que dans Outlook (*Fichier → Paramètres du compte*) : **serveur IMAP** (ex. `ssl0.ovh.net`), **port 993**, **identifiant** (l'adresse e-mail) et **mot de passe**. Une boîte par adresse (**+ Boîte mail**), puis *Tester la connexion* et **Mails → Actualiser** : chaque boîte a son bouton dans la page Mails. Détails et hébergeurs courants : [CONFIGURATION.md, section 3](CONFIGURATION.md#3-boîte-mail-lire-vos-mails-et-repérer-ceux--à-répondre-). Microsoft 365 reste possible (annexe de la même section).

### F. Notes de frais dans Google Drive (facultatif) — *Intégrations → Google Drive*

Le PDF est généré par le Hub ; Google sert seulement à le ranger dans **Deva2 › Administration › Comptabilité › Note de frais**.
1. Sur <https://console.cloud.google.com> : nouveau projet → activez **Google Drive API** → *Comptes de service* → créer → *Clés → Ajouter une clé → JSON* (un fichier se télécharge).
2. Le dossier « Note de frais » doit être dans un **Drive partagé** : ajoutez-y l'e-mail du compte de service comme **Gestionnaire de contenu** (ou partagez le dossier en **Éditeur**).
3. Dans le Hub : collez **tout le contenu du fichier JSON**, puis l'**ID du dossier** (la fin de l'URL après `/folders/`). *Tester la connexion* doit trouver le dossier.

### G. Veille de failles (facultatif) — *Intégrations → Veille de sécurité*

Clé API NVD **gratuite** : <https://nvd.nist.gov/developers/request-an-api-key>. Seuil d'alerte CVSS : `9.0` par défaut (mettez `7.0` pour être alerté plus souvent).

### H. Votre équipe — *Paramètres → Utilisateurs* puis *Équipe → Collaborateurs*

1. **+ Utilisateur** : e-mail, mot de passe provisoire (12 caractères min.), rôle :
   - **Membre** : CRM, tâches, temps, notes de frais ;
   - **Manager** : + factures, trésorerie, abonnements, équipe, documents ;
   - **Administrateur** : + réglages et utilisateurs.
2. **Collaborateurs** : une fiche par personne avec **le même e-mail que son compte** (nécessaire pour le calcul du temps) et son coût journalier.

### I. Vos données métier

| Où | Quoi |
|---|---|
| **Sociétés / Contacts** | ajoutez-les ou importez un CSV (bouton *Importer un CSV*) |
| **Pipeline** | vos affaires en cours (glissez les cartes d'étape en étape) |
| **Trésorerie** | + Compte avec son **solde actuel**, puis importez le CSV de votre banque (colonnes Date, Libellé, Montant) |
| **Abonnements & contrats** | domaines (deva2.fr, formasyl.org…), hébergement, assurances, logiciels, avec **date de renouvellement** et « m'alerter N jours avant » |
| **Impôts & TVA** | bouton *Pré-remplir l'année* puis **faites valider les dates par votre comptable** |
| **Registre des accès** | où est chaque mot de passe (jamais le mot de passe lui-même) |
| **Documents** | Kbis, statuts, contrats, assurances (PDF, Word, Excel, images ; 15 Mo max) |

---

## 7. Utilisation au quotidien

```bash
docker compose up -d        # démarrer
docker compose down         # arrêter (les données sont conservées)
docker compose logs -f api  # voir ce que fait l'API (en cas de souci)
git pull && docker compose up -d --build   # mettre à jour
```

- Le Hub surveille vos sites, envoie les alertes et les résumés **uniquement tant qu'il tourne**. Sur un ordinateur portable éteint, rien ne se passe : pour une utilisation réelle, installez-le sur un petit serveur (VPS) allumé en permanence, avec un nom de domaine (voir le bas de cette page).
- **Sauvegarde** : copiez régulièrement la base avec
  `docker compose exec db pg_dump -U hub hub > sauvegarde-$(date +%F).sql`
  (sous PowerShell : `docker compose exec db pg_dump -U hub hub | Out-File sauvegarde.sql`), et conservez votre `.env`.

## 8. Mettre le Hub sur un vrai serveur (pour qu'il tourne 24 h/24)

> **Déploiement automatisé (GitHub Actions, merge sur `main`) : suivez plutôt [`DEPLOIEMENT.md`](DEPLOIEMENT.md).** Les étapes ci-dessous décrivent l'installation manuelle.

1. Louez un petit serveur Linux (2 Go de RAM suffisent) chez OVH, Hetzner, Scaleway…
2. Chez votre registrar, créez un enregistrement DNS **A** : `hub.deva2.fr` → IP du serveur.
3. Sur le serveur : installez Docker, ouvrez les ports **80** et **443**, clonez le projet.
4. Dans `.env` : `DOMAIN=hub.deva2.fr`, `BASE_URL=https://hub.deva2.fr`, vos identifiants admin.
5. `docker compose up -d --build` : le certificat HTTPS officiel (Let's Encrypt) est obtenu automatiquement.
6. Mettez à jour l'URI de redirection Microsoft avec ce nouveau domaine.

---

## Problèmes fréquents

| Symptôme | Solution |
|---|---|
| `docker: command not found` / `Cannot connect to the Docker daemon` | Docker Desktop n'est pas lancé : ouvrez-le et attendez qu'il soit « running » |
| `POSTGRES_PASSWORD ... missing a value` | Le fichier `.env` n'existe pas ou est vide : refaites l'étape 3 |
| `port is already allocated` (80/443) | Un autre programme utilise ces ports : fermez-le |
| La page ne s'ouvre pas | Attendez 1 à 2 minutes après le démarrage ; `docker compose ps` doit montrer `api` en `healthy` |
| Connexion impossible avec mon mot de passe | `ADMIN_PASSWORD` n'est lu qu'à la **toute première** création de la base. Changez-le dans Paramètres → Mon compte, ou supprimez les données de test (`docker compose down -v`, **efface tout**) puis relancez |
| « Le serveur IMAP refuse l'identifiant » | Vérifiez identifiant et mot de passe dans Outlook (Fichier → Paramètres du compte) |
| « Dossier Drive introuvable » (Google) | Le dossier « Note de frais » n'est pas partagé avec l'adresse e-mail du compte de service |
| Aucune alerte reçue | Aucun canal créé, ou seuil trop haut : utilisez *Envoyer un test* |
| Un site de dev apparaît « Hors ligne » | Il répond 401/403 : renseignez le « Code HTTP attendu » du projet |
| Le PDF de facture affiche « Votre société » | Complétez *Intégrations → Ma société* (section 6.A) |

Le détail complet de chaque intégration se trouve dans [`CONFIGURATION.md`](CONFIGURATION.md).
