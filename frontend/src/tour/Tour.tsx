import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

export interface TourStep {
  /** Valeur de l'attribut data-tour visé ; absent = étape d'introduction centrée. */
  target?: string;
  title: string;
  body: string;
}

const PAD = 8;

/** Premier élément visible portant cet ancrage (le menu existe en version mobile et ordinateur). */
export function findTarget(target?: string): HTMLElement | null {
  if (!target) return null;
  const all = document.querySelectorAll<HTMLElement>(`[data-tour="${target}"]`);
  for (const el of all) {
    const r = el.getBoundingClientRect();
    // Ignore aussi le menu latéral replié hors de l'écran (mobile)
    if (r.width > 0 && r.height > 0 && r.right > 0 && r.left < window.innerWidth && getComputedStyle(el).visibility !== "hidden") return el;
  }
  return null;
}

type Box = { top: number; left: number; width: number; height: number };

/**
 * Guide pas à pas : la zone décrite est mise en lumière (le reste est assombri), une bulle
 * l'explique. La lumière glisse d'un élément à l'autre ; ← → pour naviguer, Échap pour quitter.
 */
export default function Tour({ steps, onClose }: { steps: TourStep[]; onClose: () => void }) {
  // Les étapes dont l'élément n'existe pas sur la page (liste vide, droits) sont sautées.
  const usable = useMemo(() => steps.filter((s) => !s.target || findTarget(s.target)), [steps]);
  const [i, setI] = useState(0);
  const [box, setBox] = useState<Box | null>(null);
  const [vw, setVw] = useState(window.innerWidth);
  const bubbleRef = useRef<HTMLDivElement>(null);
  const [bubbleH, setBubbleH] = useState(220);
  const step = usable[i];
  const last = i === usable.length - 1;

  const measure = useCallback(() => {
    setVw(window.innerWidth);
    if (bubbleRef.current) setBubbleH(bubbleRef.current.offsetHeight);
    const el = findTarget(step?.target);
    if (!el) return setBox(null);
    const r = el.getBoundingClientRect();
    setBox({ top: r.top - PAD, left: r.left - PAD, width: r.width + PAD * 2, height: r.height + PAD * 2 });
  }, [step]);

  useLayoutEffect(() => {
    const el = findTarget(step?.target);
    el?.scrollIntoView({ behavior: "smooth", block: "center", inline: "nearest" });
    measure();
    // Suit le défilement doux, les redimensionnements et les contenus qui se chargent.
    let raf = 0;
    const loop = () => { measure(); raf = requestAnimationFrame(loop); };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [step, measure]);

  const next = useCallback(() => (last ? onClose() : setI((x) => x + 1)), [last, onClose]);
  const prev = useCallback(() => setI((x) => Math.max(0, x - 1)), []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight" || e.key === "Enter") next();
      else if (e.key === "ArrowLeft") prev();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [next, prev, onClose]);

  if (!step) return null;
  const mobile = vw < 640;
  const width = Math.min(380, vw - 24);
  // Bulle sous l'élément s'il y a la place, sinon au-dessus ; centrée s'il n'y a pas d'élément.
  // Bulle : sous l'élément, sinon au-dessus, sinon à côté, sinon dans un coin (élément très grand).
  const ih = window.innerHeight;
  const h = bubbleH + 16;
  let bubble: React.CSSProperties;
  if (mobile) bubble = box && box.top + box.height > ih - h - 12 && box.top > h + 12 ? { left: 12, right: 12, top: 12 } : { left: 12, right: 12, bottom: 12 };
  else if (!box) bubble = { left: (vw - width) / 2, top: Math.max(12, (ih - h) / 2.5), width };
  else {
    const left = Math.min(Math.max(box.left, 12), vw - width - 12);
    const sideTop = Math.min(Math.max(box.top, 12), ih - h);
    if (ih - (box.top + box.height) >= h + 12) bubble = { left, top: box.top + box.height + 12, width };
    else if (box.top >= h + 12) bubble = { left, top: box.top - h, width };
    else if (vw - (box.left + box.width) >= width + 24) bubble = { left: box.left + box.width + 16, top: sideTop, width };
    else if (box.left >= width + 24) bubble = { left: box.left - width - 16, top: sideTop, width };
    else bubble = { right: 16, bottom: 16, width };
  }

  return (
    <div className="fixed inset-0 z-[100]" role="dialog" aria-modal="true" aria-label={`Guide : ${step.title}`}>
      {/* Bloque les clics sur la page pendant le guide */}
      <div className="absolute inset-0" onClick={(e) => e.stopPropagation()} />
      {box ? (
        <div className="tour-spot pointer-events-none fixed rounded-lg" style={box}>
          <div className="tour-pulse absolute inset-0 rounded-lg" />
        </div>
      ) : (
        <div className="tour-fade pointer-events-none fixed inset-0 bg-[rgba(12,20,17,0.62)]" />
      )}
      <div ref={bubbleRef} key={i} className="tour-in fixed rounded-lg border border-slate-200 bg-white p-4 shadow-2xl sm:p-5" style={bubble}>
        <div className="mb-1 flex items-center justify-between gap-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-brand-600">Étape {i + 1}/{usable.length}</p>
          <button className="text-xs text-slate-400 hover:text-slate-700" onClick={onClose}>Passer le guide</button>
        </div>
        <h3 className="font-serif text-lg font-semibold text-slate-900">{step.title}</h3>
        <p className="mt-1.5 max-h-[40vh] overflow-y-auto whitespace-pre-line text-sm leading-relaxed text-slate-600">{step.body}</p>
        <div className="mt-4 flex items-center justify-between gap-3">
          <div className="flex flex-wrap gap-1">
            {usable.map((_, k) => (
              <button key={k} aria-label={`Étape ${k + 1}`} onClick={() => setI(k)}
                className={`h-1.5 rounded-full transition-all duration-300 ${k === i ? "w-5 bg-brand-600" : "w-1.5 bg-slate-300 hover:bg-slate-400"}`} />
            ))}
          </div>
          <div className="flex shrink-0 gap-2">
            {i > 0 && <button className="rounded px-3 py-1.5 text-sm text-slate-600 ring-1 ring-slate-300 hover:bg-slate-50" onClick={prev}>Précédent</button>}
            <button autoFocus className="rounded bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700" onClick={next}>{last ? "Terminer" : "Suivant"}</button>
          </div>
        </div>
      </div>
    </div>
  );
}
