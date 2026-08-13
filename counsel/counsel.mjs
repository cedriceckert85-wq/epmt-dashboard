#!/usr/bin/env node
/**
 * counsel — Claude Code CLI und Codex CLI diskutieren gemeinsam
 * Software- und Design-Entscheidungen und erzeugen am Ende ein
 * Entscheidungsprotokoll (Decision Record).
 *
 * Nutzung:
 *   node counsel/counsel.mjs "Sollen wir das Dashboard auf React umstellen?"
 *
 * Optionen:
 *   --rounds <n>        Anzahl der Diskussionsrunden (Default: 2)
 *   --moderator <wer>   Wer fasst zusammen: claude | codex (Default: claude)
 *   --first <wer>       Wer eroeffnet: claude | codex (Default: claude)
 *   --context <datei>   Datei als Kontext mitgeben (mehrfach moeglich)
 *   --lang <de|en>      Sprache der Diskussion (Default: de)
 *   --out <datei>       Pfad fuer das Protokoll (Default: counsel/sessions/...)
 *   --claude-cmd <cmd>  Befehl fuer Claude (Default: "claude")
 *   --codex-cmd <cmd>   Befehl fuer Codex (Default: "codex")
 *   --model-claude <m>  Modell fuer Claude (optional)
 *   --model-codex <m>   Modell fuer Codex (optional)
 *   --timeout <sek>     Timeout pro CLI-Aufruf in Sekunden (Default: 600)
 *   --dry-run           Ohne echte CLIs testen (Stub-Antworten)
 *   -h, --help          Hilfe anzeigen
 */

import { spawnSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync, mkdtempSync, rmSync } from "node:fs";
import { join, dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { tmpdir } from "node:os";

const __dirname = dirname(fileURLToPath(import.meta.url));

// ---------------------------------------------------------------- Argumente

function parseArgs(argv) {
  const opts = {
    topic: null,
    rounds: 2,
    moderator: "claude",
    first: "claude",
    context: [],
    lang: "de",
    out: null,
    claudeCmd: "claude",
    codexCmd: "codex",
    modelClaude: null,
    modelCodex: null,
    timeout: 600,
    dryRun: false,
  };
  const args = [...argv];
  while (args.length) {
    const a = args.shift();
    switch (a) {
      case "--rounds": opts.rounds = parseInt(args.shift(), 10); break;
      case "--moderator": opts.moderator = args.shift(); break;
      case "--first": opts.first = args.shift(); break;
      case "--context": opts.context.push(args.shift()); break;
      case "--lang": opts.lang = args.shift(); break;
      case "--out": opts.out = args.shift(); break;
      case "--claude-cmd": opts.claudeCmd = args.shift(); break;
      case "--codex-cmd": opts.codexCmd = args.shift(); break;
      case "--model-claude": opts.modelClaude = args.shift(); break;
      case "--model-codex": opts.modelCodex = args.shift(); break;
      case "--timeout": opts.timeout = parseInt(args.shift(), 10); break;
      case "--dry-run": opts.dryRun = true; break;
      case "-h":
      case "--help": printHelp(); process.exit(0);
      default:
        if (a.startsWith("--")) die(`Unbekannte Option: ${a} (siehe --help)`);
        opts.topic = opts.topic ? `${opts.topic} ${a}` : a;
    }
  }
  if (!opts.topic) die('Kein Thema angegeben. Beispiel: node counsel/counsel.mjs "Frage..."');
  if (!Number.isInteger(opts.rounds) || opts.rounds < 1) die("--rounds muss eine Zahl >= 1 sein.");
  for (const who of [opts.moderator, opts.first]) {
    if (!["claude", "codex"].includes(who)) die(`--moderator/--first muss "claude" oder "codex" sein, nicht "${who}".`);
  }
  return opts;
}

function printHelp() {
  const header = readFileSync(fileURLToPath(import.meta.url), "utf8")
    .split("\n").slice(1, 28).map((l) => l.replace(/^ \* ?/, "")).join("\n");
  console.log(header);
}

function die(msg) {
  console.error(`counsel: ${msg}`);
  process.exit(1);
}

// ------------------------------------------------------------- CLI-Adapter

function checkAvailable(cmd, name) {
  const res = spawnSync(cmd, ["--version"], { encoding: "utf8", shell: false });
  if (res.error || res.status !== 0) {
    die(`Die ${name}-CLI ("${cmd}") wurde nicht gefunden oder startet nicht.\n` +
        `  Installation: ${name === "Codex" ? "npm install -g @openai/codex" : "npm install -g @anthropic-ai/claude-code"}\n` +
        `  Alternativ mit --${name.toLowerCase()}-cmd einen anderen Befehl angeben oder --dry-run nutzen.`);
  }
}

/** Claude Code CLI nicht-interaktiv: Prompt via stdin, Antwort auf stdout. */
function runClaude(prompt, opts) {
  const args = ["-p", "--output-format", "text"];
  if (opts.modelClaude) args.push("--model", opts.modelClaude);
  const res = spawnSync(opts.claudeCmd, args, {
    input: prompt,
    encoding: "utf8",
    timeout: opts.timeout * 1000,
    maxBuffer: 32 * 1024 * 1024,
  });
  if (res.error) die(`Claude-Aufruf fehlgeschlagen: ${res.error.message}`);
  if (res.status !== 0) die(`Claude-Aufruf fehlgeschlagen (Exit ${res.status}):\n${res.stderr || res.stdout}`);
  return res.stdout.trim();
}

/** Codex CLI nicht-interaktiv: `codex exec -` liest den Prompt von stdin;
 *  die letzte Agentennachricht wird sauber ueber --output-last-message gelesen. */
function runCodex(prompt, opts) {
  const tmp = mkdtempSync(join(tmpdir(), "counsel-"));
  const outFile = join(tmp, "last-message.txt");
  try {
    const args = ["exec", "--sandbox", "read-only", "--skip-git-repo-check",
                  "--color", "never", "--output-last-message", outFile];
    if (opts.modelCodex) args.push("--model", opts.modelCodex);
    args.push("-");
    const res = spawnSync(opts.codexCmd, args, {
      input: prompt,
      encoding: "utf8",
      timeout: opts.timeout * 1000,
      maxBuffer: 32 * 1024 * 1024,
    });
    if (res.error) die(`Codex-Aufruf fehlgeschlagen: ${res.error.message}`);
    if (res.status !== 0) die(`Codex-Aufruf fehlgeschlagen (Exit ${res.status}):\n${res.stderr || res.stdout}`);
    let out = "";
    try { out = readFileSync(outFile, "utf8").trim(); } catch { /* Fallback unten */ }
    return out || res.stdout.trim();
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }
}

function runAgent(who, prompt, opts) {
  if (opts.dryRun) {
    return `[dry-run] Antwort von ${who} auf einen Prompt mit ${prompt.length} Zeichen.`;
  }
  return who === "claude" ? runClaude(prompt, opts) : runCodex(prompt, opts);
}

// ----------------------------------------------------------------- Prompts

const TEXT = {
  de: {
    roleIntro: (self, other) =>
      `Du bist "${self}", ein Software-Architekt in einem zweikoepfigen Entscheidungsrat ("Counsel"). ` +
      `Dein Gegenueber ist "${other}". Ihr diskutiert eine Software- bzw. Design-Entscheidung und sollt ` +
      `am Ende zu einer gemeinsamen, gut begruendeten Empfehlung kommen. ` +
      `Sei konkret, nenne Trade-offs, und aendere deine Meinung, wenn die Argumente des anderen besser sind. ` +
      `Antworte auf Deutsch, kompakt (max. ~400 Woerter), in Markdown ohne Ueberschrift erster Ebene.`,
    opening: `Eroeffne die Diskussion: Analysiere die Fragestellung, nenne 2-3 realistische Optionen mit Vor- und Nachteilen und sprich eine klare vorlaeufige Empfehlung aus.`,
    reply: `Antworte auf den bisherigen Diskussionsverlauf: Wo stimmst du zu, wo widersprichst du (mit Begruendung)? Ergaenze uebersehene Aspekte. Nenne am Ende deine aktuelle Empfehlung.`,
    lastRound: `Dies ist die letzte Diskussionsrunde: Versuche aktiv, einen Konsens zu formulieren, dem beide zustimmen koennen. Benenne verbleibenden Dissens explizit.`,
    moderator: (self) =>
      `Du bist "${self}" und agierst jetzt als neutraler Moderator des Counsels. ` +
      `Fasse die Diskussion in einem Entscheidungsprotokoll (Decision Record) auf Deutsch zusammen. ` +
      `Nutze exakt diese Markdown-Struktur:\n\n` +
      `## Entscheidung\n(die gemeinsame Empfehlung in 1-3 Saetzen)\n\n` +
      `## Begruendung\n(die staerksten Argumente)\n\n` +
      `## Verworfene Alternativen\n(Optionen und warum sie ausschieden)\n\n` +
      `## Risiken & offene Fragen\n(was unklar bleibt)\n\n` +
      `## Naechste Schritte\n(konkrete, umsetzbare Schritte)\n\n` +
      `## Dissens\n(explizite Restmeinungsverschiedenheiten, oder "keiner")`,
    topicLabel: "Fragestellung",
    contextLabel: "Kontext",
    transcriptLabel: "Bisheriger Diskussionsverlauf",
  },
  en: {
    roleIntro: (self, other) =>
      `You are "${self}", a software architect on a two-member decision counsel. ` +
      `Your counterpart is "${other}". You are debating a software/design decision and must ` +
      `converge on a well-reasoned joint recommendation. ` +
      `Be concrete, name trade-offs, and change your mind when the other side argues better. ` +
      `Reply in English, concise (max ~400 words), in Markdown without a top-level heading.`,
    opening: `Open the discussion: analyse the question, present 2-3 realistic options with pros and cons, and give a clear preliminary recommendation.`,
    reply: `Respond to the discussion so far: where do you agree, where do you disagree (with reasons)? Add overlooked aspects. End with your current recommendation.`,
    lastRound: `This is the final round: actively try to formulate a consensus both can accept. Name any remaining dissent explicitly.`,
    moderator: (self) =>
      `You are "${self}", now acting as the counsel's neutral moderator. ` +
      `Summarise the discussion as a decision record in English using exactly this Markdown structure:\n\n` +
      `## Decision\n\n## Rationale\n\n## Rejected alternatives\n\n## Risks & open questions\n\n## Next steps\n\n## Dissent`,
    topicLabel: "Question",
    contextLabel: "Context",
    transcriptLabel: "Discussion so far",
  },
};

function buildContextBlock(opts, t) {
  if (!opts.context.length) return "";
  const parts = opts.context.map((p) => {
    const abs = resolve(p);
    let body;
    try { body = readFileSync(abs, "utf8"); } catch (e) { die(`Kontextdatei nicht lesbar: ${p} (${e.message})`); }
    if (body.length > 60_000) body = body.slice(0, 60_000) + "\n[... gekuerzt ...]";
    return `--- Datei: ${p} ---\n${body}`;
  });
  return `\n\n# ${t.contextLabel}\n${parts.join("\n\n")}`;
}

function buildPrompt({ self, other, t, opts, transcript, instruction, contextBlock }) {
  let p = `${t.roleIntro(self, other)}\n\n# ${t.topicLabel}\n${opts.topic}${contextBlock}`;
  if (transcript.length) {
    const log = transcript.map((turn) => `### ${turn.who} (Runde ${turn.round}):\n${turn.text}`).join("\n\n");
    p += `\n\n# ${t.transcriptLabel}\n${log}`;
  }
  p += `\n\n# Deine Aufgabe\n${instruction}`;
  return p;
}

// -------------------------------------------------------------------- Main

function main() {
  const opts = parseArgs(process.argv.slice(2));
  const t = TEXT[opts.lang] || TEXT.de;

  if (!opts.dryRun) {
    checkAvailable(opts.claudeCmd, "Claude");
    checkAvailable(opts.codexCmd, "Codex");
  }

  const contextBlock = buildContextBlock(opts, t);
  const order = opts.first === "claude" ? ["claude", "codex"] : ["codex", "claude"];
  const transcript = [];

  console.error(`\n=== Counsel gestartet: ${opts.topic}`);
  console.error(`=== Runden: ${opts.rounds} | Eroeffnung: ${order[0]} | Moderator: ${opts.moderator}\n`);

  for (let round = 1; round <= opts.rounds; round++) {
    for (const who of order) {
      const isFirstTurn = transcript.length === 0;
      const isLastRound = round === opts.rounds;
      let instruction = isFirstTurn ? t.opening : t.reply;
      if (isLastRound && !isFirstTurn) instruction += `\n\n${t.lastRound}`;
      const other = who === "claude" ? "codex" : "claude";
      const prompt = buildPrompt({ self: who, other, t, opts, transcript, instruction, contextBlock });

      console.error(`--- Runde ${round}: ${who} denkt nach ...`);
      const text = runAgent(who, prompt, opts);
      transcript.push({ who, round, text });
      console.error(`\n### ${who} (Runde ${round}):\n${text}\n`);
    }
  }

  console.error(`--- Moderator (${opts.moderator}) erstellt das Entscheidungsprotokoll ...`);
  const modPrompt = buildPrompt({
    self: opts.moderator,
    other: opts.moderator === "claude" ? "codex" : "claude",
    t, opts, transcript,
    instruction: t.moderator(opts.moderator),
    contextBlock,
  });
  const decision = runAgent(opts.moderator, modPrompt, opts);

  // Protokoll schreiben
  const stamp = new Date().toISOString().replace(/[:T]/g, "-").slice(0, 16);
  const slug = opts.topic.toLowerCase().replace(/[^a-z0-9äöüß]+/gi, "-").replace(/^-+|-+$/g, "").slice(0, 60);
  const outPath = opts.out || join(__dirname, "sessions", `${stamp}-${slug}.md`);
  mkdirSync(dirname(outPath), { recursive: true });

  const doc = [
    `# Counsel: ${opts.topic}`,
    ``,
    `- Datum: ${new Date().toISOString()}`,
    `- Teilnehmer: claude (Claude Code CLI), codex (Codex CLI)`,
    `- Runden: ${opts.rounds} | Eroeffnung: ${order[0]} | Moderator: ${opts.moderator}`,
    opts.context.length ? `- Kontext: ${opts.context.join(", ")}` : null,
    ``,
    `# Entscheidungsprotokoll`,
    ``,
    decision,
    ``,
    `# Diskussionsverlauf`,
    ``,
    ...transcript.map((turn) => `## ${turn.who} — Runde ${turn.round}\n\n${turn.text}\n`),
  ].filter((l) => l !== null).join("\n");

  writeFileSync(outPath, doc, "utf8");

  console.log(`\n${decision}\n`);
  console.error(`=== Protokoll gespeichert: ${outPath}`);
}

main();
