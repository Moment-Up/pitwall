<script lang="ts">
  import { api, type EngineerAnswer, type SessionRow } from "../lib/api";
  import { live } from "../lib/live.svelte";

  interface Msg {
    role: "user" | "engineer";
    text: string;
    answer?: EngineerAnswer;
  }

  let sessions = $state<SessionRow[]>([]);
  let sessionId = $state<string | null>(null);
  let messages = $state<Msg[]>([]);
  let question = $state("");
  let busy = $state(false);
  let useLlm = $state(true);
  let llm = $state<any>(null);
  let openFacts = $state<number | null>(null);
  let speak = $state(false);

  const suggestions = [
    "Where am I losing the most time?",
    "Give me one thing to work on.",
    "Where should I be braking for Turn 1?",
    "Compare that lap to my best.",
    "How are my tyres?",
    "What's my fuel situation?",
    "Should I change my front wing?",
  ];

  $effect(() => {
    api.sessions().then((r) => {
      sessions = r;
      sessionId = live.snap?.session_id ?? r[0]?.id ?? null;
    });
    api.llmHealth().then((h) => (llm = h)).catch(() => (llm = { ok: false, detail: "unreachable" }));
  });

  $effect(() => {
    if (!sessionId) return;
    api.history(sessionId).then((h) => {
      messages = h.map((m: any) => ({ role: m.role, text: m.text }));
    });
  });

  async function ask(q: string) {
    if (!q.trim() || busy) return;
    messages.push({ role: "user", text: q });
    question = "";
    busy = true;
    try {
      const a = await api.ask(q, sessionId, useLlm);
      messages.push({ role: "engineer", text: a.text, answer: a });
      if (speak && "speechSynthesis" in window) {
        speechSynthesis.cancel();
        speechSynthesis.speak(new SpeechSynthesisUtterance(a.speech));
      }
    } catch (e) {
      messages.push({ role: "engineer", text: `Error: ${e}` });
    } finally {
      busy = false;
    }
  }

  function render(text: string): string {
    const esc = text.replace(/&/g, "&amp;").replace(/</g, "&lt;");
    return esc.replace(/\[(F\d+)\]/g, '<sup class="cite">$1</sup>');
  }
</script>

<div class="eng">
  <section class="panel side">
    <h3>Context</h3>
    <label class="field">
      <span class="muted small">Session</span>
      <select bind:value={sessionId}>
        {#each sessions as s (s.id)}
          <option value={s.id}>{s.track_name ?? "?"} · {s.lap_count} laps{s.synthetic ? " · synthetic" : ""}</option>
        {/each}
      </select>
    </label>
    <label class="check"><input type="checkbox" bind:checked={useLlm} /> Use local LLM (off = deterministic answers)</label>
    <label class="check"><input type="checkbox" bind:checked={speak} /> Speak answers (browser voice)</label>
    <h3 style="margin-top:16px">Model</h3>
    {#if llm}
      <div class="small">
        <span class={llm.ok ? "gain" : "bad"}>{llm.ok ? "● online" : "● offline"}</span>
        <div class="muted mono">{llm.model ?? ""}</div>
        <div class="faint">{llm.base_url ?? ""} · ctx {llm.context_tokens ?? "?"}</div>
        {#if !llm.ok}<div class="muted">The engineer still answers deterministically from telemetry.</div>{/if}
      </div>
    {/if}
    <h3 style="margin-top:16px">How answers work</h3>
    <p class="small muted">The model only sees validated facts computed from your telemetry (each with an ID like F12). Every number in an answer is checked against those facts; ungrounded answers are rejected and replaced with a deterministic one.</p>
  </section>

  <section class="panel chat">
    <div class="msgs">
      {#each messages as m, i (i)}
        <div class="msg {m.role}">
          <div class="bubble">{@html render(m.text)}</div>
          {#if m.answer}
            <div class="meta small">
              <span class={m.answer.fallback ? "loss" : "gain"}>{m.answer.fallback ? "deterministic" : "LLM"}</span>
              {#if m.answer.grounded}<span class="gain">grounded</span>{/if}
              <span class="faint">{m.answer.intent}{m.answer.corner ? ` · ${m.answer.corner}` : ""} · {(m.answer.latency_ms / 1000).toFixed(1)}s</span>
              {#if m.answer.facts.length}
                <button class="link" onclick={() => (openFacts = openFacts === i ? null : i)}>{m.answer.facts.length} facts</button>
              {/if}
            </div>
            {#if openFacts === i}
              <ul class="facts small">
                {#each m.answer.facts as f (f.id)}<li><span class="cite">{f.id}</span> {f.text}</li>{/each}
              </ul>
            {/if}
          {/if}
        </div>
      {:else}
        <div class="empty">Ask your race engineer about the selected session.</div>
      {/each}
      {#if busy}<div class="msg engineer"><div class="bubble muted">Engineer is thinking… (local model)</div></div>{/if}
    </div>
    <div class="chips">
      {#each suggestions as s}<button class="chip" onclick={() => ask(s)} disabled={busy}>{s}</button>{/each}
    </div>
    <form class="input" onsubmit={(e) => { e.preventDefault(); ask(question); }}>
      <input bind:value={question} placeholder="Engineer, why am I losing time through Turn 3?" aria-label="Question" />
      <button class="primary" disabled={busy || !question.trim()}>Ask</button>
    </form>
  </section>
</div>

<style>
  .eng { display: grid; grid-template-columns: 300px 1fr; gap: 12px; height: calc(100vh - 110px); min-height: 520px; }
  .side { overflow: auto; }
  .chat { display: grid; grid-template-rows: 1fr auto auto; gap: 10px; min-height: 0; }
  .msgs { overflow: auto; display: grid; gap: 14px; align-content: start; padding-right: 4px; }
  .msg { display: grid; gap: 4px; max-width: 760px; }
  .msg.user { justify-self: end; }
  .bubble { padding: 10px 14px; border-radius: 12px; line-height: 1.5; background: var(--panel-2); border: 1px solid var(--border); }
  .msg.user .bubble { background: color-mix(in srgb, var(--accent) 16%, var(--panel)); }
  .meta { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .facts { margin: 4px 0 0; padding-left: 16px; display: grid; gap: 4px; color: var(--muted); }
  :global(.cite) { font-family: var(--mono); font-size: 10px; color: var(--ref); margin-left: 2px; }
  .chips { display: flex; gap: 6px; flex-wrap: wrap; }
  .chip { font-size: 12px; padding: 4px 10px; border-radius: 999px; }
  .input { display: flex; gap: 8px; }
  .input input { flex: 1; }
  .field { display: grid; gap: 4px; margin-bottom: 10px; }
  .field select { width: 100%; }
  .check { display: flex; gap: 8px; align-items: center; font-size: 13px; margin: 6px 0; }
  .small { font-size: 12px; }
  .mono { font-family: var(--mono); word-break: break-all; }
  button.link { background: none; border: none; color: var(--ref); padding: 0; text-decoration: underline; }
  @media (max-width: 800px) { .eng { grid-template-columns: 1fr; height: auto; } .msgs { max-height: 60vh; } }
</style>
