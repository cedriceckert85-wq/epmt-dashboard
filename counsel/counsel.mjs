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
 *   --roles <liste>     Rollen, je einmal mit Claude UND Codex besetzt,
 *                       z. B. --roles design,frontend,backend  → 6 Teilnehmer.
 *                       Verfuegbar: architekt, design, frontend, backend
 *                       (Default: architekt → 2 Teilnehmer wie bisher)
 *   --member <e:r>      Einzelnes Mitglied hinzufuegen, z. B. --member codex:frontend
 *                       (mehrfach moeglich; ersetzt --roles, wenn angegeben)
 *   --role-def <n=txt>  Eigene Rolle definieren, z. B. --role-def "security=Du bist
 *                       Security-Engineer und bewertest Angriffsflaechen." (mehrfach)
 *   --moderator <wer>   Wer fasst zusammen: claude | codex (Default: claude)
 *   --first <wer>       Welche Engine je Rolle zuerst spricht: claude | codex (Default: claude)
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
    roles: ["architekt"],
    members: [],
    roleDefs: {},
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
      case "--roles": opts.roles = args.shift().split(",").map((r) => r.trim()).filter(Boolean); break;
      case "--member": opts.members.push(args.shift()); break;
      case "--role-def": {
        const def = args.shift();
        const eq = def.indexOf("=");
        if (eq < 1) die(`--role-def erwartet das Format name=Beschreibung, nicht "${def}".`);
        opts.roleDefs[def.slice(0, eq).trim()] = def.slice(eq + 1).trim();
        break;
      }
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
  const lines = readFileSync(fileURLToPath(import.meta.url), "utf8").split("\n");
  const end = lines.findIndex((l) => l.startsWith(" */"));
  console.log(lines.slice(2, end).map((l) => l.replace(/^ \* ?/, "")).join("\n"));
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

// ------------------------------------------------------------------ Rollen

const ROLES = {
  de: {
    architekt:
      "Software-Architekt: Du bewertest Gesamtarchitektur, Modularitaet, Wartbarkeit und langfristige Folgen der Entscheidung.",
    design:
      "Design-Lead (UI/UX): Du bewertest Nutzerfuehrung, Informationsarchitektur, visuelle Konsistenz, Barrierefreiheit und ob die Loesung fuer die Zielgruppe verstaendlich ist. Technik interessiert dich nur, soweit sie das Nutzererlebnis beeinflusst.",
    frontend:
      "Frontend-Engineer: Du bewertest Umsetzbarkeit im Browser, Komponentenstruktur, State-Handling, Performance (Ladezeit, Rendering), Build-Tooling und Testbarkeit des UI-Codes.",
    backend:
      "Backend-Engineer: Du bewertest Datenmodell, Schnittstellen/APIs, Persistenz, Sicherheit, Skalierung, Betrieb/Deployment und die Folgen fuer Datenintegritaet.",
  },
  en: {
    architekt:
      "Software architect: you assess overall architecture, modularity, maintainability and long-term consequences.",
    design:
      "Design lead (UI/UX): you assess user flows, information architecture, visual consistency, accessibility and whether the solution is understandable for the target audience.",
    frontend:
      "Frontend engineer: you assess browser feasibility, component structure, state handling, performance, build tooling and UI testability.",
    backend:
      "Backend engineer: you assess data model, APIs, persistence, security, scaling, operations/deployment and data integrity.",
  },
};

/** Baut die Teilnehmerliste: pro Rolle je ein Claude- und ein Codex-Mitglied,
 *  oder explizit via --member engine:rolle. */
