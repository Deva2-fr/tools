# Deva2 Hub

Application interne qui centralise les outils de la société **Deva2** :

| Module | Ce que ça fait |
|---|---|
| 🌐 **Projets & serveurs** | Fiche de chaque site (formasyl.org, dev.icetheaters.deva2.fr, deva2.fr…) : lien, serveurs (hébergeur, IP, OS…), technologies, outils de monitoring, état en direct |
| 🚨 **Monitoring & alertes** | Vérifie chaque site (disponibilité, temps de réponse, certificat SSL, en-têtes de sécurité) et alerte par e-mail / Slack / Discord / Telegram en cas de panne, d'attaque probable ou de certificat qui expire |
| 🛡️ **Veille sécurité** | Compare vos technologies (nginx, PHP, WordPress…) à la base NVD et au catalogue CISA des failles activement exploitées → alerte si faille critique |
| ✉️ **Mails Outlook** | Lit votre boîte (lecture seule) et tague **« À répondre »**, **« Urgent »**, **« Répondu »** |
| 🧾 **Notes de frais** | Formulaire → remplit un Google Doc modèle → **télécharge le PDF** |
| 📅 **Impôts & TVA** | Calendrier des échéances (TVA, IS, CFE, URSSAF…) avec rappels J-30 / J-7 / J-1, export agenda `.ics` |

Tout est modifiable depuis l'interface (ajout/modification/suppression de projets, serveurs, canaux d'alerte, échéances, utilisateurs, clés d'API).

## Démarrage rapide

```bash
make secrets        # crée .env avec des secrets aléatoires
nano .env           # renseignez DOMAIN, BASE_URL, ADMIN_EMAIL, ADMIN_PASSWORD
make up             # construit et lance tout (Docker)
```

Ouvrez ensuite `https://<DOMAIN>` et connectez-vous. **Suite : [docs/CONFIGURATION.md](docs/CONFIGURATION.md)** (Outlook, Google, alertes… expliqué pas à pas) et [docs/IDEES.md](docs/IDEES.md) (idées d'évolutions).

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
  models.py   tables SQLAlchemy (créées au démarrage)
  routers/    API REST : auth, projects, alerts, security, mail, expenses, taxes, integrations…
  services/   logique métier : monitoring, security_watch (CVE), outlook (Graph), google_docs, taxes, alerts
  worker.py   tâches planifiées (sites chaque minute selon leur fréquence, mails /5 min, CVE 3h15, rappels d'impôts 8h30)
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
- Rôles : *Admin* (réglages, intégrations, utilisateurs) / *Membre*.
- **Sauvegardez** le volume `pgdata` **et** votre `ENCRYPTION_KEY` (sans elle, les clés enregistrées sont illisibles).

## Développement

```bash
make dev                                                                 # Docker avec rechargement auto (API sur :8000)
cd backend && pip install -r requirements-dev.txt && python -m pytest    # 22 tests
cd frontend && npm install && npm run dev                                # http://localhost:5173
make lint
```

Webhook pour brancher un outil externe (Uptime Kuma, CrowdSec, script fail2ban…) :

```bash
curl -X POST https://<DOMAIN>/api/webhooks/security \
  -H "X-Webhook-Token: <WEBHOOK_TOKEN>" -H "Content-Type: application/json" \
  -d '{"title":"Brute force SSH détecté","severity":"critical","project":"Deva2"}'
```
