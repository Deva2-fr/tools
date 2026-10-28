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
| `BASE_URL` | Pareil avec `https://` devant. Sert aux adresses de retour OAuth (Qonto, Microsoft) : s'il est resté sur `localhost`, le Hub prend le domaine par lequel vous l'ouvrez. L'adresse exacte à déclarer est affichée dans Paramètres | `https://hub.deva2.fr` |
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

## 3. Boîte mail (lire vos mails et repérer ceux « à répondre »)

Votre messagerie est sur un serveur mail classique, celui qu'interroge l'application Outlook. Le Hub le lit en **IMAP** (le SMTP ne sert qu'à envoyer).

**Retrouver les réglages dans Outlook** : *Fichier → Paramètres du compte → Paramètres du compte… → double-clic sur l'adresse → Plus de paramètres → Options avancées*. Vous y lisez le **serveur entrant (IMAP)** et son **port**. Sur le nouvel Outlook, ou si le compte est en POP, demandez ces informations à votre hébergeur.

| Hébergeur | Serveur IMAP | Port |
|---|---|---|
| OVHcloud (MX Plan) | `ssl0.ovh.net` | 993 |
| IONOS | `imap.ionos.fr` | 993 |
| Gandi | `mail.gandi.net` | 993 |
| o2switch / cPanel | `mail.<votre-domaine>` | 993 |

Dans le Hub : **Paramètres → Intégrations → Boîtes mail (IMAP) → + Boîte mail**, une fois **par adresse** à suivre (contact@, compta@, votre boîte personnelle…) :
- *Nom du bouton* : ce qui s'affiche dans la page Mails (ex. « Contact », « Compta ») ;
- *Serveur IMAP* et *Port* : voir ci-dessus (993 = SSL, recommandé ; 143 = STARTTLS, accepté) ;
- *Identifiant* : en général l'adresse e-mail complète ; *Mot de passe* : celui de la boîte (stocké chiffré, jamais réaffiché ; laissez vide en modification pour le garder) ;
- *Dossier des envoyés* : à laisser vide, il est détecté seul (« Sent », « Éléments envoyés »…). Renseignez-le seulement si le test dit qu'il est introuvable ;
- *Adresse du webmail* : facultatif (ex. `https://www.ovh.com/fr/mail/`), pour le bouton **Ouvrir le webmail**.

Cliquez **Tester la connexion** sur la ligne de la boîte (« Connexion OK – N message(s)… »), puis **Mails → Actualiser**. Toutes les boîtes actives sont ensuite relues **toutes les 5 minutes**. Le Hub importe **toute la boîte de réception** (jusqu'aux 5 000 mails les plus récents) : le premier import se fait par paquets de 400, en quelques minutes, puis seuls les nouveaux mails sont téléchargés ; les drapeaux (lu, répondu) sont relus à chaque passage et un mail supprimé ou déplacé sur le serveur disparaît du Hub. La page **Mails** fonctionne comme une messagerie : à gauche les boîtes et les filtres (À traiter, Tous les mails, Répondus, Informations), au milieu la liste avec recherche, à droite le mail **complet** quand on clique dessus (texte ou mise en forme, pièces jointes à télécharger, boutons de tag). Le mail est lu à la demande sur le serveur, sans le marquer comme lu ; les images distantes sont bloquées par défaut (« Afficher les images »). Dans la page **Mails**, un bouton par boîte (avec le nombre de mails à traiter) permet de passer de l'une à l'autre ; « Toutes les boîtes » les regroupe. Une boîte en erreur (mot de passe changé…) est signalée par un point rouge sans bloquer les autres.

Si vous aviez déjà renseigné une boîte unique avant cette version, elle est reprise automatiquement comme première boîte.

Le Hub est en **lecture seule** : il ne marque aucun mail comme lu, n'envoie, ne déplace ni ne supprime rien.

**Comment sont attribués les tags ?** (aussi expliqué en bas de la page Mails) Le mail vient d'un humain (pas `noreply`/newsletter), contient une demande ou une question (« ? », « pouvez-vous », « devis », « relance »…) et **vous n'avez pas encore répondu**. Une réponse est détectée grâce au drapeau « répondu » qu'Outlook pose sur le mail, ou grâce au dossier des envoyés, ce qui couvre aussi les réponses faites depuis le téléphone. Les mots « urgent », « dernier rappel »… passent le mail en **Urgent**. Vous pouvez corriger n'importe quel tag à la main ; une fois la réponse envoyée, le mail repasse en « Traité » tout seul.

### Annexe : boîte hébergée chez Microsoft 365
Uniquement si votre messagerie est un vrai Microsoft 365 (Exchange Online), qui n'accepte plus l'IMAP par mot de passe. Laissez alors le groupe IMAP vide.

1. <https://entra.microsoft.com> → **Identité → Applications → Inscriptions d'applications → Nouvelle inscription** (nom `Deva2 Hub`, *comptes de cet annuaire uniquement*).
2. **URI de redirection** (Web) : `https://<votre-domaine>/api/mail/callback`.
3. Copiez l'**ID d'application** et l'**ID de l'annuaire** ; créez un **secret client** (Certificats et secrets) et copiez sa valeur.
4. **Autorisations d'API → Microsoft Graph → Déléguées** : `Mail.Read` (+ `User.Read`, `offline_access`) → consentement administrateur.
5. **Paramètres → Intégrations → Microsoft 365**, collez les 3 valeurs, puis **Mails → Se connecter avec Microsoft**.

---

## 4. Google Drive (notes de frais en PDF)

Le Hub génère lui-même le PDF de la note de frais (aucun modèle à créer). Chaque note est rattachée à un **utilisateur du Hub** (un membre ne saisit et ne voit que les siennes ; un manager peut saisir pour n'importe qui). La note porte **trois signatures** : le **demandeur**, le **président** et l'**associé**. Désignez une fois pour toutes le président et l'associé dans **Paramètres → Intégrations → Signataires des notes de frais** : ils voient alors toutes les notes et y apposent leur propre signature (un manager peut aussi les apposer). Une signature se dessine à la souris ou au doigt (bouton **+ Nouvelle**) ou s'importe en image ; chacun a ses propres signatures, réutilisables, et peut les supprimer (bouton « Supprimer » sous la signature, ou depuis son **profil**). Jusqu'à **10 justificatifs** (tickets, factures : PDF, JPG ou PNG, 10 Mo max. chacun) sont ajoutés à la fin du PDF : un seul fichier contient la note signée et ses preuves. À chaque **Enregistrer**, le PDF est téléchargé sur votre poste **et** déposé dans Google Drive, dans **Deva2 › Administration › Comptabilité › Note de frais**. Si vous modifiez une note, le même fichier Drive est remplacé (pas de doublon).

### a) Créer le « robot » Google (une seule fois)
1. <https://console.cloud.google.com> → créez un projet `deva2-hub`.
2. **API et services → Bibliothèque** → activez **Google Drive API**.
3. **IAM et administration → Comptes de service → Créer** (nom : `deva2-hub`, aucun rôle nécessaire).
4. Ouvrez le compte de service → **Clés → Ajouter une clé → JSON** : un fichier `.json` se télécharge.
5. Notez l'**adresse e-mail du compte de service** (`deva2-hub@…iam.gserviceaccount.com`).

### b) Donner accès au dossier « Note de frais »
- **Le dossier doit être dans un Drive partagé** (Google Workspace : *Drive partagés*). Un compte de service n'a pas d'espace de stockage à lui : dans « Mon Drive », Google refuse le dépôt.
- Ajoutez l'e-mail du compte de service comme membre du Drive partagé, avec le rôle **Gestionnaire de contenu** (ou partagez seulement le dossier « Note de frais » en **Éditeur**).
- Ouvrez le dossier « Note de frais » et copiez la fin de l'URL : `https://drive.google.com/drive/folders/`**`CECI_EST_L_ID`**.

### c) Dans le Hub
**Paramètres → Intégrations → Google Drive (notes de frais)** :
- *Clé du compte de service* : ouvrez le fichier `.json` et **collez tout son contenu** ;
- *ID du dossier « Note de frais »* : l'ID copié (l'URL complète du dossier est aussi acceptée).

Cliquez **Tester la connexion** → « les notes de frais seront déposées dans « Note de frais » ». Si Google est indisponible ou mal réglé, le PDF est **quand même** téléchargé et archivé dans le Hub ; un message l'indique, et le bouton **Envoyer dans Drive** de l'historique permet de réessayer.

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

*Impôts & TVA → Pré-remplir* crée les échéances types de l'année : **TVA trimestrielle** (CA3 vers le 20 janvier, avril, juillet et octobre, pour le trimestre écoulé), **déclaration annuelle de résultats** (liasse fiscale vers le 15 mai, avec le relevé de solde d'IS s'il y a de l'IS à payer : pas d'acomptes) et **CFE** (15 décembre). Pas d'URSSAF. ⚠️ **Ce sont des dates indicatives** (société à l'IS, exercice = année civile) : faites-les confirmer par votre expert-comptable puis ajustez dates et montants. Vous pouvez ajouter vos propres échéances, avec répétition mensuelle / trimestrielle / annuelle : quand vous cliquez **« C'est payé »**, la suivante est créée automatiquement. **Exporter vers mon agenda** génère un fichier `.ics` (Outlook, Google Agenda…).

**Synchroniser avec Google Agenda** (utilise la même clé Google que les notes de frais, section 4) :
1. Dans la console Google Cloud du projet `deva2-hub`, activez aussi **Google Calendar API**.
2. Dans Google Agenda, ouvrez les **Paramètres de l'agenda** voulu (créez par exemple un agenda « Deva2 – Échéances ») → **Partager avec des personnes** → ajoutez l'e-mail du compte de service avec le droit **« Apporter des modifications aux événements »**.
3. Dans le Hub, **Impôts & TVA → Google Agenda → + Ajouter un agenda** : collez l'**ID de l'agenda** (section « Intégrer l'agenda »). Il apparaît alors dans la liste : choisissez-le.

Chaque échéance devient un événement « journée entière » (rouge, rappels 7 jours et 1 jour avant ; vert et sans rappel une fois payée). Création, modification, paiement et suppression sont reportés aussitôt, et tout est resynchronisé chaque heure. Choisir « Aucun agenda » arrête la synchronisation.

---

## 8. Ma société (pour les devis et factures)

**Paramètres → Intégrations → Ma société** (aussi imprimé sur les notes de frais) : tapez le nom de la société (ou son SIREN) et choisissez-la dans la liste, comme pour une fiche Société : raison sociale, forme juridique, SIRET, TVA et adresse se remplissent seuls. Complétez ensuite : raison sociale, forme juridique et capital, SIRET, n° de TVA intracommunautaire, adresse, e-mail, téléphone, IBAN/BIC, délai de paiement par défaut (30 jours) et mentions légales éventuelles (ex. « TVA non applicable, art. 293 B du CGI » si vous êtes en franchise). Ces informations sont imprimées sur chaque PDF : **complétez-les avant d'émettre votre première facture.**

Le PDF contient déjà les mentions obligatoires usuelles (pénalités de retard, indemnité forfaitaire de 40 €). Faites valider le modèle par votre expert-comptable.

**Devis et factures faits dans Qonto ?** Si la clé API Qonto est renseignée (section 12), le Hub **importe vos devis et factures Qonto** toutes les heures (ou via **Devis & factures → Synchroniser Qonto**) : client (créé dans le CRM s'il n'existe pas), lignes, montants, statut, paiement et lien **Ouvrir dans Qonto**. Ces documents sont en lecture seule dans le Hub : on les crée et les modifie dans Qonto. Ils alimentent le CA, le reste à encaisser, les relances d'impayés et la prévision de trésorerie. Les boutons « + Devis / + Facture » du Hub disparaissent alors pour garder une seule numérotation.

**Préparer un devis dans le Hub, l'améliorer avec l'IA, puis l'envoyer vers Qonto** :
1. *Devis & factures → + Devis* : client, objet, lignes, conditions ; enregistrez le brouillon.
2. **✨ Améliorer avec l'IA** (facultatif) : donnez une consigne ou laissez vide pour une relecture. L'IA (Claude) propose un objet, des intitulés plus clairs, un découpage des lignes et des conditions ; elle ne change ni prix, ni quantités, ni TVA sauf si vous le demandez, et affiche l'ancien et le nouveau total. **Appliquer au devis**, relisez, enregistrez.
3. **Envoyer vers Qonto** : le client est retrouvé (ou créé) dans Qonto et le devis y est créé **« en attente de validation »** : c'est l'équivalent d'un brouillon chez Qonto (il n'existe pas d'autre statut à la création) : modifiable, supprimable, **pas envoyé au client**. Il prend le numéro Qonto et se gère ensuite dans Qonto (envoi, acceptation) ; le Hub le suit en lecture seule.

Réglages nécessaires (**Paramètres → Intégrations**) :
- **Assistant IA** : une clé API Anthropic (<https://console.anthropic.com> → API Keys), facturée à l'usage par Anthropic. **Tester la connexion** pour vérifier.
- **Banque Qonto → Connexion Qonto pour les devis** : voir section 12 (connexion OAuth).

**Abonnements** : chaque abonnement peut avoir un **responsable** (utilisateur du Hub : licence nominative, carte utilisée…). **Abonnements ↔ dépenses** : dans **Abonnements**, le bouton **Dépenses liées** rattache à un abonnement (hébergement, nom de domaine…) tout ce qui a été payé pour lui : **mouvements bancaires** (ex. prélèvement OVH importé de Qonto ; la liste est pré-filtrée sur le fournisseur), **notes de frais** et **factures**. La colonne **Payé (12 mois)** additionne ces dépenses et signale quand elles dépassent nettement le coût prévu.

**Comment marche la facturation sans Qonto ?**
1. *Devis & factures → + Devis* : choisissez le client, ajoutez des lignes (le total se calcule seul, TVA par taux). Enregistrez : c'est un **brouillon** modifiable, sans numéro.
2. **Émettre** : le numéro définitif est attribué (`DEV-2026-0001`, `FAC-2026-0001`…, sans trou, par année). Une facture émise **ne peut plus être modifiée** (obligation légale) : pour corriger, on l'annule et on en crée une nouvelle.
3. Devis accepté → **Transformer en facture** (les lignes sont recopiées).
4. Encaissement → **Enregistrer le paiement** (paiements partiels possibles) : la facture passe « Payée » quand le solde est à zéro.
5. Impayé : le Hub alerte à J-3 de l'échéance, puis à J+1, J+7, J+15, J+30… sur vos canaux d'alerte.

## 9. Utilisateurs et rôles

Chaque utilisateur a un **profil** (clic sur son nom en bas du menu, ou dans Paramètres → Utilisateurs) : nombre et total de ses notes de frais (et celles sans justificatif), abonnements dont il est responsable et leur coût annuel, signatures, tâches ouvertes, opportunités et temps saisi ce mois-ci. Un membre ne voit que son profil ; un manager voit ceux de toute l'équipe.

**Paramètres → Utilisateurs → + Utilisateur.** *Membre* : CRM, tâches, saisie de son temps, notes de frais. *Manager* : en plus, devis/factures, trésorerie, abonnements, équipe, documents, accès. *Administrateur* : en plus, réglages, intégrations et utilisateurs.
Pour que le temps passé d'un membre soit valorisé, créez sa fiche dans **Équipe → Collaborateurs** avec **le même e-mail que son compte**.

## 10. Page de statut publique

Cochez « Afficher sur la page de statut publique » dans un projet : `https://<votre-domaine>/statut` montre alors, sans connexion, son nom et son état (rien d'autre : ni lien, ni serveur, ni note).

## 11. Mise à jour depuis la v1

Rien à faire : au démarrage, la base existante est reconnue et migrée automatiquement (Alembic). **Faites tout de même une sauvegarde du volume `pgdata` avant `make up`.**

---

## 12. Banque Qonto (trésorerie, devis et factures)

Le Hub importe tout seul, **toutes les heures**, vos comptes Qonto, leurs soldes, les transactions réglées (les 90 derniers jours lors de la première synchronisation), ainsi que vos **devis et factures clients** (voir section 8). Il ne fait que **lire** : aucun virement n'est possible depuis le Hub.

1. Connectez-vous à Qonto (application web) avec un compte **propriétaire ou administrateur**.
2. **Paramètres → Intégrations et partenariats → Clé API** : notez l'**Identifiant** et la **Clé secrète**.
3. Dans le Hub : **Paramètres → Intégrations → Banque Qonto**, collez les deux valeurs, puis **Tester la connexion** (« Connexion OK – … : N compte(s) »).
4. **Trésorerie → Synchroniser Qonto** pour lancer la première importation sans attendre. Un compte « Qonto – … » apparaît par compte bancaire, et son solde est celui de Qonto.

À savoir :
- Les opérations en attente ne sont pas importées : elles arrivent quand elles sont réglées.
- Le solde d'un compte Qonto est recalé à chaque synchronisation. Inutile de le modifier à la main.
- Vos comptes saisis à la main (ou importés en CSV) restent utilisables à côté.
- Si vous régénérez la clé chez Qonto, remettez-la dans le Hub.
- « La clé API Qonto n'a pas accès aux devis/factures » : la clé doit appartenir à un propriétaire ou administrateur de l'organisation.

**Connexion OAuth (devis)** : Qonto réserve les **devis** (import et création) aux applications connectées en OAuth ; la clé API ci-dessus suffit pour le reste. Sans cette connexion, les factures sont importées normalement et un message signale que les devis ne le sont pas.
1. Sur le portail développeur Qonto (<https://developers.qonto.com>), créez une application et déclarez l'**adresse de redirection** affichée dans le Hub (*Paramètres → Intégrations → Banque Qonto*), de la forme `https://<votre-domaine>/api/billing/qonto/oauth/callback`.
2. Autorisez les droits : `offline_access`, `organization.read`, `client.read`, `client.write`, `client_invoices.read`, `client_invoice.write`.
3. Copiez l'**ID** et le **secret** de l'application dans les champs « Qonto – ID / Secret de l'application ».
4. Cliquez **Se connecter avec Qonto** (compte administrateur Qonto) et acceptez.

## Dépannage rapide

| Symptôme | Cause probable |
|---|---|
| Le site du Hub n'ouvre pas en HTTPS | Le DNS ne pointe pas encore vers le serveur, ou les ports 80/443 sont fermés (`make logs`) |
| « Microsoft a refusé la connexion » | L'URI de redirection ne correspond pas **exactement** à celle affichée dans le Hub |
| « Dossier Drive introuvable » (Google) | Le dossier « Note de frais » n'est pas partagé avec l'e-mail du compte de service |
| « pas d'espace de stockage » (Google) | Le dossier est dans « Mon Drive » : placez-le dans un Drive partagé |
| « Le serveur IMAP refuse l'identifiant » | Mauvais mot de passe, ou identifiant différent de l'adresse e-mail : vérifiez dans Outlook, puis Paramètres → Boîtes mail → Modifier |
| « Serveur IMAP injoignable » | Nom du serveur ou port erroné (993 en SSL) |
| Aucune alerte reçue | Aucun canal créé, ou seuil trop haut ; utilisez « Envoyer un test » |
| « Qonto refuse les identifiants » | Identifiant ou clé secrète erronés (ou clé régénérée chez Qonto) : recopiez-les dans Paramètres → Intégrations |
| Le PDF de facture affiche « Votre société » | Complétez Paramètres → Intégrations → Ma société |
| Un site de dev apparaît « Hors ligne » | Il renvoie 401/403 : renseignez le *code HTTP attendu* |
