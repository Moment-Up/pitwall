import { MINUS } from "../../lib/format";
import { splitMinus } from "./kit";

/**
 * Numeral text with the minus sign (U+2212) drawn narrowed (`.pw-minus`, scaleX .62) so a sign change never pushes
 * the digits sideways (spec 4.5, 9.3). The sign stays in the text for assistive tech.
 */
export function NumText({ text }: { text: string }) {
  const { minus, rest } = splitMinus(text);
  if (!minus) return <>{text}</>;
  return (
    <>
      <span className="pw-minus">{MINUS}</span>
      {rest}
    </>
  );
}