function buildParticipants(opts) {
  const roleDesc = (role) => {
    const desc = opts.roleDefs[role] || (ROLES[opts.lang] || ROLES.de)[role];
    if (!desc) die(`Unbekannte Rolle "${role}". Verfuegbar: ${Object.keys(ROLES.de).join(", ")} oder eigene via --role-def.`);
    return desc;
  };
  let participants;
  if (opts.members.length) {
    participants = opts.members.map((m) => {
      const [engine, role] = m.split(":").map((s) => s && s.trim());
      if (!["claude", "codex"].includes(engine) || !role) {
        die(`--member erwartet das Format engine:rolle (z. B. claude:frontend), nicht "${m}".`);
      }
      return { engine, role, desc: roleDesc(role) };
    });
  } else {
    const engineOrder = opts.first === "claude" ? ["claude", "codex"] : ["codex", "claude"];
    participants = opts.roles.flatMap((role) =>
      engineOrder.map((engine) => ({ engine, role, desc: roleDesc(role) })),
    );
  }
  for (const p of participants) {
    const sameRoleSameEngine = participants.filter((q) => q.engine === p.engine && q.role === p.role);
    p.name = sameRoleSameEngine.length > 1
      ? `${p.engine}·${p.role}·${sameRoleSameEngine.indexOf(p) + 1}`
      : `${p.engine}·${p.role}`;
  }
  return participants;
}

// ----------------------------------------------------------------- Prompts

