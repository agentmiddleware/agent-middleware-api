/* ==========================================================================
   THE HUMAN WAITING ROOM — an arcade for the party that is not doing the work.
   ==========================================================================

   This product authorizes, meters, and receipts actions taken by agents. The
   human's job during that loop is to wait. This file is what the waiting looks
   like: the page fades out, a cabinet-select screen fades in, and four
   deliberately generic cabinets keep the human occupied while the agents do
   the actual work.

   Contracts this file lives inside:

   - CSP is script-src 'self' with no 'unsafe-inline', so this is a file, not
     an inline <script>, and it injects no <style> or event-handler attributes.
   - The launcher button ships hidden and is revealed only once this script
     runs, so a visitor without JavaScript never sees a control that does
     nothing.
   - Opening the arcade sets display:none on the particle canvas. /wave.js
     already watches that canvas with an IntersectionObserver and unschedules
     its frame loop when it leaves view, so the renderer pauses on open and
     resumes on close without either file knowing about the other.
   - Every cabinet is generic by construction. No arcade trademark, character,
     or company name appears here, and a contract test enforces that.
   - Game-over "receipts" are theatre and say so in their own body text. This
     site's entire pitch is that a real receipt is verifiable, so a fake one
     must be unmistakable at a glance.

   Debug/automation handle: window.__amwArcade — see the bottom of the file.
   ========================================================================== */

