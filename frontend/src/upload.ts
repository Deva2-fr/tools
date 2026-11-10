import { api, apiUploadProgress } from "./api";

/** Fichier à envoyer, avec le chemin de sous-dossiers d'où il vient (vide pour un fichier seul). */
export interface UploadItem { file: File; dirs: string[] }

// Fichiers système déposés avec un dossier : jamais envoyés.
const SKIP = /^(\..*|thumbs\.db|desktop\.ini)$/i;
const keep = (name: string) => !SKIP.test(name);

/** Choix via <input type="file"> (fichiers, ou dossier avec webkitdirectory). */
export function fromInput(list: FileList | null): UploadItem[] {
  return Array.from(list ?? [])
    .filter((f) => keep(f.name))
    .map((file) => ({ file, dirs: (file.webkitRelativePath || "").split("/").slice(0, -1) }));
}

/** Glisser-déposer : fichiers et dossiers (parcourus en entier, sous-dossiers compris). */
export async function fromDrop(dt: DataTransfer): Promise<UploadItem[]> {
  const entries = Array.from(dt.items ?? []).map((i) => i.webkitGetAsEntry?.()).filter((e): e is FileSystemEntry => !!e);
  if (!entries.length) return fromInput(dt.files);
  const out: UploadItem[] = [];
  const walk = async (entry: FileSystemEntry, dirs: string[]): Promise<void> => {
    if (!keep(entry.name)) return;
    if (entry.isFile) {
      const file = await new Promise<File>((ok, ko) => (entry as FileSystemFileEntry).file(ok, ko));
      out.push({ file, dirs });
    } else if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      // readEntries renvoie les éléments par lots : on lit jusqu'à un lot vide.
      for (;;) {
        const batch = await new Promise<FileSystemEntry[]>((ok, ko) => reader.readEntries(ok, ko));
        if (!batch.length) break;
        for (const child of batch) await walk(child, [...dirs, entry.name]);
      }
    }
  };
  for (const e of entries) await walk(e, []);
  return out;
}

export const folderCount = (items: UploadItem[]) => new Set(items.filter((i) => i.dirs.length).map((i) => i.dirs.join("/"))).size;

/**
 * Envoie les fichiers l'un après l'autre dans `baseFolderId`, en recréant leurs sous-dossiers.
 * Un fichier refusé n'arrête pas les suivants : la liste des erreurs est renvoyée.
 */
export async function uploadItems(
  items: UploadItem[],
  baseFolderId: number | null,
  fields: Record<string, string>,
  onProgress: (i: number, n: number, pct: number) => void,
): Promise<string[]> {
  const errors: string[] = [];
  const folderIds = new Map<string, number | null>([["", baseFolderId]]);
  for (const [i, { file, dirs }] of items.entries()) {
    onProgress(i + 1, items.length, 0);
    const key = dirs.join("/");
    try {
      if (!folderIds.has(key)) {
        const r = await api<{ id: number }>("/files/folders/path", "POST", { parent_id: baseFolderId, path: dirs });
        folderIds.set(key, r.id);
      }
      const fd = new FormData();
      fd.append("file", file);
      const target = folderIds.get(key);
      if (target) fd.append("folder_id", String(target));
      for (const [k, v] of Object.entries(fields)) if (v) fd.append(k, v);
      await apiUploadProgress("/files", fd, (pct) => onProgress(i + 1, items.length, pct));
    } catch (e) {
      errors.push(`${key ? `${key}/` : ""}${file.name} : ${e instanceof Error ? e.message : String(e)}`);
    }
  }
  return errors;
}
