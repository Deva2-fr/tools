# Idées pour aller plus loin

> Déjà réalisé dans la v2 (CRM) : renouvellements & abonnements, factures et relances, trésorerie prévisionnelle, registre des accès, check-lists arrivée/départ, suivi du temps et rentabilité, page de statut publique, résumé quotidien. Ci-dessous, ce qui reste à faire.

Classées par rapport effort / valeur. Elles s'intègrent naturellement dans l'architecture existante (un fichier dans `routers/` + `services/` + une page React).

## ⭐ À fort impact, simples
3. **Vérification des sauvegardes** : chaque serveur « ping » le Hub après sa sauvegarde ; pas de ping = alerte. Une sauvegarde non vérifiée n'existe pas.

## 🔒 Sécurité & infrastructure
5. **Scan externe hebdomadaire** : ports ouverts inattendus, versions exposées, qualité TLS, DNS (SPF/DKIM/DMARC pour que vos mails n'arrivent pas en spam).
6. **Alertes de dépendances** : Dependabot / GitHub Security Advisories remontés dans le Hub.
8. **Suivi des déploiements** : intégration GitHub (dernier déploiement par projet, CI rouge → alerte).

## 🧾 Gestion de la société
10. **Justificatifs des notes de frais** : photo du ticket jointe, export mensuel groupé pour le comptable, validation par un responsable.
12. **Obligations légales** : AG annuelle, dépôt des comptes, registre des bénéficiaires effectifs, mise à jour du Kbis.

## ✉️ Mails & productivité
15. **Brouillon de réponse assisté par IA** pour les mails « À répondre » (vous relisez et envoyez).
17. **Rappel de relance** : si vous attendez la réponse d'un client depuis X jours, le Hub vous le dit.
18. **Application mobile (PWA)** installable avec notifications push.

## 🧱 Évolutions techniques
19. **Connexion SSO Microsoft** (mêmes comptes que Outlook) à la place des mots de passe locaux.
20. **Sauvegarde automatique chiffrée** de la base du Hub vers un stockage externe (S3, OVH Object Storage).

## 🚀 Idées « CRM » pour la suite
22. **Envoi des devis/factures par e-mail** depuis le Hub (SMTP déjà configurable) avec le PDF en pièce jointe et suivi d'ouverture.
23. **Factures récurrentes** (abonnements clients, maintenance mensuelle) générées automatiquement.
24. **Signature électronique des devis** (lien public à usage unique).
25. **Portail client** : vos clients consultent leurs devis, factures et le statut de leurs projets.
26. **Synchronisation bancaire** (Open Banking : Qonto, Bridge…) à la place de l'import CSV, avec rapprochement automatique des paiements.
27. **Facturation électronique (Factur-X)** : PDF + XML conforme à la réforme française.
28. **Création automatique de contacts** à partir des expéditeurs de vos mails Outlook.
29. **Calendrier Outlook** : rendez-vous liés aux affaires, rappels dans le journal d'activité.
30. **Rapports** : CA par client / par mois, taux de transformation du pipeline, délai moyen de paiement.
31. **Tickets / support client** liés aux projets hébergés, avec suivi du temps.
32. **Notes de frais** : photo du justificatif, validation par un manager, refacturation au client.
