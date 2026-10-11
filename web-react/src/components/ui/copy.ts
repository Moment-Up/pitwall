// Copy-to-clipboard for CopyField. The async Clipboard API needs a secure context (HTTPS / localhost), but Pitwall
// is also opened over plain HTTP on the LAN (http://192.168.x.x:8770), so it falls back to the legacy
// execCommand("copy") on a temporary textarea. Returns false when neither works (the value stays selectable).
// Browser globals are injectable so the logic is tested in plain node.

export interface CopyEnv {
  clipboard?: { writeText(text: string): Promise<void> } | null;
  /** Legacy fallback: put the text in a hidden textarea, select it, execCommand("copy"). */
  legacyCopy?: ((text: string) => boolean) | null;
}

function legacyCopy(text: string): boolean {
  if (typeof document === "undefined" || !document.body) return false;
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.top = "-1000px";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  try {
    ta.select();
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    ta.remove();
  }
}

function defaultEnv(): CopyEnv {
  const nav = typeof navigator !== "undefined" ? navigator : undefined;
  const secure = typeof window !== "undefined" && window.isSecureContext === true;
  return { clipboard: secure ? (nav?.clipboard ?? null) : null, legacyCopy };
}

export async function copyText(text: string, env: CopyEnv = defaultEnv()): Promise<boolean> {
  if (text === "") return false;
  if (env.clipboard) {
    try {
      await env.clipboard.writeText(text);
      return true;
    } catch {
      /* permission refused or not focused: try the legacy path */
    }
  }
  return env.legacyCopy ? env.legacyCopy(text) : false;
}
