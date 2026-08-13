//! Counsel GUI — Claude & Codex diskutieren, du liest live mit.
//!
//! Duenner Wrapper um `counsel/counsel.mjs`: startet das Skript als
//! Kindprozess, zeigt stderr (Diskussionsverlauf) live im Mitlese-Feld
//! und stdout (Entscheidungsprotokoll) im Ergebnis-Feld.

use eframe::egui;
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::{Arc, Mutex};

fn main() -> eframe::Result {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1000.0, 760.0])
            .with_title("Counsel — Claude & Codex"),
        ..Default::default()
    };
    eframe::run_native(
        "Counsel",
        options,
        Box::new(|cc| {
            cc.egui_ctx.set_pixels_per_point(1.15);
            Ok(Box::new(CounselApp::default()))
        }),
    )
}

enum Msg {
    Log(String),
    Result(String),
    Done(Option<i32>),
}

#[derive(PartialEq, Clone, Copy)]
enum Panel {
    Architekten,
    Volles,
}

struct CounselApp {
    topic: String,
    rounds: u32,
    panel: Panel,
    log: String,
    result: String,
    running: bool,
    rx: Option<Receiver<Msg>>,
    child: Arc<Mutex<Option<Child>>>,
}

impl Default for CounselApp {
    fn default() -> Self {
        Self {
            topic: String::new(),
            rounds: 2,
            panel: Panel::Architekten,
            log: String::new(),
            result: String::new(),
            running: false,
            rx: None,
            child: Arc::new(Mutex::new(None)),
        }
    }
}

/// Sucht counsel.mjs relativ zum Arbeitsverzeichnis bzw. zur Binary,
/// ueberschreibbar per COUNSEL_SCRIPT.
fn find_script() -> Option<PathBuf> {
    if let Ok(p) = std::env::var("COUNSEL_SCRIPT") {
        let p = PathBuf::from(p);
        return p.exists().then_some(p);
    }
    let mut candidates: Vec<PathBuf> = vec![
        "counsel/counsel.mjs".into(),
        "../counsel/counsel.mjs".into(),
    ];
    if let Ok(exe) = std::env::current_exe() {
        for anc in exe.ancestors().skip(1).take(5) {
            candidates.push(anc.join("counsel/counsel.mjs"));
        }
    }
    candidates.into_iter().find(|p| p.exists())
}

impl CounselApp {
    fn start(&mut self) {
        let script = match find_script() {
            Some(s) => s,
            None => {
                self.log.push_str(
                    "FEHLER: counsel/counsel.mjs nicht gefunden. \
                     Starte die GUI aus dem Repo-Verzeichnis oder setze COUNSEL_SCRIPT.\n",
                );
                return;
            }
        };

        let (tx, rx) = channel::<Msg>();
        self.rx = Some(rx);
        self.log.clear();
        self.result.clear();
        self.running = true;

        let mut cmd = Command::new("node");
        cmd.arg(&script);
        cmd.args(["--rounds", &self.rounds.to_string()]);
        if self.panel == Panel::Volles {
            cmd.args(["--roles", "design,frontend,backend"]);
        }
        cmd.arg(self.topic.trim());
        cmd.stdout(Stdio::piped()).stderr(Stdio::piped()).stdin(Stdio::null());

        let mut child = match cmd.spawn() {
            Ok(c) => c,
            Err(e) => {
                self.running = false;
                self.log.push_str(&format!("FEHLER beim Start von node: {e}\n"));
                return;
            }
        };

        let stderr = child.stderr.take().expect("stderr piped");
        let stdout = child.stdout.take().expect("stdout piped");
        *self.child.lock().unwrap() = Some(child);

        // Diskussionsverlauf (stderr) zeilenweise streamen
        let tx_log: Sender<Msg> = tx.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(stderr).lines() {
                match line {
                    Ok(l) => {
                        if tx_log.send(Msg::Log(l)).is_err() {
                            break;
                        }
                    }
                    Err(_) => break,
                }
            }
        });

        // Ergebnis (stdout) sammeln und auf Prozessende warten
        let child_ref = Arc::clone(&self.child);
        std::thread::spawn(move || {
            let mut out = String::new();
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                out.push_str(&line);
                out.push('\n');
            }
            let _ = tx.send(Msg::Result(out.trim().to_string()));
            let status = child_ref.lock().unwrap().take().and_then(|mut c| c.wait().ok());
            let _ = tx.send(Msg::Done(status.and_then(|s| s.code())));
        });
    }

    fn stop(&mut self) {
        if let Some(mut c) = self.child.lock().unwrap().take() {
            let _ = c.kill();
            let _ = c.wait();
        }
        self.running = false;
        self.log.push_str("\n[abgebrochen]\n");
    }

    fn drain_messages(&mut self) {
        let mut done = false;
        if let Some(rx) = &self.rx {
            while let Ok(msg) = rx.try_recv() {
                match msg {
                    Msg::Log(l) => {
                        self.log.push_str(&l);
                        self.log.push('\n');
                    }
                    Msg::Result(r) => self.result = r,
                    Msg::Done(code) => {
                        done = true;
                        if let Some(c) = code {
                            if c != 0 {
                                self.log.push_str(&format!("\n[Prozess beendet mit Exit-Code {c}]\n"));
                            }
                        }
                    }
                }
            }
        }
        if done {
            self.running = false;
            self.rx = None;
        }
    }
}

