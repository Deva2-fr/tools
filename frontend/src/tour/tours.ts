import type { TourStep } from "./Tour";

// Guides déjà vus : mémorisés dans ce navigateur, par utilisateur (rien de critique si perdu).
const PREFIX = "deva2.tour2."; // v2 : guides courts (les anciens guides vus ne comptent plus)
export function tourSeen(key: string, uid: number): boolean {
  try { return localStorage.getItem(`${PREFIX}${key}.${uid}`) === "1"; } catch { return true; }
}
export function markTourSeen(key: string, uid: number): void {
  try { localStorage.setItem(`${PREFIX}${key}.${uid}`, "1"); } catch { /* stockage indisponible */ }
}
/** Les guides ne se lancent seuls que pendant la toute première session (onglet) de l'utilisateur. */
const FIRST_SESSION = "deva2.tour.firstSession";
export function isFirstSession(): boolean {
  try { return sessionStorage.getItem(FIRST_SESSION) === "1"; } catch { return false; }
}
export function startFirstSession(): void {
  try { sessionStorage.setItem(FIRST_SESSION, "1"); } catch { /* stockage indisponible */ }
}
export function resetTours(uid: number): void {
  try {
    Object.keys(localStorage).filter((k) => k.startsWith(PREFIX) && k.endsWith(`.${uid}`)).forEach((k) => localStorage.removeItem(k));
  } catch { /* stockage indisponible */ }
}

/** Guides par section : une vue d'ensemble courte (3-4 étapes), pas un mode d'emploi détaillé.
 * Les étapes dont l'élément n'est pas affiché (page vide, droits) sont sautées. */