const TEXT = {
  de: {
    roleIntro: (self, desc, others, maxWords) =>
      `Du bist "${self.name}" in einem ${others.length + 1}-koepfigen Entscheidungsrat ("Counsel"). ` +
      `Deine Rolle: ${desc} ` +
      `Die weiteren Mitglieder sind: ${others.map((o) => `"${o.name}" (${o.role})`).join(", ")}. ` +
      `Ihr diskutiert eine Software- bzw. Design-Entscheidung und sollt am Ende zu einer gemeinsamen, ` +
      `gut begruendeten Empfehlung kommen. Argumentiere klar aus der Perspektive deiner Rolle, ` +
      `sei konkret, nenne Trade-offs, und aendere deine Meinung, wenn andere besser argumentieren. ` +
      `Antworte auf Deutsch, kompakt (max. ~${maxWords} Woerter), in Markdown ohne Ueberschrift erster Ebene.`,
    opening: `Eroeffne die Diskussion: Analysiere die Fragestellung aus Sicht deiner Rolle, nenne 2-3 realistische Optionen mit Vor- und Nachteilen und sprich eine klare vorlaeufige Empfehlung aus.`,
    reply: `Antworte auf den bisherigen Diskussionsverlauf: Wo stimmst du zu, wo widersprichst du (mit Begruendung)? Ergaenze Aspekte, die aus Sicht deiner Rolle uebersehen wurden. Nenne am Ende deine aktuelle Empfehlung.`,
    lastRound: `Dies ist die letzte Diskussionsrunde: Versuche aktiv, einen Konsens zu formulieren, dem alle Mitglieder zustimmen koennen. Benenne verbleibenden Dissens explizit.`,
    moderator: (self) =>
      `Du bist "${self}" und agierst jetzt als neutraler Moderator des Counsels. ` +
      `Fasse die Diskussion in einem Entscheidungsprotokoll (Decision Record) auf Deutsch zusammen. ` +
      `Nutze exakt diese Markdown-Struktur:\n\n` +
      `## Entscheidung\n(die gemeinsame Empfehlung in 1-3 Saetzen)\n\n` +
      `## Begruendung\n(die staerksten Argumente)\n\n` +
      `## Verworfene Alternativen\n(Optionen und warum sie ausschieden)\n\n` +
      `## Risiken & offene Fragen\n(was unklar bleibt)\n\n` +
      `## Naechste Schritte\n(konkrete, umsetzbare Schritte)\n\n` +
      `## Dissens\n(explizite Restmeinungsverschiedenheiten — nenne jeweils, welches Mitglied/welche Rolle abweicht, oder "keiner")`,
    topicLabel: "Fragestellung",
    contextLabel: "Kontext",
    transcriptLabel: "Bisheriger Diskussionsverlauf",
  },
  en: {
    roleIntro: (self, desc, others, maxWords) =>
      `You are "${self.name}" on a ${others.length + 1}-member decision counsel. ` +
      `Your role: ${desc} ` +
      `The other members are: ${others.map((o) => `"${o.name}" (${o.role})`).join(", ")}. ` +
      `You are debating a software/design decision and must converge on a well-reasoned joint recommendation. ` +
      `Argue clearly from your role's perspective, be concrete, name trade-offs, and change your mind when others argue better. ` +
      `Reply in English, concise (max ~${maxWords} words), in Markdown without a top-level heading.`,
    opening: `Open the discussion: analyse the question from your role's perspective, present 2-3 realistic options with pros and cons, and give a clear preliminary recommendation.`,
    reply: `Respond to the discussion so far: where do you agree, where do you disagree (with reasons)? Add aspects your role sees that were overlooked. End with your current recommendation.`,
    lastRound: `This is the final round: actively try to formulate a consensus all members can accept. Name any remaining dissent explicitly.`,
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

function buildPrompt({ intro, t, opts, transcript, instruction, contextBlock }) {
  let p = `${intro}\n\n# ${t.topicLabel}\n${opts.topic}${contextBlock}`;
  if (transcript.length) {
    const log = transcript.map((turn) => `### ${turn.name} (Runde ${turn.round}):\n${turn.text}`).join("\n\n");
    p += `\n\n# ${t.transcriptLabel}\n${log}`;
  }
  p += `\n\n# Deine Aufgabe\n${instruction}`;
  return p;
}

// -------------------------------------------------------------------- Main

function main() {
  const opts = parseArgs(process.argv.slice(2));
  const t = TEXT[opts.lang] || TEXT.de;

  const contextBlock = buildContextBlock(opts, t);
  const participants = buildParticipants(opts);

  // Nur die CLIs pruefen, die tatsaechlich am Tisch sitzen (inkl. Moderator)
  if (!opts.dryRun) {
    const engines = new Set([...participants.map((p) => p.engine), opts.moderator]);
    if (engines.has("claude")) checkAvailable(opts.claudeCmd, "Claude");
    if (engines.has("codex")) checkAvailable(opts.codexCmd, "Codex");
  }
  const maxWords = participants.length > 2 ? 250 : 400;
  const transcript = [];

  console.error(`\n=== Counsel gestartet: ${opts.topic}`);
  console.error(`=== Mitglieder: ${participants.map((p) => p.name).join(", ")}`);
  console.error(`=== Runden: ${opts.rounds} | Moderator: ${opts.moderator}\n`);

  for (let round = 1; round <= opts.rounds; round++) {
    for (const p of participants) {
      const isFirstTurn = transcript.length === 0;
      const isLastRound = round === opts.rounds;
      let instruction = isFirstTurn ? t.opening : t.reply;
      if (isLastRound && !isFirstTurn) instruction += `\n\n${t.lastRound}`;
      const others = participants.filter((q) => q !== p);
      const intro = t.roleIntro(p, p.desc, others, maxWords);
      const prompt = buildPrompt({ intro, t, opts, transcript, instruction, contextBlock });

      console.error(`--- Runde ${round}: ${p.name} denkt nach ...`);
      const text = runAgent(p.engine, prompt, opts);
      transcript.push({ name: p.name, round, text });
      console.error(`\n### ${p.name} (Runde ${round}):\n${text}\n`);
    }
  }

  console.error(`--- Moderator (${opts.moderator}) erstellt das Entscheidungsprotokoll ...`);
  const modPrompt = buildPrompt({
    intro: t.moderator(opts.moderator),
    t, opts, transcript,
    instruction: opts.lang === "en"
      ? "Write the decision record now, following the structure above."
      : "Erstelle jetzt das Entscheidungsprotokoll gemaess der oben vorgegebenen Struktur.",
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
    `- Mitglieder: ${participants.map((p) => p.name).join(", ")}`,
    `- Runden: ${opts.rounds} | Moderator: ${opts.moderator}`,
    opts.context.length ? `- Kontext: ${opts.context.join(", ")}` : null,
    ``,
    `# Entscheidungsprotokoll`,
    ``,
    decision,
    ``,
    `# Diskussionsverlauf`,
    ``,
    ...transcript.map((turn) => `## ${turn.name} — Runde ${turn.round}\n\n${turn.text}\n`),
  ].filter((l) => l !== null).join("\n");

  writeFileSync(outPath, doc, "utf8");

  console.log(`\n${decision}\n`);
  console.error(`=== Protokoll gespeichert: ${outPath}`);
}

main();
