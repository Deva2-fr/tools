# Idées pour aller plus loin

Classées par rapport effort / valeur. Elles s'intègrent naturellement dans l'architecture existante (un fichier dans `routers/` + `services/` + une page React).

## ⭐ À fort impact, simples
1. **Renouvellements de domaines & abonnements** : date d'expiration de chaque nom de domaine (deva2.fr, formasyl.org…), hébergement, licences, SaaS — avec rappel avant renouvellement et coût annuel total. *(Perdre un domaine est l'un des pires incidents évitables.)*
2. **Suivi des factures clients & relances** : devis → facture → payée / en retard, rappel « facture X impayée depuis 15 jours », brouillon de mail de relance.
3. **Vérification des sauvegardes** : chaque serveur « ping » le Hub après sa sauvegarde ; pas de ping = alerte. Une sauvegarde non vérifiée n'existe pas.
4. **Tableau de bord trésorerie** : import CSV de la banque, solde prévisionnel intégrant les échéances fiscales déjà connues du Hub.

## 🔒 Sécurité & infrastructure
5. **Scan externe hebdomadaire** : ports ouverts inattendus, versions exposées, qualité TLS, DNS (SPF/DKIM/DMARC pour que vos mails n'arrivent pas en spam).
6. **Alertes de dépendances** : Dependabot / GitHub Security Advisories remontés dans le Hub.
7. **Registre des accès (sans mots de passe)** : où se trouve chaque accès (Bitwarden, clés SSH, comptes cloud), qui y a accès, date de dernière rotation.
8. **Suivi des déploiements** : intégration GitHub (dernier déploiement par projet, CI rouge → alerte).
9. **Page de statut publique** pour vos clients (formasyl.org…), alimentée par le monitoring.

## 🧾 Gestion de la société
10. **Justificatifs des notes de frais** : photo du ticket jointe, export mensuel groupé pour le comptable, validation par un responsable.
11. **Contrats & assurances** : échéances, tacite reconduction, préavis de résiliation (alerte 90 jours avant).
12. **Obligations légales** : AG annuelle, dépôt des comptes, registre des bénéficiaires effectifs, mise à jour du Kbis.
13. **Onboarding / offboarding** : check-list d'accès à donner ou retirer quand quelqu'un arrive ou part.
14. **Suivi du temps / TJM par projet** pour mesurer la rentabilité de chaque client.

## ✉️ Mails & productivité
15. **Brouillon de réponse assisté par IA** pour les mails « À répondre » (vous relisez et envoyez).
16. **Résumé quotidien** à 8h30 : mails à répondre, sites en alerte, échéances de la semaine, en un seul message.
17. **Rappel de relance** : si vous attendez la réponse d'un client depuis X jours, le Hub vous le dit.
18. **Application mobile (PWA)** installable avec notifications push.

## 🧱 Évolutions techniques
19. **Connexion SSO Microsoft** (mêmes comptes que Outlook) à la place des mots de passe locaux.
20. **Sauvegarde automatique chiffrée** de la base du Hub vers un stockage externe (S3, OVH Object Storage).
21. **Migrations Alembic** : aujourd'hui les tables sont créées au démarrage ; à ajouter avant de faire évoluer le schéma en production.
