// Settings › Radio & voice, "What the radio says" (v0.3.0): the radio's one policy, read from GET /api/radio/policy
// (voice.scheduler.POLICY) so the page says what the code does. RadioPolicyCardView is pure (render tests); an older
// server without the endpoint shows no card.

import { useApi } from "../../../hooks/useApi";
import { RADIO_POLICY_KEY, radioPolicyApi, type RadioPolicy } from "../../../lib/endpoints/radiopolicy";
import { CellGroup, CellRow } from "../cells";
import { POLICY_TITLE, policyRows, policySummary } from "./policy-model";

export function RadioPolicyCardView({ policy }: { policy: RadioPolicy | null | undefined }) {
  if (!policy) return null;
  return (
    <section className="grid min-w-0 gap-2" aria-label={POLICY_TITLE}>
      <h3 className="m-0 px-1 text-sm font-semibold text-muted">{POLICY_TITLE}</h3>
      <p className="m-0 px-1 text-sm text-muted">{policySummary(policy)}</p>
      <CellGroup label={POLICY_TITLE}>
        {policyRows(policy).map((r) => (
          <CellRow key={r.key} title={r.title} hint={r.hint} />
        ))}
      </CellGroup>
    </section>
  );
}

export function RadioPolicyCard() {
  const q = useApi(RADIO_POLICY_KEY, radioPolicyApi.get, { maxAgeMs: 60_000 });
  return <RadioPolicyCardView policy={q.data} />;
}
