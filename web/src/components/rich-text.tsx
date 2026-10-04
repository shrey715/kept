// The little markdown the model and the policy documents use (**bold**, *italic*, `code`, "- " lists,
// "#" headings, line breaks), rendered as text. ponytail: no markdown library; tables and links stay plain.
import { Fragment } from "react";

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|(?<![\w*])\*[^*\s][^*]*\*(?![\w*]))/g;

/** One line: bold, italic and code spans. */
export function inline(text: string, key = ""): React.ReactNode[] {
  return text.split(INLINE).map((p, i) => {
    const k = `${key}-${i}`;
    if (p.startsWith("**") && p.endsWith("**") && p.length > 4) return <strong key={k}>{p.slice(2, -2)}</strong>;
    if (p.startsWith("`") && p.endsWith("`") && p.length > 2)
      return <code key={k} style={{ fontFamily: "var(--code-font-family)", fontSize: "0.9em", background: "var(--gray-a3)", borderRadius: 4, padding: "0 4px" }}>{p.slice(1, -1)}</code>;
    if (p.startsWith("*") && p.endsWith("*") && p.length > 2) return <em key={k}>{p.slice(1, -1)}</em>;
    return <Fragment key={k}>{p}</Fragment>;
  });
}

/** A block of text: paragraphs, "- " / "1. " lists and "#" headings, each line with inline formatting. */
export function Rich({ text }: { text: string }) {
  const out: React.ReactNode[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  const flush = () => {
    if (!list) return;
    const Tag = list.ordered ? "ol" : "ul";
    out.push(<Tag key={`l${out.length}`} style={{ margin: "4px 0", paddingLeft: "1.3em" }}>{list.items.map((t, i) => <li key={i}>{inline(t, `li${i}`)}</li>)}</Tag>);
    list = null;
  };
  text.split("\n").forEach((raw, i) => {
    const line = raw.trimEnd();
    const item = line.match(/^\s*(?:[-*•]|(\d+)[.)])\s+(.*)$/);
    if (item) {
      const ordered = item[1] !== undefined;
      if (list && list.ordered !== ordered) flush();
      list ??= { ordered, items: [] };
      list.items.push(item[2]);
      return;
    }
    flush();
    const h = line.match(/^#{1,6}\s+(.*)$/);
    if (h) out.push(<strong key={i} style={{ display: "block", marginTop: 6 }}>{inline(h[1], `h${i}`)}</strong>);
    else if (line.trim()) out.push(<span key={i} style={{ display: "block" }}>{inline(line, `p${i}`)}</span>);
    else out.push(<span key={i} style={{ display: "block", height: "0.5em" }} />);
  });
  flush();
  return <>{out}</>;
}

/** The text without markdown markers, plus where each original offset landed, so a highlight computed on
 * the original text can be drawn on the clean one. */
export function stripMarks(text: string): { plain: string; at: (i: number) => number } {
  const map: number[] = [];
  let plain = "";
  for (let i = 0; i < text.length; i++) {
    map.push(plain.length);
    const two = text.slice(i, i + 2);
    if (two === "**") {
      map.push(plain.length);
      i++;
      continue;
    }
    if (text[i] === "`") continue;
    if (text[i] === "#" && (i === 0 || text[i - 1] === "\n")) {
      while (text[i + 1] === "#" || text[i + 1] === " ") {
        map.push(plain.length);
        i++;
      }
      continue;
    }
    plain += text[i];
  }
  map.push(plain.length);
  return { plain, at: (i) => map[Math.min(i, map.length - 1)] };
}