impl eframe::App for CounselApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        self.drain_messages();
        if self.running {
            ctx.request_repaint_after(std::time::Duration::from_millis(150));
        }

        // Eingabe unten: Frage + Start/Stop
        egui::TopBottomPanel::bottom("input").resizable(false).show(ctx, |ui| {
            ui.add_space(6.0);
            ui.horizontal(|ui| {
                ui.label("Panel:");
                ui.selectable_value(&mut self.panel, Panel::Architekten, "2 Architekten");
                ui.selectable_value(&mut self.panel, Panel::Volles, "Design + Frontend + Backend (6)");
                ui.separator();
                ui.label("Runden:");
                ui.add(egui::DragValue::new(&mut self.rounds).range(1..=5));
            });
            ui.add_space(4.0);
            ui.horizontal(|ui| {
                let input = egui::TextEdit::singleline(&mut self.topic)
                    .hint_text("Deine Frage an den Counsel …")
                    .desired_width(ui.available_width() - 110.0);
                let resp = ui.add_enabled(!self.running, input);
                let submitted =
                    resp.lost_focus() && ui.input(|i| i.key_pressed(egui::Key::Enter));
                if self.running {
                    if ui.button("⏹ Stopp").clicked() {
                        self.stop();
                    }
                } else {
                    let can_start = !self.topic.trim().is_empty();
                    if ui.add_enabled(can_start, egui::Button::new("▶ Start")).clicked()
                        || (submitted && can_start)
                    {
                        self.start();
                    }
                }
            });
            ui.add_space(6.0);
        });

        // Ergebnis rechts
        egui::SidePanel::right("result")
            .resizable(true)
            .default_width(400.0)
            .show(ctx, |ui| {
                ui.horizontal(|ui| {
                    ui.heading("Ergebnis");
                    if !self.result.is_empty() && ui.small_button("📋 Kopieren").clicked() {
                        ctx.copy_text(self.result.clone());
                    }
                });
                ui.separator();
                egui::ScrollArea::vertical().auto_shrink(false).show(ui, |ui| {
                    if self.result.is_empty() {
                        ui.weak(if self.running {
                            "Der Counsel diskutiert noch …"
                        } else {
                            "Hier erscheint das Entscheidungsprotokoll."
                        });
                    } else {
                        ui.add(
                            egui::TextEdit::multiline(&mut self.result.as_str())
                                .desired_width(f32::INFINITY)
                                .font(egui::TextStyle::Body),
                        );
                    }
                });
            });

        // Mitlese-Feld: Diskussionsverlauf
        egui::CentralPanel::default().show(ctx, |ui| {
            ui.horizontal(|ui| {
                ui.heading("Diskussion");
                if self.running {
                    ui.spinner();
                }
            });
            ui.separator();
            egui::ScrollArea::vertical()
                .auto_shrink(false)
                .stick_to_bottom(true)
                .show(ui, |ui| {
                    if self.log.is_empty() {
                        ui.weak("Hier liest du live mit, sobald der Counsel startet.");
                    } else {
                        ui.add(
                            egui::TextEdit::multiline(&mut self.log.as_str())
                                .desired_width(f32::INFINITY)
                                .font(egui::TextStyle::Monospace),
                        );
                    }
                });
        });
    }
}
