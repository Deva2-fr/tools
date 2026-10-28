# Configuration pas à pas

Tout se règle à deux endroits :

1. le fichier **`.env`** (quelques lignes, une seule fois) ;
2. l'écran **Paramètres → Intégrations** du Hub (clés Microsoft, Google, e-mail…), sans toucher au serveur.

> 💡 Vous n'avez pas besoin de tout configurer d'un coup. Le suivi des sites et des impôts fonctionne dès le premier démarrage ; Outlook, Google et les alertes s'ajoutent quand vous voulez.

---

## 1. Le fichier `.env` (obligatoire)

```bash
make secrets      # crée .env avec des mots de passe aléatoires
```

Ouvrez `.env` et remplissez uniquement ces 4 lignes :

| Ligne | Quoi mettre | Exemple |
|---|---|---|
| `DOMAIN` | Le nom de domaine du Hub (à faire pointer vers votre serveur chez votre registrar : enregistrement **A** vers l'IP du serveur) | `hub.deva2.fr` |
| `BASE_URL` | Pareil avec `https://` devant | `https://hub.deva2.fr` |
| `ADMIN_EMAIL` | Votre e-mail (votre identifiant) | `vous@deva2.fr` |
| `ADMIN_PASSWORD` | Votre mot de passe (12 caractères minimum). Vous pourrez le changer ensuite | … |

Puis `make up`. Les ports **80 et 443** du serveur doivent être ouverts. Au premier lancement, connectez-vous puis allez dans **Paramètres → Mon compte** et **activez la 2FA**.

⚠️ Sauvegardez `ENCRYPTION_KEY` dans votre gestionnaire de mots de passe : c'est la clé qui protège les identifiants enregistrés.

---

## 2. Ajouter vos projets

*Projets & serveurs → + Ajouter un projet* (les trois sites **deva2.fr**, **formasyl.org** et **dev.icetheaters.deva2.fr** sont déjà créés).
Ouvrez un projet pour ajouter ses **serveurs** (hébergeur, IP, système…) et ses **technologies** (nom + version : `nginx 1.24`, `php 8.3`, `wordpress 6.6`…). Plus la version est précise, plus la veille de failles est fiable. Le Hub vérifie le site toutes les 5 minutes (modifiable).

> Si le site de dev est protégé par mot de passe (ex. renvoie 401), indiquez « Code HTTP attendu : 401 » dans le projet.

---

## 3. Outlook (lire vos mails et les étiqueter)

À faire une seule fois sur <https://entra.microsoft.com> (compte administrateur Microsoft 365) :

1. **Identité → Applications → Inscriptions d'applications → Nouvelle inscription**.
2. Nom : `Deva2 Hub`. Types de comptes : *« Comptes de cet annuaire uniquement »*.
3. **URI de redirection** → type **Web** → saisissez `https://<votre-domaine>/api/mail/callback` (l'adresse exacte est aussi affichée dans la page *Mails Outlook* du Hub).
4. Une fois créée, sur la page **Vue d'ensemble**, copiez :
   - **ID d'application (client)** → champ « Microsoft – ID de l'application »
   - **ID de l'annuaire (locataire)** → champ « Microsoft – ID de l'annuaire »
5. **Certificats et secrets → Nouveau secret client** → copiez la **Valeur** (visible une seule fois) → champ « Microsoft – Secret client ».
6. **Autorisations d'API → Ajouter une autorisation → Microsoft Graph → Déléguées** → cochez **`Mail.Read`** (et `User.Read`, `offline_access` s'ils ne sont pas déjà là) → *Accorder le consentement administrateur*.
7. Dans le Hub : **Paramètres → Intégrations → Outlook**, collez les 3 valeurs, puis **Mails Outlook → Se connecter avec Microsoft**.

Le Hub est en **lecture seule** : il ne peut ni envoyer, ni supprimer, ni modifier de mails.

**Comment est décidé « À répondre » ?** Le mail vient d'un humain (pas `noreply`/newsletter), contient une demande ou une question (« ? », « pouvez-vous », « devis », « relance »…) et **vous n'avez pas déjà répondu** dans la conversation. Les mots « urgent », « dernier rappel »… passent le mail en **Urgent**. Vous pouvez corriger n'importe quel tag à la main.

---

## 4. Google (notes de frais → PDF)

### a) Créer le modèle
Créez un **Google Doc** « Modèle note de frais » avec votre mise en page, et placez dedans les champs suivants, **tels quels** (accolades comprises) :

`{{numero}}` `{{date}}` `{{nom}}` `{{motif}}` `{{categorie}}` `{{projet}}` `{{moyen_paiement}}` `{{montant_ttc}}` `{{montant_ht}}` `{{tva}}` `{{taux_tva}}` `{{notes}}` `{{date_generation}}`

Exemple : « Note de frais n° {{numero}} du {{date}} — Salarié : {{nom}} — Motif : {{motif}} — Total TTC : {{montant_ttc}} (dont TVA {{tva}}) ».

Copiez l'**ID du Doc** : dans l'URL `https://docs.google.com/document/d/`**`CECI_EST_L_ID`**`/edit`.

### b) Créer le « robot » Google
1. <https://console.cloud.google.com> → créez un projet `deva2-hub`.
2. **API et services → Bibliothèque** → activez **Google Docs API** et **Google Drive API**.
3. **IAM et administration → Comptes de service → Créer** (nom : `deva2-hub`, pas de rôle nécessaire).
4. Ouvrez le compte de service → **Clés → Ajouter une clé → JSON** : un fichier `.json` se télécharge.
5. Notez l'**adresse e-mail du compte de service** (`deva2-hub@…iam.gserviceaccount.com`).
6. Dans Google Docs, **partagez le modèle** avec cette adresse (rôle *Lecteur*).

### c) Dans le Hub
**Paramètres → Intégrations → Google** :
- *Clé du compte de service* : ouvrez le fichier `.json` et **collez tout son contenu** ;
- *ID du modèle* : l'ID noté plus haut ;
- *Dossier de sortie* : facultatif (dossier Drive partagé avec le compte de service, en mode Éditeur).

Cliquez **Tester la connexion** → « modèle trouvé ✅ ». Ensuite, **Notes de frais → Enregistrer et télécharger le PDF** fait tout : copie du modèle, remplissage, PDF téléchargé. Le Doc temporaire est supprimé de Google ; le PDF reste archivé dans le Hub (lien « PDF » dans l'historique).

---

## 5. Recevoir les alertes

**Alertes & sécurité → Où recevoir les alertes ? → + Canal.** Choisissez :

| Canal | Ce qu'il faut |
|---|---|
| **Slack** | *api.slack.com/apps → Incoming Webhooks* : activez, « Add New Webhook to Workspace », choisissez le canal, copiez l'URL |
| **Discord** | Paramètres du salon → Intégrations → Webhooks → Nouveau → *Copier l'URL* |
| **Telegram** | Parlez à **@BotFather** (`/newbot`) → copiez le *jeton* ; écrivez à votre bot puis à **@userinfobot** pour obtenir votre *Chat ID* |
| **E-mail** | Remplissez d'abord **Paramètres → Intégrations → E-mail (SMTP)** : serveur (ex. `smtp.office365.com`), port `587`, utilisateur, mot de passe (préférez un *mot de passe d'application*), adresse d'expédition. Puis créez le canal avec l'adresse destinataire |
| **Webhook** | Une URL qui recevra un POST JSON `{title, message, severity}` |

Utilisez **Envoyer un test** pour vérifier. Chaque canal a un seuil (tout / attention+ / critique seulement).

**Quand suis-je alerté ?**
- 🚨 **Site down** : après 2 échecs consécutifs (anti-faux-positifs), puis message « rétabli » ;
- 🔒 **Certificat SSL** : expire dans moins de 14 jours (critique sous 3 jours) ou invalide ;
- ⚠️ **Attaque / anomalie** : ralentissement anormal (5× la normale), certificat modifié sans raison, ou alerte envoyée par un outil externe (webhook, voir README) ;
- 🛡️ **Faille critique** : CVE avec score CVSS ≥ 9 (réglable) sur une de vos technologies, ou faille déjà exploitée activement (catalogue CISA) ;
- 📅 **Échéances** : J-30, J-7, J-1, le jour J, puis chaque jour de retard.

---

## 6. Veille de failles (facultatif)

Sans rien faire, la veille fonctionne (lentement). Pour l'accélérer : demandez une clé **gratuite** sur <https://nvd.nist.gov/developers/request-an-api-key> et collez-la dans **Intégrations → Veille de sécurité**. Vous pouvez aussi y changer le **seuil CVSS** (9.0 par défaut ; 7.0 = plus d'alertes).
La recherche se fait par mot-clé : vérifiez toujours que votre version est concernée, puis cliquez « Ignorer » si ce n'est pas le cas.

