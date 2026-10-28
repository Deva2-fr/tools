# Deva2 Hub

Application interne qui centralise **tout le pilotage de la société Deva2** : relation client (CRM), facturation, finances, équipe et infrastructure.

| Domaine | Modules |
|---|---|
| 🤝 **Commercial (CRM)** | **Sociétés** et **contacts** (fiche complète : activités, mails liés, devis/factures, tâches), **pipeline** en Kanban (glisser-déposer) avec prévision de CA pondérée, **tâches** et journal d'activité, import/export CSV, recherche globale **⌘K** |
| 💶 **Finances** | **Devis & factures** (importés de **Qonto** ou créés dans le Hub : numérotation continue sans trou, TVA par taux, PDF, paiements partiels, devis → facture, relances automatiques des impayés), **trésorerie** (comptes, import CSV bancaire, prévision à 30/90/180 j), **abonnements, domaines & contrats** (rappels de renouvellement, coût annuel, factures liées), **notes de frais** (PDF rangé dans Google Drive), **impôts & TVA** (échéances + rappels, export agenda) |
| 👥 **Équipe** | Collaborateurs, **check-lists** arrivée/départ, **suivi du temps** et **rentabilité par client**, **coffre de documents**, **registre des accès** (sans mots de passe) |
| 🌐 **Infrastructure** | **Projets & serveurs** (formasyl.org, dev.icetheaters.deva2.fr, deva2.fr…), **monitoring** (disponibilité, SSL, en-têtes), **alertes** e-mail/Slack/Discord/Telegram (panne, attaque probable, faille critique), **veille CVE** (NVD + CISA KEV), **page de statut publique** `/statut` |
| ✉️ **Mails** | Boîte mail (**IMAP**, ou Microsoft 365) en lecture seule avec tags « À répondre » / « Urgent » / « Répondu » |
| 📣 **Pilotage** | **Résumé quotidien** à 8h50 (mails, tâches, factures en retard, échéances, renouvellements) et **tableau de bord** adapté au rôle |

Trois rôles : **Membre** (CRM, tâches, temps, notes de frais), **Manager** (+ finances, équipe, documents, accès), **Administrateur** (+ réglages, intégrations, utilisateurs).

Tout est modifiable depuis l'interface (ajout/modification/suppression partout).

## Démarrage rapide

> **Mise en production (CI/CD, merge sur `main`) : [docs/DEPLOIEMENT.md](docs/DEPLOIEMENT.md).**
>
> **Première fois ? Suivez le guide pas à pas : [docs/DEMARRAGE.md](docs/DEMARRAGE.md)** (installation sur votre poste, tout ce qu'il faut remplir, dépannage).

```bash
make secrets        # crée .env avec des secrets aléatoires
nano .env           # renseignez DOMAIN, BASE_URL, ADMIN_EMAIL, ADMIN_PASSWORD
make up             # construit et lance tout (Docker)
```

Ouvrez ensuite `https://<DOMAIN>` et connectez-vous. **Suite : [docs/CONFIGURATION.md](docs/CONFIGURATION.md)** (boîte mail, Google Drive, Qonto, alertes… expliqué pas à pas) et [docs/IDEES.md](docs/IDEES.md) (idées d'évolutions).

En local sans domaine : `DOMAIN=localhost`, `BASE_URL=https://localhost` (Caddy fournit un certificat local ; le navigateur affichera un avertissement à accepter).

## Architecture

```
Internet ──443──▶ Caddy (HTTPS auto, en-têtes de sécurité)
                    ├── /api/*  ──▶ api      (FastAPI)  ──┐
                    └── /*      ──▶ frontend (React, nginx)│
                                    worker   (APScheduler) ┼──▶ db (PostgreSQL, réseau isolé)
```

```
backend/app/
  core/       configuration, base de données, sécurité (sessions, CSRF, limiteur), chiffrement
  models.py   tables SQLAlchemy ; le schéma est géré par Alembic (alembic/versions, appliqué au démarrage)
  routers/    API REST : auth, crm, billing, ops (abonnements, trésorerie, temps, équipe, fichiers), projects, alerts…
              (_common.py : fabrique de routes CRUD réutilisée par la plupart des modules)
  services/   logique métier : billing (+PDF), treasury, renewals, digest, monitoring, security_watch, mail_imap, outlook, qonto, qonto_billing, expense_pdf, google_drive, taxes, alerts
  worker.py   tâches planifiées (sites chaque minute selon leur fréquence, mails /5 min, CVE 3h15, puis 8h30-8h50 : impôts, factures, renouvellements, résumé du jour)
frontend/src/ pages React (une par module) + petit kit UI (ui.tsx)
caddy/        reverse proxy
docs/         guides
```

Services Docker : `caddy` (seul exposé : 80/443), `api`, `worker` (même image), `frontend`, `db`.

## Sécurité

- Connexion par cookie `HttpOnly`, **2FA TOTP** optionnelle (recommandée), mots de passe **Argon2**, limitation des essais (5 / 15 min), journal d'audit.
- Protection CSRF (en-tête obligatoire sur toute écriture), CSP / HSTS / anti-clickjacking via Caddy, pas de documentation d'API publique.
- Tokens et clés d'API **chiffrés en base** (Fernet, clé `ENCRYPTION_KEY`) et jamais renvoyés au navigateur.
- Conteneurs non-root, système de fichiers en lecture seule, `cap_drop: ALL`, `no-new-privileges`, base de données sur un réseau Docker **sans accès Internet** et sans port publié.
- Rôles *Admin / Manager / Membre* vérifiés côté serveur sur chaque route (les chiffres financiers sont masqués aux membres, même dans les fiches clients).
- Fichiers : extension autorisée + vérification du contenu + 15 Mo max + nom aléatoire, téléchargement authentifié ; exports CSV protégés contre l'injection de formules ; factures émises **immuables** et numérotées sans trou.
- **Sauvegardez** le volume `pgdata` **et** votre `ENCRYPTION_KEY` (sans elle, les clés enregistrées sont illisibles).

## Développement

```bash
make dev                                                                 # Docker avec rechargement auto (API sur :8000)
cd backend && pip install -r requirements-dev.txt && python -m pytest    # 54 tests
cd frontend && npm install && npm run dev                                # http://localhost:5173
make lint
```

Webhook pour brancher un outil externe (Uptime Kuma, CrowdSec, script fail2ban…) :

```bash
curl -X POST https://<DOMAIN>/api/webhooks/security \
  -H "X-Webhook-Token: <WEBHOOK_TOKEN>" -H "Content-Type: application/json" \
  -d '{"title":"Brute force SSH détecté","severity":"critical","project":"Deva2"}'
```