export const TOURS: Record<string, TourStep[]> = {
  welcome: [
    { title: "Bienvenue dans le Hub Deva2", body: "Tout l'outil de gestion de Deva2 au même endroit. Chaque page a son petit guide, lancé la première fois que vous l'ouvrez." },
    { target: "nav", title: "Le menu", body: "Toutes les sections, rangées par thème : commercial, finances, équipe, infrastructure." },
    { target: "search", title: "La recherche", body: "Retrouvez une société, un contact ou un devis depuis n'importe où (⌘K / Ctrl+K)." },
    { target: "copilot", title: "Le copilote IA", body: "Posez vos questions sur tout le Hub : il fait les liens et vous propose des actions, que vous validez (⌘J / Ctrl+J)." },
    { target: "guide", title: "Revoir un guide", body: "Ce bouton relance le guide de la page où vous êtes." },
  ],
  dashboard: [
    { target: "page-title", title: "Tableau de bord", body: "L'essentiel du jour en un coup d'œil. Chaque chiffre mène à la section concernée." },
    { target: "dash-tech", title: "Santé technique", body: "Sites en ligne, alertes, failles et mails à répondre." },
    { target: "dash-finance", title: "Finances", body: "CA facturé, reste à encaisser, trésorerie et pipeline." },
    { target: "card:mes-taches", title: "À faire", body: "Vos tâches, renouvellements et échéances qui arrivent." },
  ],
  companies: [
    { target: "page-title", title: "Sociétés", body: "Vos clients, prospects et fournisseurs. Cliquez sur un nom pour ouvrir sa fiche complète." },
    { target: "rp-new", title: "Ajouter une société", body: "Tapez le nom : les informations officielles se remplissent toutes seules." },
    { target: "rp-list", title: "La liste", body: "Recherchez, modifiez ou exportez vos sociétés." },
  ],
  company: [
    { target: "page-title", title: "Fiche société", body: "Tout ce qui concerne ce client, au même endroit." },
    { target: "page-actions", title: "Actions rapides", body: "Créez un devis ou une facture, ou modifiez la société." },
    { target: "card:contacts", title: "Le suivi", body: "Contacts, affaires, tâches, devis, mails et historique des échanges." },
  ],
  contacts: [
    { target: "page-title", title: "Contacts", body: "Les personnes avec qui vous travaillez, rattachées à leur société." },
    { target: "rp-new", title: "Nouveau contact", body: "Ajoutez un contact, ou importez-en plusieurs depuis un CSV." },
    { target: "rp-list", title: "La liste", body: "Recherchez, modifiez ou exportez vos contacts." },
  ],
  pipeline: [
    { target: "page-title", title: "Pipeline commercial", body: "Vos affaires en cours, de « Prospect » à « Gagné »." },
    { target: "pipe-stats", title: "Les chiffres", body: "Montant en cours, prévision pondérée et affaires gagnées." },
    { target: "pipe-board", title: "Le tableau", body: "Glissez une carte d'une colonne à l'autre pour la faire avancer." },
  ],
  tasks: [
    { target: "page-title", title: "Tâches", body: "La to-do partagée de l'équipe : relances, rendez-vous, rappels." },
    { target: "tasks-add", title: "Ajouter", body: "Écrivez la tâche et, si besoin, une échéance." },
    { target: "tasks-list", title: "La liste", body: "Cochez une tâche pour la terminer. Filtrez par « À faire », « Mes tâches » ou « Terminées »." },
  ],
  mail: [
    { target: "page-title", title: "Mails", body: "Vos boîtes mail réunies, en lecture seule : rien n'est modifié sur le serveur." },
    { target: "mail-boxes", title: "Boîtes et filtres", body: "Choisissez une boîte, puis « À traiter » pour voir ce qui attend une réponse." },
    { target: "mail-list", title: "Les mails", body: "Cliquez sur un mail pour le lire en entier. Les tags (À répondre, Urgent…) sont posés automatiquement." },
  ],
  billing: [
    { target: "page-title", title: "Devis & factures", body: "Vos documents Qonto importés automatiquement, et vos devis préparés ici." },
    { target: "billing-kpis", title: "Les indicateurs", body: "Facturé, encaissé, reste à encaisser et retards." },
    { target: "billing-new-quote", title: "Créer un devis", body: "Un brouillon de travail : envoyez-le vers Qonto seulement quand il est prêt." },
    { target: "billing-list", title: "La liste", body: "Ouvrez un document, ou supprimez un devis avec la corbeille." },
  ],
  billingEditor: [
    { target: "page-title", title: "Le devis", body: "Préparez votre devis : rien n'est envoyé sans votre action." },
    { target: "card:lignes", title: "Les lignes", body: "Une ligne par prestation ; les totaux se calculent seuls." },
    { target: "editor-ai", title: "L'IA", body: "Propose une version plus claire et professionnelle, que vous appliquez ou non." },
    { target: "editor-push", title: "Vers Qonto", body: "Crée le devis dans Qonto en attente de validation." },
  ],
  treasury: [
    { target: "page-title", title: "Trésorerie", body: "Votre solde bancaire et sa prévision." },
    { target: "card:prevision-de-tresorerie", title: "La prévision", body: "Le solde projeté sur les prochains mois, avec le point bas à anticiper." },
    { target: "card:mouvements-bancaires", title: "Les mouvements", body: "L'historique de vos comptes, synchronisé avec Qonto." },
  ],
  renewals: [
    { target: "page-title", title: "Abonnements & contrats", body: "Domaines, hébergements, logiciels, assurances : le Hub vous prévient avant chaque renouvellement." },
    { target: "subs-summary", title: "Le coût annuel", body: "Ce que coûtent vos abonnements actifs sur un an." },
    { target: "rp-list", title: "La liste", body: "Ajoutez un abonnement et reliez-le à ses dépenses réelles." },
  ],
  expenses: [
    { target: "page-title", title: "Notes de frais", body: "Remplissez, faites signer, joignez les justificatifs : le PDF est généré et rangé dans Drive." },
    { target: "exp-signatures", title: "Les signatures", body: "Demandeur, président et associé." },
    { target: "card:historique", title: "L'historique", body: "Retrouvez et retéléchargez toutes les notes." },
  ],
  taxes: [
    { target: "page-title", title: "Impôts & TVA", body: "Vos échéances fiscales : TVA, déclaration annuelle et CFE." },
    { target: "tax-next", title: "La prochaine échéance", body: "La date et le compte à rebours, en couleur quand elle approche." },
    { target: "card:echeances", title: "Les échéances", body: "Marquez-les payées au fur et à mesure. Elles peuvent aussi aller dans votre Google Agenda." },
  ],
  time: [
    { target: "page-title", title: "Suivi du temps", body: "Notez le temps passé par client pour mesurer leur rentabilité." },
    { target: "card:ce-mois-ci-h", title: "Vos saisies", body: "Le temps du mois, avec le total en titre." },
  ],
  team: [
    { target: "page-title", title: "Collaborateurs", body: "Les fiches de l'équipe, reliées à leur compte du Hub." },
    { target: "rp-list", title: "La liste", body: "Ajoutez, modifiez ou exportez les fiches." },
  ],
  documents: [
    { target: "page-title", title: "Documents", body: "Le coffre de l'entreprise : Kbis, statuts, contrats, assurances." },
    { target: "docs-new-folder", title: "Les dossiers", body: "Créez des dossiers (et sous-dossiers) pour ranger vos documents ; « Déplacer » change un fichier de dossier." },
    { target: "card:fichiers", title: "Les fichiers", body: "Le fichier téléversé va dans le dossier ouvert. Ajoutez une date d'expiration : le Hub vous prévient avant." },
  ],
  access: [
    { target: "page-title", title: "Registre des accès", body: "Qui a accès à quoi, et où est rangé le mot de passe (jamais le mot de passe lui-même)." },
    { target: "rp-list", title: "La liste", body: "Indispensable pour savoir quels accès révoquer quand quelqu'un part." },
  ],
  projects: [
    { target: "page-title", title: "Projets & serveurs", body: "Vos sites, surveillés en continu." },
    { target: "projects-list", title: "Vos projets", body: "Vert : en ligne. Rouge : hors ligne. Cliquez pour le détail." },
  ],
  project: [
    { target: "page-title", title: "Fiche projet", body: "L'état d'un site : disponibilité, certificat, serveurs et technologies." },
    { target: "project-status", title: "En direct", body: "Statut, certificat SSL et dernier contrôle." },
    { target: "card:technologies", title: "Technologies", body: "Renseignez-les pour que le Hub cherche les failles connues." },
  ],
  alerts: [
    { target: "page-title", title: "Alertes & sécurité", body: "Pannes, certificats, failles et échéances qui demandent une réaction." },
    { target: "card:alertes", title: "Les alertes", body: "Marquez-les traitées une fois réglées." },
    { target: "card:ou-recevoir-les-alertes", title: "Les notifications", body: "Recevez les alertes par e-mail, Slack, Discord ou Telegram." },
  ],
  settings: [
    { target: "page-title", title: "Paramètres", body: "Votre compte et, pour les administrateurs, les intégrations et les utilisateurs." },
    { target: "settings-tabs", title: "Les onglets", body: "Sécurité du compte, connexions (Qonto, Google, mails, IA…) et utilisateurs." },
    { target: "card:double-authentification", title: "Sécurité", body: "Activez la double authentification : fortement recommandé." },
  ],
  profile: [
    { target: "page-title", title: "Profil", body: "Tout ce qui est rattaché à cette personne dans le Hub." },
    { target: "profile-stats", title: "En chiffres", body: "Notes de frais, abonnements, signatures, tâches et temps passé." },
    { target: "reset-guides", title: "Les guides", body: "Réactivez tous les guides pour les revoir." },
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