---

## 7. Impôts & TVA

*Impôts & TVA → Pré-remplir* crée les échéances types de l'année (TVA mensuelle, acomptes et solde d'IS, CFE, URSSAF, dépôt des comptes, DAS2…). ⚠️ **Ce sont des dates indicatives** (société à l'IS, exercice = année civile) : faites-les confirmer par votre expert-comptable puis ajustez dates et montants. Vous pouvez ajouter vos propres échéances, avec répétition mensuelle / trimestrielle / annuelle : quand vous cliquez **« C'est payé »**, la suivante est créée automatiquement. **Exporter vers mon agenda** génère un fichier `.ics` (Outlook, Google Agenda…).

---

## 8. Ma société (pour les devis et factures)

**Paramètres → Intégrations → Ma société** : raison sociale, forme juridique et capital, SIRET, n° de TVA intracommunautaire, adresse, e-mail, téléphone, IBAN/BIC, délai de paiement par défaut (30 jours) et mentions légales éventuelles (ex. « TVA non applicable, art. 293 B du CGI » si vous êtes en franchise). Ces informations sont imprimées sur chaque PDF : **complétez-les avant d'émettre votre première facture.**

Le PDF contient déjà les mentions obligatoires usuelles (pénalités de retard, indemnité forfaitaire de 40 €). Faites valider le modèle par votre expert-comptable.

**Comment marche la facturation ?**
1. *Devis & factures → + Devis* : choisissez le client, ajoutez des lignes (le total se calcule seul, TVA par taux). Enregistrez : c'est un **brouillon** modifiable, sans numéro.
2. **Émettre** : le numéro définitif est attribué (`DEV-2026-0001`, `FAC-2026-0001`…, sans trou, par année). Une facture émise **ne peut plus être modifiée** (obligation légale) : pour corriger, on l'annule et on en crée une nouvelle.
3. Devis accepté → **Transformer en facture** (les lignes sont recopiées).
4. Encaissement → **Enregistrer le paiement** (paiements partiels possibles) : la facture passe « Payée » quand le solde est à zéro.
5. Impayé : le Hub alerte à J-3 de l'échéance, puis à J+1, J+7, J+15, J+30… sur vos canaux d'alerte.

## 9. Utilisateurs et rôles

**Paramètres → Utilisateurs → + Utilisateur.** *Membre* : CRM, tâches, saisie de son temps, demande de congés, notes de frais. *Manager* : en plus, devis/factures, trésorerie, abonnements, équipe, documents, accès. *Administrateur* : en plus, réglages, intégrations et utilisateurs.
Pour qu'un membre puisse poser des congés, créez sa fiche dans **Équipe → Collaborateurs** avec **le même e-mail que son compte**.

## 10. Page de statut publique

Cochez « Afficher sur la page de statut publique » dans un projet : `https://<votre-domaine>/statut` montre alors, sans connexion, son nom et son état (rien d'autre : ni lien, ni serveur, ni note).

## 11. Mise à jour depuis la v1

Rien à faire : au démarrage, la base existante est reconnue et migrée automatiquement (Alembic). **Faites tout de même une sauvegarde du volume `pgdata` avant `make up`.**

---

## Dépannage rapide

| Symptôme | Cause probable |
|---|---|
| Le site du Hub n'ouvre pas en HTTPS | Le DNS ne pointe pas encore vers le serveur, ou les ports 80/443 sont fermés (`make logs`) |
| « Microsoft a refusé la connexion » | L'URI de redirection ne correspond pas **exactement** à celle affichée dans le Hub |
| « Modèle introuvable » (Google) | Le Doc n'est pas partagé avec l'e-mail du compte de service |
| Aucune alerte reçue | Aucun canal créé, ou seuil trop haut ; utilisez « Envoyer un test » |
| « Aucune fiche collaborateur à votre e-mail » (congés) | Créez le collaborateur dans Équipe → Collaborateurs avec le même e-mail que son compte |
| Le PDF de facture affiche « Votre société » | Complétez Paramètres → Intégrations → Ma société |
| Un site de dev apparaît « Hors ligne » | Il renvoie 401/403 : renseignez le *code HTTP attendu* |
