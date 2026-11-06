(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const ROLE_EMOJI = { loup: "🐺", sorciere: "🧙‍♀️", villageois: "🧑‍🌾" };
  let state = null, clockOffset = 0, pendingId = null, ws = null, retry = 0;

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  // ---- WebSocket --------------------------------------------------------
  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws/game/`);
    ws.onopen = () => { retry = 0; $("conn").classList.add("hidden"); };
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "state") {
        if (msg.server_time) clockOffset = msg.server_time - Date.now() / 1000;
        state = msg.payload;
        render();
      } else if (msg.type === "error") {
        showError(msg.message);
      }
    };
    ws.onclose = (ev) => {
      if (ev.code === 4403) { location.href = "/"; return; }
      $("conn").classList.remove("hidden");
      setTimeout(connect, Math.min(1000 * 2 ** retry++, 8000));
    };
  }

  function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  }

  // ---- Rendu ------------------------------------------------------------
  function renderLog(container, entries, me) {
    const key = entries.length + "|" + (entries.length ? entries[entries.length - 1].text : "");
    if (container.dataset.key === key) return;
    container.dataset.key = key;
    const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 60;
    container.replaceChildren();
    for (const e of entries) {
      if (e.author === null) {
        container.append(el("p", "narration", e.text));
      } else {
        const mine = e.author_id === me.id;
        const row = el("p", "rounded-lg px-3 py-1.5 " + (mine ? "msg-mine" : "inset"));
        row.append(el("span", "font-display text-ember", e.author + " : "), document.createTextNode(e.text));
        container.append(row);
      }
    }
    if (atBottom || container.dataset.init !== "1") container.scrollTop = container.scrollHeight;
    container.dataset.init = "1";
  }

  function renderPlayers(s) {
    const ul = $("players");
    ul.replaceChildren();
    for (const p of s.players) {
      const li = el("li", "flex items-center gap-2 rounded-lg px-2 py-1 " +
        (p.alive ? "inset" : "bg-black/50 opacity-60"));
      const badge = el("span", "text-xl", p.alive ? (p.role ? ROLE_EMOJI[p.role] : "🙂") : "💀");
      const info = el("div", "min-w-0 leading-tight");
      info.append(el("div", "truncate font-semibold " + (p.alive ? "" : "line-through"), p.pseudo + (p.is_me ? " (toi)" : " (IA)")));
      info.append(el("div", "text-xs text-parchment/70", p.role_label || (p.alive ? "En vie" : "")));
      li.append(badge, info);
      if (s.thinking === p.pseudo) li.classList.add("pulse-eye");
      ul.append(li);
    }
  }

  function renderStatus(s) {
    const status = $("status");
    let text = "";
    if (s.phase === "terminee") text = "La partie est terminée.";
    else if (!s.me.alive) text = "Tu es mort : tu observes la fin de la partie.";
    else if (s.thinking) text = `${s.thinking} réfléchit…`;
    else if (s.is_night) text = ""; // l'icône du dernier évènement dit déjà que la nuit tombe
    else text = "En attente des autres joueurs…";
    status.textContent = text;
  }

  function renderForm(p) {
    const form = $("form");
    // Le panneau d'action n'existe que lorsqu'on attend quelque chose du joueur ;
    // sinon le statut (« X réfléchit… ») s'affiche sous le dernier évènement.
    $("action").classList.toggle("hidden", !p);
    $("status").classList.toggle("hidden", !!p);
    if (!p) { pendingId = null; form.classList.add("hidden"); return; }
    form.classList.remove("hidden");
    if (pendingId === p.id) return; // formulaire déjà construit : on ne touche pas à la saisie
    pendingId = p.id;
    $("error").classList.add("hidden");
    $("prompt").textContent = p.prompt;
    const msg = $("message");
    msg.value = "";
    msg.classList.toggle("hidden", !p.allow_message);
    msg.placeholder = p.kind === "debate" ? "Ton intervention devant le village…" : "Ton message aux autres loups (facultatif)…";

    let selected = null;
    const targets = $("targets");
    targets.replaceChildren();
    const buttons = $("buttons");
    buttons.replaceChildren();
    const mkBtn = (label, cls, onClick, type = "button") => {
      const b = el("button", "btn " + cls, label); b.type = type; b.onclick = onClick; buttons.append(b); return b;
    };
    const answer = (extra) => send({ type: "answer", request_id: p.id, message: msg.value, ...extra });

    if (p.targets.length) {
      const confirm = () => answer({ target: selected, accept: true });
      for (const t of p.targets) {
        const b = el("button", "btn btn-ghost", t.pseudo);
        b.type = "button";
        b.onclick = () => {
          selected = t.id;
          for (const c of targets.children) c.classList.remove("!bg-blood", "!border-ember");
          b.classList.add("!bg-blood", "!border-ember");
          ok.disabled = false;
        };
        targets.append(b);
      }
      var ok = mkBtn(p.kind === "vote" ? "Voter" : p.kind === "wolf_kill" ? "Dévorer" : "Empoisonner", "btn-primary", confirm);
      ok.disabled = true;
      if (p.kind === "wolf_kill") mkBtn("Discuter sans voter", "btn-ghost", () => msg.value.trim() ? answer({}) : showError("Écris un message pour discuter."));
      if (p.kind === "witch_poison") mkBtn("Ne rien faire", "btn-ghost", () => answer({ accept: false }));
    } else if (p.kind === "witch_heal") {
      const yes = mkBtn("Sauver la victime", "btn-primary", () => answer({ accept: true }));
      yes.disabled = !p.can_accept;
      mkBtn("Laisser faire", "btn-ghost", () => answer({ accept: false }));
      if (!p.can_accept) $("prompt").textContent += " (Tu ne peux pas te soigner toi-même.)";
    } else if (p.kind === "debate") {
      mkBtn("Parler", "btn-primary", () => msg.value.trim() ? answer({}) : showError("Écris quelque chose, ou passe ton tour."));
      mkBtn("Passer", "btn-ghost", () => answer({ message: "" }));
      setTimeout(() => msg.focus(), 0);
    }
  }

  function showError(text) {
    const e = $("error");
    e.textContent = text;
    e.classList.remove("hidden");
  }

  // Dernier évènement de narration, affiché sous « Le village » : icône + légende.
  function renderLastEvent(log) {
    const last = [...log].reverse().find((e) => e.author === null);
    if (!last) { $("last-event-icon").textContent = ""; $("last-event-text").textContent = ""; return; }
    const m = last.text.match(/^(\p{Extended_Pictographic}\uFE0F?)\s*(.*)$/u);
    let icon = m ? m[1] : "📜", text = m ? m[2] : last.text;
    if (!m) {
      if (/éliminé/.test(text)) icon = "🗳️";
      else if (/mort/.test(text) && !/Personne/.test(text)) icon = "💀";
      else if (/Personne/.test(text)) icon = "🕊️";
    }
    $("last-event-icon").textContent = icon;
    $("last-event-text").textContent = text;
  }

  function renderAiStats(stats) {
    const chip = $("ai-stats");
    const tokens = stats.total_tokens.toLocaleString("fr-FR");
    chip.textContent = `🤖 ${stats.model || "en attente d'un appel"} · ${tokens} jeton${stats.total_tokens > 1 ? "s" : ""}`;
    chip.title = `Modèle d'IA utilisé · ${stats.calls} appel${stats.calls > 1 ? "s" : ""} · ${tokens} jetons consommés par la partie`;
  }

  function render() {
    const s = state;
    if (!s || !s.active) { location.href = "/"; return; }
    renderAiStats(s.ai_stats);
    renderLastEvent(s.main_log);
    $("scene").classList.toggle("night", s.is_night);
    $("scene").classList.toggle("day", !s.is_night);
    $("ai-down").classList.toggle("hidden", !s.ai_down);
    $("ai-down").classList.toggle("flex", s.ai_down);
    $("phase").textContent = (s.is_night ? "🌙 " : "☀️ ") + s.phase_label + " · tour " + s.cycle;
    $("role").textContent = (ROLE_EMOJI[s.me.role] || "") + " Tu es " + s.me.role_label;
    renderPlayers(s);
    renderLog($("main-log"), s.main_log, s.me);

    const wolfRoom = $("wolf-room");
    if (s.wolf_log !== null) {
      wolfRoom.classList.remove("hidden"); wolfRoom.classList.add("flex");
      $("wolf-mates").textContent = s.wolf_mates && s.wolf_mates.length ? "— avec " + s.wolf_mates.join(", ") : "";
      renderLog($("wolf-log"), s.wolf_log, s.me);
    }

    const witch = $("witch");
    if (s.me.role === "sorciere") {
      witch.classList.remove("hidden");
      witch.textContent = `🧪 Vie : ${s.me.heal_left ? "disponible" : "utilisée"} · ☠️ Poison : ${s.me.poison_left ? "disponible" : "utilisé"}`;
    }

    renderStatus(s);
    renderForm(s.pending);

    const end = $("end");
    if (s.phase === "terminee" && s.winner) {
      end.classList.remove("hidden"); end.classList.add("flex");
      $("end-emoji").textContent = s.i_won ? "🏆" : "💀";
      $("end-title").textContent = s.winner_label + " gagnent !";
      $("end-text").textContent = s.i_won ? "Ton camp l'emporte. Bravo !" : "Ton camp a perdu cette fois.";
    }
  }

  // ---- Décomptes (délai de l'humain + durée du débat) -----------------------
  setInterval(() => {
    if (!state) return;
    const now = Date.now() / 1000 + clockOffset;
    const p = state.pending;
    if (p) {
      const left = Math.max(0, p.deadline - now);
      $("bar").style.width = Math.min(100, (left / (state.human_timeout || 75)) * 100) + "%";
      $("timer").textContent = `Temps restant : ${Math.ceil(left)} s — passé ce délai, une action par défaut sera choisie pour toi.`;
    }
    const dt = $("debate-timer");
    if (state.debate_deadline) {
      const left = Math.max(0, Math.ceil(state.debate_deadline - now));
      dt.textContent = `Débat ${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}`;
      dt.classList.remove("hidden");
    } else dt.classList.add("hidden");
  }, 250);

  connect();
})();
