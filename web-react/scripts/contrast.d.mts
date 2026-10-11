// Types for scripts/contrast.mjs, so the vitest suite (src/styles/tokens.test.ts) can run the same checks under
// `tsc --strict` without pulling Node's types into the browser program.

export type Rgba = [number, number, number, number];
export type ModeName = "dark" | "light" | "night" | "rg-dark" | "rg-light" | "rg-night";

export interface ContrastResult {
  mode: ModeName;
  fg: string;
  bg: string;
  what: string;
  ratio: number;
  target: number;
  aim: number | null;
  pass: boolean;
  warn: boolean;
  fgHex: string;
  bgHex: string;
}

export interface ContrastReport {
  results: ContrastResult[];
  errors: string[];
  ok: boolean;
}

export interface CssRule {
  selectors: string[];
  decls: Map<string, string>;
  source: string;
}

export const MODES: Record<ModeName, { classes: string[]; attrs: Record<string, string> }>;
export const DEPRECATED_ALIASES: Record<string, string>;
export const DEFAULT_TOKENS_PATH: string;
export const DEFAULT_HEROUI_PATH: string;

export function parseRules(css: string, source?: string): CssRule[];
export function matchRoot(selector: string, el: { classes: string[]; attrs: Record<string, string> }): number | null;
export function cascade(rules: CssRule[], el: { classes: string[]; attrs: Record<string, string> }): Map<string, string>;
export function resolveVar(props: Map<string, string>, name: string): string | null;
export function parseColor(css: string): Rgba | null;
export function over(fg: Rgba, bg: Rgba): Rgba;
export function contrast(a: Rgba, b: Rgba): number;
export function hex(c: Rgba): string;
export function modeColours(rules: CssRule[], mode: ModeName): { props: Map<string, string>; colour: (name: string) => Rgba | null };
export function parityErrors(tokenRules: CssRule[]): string[];
export function runContrast(input: { tokensCss: string; herouiCss: string }): ContrastReport;
export function checkFiles(paths?: { tokensPath?: string; herouiPath?: string }): ContrastReport;
/** The stylesheet text at `path` (the script's own reader, so tests need no Node types). */
export function readText(path: string): string;