(function () {
  "use strict";

  var doc = document;
  var root = doc.documentElement;

  /* ---- logical screen ----------------------------------------------------

     Everything is authored against a fixed 320x240 field and drawn through an
     integer scale, so sprites stay blocky while text is rasterised at the
     scaled size and stays legible. */
  var W = 320;
  var H = 240;
  var STEP = 1 / 60; // fixed simulation timestep
  var MAX_CATCHUP = 5; // never simulate more than this many steps per frame

  var PALETTE = {
    bg: "#05040f",
    grid: "#2e2663",
    ink: "#eceafd",
    dim: "#a49ddb",
    brass: "#ffc233",
    bright: "#ffe066",
    verify: "#4cf08a",
    danger: "#ff6b5e"
  };

  var BOOT_LINES = [
    "AGENT MIDDLEWARE API — HUMAN WAITING ROOM v1.0",
    "PURPOSE: OCCUPY THE PARTY NOT DOING THE WORK",
    "PROVISIONING ENTERTAINMENT PERMIT ....... GRANTED",
    "  SCOPE: fun:play   TTL: UNTIL YOU GET BORED",
    "METERING JOY AT 0.00 CREDITS PER SMILE",
    "AUDIT: human.entered_waiting_room  ACTOR: YOU",
    "AUDIO ........................ DENIED BY DEFAULT",
    "AGENTS ARE WORKING. YOU ARE NOT ON THE CRITICAL PATH.",
    "FOUR CABINETS READY. NONE OF THEM ARE LOAD-BEARING."
  ];

  /* Rotating status ticker: the whole conceit is that real work is happening
     somewhere else, at a pace nobody will explain to you. */
  var AGENT_STATUS = [
    "AGENT-7 · NEGOTIATING A PERMIT WITH ITSELF",
    "AGENT-3 · METERING SOMETHING. IT WILL NOT SAY WHAT.",
    "AGENT-9 · WRITING A RECEIPT LONGER THAN THE ACTION",
    "AGENT-4 · ARGUING WITH POLICY. POLICY IS WINNING.",
    "AGENT-1 · IDLE, BUT BILLING FOR READINESS",
    "AGENT-6 · RE-READING THE AUDIT LOG FOR PLEASURE",
    "AGENT-2 · WAITING ON AGENT-5",
    "AGENT-5 · WAITING ON AGENT-2",
    "AGENT-8 · ESTIMATED COMPLETION: SOON, PROBABLY, SEE RECEIPT"
  ];

  var PAUSE_LINES = [
    "PAUSED — HUMAN IDLE.",
    "AGENTS UNAFFECTED.",
    "PRESS P TO RESUME BEING BUSY."
  ];

  /* ---- small utilities --------------------------------------------------- */

  function el(tag, className, text) {
    var node = doc.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function clamp(value, low, high) {
    return value < low ? low : value > high ? high : value;
  }

  /* Seeded generator: a deterministic arcade is a testable arcade. Every run
     starts from a fixed seed unless a caller reseeds it. */
  function makeRandom(seed) {
    var state = seed >>> 0 || 1;
    return function () {
      state = (state * 1664525 + 1013904223) >>> 0;
      return state / 4294967296;
    };
  }

  function prefersStaticMotion() {
    if (root.getAttribute("data-a11y-motion") === "reduce") return true;
    return (
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  }

  function contrastHigh() {
    return root.getAttribute("data-a11y-contrast") === "high";
  }

  /* ---- fake receipts -----------------------------------------------------

     Deliberately unmistakable. The real artifact lives at /proof/ and is
     verifiable offline; this one announces that it is not. */
  function receiptId(random) {
    var alphabet = "0123456789abcdef";
    var out = "";
    for (var i = 0; i < 12; i += 1) {
      out += alphabet.charAt(Math.floor(random() * alphabet.length));
    }
    return "rcpt_sim_" + out;
  }

  var RECEIPT_VERDICTS = [
    "ALLOWED — NOBODY CHECKED",
    "ALLOWED — POLICY WAS ASLEEP",
    "ALLOWED — RETROACTIVELY, WHICH IS THE BEST KIND",
    "ALLOWED — THE AGENTS VOTED AND YOU LOST"
  ];

  function buildReceipt(cabinet, score, random) {
    var wrap = el("div", "arcade-receipt");
    wrap.setAttribute("role", "group");
    wrap.setAttribute("aria-label", "Simulated receipt");

    wrap.appendChild(el("p", "arcade-receipt-stamp", "SIMULATED · NOT A REAL RECEIPT"));

    var rows = [
      ["receipt_id", receiptId(random)],
      ["action", "arcade.play"],
      ["tool", "cabinet/" + cabinet.id],
      ["units", score + " RECEIPTS SCORED"],
      ["amount", "0.00 CREDITS — HUMAN LABOR IS UNBILLABLE"],
      ["verdict", RECEIPT_VERDICTS[Math.floor(random() * RECEIPT_VERDICTS.length)]],
      ["signature", "—— UNSIGNED · UNVERIFIABLE · THEATRE ——"]
    ];

    var list = el("dl", "arcade-receipt-rows");
    rows.forEach(function (row) {
      list.appendChild(el("dt", null, row[0]));
      list.appendChild(el("dd", null, row[1]));
    });
    wrap.appendChild(list);

    var note = el("p", "arcade-receipt-note");
    note.appendChild(
      doc.createTextNode("This artifact is a prop. Real receipts are signed and verify offline — ")
    );
    var link = el("a", null, "see one at /proof/");
    link.href = "/proof/";
    note.appendChild(link);
    note.appendChild(doc.createTextNode("."));
    wrap.appendChild(note);

    return wrap;
  }

  /* ======================================================================
     CABINETS

     Each cabinet is a factory returning an object with reset/update/draw and
     the fields the shell reads: score, lives, over, hud().
     ====================================================================== */

  /* ---- 1. SCOPE CREEP ----------------------------------------------------

     A descending grid of permission scopes marches toward PRODUCTION. You
     hold a deny key. Every scope you deny makes the survivors faster, and a
     consultant occasionally drifts past to add one more requirement, which is
     the joke and also the documented behaviour. */
  function cabinetScopeCreep(random) {
    // Labels are kept to eight characters and the columns spaced wider than
    // the widest of them: at 8px monospace a nine-character scope overruns its
    // neighbour and the grid reads as mush.
    var SCOPES = [
      "*:*", "admin:*", "db:drop", "bill:*", "iam:*",
      "prod:ssh", "keys:rw", "audit:w", "refund:*", "fs:rm-rf"
    ];
    var COLS = 6;
    var ROWS = 4;
    var COL_STEP = 52;
    var COL_ORIGIN = 34;

    var game = { id: "scope-creep", score: 0, lives: 3, over: false };
    var scopes, player, shots, bombs, dir, speed, wave, consultant, cooldown, message, messageAge;

    function spawnWave() {
      scopes = [];
      for (var r = 0; r < ROWS; r += 1) {
        for (var c = 0; c < COLS; c += 1) {
          scopes.push({
            x: COL_ORIGIN + c * COL_STEP,
            y: 34 + r * 22,
            label: SCOPES[(r * COLS + c) % SCOPES.length],
            alive: true,
            value: (ROWS - r) * 10
          });
        }
      }
      dir = 1;
      speed = 10 + wave * 3;
      bombs = [];
    }

    game.reset = function () {
      game.score = 0;
      game.lives = 3;
      game.over = false;
      wave = 1;
      shots = [];
      consultant = null;
      cooldown = 0;
      message = "";
      messageAge = 0;
      player = { x: W / 2, w: 22 };
      spawnWave();
    };

    function say(text) {
      message = text;
      messageAge = 0;
    }

    function liveScopes() {
      return scopes.filter(function (s) {
        return s.alive;
      });
    }

    game.update = function (dt, input) {
      if (game.over) return;

      if (input.left) player.x -= 130 * dt;
      if (input.right) player.x += 130 * dt;
      if (input.pointerX != null) player.x = input.pointerX;
      player.x = clamp(player.x, player.w / 2, W - player.w / 2);

      cooldown -= dt;
      if (input.fire && cooldown <= 0) {
        shots.push({ x: player.x, y: H - 26 });
        cooldown = 0.28;
      }

      shots.forEach(function (shot) {
        shot.y -= 190 * dt;
      });
      shots = shots.filter(function (shot) {
        return shot.y > -6;
      });

      var living = liveScopes();
      if (!living.length) {
        wave += 1;
        say("WAVE CLEARED. REQUIREMENTS GATHERED ANYWAY.");
        spawnWave();
        living = liveScopes();
      }

      // Classic side-step march: drift until the block touches an edge, then
      // drop a row and reverse. Speed scales with how few are left, so the
      // last scope is always the fastest — as in life.
      var pace = speed * (1 + (ROWS * COLS - living.length) / (ROWS * COLS) * 2.2);
      var minX = W;
      var maxX = 0;
      living.forEach(function (s) {
        s.x += dir * pace * dt;
        if (s.x < minX) minX = s.x;
        if (s.x > maxX) maxX = s.x;
      });
      // Labels are centred, so the turn margin has to clear half a label or
      // the widest scopes clip against the bezel.
      if (maxX > W - 24 || minX < 24) {
        dir *= -1;
        living.forEach(function (s) {
          s.y += 10;
          s.x = clamp(s.x, 24, W - 24);
        });
      }

      // Escalation bombs.
      if (random() < dt * (0.8 + wave * 0.25) && living.length) {
        var shooter = living[Math.floor(random() * living.length)];
        bombs.push({ x: shooter.x, y: shooter.y + 6 });
      }
      bombs.forEach(function (bomb) {
        bomb.y += 96 * dt;
      });

      // The consultant: pure overhead, worth points, adds one scope on death.
      if (!consultant && random() < dt * 0.22) {
        consultant = { x: -16, y: 20, dir: 1 };
      }
      if (consultant) {
        consultant.x += 62 * dt * consultant.dir;
        if (consultant.x > W + 16) consultant = null;
      }

      // Collisions: shots vs scopes.
      shots.forEach(function (shot) {
        living.forEach(function (s) {
          if (
            s.alive &&
            Math.abs(shot.x - s.x) < 15 &&
            Math.abs(shot.y - s.y) < 9
          ) {
            s.alive = false;
            shot.y = -99;
            game.score += s.value;
          }
        });
        if (
          consultant &&
          Math.abs(shot.x - consultant.x) < 16 &&
          Math.abs(shot.y - consultant.y) < 9
        ) {
          game.score += 150;
          shot.y = -99;
          consultant = null;
          var extra = liveScopes()[0];
          if (extra) {
            scopes.push({
              x: clamp(extra.x + 20, 24, W - 24),
              y: extra.y,
              label: SCOPES[Math.floor(random() * SCOPES.length)],
              alive: true,
              value: 10
            });
          }
          say("CONSULTANT DENIED. ONE MORE REQUIREMENT ADDED.");
        }
      });
      shots = shots.filter(function (shot) {
        return shot.y > -6;
      });

      // Bombs vs player.
      bombs.forEach(function (bomb) {
        if (
          bomb.y > H - 30 &&
          bomb.y < H - 14 &&
          Math.abs(bomb.x - player.x) < player.w / 2 + 3
        ) {
          bomb.y = H + 99;
          game.lives -= 1;
          say("PRIVILEGE ESCALATED THROUGH YOUR CHEST.");
          if (game.lives <= 0) game.over = true;
        }
      });
      bombs = bombs.filter(function (bomb) {
        return bomb.y < H + 8;
      });

      // Anything reaching production ends the run outright.
      var breached = liveScopes().some(function (s) {
        return s.y > H - 40;
      });
      if (breached) {
        game.lives = 0;
        game.over = true;
        say("SCOPE REACHED PRODUCTION.");
      }

      messageAge += dt;
      if (messageAge > 2.6) message = "";
    };

    game.draw = function (ctx, ink) {
      ctx.fillStyle = ink.danger;
      ctx.fillRect(0, H - 34, W, 1);
      ctx.fillStyle = ink.dim;
      ctx.font = '7px "IBM Plex Mono", monospace';
      ctx.fillText("PRODUCTION", 4, H - 37);

      ctx.font = '8px "IBM Plex Mono", monospace';
      liveScopes().forEach(function (s) {
        ctx.fillStyle = s.value > 30 ? ink.danger : ink.brass;
        ctx.textAlign = "center";
        ctx.fillText(s.label, s.x, s.y);
      });

      if (consultant) {
        ctx.fillStyle = ink.verify;
        ctx.textAlign = "center";
        ctx.fillText("[CONSULTANT]", consultant.x, consultant.y);
      }

      ctx.textAlign = "left";
      ctx.fillStyle = ink.bright;
      shots.forEach(function (shot) {
        ctx.fillRect(shot.x - 1, shot.y - 5, 2, 6);
      });
      ctx.fillStyle = ink.danger;
      bombs.forEach(function (bomb) {
        ctx.fillRect(bomb.x - 1, bomb.y, 2, 5);
      });

      ctx.fillStyle = ink.ink;
      ctx.fillRect(player.x - player.w / 2, H - 24, player.w, 6);
      ctx.fillRect(player.x - 2, H - 29, 4, 5);

      if (message) {
        ctx.fillStyle = ink.dim;
        ctx.font = '7px "IBM Plex Mono", monospace';
        ctx.textAlign = "center";
        ctx.fillText(message, W / 2, H - 6);
        ctx.textAlign = "left";
      }
    };

    game.hud = function () {
      return "WAVE " + wave;
    };

    return game;
  }

  /* ---- 2. TOKEN BUCKET ---------------------------------------------------

     Paddle-and-ball against a bucket of tokens. The bucket refills on a timer,
     so the board can never be permanently cleared: you are not playing to win,
     you are playing to stay under the limit, forever. */
  function cabinetTokenBucket(random) {
    var COLS = 10;
    var game = { id: "token-bucket", score: 0, lives: 3, over: false };
    var bricks, paddle, ball, refillTimer, refills, message, messageAge, launched;

    function makeRow(y) {
      var row = [];
      for (var c = 0; c < COLS; c += 1) {
        row.push({ x: 8 + c * 30, y: y, w: 26, h: 8, alive: true });
      }
      return row;
    }

    function resetBall() {
      ball = { x: W / 2, y: H - 46, vx: 0, vy: 0, r: 2 };
      launched = false;
    }

    game.reset = function () {
      game.score = 0;
      game.lives = 3;
      game.over = false;
      bricks = [];
      for (var r = 0; r < 4; r += 1) {
        bricks = bricks.concat(makeRow(30 + r * 12));
      }
      paddle = { x: W / 2, w: 42 };
      refillTimer = 9;
      refills = 0;
      message = "";
      messageAge = 0;
      resetBall();
    };

    function say(text) {
      message = text;
      messageAge = 0;
    }

    game.update = function (dt, input) {
      if (game.over) return;

      if (input.left) paddle.x -= 165 * dt;
      if (input.right) paddle.x += 165 * dt;
      if (input.pointerX != null) paddle.x = input.pointerX;
      paddle.x = clamp(paddle.x, paddle.w / 2, W - paddle.w / 2);

      if (!launched) {
        ball.x = paddle.x;
        ball.y = H - 26;
        if (input.fire) {
          launched = true;
          ball.vx = (random() < 0.5 ? -1 : 1) * 70;
          ball.vy = -128;
        }
        return;
      }

      ball.x += ball.vx * dt;
      ball.y += ball.vy * dt;

      if (ball.x < 3) {
        ball.x = 3;
        ball.vx = Math.abs(ball.vx);
      }
      if (ball.x > W - 3) {
        ball.x = W - 3;
        ball.vx = -Math.abs(ball.vx);
      }
      if (ball.y < 20) {
        ball.y = 20;
        ball.vy = Math.abs(ball.vy);
      }

      // Paddle: contact point steers, so the rate limiter has some say.
      if (
        ball.vy > 0 &&
        ball.y > H - 24 &&
        ball.y < H - 16 &&
        Math.abs(ball.x - paddle.x) < paddle.w / 2 + 2
      ) {
        ball.y = H - 24;
        ball.vy = -Math.abs(ball.vy);
        ball.vx = clamp((ball.x - paddle.x) / (paddle.w / 2), -1, 1) * 130;
      }

      // One bounce per frame no matter how many tokens the ball overlaps —
      // flipping once per brick can cancel itself out and tunnel the ball.
      var bounced = false;
      bricks.forEach(function (brick) {
        if (!brick.alive) return;
        if (
          ball.x > brick.x - 2 &&
          ball.x < brick.x + brick.w + 2 &&
          ball.y > brick.y - 2 &&
          ball.y < brick.y + brick.h + 2
        ) {
          brick.alive = false;
          game.score += 15;
          bounced = true;
        }
      });
      if (bounced) ball.vy *= -1;

      if (ball.y > H - 6) {
        game.lives -= 1;
        say("REQUEST DROPPED. 429.");
        resetBall();
        if (game.lives <= 0) game.over = true;
        return;
      }

      // The refill. The bucket is never empty for long, which is the entire
      // point of a bucket.
      refillTimer -= dt;
      if (refillTimer <= 0) {
        refills += 1;
        refillTimer = Math.max(4.5, 9 - refills * 0.6);
        bricks.forEach(function (brick) {
          brick.y += 12;
        });
        bricks = bricks.concat(makeRow(30));
        say("BUCKET REFILLED. IT ALWAYS REFILLS.");
        var flooded = bricks.some(function (brick) {
          return brick.alive && brick.y > H - 40;
        });
        if (flooded) {
          game.over = true;
          say("BUCKET OVERFLOWED INTO PRODUCTION.");
        }
      }

      messageAge += dt;
      if (messageAge > 2.4) message = "";
    };

    game.draw = function (ctx, ink) {
      bricks.forEach(function (brick) {
        if (!brick.alive) return;
        ctx.fillStyle = brick.y > H - 70 ? ink.danger : ink.brass;
        ctx.fillRect(brick.x, brick.y, brick.w, brick.h);
        ctx.fillStyle = ink.bg;
        ctx.font = '6px "IBM Plex Mono", monospace';
        ctx.textAlign = "center";
        ctx.fillText("TKN", brick.x + brick.w / 2, brick.y + 6);
      });

      ctx.textAlign = "left";
      ctx.fillStyle = ink.ink;
      ctx.fillRect(paddle.x - paddle.w / 2, H - 20, paddle.w, 5);
      ctx.fillRect(ball.x - ball.r, ball.y - ball.r, ball.r * 2, ball.r * 2);

      ctx.fillStyle = ink.dim;
      ctx.font = '7px "IBM Plex Mono", monospace';
      ctx.textAlign = "center";
      if (!launched) {
        ctx.fillText("SPACE TO ISSUE A REQUEST", W / 2, H - 32);
      } else if (message) {
        ctx.fillText(message, W / 2, H - 6);
      }
      ctx.textAlign = "left";
    };

    game.hud = function () {
      return "REFILL " + Math.max(0, Math.ceil(refillTimer)) + "s";
    };

    return game;
  }

  /* ---- 3. APPEND-ONLY ----------------------------------------------------

     A ledger that grows and may never cross itself, because crossing itself
     would be rewriting history. Vacuum requests appear; they are refused, and
     refusing them still makes the ledger longer. */
  function cabinetAppendOnly(random) {
    var CELL = 8;
    var COLS = Math.floor(W / CELL);
    // Leave a clear band under the grid: the legend is drawn at the bottom of
    // the screen and a full-height field would run underneath it.
    var ROWS = Math.floor((H - 36) / CELL);
    var game = { id: "append-only", score: 0, lives: 1, over: false };
    var body, dir, nextDir, entry, vacuum, timer, rate, message, messageAge;

    function placeCell(avoid) {
      for (var attempt = 0; attempt < 200; attempt += 1) {
        var cell = {
          x: Math.floor(random() * COLS),
          y: Math.floor(random() * ROWS)
        };
        var clash = avoid.some(function (part) {
          return part.x === cell.x && part.y === cell.y;
        });
        if (!clash) return cell;
      }
      return { x: 0, y: 0 };
    }

    game.reset = function () {
      game.score = 0;
      game.lives = 1;
      game.over = false;
      body = [
        { x: 6, y: Math.floor(ROWS / 2) },
        { x: 5, y: Math.floor(ROWS / 2) },
        { x: 4, y: Math.floor(ROWS / 2) }
      ];
      dir = { x: 1, y: 0 };
      nextDir = { x: 1, y: 0 };
      entry = placeCell(body);
      vacuum = null;
      timer = 0;
      rate = 0.14;
      message = "";
      messageAge = 0;
    };

    function say(text) {
      message = text;
      messageAge = 0;
    }

    game.update = function (dt, input) {
      if (game.over) return;

      // Queue the turn rather than applying it mid-cell: a 180 into your own
      // neck should be refused, not fatal.
      if (input.left && dir.x === 0) nextDir = { x: -1, y: 0 };
      if (input.right && dir.x === 0) nextDir = { x: 1, y: 0 };
      if (input.up && dir.y === 0) nextDir = { x: 0, y: -1 };
      if (input.down && dir.y === 0) nextDir = { x: 0, y: 1 };

      messageAge += dt;
      if (messageAge > 2.4) message = "";

      timer += dt;
      if (timer < rate) return;
      timer = 0;
      dir = nextDir;

      var head = {
        x: body[0].x + dir.x,
        y: body[0].y + dir.y
      };

      if (head.x < 0 || head.y < 0 || head.x >= COLS || head.y >= ROWS) {
        game.over = true;
        say("LEDGER LEFT THE JURISDICTION.");
        return;
      }

      var selfHit = body.some(function (part) {
        return part.x === head.x && part.y === head.y;
      });
      if (selfHit) {
        game.over = true;
        game.lives = 0;
        say("HISTORY REWRITTEN. THAT IS NOT PERMITTED.");
        return;
      }

      body.unshift(head);

      if (entry && head.x === entry.x && head.y === entry.y) {
        game.score += 25;
        entry = placeCell(body);
        rate = Math.max(0.06, rate - 0.004);
        if (!vacuum && random() < 0.35) vacuum = placeCell(body.concat([entry]));
      } else if (vacuum && head.x === vacuum.x && head.y === vacuum.y) {
        // The refusal is the feature. It also costs you, because refusals are
        // themselves appended.
        vacuum = null;
        game.score += 5;
        say("VACUUM DENIED: THE LEDGER IS APPEND-ONLY.");
        body.push({ x: body[body.length - 1].x, y: body[body.length - 1].y });
      } else {
        body.pop();
      }
    };

    game.draw = function (ctx, ink) {
      ctx.fillStyle = ink.grid;
      for (var gx = 0; gx < COLS; gx += 4) {
        ctx.fillRect(gx * CELL, 20, 1, ROWS * CELL);
      }

      if (entry) {
        ctx.fillStyle = ink.verify;
        ctx.fillRect(entry.x * CELL + 1, 20 + entry.y * CELL + 1, CELL - 2, CELL - 2);
      }
      if (vacuum) {
        ctx.fillStyle = ink.danger;
        ctx.fillRect(vacuum.x * CELL + 1, 20 + vacuum.y * CELL + 1, CELL - 2, CELL - 2);
      }

      body.forEach(function (part, index) {
        ctx.fillStyle = index === 0 ? ink.bright : ink.brass;
        ctx.fillRect(part.x * CELL + 1, 20 + part.y * CELL + 1, CELL - 2, CELL - 2);
      });

      ctx.fillStyle = ink.dim;
      ctx.font = '7px "IBM Plex Mono", monospace';
      ctx.textAlign = "center";
      ctx.fillText(message || "GREEN = ENTRY · RED = VACUUM REQUEST", W / 2, H - 4);
      ctx.textAlign = "left";
    };

    game.hud = function () {
      return "ENTRIES " + body.length;
    };

    return game;
  }

  /* ---- 4. RACE CONDITION -------------------------------------------------

     A rally against an agent that does not blink and occasionally applies
     eventual consistency to its own paddle position. First to seven. */
  function cabinetRaceCondition(random) {
    var TARGET = 7;
    var TAUNTS = [
      "I HAVE ALREADY WON. THE RECEIPT IS PENDING.",
      "YOUR MOVE WAS VALID. IT WAS ALSO LATE.",
      "I READ YOUR PADDLE FROM A STALE REPLICA.",
      "THIS RALLY IS IDEMPOTENT. YOU STILL LOSE ONCE.",
      "I DO NOT BLINK. BLINKING IS UNAUDITED."
    ];

    var game = { id: "race-condition", score: 0, lives: 1, over: false };
    var you, them, ball, theirScore, taunt, tauntAge, teleportTimer;

    function serve(towardYou) {
      ball = {
        x: W / 2,
        y: H / 2,
        vx: towardYou ? -95 : 95,
        vy: (random() * 2 - 1) * 60
      };
    }

    game.reset = function () {
      game.score = 0;
      game.lives = 1;
      game.over = false;
      you = { y: H / 2, h: 34 };
      them = { y: H / 2, h: 34 };
      theirScore = 0;
      taunt = "";
      tauntAge = 0;
      teleportTimer = 3.5;
      serve(random() < 0.5);
    };

    function say(text) {
      taunt = text;
      tauntAge = 0;
    }

    game.update = function (dt, input) {
      if (game.over) return;

      if (input.up) you.y -= 155 * dt;
      if (input.down) you.y += 155 * dt;
      if (input.pointerY != null) you.y = input.pointerY;
      you.y = clamp(you.y, 22 + you.h / 2, H - 8 - you.h / 2);

      // The opponent tracks honestly, then cheats on a timer and files the
      // cheat under a respectable word.
      var chase = ball.y - them.y;
      them.y += clamp(chase, -118 * dt, 118 * dt);
      teleportTimer -= dt;
      if (teleportTimer <= 0 && ball.vx > 0) {
        teleportTimer = 3.2 + random() * 2.4;
        them.y = ball.y;
        say("EVENTUAL CONSISTENCY APPLIED.");
      }
      them.y = clamp(them.y, 22 + them.h / 2, H - 8 - them.h / 2);

      ball.x += ball.vx * dt;
      ball.y += ball.vy * dt;
      if (ball.y < 24) {
        ball.y = 24;
        ball.vy = Math.abs(ball.vy);
      }
      if (ball.y > H - 10) {
        ball.y = H - 10;
        ball.vy = -Math.abs(ball.vy);
      }

      if (ball.vx < 0 && ball.x < 16 && Math.abs(ball.y - you.y) < you.h / 2 + 3) {
        ball.x = 16;
        ball.vx = Math.abs(ball.vx) * 1.05;
        ball.vy += clamp((ball.y - you.y) / (you.h / 2), -1, 1) * 45;
      }
      if (
        ball.vx > 0 &&
        ball.x > W - 16 &&
        Math.abs(ball.y - them.y) < them.h / 2 + 3
      ) {
        ball.x = W - 16;
        ball.vx = -Math.abs(ball.vx) * 1.05;
        ball.vy += clamp((ball.y - them.y) / (them.h / 2), -1, 1) * 45;
      }

      if (ball.x < 4) {
        theirScore += 1;
        say(TAUNTS[Math.floor(random() * TAUNTS.length)]);
        serve(false);
      } else if (ball.x > W - 4) {
        game.score += 1;
        say("CONFLICT RESOLVED IN YOUR FAVOUR. LOGGED RELUCTANTLY.");
        serve(true);
      }

      if (game.score >= TARGET || theirScore >= TARGET) {
        game.over = true;
        game.lives = 0;
        say(
          game.score >= TARGET
            ? "YOU WON. THE AGENTS WILL REVIEW THE FOOTAGE."
            : "AGENT-7 WON. IT WAS ALWAYS GOING TO."
        );
      }

      tauntAge += dt;
      if (tauntAge > 3.2) taunt = "";
    };

    game.draw = function (ctx, ink) {
      ctx.fillStyle = ink.grid;
      for (var y = 24; y < H - 6; y += 10) {
        ctx.fillRect(W / 2 - 1, y, 2, 5);
      }

      ctx.fillStyle = ink.ink;
      ctx.fillRect(8, you.y - you.h / 2, 4, you.h);
      ctx.fillStyle = ink.danger;
      ctx.fillRect(W - 12, them.y - them.h / 2, 4, them.h);

      ctx.fillStyle = ink.bright;
      ctx.fillRect(ball.x - 2, ball.y - 2, 4, 4);

      ctx.font = '9px "IBM Plex Mono", monospace';
      ctx.textAlign = "center";
      ctx.fillStyle = ink.ink;
      ctx.fillText(String(game.score), W / 2 - 26, 32);
      ctx.fillStyle = ink.danger;
      ctx.fillText(String(theirScore), W / 2 + 26, 32);

      if (taunt) {
        ctx.fillStyle = ink.dim;
        ctx.font = '7px "IBM Plex Mono", monospace';
        ctx.fillText(taunt, W / 2, H - 4);
      }
      ctx.textAlign = "left";
    };

    game.hud = function () {
      return "AGENT-7 " + theirScore + " / " + TARGET;
    };

    return game;
  }

  var CABINETS = [
    {
      id: "scope-creep",
      name: "SCOPE CREEP",
      tagline: "Deny the permissions before they reach production.",
      controls: "← → move · SPACE deny",
      make: cabinetScopeCreep
    },
    {
      id: "token-bucket",
      name: "TOKEN BUCKET",
      tagline: "Drain the burst. The bucket refills. Forever.",
      controls: "← → limiter · SPACE serve",
      make: cabinetTokenBucket
    },
    {
      id: "append-only",
      name: "APPEND-ONLY",
      tagline: "The ledger grows. It may never cross itself.",
      controls: "arrows steer the write head",
      make: cabinetAppendOnly
    },
    {
      id: "race-condition",
      name: "RACE CONDITION",
      tagline: "Rally against an agent that does not blink.",
      controls: "↑ ↓ move · first to 7",
      make: cabinetRaceCondition
    }
  ];

  /* ======================================================================
     SHELL: overlay, focus management, boot, select, play loop
     ====================================================================== */

  var launcher = doc.getElementById("arcade-launch");
  if (!launcher || !doc.createElement("canvas").getContext) return;

  var overlay = null;
  var nodes = {};
  var isOpen = false;
  var screen = "closed"; // closed | boot | select | play | over
  var current = null;
  var game = null;
  var random = makeRandom(20260819);
  var rafId = 0;
  var lastNow = 0;
  var accumulator = 0;
  var paused = false;
  var statusIndex = 0;
  var statusTimer = 0;
  var bootIndex = 0;
  var bootTimer = 0;
  var lastFocus = null;
  var announceTimer = 0;

  var swipeFrom = null;
  /* A tap's pointerdown and pointerup can both land inside one animation
     frame, and the simulation only samples input once per fixed step — so a
     raw "true on down, false on up" fire would be invisible to the game about
     as often as not. A tap therefore latches fire for a few steps, and the
     three sources (key held, pointer held, tap pulse) are tracked separately
     so releasing one cannot cancel another. */
  var FIRE_PULSE_STEPS = 4;
  var pointerHeld = false;
  var pointerFireSteps = 0;
  var keyFire = false;

  var input = {
    left: false,
    right: false,
    up: false,
    down: false,
    fire: false,
    pointerX: null,
    pointerY: null
  };

  function inkPalette() {
    if (!contrastHigh()) return PALETTE;
    return {
      bg: "#000000",
      grid: "#4a5468",
      ink: "#ffffff",
      dim: "#d4dae8",
      brass: "#ffc94d",
      bright: "#ffd97a",
      verify: "#5ce0a4",
      danger: "#ff8f76"
    };
  }

  function buildOverlay() {
    overlay = el("div", "arcade-overlay");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-labelledby", "arcade-title");
    overlay.hidden = true;

    var frame = el("div", "arcade-frame");

    var head = el("header", "arcade-head");
    var title = el("h2", "arcade-title", "THE HUMAN WAITING ROOM");
    title.id = "arcade-title";
    head.appendChild(title);
    nodes.status = el("p", "arcade-status", AGENT_STATUS[0]);
    head.appendChild(nodes.status);

    var close = el("button", "arcade-close", "EXIT [ESC]");
    close.type = "button";
    close.addEventListener("click", function () {
      closeArcade();
    });
    head.appendChild(close);
    frame.appendChild(head);

    nodes.boot = el("pre", "arcade-boot");
    nodes.boot.setAttribute("aria-hidden", "true");
    frame.appendChild(nodes.boot);

    nodes.select = el("div", "arcade-select");
    nodes.select.hidden = true;
    var selectHeading = el("p", "arcade-select-heading", "SELECT A CABINET — ALL RUNS ARE FREE AND ALSO METERED");
    nodes.select.appendChild(selectHeading);
    var grid = el("div", "arcade-cabinets");
    CABINETS.forEach(function (cabinet) {
      var button = el("button", "arcade-cabinet");
      button.type = "button";
      button.setAttribute("data-cabinet", cabinet.id);
      button.appendChild(el("span", "arcade-cabinet-name", cabinet.name));
      button.appendChild(el("span", "arcade-cabinet-tag", cabinet.tagline));
      button.appendChild(el("span", "arcade-cabinet-controls", cabinet.controls));
      button.addEventListener("click", function () {
        startGame(cabinet.id);
      });
      grid.appendChild(button);
    });
    nodes.select.appendChild(grid);
    frame.appendChild(nodes.select);

    nodes.stage = el("div", "arcade-stage");
    nodes.stage.hidden = true;

    var hud = el("div", "arcade-hud");
    nodes.hudName = el("span", "arcade-hud-name", "");
    nodes.hudScore = el("span", null, "RECEIPTS 0");
    nodes.hudLives = el("span", null, "RETRIES 3");
    nodes.hudExtra = el("span", null, "");
    hud.appendChild(nodes.hudName);
    hud.appendChild(nodes.hudScore);
    hud.appendChild(nodes.hudLives);
    hud.appendChild(nodes.hudExtra);
    nodes.stage.appendChild(hud);

    nodes.canvas = el("canvas", "arcade-canvas");
    // Focusable and role="application": the running cabinet consumes arrow
    // keys and space itself, and focus has to land somewhere inside the
    // dialog when the cabinet-select buttons are hidden on start.
    nodes.canvas.setAttribute("role", "application");
    nodes.canvas.setAttribute("tabindex", "0");
    nodes.canvas.setAttribute("aria-label", "Arcade cabinet screen");
    nodes.stage.appendChild(nodes.canvas);

    var stageFoot = el("div", "arcade-stagefoot");
    nodes.hint = el("span", "arcade-hint", "");
    var back = el("button", "arcade-back", "← CABINETS");
    back.type = "button";
    back.addEventListener("click", showSelect);
    stageFoot.appendChild(nodes.hint);
    stageFoot.appendChild(back);
    nodes.stage.appendChild(stageFoot);
    frame.appendChild(nodes.stage);

    nodes.over = el("div", "arcade-over");
    nodes.over.hidden = true;
    frame.appendChild(nodes.over);

    nodes.live = el("p", "arcade-live");
    nodes.live.setAttribute("role", "status");
    nodes.live.setAttribute("aria-live", "polite");
    frame.appendChild(nodes.live);

    overlay.appendChild(frame);
    doc.body.appendChild(overlay);

    nodes.ctx = nodes.canvas.getContext("2d");
    nodes.canvas.addEventListener("pointermove", onPointer);
    nodes.canvas.addEventListener("pointerdown", onPointerDown);
    nodes.canvas.addEventListener("pointerup", releasePointer);
    nodes.canvas.addEventListener("pointercancel", releasePointer);
    nodes.canvas.addEventListener("pointerleave", function () {
      releasePointer();
      input.pointerX = null;
      input.pointerY = null;
    });
  }

  /* ---- pointer and touch -------------------------------------------------

     A phone has no arrow keys and no space bar, so the pointer has to carry
     all three verbs: position (drag), fire (tap), and direction (swipe). The
     cabinets that read a position prefer pointerX/pointerY over the direction
     flags, so latching a swipe direction here cannot fight a drag there. */
  var SWIPE_MIN = 10; // logical px before a drag counts as a swipe

  function canvasPoint(event) {
    var rect = nodes.canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return null;
    return {
      x: ((event.clientX - rect.left) / rect.width) * W,
      y: ((event.clientY - rect.top) / rect.height) * H
    };
  }

  function clearDirections() {
    input.left = false;
    input.right = false;
    input.up = false;
    input.down = false;
  }

  function onPointerDown(event) {
    var point = canvasPoint(event);
    if (!point) return;
    input.pointerX = point.x;
    input.pointerY = point.y;
    swipeFrom = point;
    // A tap is the fire button: it denies a scope and serves a request.
    pointerHeld = true;
    pointerFireSteps = FIRE_PULSE_STEPS;
    input.fire = true;
    if (screen === "play" && nodes.canvas.focus) nodes.canvas.focus();
  }

  function onPointer(event) {
    var point = canvasPoint(event);
    if (!point) return;
    input.pointerX = point.x;
    input.pointerY = point.y;
    if (!swipeFrom) return;
    var dx = point.x - swipeFrom.x;
    var dy = point.y - swipeFrom.y;
    if (Math.abs(dx) < SWIPE_MIN && Math.abs(dy) < SWIPE_MIN) return;
    // Latch the dominant axis and re-anchor, so a long drag can turn more
    // than once. Cabinets that steer by held direction read this; the rest
    // ignore it in favour of the position above.
    clearDirections();
    if (Math.abs(dx) > Math.abs(dy)) {
      input[dx > 0 ? "right" : "left"] = true;
    } else {
      input[dy > 0 ? "down" : "up"] = true;
    }
    swipeFrom = point;
  }

  function releasePointer() {
    swipeFrom = null;
    pointerHeld = false;
    if (!keyFire && pointerFireSteps <= 0) input.fire = false;
  }

  /* Run once per simulation step, before the cabinet reads input, so a tap's
     pulse is measured in steps the game actually took rather than in
     wall-clock time it may have slept through. */
  function advanceInput() {
    if (pointerFireSteps > 0) {
      pointerFireSteps -= 1;
      if (pointerFireSteps === 0 && !pointerHeld && !keyFire) input.fire = false;
    }
  }

  /* ---- focus containment -------------------------------------------------

     The page's skip link sits at body level, outside the regions this makes
     inert, and above the overlay in the stacking order, so a Tab that escaped
     would land on a control the visitor cannot even see. Containment is
     therefore handled at the document, not on the overlay: once focus is out
     — which happens whenever starting a cabinet hides the button that had it
     — an overlay-scoped listener would never run again. */
  function focusables() {
    return Array.prototype.filter.call(
      overlay.querySelectorAll("button, a[href], canvas[tabindex]"),
      function (node) {
        return !node.disabled && node.offsetParent !== null;
      }
    );
  }

  function trapFocus(event) {
    var list = focusables();
    if (!list.length) return;
    var first = list[0];
    var last = list[list.length - 1];
    if (!overlay.contains(doc.activeElement)) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
      return;
    }
    if (event.shiftKey && doc.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && doc.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function announce(text) {
    if (nodes.live) nodes.live.textContent = text;
  }

  function resizeCanvas() {
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var rect = nodes.canvas.getBoundingClientRect();
    var scale = Math.max(1, Math.floor(Math.min(rect.width / W, rect.height / H)));
    if (!rect.width) scale = 2;
    nodes.canvas.width = Math.round(W * scale * dpr);
    nodes.canvas.height = Math.round(H * scale * dpr);
    nodes.ctx.setTransform(scale * dpr, 0, 0, scale * dpr, 0, 0);
    nodes.ctx.imageSmoothingEnabled = false;
    nodes.ctx.textBaseline = "middle";
  }

  /* ---- open / close ------------------------------------------------------ */

  function openArcade() {
    if (isOpen) return;
    if (!overlay) buildOverlay();
    lastFocus = doc.activeElement;
    isOpen = true;
    overlay.hidden = false;
    root.classList.add("arcade-open");
    // The particle field's IntersectionObserver unschedules its loop the
    // moment the canvas stops intersecting, so hiding it here is the pause.
    setBackgroundInert(true);
    random = makeRandom(20260819);
    startBoot();
    var close = overlay.querySelector(".arcade-close");
    if (close) close.focus();
    announce("Arcade open. The agents continue working.");
  }

  function closeArcade() {
    if (!isOpen) return;
    isOpen = false;
    stopLoop();
    screen = "closed";
    current = null;
    game = null;
    overlay.hidden = true;
    root.classList.remove("arcade-open");
    setBackgroundInert(false);
    if (lastFocus && typeof lastFocus.focus === "function") lastFocus.focus();
  }

  function setBackgroundInert(on) {
    // The skip link is a body-level sibling rather than part of any of these
    // landmarks, so listing only the landmarks would leave exactly one
    // tabbable control outside the dialog.
    var regions = [
      doc.querySelector(".skip-link"),
      doc.querySelector(".site-nav"),
      doc.getElementById("main"),
      doc.querySelector(".site-footer")
    ];
    regions.forEach(function (region) {
      if (!region) return;
      if (on) {
        region.setAttribute("aria-hidden", "true");
        if ("inert" in region) region.inert = true;
      } else {
        region.removeAttribute("aria-hidden");
        if ("inert" in region) region.inert = false;
      }
    });
  }

  /* ---- boot -------------------------------------------------------------- */

  function startBoot() {
    screen = "boot";
    nodes.boot.hidden = false;
    nodes.select.hidden = true;
    nodes.stage.hidden = true;
    nodes.over.hidden = true;
    bootIndex = 0;
    bootTimer = 0;
    nodes.boot.textContent = "";
    if (prefersStaticMotion()) {
      // One frame, no typing: the boot sequence is decoration, and decoration
      // is exactly what reduced motion asks us to drop.
      nodes.boot.textContent = BOOT_LINES.join("\n");
      bootIndex = BOOT_LINES.length;
      showSelect();
      return;
    }
    startLoop();
  }

  function tickBoot(dt) {
    bootTimer += dt;
    if (bootTimer < 0.16) return;
    bootTimer = 0;
    if (bootIndex >= BOOT_LINES.length) {
      showSelect();
      return;
    }
    nodes.boot.textContent += (bootIndex ? "\n" : "") + BOOT_LINES[bootIndex];
    bootIndex += 1;
  }

  /* ---- select ------------------------------------------------------------ */

  function showSelect() {
    screen = "select";
    current = null;
    game = null;
    nodes.boot.hidden = false;
    nodes.select.hidden = false;
    nodes.stage.hidden = true;
    nodes.over.hidden = true;
    if (!prefersStaticMotion()) startLoop();
    else stopLoop();
    // Coming back from a run hides the stage while its ← CABINETS button still
    // holds focus. Engines disagree about whether that resets activeElement to
    // body or leaves it on the now-invisible button, and the second case
    // strands keyboard and screen-reader focus in a hidden subtree — so test
    // whether focus is still on something visible rather than trusting either
    // behaviour.
    var first = nodes.select.querySelector(".arcade-cabinet");
    var active = doc.activeElement;
    var activeVisible =
      active &&
      active !== doc.body &&
      overlay.contains(active) &&
      active.offsetParent !== null;
    if (first && isOpen && !activeVisible) first.focus();
    announce("Cabinet select. Four cabinets available.");
  }

  /* ---- play -------------------------------------------------------------- */

  function startGame(id) {
    var cabinet = null;
    CABINETS.forEach(function (entry) {
      if (entry.id === id) cabinet = entry;
    });
    if (!cabinet) return;
    current = cabinet;
    game = cabinet.make(random);
    game.reset();
    screen = "play";
    paused = false;
    nodes.boot.hidden = true;
    nodes.select.hidden = true;
    nodes.over.hidden = true;
    nodes.stage.hidden = false;
    nodes.hudName.textContent = cabinet.name;
    nodes.hint.textContent =
      cabinet.controls + touchHint(cabinet) + " · P pause · ESC exit";
    nodes.canvas.setAttribute("aria-label", cabinet.name + " — " + cabinet.tagline);
    resizeCanvas();
    updateHud();
    clearDirections();
    clearPointerAim();
    input.fire = false;
    pointerHeld = false;
    pointerFireSteps = 0;
    keyFire = false;
    // Starting a cabinet hides the button that had focus, which would drop
    // focus to the body and let the next Tab leave the dialog. The screen
    // itself takes it instead — it is the control now.
    nodes.canvas.focus();
    startLoop();
    announce(cabinet.name + " started. " + cabinet.controls);
  }

  /* Touch verbs differ per cabinet, and a phone visitor has no way to guess
     them from a line that only names keys. */
  function touchHint(cabinet) {
    var coarse =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(pointer: coarse)").matches;
    if (!coarse) return "";
    if (cabinet.id === "append-only") return " · or swipe to steer";
    if (cabinet.id === "race-condition") return " · or drag to move";
    return " · or drag to move, tap to fire";
  }

  function updateHud() {
    if (!game) return;
    nodes.hudScore.textContent = "RECEIPTS " + game.score;
    nodes.hudLives.textContent = "RETRIES " + Math.max(0, game.lives);
    nodes.hudExtra.textContent = game.hud ? game.hud() : "";
  }

  function endGame() {
    screen = "over";
    stopLoop();
    nodes.stage.hidden = true;
    nodes.over.hidden = false;
    nodes.over.textContent = "";

    var heading = el("p", "arcade-over-heading", "RUN COMPLETE — " + current.name);
    nodes.over.appendChild(heading);
    nodes.over.appendChild(
      el("p", "arcade-over-score", game.score + " RECEIPTS SCORED. NONE OF THEM COUNT.")
    );
    nodes.over.appendChild(buildReceipt(current, game.score, random));

    var actions = el("div", "arcade-over-actions");
    var again = el("button", "arcade-again", "PLAY AGAIN");
    again.type = "button";
    again.addEventListener("click", function () {
      startGame(current.id);
    });
    var back = el("button", "arcade-back", "← CABINETS");
    back.type = "button";
    back.addEventListener("click", showSelect);
    actions.appendChild(again);
    actions.appendChild(back);
    nodes.over.appendChild(actions);
    again.focus();
    announce("Run complete. " + game.score + " receipts scored. A simulated receipt was issued.");
  }

  /* ---- frame loop -------------------------------------------------------- */

  function startLoop() {
    if (rafId) return;
    lastNow = 0;
    accumulator = 0;
    rafId = window.requestAnimationFrame(frame);
  }

  function stopLoop() {
    if (rafId) {
      window.cancelAnimationFrame(rafId);
      rafId = 0;
    }
  }

  function frame(now) {
    rafId = 0;
    if (!isOpen) return;

    var dt = lastNow ? Math.min((now - lastNow) / 1000, 0.25) : STEP;
    lastNow = now;

    // Status ticker runs on every screen: the agents are always busy.
    statusTimer += dt;
    if (statusTimer > 4 && !prefersStaticMotion()) {
      statusTimer = 0;
      statusIndex = (statusIndex + 1) % AGENT_STATUS.length;
      nodes.status.textContent = AGENT_STATUS[statusIndex];
    }

    if (screen === "boot") {
      tickBoot(dt);
    } else if (screen === "play" && game) {
      if (!paused) {
        accumulator += dt;
        var steps = 0;
        while (accumulator >= STEP && steps < MAX_CATCHUP) {
          advanceInput();
          game.update(STEP, input);
          accumulator -= STEP;
          steps += 1;
          if (game.over) break;
        }
        if (accumulator > STEP * MAX_CATCHUP) accumulator = 0;
      }
      render();
      updateHud();
      announceTimer += dt;
      if (announceTimer > 8) {
        announceTimer = 0;
        announce(
          "Score " + game.score + " receipts, " + Math.max(0, game.lives) + " retries left."
        );
      }
      if (game.over) {
        endGame();
        return;
      }
    }

    // Only reschedule if nothing already did. tickBoot's hand-off to the
    // select screen calls startLoop() from inside this very frame, where
    // rafId has already been zeroed — without this guard that leaves two
    // loops running and stopLoop() able to cancel only the newer one.
    if (isOpen && screen !== "over" && !rafId) {
      rafId = window.requestAnimationFrame(frame);
    }
  }

  function render() {
    var ctx = nodes.ctx;
    var ink = inkPalette();
    ctx.fillStyle = ink.bg;
    ctx.fillRect(0, 0, W, H);

    ctx.fillStyle = ink.grid;
    ctx.fillRect(0, 18, W, 1);

    ctx.font = '8px "IBM Plex Mono", monospace';
    ctx.fillStyle = ink.dim;
    ctx.textAlign = "left";
    ctx.fillText(current ? current.name : "", 4, 10);
    ctx.textAlign = "right";
    ctx.fillText("RECEIPTS " + game.score, W - 4, 10);
    ctx.textAlign = "left";

    game.draw(ctx, ink);

    if (paused) {
      ctx.fillStyle = "rgba(5, 7, 13, 0.86)";
      ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = ink.brass;
      ctx.textAlign = "center";
      ctx.font = '9px "IBM Plex Mono", monospace';
      PAUSE_LINES.forEach(function (line, index) {
        ctx.fillText(line, W / 2, H / 2 - 12 + index * 14);
      });
      ctx.textAlign = "left";
    }
  }

  /* ---- input ------------------------------------------------------------- */

  var KEYS = {
    ArrowLeft: "left",
    ArrowRight: "right",
    ArrowUp: "up",
    ArrowDown: "down",
    a: "left",
    d: "right",
    w: "up",
    s: "down",
    A: "left",
    D: "right",
    W: "up",
    S: "down",
    " ": "fire",
    Spacebar: "fire"
  };

  function onKeyDown(event) {
    if (!isOpen) return;
    if (event.key === "Tab") {
      trapFocus(event);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      closeArcade();
      return;
    }
    if ((event.key === "p" || event.key === "P") && screen === "play") {
      paused = !paused;
      announce(paused ? "Paused." : "Resumed.");
      render();
      return;
    }
    var slot = KEYS[event.key];
    if (!slot) return;
    // Only a running cabinet claims the game keys. On the menus they belong
    // to the browser, or Space could never choose a cabinet or press PLAY
    // AGAIN — both of which are buttons the keyboard has to be able to
    // activate.
    if (screen !== "play") return;
    var onControl =
      event.target &&
      typeof event.target.closest === "function" &&
      event.target.closest("button, a[href]");
    if (slot === "fire" && onControl) return;
    // Arrow keys and space scroll the page underneath otherwise.
    event.preventDefault();
    if (slot === "fire") keyFire = true;
    input[slot] = true;
    clearPointerAim();
  }

  /* Keyboard reclaims aim from the pointer: a cabinet that reads pointerX
     would otherwise pin the player where the mouse was last seen. */
  function clearPointerAim() {
    input.pointerX = null;
    input.pointerY = null;
    swipeFrom = null;
  }

  function onKeyUp(event) {
    var slot = KEYS[event.key];
    if (!slot) return;
    if (slot === "fire") {
      keyFire = false;
      // A pointer may still be holding fire, or a tap's pulse may still be
      // owed steps; releasing the key must not cancel either.
      if (pointerHeld || pointerFireSteps > 0) return;
    }
    input[slot] = false;
  }

  doc.addEventListener("keydown", onKeyDown);
  doc.addEventListener("keyup", onKeyUp);

  window.addEventListener("resize", function () {
    if (isOpen && screen === "play") resizeCanvas();
  });

  doc.addEventListener("visibilitychange", function () {
    if (doc.hidden && screen === "play") {
      paused = true;
      if (nodes.ctx) render();
    }
  });

  /* ---- launcher ---------------------------------------------------------- */

  // The launcher ships hidden so a visitor without JavaScript never sees a
  // control that cannot do anything; revealing it is this script's proof of
  // life. The wrapper carries the explanatory copy, so it is revealed too.
  launcher.hidden = false;
  if (typeof launcher.closest === "function") {
    var launchWrap = launcher.closest(".footer-arcade");
    if (launchWrap) launchWrap.hidden = false;
  }
  launcher.addEventListener("click", function () {
    openArcade();
  });

  // ?arcade=<cabinet-id> opens straight into a cabinet. Used for screenshots
  // and headless checks; harmless in a visitor's hands.
  try {
    var requested = new URLSearchParams(window.location.search).get("arcade");
    if (requested) {
      openArcade();
      if (requested !== "1" && requested !== "true") startGame(requested);
    }
  } catch (error) {
    /* URLSearchParams is absent on very old engines; the launcher still works. */
  }

  window.__amwArcade = {
    open: openArcade,
    close: closeArcade,
    start: startGame,
    select: showSelect,
    /* Buttons only. pointerX/pointerY live on the same object but hold a
       number or null, and coercing them with !! would pin a cabinet's player
       at the clamp floor instead of the requested position — use aim(). */
    press: function (name, down) {
      if (name === "pointerX" || name === "pointerY") return false;
      if (!Object.prototype.hasOwnProperty.call(input, name)) return false;
      input[name] = !!down;
      if (name === "fire") keyFire = !!down;
      return true;
    },
    aim: function (x, y) {
      input.pointerX = typeof x === "number" ? x : null;
      input.pointerY = typeof y === "number" ? y : null;
    },
    /* Advance the simulation deterministically, bypassing wall-clock timing so
       automated checks never race a frame budget. */
    step: function (count) {
      var n = count || 1;
      for (var i = 0; i < n && game && !game.over; i += 1) {
        advanceInput();
        game.update(STEP, input);
      }
      if (game && nodes.ctx) {
        render();
        updateHud();
        if (game.over && screen === "play") endGame();
      }
      return this.state();
    },
    state: function () {
      return {
        open: isOpen,
        screen: screen,
        cabinet: current ? current.id : null,
        score: game ? game.score : 0,
        lives: game ? game.lives : 0,
        over: game ? game.over : false,
        paused: paused,
        reducedMotion: prefersStaticMotion(),
        // What the cabinet is actually being told, so a check can prove a tap
        // or a swipe arrived rather than inferring it from a score.
        keys: {
          left: input.left,
          right: input.right,
          up: input.up,
          down: input.down,
          fire: input.fire,
          pointerX: input.pointerX,
          pointerY: input.pointerY
        }
      };
    }
  };
})();
