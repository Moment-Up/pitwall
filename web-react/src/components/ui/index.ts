// Pitwall UI kit (design spec v2, 10.6). Lane T owns this folder; other lanes import from here.
//
//   import { TimingValue, TimingCell, TimingTag, TimingLegend, EvidenceChips, CornerTag, Glossary, Unknown,
//            SettingValue, RangeMarker, CopyField } from "../components/ui";
//
// Styles live in src/styles/index.css (`.pw-*` component classes) and read tokens from src/styles/tokens.css.

export { copyText, type CopyEnv } from "./copy";
export { CopyField } from "./CopyField";
export { CornerTag } from "./CornerTag";
export { EvidenceChips } from "./EvidenceChips";
export { Glossary } from "./Glossary";
export { GLOSSARY, type GlossaryEntry } from "./glossary-terms";
export {
  cx,
  deltaToneOf,
  evidenceOf,
  isTagged,
  legendItems,
  numeralFontSize,
  rangeDescription,
  rangeGeometry,
  settingText,
  sizeStyle,
  splitMinus,
  tagFor,
  TAGS,
  timingText,
  type LegendItem,
  type RangeGeometry,
  type TaggedStatus,
} from "./kit";
export { NumText } from "./NumText";
export { RangeMarker } from "./RangeMarker";
export { SettingValue } from "./SettingValue";
export { TimingCell } from "./TimingCell";
export { TimingLegend } from "./TimingLegend";
export { TimingTag } from "./TimingTag";
export { TimingValue } from "./TimingValue";
export { Unknown } from "./Unknown";
export type * from "./types";
