import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { SignatureRow, apiUpload } from "../api";
import { Button, ErrorMsg, Field, Modal } from "../ui";

/** Nouvelle signature : dessinée à la souris / au doigt, ou image importée (scan, photo détourée). */
export default function SignaturePad({ userId, defaultName, onClose, onCreated }: { userId: number | null; defaultName: string; onClose: () => void; onCreated: (s: SignatureRow) => void }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  const [name, setName] = useState(defaultName);
  const [mode, setMode] = useState<"draw" | "upload">("draw");
  const [file, setFile] = useState<File | null>(null);
  const [empty, setEmpty] = useState(true);

  useEffect(() => {
    const c = canvas.current;
    if (!c) return;
    // Résolution doublée pour un trait net à l'impression.
    const ratio = 2;
    c.width = c.offsetWidth * ratio;
    c.height = c.offsetHeight * ratio;
    const ctx = c.getContext("2d")!;
    ctx.scale(ratio, ratio);
    ctx.lineWidth = 2.2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.strokeStyle = "#1c2b4a";
  }, [mode]);

  const pos = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top] as const;
  };
  const down = (e: React.PointerEvent<HTMLCanvasElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    drawing.current = true;
    const ctx = e.currentTarget.getContext("2d")!;
    const [x, y] = pos(e);
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + 0.1, y + 0.1);
    ctx.stroke();
    setEmpty(false);
  };
  const move = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drawing.current) return;
    const ctx = e.currentTarget.getContext("2d")!;
    const [x, y] = pos(e);
    ctx.lineTo(x, y);
    ctx.stroke();
  };
  const clear = () => {
    const c = canvas.current!;
    c.getContext("2d")!.clearRect(0, 0, c.width, c.height);
    setEmpty(true);
  };

  const save = useMutation({
    mutationFn: async () => {
      const blob: Blob | null = mode === "upload" ? file : await new Promise((ok) => canvas.current!.toBlob(ok, "image/png"));
      if (!blob) throw new Error("Aucune signature");
      const form = new FormData();
      form.append("name", name.trim() || "Signature");
      form.append("file", blob, mode === "upload" && file ? file.name : "signature.png");
      if (userId) form.append("user_id", String(userId));
      return apiUpload<SignatureRow>("/expenses/signatures", form);
    },
    onSuccess: onCreated,
  });

  const ready = mode === "draw" ? !empty : !!file;
  return (
    <Modal title="Nouvelle signature" onClose={onClose}>
      <div className="space-y-4">
        <Field label="Nom" hint="Pour la retrouver dans la liste"><input value={name} maxLength={120} onChange={(e) => setName(e.target.value)} /></Field>
        <div className="flex gap-2 text-sm">
          {(["draw", "upload"] as const).map((m) => (
            <button key={m} type="button" onClick={() => setMode(m)} className={m === mode ? "rounded bg-brand-600 px-3 py-1.5 font-medium text-white" : "rounded px-3 py-1.5 font-medium text-slate-600 ring-1 ring-slate-200"}>
              {m === "draw" ? "Dessiner" : "Importer une image"}
            </button>
          ))}
        </div>
        {mode === "draw" ? (
          <div>
            <canvas ref={canvas} className="h-40 w-full touch-none rounded border border-dashed border-slate-300 bg-white" onPointerDown={down} onPointerMove={move} onPointerUp={() => (drawing.current = false)} onPointerLeave={() => (drawing.current = false)} />
            <div className="mt-1 flex justify-between text-xs text-slate-400"><span>Signez dans le cadre (souris, doigt ou stylet).</span><button type="button" className="text-brand-600" onClick={clear}>Effacer</button></div>
          </div>
        ) : (
          <Field label="Image de la signature" hint="PNG ou JPG, idéalement sur fond blanc ou transparent (2 Mo max.)">
            <input type="file" accept="image/png,image/jpeg" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </Field>
        )}
        <ErrorMsg error={save.error} />
        <div className="flex flex-wrap justify-end gap-2"><Button variant="ghost" onClick={onClose}>Annuler</Button><Button disabled={!ready} busy={save.isPending} onClick={() => save.mutate()}>Enregistrer la signature</Button></div>
      </div>
    </Modal>
  );
}
