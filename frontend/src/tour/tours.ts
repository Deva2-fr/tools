import type { TourStep } from "./Tour";

// Guides déjà vus : mémorisés dans ce navigateur, par utilisateur (rien de critique si perdu).
const PREFIX = "deva2.tour.";
export function tourSeen(key: string, uid: number): boolean {
  try { return localStorage.getItem(`${PREFIX}${key}.${uid}`) === "1"; } catch { return true; }
}
export function markTourSeen(key: string, uid: number): void {
  try { localStorage.setItem(`${PREFIX}${key}.${uid}`, "1"); } catch { /* stockage indisponible */ }
}
export function resetTours(uid: number): void {
  try {
    Object.keys(localStorage).filter((k) => k.startsWith(PREFIX) && k.endsWith(`.${uid}`)).forEach((k) => localStorage.removeItem(k));
  } catch { /* stockage indisponible */ }
}

/** Guides par section. Les étapes dont l'élément n'est pas affiché (page vide, droits) sont sautées. */
export const TOURS: Record<string, TourStep[]> = {
  welcome: [
    { title: "Bienvenue dans le Hub Deva2 👋", body: "Le Hub regroupe toute la gestion de Deva2 : clients, devis, trésorerie, notes de frais, mails, impôts, projets et sécurité.\n\nCe guide vous montre l'essentiel en quelques étapes. Chaque section a ensuite son propre guide, lancé automatiquement la première fois que vous l'ouvrez." },
    { target: "nav", title: "Le menu", body: "Toutes les sections, rangées par thème : Commercial (sociétés, contacts, pipeline, tâches, mails), Finances (devis & factures, trésorerie, abonnements, notes de frais, impôts), Équipe et Infrastructure.\n\nSur téléphone, le menu s'ouvre avec le bouton ☰ en haut à gauche." },
    { target: "search", title: "La recherche globale", body: "Retrouvez instantanément une société, un contact, un projet, un devis… depuis n'importe quelle page.\n\nRaccourci clavier : ⌘K (Mac) ou Ctrl+K (Windows)." },
    { target: "profile", title: "Votre profil", body: "Cliquez sur votre nom pour voir tout ce qui vous est rattaché : notes de frais, abonnements, signatures, tâches, temps passé. C'est aussi là que vous vous déconnectez." },
    { target: "guide", title: "Revoir un guide à tout moment", body: "Le bouton « ? Guide » relance le guide de la page où vous êtes. Pratique pour (re)découvrir une section ou former un collègue." },
  ],
  dashboard: [
    { target: "page-title", title: "Tableau de bord", body: "Votre page d'accueil : tout ce qui demande votre attention, en un coup d'œil. Chaque indicateur est cliquable et mène à la section concernée." },
    { target: "dash-tech", title: "Santé technique", body: "Sites en ligne (surveillés toutes les 5 minutes), alertes ouvertes, failles de sécurité à traiter et mails qui attendent une réponse.\n\nUn chiffre en couleur signale quelque chose à regarder." },
    { target: "dash-finance", title: "Indicateurs financiers", body: "Visible des managers : chiffre d'affaires facturé dans l'année, reste à encaisser (en orange s'il y a des retards), solde de trésorerie et pipeline pondéré (affaires en cours × probabilité)." },
    { target: "card:mes-taches", title: "Vos tâches", body: "Les tâches qui vous sont assignées, les plus urgentes en premier. Cochez-les ici ou gérez-les dans Commercial → Tâches." },
    { target: "card:renouvellements-a-venir", title: "Renouvellements à venir", body: "Domaines, hébergements, licences et contrats qui se renouvellent dans les 30 jours : de quoi anticiper ou résilier à temps." },
    { target: "card:mes-sites", title: "Vos sites", body: "L'état en direct de chaque site surveillé. Cliquez sur un site pour voir ses serveurs, ses technologies et ses failles." },
    { target: "card:prochaines-echeances", title: "Échéances fiscales", body: "Les prochaines dates de TVA, déclarations et CFE. Le Hub vous prévient avant chaque date limite." },
  ],
  companies: [
    { target: "page-title", title: "Sociétés", body: "Le carnet d'adresses des entreprises : clients, prospects, fournisseurs et partenaires. Chaque société a une fiche complète (contacts, affaires, devis, mails, documents, historique)." },
    { target: "rp-new", title: "Ajouter une société", body: "Tapez simplement le nom ou le SIREN : le Hub interroge l'annuaire officiel et remplit tout seul la raison sociale, le SIRET, la TVA, l'adresse et le secteur." },
    { target: "rp-extra", title: "Importer un fichier", body: "Vous avez déjà une liste dans Excel ? Exportez-la en CSV et importez-la ici. La première ligne doit contenir les en-têtes (name, kind, siret…)." },
    { target: "rp-search", title: "Rechercher", body: "Filtrez par nom, ville ou étiquette." },
    { target: "rp-list", title: "La liste", body: "Cliquez sur le nom d'une société pour ouvrir sa fiche. Les boutons en bout de ligne permettent de la modifier ou de la supprimer." },
    { target: "rp-export", title: "Exporter", body: "Téléchargez toute la liste en CSV (ouvrable dans Excel)." },
  ],
  company: [
    { target: "page-title", title: "La fiche société", body: "Tout ce qui concerne cette société, au même endroit." },
    { target: "page-actions", title: "Actions rapides", body: "Créez directement un devis ou une facture pour cette société, modifiez ses informations ou supprimez-la." },
    { target: "card:contacts", title: "Contacts", body: "Les personnes de cette société. Leurs mails apparaissent automatiquement plus bas dans « Mails liés »." },
    { target: "card:affaires-en-cours", title: "Affaires", body: "Les opportunités commerciales en cours avec cette société. Elles alimentent le pipeline." },
    { target: "card:taches-a-faire", title: "Tâches", body: "Relances et choses à faire pour ce client." },
    { target: "card:devis-factures", title: "Devis & factures", body: "Tous les devis et factures de la société, avec leur statut." },
    { target: "card:journal-d-activite", title: "Journal d'activité", body: "Notez chaque échange (appel, rendez-vous, mail important) : toute l'équipe garde l'historique de la relation." },
  ],
  contacts: [
    { target: "page-title", title: "Contacts", body: "Les personnes avec qui vous travaillez. Rattachez chaque contact à sa société : ses mails apparaîtront sur la fiche de la société." },
    { target: "rp-new", title: "Nouveau contact", body: "Nom, poste, e-mail, téléphone et société." },
    { target: "rp-extra", title: "Import CSV", body: "Importez vos contacts depuis un fichier (Outlook, Excel, ancien CRM…)." },
    { target: "rp-list", title: "La liste", body: "Recherchez, modifiez ou exportez vos contacts. Cliquez sur un e-mail pour écrire directement." },
  ],
  pipeline: [
    { target: "page-title", title: "Pipeline commercial", body: "Suivez vos affaires de « Prospect » à « Gagné » sur un tableau en colonnes." },
    { target: "pipe-stats", title: "Les chiffres clés", body: "En cours : total des affaires ouvertes. Prévision pondérée : chaque montant × sa probabilité de signature (le chiffre le plus réaliste). Gagné : ce qui est signé." },
    { target: "pipe-board", title: "Le tableau", body: "Glissez-déposez une carte d'une colonne à l'autre pour la faire avancer. Cliquez sur une carte pour la modifier (montant, probabilité, date de signature prévue)." },
    { target: "page-actions", title: "Nouvelle affaire", body: "Créez une affaire liée à une société : elle apparaît dans la première colonne." },
  ],
  tasks: [
    { target: "page-title", title: "Tâches", body: "La to-do partagée de l'équipe : relances, rendez-vous à préparer, choses à ne pas oublier." },
    { target: "tasks-add", title: "Ajouter une tâche", body: "Écrivez la tâche, choisissez une échéance si besoin, puis « Ajouter ». Elle apparaît aussi sur votre tableau de bord." },
    { target: "tasks-filters", title: "Les filtres", body: "« À faire » : toutes les tâches ouvertes. « Mes tâches » : seulement les vôtres. « Terminées » : l'historique." },
    { target: "tasks-list", title: "La liste", body: "Cochez une tâche pour la terminer. Les tâches en retard sont signalées en rouge." },
  ],
  mail: [
    { target: "page-title", title: "Mails", body: "Vos boîtes mail réunies, avec un tri automatique des mails qui attendent une réponse.\n\nLe Hub ne fait que lire : il ne marque rien comme lu, n'envoie, ne déplace ni ne supprime aucun mail." },
    { target: "mail-boxes", title: "Les boîtes", body: "Passez d'une boîte à l'autre (contact@, compta@…) ou affichez-les toutes. Le chiffre indique les mails à traiter. Un point rouge signale une synchronisation en échec." },
    { target: "mail-filters", title: "Les filtres", body: "À traiter : mails qui attendent une réponse (et urgents). Tous les mails. Répondus. Informations : notifications, newsletters, mails sans question." },
    { target: "mail-help", title: "Comment sont attribués les tags ?", body: "Le Hub repère les questions, les mots urgents et vos réponses envoyées. Cliquez ici pour le détail des règles." },
    { target: "mail-search", title: "Rechercher", body: "Par objet, expéditeur ou texte du mail." },
    { target: "mail-list", title: "La liste", body: "Cliquez sur un mail pour le lire en entier (avec les pièces jointes). Les mails non lus sont en gras." },
    { target: "mail-reader", title: "La lecture", body: "Le mail s'affiche ici. Les boutons du haut changent son tag (À répondre, Urgent, Traité, Ignorer) ; « Automatique » rend la main au tri automatique. Les images distantes sont bloquées par défaut (sécurité)." },
    { target: "mail-refresh", title: "Actualiser", body: "Les boîtes se synchronisent toutes les 5 minutes ; ce bouton force une synchronisation immédiate." },
  ],
  billing: [
    { target: "page-title", title: "Devis & factures", body: "Les factures et devis Qonto sont importés automatiquement toutes les heures : chiffre d'affaires, encaissements, retards.\n\nLes devis peuvent aussi être préparés ici, améliorés avec l'IA, puis envoyés vers Qonto." },
    { target: "billing-kpis", title: "Les indicateurs", body: "Facturé et encaissé dans l'année, reste à encaisser, montant en retard, et le chiffre d'affaires mensuel en graphique." },
    { target: "billing-new-quote", title: "Créer un devis", body: "Un devis créé ici est un brouillon de travail : il n'a rien d'officiel et n'est PAS envoyé à Qonto tant que vous ne le décidez pas.\n\nVous pouvez le garder, le modifier, l'améliorer avec l'IA ou le supprimer à tout moment." },
    { target: "billing-sync", title: "Synchroniser Qonto", body: "Force l'import immédiat des factures et devis Qonto (sinon automatique toutes les heures)." },
    { target: "billing-filters", title: "Filtrer", body: "Tous, devis, factures ou documents en retard, et recherche par numéro ou objet." },
    { target: "billing-list", title: "La liste", body: "« Hub » = devis préparé ici, pas encore envoyé. « Qonto » = document présent dans Qonto.\n\nLa corbeille 🗑 supprime un devis du Hub ; s'il a déjà été envoyé vers Qonto sans être validé, il est supprimé des deux côtés." },
    { target: "billing-export", title: "Export comptable", body: "Un fichier CSV de tous les documents émis, pour votre expert-comptable." },
  ],
  billingEditor: [
    { target: "page-title", title: "Le devis", body: "Préparez votre devis ici. Rien n'est envoyé au client ni à Qonto sans votre action." },
    { target: "card:informations", title: "Informations", body: "Client, contact, objet, date et date de validité." },
    { target: "card:lignes", title: "Les lignes", body: "Une ligne par prestation : désignation (la 1re ligne sert de titre, les suivantes de détail), quantité, prix unitaire HT et TVA. Les totaux se calculent seuls." },
    { target: "card:notes-conditions", title: "Notes et conditions", body: "Acompte, délais, périmètre, validité… Elles figurent sur le devis." },
    { target: "editor-save", title: "Enregistrer sans envoyer", body: "Le devis reste un brouillon dans le Hub : vous pourrez y revenir, le modifier ou le supprimer." },
    { target: "editor-ai", title: "Améliorer avec l'IA", body: "L'IA reformule les intitulés, détaille les prestations et rédige les conditions. Elle ne change jamais les prix sans que vous le demandiez. Vous comparez sa proposition et l'appliquez (ou non)." },
    { target: "editor-push", title: "Envoyer vers Qonto", body: "Crée le devis dans Qonto « en attente de validation » : rien n'est envoyé au client. Tant qu'il n'est pas validé dans Qonto, vos modifications ici y sont reportées." },
  ],
  treasury: [
    { target: "page-title", title: "Trésorerie", body: "Votre solde bancaire et sa prévision : factures à encaisser, impôts et abonnements à venir." },
    { target: "page-actions", title: "Comptes et mouvements", body: "Avec Qonto connecté, comptes et mouvements sont importés toutes les heures (« Synchroniser » pour forcer). Sinon, ajoutez un compte et saisissez ou importez vos mouvements (CSV de la banque)." },
    { target: "card:prevision-de-tresorerie", title: "La prévision", body: "Le solde projeté sur 30, 90 ou 180 jours, avec le point bas prévu : de quoi anticiper un creux de trésorerie." },
    { target: "card:prochains-mouvements-prevus", title: "Mouvements prévus", body: "Les encaissements et dépenses attendus qui alimentent la prévision." },
    { target: "card:mouvements-bancaires", title: "Mouvements bancaires", body: "L'historique de vos comptes. Filtrez par compte avec la liste en haut à droite." },
  ],
  renewals: [
    { target: "page-title", title: "Abonnements, domaines & contrats", body: "Tout ce qui se renouvelle : noms de domaine, hébergements, logiciels, assurances. Le Hub vous prévient avant chaque échéance." },
    { target: "subs-summary", title: "Le coût annuel", body: "Le total annuel HT de vos abonnements actifs, et sa répartition par type." },
    { target: "rp-new", title: "Nouvel abonnement", body: "Nom, fournisseur, coût, périodicité, date de renouvellement, délai d'alerte et responsable (licence nominative, carte utilisée…)." },
    { target: "rp-list", title: "La liste", body: "La colonne « Payé (12 mois) » additionne les dépenses liées. Le lien « Dépenses liées » relie l'abonnement aux prélèvements bancaires, notes de frais ou factures correspondants." },
  ],
  expenses: [
    { target: "page-title", title: "Notes de frais", body: "Remplissez la note, faites-la signer, joignez les justificatifs : le Hub génère le PDF, le télécharge et le range dans Google Drive." },
    { target: "card:nouvelle-note-de-frais", title: "La note", body: "Date, personne qui a avancé les frais, catégorie, motif, montant TTC et TVA (le HT est calculé), moyen de paiement et projet concerné." },
    { target: "exp-signatures", title: "Les trois signatures", body: "Le demandeur, le président et l'associé (désignés dans Paramètres). Choisissez une signature enregistrée ou créez-en une (« + Nouvelle ») : dessinée au doigt ou importée." },
    { target: "exp-receipts", title: "Les justificatifs", body: "Jusqu'à 10 fichiers (PDF, JPG, PNG) : ils sont ajoutés à la fin du PDF, dans l'ordre." },
    { target: "exp-save", title: "Enregistrer", body: "Génère le PDF signé avec ses justificatifs, le télécharge et le dépose dans Drive (Administration › Comptabilité › Note de frais)." },
    { target: "card:historique", title: "L'historique", body: "Toutes les notes : retéléchargez le PDF, modifiez une note ou retrouvez ses justificatifs." },
  ],
  taxes: [
    { target: "page-title", title: "Impôts, TVA & déclarations", body: "Les échéances fiscales de Deva2 : TVA trimestrielle, déclaration annuelle de résultats et CFE." },
    { target: "tax-next", title: "La prochaine échéance", body: "En grand : la date, le compte à rebours et le montant. La couleur passe à l'orange puis au rouge à l'approche de la date." },
    { target: "tax-gcal", title: "Google Agenda", body: "Choisissez un agenda Google : chaque échéance y est ajoutée et tenue à jour automatiquement." },
    { target: "card:echeances", title: "Les échéances", body: "« ✓ C'est payé » une fois réglée, « Modifier » pour saisir le montant ou la date. « + Échéance » en ajoute une ; s'il n'y en a aucune, « Pré-remplir » crée d'un coup toutes celles de l'année (TVA, déclaration annuelle, CFE)." },
    { target: "tax-ics", title: "Exporter vers un agenda", body: "Un fichier .ics à ajouter dans Outlook, Apple Calendar ou tout autre agenda." },
  ],
  time: [
    { target: "page-title", title: "Suivi du temps", body: "Notez le temps passé par client : le Hub en déduit la rentabilité de chaque client." },
    { target: "time-tabs", title: "Deux vues", body: "Pour les managers : « Saisie du mois » pour noter le temps, « Rentabilité » pour comparer le temps passé et le chiffre d'affaires par client." },
    { target: "card:ce-mois-ci-h", title: "Vos saisies", body: "Date, heures, client, travail effectué, taux horaire et facturable ou non. Le total du mois s'affiche en titre." },
  ],
  team: [
    { target: "page-title", title: "Collaborateurs", body: "Les fiches de l'équipe. L'e-mail relie le collaborateur à son compte du Hub (temps passé, tâches)." },
    { target: "rp-new", title: "Nouveau collaborateur", body: "Nom, e-mail (le même que son compte Hub), poste, contrat, dates d'arrivée et de départ, et coût journalier chargé (sert au calcul de rentabilité)." },
    { target: "rp-list", title: "La liste", body: "Modifiez ou exportez les fiches." },
  ],
  documents: [
    { target: "page-title", title: "Documents", body: "Le coffre de l'entreprise : Kbis, statuts, contrats, attestations, assurances…" },
    { target: "card:fichiers", title: "Les fichiers", body: "Téléversez un fichier, classez-le, liez-le à une société et indiquez sa date d'expiration : le Hub vous prévient avant qu'il ne périme." },
  ],
  access: [
    { target: "page-title", title: "Registre des accès", body: "Qui a accès à quoi, et où est rangé le mot de passe.\n\n⚠️ N'écrivez JAMAIS un mot de passe ici : indiquez seulement son emplacement (ex. « Bitwarden > Deva2 > OVH »)." },
    { target: "rp-new", title: "Nouvel accès", body: "Service, identifiant, emplacement du mot de passe, personnes qui y ont accès, et fréquence de changement du mot de passe : le Hub signale ceux à changer." },
    { target: "rp-list", title: "La liste", body: "Indispensable quand quelqu'un quitte l'équipe : vous savez exactement quels accès révoquer." },
  ],
  projects: [
    { target: "page-title", title: "Projets & serveurs", body: "Tous vos sites : leur état en direct, leurs serveurs et leurs technologies." },
    { target: "page-actions", title: "Ajouter un projet", body: "Nom, URL et environnement : le Hub vérifie le site toutes les 5 minutes et surveille son certificat SSL." },
    { target: "projects-list", title: "Vos projets", body: "Un point vert : en ligne. Rouge : hors ligne (une alerte est envoyée). Cliquez sur un projet pour le détail." },
  ],
  project: [
    { target: "page-title", title: "La fiche projet", body: "Disponibilité, serveurs, technologies et failles de sécurité de ce site." },
    { target: "page-actions", title: "Actions", body: "« Vérifier maintenant » teste le site immédiatement. Modifiez ou supprimez le projet." },
    { target: "project-status", title: "État en direct", body: "Statut, certificat SSL (jours restants) et dernier contrôle." },
    { target: "card:serveurs", title: "Serveurs", body: "Hébergeur, IP, système… pour savoir où tourne le site." },
    { target: "card:technologies", title: "Technologies", body: "Renseignez les technologies et leurs versions (WordPress 6.4, PHP 8.2…) : « Chercher des failles » les compare aux bases de failles connues." },
  ],
  alerts: [
    { target: "page-title", title: "Alertes & sécurité", body: "Sites en panne, certificats qui expirent, failles critiques et échéances : tout ce qui demande une réaction." },
    { target: "card:alertes", title: "Les alertes", body: "Marquez une alerte « Traité » une fois réglée, ou tout marquer comme lu." },
    { target: "card:veille-des-failles-de-securite", title: "Veille des failles", body: "Le Hub compare les technologies de vos projets aux failles publiées (NVD et catalogue CISA des failles exploitées)." },
    { target: "card:ou-recevoir-les-alertes", title: "Où recevoir les alertes", body: "Ajoutez un canal : e-mail, Slack, Discord ou Telegram. Sans canal, les alertes restent visibles ici seulement." },
  ],
  settings: [
    { target: "page-title", title: "Paramètres", body: "Votre compte, et pour les administrateurs : les intégrations et les utilisateurs." },
    { target: "settings-tabs", title: "Les onglets", body: "Mon compte & sécurité : 2FA et mot de passe.\nIntégrations : Qonto, Google (Drive et Agenda), boîtes mail, IA, Ma société, e-mail d'alerte, signataires des notes de frais.\nUtilisateurs : comptes, rôles et journal d'activité." },
    { target: "card:double-authentification", title: "Double authentification", body: "Fortement recommandée : un code de votre téléphone en plus du mot de passe. Même si votre mot de passe fuit, votre compte reste protégé." },
    { target: "card:changer-mon-mot-de-passe", title: "Mot de passe", body: "12 caractères minimum." },
  ],
  profile: [
    { target: "page-title", title: "Profil", body: "Tout ce qui est rattaché à cette personne dans le Hub." },
    { target: "profile-stats", title: "En chiffres", body: "Notes de frais (et celles sans justificatif), abonnements, signatures, tâches ouvertes et temps passé ce mois-ci. Cliquez pour ouvrir la section." },
    { target: "card:signatures", title: "Signatures", body: "Les signatures enregistrées pour les notes de frais. Vous pouvez en supprimer." },
    { target: "reset-guides", title: "Revoir les guides", body: "Réactive tous les guides : ils se relanceront à la prochaine visite de chaque section." },
  ],
};

/** Guide correspondant à une adresse. */
export function tourKey(path: string): string | null {
  const rules: [RegExp, string][] = [
    [/^\/$/, "dashboard"],
    [/^\/crm\/societes\/\d+/, "company"],
    [/^\/crm\/societes/, "companies"],
    [/^\/crm\/contacts/, "contacts"],
    [/^\/crm\/pipeline/, "pipeline"],
    [/^\/crm\/taches/, "tasks"],
    [/^\/mails/, "mail"],
    [/^\/facturation\/(nouveau|\d+)/, "billingEditor"],
    [/^\/facturation/, "billing"],
    [/^\/tresorerie/, "treasury"],
    [/^\/abonnements/, "renewals"],
    [/^\/notes-de-frais/, "expenses"],
    [/^\/impots/, "taxes"],
    [/^\/temps/, "time"],
    [/^\/equipe/, "team"],
    [/^\/documents/, "documents"],
    [/^\/acces/, "access"],
    [/^\/projets\/\d+/, "project"],
    [/^\/projets/, "projects"],
    [/^\/alertes/, "alerts"],
    [/^\/parametres/, "settings"],
    [/^\/profil/, "profile"],
  ];
  return rules.find(([re]) => re.test(path))?.[1] ?? null;
}
