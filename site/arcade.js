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

  /* Sprite labels for the first-person cabinets. Eight characters or fewer:
     the label band is drawn at the sprite's own width and a longer string
     overruns it into the corridor. */
  var LOOSE_CALLS = [
    "tools/*", "refund", "db:drop", "keys:rw", "admin:*", "payout", "prod:ssh", "iam:*"
  ];
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
    danger: "#ff6b5e",
    /* Four wall shades for the first-person cabinets, darkest last. A wall
       painted in `ink` (near-white) reads as a light source rather than as
       stone, which is what the corridors looked like before this ramp existed.
       Four steps, not a gradient: a continuous ramp needs colours this palette
       does not have, and banding is how depth was said at this vintage. */
    wall: ["#8b7cd4", "#5f52a8", "#463a86", "#2e2663"]
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

  /* Signed shortest angle from `b` to `a`, in (-pi, pi].

     JavaScript's `%` keeps the sign of its left operand, so the usual
     "+ 3*PI then % 2*PI" trick silently breaks once the left side goes
     negative — which it does as soon as a heading is left to accumulate past
     3*PI. Written out rather than golfed, because the golfed version reads as
     correct right up until the frame it stops being. */
  function angleDelta(a, b) {
    var d = (a - b) % (Math.PI * 2);
    if (d <= -Math.PI) d += Math.PI * 2;
    else if (d > Math.PI) d -= Math.PI * 2;
    return d;
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

  /* ======================================================================
     RAYCAST ENGINE

     Shared by the two first-person cabinets. A grid map, a DDA per column,
     and billboarded sprites — the 1992 technique, which is the only one that
     fits this canvas and this palette. Nothing here is 3D: every wall is an
     axis-aligned unit square, so a column's height is one divide.

     Columns are drawn COLUMN_W wide rather than one pixel each. That is two
     things at once: a quarter of the fill calls, and the chunky vertical banding
     the rest of the design system is built out of. A one-pixel column on a
     320-wide canvas would render a smooth wall, which would look wrong here.
     ====================================================================== */

  var COLUMN_W = 4;
  var FOV = 0.66; // camera plane half-width; ~60 degrees horizontal

  function makeCaster(mapRows) {
    /* Solids are named explicitly and everything else is open floor. The
       inverse — defaulting to solid — silently turns a level that uses any
       other character for floor into a block of stone, which the cabinet then
       reports as "cleared" on its first frame because nothing can spawn in it.
         #  wall
         =  boundary marker (verify-tinted)
         !  hot wall (danger-tinted)
         anything else  open floor */
    var map = mapRows.map(function (row) {
      return row.split("").map(function (ch) {
        return ch === "#" ? 1 : ch === "=" ? 2 : ch === "!" ? 3 : 0;
      });
    });
    var MH = map.length;
    var MW = map[0].length;

    function solid(x, y) {
      var cx = Math.floor(x);
      var cy = Math.floor(y);
      if (cx < 0 || cy < 0 || cx >= MW || cy >= MH) return 1;
      return map[cy][cx];
    }

    /* Walls are stepped through in grid units (DDA) rather than sampled at a
       fixed distance: sampling misses thin walls at grazing angles and costs
       more the further the ray travels. Returns the perpendicular distance —
       not the euclidean one, which would fisheye the view. */
    function cast(px, py, rdx, rdy) {
      var mapX = Math.floor(px);
      var mapY = Math.floor(py);
      var deltaX = rdx === 0 ? 1e30 : Math.abs(1 / rdx);
      var deltaY = rdy === 0 ? 1e30 : Math.abs(1 / rdy);
      var stepX, stepY, sideX, sideY;

      if (rdx < 0) { stepX = -1; sideX = (px - mapX) * deltaX; }
      else { stepX = 1; sideX = (mapX + 1 - px) * deltaX; }
      if (rdy < 0) { stepY = -1; sideY = (py - mapY) * deltaY; }
      else { stepY = 1; sideY = (mapY + 1 - py) * deltaY; }

      var side = 0;
      var tile = 0;
      // Bounded rather than while(true): a ray that escapes the map through a
      // gap would otherwise walk forever on a malformed level.
      for (var guard = 0; guard < 64; guard += 1) {
        if (sideX < sideY) { sideX += deltaX; mapX += stepX; side = 0; }
        else { sideY += deltaY; mapY += stepY; side = 1; }
        if (mapX < 0 || mapY < 0 || mapX >= MW || mapY >= MH) { tile = 1; break; }
        tile = map[mapY][mapX];
        if (tile) break;
      }
      var dist = side === 0
        ? (mapX - px + (1 - stepX) / 2) / (rdx || 1e-30)
        : (mapY - py + (1 - stepY) / 2) / (rdy || 1e-30);
      return { dist: Math.max(0.0001, dist), side: side, tile: tile || 1 };
    }

    return { map: map, w: MW, h: MH, solid: solid, cast: cast };
  }

  /* Move with a wall slide: each axis is tested on its own so a player who
     walks into a corner slides along it instead of sticking. Sticking in a
     corridor shooter reads as a broken control, not as a wall. */
  function casterMove(caster, ent, dx, dy) {
    var pad = 0.18;
    if (!caster.solid(ent.x + dx + (dx > 0 ? pad : -pad), ent.y)) ent.x += dx;
    if (!caster.solid(ent.x, ent.y + dy + (dy > 0 ? pad : -pad))) ent.y += dy;
  }

  /* Renders walls into ctx and returns the per-column depth buffer, which the
     sprite pass needs to avoid drawing enemies through walls. */
  function casterDrawWalls(ctx, ink, caster, cam) {
    var zbuf = [];
    var planeX = -cam.dirY * FOV;
    var planeY = cam.dirX * FOV;
    var horizon = H / 2;

    // Ceiling and floor as two flat bands. A textured floor would cost more
    // than the whole rest of the frame and read as noise at this palette.
    ctx.fillStyle = ink.bg;
    ctx.fillRect(0, 0, W, horizon);
    ctx.fillStyle = ink.grid;
    ctx.fillRect(0, horizon, W, H - horizon);

    for (var x = 0; x < W; x += COLUMN_W) {
      var camX = 2 * (x + COLUMN_W / 2) / W - 1;
      var hit = caster.cast(cam.x, cam.y, cam.dirX + planeX * camX, cam.dirY + planeY * camX);
      var lineH = Math.floor(H / hit.dist);
      var top = Math.floor(horizon - lineH / 2);

      // Four depth bands instead of a continuous ramp: a smooth gradient needs
      // colours this palette does not have, and banding is the period-correct
      // way to say "further away".
      var shade;
      if (hit.tile === 2) shade = hit.side ? ink.verify : ink.bright;
      else if (hit.tile === 3) shade = hit.side ? ink.danger : ink.brass;
      else {
        var band = hit.dist < 2.5 ? 0 : hit.dist < 5 ? 1 : hit.dist < 8 ? 2 : 3;
        // A wall seen edge-on drops one band, which is what separates a
        // corner from a flat run at this palette depth.
        if (hit.side) band = Math.min(3, band + 1);
        shade = ink.wall[band];
      }

      ctx.fillStyle = shade;
      ctx.fillRect(x, Math.max(0, top), COLUMN_W, Math.min(H, lineH));
      for (var c = 0; c < COLUMN_W; c += 1) zbuf[x + c] = hit.dist;
    }
    return zbuf;
  }

  /* Billboarded sprites: transform into camera space, reject anything behind
     the plane, then draw as a stack of chunky columns so a sprite occluded by
     a wall corner is clipped per column rather than all-or-nothing. */
  function casterDrawSprites(ctx, ink, cam, sprites, zbuf) {
    var planeX = -cam.dirY * FOV;
    var planeY = cam.dirX * FOV;
    var inv = 1 / (planeX * cam.dirY - cam.dirX * planeY);

    sprites
      .map(function (s) {
        var relX = s.x - cam.x;
        var relY = s.y - cam.y;
        return {
          s: s,
          tx: inv * (cam.dirY * relX - cam.dirX * relY),
          ty: inv * (-planeY * relX + planeX * relY)
        };
      })
      .filter(function (p) { return p.ty > 0.25; })
      .sort(function (a, b) { return b.ty - a.ty; })
      .forEach(function (p) {
        var screenX = Math.floor((W / 2) * (1 + p.tx / p.ty));
        var size = Math.abs(Math.floor(H / p.ty)) * (p.s.scale || 0.7);
        var top = Math.floor(H / 2 - size / 2 + (p.s.lift || 0) / p.ty);
        var left = Math.floor(screenX - size / 2);

        var visible = 0;
        for (var x = left; x < left + size; x += COLUMN_W) {
          if (x < 0 || x >= W) continue;
          if (zbuf[x] != null && p.ty >= zbuf[x]) continue;
          visible += 1;
          ctx.fillStyle = p.s.color;
          ctx.fillRect(x, Math.max(0, top), COLUMN_W, Math.min(H - Math.max(0, top), size));
        }

        // A label band, so the thing you are shooting says what it is. The
        // whole point of these cabinets is the vocabulary.
        //
        // Gated on a column of the sprite actually having survived the depth
        // test. The body columns are rejected against zbuf individually, but
        // the label was painted unconditionally — so a call standing behind a
        // wall announced itself through it, which both looks broken and gives
        // away a target the corridor is supposed to be hiding.
        if (visible > 0 && p.s.label && p.ty < 7 && size > 22) {
          ctx.fillStyle = ink.bg;
          ctx.fillRect(left, top - 9, size, 8);
          ctx.fillStyle = p.s.color;
          ctx.font = '7px "IBM Plex Mono", monospace';
          ctx.textAlign = "center";
          ctx.fillText(p.s.label, screenX, top - 2);
          ctx.textAlign = "left";
        }
      });
  }

  /* The muzzle/weapon furniture both first-person cabinets share. */
  function casterDrawWeapon(ctx, ink, kick, flash) {
    var baseY = H - 6 + kick * 5;
    ctx.fillStyle = ink.dim;
    ctx.fillRect(W / 2 - 10, baseY - 26, 20, 26);
    ctx.fillStyle = ink.ink;
    ctx.fillRect(W / 2 - 6, baseY - 34, 12, 10);
    if (flash > 0) {
      ctx.fillStyle = ink.bright;
      ctx.fillRect(W / 2 - 5, baseY - 42, 10, 9);
      ctx.fillStyle = ink.brass;
      ctx.fillRect(W / 2 - 9, baseY - 39, 18, 4);
    }
    // Reticle
    ctx.fillStyle = ink.verify;
    ctx.fillRect(W / 2 - 5, H / 2, 3, 1);
    ctx.fillRect(W / 2 + 2, H / 2, 3, 1);
    ctx.fillRect(W / 2, H / 2 - 5, 1, 3);
    ctx.fillRect(W / 2, H / 2 + 2, 1, 3);
  }

  /* Hitscan: the nearest sprite within `spread` radians of the view axis and
     in front of a wall. Hitscan rather than a projectile because a travelling
     bullet at this resolution is a single pixel nobody can see. */
  function casterHitscan(cam, sprites, caster) {
    var best = null;
    sprites.forEach(function (s) {
      if (s.dead) return;
      var relX = s.x - cam.x;
      var relY = s.y - cam.y;
      var dist = Math.sqrt(relX * relX + relY * relY);
      if (dist < 0.01) return;
      var along = (relX * cam.dirX + relY * cam.dirY) / dist;
      if (along < 0) return; // behind the camera plane
      var spread = Math.atan2(Math.abs(relX * cam.dirY - relY * cam.dirX), relX * cam.dirX + relY * cam.dirY);
      // A fixed angular cone covers less and less of a target the closer it
      // stands, so an enemy that walks into your face becomes unhittable at
      // exactly the moment it is most dangerous — which is how it read on the
      // corridor cabinets, as a gun that stops working under pressure. Accept
      // either the cone or a small lateral miss distance; beyond ~2.5 units
      // the cone is the narrower of the two and nothing changes.
      if (spread > 0.16 && Math.sin(spread) * dist > 0.4) return;
      // A wall between us and it means the shot stops at the wall.
      if (caster.cast(cam.x, cam.y, relX / dist, relY / dist).dist < dist - 0.2) return;
      if (!best || dist < best.dist) best = { sprite: s, dist: dist };
    });
    return best;
  }

  /* ---- 5. BLAST RADIUS ---------------------------------------------------

     First person, down the corridors of a permit boundary. Unscoped calls
     wander the maze looking for the tool; you get there first. Clear the
     floor and the next one has more of them, moving faster.

     Controls are turn-and-walk rather than mouselook, which is both what this
     input surface offers (five keys, no pointer lock) and what a cabinet of
     this vintage would have had anyway. */
  function cabinetBlastRadius(random) {
    var MAP = [
      "################",
      "#....#.....#...#",
      "#.##.#.###.#.#.#",
      "#.#..#...#...#.#",
      "#.#.###.###.##.#",
      "#.#.....#....#.#",
      "#.#####.#.####.#",
      "#.......#......#",
      "#.####.###.###.#",
      "#.#..#.....#...#",
      "#.#.###.##.#.#.#",
      "#.#...#..#.#.#.#",
      "#.###.##.#.#.#.#",
      "#.....#....#...#",
      "#.###.#.####.#.#",
      "################"
    ];
    var caster = makeCaster(MAP);
    var game = { id: "blast-radius", score: 0, lives: 3, over: false };
    var cam, calls, floor, kick, flash, cooldown, hurt, message, messageAge, open;

    /* Reachable open cells, flood-filled from the spawn. Spawning from the
       raw map instead would eventually drop a call into a sealed pocket,
       where it is unkillable and the floor can never be cleared. */
    function reachable(sx, sy) {
      var seen = {};
      var out = [];
      var queue = [[sx, sy]];
      seen[sx + "," + sy] = true;
      while (queue.length) {
        var cell = queue.shift();
        out.push(cell);
        [[1, 0], [-1, 0], [0, 1], [0, -1]].forEach(function (d) {
          var nx = cell[0] + d[0];
          var ny = cell[1] + d[1];
          var key = nx + "," + ny;
          if (seen[key]) return;
          if (nx < 0 || ny < 0 || nx >= caster.w || ny >= caster.h) return;
          if (caster.map[ny][nx]) return;
          seen[key] = true;
          queue.push([nx, ny]);
        });
      }
      return out;
    }

    function spawnFloor() {
      calls = [];
      var count = Math.min(3 + floor * 2, 12);
      // Never adjacent to the player: a call spawned in your face is a retry
      // lost to nothing you could have reacted to.
      var far = open.filter(function (cell) {
        var dx = cell[0] + 0.5 - cam.x;
        var dy = cell[1] + 0.5 - cam.y;
        return Math.sqrt(dx * dx + dy * dy) > 4;
      });
      for (var i = 0; i < count && far.length; i += 1) {
        var pick = far[Math.floor(random() * far.length)];
        calls.push({
          x: pick[0] + 0.5,
          y: pick[1] + 0.5,
          color: "",
          label: LOOSE_CALLS[Math.floor(random() * LOOSE_CALLS.length)],
          scale: 0.62,
          speed: 0.55 + floor * 0.14,
          dead: false
        });
      }
    }

    game.reset = function () {
      game.score = 0;
      game.lives = 3;
      game.over = false;
      floor = 1;
      kick = 0;
      flash = 0;
      cooldown = 0;
      hurt = 0;
      message = "FLOOR 1";
      messageAge = 0;
      cam = { x: 1.5, y: 1.5, dirX: 1, dirY: 0, angle: 0 };
      open = reachable(1, 1);
      spawnFloor();
    };

    game.update = function (dt, input) {
      if (game.over) return;

      var turn = 2.1 * dt;
      // Turning reads only the direction flags. A drag sets those through the
      // shell's swipe latch, so touch steers without this cabinet knowing
      // anything about pointers — and, crucially, a hovering mouse does not
      // steer at all. Treating pointerX as a turn RATE (which an earlier
      // version did) spins the camera forever the moment the pointer rests
      // anywhere off-centre, including on a desktop with no button held.
      if (input.left) cam.angle -= turn;
      if (input.right) cam.angle += turn;
      cam.dirX = Math.cos(cam.angle);
      cam.dirY = Math.sin(cam.angle);

      var pace = 2.0 * dt;
      if (input.up) casterMove(caster, cam, cam.dirX * pace, cam.dirY * pace);
      if (input.down) casterMove(caster, cam, -cam.dirX * pace * 0.7, -cam.dirY * pace * 0.7);

      cooldown -= dt;
      kick = Math.max(0, kick - dt * 6);
      flash = Math.max(0, flash - dt * 8);
      hurt = Math.max(0, hurt - dt * 2);
      messageAge += dt;

      if (input.fire && cooldown <= 0) {
        cooldown = 0.28;
        kick = 1;
        flash = 1;
        var hit = casterHitscan(cam, calls, caster);
        if (hit) {
          hit.sprite.dead = true;
          game.score += 25;
          message = "DENIED " + hit.sprite.label;
          messageAge = 0;
        } else {
          // Missing costs score, not a retry: the joke is the metering, and a
          // shot that debits nothing would make firing blindly optimal.
          game.score = Math.max(0, game.score - 5);
        }
      }

      calls = calls.filter(function (c) { return !c.dead; });

      calls.forEach(function (c) {
        var dx = cam.x - c.x;
        var dy = cam.y - c.y;
        var dist = Math.sqrt(dx * dx + dy * dy) || 1;
        casterMove(caster, c, (dx / dist) * c.speed * dt, (dy / dist) * c.speed * dt);
        if (dist < 0.55 && hurt <= 0) {
          hurt = 1;
          game.lives -= 1;
          message = "REACHED THE TOOL";
          messageAge = 0;
          // Shoved back to the spawn rather than killed outright: losing the
          // floor's progress to one bad corner would be the cheap version.
          cam.x = 1.5;
          cam.y = 1.5;
          if (game.lives <= 0) game.over = true;
        }
      });

      if (!calls.length && !game.over) {
        floor += 1;
        game.score += 100;
        message = "FLOOR " + floor;
        messageAge = 0;
        spawnFloor();
      }
    };

    game.draw = function (ctx, ink) {
      calls.forEach(function (c) { c.color = ink.danger; });
      var zbuf = casterDrawWalls(ctx, ink, caster, cam);
      casterDrawSprites(ctx, ink, cam, calls, zbuf);
      casterDrawWeapon(ctx, ink, kick, flash);

      if (hurt > 0) {
        // A full-screen red wash would be unreadable on this palette; a border
        // says the same thing and leaves the corridor visible.
        ctx.fillStyle = ink.danger;
        ctx.fillRect(0, 0, W, 2);
        ctx.fillRect(0, H - 2, W, 2);
        ctx.fillRect(0, 0, 2, H);
        ctx.fillRect(W - 2, 0, 2, H);
      }

      drawMinimap(ctx, ink, caster, cam, calls);

      if (message && messageAge < 2) {
        ctx.fillStyle = ink.bright;
        ctx.font = '8px "IBM Plex Mono", monospace';
        ctx.textAlign = "center";
        ctx.fillText(message, W / 2, 32);
        ctx.textAlign = "left";
      }
    };

    game.hud = function () {
      return "FLOOR " + floor + " · " + calls.length + " LOOSE";
    };

    return game;
  }

  /* A corner minimap. Both first-person cabinets need one: turn-and-walk with
     no strafe is disorienting without a plan view, and this is cheaper to read
     than making the maze simpler. */
  function drawMinimap(ctx, ink, caster, cam, sprites) {
    var cell = 3;
    var ox = W - caster.w * cell - 3;
    var oy = 22;
    ctx.fillStyle = ink.bg;
    ctx.fillRect(ox - 1, oy - 1, caster.w * cell + 2, caster.h * cell + 2);
    for (var y = 0; y < caster.h; y += 1) {
      for (var x = 0; x < caster.w; x += 1) {
        if (!caster.map[y][x]) continue;
        ctx.fillStyle = ink.grid;
        ctx.fillRect(ox + x * cell, oy + y * cell, cell, cell);
      }
    }
    sprites.forEach(function (s) {
      ctx.fillStyle = ink.danger;
      ctx.fillRect(ox + s.x * cell - 1, oy + s.y * cell - 1, 2, 2);
    });
    ctx.fillStyle = ink.verify;
    ctx.fillRect(ox + cam.x * cell - 1, oy + cam.y * cell - 1, 2, 2);
  }

  /* ---- 6. HOLD THE LINE --------------------------------------------------

     The other half of the first-person pair, and the inverse problem. You do
     not advance: you stand on the boundary itself while calls arrive down four
     corridors. Anything that reaches the post is a call that got through. */
  function cabinetHoldTheLine(random) {
    var MAP = [
      "#####==#####",
      "#####..#####",
      "#####..#####",
      "##.......###",
      "##.......###",
      "=..........=",
      "=..........=",
      "##.......###",
      "##.......###",
      "#####..#####",
      "#####..#####",
      "#####==#####"
    ];
    var caster = makeCaster(MAP);
    var MOUTHS = [
      { x: 6, y: 1.2 }, { x: 6, y: 10.8 }, { x: 1.2, y: 6 }, { x: 10.8, y: 6 }
    ];

    var game = { id: "hold-the-line", score: 0, lives: 3, over: false };
    var cam, calls, wave, spawnTimer, remaining, kick, flash, cooldown, hurt, message, messageAge, post;

    function startWave() {
      remaining = 4 + wave * 2;
      spawnTimer = 0.6;
    }

    game.reset = function () {
      game.score = 0;
      game.lives = 3;
      game.over = false;
      wave = 1;
      calls = [];
      kick = 0;
      flash = 0;
      cooldown = 0;
      hurt = 0;
      message = "WAVE 1";
      messageAge = 0;
      post = { x: 6, y: 6 };
      cam = { x: post.x, y: post.y, dirX: 0, dirY: -1, angle: -Math.PI / 2 };
      startWave();
    };

    game.update = function (dt, input) {
      if (game.over) return;

      var turn = 2.4 * dt;
      // Direction flags only — see the note in BLAST RADIUS on why a pointer
      // position must not drive a camera.
      if (input.left) cam.angle -= turn;
      if (input.right) cam.angle += turn;
      cam.dirX = Math.cos(cam.angle);
      cam.dirY = Math.sin(cam.angle);

      // Step off the post only far enough to change an angle. Wandering is the
      // other cabinet's game; here leaving the line is the failure.
      var pace = 1.4 * dt;
      if (input.up) casterMove(caster, cam, cam.dirX * pace, cam.dirY * pace);
      if (input.down) casterMove(caster, cam, -cam.dirX * pace, -cam.dirY * pace);
      var offX = cam.x - post.x;
      var offY = cam.y - post.y;
      var leash = Math.sqrt(offX * offX + offY * offY);
      if (leash > 1.6) {
        cam.x = post.x + (offX / leash) * 1.6;
        cam.y = post.y + (offY / leash) * 1.6;
      }

      cooldown -= dt;
      kick = Math.max(0, kick - dt * 6);
      flash = Math.max(0, flash - dt * 8);
      hurt = Math.max(0, hurt - dt * 2);
      messageAge += dt;

      if (input.fire && cooldown <= 0) {
        cooldown = 0.24;
        kick = 1;
        flash = 1;
        var hit = casterHitscan(cam, calls, caster);
        if (hit) {
          hit.sprite.dead = true;
          game.score += 20;
        } else {
          game.score = Math.max(0, game.score - 4);
        }
      }

      spawnTimer -= dt;
      if (spawnTimer <= 0 && remaining > 0) {
        remaining -= 1;
        spawnTimer = Math.max(0.35, 1.5 - wave * 0.12);
        var mouth = MOUTHS[Math.floor(random() * MOUTHS.length)];
        calls.push({
          x: mouth.x,
          y: mouth.y,
          color: "",
          label: LOOSE_CALLS[Math.floor(random() * LOOSE_CALLS.length)],
          scale: 0.6,
          speed: 0.5 + wave * 0.1,
          dead: false
        });
      }

      calls = calls.filter(function (c) { return !c.dead; });
      calls.forEach(function (c) {
        var dx = post.x - c.x;
        var dy = post.y - c.y;
        var dist = Math.sqrt(dx * dx + dy * dy) || 1;
        casterMove(caster, c, (dx / dist) * c.speed * dt, (dy / dist) * c.speed * dt);
        if (dist < 0.8) {
          c.dead = true;
          if (hurt <= 0) {
            hurt = 1;
            game.lives -= 1;
            message = "GOT THROUGH";
            messageAge = 0;
            if (game.lives <= 0) game.over = true;
          }
        }
      });

      if (!calls.length && remaining <= 0 && !game.over) {
        wave += 1;
        game.score += 60;
        message = "WAVE " + wave;
        messageAge = 0;
        startWave();
      }
    };

    game.draw = function (ctx, ink) {
      calls.forEach(function (c) { c.color = ink.danger; });
      var zbuf = casterDrawWalls(ctx, ink, caster, cam);
      casterDrawSprites(ctx, ink, cam, calls, zbuf);
      casterDrawWeapon(ctx, ink, kick, flash);

      if (hurt > 0) {
        ctx.fillStyle = ink.danger;
        ctx.fillRect(0, 0, W, 2);
        ctx.fillRect(0, H - 2, W, 2);
        ctx.fillRect(0, 0, 2, H);
        ctx.fillRect(W - 2, 0, 2, H);
      }

      drawMinimap(ctx, ink, caster, cam, calls);

      if (message && messageAge < 2) {
        ctx.fillStyle = ink.bright;
        ctx.font = '8px "IBM Plex Mono", monospace';
        ctx.textAlign = "center";
        ctx.fillText(message, W / 2, 32);
        ctx.textAlign = "left";
      }
    };

    game.hud = function () {
      return "WAVE " + wave + " · " + (calls.length + remaining) + " INBOUND";
    };

    return game;
  }

  /* ---- 7. RETRY STORM ----------------------------------------------------

     Free-floating duplicate requests. Shooting one does not remove it — it
     splits into two smaller ones, because a retry of a retry is two retries.
     Only the smallest tier can actually be cleared, and only by ramming it
     with the idempotency key you are carrying. */
  function cabinetRetryStorm(random) {
    var game = { id: "retry-storm", score: 0, lives: 3, over: false };
    var ship, dupes, shots, wave, cooldown, invuln, message, messageAge;

    function spawnWave() {
      dupes = [];
      for (var i = 0; i < 2 + wave; i += 1) {
        var edge = random();
        dupes.push({
          x: edge < 0.5 ? 8 : W - 8,
          y: random() * H,
          vx: (random() - 0.5) * 34,
          vy: (random() - 0.5) * 34,
          tier: 3
        });
      }
    }

    function radius(tier) { return tier * 5; }

    game.reset = function () {
      game.score = 0;
      game.lives = 3;
      game.over = false;
      wave = 1;
      shots = [];
      cooldown = 0;
      invuln = 1.5;
      message = "";
      messageAge = 0;
      ship = { x: W / 2, y: H / 2, angle: -Math.PI / 2, vx: 0, vy: 0 };
      spawnWave();
    };

    game.update = function (dt, input) {
      if (game.over) return;
      messageAge += dt;
      cooldown -= dt;
      invuln = Math.max(0, invuln - dt);

      if (input.left) ship.angle -= 3 * dt;
      if (input.right) ship.angle += 3 * dt;
      if (input.up) {
        ship.vx += Math.cos(ship.angle) * 150 * dt;
        ship.vy += Math.sin(ship.angle) * 150 * dt;
      }
      // Drag, so the ship is steerable at this screen size. Frictionless drift
      // on a 320px board means one thrust and you are gone.
      ship.vx *= 0.99;
      ship.vy *= 0.99;
      ship.x = (ship.x + ship.vx * dt + W) % W;
      ship.y = (ship.y + ship.vy * dt + H) % H;

      if (input.fire && cooldown <= 0) {
        cooldown = 0.3;
        shots.push({
          x: ship.x, y: ship.y,
          vx: Math.cos(ship.angle) * 210,
          vy: Math.sin(ship.angle) * 210,
          life: 1.1
        });
      }

      shots.forEach(function (s) {
        s.x = (s.x + s.vx * dt + W) % W;
        s.y = (s.y + s.vy * dt + H) % H;
        s.life -= dt;
      });
      shots = shots.filter(function (s) { return s.life > 0; });

      dupes.forEach(function (d) {
        d.x = (d.x + d.vx * dt + W) % W;
        d.y = (d.y + d.vy * dt + H) % H;
      });

      // Shot hits: split rather than clear.
      var spawned = [];
      shots.forEach(function (s) {
        dupes.forEach(function (d) {
          if (d.hit) return;
          if (Math.hypot(d.x - s.x, d.y - s.y) > radius(d.tier)) return;
          d.hit = true;
          s.life = 0;
          if (d.tier > 1) {
            game.score += 5;
            for (var k = 0; k < 2; k += 1) {
              spawned.push({
                x: d.x, y: d.y,
                vx: (random() - 0.5) * 70,
                vy: (random() - 0.5) * 70,
                tier: d.tier - 1
              });
            }
            message = "RETRIED — NOW THERE ARE TWO";
            messageAge = 0;
          } else {
            // A tier-1 shot is just noise; it neither clears nor splits.
            d.hit = false;
            s.life = 0;
          }
        });
      });
      dupes = dupes.filter(function (d) { return !d.hit; }).concat(spawned);
      shots = shots.filter(function (s) { return s.life > 0; });

      // Ramming: the idempotency key. Only tier 1 is absorbed; anything bigger
      // is a collision and costs a retry.
      dupes.forEach(function (d) {
        if (Math.hypot(d.x - ship.x, d.y - ship.y) > radius(d.tier) + 4) return;
        if (d.tier === 1) {
          d.hit = true;
          game.score += 30;
          message = "KEYED — ABSORBED";
          messageAge = 0;
        } else if (invuln <= 0) {
          invuln = 1.5;
          game.lives -= 1;
          ship.x = W / 2; ship.y = H / 2; ship.vx = 0; ship.vy = 0;
          message = "COLLIDED";
          messageAge = 0;
          if (game.lives <= 0) game.over = true;
        }
      });
      dupes = dupes.filter(function (d) { return !d.hit; });

      if (!dupes.length && !game.over) {
        wave += 1;
        game.score += 80;
        message = "STORM CLEARED";
        messageAge = 0;
        spawnWave();
      }
    };

    game.draw = function (ctx, ink) {
      dupes.forEach(function (d) {
        ctx.fillStyle = d.tier === 1 ? ink.verify : ink.danger;
        var r = radius(d.tier);
        ctx.fillRect(d.x - r, d.y - r, r * 2, r * 2);
        ctx.fillStyle = ink.bg;
        ctx.fillRect(d.x - r + 2, d.y - r + 2, r * 2 - 4, r * 2 - 4);
      });

      ctx.fillStyle = ink.brass;
      shots.forEach(function (s) { ctx.fillRect(s.x - 1, s.y - 1, 2, 2); });

      // Ship: a chunky arrow, blinking while the collision grace lasts.
      if (invuln <= 0 || Math.floor(invuln * 12) % 2 === 0) {
        ctx.save();
        ctx.translate(ship.x, ship.y);
        ctx.rotate(ship.angle);
        ctx.fillStyle = ink.ink;
        ctx.fillRect(-4, -3, 8, 6);
        ctx.fillStyle = ink.verify;
        ctx.fillRect(4, -1, 4, 2);
        ctx.restore();
      }

      if (message && messageAge < 1.8) {
        ctx.fillStyle = ink.bright;
        ctx.font = '7px "IBM Plex Mono", monospace';
        ctx.textAlign = "center";
        ctx.fillText(message, W / 2, 32);
        ctx.textAlign = "left";
      }
    };

    game.hud = function () { return "STORM " + wave + " · " + dupes.length + " DUPES"; };
    return game;
  }

  /* ---- 8. DOUBLE SPEND ---------------------------------------------------

     Cross the settlement lanes to the ledger and back. Each lane carries
     charges moving at its own rate; touching one is the same request being
     charged twice, which is the one thing this product exists to prevent. */
  function cabinetDoubleSpend(random) {
    var game = { id: "double-spend", score: 0, lives: 3, over: false };
    var LANES = 6;
    var LANE_H = 26;
    var TOP = 44;
    var player, lanes, round, message, messageAge, invuln;

    function buildLanes() {
      lanes = [];
      for (var i = 0; i < LANES; i += 1) {
        var dir = i % 2 === 0 ? 1 : -1;
        var speed = (28 + random() * 26 + round * 7) * dir;
        var charges = [];
        var gap = 74 + random() * 34;
        for (var x = 0; x < W + gap; x += gap) {
          charges.push({ x: x, w: 22 + Math.floor(random() * 14) });
        }
        lanes.push({ y: TOP + i * LANE_H, speed: speed, charges: charges });
      }
    }

    game.reset = function () {
      game.score = 0;
      game.lives = 3;
      game.over = false;
      round = 1;
      message = "";
      messageAge = 0;
      invuln = 0;
      player = { x: W / 2, y: H - 12 };
      buildLanes();
    };

    game.update = function (dt, input) {
      if (game.over) return;
      messageAge += dt;
      invuln = Math.max(0, invuln - dt);

      // Stepped movement on a cooldown, not free gliding: the lanes are a
      // timing puzzle and analogue movement turns them into a smear.
      player.step = (player.step || 0) - dt;
      if (player.step <= 0) {
        var moved = false;
        if (input.left) { player.x -= 18; moved = true; }
        if (input.right) { player.x += 18; moved = true; }
        if (input.up) { player.y -= LANE_H; moved = true; }
        if (input.down) { player.y += LANE_H; moved = true; }
        if (moved) player.step = 0.12;
      }
      player.x = clamp(player.x, 6, W - 6);
      player.y = clamp(player.y, 6, H - 12);

      lanes.forEach(function (lane) {
        lane.charges.forEach(function (c) {
          c.x += lane.speed * dt;
          if (lane.speed > 0 && c.x > W + 30) c.x = -30;
          if (lane.speed < 0 && c.x < -30) c.x = W + 30;
        });
      });

      if (invuln <= 0) {
        lanes.forEach(function (lane) {
          if (Math.abs(player.y - lane.y) > 9) return;
          lane.charges.forEach(function (c) {
            if (player.x + 4 < c.x || player.x - 4 > c.x + c.w) return;
            invuln = 1.2;
            game.lives -= 1;
            message = "CHARGED TWICE";
            messageAge = 0;
            player.x = W / 2;
            player.y = H - 12;
            if (game.lives <= 0) game.over = true;
          });
        });
      }

      if (player.y < TOP - 10 && !game.over) {
        round += 1;
        game.score += 50 + round * 10;
        message = "SETTLED ONCE";
        messageAge = 0;
        player.x = W / 2;
        player.y = H - 12;
        buildLanes();
      }
    };

    game.draw = function (ctx, ink) {
      ctx.fillStyle = ink.verify;
      ctx.fillRect(0, TOP - 14, W, 1);
      ctx.font = '7px "IBM Plex Mono", monospace';
      ctx.fillStyle = ink.dim;
      ctx.fillText("LEDGER", 4, TOP - 17);

      lanes.forEach(function (lane) {
        ctx.fillStyle = ink.grid;
        ctx.fillRect(0, lane.y + 10, W, 1);
        lane.charges.forEach(function (c) {
          ctx.fillStyle = ink.danger;
          ctx.fillRect(c.x, lane.y - 7, c.w, 14);
          ctx.fillStyle = ink.bg;
          ctx.fillRect(c.x + 2, lane.y - 5, c.w - 4, 10);
          ctx.fillStyle = ink.danger;
          ctx.fillText("$", c.x + c.w / 2 - 2, lane.y + 3);
        });
      });

      if (invuln <= 0 || Math.floor(invuln * 12) % 2 === 0) {
        ctx.fillStyle = ink.verify;
        ctx.fillRect(player.x - 4, player.y - 5, 8, 10);
        ctx.fillStyle = ink.bg;
        ctx.fillRect(player.x - 2, player.y - 3, 4, 3);
      }

      if (message && messageAge < 1.6) {
        ctx.fillStyle = ink.bright;
        ctx.textAlign = "center";
        ctx.fillText(message, W / 2, 32);
        ctx.textAlign = "left";
      }
    };

    game.hud = function () { return "CROSSING " + round; };
    return game;
  }

  /* ---- 9. BACKPRESSURE ---------------------------------------------------

     Work arrives faster than it drains. Stack it into the queue; a completed
     row is a batch that drains. Reach the top and the queue has overflowed,
     which downstream will experience as your outage. */
  function cabinetBackpressure(random) {
    var COLS = 10;
    var ROWS = 15;
    var CELL = 12;
    var OX = (W - COLS * CELL) / 2;
    var OY = H - ROWS * CELL - 4;

    // Deliberately not the canonical seven: four shapes keep the piece table
    // short enough to read and the well solvable at this speed.
    var SHAPES = [
      [[0, 0], [1, 0], [0, 1], [1, 1]],
      [[0, 0], [1, 0], [2, 0], [3, 0]],
      [[0, 0], [0, 1], [1, 1], [2, 1]],
      [[0, 1], [1, 1], [1, 0], [2, 0]]
    ];

    var game = { id: "backpressure", score: 0, lives: 3, over: false };
    var grid, piece, drop, dropRate, moveCd, batches, message, messageAge;

    function newPiece() {
      piece = {
        cells: SHAPES[Math.floor(random() * SHAPES.length)].map(function (c) { return [c[0], c[1]]; }),
        x: 3,
        y: 0
      };
      if (collides(piece.cells, piece.x, piece.y)) {
        game.lives = 0;
        game.over = true;
        message = "QUEUE OVERFLOW";
        messageAge = 0;
      }
    }

    function collides(cells, px, py) {
      return cells.some(function (c) {
        var x = px + c[0];
        var y = py + c[1];
        if (x < 0 || x >= COLS || y >= ROWS) return true;
        if (y < 0) return false;
        return !!grid[y][x];
      });
    }

    function settle() {
      piece.cells.forEach(function (c) {
        var x = piece.x + c[0];
        var y = piece.y + c[1];
        if (y >= 0 && y < ROWS && x >= 0 && x < COLS) grid[y][x] = 1;
      });
      // Drain any full rows.
      var drained = 0;
      for (var y = ROWS - 1; y >= 0; y -= 1) {
        var full = grid[y].every(function (v) { return v; });
        if (!full) continue;
        grid.splice(y, 1);
        grid.unshift(new Array(COLS).fill(0));
        drained += 1;
        y += 1; // re-test the row that just shifted down into y
      }
      if (drained) {
        batches += drained;
        game.score += drained * drained * 40;
        dropRate = Math.max(0.12, dropRate - 0.015 * drained);
        message = drained > 1 ? "BATCH DRAINED ×" + drained : "BATCH DRAINED";
        messageAge = 0;
      }
      newPiece();
    }

    game.reset = function () {
      game.score = 0;
      game.lives = 3;
      game.over = false;
      grid = [];
      for (var y = 0; y < ROWS; y += 1) grid.push(new Array(COLS).fill(0));
      drop = 0;
      dropRate = 0.55;
      moveCd = 0;
      batches = 0;
      message = "";
      messageAge = 0;
      newPiece();
    };

    game.update = function (dt, input) {
      if (game.over) return;
      messageAge += dt;
      moveCd -= dt;

      if (moveCd <= 0) {
        if (input.left && !collides(piece.cells, piece.x - 1, piece.y)) { piece.x -= 1; moveCd = 0.11; }
        else if (input.right && !collides(piece.cells, piece.x + 1, piece.y)) { piece.x += 1; moveCd = 0.11; }
      }

      if (input.fire && !piece.rotated) {
        // Rotate about the piece's own bounding box, then reject the rotation
        // outright if it would overlap: wall kicks are more machinery than
        // this well needs.
        var turned = piece.cells.map(function (c) { return [-c[1] + 1, c[0]]; });
        if (!collides(turned, piece.x, piece.y)) piece.cells = turned;
        piece.rotated = true;
      }
      if (!input.fire) piece.rotated = false;

      drop -= dt * (input.down ? 8 : 1);
      if (drop <= 0) {
        drop = dropRate;
        if (collides(piece.cells, piece.x, piece.y + 1)) settle();
        else piece.y += 1;
      }
    };

    game.draw = function (ctx, ink) {
      ctx.fillStyle = ink.grid;
      ctx.fillRect(OX - 2, OY - 2, COLS * CELL + 4, ROWS * CELL + 4);
      ctx.fillStyle = ink.bg;
      ctx.fillRect(OX, OY, COLS * CELL, ROWS * CELL);

      for (var y = 0; y < ROWS; y += 1) {
        for (var x = 0; x < COLS; x += 1) {
          if (!grid[y][x]) continue;
          ctx.fillStyle = ink.dim;
          ctx.fillRect(OX + x * CELL, OY + y * CELL, CELL - 1, CELL - 1);
        }
      }
      if (piece) {
        ctx.fillStyle = ink.brass;
        piece.cells.forEach(function (c) {
          var x = piece.x + c[0];
          var y = piece.y + c[1];
          if (y < 0) return;
          ctx.fillRect(OX + x * CELL, OY + y * CELL, CELL - 1, CELL - 1);
        });
      }

      ctx.font = '7px "IBM Plex Mono", monospace';
      ctx.fillStyle = ink.dim;
      ctx.fillText("QUEUE DEPTH", 4, 34);
      ctx.fillStyle = ink.danger;
      ctx.fillText("OVERFLOW", 4, 44);
      ctx.fillStyle = ink.grid;
      ctx.fillRect(0, OY, OX - 4, 1);

      if (message && messageAge < 1.6) {
        ctx.fillStyle = ink.verify;
        ctx.textAlign = "center";
        ctx.fillText(message, W / 2, 30);
        ctx.textAlign = "left";
      }
    };

    game.hud = function () { return "BATCHES " + batches; };
    return game;
  }

  /* ---- 10. NONCE BURN ----------------------------------------------------

     A grid of nonces, each good exactly once and only until it expires. Move
     the cursor, burn the live ones. Burning a spent cell is a replay, and
     replays are what the nonce exists to stop. */
  function cabinetNonceBurn(random) {
    var COLS = 5;
    var ROWS = 4;
    var CELL = 46;
    var OX = (W - COLS * CELL) / 2;
    var OY = 42;

    var game = { id: "nonce-burn", score: 0, lives: 3, over: false };
    var cells, cursor, moveCd, fireLatch, spawnTimer, round, message, messageAge;

    function idx(cx, cy) { return cy * COLS + cx; }

    game.reset = function () {
      game.score = 0;
      game.lives = 3;
      game.over = false;
      cells = [];
      for (var i = 0; i < COLS * ROWS; i += 1) cells.push({ live: false, ttl: 0, spent: false });
      cursor = { x: 2, y: 1 };
      moveCd = 0;
      fireLatch = false;
      spawnTimer = 0.4;
      round = 1;
      message = "";
      messageAge = 0;
    };

    game.update = function (dt, input) {
      if (game.over) return;
      messageAge += dt;
      moveCd -= dt;

      if (moveCd <= 0) {
        var moved = false;
        if (input.left) { cursor.x -= 1; moved = true; }
        else if (input.right) { cursor.x += 1; moved = true; }
        else if (input.up) { cursor.y -= 1; moved = true; }
        else if (input.down) { cursor.y += 1; moved = true; }
        if (moved) moveCd = 0.13;
        cursor.x = clamp(cursor.x, 0, COLS - 1);
        cursor.y = clamp(cursor.y, 0, ROWS - 1);
      }

      if (input.fire && !fireLatch) {
        fireLatch = true;
        var cell = cells[idx(cursor.x, cursor.y)];
        if (cell.live) {
          cell.live = false;
          cell.spent = true;
          cell.ttl = 0;
          game.score += 15 + Math.floor(round * 2);
          message = "BURNED";
          messageAge = 0;
        } else {
          // Pressing an empty or spent cell is the replay.
          game.lives -= 1;
          message = cell.spent ? "REPLAY REJECTED" : "NO NONCE THERE";
          messageAge = 0;
          if (game.lives <= 0) game.over = true;
        }
      }
      if (!input.fire) fireLatch = false;

      spawnTimer -= dt;
      if (spawnTimer <= 0) {
        spawnTimer = Math.max(0.25, 1.1 - round * 0.05);
        var free = [];
        cells.forEach(function (c, i) { if (!c.live) free.push(i); });
        if (free.length) {
          var pick = free[Math.floor(random() * free.length)];
          cells[pick].live = true;
          cells[pick].spent = false;
          cells[pick].ttl = Math.max(1.1, 2.6 - round * 0.08);
          cells[pick].max = cells[pick].ttl;
        }
      }

      cells.forEach(function (c) {
        if (!c.live) return;
        c.ttl -= dt;
        if (c.ttl > 0) return;
        // An expired nonce is not a life lost — it is just gone. Losing a
        // retry to the clock would make the board unplayable at speed.
        c.live = false;
        c.spent = false;
        game.score = Math.max(0, game.score - 3);
      });

      round += dt * 0.25;
    };

    game.draw = function (ctx, ink) {
      ctx.font = '7px "IBM Plex Mono", monospace';
      ctx.fillStyle = ink.dim;
      ctx.fillText("BURN EACH NONCE ONCE — BEFORE IT EXPIRES", 6, 32);

      for (var y = 0; y < ROWS; y += 1) {
        for (var x = 0; x < COLS; x += 1) {
          var c = cells[idx(x, y)];
          var px = OX + x * CELL;
          var py = OY + y * CELL;
          ctx.fillStyle = ink.grid;
          ctx.fillRect(px, py, CELL - 6, CELL - 6);
          ctx.fillStyle = ink.bg;
          ctx.fillRect(px + 2, py + 2, CELL - 10, CELL - 10);

          if (c.live) {
            ctx.fillStyle = ink.brass;
            ctx.fillRect(px + 6, py + 6, CELL - 18, CELL - 18);
            // TTL as a draining bar rather than a ring: an arc at this size is
            // four grey pixels and reads as nothing.
            var frac = clamp(c.ttl / (c.max || 1), 0, 1);
            ctx.fillStyle = c.ttl < 0.6 ? ink.danger : ink.verify;
            ctx.fillRect(px + 4, py + CELL - 12, Math.floor((CELL - 14) * frac), 3);
          } else if (c.spent) {
            ctx.fillStyle = ink.dim;
            ctx.fillRect(px + 12, py + 16, CELL - 30, 3);
          }
        }
      }

      var cx = OX + cursor.x * CELL;
      var cy = OY + cursor.y * CELL;
      ctx.fillStyle = ink.verify;
      ctx.fillRect(cx - 2, cy - 2, CELL - 2, 2);
      ctx.fillRect(cx - 2, cy + CELL - 6, CELL - 2, 2);
      ctx.fillRect(cx - 2, cy - 2, 2, CELL - 2);
      ctx.fillRect(cx + CELL - 6, cy - 2, 2, CELL - 2);

      if (message && messageAge < 1.2) {
        ctx.fillStyle = ink.bright;
        ctx.textAlign = "center";
        ctx.fillText(message, W / 2, H - 8);
        ctx.textAlign = "left";
      }
    };

    game.hud = function () { return "TIER " + Math.floor(round); };
    return game;
  }

  /* ---- 11. KEY ROTATION --------------------------------------------------

     Collect every shard of the new signing key while the revocation sweepers
     walk the old one out of the maze. Touching a sweeper is being caught
     holding a key that is no longer valid. */
  function cabinetKeyRotation(random) {
    var MAZE = [
      "###############",
      "#......#......#",
      "#.####.#.####.#",
      "#.#..........##",
      "#.#.##.#.##.#.#",
      "#......#......#",
      "##.###.#.###.##",
      "#......#......#",
      "#.####.#.####.#",
      "#.....       .#",
      "#.###.##.##.#.#",
      "#......#......#",
      "###############"
    ];
    var CELL = 16;
    var COLS = MAZE[0].length;
    var ROWS = MAZE.length;
    var OX = (W - COLS * CELL) / 2;
    var OY = (H - ROWS * CELL) / 2 + 8;

    var game = { id: "key-rotation", score: 0, lives: 3, over: false };
    var walls, shards, player, sweepers, moveCd, rotation, message, messageAge, invuln;

    function wall(x, y) {
      if (x < 0 || y < 0 || x >= COLS || y >= ROWS) return true;
      return walls[y][x];
    }

    function layout() {
      walls = MAZE.map(function (row) {
        return row.split("").map(function (ch) { return ch === "#" ? 1 : 0; });
      });
      shards = [];
      for (var y = 0; y < ROWS; y += 1) {
        for (var x = 0; x < COLS; x += 1) {
          if (walls[y][x]) continue;
          if (x === 1 && y === 1) continue;
          shards.push({ x: x, y: y });
        }
      }
      player = { x: 1, y: 1 };
      sweepers = [
        { x: COLS - 2, y: ROWS - 2, dx: -1, dy: 0, step: 0 },
        { x: COLS - 2, y: 1, dx: 0, dy: 1, step: 0 },
        { x: 1, y: ROWS - 2, dx: 1, dy: 0, step: 0 }
      ];
    }

    game.reset = function () {
      game.score = 0;
      game.lives = 3;
      game.over = false;
      rotation = 1;
      moveCd = 0;
      invuln = 0;
      message = "";
      messageAge = 0;
      layout();
    };

    game.update = function (dt, input) {
      if (game.over) return;
      messageAge += dt;
      moveCd -= dt;
      invuln = Math.max(0, invuln - dt);

      if (moveCd <= 0) {
        var nx = player.x;
        var ny = player.y;
        if (input.left) nx -= 1;
        else if (input.right) nx += 1;
        else if (input.up) ny -= 1;
        else if (input.down) ny += 1;
        if ((nx !== player.x || ny !== player.y) && !wall(nx, ny)) {
          player.x = nx;
          player.y = ny;
          moveCd = 0.11;
        }
      }

      shards = shards.filter(function (s) {
        if (s.x !== player.x || s.y !== player.y) return true;
        game.score += 10;
        return false;
      });

      sweepers.forEach(function (s) {
        s.step -= dt;
        if (s.step > 0) return;
        s.step = Math.max(0.10, 0.24 - rotation * 0.02);
        // Head toward the player when the way is open, otherwise take any
        // turn that is not a reversal. Enough to be threatening; not enough
        // to be unfair on a maze this size.
        var options = [[1, 0], [-1, 0], [0, 1], [0, -1]].filter(function (d) {
          return !wall(s.x + d[0], s.y + d[1]);
        });
        if (!options.length) return;
        var forward = options.filter(function (d) {
          return !(d[0] === -s.dx && d[1] === -s.dy);
        });
        var pool = forward.length ? forward : options;
        pool.sort(function (a, b) {
          var da = Math.abs(s.x + a[0] - player.x) + Math.abs(s.y + a[1] - player.y);
          var db = Math.abs(s.x + b[0] - player.x) + Math.abs(s.y + b[1] - player.y);
          return da - db;
        });
        var choice = random() < 0.72 ? pool[0] : pool[Math.floor(random() * pool.length)];
        s.dx = choice[0];
        s.dy = choice[1];
        s.x += s.dx;
        s.y += s.dy;
      });

      if (invuln <= 0) {
        sweepers.forEach(function (s) {
          if (s.x !== player.x || s.y !== player.y) return;
          invuln = 1.4;
          game.lives -= 1;
          message = "REVOKED";
          messageAge = 0;
          player.x = 1;
          player.y = 1;
          if (game.lives <= 0) game.over = true;
        });
      }

      if (!shards.length && !game.over) {
        rotation += 1;
        game.score += 120;
        message = "KEY ROTATED";
        messageAge = 0;
        layout();
      }
    };

    game.draw = function (ctx, ink) {
      for (var y = 0; y < ROWS; y += 1) {
        for (var x = 0; x < COLS; x += 1) {
          if (!walls[y][x]) continue;
          ctx.fillStyle = ink.grid;
          ctx.fillRect(OX + x * CELL, OY + y * CELL, CELL - 1, CELL - 1);
        }
      }
      ctx.fillStyle = ink.brass;
      shards.forEach(function (s) {
        ctx.fillRect(OX + s.x * CELL + 6, OY + s.y * CELL + 6, 4, 4);
      });
      ctx.fillStyle = ink.danger;
      sweepers.forEach(function (s) {
        ctx.fillRect(OX + s.x * CELL + 2, OY + s.y * CELL + 2, CELL - 5, CELL - 5);
        ctx.fillStyle = ink.bg;
        ctx.fillRect(OX + s.x * CELL + 5, OY + s.y * CELL + 5, 3, 3);
        ctx.fillStyle = ink.danger;
      });
      if (invuln <= 0 || Math.floor(invuln * 12) % 2 === 0) {
        ctx.fillStyle = ink.verify;
        ctx.fillRect(OX + player.x * CELL + 3, OY + player.y * CELL + 3, CELL - 7, CELL - 7);
      }

      ctx.font = '7px "IBM Plex Mono", monospace';
      if (message && messageAge < 1.5) {
        ctx.fillStyle = ink.bright;
        ctx.textAlign = "center";
        ctx.fillText(message, W / 2, H - 3);
        ctx.textAlign = "left";
      }
    };

    game.hud = function () { return "ROTATION " + rotation + " · " + shards.length + " LEFT"; };
    return game;
  }

  /* ---- 12. TAIL LATENCY --------------------------------------------------

     A runner along the latency chart. The floor is p50 and it is fine. The
     spikes are the tail, and the tail is what your users actually experience,
     so the tail is the part you have to clear. */
  function cabinetTailLatency(random) {
    var game = { id: "tail-latency", score: 0, lives: 3, over: false };
    var GROUND = H - 40;
    var runner, spikes, speed, spawnIn, distance, message, messageAge, invuln, trace;

    game.reset = function () {
      game.score = 0;
      game.lives = 3;
      game.over = false;
      runner = { y: GROUND, vy: 0, onGround: true, duck: false };
      spikes = [];
      speed = 96;
      spawnIn = 1.1;
      distance = 0;
      invuln = 0;
      message = "";
      messageAge = 0;
      trace = [];
      for (var i = 0; i < W; i += 4) trace.push(GROUND + 8 + Math.sin(i * 0.11) * 3);
    };

    game.update = function (dt, input) {
      if (game.over) return;
      messageAge += dt;
      invuln = Math.max(0, invuln - dt);
      distance += speed * dt;
      speed = Math.min(230, 96 + distance * 0.012);
      game.score = Math.floor(distance / 10);

      if ((input.up || input.fire) && runner.onGround) {
        runner.vy = -232;
        runner.onGround = false;
      }
      runner.duck = !!input.down && runner.onGround;

      runner.vy += 640 * dt;
      runner.y += runner.vy * dt;
      if (runner.y >= GROUND) {
        runner.y = GROUND;
        runner.vy = 0;
        runner.onGround = true;
      }

      spawnIn -= dt;
      if (spawnIn <= 0) {
        spawnIn = Math.max(0.55, 1.35 - distance * 0.00035) + random() * 0.4;
        var tall = random() < 0.35;
        spikes.push({
          x: W + 10,
          h: tall ? 34 : 20,
          w: 8 + Math.floor(random() * 8),
          high: tall && random() < 0.5
        });
      }

      spikes.forEach(function (s) { s.x -= speed * dt; });
      spikes = spikes.filter(function (s) { return s.x > -20; });

      var rh = runner.duck ? 8 : 16;
      var ry = runner.y - rh;
      spikes.forEach(function (s) {
        if (invuln > 0) return;
        // A "high" spike hangs from above: it is the one you duck rather than
        // jump, so the two controls both have a reason to exist.
        // A standing runner occupies GROUND-16..GROUND and a ducking one
        // GROUND-8..GROUND, so a hanging spike has to reach below GROUND-16
        // to threaten the first and stop above GROUND-8 to spare the second.
        // At the original 26 it ended at GROUND-18 and cleared a standing
        // runner entirely, which made ducking decorative.
        var sy = s.high ? GROUND - 44 : GROUND - s.h;
        var sh = s.high ? 32 : s.h;
        if (s.x > 16 + 10 || s.x + s.w < 16 - 6) return;
        if (ry + rh < sy || ry > sy + sh) return;
        invuln = 1.2;
        game.lives -= 1;
        message = "TAIL EVENT";
        messageAge = 0;
        if (game.lives <= 0) game.over = true;
      });

      trace.push(GROUND + 8 + Math.sin(distance * 0.02) * 3 + random() * 2);
      if (trace.length > W / 4) trace.shift();
    };

    game.draw = function (ctx, ink) {
      ctx.fillStyle = ink.grid;
      ctx.fillRect(0, GROUND + 2, W, 1);

      // The p50 trace under the floor: flat, boring, and not the problem.
      ctx.fillStyle = ink.grid;
      trace.forEach(function (v, i) { ctx.fillRect(i * 4, v, 3, 1); });

      ctx.font = '7px "IBM Plex Mono", monospace';
      ctx.fillStyle = ink.dim;
      ctx.fillText("p50", 4, GROUND + 22);
      ctx.fillStyle = ink.danger;
      ctx.fillText("p99", 4, 32);

      spikes.forEach(function (s) {
        ctx.fillStyle = ink.danger;
        if (s.high) ctx.fillRect(s.x, GROUND - 44, s.w, 32);
        else ctx.fillRect(s.x, GROUND - s.h, s.w, s.h);
      });

      if (invuln <= 0 || Math.floor(invuln * 12) % 2 === 0) {
        var rh = runner.duck ? 8 : 16;
        ctx.fillStyle = ink.verify;
        ctx.fillRect(10, runner.y - rh, 12, rh);
        ctx.fillStyle = ink.bg;
        ctx.fillRect(13, runner.y - rh + 3, 3, 3);
      }

      if (message && messageAge < 1.4) {
        ctx.fillStyle = ink.bright;
        ctx.textAlign = "center";
        ctx.fillText(message, W / 2, 30);
        ctx.textAlign = "left";
      }
    };

    game.hud = function () { return "p99 " + Math.floor(speed) + "ms"; };
    return game;
  }

  /* ---- 13. COUNTERSIGN ---------------------------------------------------

     The round-based tactical shooter, which is the one console-era first
     person shape the other two cabinets do not cover: they are both endless
     waves, and this one is a bomb round. A rogue agent plants an *unsigned*
     action on one of two sites; the fuse is its TTL; you either eliminate the
     whole crew before the plant lands or you stand on the thing and hold the
     countersign key until the action is void again. Losing the fuse costs a
     retry and restarts the round, which is the genre's whole tension: the
     round is the unit, not the life.

     The buy phase is a caption rather than a menu. Five keys is not a shop,
     and a loadout line between rounds says the same joke in one frame. */
  function cabinetCountersign(random) {
    /* Open plan with pillars rather than sealed rooms. The crew chase by
       walking straight at you — there is no pathfinder in this file — so a
       map of small rooms joined by single doorways is one where half the
       hostiles spend the round pressed against a wall you cannot see. Every
       other row here runs clear from side to side, and the two floors are
       joined by two full-height openings. */
    var MAP = [
      "################",
      "#..............#",
      "#.==.#....#.##.#",
      "#....#....#....#",
      "#..............#",
      "####.######.####",
      "#..............#",
      "#....#....#....#",
      "#.##.#....#.==.#",
      "#..............#",
      "#..............#",
      "################"
    ];
    var caster = makeCaster(MAP);
    // The two plantable sites, in the corners the boundary markers stand in.
    var SITES = [
      { x: 2.5, y: 3.5, name: "SITE A" },
      { x: 13.5, y: 9.5, name: "SITE B" }
    ];
    // Hostile spawns, kept away from both sites so a round never opens with a
    // crew already standing on the thing they are about to plant.
    var SPAWNS = [
      { x: 8.5, y: 1.5 }, { x: 14.5, y: 1.5 },
      { x: 1.5, y: 10.5 }, { x: 14.5, y: 10.5 },
      { x: 8.5, y: 6.5 }
    ];
    var LOADOUTS = [
      "LOADOUT: ONE REVOCATION KEY. IT IS ENOUGH.",
      "BOUGHT: SECOND OPINION. NOBODY ASKED FOR IT.",
      "BOUGHT: FASTER AUDIT. SAME AUDITOR.",
      "BOUGHT: ARMOUR, BILLED AS A SUBSCRIPTION.",
      "BOUGHT: NOTHING. THE BUDGET IS THE POLICY."
    ];

    var PLANT_DELAY = 9;   // seconds of round time before the crew commits
    var FUSE = 32;         // TTL on the planted action
    var DEFUSE_TIME = 3.2; // hold-to-countersign

    var game = { id: "countersign", score: 0, lives: 3, over: false };
    var cam, crew, round, phase, timer, fuse, site, defuse, cooldown, kick,
      flash, hurt, message, messageAge, loadout, armour;

    function say(text) {
      message = text;
      messageAge = 0;
    }

    function startRound() {
      phase = "hunt";
      timer = PLANT_DELAY;
      fuse = FUSE;
      site = null;
      defuse = 0;
      crew = [];
      var count = Math.min(6, 2 + round);
      for (var i = 0; i < count; i += 1) {
        var spawn = SPAWNS[(i + round) % SPAWNS.length];
        crew.push({
          x: spawn.x + (random() - 0.5) * 0.4,
          y: spawn.y + (random() - 0.5) * 0.4,
          label: LOOSE_CALLS[Math.floor(random() * LOOSE_CALLS.length)],
          scale: 0.72,
          shootTimer: 1.5 + random() * 2,
          speed: 0.9 + round * 0.08,
          // Every hostile holds its own firing distance, so a crew arrives as
          // a firing line rather than as one clump on top of the player.
          standoff: 2.4 + random() * 1.6,
          dead: false
        });
      }
      // The player restarts each round at the post, the way a round-based
      // shooter resets the map rather than continuing from where the last one
      // ended. Continuing is a wave shooter, and the arcade has two already.
      cam = { x: 8.5, y: 4.5, dirX: 0, dirY: -1, angle: -Math.PI / 2 };
      armour = 100;
      loadout = LOADOUTS[round % LOADOUTS.length];
      say("ROUND " + round + " — " + loadout);
    }

    game.reset = function () {
      game.score = 0;
      game.lives = 3;
      game.over = false;
      round = 1;
      cooldown = 0;
      kick = 0;
      flash = 0;
      hurt = 0;
      messageAge = 0;
      startRound();
    };

    function alive() {
      return crew.filter(function (c) { return !c.dead; });
    }

    /* One radius, read by both the defuse and the "does this press shoot
       instead" test. They were a manhattan distance apart before, so there
       was a ring around the beacon where holding the key neither
       countersigned nor fired at anything. */
    function atSite() {
      if (phase !== "planted") return false;
      var dx = cam.x - site.x;
      var dy = cam.y - site.y;
      return dx * dx + dy * dy < 1.7;
    }

    function sees(from, to) {
      var dx = to.x - from.x;
      var dy = to.y - from.y;
      var dist = Math.sqrt(dx * dx + dy * dy);
      if (dist < 0.001) return 0;
      return caster.cast(from.x, from.y, dx / dist, dy / dist).dist >= dist - 0.2
        ? dist
        : 0;
    }

    function loseRound(reason) {
      game.lives -= 1;
      say(reason);
      if (game.lives <= 0) {
        game.over = true;
        return;
      }
      startRound();
    }

    game.update = function (dt, input) {
      if (game.over) return;
      messageAge += dt;
      kick = Math.max(0, kick - dt * 4);
      flash = Math.max(0, flash - dt * 6);
      hurt = Math.max(0, hurt - dt);
      cooldown = Math.max(0, cooldown - dt);

      var turn = 2.4 * dt;
      if (input.left) cam.angle -= turn;
      if (input.right) cam.angle += turn;
      cam.dirX = Math.cos(cam.angle);
      cam.dirY = Math.sin(cam.angle);

      var step = 2.2 * dt;
      if (input.up) casterMove(caster, cam, cam.dirX * step, cam.dirY * step);
      if (input.down) casterMove(caster, cam, -cam.dirX * step, -cam.dirY * step);

      // ---- the plant -------------------------------------------------
      if (phase === "hunt") {
        timer -= dt;
        if (!alive().length) {
          game.score += 100 + round * 20;
          round += 1;
          say("CREW ELIMINATED PRE-PLANT — ROUND WON");
          startRound();
          return;
        }
        if (timer <= 0) {
          phase = "planted";
          // Planted at whichever site the crew is closest to, so the round
          // reads as a decision the crew made rather than a coin flip.
          var planter = alive()[0];
          site = SITES[0];
          SITES.forEach(function (candidate) {
            var here = Math.abs(candidate.x - planter.x) + Math.abs(candidate.y - planter.y);
            var there = Math.abs(site.x - planter.x) + Math.abs(site.y - planter.y);
            if (here < there) site = candidate;
          });
          say("UNSIGNED ACTION PLANTED — " + site.name);
        }
      } else if (phase === "planted") {
        fuse -= dt;
        if (fuse <= 0) {
          loseRound("FUSE EXPIRED — THE ACTION EXECUTED UNSIGNED");
          return;
        }

        if (atSite() && input.fire) {
          // Holding fire on the site countersigns instead of shooting: one
          // key, and standing on the thing is the only place the meaning
          // changes, so it cannot be pressed by accident somewhere it matters.
          defuse += dt;
          if (defuse >= DEFUSE_TIME) {
            game.score += 250 + Math.floor(fuse) * 5;
            round += 1;
            say("COUNTERSIGNED WITH " + Math.ceil(fuse) + "s LEFT");
            startRound();
            return;
          }
        } else if (defuse > 0) {
          // Interrupting drains rather than resets: a defuse you had to break
          // off to shoot somebody is the round the genre is actually about.
          defuse = Math.max(0, defuse - dt * 0.6);
        }
      }

      // ---- shooting --------------------------------------------------
      if (input.fire && !atSite() && cooldown <= 0) {
        cooldown = 0.22;
        kick = 1;
        flash = 1;
        var hit = casterHitscan(cam, alive(), caster);
        if (hit) {
          hit.sprite.dead = true;
          game.score += 25;
        }
      }

      // ---- the crew --------------------------------------------------
      alive().forEach(function (c) {
        var target = phase === "planted" ? { x: site.x, y: site.y } : cam;
        var dx = target.x - c.x;
        var dy = target.y - c.y;
        var dist = Math.sqrt(dx * dx + dy * dy) || 1;
        // Defending the plant rather than chasing: once it is down the crew
        // wants the fuse to run, so they hold the site instead of the player.
        //
        // And they stop at their standoff instead of walking into you. A
        // hostile at arm's length is not a harder shot, it is an impossible
        // one: the hitscan cone is a fixed angle, so the closer a target
        // stands the less of it that cone covers, and a crew that hugged the
        // player made the cabinet unwinnable rather than difficult.
        var hold = phase === "planted" ? 1.4 : c.standoff;
        var drive = dist > hold ? 1 : dist < hold - 0.6 ? -0.7 : 0;
        if (drive) {
          casterMove(caster, c, (dx / dist) * c.speed * drive * dt, (dy / dist) * c.speed * drive * dt);
        }

        c.shootTimer -= dt;
        if (c.shootTimer > 0) return;
        c.shootTimer = 1.4 + random() * 1.6;
        var range = sees(c, cam);
        if (!range || range > 9) return;
        // Range falloff, so a corridor duel is winnable and a point-blank
        // surprise is not.
        if (random() > 0.5 - range * 0.03) return;
        hurt = 0.5;
        // Armour, not an instant retry: a round-based shooter that spent a
        // life per bullet ended the run before the first plant ever landed.
        armour -= 18 + Math.floor(random() * 14);
        if (armour > 0) return;
        game.lives -= 1;
        if (game.lives <= 0) {
          game.over = true;
          return;
        }
        say("TAKEN — RETRY, SAME ROUND");
        startRound();
      });
    };

    game.draw = function (ctx, ink) {
      var sprites = alive().map(function (c) {
        return { x: c.x, y: c.y, color: ink.danger, label: c.label, scale: c.scale };
      });
      if (phase === "planted") {
        sprites.push({
          x: site.x,
          y: site.y,
          color: fuse < 8 && Math.floor(fuse * 4) % 2 === 0 ? ink.bright : ink.brass,
          label: "UNSIGNED",
          scale: 0.42,
          lift: 40
        });
      }

      var zbuf = casterDrawWalls(ctx, ink, caster, cam);
      casterDrawSprites(ctx, ink, cam, sprites, zbuf);
      casterDrawWeapon(ctx, ink, kick, flash);
      drawMinimap(ctx, ink, caster, cam, sprites);

      if (hurt > 0) {
        ctx.fillStyle = ink.danger;
        ctx.fillRect(0, 0, W, 3);
        ctx.fillRect(0, H - 3, W, 3);
      }

      ctx.font = '8px "IBM Plex Mono", monospace';
      ctx.fillStyle = ink.dim;
      ctx.fillText("CREW " + alive().length, 4, 10);
      ctx.fillStyle = ink.grid;
      ctx.fillRect(4, H - 10, 72, 6);
      ctx.fillStyle = armour > 35 ? ink.verify : ink.danger;
      ctx.fillRect(4, H - 10, Math.max(0, Math.floor(armour * 0.72)), 6);

      if (phase === "planted") {
        ctx.fillStyle = fuse < 8 ? ink.danger : ink.brass;
        ctx.fillText("TTL " + fuse.toFixed(1) + "s", 4, 20);
        if (defuse > 0) {
          var width = Math.floor((defuse / DEFUSE_TIME) * 120);
          ctx.fillStyle = ink.grid;
          ctx.fillRect(W / 2 - 60, H - 52, 120, 6);
          ctx.fillStyle = ink.verify;
          ctx.fillRect(W / 2 - 60, H - 52, width, 6);
          ctx.textAlign = "center";
          ctx.fillStyle = ink.verify;
          ctx.fillText("COUNTERSIGNING", W / 2, H - 56);
          ctx.textAlign = "left";
        }
      } else {
        ctx.fillStyle = ink.verify;
        ctx.fillText("PLANT IN " + Math.max(0, timer).toFixed(1) + "s", 4, 20);
      }

      if (messageAge < 2.6) {
        ctx.textAlign = "center";
        ctx.fillStyle = ink.bright;
        ctx.fillText(message, W / 2, 34);
        ctx.textAlign = "left";
      }
    };

    game.hud = function () {
      return "ROUND " + round + " · ARMOUR " + Math.max(0, armour);
    };
    return game;
  }

  /* ---- 14. HAPPY PATH ----------------------------------------------------

     The side-scrolling platformer, which is the console shape everything else
     in the roster is measured against. You are a request, running left to
     right along the path the demo took. The gaps are the cases nobody wrote,
     the regressions patrol the platforms, and landing on one squashes it —
     touching one at ground level does not. The flag at the end is a release.

     Level geometry is generated once per stage from the seeded generator, so
     a stage is the same stage every time it is played at the same seed, which
     is what makes a platformer learnable rather than merely random. */
  function cabinetHappyPath(random) {
    var GROUND = H - 34;
    var GRAVITY = 520;
    var JUMP = -196;
    var RUN = 96;

    var game = { id: "happy-path", score: 0, lives: 3, over: false };
    var runner, camX, stage, platforms, gaps, hazards, coins, flagX,
      message, messageAge, clock;

    function say(text) {
      message = text;
      messageAge = 0;
    }

    function buildStage() {
      platforms = [];
      gaps = [];
      hazards = [];
      coins = [];
      var x = 60;
      var length = 1400 + stage * 260;

      while (x < length) {
        // A gap, then a run of solid path, then the furniture standing on it.
        var gapWidth = 26 + Math.floor(random() * (16 + stage * 4));
        gaps.push({ x: x, w: gapWidth });
        x += gapWidth;

        var runWidth = 110 + Math.floor(random() * 120);
        if (random() < 0.55) {
          var ledgeX = x + 20 + random() * (runWidth - 60);
          var ledgeY = GROUND - 34 - Math.floor(random() * 30);
          platforms.push({ x: ledgeX, y: ledgeY, w: 46 + random() * 30 });
          coins.push({ x: ledgeX + 18, y: ledgeY - 12, taken: false });
        }
        if (random() < 0.75) {
          hazards.push({
            x: x + 30 + random() * (runWidth - 50),
            y: GROUND - 10,
            dir: random() < 0.5 ? -1 : 1,
            span: 24 + random() * 30,
            home: 0,
            dead: false
          });
        }
        coins.push({ x: x + runWidth / 2, y: GROUND - 24, taken: false });
        x += runWidth;
      }
      hazards.forEach(function (h) { h.home = h.x; });
      flagX = x + 40;
      // A stage clock, because a platformer without one is a place to stand
      // rather than a level. Generous, and it scales with the stage length.
      clock = 55 + stage * 6;
      camX = 0;
      runner = { x: 30, y: GROUND - 12, vy: 0, w: 8, h: 12, onGround: true, face: 1 };
    }

    function solidAt(x) {
      // The floor exists everywhere except inside a gap. One pass, because a
      // platformer that asks "am I over a hole" on every frame for every body
      // is the cheapest thing in the file and the one that has to be right.
      for (var i = 0; i < gaps.length; i += 1) {
        if (x > gaps[i].x && x < gaps[i].x + gaps[i].w) return false;
      }
      return true;
    }

    game.reset = function () {
      game.score = 0;
      game.lives = 3;
      game.over = false;
      stage = 1;
      messageAge = 0;
      buildStage();
      say("STAGE 1 — SHIP IT");
    };

    function fall() {
      game.lives -= 1;
      if (game.lives <= 0) {
        game.over = true;
        return;
      }
      say("FELL THROUGH AN UNHANDLED CASE");
      runner.x = Math.max(30, runner.x - 90);
      runner.y = GROUND - 40;
      runner.vy = 0;
      // Nudge out of the hole rather than respawning back into it.
      while (!solidAt(runner.x) && runner.x > 20) runner.x -= 6;
    }

    game.update = function (dt, input) {
      if (game.over) return;
      messageAge += dt;
      clock -= dt;
      if (clock <= 0) {
        game.lives -= 1;
        if (game.lives <= 0) {
          game.over = true;
          return;
        }
        buildStage();
        say("TIMED OUT — THE RELEASE SLIPPED");
        return;
      }

      if (input.left) { runner.x -= RUN * dt; runner.face = -1; }
      if (input.right) { runner.x += RUN * dt; runner.face = 1; }
      if (runner.x < 4) runner.x = 4;

      if (input.fire && runner.onGround) {
        runner.vy = JUMP;
        runner.onGround = false;
      }

      runner.vy += GRAVITY * dt;
      runner.y += runner.vy * dt;
      runner.onGround = false;

      // Ledges first: a ledge over a gap is the only thing keeping the player
      // out of it, so it has to win the collision.
      platforms.forEach(function (p) {
        if (runner.x + 4 < p.x || runner.x - 4 > p.x + p.w) return;
        if (runner.vy < 0) return;
        if (runner.y >= p.y - 12 && runner.y <= p.y + 6) {
          runner.y = p.y - 12;
          runner.vy = 0;
          runner.onGround = true;
        }
      });

      if (!runner.onGround && runner.y >= GROUND - 12 && solidAt(runner.x)) {
        runner.y = GROUND - 12;
        runner.vy = 0;
        runner.onGround = true;
      }

      if (runner.y > H + 20) {
        fall();
        return;
      }

      hazards.forEach(function (h) {
        if (h.dead) return;
        h.x += h.dir * 26 * dt;
        if (h.x < h.home - h.span || h.x > h.home + h.span) h.dir *= -1;
        if (!solidAt(h.x)) h.dir *= -1;

        var dx = Math.abs(h.x - runner.x);
        var dy = h.y - runner.y;
        if (dx > 8 || dy < 0 || dy > 16) return;
        if (runner.vy > 40) {
          // Stomped: descending onto it is a fix, walking into it is not.
          h.dead = true;
          runner.vy = JUMP * 0.7;
          game.score += 15;
          return;
        }
        game.lives -= 1;
        if (game.lives <= 0) {
          game.over = true;
          return;
        }
        say("REGRESSION HIT THE REQUEST");
        runner.x = Math.max(20, runner.x - 40);
      });

      coins.forEach(function (c) {
        if (c.taken) return;
        if (Math.abs(c.x - runner.x) > 8 || Math.abs(c.y - runner.y) > 12) return;
        c.taken = true;
        game.score += 5;
      });

      if (runner.x > flagX) {
        stage += 1;
        game.score += 120;
        buildStage();
        say("STAGE " + stage + " — THE PATH GOT LONGER");
      }

      camX = clamp(runner.x - 96, 0, Math.max(0, flagX - W + 60));
    };

    game.draw = function (ctx, ink) {
      ctx.fillStyle = ink.bg;
      ctx.fillRect(0, 0, W, H);

      // Parallax skyline: one band at a third of the scroll rate, drawn as
      // blocks because a skyline at this palette is blocks.
      ctx.fillStyle = ink.grid;
      for (var b = -1; b < 14; b += 1) {
        var bx = b * 40 - (camX * 0.3) % 40;
        ctx.fillRect(bx, GROUND - 60 - (b % 3) * 14, 26, 60 + (b % 3) * 14);
      }

      ctx.fillStyle = ink.wall[2];
      for (var x = 0; x < W; x += 4) {
        if (!solidAt(x + camX)) continue;
        ctx.fillRect(x, GROUND, 4, H - GROUND);
      }
      ctx.fillStyle = ink.wall[1];
      for (var t = 0; t < W; t += 4) {
        if (!solidAt(t + camX)) continue;
        ctx.fillRect(t, GROUND, 4, 3);
      }

      platforms.forEach(function (p) {
        var px = p.x - camX;
        if (px < -80 || px > W) return;
        ctx.fillStyle = ink.brass;
        ctx.fillRect(px, p.y, p.w, 4);
        ctx.fillStyle = ink.wall[2];
        ctx.fillRect(px, p.y + 4, p.w, 3);
      });

      coins.forEach(function (c) {
        if (c.taken) return;
        var cx = c.x - camX;
        if (cx < -8 || cx > W) return;
        ctx.fillStyle = ink.bright;
        ctx.fillRect(cx - 2, c.y - 3, 4, 6);
      });

      hazards.forEach(function (h) {
        if (h.dead) return;
        var hx = h.x - camX;
        if (hx < -12 || hx > W) return;
        ctx.fillStyle = ink.danger;
        ctx.fillRect(hx - 5, h.y - 6, 10, 10);
        ctx.fillStyle = ink.bg;
        ctx.fillRect(hx - 3, h.y - 4, 2, 2);
        ctx.fillRect(hx + 1, h.y - 4, 2, 2);
      });

      var fx = flagX - camX;
      if (fx < W + 20) {
        ctx.fillStyle = ink.verify;
        ctx.fillRect(fx, GROUND - 44, 2, 44);
        ctx.fillRect(fx + 2, GROUND - 44, 14, 9);
      }

      var rx = Math.floor(runner.x - camX);
      var ry = Math.floor(runner.y);
      ctx.fillStyle = ink.verify;
      ctx.fillRect(rx - 4, ry - 12, 8, 12);
      ctx.fillStyle = ink.bg;
      ctx.fillRect(rx + (runner.face > 0 ? 0 : -3), ry - 9, 3, 2);

      ctx.font = '8px "IBM Plex Mono", monospace';
      ctx.fillStyle = clock < 10 ? ink.danger : ink.dim;
      ctx.fillText(Math.max(0, Math.ceil(clock)) + "s", W - 30, 12);
      if (messageAge < 2.4) {
        ctx.textAlign = "center";
        ctx.fillStyle = ink.bright;
        ctx.fillText(message, W / 2, 22);
        ctx.textAlign = "left";
      }
    };

    game.hud = function () {
      return "STAGE " + stage + " · " + Math.max(0, Math.ceil(clock)) + "s TO SHIP";
    };
    return game;
  }

  /* ---- 15. LEAST PRIVILEGE -----------------------------------------------

     The top-down room-at-a-time adventure. A three-by-three grid of rooms,
     one screen each, no scrolling between them: you leave through a doorway
     and the next room is simply there, which is what this genre did before
     hardware could scroll a world. Keys are scoped permits, the locked room
     is the vault, and the blade is a revocation — swing it at a daemon and
     the grant it was holding goes away.

     Rooms are generated from the seeded generator but their doorways are not:
     a doorway that generated itself into a wall makes a room a dead end the
     player cannot tell from a puzzle. Every adjacency gets a real opening. */
  function cabinetLeastPrivilege(random) {
    var COLS = 15;
    var ROWS = 11;
    var TILE = 16;
    var OX = (W - COLS * TILE) / 2;
    var OY = 28;
    var GRID = 3; // rooms per side

    var game = { id: "least-privilege", score: 0, lives: 3, over: false };
    var rooms, here, hero, blade, keys, floorNo, message, messageAge, hurt;

    function say(text) {
      message = text;
      messageAge = 0;
    }

    function roomAt(rx, ry) {
      return rooms[ry * GRID + rx];
    }

    function buildFloor() {
      rooms = [];
      for (var ry = 0; ry < GRID; ry += 1) {
        for (var rx = 0; rx < GRID; rx += 1) {
          var tiles = [];
          for (var y = 0; y < ROWS; y += 1) {
            var row = [];
            for (var x = 0; x < COLS; x += 1) {
              var edge = x === 0 || y === 0 || x === COLS - 1 || y === ROWS - 1;
              // Interior pillars, never on the centre lines the doorways open
              // onto, so a room can always be crossed both ways.
              var pillar =
                !edge &&
                x % 3 === 0 &&
                y % 3 === 0 &&
                y !== (ROWS - 1) / 2 &&
                x !== (COLS - 1) / 2 &&
                random() < 0.55;
              row.push(edge || pillar ? 1 : 0);
            }
            tiles.push(row);
          }
          // Doorways on every edge that has a neighbour.
          if (ry > 0) tiles[0][(COLS - 1) / 2] = 0;
          if (ry < GRID - 1) tiles[ROWS - 1][(COLS - 1) / 2] = 0;
          if (rx > 0) tiles[(ROWS - 1) / 2][0] = 0;
          if (rx < GRID - 1) tiles[(ROWS - 1) / 2][COLS - 1] = 0;

          var isStart = rx === 0 && ry === 0;
          var isVault = rx === GRID - 1 && ry === GRID - 1;
          var daemons = [];
          var count = isStart ? 0 : 1 + Math.floor(random() * 2) + Math.floor(floorNo / 2);
          for (var d = 0; d < Math.min(4, count); d += 1) {
            daemons.push({
              x: 3 + Math.floor(random() * (COLS - 6)),
              y: 2 + Math.floor(random() * (ROWS - 4)),
              dx: random() < 0.5 ? -1 : 1,
              dy: 0,
              cool: random(),
              dead: false
            });
          }
          rooms.push({
            tiles: tiles,
            daemons: daemons,
            // A key in most rooms that are neither the start nor the vault.
            // Which rooms is a roll; *how many* is not — see below.
            key: !isStart && !isVault && random() < 0.6,
            vault: isVault,
            opened: false,
            cleared: false
          });
        }
      }

      // The vault wants two permits and `keys` resets with the floor, so a
      // floor that rolled fewer than two is a floor with no way out — about
      // one in fifty at p=0.6 over seven rooms, which is often enough that a
      // player would meet it and read it as the game being broken. Top the
      // supply up rather than raising p: the distribution is the texture, the
      // floor being finishable is the contract.
      var carriers = rooms.filter(function (r) { return !r.vault && r !== rooms[0]; });
      var supply = carriers.filter(function (r) { return r.key; });
      while (supply.length < 2 && supply.length < carriers.length) {
        var empty = carriers.filter(function (r) { return !r.key; });
        var pick = empty[Math.floor(random() * empty.length)];
        pick.key = true;
        supply.push(pick);
      }
      here = { x: 0, y: 0 };
      hero = { x: 7, y: 5, face: 0 };
      keys = 0;
      blade = { active: 0, dir: 0 };
    }

    function solid(tx, ty) {
      var room = roomAt(here.x, here.y);
      if (ty < 0 || tx < 0 || ty >= ROWS || tx >= COLS) return true;
      return room.tiles[ty][tx] === 1;
    }

    game.reset = function () {
      game.score = 0;
      game.lives = 3;
      game.over = false;
      floorNo = 1;
      hurt = 0;
      messageAge = 0;
      buildFloor();
      say("FLOOR 1 — FIND TWO PERMITS, THEN THE VAULT");
    };

    function enter(dx, dy) {
      here.x = clamp(here.x + dx, 0, GRID - 1);
      here.y = clamp(here.y + dy, 0, GRID - 1);
      // Arrive just inside the opposite doorway.
      if (dx > 0) hero.x = 1;
      if (dx < 0) hero.x = COLS - 2;
      if (dy > 0) hero.y = 1;
      if (dy < 0) hero.y = ROWS - 2;
    }

    var moveCool = 0;

    game.update = function (dt, input) {
      if (game.over) return;
      messageAge += dt;
      hurt = Math.max(0, hurt - dt);
      moveCool -= dt;
      blade.active = Math.max(0, blade.active - dt);

      var room = roomAt(here.x, here.y);

      // Grid-stepped movement on a cooldown, not free pixels: this genre's
      // rooms are read as tiles, and a body that stands between two of them
      // makes every collision above ambiguous.
      if (moveCool <= 0) {
        var mx = 0;
        var my = 0;
        if (input.left) mx = -1;
        else if (input.right) mx = 1;
        else if (input.up) my = -1;
        else if (input.down) my = 1;

        if (mx || my) {
          blade.dir = mx ? (mx > 0 ? 1 : 3) : (my > 0 ? 2 : 0);
          hero.face = blade.dir;
          var nx = hero.x + mx;
          var ny = hero.y + my;
          moveCool = 0.11;

          if (nx < 0 || nx >= COLS || ny < 0 || ny >= ROWS) {
            enter(mx, my);
          } else if (!solid(nx, ny)) {
            hero.x = nx;
            hero.y = ny;
          }
        }
      }

      if (input.fire && blade.active <= 0) {
        blade.active = 0.18;
        var bx = hero.x + (blade.dir === 1 ? 1 : blade.dir === 3 ? -1 : 0);
        var by = hero.y + (blade.dir === 2 ? 1 : blade.dir === 0 ? -1 : 0);
        room.daemons.forEach(function (d) {
          if (d.dead) return;
          if (d.x !== bx || d.y !== by) return;
          d.dead = true;
          game.score += 20;
        });
      }

      room.daemons.forEach(function (d) {
        if (d.dead) return;
        d.cool -= dt;
        if (d.cool <= 0) {
          d.cool = 0.34;
          // Drifts toward the player on one axis, bounces off walls on the
          // other. Cheap, and it reads as a patrol that has noticed you.
          var towardX = hero.x > d.x ? 1 : hero.x < d.x ? -1 : 0;
          var towardY = hero.y > d.y ? 1 : hero.y < d.y ? -1 : 0;
          var stepX = random() < 0.6 ? towardX : d.dx;
          var stepY = stepX ? 0 : towardY;
          if (!solid(d.x + stepX, d.y + stepY)) {
            d.x += stepX;
            d.y += stepY;
          } else {
            d.dx *= -1;
          }
        }
        if (d.x === hero.x && d.y === hero.y && hurt <= 0) {
          hurt = 1.1;
          game.lives -= 1;
          if (game.lives <= 0) {
            game.over = true;
            return;
          }
          say("A DAEMON TOOK A GRANT BACK");
        }
      });

      if (!room.daemons.some(function (d) { return !d.dead; }) && !room.cleared) {
        room.cleared = true;
        game.score += 30;
      }

      if (room.key && room.cleared) {
        room.key = false;
        keys += 1;
        game.score += 40;
        say("SCOPED PERMIT " + keys + " — EXPIRES ON USE");
      }

      if (room.vault && !room.opened) {
        if (keys >= 2) {
          room.opened = true;
          keys -= 2;
          floorNo += 1;
          game.score += 200;
          buildFloor();
          say("VAULT SIGNED — FLOOR " + floorNo);
        } else if (messageAge > 1.6) {
          say("VAULT NEEDS TWO PERMITS. YOU HAVE " + keys + ".");
        }
      }
    };

    game.draw = function (ctx, ink) {
      ctx.fillStyle = ink.bg;
      ctx.fillRect(0, 0, W, H);
      var room = roomAt(here.x, here.y);

      for (var y = 0; y < ROWS; y += 1) {
        for (var x = 0; x < COLS; x += 1) {
          var px = OX + x * TILE;
          var py = OY + y * TILE;
          if (room.tiles[y][x]) {
            // Walls in the brightest wall shade with a dark mortar line. At
            // wall[2] against a grid-coloured floor checker the two sat one
            // step apart in value and the room read as a single chequerboard
            // with no walls in it — the doorways especially disappeared.
            ctx.fillStyle = room.vault ? ink.brass : ink.wall[1];
            ctx.fillRect(px, py, TILE, TILE);
            ctx.fillStyle = ink.bg;
            ctx.fillRect(px + TILE - 2, py, 2, TILE);
            ctx.fillRect(px, py + TILE - 2, TILE, 2);
          } else if ((x + y) % 2 === 0) {
            // Floor: a pip rather than a filled cell, so the pattern says
            // "tiles" without competing with the walls for brightness.
            ctx.fillStyle = ink.grid;
            ctx.fillRect(px + TILE / 2 - 1, py + TILE / 2 - 1, 2, 2);
          }
        }
      }

      if (room.key && room.cleared === false) {
        ctx.fillStyle = ink.dim;
        ctx.font = '7px "IBM Plex Mono", monospace';
        ctx.textAlign = "center";
        ctx.fillText("CLEAR THE ROOM TO RELEASE THE PERMIT", W / 2, OY + ROWS * TILE + 10);
        ctx.textAlign = "left";
      }

      room.daemons.forEach(function (d) {
        if (d.dead) return;
        ctx.fillStyle = ink.danger;
        ctx.fillRect(OX + d.x * TILE + 2, OY + d.y * TILE + 2, TILE - 4, TILE - 4);
        ctx.fillStyle = ink.bg;
        ctx.fillRect(OX + d.x * TILE + 5, OY + d.y * TILE + 6, 2, 2);
        ctx.fillRect(OX + d.x * TILE + 9, OY + d.y * TILE + 6, 2, 2);
      });

      var hx = OX + hero.x * TILE;
      var hy = OY + hero.y * TILE;
      ctx.fillStyle = hurt > 0 && Math.floor(hurt * 12) % 2 === 0 ? ink.bright : ink.verify;
      ctx.fillRect(hx + 3, hy + 2, TILE - 6, TILE - 4);

      if (blade.active > 0) {
        var bx = hx + (blade.dir === 1 ? TILE : blade.dir === 3 ? -TILE : 0);
        var by = hy + (blade.dir === 2 ? TILE : blade.dir === 0 ? -TILE : 0);
        ctx.fillStyle = ink.bright;
        ctx.fillRect(bx + 5, by + 5, TILE - 10, TILE - 10);
      }

      ctx.font = '8px "IBM Plex Mono", monospace';
      ctx.fillStyle = ink.dim;
      ctx.fillText("PERMITS " + keys, 4, 12);
      ctx.fillText("ROOM " + (here.x + 1) + "," + (here.y + 1), W - 62, 12);
      if (messageAge < 2.4) {
        ctx.textAlign = "center";
        ctx.fillStyle = ink.bright;
        ctx.fillText(message, W / 2, 22);
        ctx.textAlign = "left";
      }
    };

    game.hud = function () {
      return "FLOOR " + floorNo + " · PERMITS " + keys;
    };
    return game;
  }

  /* ---- 16. ESCALATION ----------------------------------------------------

     The turn-based console RPG, reduced to the one screen it is actually
     remembered as: a menu, a monster, and two numbers going down. The party
     is you; the encounters are the things a request meets on its way through
     a trust plane, and they escalate because that is what an unreviewed
     request does. Four verbs, one key to commit them, and a damage roll the
     player can feel the shape of after two fights.

     Menu-driven rather than twitch, which also makes this the one cabinet on
     the roster a person can play badly and still finish a thought during. */
  function cabinetEscalation(random) {
    var ACTIONS = [
      { name: "REQUEST", note: "a plain call. cheap, honest, small." },
      { name: "ESCALATE", note: "more privilege than you need. it shows." },
      { name: "REVOKE", note: "take a grant back. hurts what holds one." },
      { name: "ROTATE", note: "new keys. heals you. wastes a turn." }
    ];
    var FOES = [
      { name: "POLICY DAEMON", hp: 40, hit: 7 },
      { name: "RATE LIMITER", hp: 55, hit: 9 },
      { name: "AUDIT BACKLOG", hp: 70, hit: 11 },
      { name: "BUDGET OWNER", hp: 90, hit: 14 },
      { name: "THE COMMITTEE", hp: 120, hit: 17 }
    ];

    var game = { id: "escalation", score: 0, lives: 3, over: false };
    var hero, foe, tier, pick, phase, timer, log, shake, held;

    function nextFoe() {
      var base = FOES[Math.min(FOES.length - 1, tier - 1)];
      var over = Math.max(0, tier - FOES.length);
      foe = {
        name: base.name + (over ? " +" + over : ""),
        hp: base.hp + over * 26,
        max: base.hp + over * 26,
        hit: base.hit + over * 3,
        guard: 0
      };
    }

    function write(line) {
      log.unshift(line);
      if (log.length > 3) log.pop();
    }

    game.reset = function () {
      game.score = 0;
      game.lives = 3;
      game.over = false;
      tier = 1;
      pick = 0;
      phase = "choose";
      timer = 0;
      shake = 0;
      held = false;
      log = [];
      hero = { hp: 60, max: 60, mp: 5 };
      nextFoe();
      write("A " + foe.name + " BLOCKS THE CALL.");
    };

    function heroTurn() {
      var action = ACTIONS[pick];
      var roll = Math.floor(random() * 6);

      if (action.name === "REQUEST") {
        var dmg = 8 + roll;
        foe.hp -= dmg;
        write("REQUEST LANDS FOR " + dmg + ".");
      } else if (action.name === "ESCALATE") {
        // High roll, real cost: the whole point of the verb is that it works
        // and that using it is visible afterwards.
        var big = 18 + roll * 2;
        foe.hp -= big;
        hero.hp -= 6;
        game.score += 5;
        write("ESCALATED FOR " + big + ". THE AUDIT NOTICED.");
      } else if (action.name === "REVOKE") {
        var cut = 10 + roll;
        foe.hp -= cut;
        foe.guard = 2;
        write("REVOKED A GRANT. -" + cut + ", AND IT IS SLOWER.");
      } else {
        if (hero.mp <= 0) {
          write("NO KEYS LEFT TO ROTATE. TURN WASTED.");
        } else {
          hero.mp -= 1;
          hero.hp = Math.min(hero.max, hero.hp + 18);
          write("ROTATED KEYS. +18, AND ONE FEWER SPARE.");
        }
      }

      if (foe.hp <= 0) {
        game.score += 60 + tier * 20;
        tier += 1;
        hero.mp += 1;
        hero.hp = Math.min(hero.max, hero.hp + 10);
        nextFoe();
        write("CLEARED. NEXT: " + foe.name + ".");
        phase = "choose";
        return;
      }
      phase = "foe";
      timer = 0.7;
    }

    function foeTurn() {
      if (foe.guard > 0) {
        foe.guard -= 1;
        write(foe.name + " IS STILL RE-READING THE POLICY.");
        phase = "choose";
        return;
      }
      var dmg = Math.floor(foe.hit * (0.7 + random() * 0.6));
      hero.hp -= dmg;
      shake = 0.3;
      write(foe.name + " DENIES YOU FOR " + dmg + ".");
      if (hero.hp <= 0) {
        game.lives -= 1;
        if (game.lives <= 0) {
          game.over = true;
          return;
        }
        hero.hp = hero.max;
        hero.mp = Math.max(1, hero.mp);
        write("THE CALL DIED. RETRY WITH THE SAME PARTY.");
      }
      phase = "choose";
    }

    game.update = function (dt, input) {
      if (game.over) return;
      shake = Math.max(0, shake - dt);

      if (phase === "foe") {
        timer -= dt;
        if (timer <= 0) foeTurn();
        return;
      }

      // Edge-triggered menu: a held key that repeated every frame would run
      // the cursor down the list and commit something the player never chose.
      var pressed = input.up || input.down || input.fire;
      if (!pressed) {
        held = false;
        return;
      }
      if (held) return;
      held = true;

      if (input.up) pick = (pick + ACTIONS.length - 1) % ACTIONS.length;
      else if (input.down) pick = (pick + 1) % ACTIONS.length;
      else heroTurn();
    };

    game.draw = function (ctx, ink) {
      ctx.fillStyle = ink.bg;
      ctx.fillRect(0, 0, W, H);

      var jolt = shake > 0 ? (Math.floor(shake * 40) % 2 ? 2 : -2) : 0;

      // The foe, as a slab with a face. A sprite this size at this palette is
      // read as a silhouette anyway.
      var fw = 74;
      var fh = 54;
      ctx.fillStyle = ink.danger;
      ctx.fillRect(W / 2 - fw / 2 + jolt, 34, fw, fh);
      ctx.fillStyle = ink.bg;
      ctx.fillRect(W / 2 - 22 + jolt, 50, 12, 8);
      ctx.fillRect(W / 2 + 10 + jolt, 50, 12, 8);
      ctx.fillRect(W / 2 - 18 + jolt, 72, 36, 4);

      ctx.font = '8px "IBM Plex Mono", monospace';
      ctx.textAlign = "center";
      ctx.fillStyle = ink.ink;
      ctx.fillText(foe.name, W / 2, 26);
      ctx.textAlign = "left";

      // Foe health as a bar, because a number nobody can read at 8px is not a
      // health bar.
      ctx.fillStyle = ink.grid;
      ctx.fillRect(W / 2 - 50, 94, 100, 5);
      ctx.fillStyle = ink.danger;
      ctx.fillRect(W / 2 - 50, 94, Math.max(0, Math.floor((foe.hp / foe.max) * 100)), 5);

      // Log panel.
      ctx.fillStyle = ink.grid;
      ctx.fillRect(6, 104, W - 12, 34);
      ctx.fillStyle = ink.ink;
      for (var i = 0; i < log.length; i += 1) {
        ctx.fillText(log[i], 10, 115 + i * 10);
      }

      // Menu.
      ctx.fillStyle = ink.grid;
      ctx.fillRect(6, 144, 150, 52);
      ACTIONS.forEach(function (action, index) {
        var y = 156 + index * 12;
        if (index === pick) {
          ctx.fillStyle = ink.brass;
          ctx.fillRect(8, y - 8, 146, 11);
          ctx.fillStyle = ink.bg;
        } else {
          ctx.fillStyle = ink.ink;
        }
        ctx.fillText(action.name, 14, y);
      });
      ctx.fillStyle = ink.dim;
      ctx.fillText(ACTIONS[pick].note, 10, 208);

      // Party panel.
      ctx.fillStyle = ink.grid;
      ctx.fillRect(164, 144, W - 170, 52);
      ctx.fillStyle = ink.ink;
      ctx.fillText("YOU", 170, 156);
      ctx.fillStyle = ink.grid;
      ctx.fillRect(170, 162, 120, 5);
      ctx.fillStyle = ink.verify;
      ctx.fillRect(170, 162, Math.max(0, Math.floor((hero.hp / hero.max) * 120)), 5);
      ctx.fillStyle = ink.dim;
      ctx.fillText("HP " + Math.max(0, hero.hp) + "/" + hero.max, 170, 178);
      ctx.fillText("SPARE KEYS " + hero.mp, 170, 190);

      ctx.fillStyle = ink.dim;
      ctx.fillText(phase === "foe" ? "…THINKING" : "↑ ↓ CHOOSE · SPACE COMMIT", 10, 228);
    };

    game.hud = function () {
      return "TIER " + tier + " · HP " + Math.max(0, hero.hp);
    };
    return game;
  }

  /* ---- 17. ARBITRATION ---------------------------------------------------

     The one-on-one fighter. Two parties to a dispute, two health bars, a
     round timer, and best of three. The genre's real subject is spacing, so
     that is what this models: a strike has reach and recovery, a block eats
     most of a hit but not the chip, and the opponent reads your distance
     rather than rolling dice.

     Five keys means no motion inputs and no special moves. What is left is
     the part of a fighter that survives at 8 bits: get in, hit, get out. */
  function cabinetArbitration(random) {
    var FLOOR = H - 42;
    var REACH = 26;

    var game = { id: "arbitration", score: 0, lives: 3, over: false };
    var you, foe, round, wins, losses, clock, freeze, message, messageAge, tier;

    function say(text) {
      message = text;
      messageAge = 0;
    }

    function fighter(x, face) {
      return {
        x: x,
        vy: 0,
        y: FLOOR,
        face: face,
        hp: 100,
        strike: 0,   // >0 while the arm is out
        recover: 0,  // >0 while it cannot strike again
        block: false,
        stun: 0,
        landed: false
      };
    }

    function newRound() {
      you = fighter(80, 1);
      foe = fighter(240, -1);
      clock = 45;
      freeze = 0.8;
      say("ROUND " + round + " — ARGUE");
    }

    game.reset = function () {
      game.score = 0;
      game.lives = 3;
      game.over = false;
      round = 1;
      wins = 0;
      losses = 0;
      tier = 1;
      messageAge = 0;
      newRound();
    };

    function hitCheck(attacker, defender) {
      if (attacker.strike <= 0 || attacker.landed) return;
      var gap = Math.abs(attacker.x - defender.x);
      var facing = (defender.x - attacker.x) * attacker.face > 0;
      if (!facing || gap > REACH) return;
      attacker.landed = true;
      // Blocking is worth having and is not a wall: chip damage keeps a
      // turtling opponent from being a stalemate, which is the failure mode
      // this genre spent a decade fixing.
      var dmg = defender.block ? 3 : 9 + Math.floor(random() * 4);
      defender.hp -= dmg;
      defender.stun = defender.block ? 0.12 : 0.3;
      defender.x += attacker.face * (defender.block ? 3 : 7);
      if (attacker === you) game.score += defender.block ? 1 : 4;
    }

    function endRound(playerWon) {
      if (playerWon) {
        wins += 1;
        game.score += 80;
        say("AWARD TO YOU");
      } else {
        losses += 1;
        say("AWARD AGAINST YOU");
      }
      if (wins >= 2) {
        tier += 1;
        wins = 0;
        losses = 0;
        round = 1;
        game.score += 150;
        say("MATCH WON — NEXT ARBITER");
        newRound();
        return;
      }
      if (losses >= 2) {
        game.lives -= 1;
        wins = 0;
        losses = 0;
        round = 1;
        if (game.lives <= 0) {
          game.over = true;
          return;
        }
        say("MATCH LOST — RETRY");
        newRound();
        return;
      }
      round += 1;
      newRound();
    }

    function stepBody(body, dt) {
      body.strike = Math.max(0, body.strike - dt);
      body.recover = Math.max(0, body.recover - dt);
      body.stun = Math.max(0, body.stun - dt);
      if (body.strike <= 0) body.landed = false;
      body.y += body.vy * dt;
      if (body.y < FLOOR) body.vy += 900 * dt;
      if (body.y >= FLOOR) {
        body.y = FLOOR;
        body.vy = 0;
      }
      body.x = clamp(body.x, 16, W - 16);
    }

    game.update = function (dt, input) {
      if (game.over) return;
      messageAge += dt;
      if (freeze > 0) {
        freeze -= dt;
        return;
      }

      clock -= dt;
      you.face = foe.x >= you.x ? 1 : -1;
      foe.face = you.x >= foe.x ? 1 : -1;

      // ---- you --------------------------------------------------------
      you.block = !!input.down && you.y >= FLOOR;
      if (!you.stun && !you.block) {
        var speed = 74 * dt;
        if (input.left) you.x -= speed;
        if (input.right) you.x += speed;
        if (input.up && you.y >= FLOOR) you.vy = -260;
        if (input.fire && you.recover <= 0) {
          you.strike = 0.14;
          you.recover = 0.34;
        }
      }

      // ---- the arbiter -------------------------------------------------
      // A distance machine, not a random one: it closes when far, strikes in
      // range, blocks when your arm is out, and backs off after trading. The
      // tier turns the dials rather than adding new behaviour.
      var gap = Math.abs(foe.x - you.x);
      var aggression = 0.5 + tier * 0.12;
      foe.block = you.strike > 0 && gap < REACH + 8 && random() < 0.6;
      if (!foe.stun && !foe.block) {
        var pace = (56 + tier * 9) * dt;
        if (gap > REACH - 4) foe.x += foe.face * pace;
        else if (gap < REACH - 16) foe.x -= foe.face * pace * 0.8;
        if (gap <= REACH && foe.recover <= 0 && random() < aggression * dt * 8) {
          foe.strike = 0.14;
          foe.recover = 0.42 - tier * 0.02;
        }
      }

      stepBody(you, dt);
      stepBody(foe, dt);
      hitCheck(you, foe);
      hitCheck(foe, you);

      if (foe.hp <= 0) {
        freeze = 1;
        endRound(true);
        return;
      }
      if (you.hp <= 0) {
        freeze = 1;
        endRound(false);
        return;
      }
      if (clock <= 0) {
        freeze = 1;
        endRound(you.hp >= foe.hp);
      }
    };

    function drawFighter(ctx, ink, body, color) {
      var x = Math.floor(body.x);
      var y = Math.floor(body.y);
      ctx.fillStyle = body.stun > 0 ? ink.bright : color;
      ctx.fillRect(x - 7, y - 34, 14, 22);          // torso
      ctx.fillRect(x - 5, y - 12, 4, 12);           // legs
      ctx.fillRect(x + 1, y - 12, 4, 12);
      ctx.fillRect(x - 5, y - 44, 10, 10);          // head
      if (body.block) {
        ctx.fillStyle = ink.verify;
        ctx.fillRect(x + (body.face > 0 ? 6 : -10), y - 34, 4, 20);
      } else if (body.strike > 0) {
        ctx.fillStyle = ink.bright;
        ctx.fillRect(x + (body.face > 0 ? 6 : -24), y - 32, 18, 4);
      }
    }

    game.draw = function (ctx, ink) {
      ctx.fillStyle = ink.bg;
      ctx.fillRect(0, 0, W, H);

      // Crowd band and floor. The crowd is committee members, which is the
      // only joke this cabinet needs in the background.
      ctx.fillStyle = ink.grid;
      for (var c = 0; c < 20; c += 1) {
        ctx.fillRect(c * 17 + 3, 58 + (c % 3) * 3, 11, 14);
      }
      ctx.fillStyle = ink.wall[2];
      ctx.fillRect(0, FLOOR, W, H - FLOOR);
      ctx.fillStyle = ink.wall[1];
      ctx.fillRect(0, FLOOR, W, 3);

      drawFighter(ctx, ink, foe, ink.danger);
      drawFighter(ctx, ink, you, ink.verify);

      // Health bars, drained from the centre outward the way this genre does.
      ctx.fillStyle = ink.grid;
      ctx.fillRect(8, 12, 132, 8);
      ctx.fillRect(W - 140, 12, 132, 8);
      ctx.fillStyle = ink.verify;
      var yw = Math.max(0, Math.floor((you.hp / 100) * 132));
      ctx.fillRect(8 + (132 - yw), 12, yw, 8);
      ctx.fillStyle = ink.danger;
      ctx.fillRect(W - 140, 12, Math.max(0, Math.floor((foe.hp / 100) * 132)), 8);

      ctx.font = '8px "IBM Plex Mono", monospace';
      ctx.textAlign = "center";
      ctx.fillStyle = ink.brass;
      ctx.fillText(String(Math.max(0, Math.ceil(clock))), W / 2, 20);
      ctx.fillStyle = ink.dim;
      ctx.fillText("YOU " + wins + " — " + losses + " ARBITER", W / 2, 32);
      if (messageAge < 2 || freeze > 0) {
        ctx.fillStyle = ink.bright;
        ctx.fillText(message, W / 2, 48);
      }
      ctx.textAlign = "left";
    };

    game.hud = function () {
      return "ARBITER " + tier + " · ROUND " + round;
    };
    return game;
  }

  /* ---- 18. THROUGHPUT ----------------------------------------------------

     The top-down circuit racer. Whole track on one screen, no scrolling: this
     is the layout the genre used before hardware could rotate a road, and it
     is the one that still reads at 320x240.

     The track is a bitmap of drivable cells. Off it you do not crash, you get
     slow — which is the honest version of the metaphor: exceeding your
     throughput budget does not stop the work, it just makes everything take
     longer, and the rivals do not wait. Checkpoints exist so that reversing
     over the line cannot farm laps. */
  function cabinetThroughput(random) {
    var TRACK = [
      "################################",
      "################################",
      "##............................##",
      "##............................##",
      "##............................##",
      "##...######################...##",
      "##...######################...##",
      "##...######################...##",
      "##...######################...##",
      "##...######################...##",
      "##............................##",
      "##............................##",
      "##............................##",
      "################################",
      "################################"
    ];
    // Drivable is '.', wall/infield is '#': inverted from the raycaster maps
    // on purpose — a circuit is a ring of road drawn inside a solid, and
    // writing it the other way round makes the shape unreadable in source.
    var CELL = 10;
    var COLS = TRACK[0].length;
    var ROWS = TRACK.length;
    var OX = (W - COLS * CELL) / 2;
    var OY = (H - ROWS * CELL) / 2 + 6;
    // Four quadrant checkpoints, cleared in order, running anticlockwise from
    // the bottom straight. The line sits on the bottom straight behind the
    // first of them, so a lap is a lap rather than a reversed dab over it.
    var GATES = [
      { x: 22, y: 11 }, { x: 28, y: 7 }, { x: 10, y: 3 }, { x: 3, y: 7 }
    ];
    var LINE_CELL = { x: 8, y: 11 };

    var game = { id: "throughput", score: 0, lives: 3, over: false };
    var car, rivals, lap, gate, best, clock, budget, message, messageAge;

    function drivable(px, py) {
      var cx = Math.floor((px - OX) / CELL);
      var cy = Math.floor((py - OY) / CELL);
      if (cx < 0 || cy < 0 || cx >= COLS || cy >= ROWS) return false;
      return TRACK[cy].charAt(cx) === ".";
    }

    function cellCentre(cx, cy) {
      return { x: OX + cx * CELL + CELL / 2, y: OY + cy * CELL + CELL / 2 };
    }

    function say(text) {
      message = text;
      messageAge = 0;
    }

    game.reset = function () {
      game.score = 0;
      game.lives = 3;
      game.over = false;
      lap = 1;
      gate = 0;
      best = 0;
      clock = 0;
      // A time budget rather than a field that can lap you. Arcade racers ran
      // on an extend clock for a reason: a rival marginally faster than a
      // clean lap means perfect driving still loses, which is not a race, it
      // is a countdown wearing a car.
      budget = 30;
      messageAge = 0;
      var start = cellCentre(LINE_CELL.x, LINE_CELL.y);
      car = { x: start.x, y: start.y, angle: 0, speed: 0 };
      rivals = [];
      for (var i = 0; i < 3; i += 1) {
        var seat = cellCentre(LINE_CELL.x + 1 + i, LINE_CELL.y + (i % 2 ? -1 : 0));
        rivals.push({
          x: seat.x,
          y: seat.y,
          gate: 0,
          lap: 1,
          pace: 34 + i * 6 + random() * 6
        });
      }
      say("GREEN — HOLD YOUR BUDGET");
    };

    game.update = function (dt, input) {
      if (game.over) return;
      messageAge += dt;
      clock += dt;
      budget -= dt;

      if (budget <= 0) {
        game.lives -= 1;
        if (game.lives <= 0) {
          game.over = true;
          return;
        }
        var restart = cellCentre(LINE_CELL.x, LINE_CELL.y);
        car = { x: restart.x, y: restart.y, angle: 0, speed: 0 };
        gate = 0;
        clock = 0;
        budget = 30;
        say("BUDGET EXHAUSTED — BACK TO THE LINE");
        return;
      }

      if (input.left) car.angle -= 2.6 * dt;
      if (input.right) car.angle += 2.6 * dt;

      var onRoad = drivable(car.x, car.y);
      var ceiling = onRoad ? 92 : 34;
      if (input.up) car.speed += 118 * dt;
      else car.speed -= 46 * dt;
      if (input.down) car.speed -= 150 * dt;
      car.speed = clamp(car.speed, 0, ceiling);

      var nx = car.x + Math.cos(car.angle) * car.speed * dt;
      var ny = car.y + Math.sin(car.angle) * car.speed * dt;
      // The infield and the outer field are the same rule: you may leave the
      // road, you may not leave the board.
      if (nx > OX && nx < OX + COLS * CELL) car.x = nx;
      if (ny > OY && ny < OY + ROWS * CELL) car.y = ny;

      var target = cellCentre(GATES[gate].x, GATES[gate].y);
      if (Math.abs(car.x - target.x) < 22 && Math.abs(car.y - target.y) < 22) {
        gate += 1;
        game.score += 10;
        // Capped: without a ceiling a clean driver banks minutes by lap four
        // and the clock stops meaning anything for the rest of the run.
        budget = Math.min(45, budget + 3.5);
        if (gate >= GATES.length) {
          gate = 0;
          lap += 1;
          game.score += 100;
          budget = Math.min(45, budget + 6);
          if (!best || clock < best) best = clock;
          say("LAP " + lap + " — " + clock.toFixed(1) + "s · EXTENDED");
          clock = 0;
        }
      }

      rivals.forEach(function (r) {
        // Rivals drive the gate ring rather than the road: an opponent that
        // needs its own physics is an opponent that gets stuck on the infield
        // while the player watches, which is worse than one that cheats.
        var to = cellCentre(GATES[r.gate].x, GATES[r.gate].y);
        var dx = to.x - r.x;
        var dy = to.y - r.y;
        var dist = Math.sqrt(dx * dx + dy * dy) || 1;
        r.x += (dx / dist) * r.pace * dt;
        r.y += (dy / dist) * r.pace * dt;
        if (dist < 12) {
          r.gate = (r.gate + 1) % GATES.length;
          if (r.gate === 0) r.lap += 1;
        }

        // Rivals are traffic, not a timer: touching one scrubs your speed,
        // which costs budget, which is the only currency here.
        if (Math.abs(r.x - car.x) < 8 && Math.abs(r.y - car.y) < 8) {
          car.speed *= 0.35;
        }
      });
    };

    game.draw = function (ctx, ink) {
      ctx.fillStyle = ink.bg;
      ctx.fillRect(0, 0, W, H);

      // The whole board is painted, not just the road: an unpainted verge is
      // the same black as the void outside the board, so a car that left the
      // circuit appeared to be driving on nothing. And the road's two checker
      // shades have to be two shades — grid and wall[3] are the same colour in
      // this palette, so the surface came out flat.
      for (var y = 0; y < ROWS; y += 1) {
        for (var x = 0; x < COLS; x += 1) {
          var px = OX + x * CELL;
          var py = OY + y * CELL;
          var road = TRACK[y].charAt(x) === ".";
          ctx.fillStyle = road
            ? ((x + y) % 2 === 0 ? ink.wall[1] : ink.wall[2])
            : ink.wall[3];
          ctx.fillRect(px, py, CELL, CELL);
        }
      }

      // Start/finish line: a checker band across the bottom straight.
      var line = cellCentre(LINE_CELL.x, LINE_CELL.y);
      ctx.fillStyle = ink.ink;
      for (var s = 0; s < 8; s += 1) {
        ctx.fillRect(line.x - 4 + (s % 2) * 4, line.y - 16 + s * 4, 4, 4);
      }

      var next = cellCentre(GATES[gate].x, GATES[gate].y);
      ctx.fillStyle = ink.verify;
      ctx.fillRect(next.x - 8, next.y - 1, 16, 2);
      ctx.fillRect(next.x - 1, next.y - 8, 2, 16);

      rivals.forEach(function (r) {
        ctx.fillStyle = ink.danger;
        ctx.fillRect(Math.floor(r.x) - 3, Math.floor(r.y) - 3, 7, 7);
      });

      ctx.fillStyle = drivable(car.x, car.y) ? ink.bright : ink.brass;
      ctx.fillRect(Math.floor(car.x) - 4, Math.floor(car.y) - 4, 9, 9);
      ctx.fillStyle = ink.bg;
      ctx.fillRect(
        Math.floor(car.x + Math.cos(car.angle) * 3) - 1,
        Math.floor(car.y + Math.sin(car.angle) * 3) - 1,
        2,
        2
      );

      ctx.font = '8px "IBM Plex Mono", monospace';
      ctx.fillStyle = ink.dim;
      ctx.fillText("LAP " + lap, 6, 12);
      ctx.fillText(clock.toFixed(1) + "s", 6, 22);
      ctx.fillStyle = budget < 8 ? ink.danger : ink.verify;
      ctx.fillText("BUDGET " + Math.ceil(budget) + "s", W / 2 - 34, 12);
      ctx.fillStyle = ink.dim;
      if (best) ctx.fillText("BEST " + best.toFixed(1) + "s", W - 74, 12);
      if (!drivable(car.x, car.y)) {
        ctx.fillStyle = ink.danger;
        ctx.fillText("OVER BUDGET — THROTTLED", W - 148, 22);
      }
      if (messageAge < 2.2) {
        ctx.textAlign = "center";
        ctx.fillStyle = ink.bright;
        ctx.fillText(message, W / 2, H - 8);
        ctx.textAlign = "left";
      }
    };

    game.hud = function () {
      return "LAP " + lap + " · BUDGET " + Math.max(0, Math.ceil(budget)) + "s";
    };
    return game;
  }

  /* ---- 19. SIDE CHANNEL --------------------------------------------------

     The stealth cabinet. Observers sweep vision cones across a floor of
     server aisles; you are a request that is not supposed to be readable,
     moving between the racks to reach the egress. Being seen does not kill
     you outright — it fills a suspicion meter, and a full meter is the loss,
     because that is what a side channel actually is: not one observation, but
     enough of them.

     Crouching (the fire key, held) halves your speed and makes you unreadable
     at anything but point-blank range. */
  function cabinetSideChannel(random) {
    var CELL = 16;
    var COLS = 20;
    var ROWS = 13;
    var OX = 0;
    var OY = 24;

    var game = { id: "side-channel", score: 0, lives: 3, over: false };
    var racks, watchers, you, exitCell, token, suspicion, floorNo,
      message, messageAge;

    function say(text) {
      message = text;
      messageAge = 0;
    }

    function blocked(px, py) {
      var cx = Math.floor((px - OX) / CELL);
      var cy = Math.floor((py - OY) / CELL);
      if (cx < 0 || cy < 0 || cx >= COLS || cy >= ROWS) return true;
      return racks[cy][cx] === 1;
    }

    function buildFloor() {
      racks = [];
      for (var y = 0; y < ROWS; y += 1) {
        var row = [];
        for (var x = 0; x < COLS; x += 1) {
          // Aisles: solid rows of rack with a gap punched through, so cover
          // exists and so does a way past it.
          var isRack = y % 3 === 1 && x > 1 && x < COLS - 2 && (x % 7 !== 3);
          row.push(isRack ? 1 : 0);
        }
        racks.push(row);
      }
      watchers = [];
      var count = Math.min(5, 2 + floorNo);
      for (var w = 0; w < count; w += 1) {
        watchers.push({
          x: OX + (4 + w * 4) * CELL + CELL / 2,
          y: OY + ((w % 3) * 3 + 2) * CELL + CELL / 2,
          angle: random() * Math.PI * 2,
          sweep: (random() < 0.5 ? -1 : 1) * (0.5 + floorNo * 0.08)
        });
      }
      you = { x: OX + CELL, y: OY + CELL / 2 + CELL * (ROWS - 1) };
      exitCell = { x: COLS - 1, y: 0 };
      token = { x: OX + CELL * (COLS - 3), y: OY + CELL * (ROWS - 2), taken: false };
      suspicion = 0;
    }

    game.reset = function () {
      game.score = 0;
      game.lives = 3;
      game.over = false;
      floorNo = 1;
      messageAge = 0;
      buildFloor();
      say("FLOOR 1 — TAKE THE TOKEN, THEN EGRESS");
    };

    game.update = function (dt, input) {
      if (game.over) return;
      messageAge += dt;

      var crouched = !!input.fire;
      var speed = (crouched ? 34 : 68) * dt;
      var nx = you.x + (input.right ? speed : 0) - (input.left ? speed : 0);
      var ny = you.y + (input.down ? speed : 0) - (input.up ? speed : 0);
      if (!blocked(nx, you.y)) you.x = nx;
      if (!blocked(you.x, ny)) you.y = ny;

      var seen = false;
      watchers.forEach(function (w) {
        // Wrapped, not accumulated: an unbounded heading is what made the
        // cone test below wrong in the first place, and it is also a float
        // that grows all run.
        w.angle = (w.angle + w.sweep * dt) % (Math.PI * 2);
        var dx = you.x - w.x;
        var dy = you.y - w.y;
        var dist = Math.sqrt(dx * dx + dy * dy);
        var range = crouched ? 26 : 84;
        if (dist > range) return;
        var toward = Math.atan2(dy, dx);
        if (Math.abs(angleDelta(toward, w.angle)) > 0.42) return;
        // Line of sight is sampled along the ray rather than assumed: a rack
        // between you and a watcher is the entire point of the racks.
        for (var t = 6; t < dist; t += 5) {
          if (blocked(w.x + Math.cos(toward) * t, w.y + Math.sin(toward) * t)) return;
        }
        seen = true;
      });

      if (seen) {
        suspicion = Math.min(1, suspicion + dt * 0.45);
        if (suspicion >= 1) {
          game.lives -= 1;
          if (game.lives <= 0) {
            game.over = true;
            return;
          }
          say("OBSERVED ENOUGH TIMES TO BE A CHANNEL");
          buildFloor();
          return;
        }
      } else {
        suspicion = Math.max(0, suspicion - dt * 0.22);
      }

      if (!token.taken && Math.abs(you.x - token.x) < 10 && Math.abs(you.y - token.y) < 10) {
        token.taken = true;
        game.score += 60;
        say("TOKEN LIFTED — NOW LEAVE");
      }

      var exitX = OX + exitCell.x * CELL + CELL / 2;
      var exitY = OY + exitCell.y * CELL + CELL / 2;
      if (token.taken && Math.abs(you.x - exitX) < 12 && Math.abs(you.y - exitY) < 12) {
        floorNo += 1;
        game.score += 150;
        buildFloor();
        say("EGRESS CLEAN — FLOOR " + floorNo);
      }
    };

    game.draw = function (ctx, ink) {
      ctx.fillStyle = ink.bg;
      ctx.fillRect(0, 0, W, H);

      for (var y = 0; y < ROWS; y += 1) {
        for (var x = 0; x < COLS; x += 1) {
          if (!racks[y][x]) continue;
          ctx.fillStyle = ink.wall[2];
          ctx.fillRect(OX + x * CELL, OY + y * CELL, CELL, CELL);
          ctx.fillStyle = ink.wall[3];
          ctx.fillRect(OX + x * CELL + 2, OY + y * CELL + 3, CELL - 4, 2);
          ctx.fillRect(OX + x * CELL + 2, OY + y * CELL + 9, CELL - 4, 2);
        }
      }

      // Cones as stepped wedges: three arcs of blocks, which is how a cone
      // was drawn before anyone had an alpha channel to spare.
      watchers.forEach(function (w) {
        ctx.fillStyle = ink.grid;
        for (var t = 8; t < 84; t += 6) {
          for (var a = -0.42; a <= 0.42; a += 0.14) {
            var px = w.x + Math.cos(w.angle + a) * t;
            var py = w.y + Math.sin(w.angle + a) * t;
            if (blocked(px, py)) continue;
            ctx.fillRect(Math.floor(px) - 1, Math.floor(py) - 1, 3, 3);
          }
        }
        ctx.fillStyle = ink.danger;
        ctx.fillRect(Math.floor(w.x) - 4, Math.floor(w.y) - 4, 8, 8);
      });

      var exitX = OX + exitCell.x * CELL;
      var exitY = OY + exitCell.y * CELL;
      ctx.fillStyle = token.taken ? ink.verify : ink.grid;
      ctx.fillRect(exitX + 2, exitY + 2, CELL - 4, CELL - 4);

      if (!token.taken) {
        ctx.fillStyle = ink.brass;
        ctx.fillRect(Math.floor(token.x) - 4, Math.floor(token.y) - 4, 8, 8);
      }

      ctx.fillStyle = ink.verify;
      ctx.fillRect(Math.floor(you.x) - 4, Math.floor(you.y) - 5, 8, 10);

      ctx.fillStyle = ink.grid;
      ctx.fillRect(6, 8, 120, 6);
      ctx.fillStyle = suspicion > 0.6 ? ink.danger : ink.brass;
      ctx.fillRect(6, 8, Math.floor(suspicion * 120), 6);
      ctx.font = '8px "IBM Plex Mono", monospace';
      ctx.fillStyle = ink.dim;
      ctx.fillText("SUSPICION", 132, 14);
      if (messageAge < 2.4) {
        ctx.textAlign = "center";
        ctx.fillStyle = ink.bright;
        ctx.fillText(message, W / 2, H - 6);
        ctx.textAlign = "left";
      }
    };

    game.hud = function () {
      return "FLOOR " + floorNo + " · " + (token.taken ? "EGRESS" : "TOKEN");
    };
    return game;
  }

  /* ---- 20. COLD STORAGE --------------------------------------------------

     Survival horror, which at this palette is one mechanic: you cannot see,
     and you cannot shoot everything. The floor is an archive nobody has read
     in years; the shamblers are replicas of records that were never garbage
     collected. Ammo is scarce enough that walking past something is usually
     the right call, which is the genre's actual lesson.

     The dark is drawn as a mask of blocks rather than a gradient: a radial
     falloff needs colours this palette does not have, and a chunky vignette
     is what this generation's horror looked like anyway. */
  function cabinetColdStorage(random) {
    var CELL = 16;
    var COLS = 20;
    var ROWS = 13;
    var OY = 24;
    var LIGHT = 54;

    var game = { id: "cold-storage", score: 0, lives: 3, over: false };
    var walls, shamblers, shards, you, ammo, depth, exitAt, message, messageAge, hurt, cooldown;

    function say(text) {
      message = text;
      messageAge = 0;
    }

    function blocked(px, py) {
      var cx = Math.floor(px / CELL);
      var cy = Math.floor((py - OY) / CELL);
      if (cx < 0 || cy < 0 || cx >= COLS || cy >= ROWS) return true;
      return walls[cy][cx] === 1;
    }

    function buildFloor() {
      walls = [];
      for (var y = 0; y < ROWS; y += 1) {
        var row = [];
        for (var x = 0; x < COLS; x += 1) {
          var edge = x === 0 || y === 0 || x === COLS - 1 || y === ROWS - 1;
          var stack = !edge && x % 4 === 2 && y % 2 === 1 && random() < 0.8;
          row.push(edge || stack ? 1 : 0);
        }
        walls.push(row);
      }
      you = { x: CELL * 1.5, y: OY + CELL * 1.5, face: 1, faceY: 0 };
      shards = [];
      for (var s = 0; s < 3; s += 1) {
        shards.push({
          x: CELL * (5 + Math.floor(random() * (COLS - 8))) + CELL / 2,
          y: OY + CELL * (2 + Math.floor(random() * (ROWS - 4))) + CELL / 2,
          taken: false
        });
      }
      shamblers = [];
      var count = Math.min(7, 3 + depth);
      for (var i = 0; i < count; i += 1) {
        shamblers.push({
          x: CELL * (8 + Math.floor(random() * (COLS - 10))) + CELL / 2,
          y: OY + CELL * (1 + Math.floor(random() * (ROWS - 2))) + CELL / 2,
          hp: 1,
          dead: false
        });
      }
      exitAt = { x: CELL * (COLS - 2) + CELL / 2, y: OY + CELL * (ROWS - 2) + CELL / 2 };
    }

    game.reset = function () {
      game.score = 0;
      game.lives = 3;
      game.over = false;
      depth = 1;
      ammo = 10;
      hurt = 0;
      cooldown = 0;
      messageAge = 0;
      buildFloor();
      say("B1 — THREE SHARDS, THEN THE STAIR");
    };

    function shardsLeft() {
      return shards.filter(function (s) { return !s.taken; }).length;
    }

    game.update = function (dt, input) {
      if (game.over) return;
      messageAge += dt;
      hurt = Math.max(0, hurt - dt);
      cooldown = Math.max(0, cooldown - dt);

      var speed = 54 * dt;
      var mx = (input.right ? 1 : 0) - (input.left ? 1 : 0);
      var my = (input.down ? 1 : 0) - (input.up ? 1 : 0);
      if (mx || my) {
        you.face = mx;
        you.faceY = mx ? 0 : my;
      }
      if (!blocked(you.x + mx * speed, you.y)) you.x += mx * speed;
      if (!blocked(you.x, you.y + my * speed)) you.y += my * speed;

      if (input.fire && cooldown <= 0 && ammo > 0) {
        cooldown = 0.45;
        ammo -= 1;
        // Hitscan down the facing axis, short range: a torch-lit archive is
        // not a place you take long shots in.
        var hit = null;
        shamblers.forEach(function (s) {
          if (s.dead) return;
          var dx = s.x - you.x;
          var dy = s.y - you.y;
          var alongAxis = you.faceY ? dy * you.faceY : dx * you.face;
          var offAxis = you.faceY ? Math.abs(dx) : Math.abs(dy);
          if (alongAxis < 0 || alongAxis > LIGHT || offAxis > 10) return;
          if (!hit || alongAxis < hit.d) hit = { s: s, d: alongAxis };
        });
        if (hit) {
          hit.s.hp -= 1;
          if (hit.s.hp <= 0) {
            hit.s.dead = true;
            game.score += 30;
            // Ammo comes back off a kill and only off a kill, so a missed
            // shot is a real loss rather than a rounding error.
            if (random() < 0.5) ammo += 1;
          }
        }
      }

      shamblers.forEach(function (s) {
        if (s.dead) return;
        var dx = you.x - s.x;
        var dy = you.y - s.y;
        var dist = Math.sqrt(dx * dx + dy * dy) || 1;
        // Always coming, faster once they have you: a shambler that idles
        // outside a wake radius lets the player stand in the far corner of
        // the floor indefinitely, and the whole cabinet is the pressure.
        var step = (dist < 100 ? 22 : 13) * dt;
        if (!blocked(s.x + (dx / dist) * step, s.y)) s.x += (dx / dist) * step;
        if (!blocked(s.x, s.y + (dy / dist) * step)) s.y += (dy / dist) * step;
        if (dist < 9 && hurt <= 0) {
          hurt = 1.8;
          game.lives -= 1;
          // Knocked clear, and the replica is pushed back with you. Without
          // it a cornered player took all three retries inside four seconds:
          // the invulnerability window ran out with the thing still standing
          // on them.
          var shove = 14;
          if (!blocked(you.x - (dx / dist) * shove, you.y)) you.x -= (dx / dist) * shove;
          if (!blocked(you.x, you.y - (dy / dist) * shove)) you.y -= (dy / dist) * shove;
          if (!blocked(s.x + (dx / dist) * shove, s.y)) s.x += (dx / dist) * shove;
          if (!blocked(s.x, s.y + (dy / dist) * shove)) s.y += (dy / dist) * shove;
          if (game.lives <= 0) {
            game.over = true;
            return;
          }
          say("A REPLICA GOT A HAND ON THE REQUEST");
        }
      });

      shards.forEach(function (s) {
        if (s.taken) return;
        if (Math.abs(s.x - you.x) > 9 || Math.abs(s.y - you.y) > 9) return;
        s.taken = true;
        ammo += 2;
        game.score += 50;
        say(shardsLeft() ? shardsLeft() + " SHARDS LEFT" : "STAIR UNLOCKED");
      });

      if (!shardsLeft() && Math.abs(you.x - exitAt.x) < 10 && Math.abs(you.y - exitAt.y) < 10) {
        depth += 1;
        game.score += 200;
        ammo += 4;
        buildFloor();
        say("B" + depth + " — IT IS COLDER DOWN HERE");
      }
    };

    game.draw = function (ctx, ink) {
      ctx.fillStyle = ink.bg;
      ctx.fillRect(0, 0, W, H);

      for (var y = 0; y < ROWS; y += 1) {
        for (var x = 0; x < COLS; x += 1) {
          if (!walls[y][x]) continue;
          ctx.fillStyle = ink.wall[3];
          ctx.fillRect(x * CELL, OY + y * CELL, CELL, CELL);
          ctx.fillStyle = ink.wall[2];
          ctx.fillRect(x * CELL, OY + y * CELL, CELL, 2);
        }
      }

      if (!shardsLeft()) {
        ctx.fillStyle = ink.verify;
        ctx.fillRect(exitAt.x - 6, exitAt.y - 6, 12, 12);
      }

      shards.forEach(function (s) {
        if (s.taken) return;
        ctx.fillStyle = ink.brass;
        ctx.fillRect(s.x - 3, s.y - 4, 6, 8);
      });

      shamblers.forEach(function (s) {
        if (s.dead) return;
        ctx.fillStyle = ink.danger;
        ctx.fillRect(Math.floor(s.x) - 5, Math.floor(s.y) - 6, 10, 12);
      });

      ctx.fillStyle = hurt > 0 && Math.floor(hurt * 10) % 2 === 0 ? ink.danger : ink.verify;
      ctx.fillRect(Math.floor(you.x) - 4, Math.floor(you.y) - 5, 8, 10);

      // The dark, last and over everything: 8x8 blocks outside the torch.
      ctx.fillStyle = ink.bg;
      for (var by = OY; by < H; by += 8) {
        for (var bx = 0; bx < W; bx += 8) {
          var dx = bx + 4 - you.x;
          var dy = by + 4 - you.y;
          if (dx * dx + dy * dy < LIGHT * LIGHT) continue;
          ctx.fillRect(bx, by, 8, 8);
        }
      }

      ctx.font = '8px "IBM Plex Mono", monospace';
      ctx.fillStyle = ammo ? ink.dim : ink.danger;
      ctx.fillText("ROUNDS " + ammo, 6, 14);
      ctx.fillStyle = ink.dim;
      ctx.fillText("SHARDS " + (3 - shardsLeft()) + "/3", W - 76, 14);
      if (messageAge < 2.4) {
        ctx.textAlign = "center";
        ctx.fillStyle = ink.bright;
        ctx.fillText(message, W / 2, 20);
        ctx.textAlign = "left";
      }
    };

    game.hud = function () {
      return "B" + depth + " · ROUNDS " + ammo;
    };
    return game;
  }

  /* ---- 21. BLOCK STORE ---------------------------------------------------

     The sandbox: dig, carry, place, and be somewhere defensible when the
     lights go out. One key does both verbs because there is only one key —
     facing a block mines it, facing empty space places one — and that turns
     out to be the whole loop rather than a compromise.

     Themed as an object store, because a block store is what one is: you are
     paid per block retrieved, the night is a scheduled scan, and the wall you
     stack between yourself and it is the only policy that has ever worked. */
  function cabinetBlockStore(random) {
    var CELL = 12;
    var COLS = 26;
    var ROWS = 18;
    var OX = (W - COLS * CELL) / 2;
    var OY = 6;
    var SKY = 5; // rows of open air above the surface

    var game = { id: "block-store", score: 0, lives: 3, over: false };
    var grid, you, held, dayClock, night, prowlers, cycle, message, messageAge, hurt, actCool;

    function say(text) {
      message = text;
      messageAge = 0;
    }

    function at(cx, cy) {
      if (cx < 0 || cy < 0 || cx >= COLS || cy >= ROWS) return 1;
      return grid[cy][cx];
    }

    function buildWorld() {
      grid = [];
      for (var y = 0; y < ROWS; y += 1) {
        var row = [];
        for (var x = 0; x < COLS; x += 1) {
          if (y < SKY) row.push(0);
          else if (y === SKY) row.push(1);
          // 2 is ore: worth score, and the only thing down here that is.
          else row.push(random() < 0.12 ? 2 : 1);
        }
        grid.push(row);
      }
      you = { x: 3, y: SKY - 1, face: 1, fall: 0 };
      held = 0;
      prowlers = [];
    }

    game.reset = function () {
      game.score = 0;
      game.lives = 3;
      game.over = false;
      cycle = 1;
      dayClock = 42;
      night = false;
      hurt = 0;
      actCool = 0;
      messageAge = 0;
      buildWorld();
      say("DAY 1 — DIG. THE SCAN RUNS AT DUSK.");
    };

    game.update = function (dt, input) {
      if (game.over) return;
      messageAge += dt;
      hurt = Math.max(0, hurt - dt);
      actCool = Math.max(0, actCool - dt);
      dayClock -= dt;

      if (dayClock <= 0) {
        night = !night;
        dayClock = night ? 26 : 42;
        if (night) {
          say("SCAN RUNNING — GET BEHIND SOMETHING");
          var count = Math.min(4, 1 + cycle);
          for (var p = 0; p < count; p += 1) {
            prowlers.push({
              x: (p % 2 ? COLS - 2 : 1) + random(),
              y: SKY - 1,
              speed: 1.7 + cycle * 0.22
            });
          }
        } else {
          cycle += 1;
          prowlers = [];
          game.score += 80;
          say("DAY " + cycle + " — YOU SURVIVED THE SCAN");
        }
      }

      // ---- movement: step on a grid, fall if unsupported ----------------
      if (actCool <= 0) {
        var mx = (input.right ? 1 : 0) - (input.left ? 1 : 0);
        var my = (input.down ? 1 : 0) - (input.up ? 1 : 0);
        if (mx) {
          you.face = mx;
          // Walk into a block and you climb it if the step is one high, which
          // is what keeps a dug trench from being a trap.
          if (!at(you.x + mx, you.y)) {
            you.x += mx;
            actCool = 0.1;
          } else if (!at(you.x + mx, you.y - 1) && !at(you.x, you.y - 1)) {
            you.x += mx;
            you.y -= 1;
            actCool = 0.14;
          }
        } else if (my > 0 && !at(you.x, you.y + 1)) {
          you.y += 1;
          actCool = 0.1;
        } else if (my < 0 && !at(you.x, you.y - 1) && at(you.x, you.y + 1)) {
          // Jump: only from solid ground, only one block, only into air.
          you.y -= 1;
          actCool = 0.16;
        }
      }

      if (!at(you.x, you.y + 1) && you.y < ROWS - 1) {
        you.fall += dt;
        if (you.fall > 0.14) {
          you.y += 1;
          you.fall = 0;
        }
      } else {
        you.fall = 0;
      }

      // ---- one key, two verbs -------------------------------------------
      if (input.fire && actCool <= 0) {
        actCool = 0.22;
        // The aim is the held direction, falling back to the way you face.
        // Without the vertical case there is no way down: the surface row is
        // air at head height, so every press placed a block instead of
        // digging and the ore below was unreachable.
        var tx = you.x;
        var ty = you.y;
        if (input.down) ty += 1;
        else if (input.up) ty -= 1;
        else tx += you.face;
        var target = at(tx, ty);
        if (target) {
          if (tx >= 0 && tx < COLS && ty >= 0 && ty < ROWS) {
            if (target === 2) {
              game.score += 25;
              say("COLD OBJECT RETRIEVED");
            }
            grid[ty][tx] = 0;
            held += 1;
          }
        } else if (held > 0) {
          grid[ty][tx] = 1;
          held -= 1;
        }
      }

      // ---- the scan ------------------------------------------------------
      prowlers.forEach(function (p) {
        var toward = you.x > p.x ? 1 : -1;
        var nx = p.x + toward * p.speed * dt;
        // A prowler walks the surface and cannot dig: a wall or a trench is
        // real cover, which is what makes the building half of the loop mean
        // something.
        if (at(Math.floor(nx), Math.round(p.y))) {
          if (!at(Math.floor(nx), Math.round(p.y) - 1)) p.y -= 1;
          return;
        }
        p.x = nx;
        if (!at(Math.floor(p.x), Math.round(p.y) + 1)) p.y += 1;

        if (Math.abs(p.x - you.x) < 0.8 && Math.abs(p.y - you.y) < 0.8 && hurt <= 0) {
          hurt = 1.2;
          game.lives -= 1;
          if (game.lives <= 0) {
            game.over = true;
            return;
          }
          say("THE SCAN FOUND YOU IN THE OPEN");
        }
      });
    };

    game.draw = function (ctx, ink) {
      ctx.fillStyle = ink.bg;
      ctx.fillRect(0, 0, W, H);

      ctx.fillStyle = night ? ink.bg : ink.grid;
      ctx.fillRect(OX, OY, COLS * CELL, SKY * CELL);
      // Sun or moon, as one block on a rail across the sky.
      var phase = 1 - dayClock / (night ? 26 : 42);
      ctx.fillStyle = night ? ink.dim : ink.bright;
      ctx.fillRect(OX + phase * (COLS * CELL - 10), OY + 8, 8, 8);

      for (var y = 0; y < ROWS; y += 1) {
        for (var x = 0; x < COLS; x += 1) {
          var tile = grid[y][x];
          if (!tile) continue;
          ctx.fillStyle = tile === 2 ? ink.brass : y === SKY ? ink.verify : ink.wall[2];
          ctx.fillRect(OX + x * CELL, OY + y * CELL, CELL, CELL);
          ctx.fillStyle = ink.bg;
          ctx.fillRect(OX + x * CELL + CELL - 1, OY + y * CELL, 1, CELL);
          ctx.fillRect(OX + x * CELL, OY + y * CELL + CELL - 1, CELL, 1);
        }
      }

      prowlers.forEach(function (p) {
        ctx.fillStyle = ink.danger;
        ctx.fillRect(OX + p.x * CELL, OY + p.y * CELL + 1, CELL - 2, CELL - 1);
      });

      ctx.fillStyle = hurt > 0 && Math.floor(hurt * 10) % 2 === 0 ? ink.bright : ink.verify;
      ctx.fillRect(OX + you.x * CELL + 2, OY + you.y * CELL + 1, CELL - 4, CELL - 2);
      ctx.fillStyle = ink.bg;
      ctx.fillRect(OX + you.x * CELL + (you.face > 0 ? CELL - 5 : 3), OY + you.y * CELL + 4, 2, 2);

      ctx.font = '8px "IBM Plex Mono", monospace';
      ctx.fillStyle = ink.dim;
      ctx.fillText("BLOCKS " + held, 4, H - 4);
      ctx.fillStyle = night ? ink.danger : ink.verify;
      ctx.fillText((night ? "SCAN " : "DAY ") + Math.ceil(dayClock) + "s", W - 78, H - 4);
      if (messageAge < 2.6) {
        ctx.textAlign = "center";
        ctx.fillStyle = ink.bright;
        ctx.fillText(message, W / 2, 20);
        ctx.textAlign = "left";
      }
    };

    game.hud = function () {
      return "DAY " + cycle + " · " + (night ? "SCAN" : "CLEAR");
    };
    return game;
  }

  /* ---- 22. LAST QUORUM ---------------------------------------------------

     The battle royale, which is a genre made of one idea: the board shrinks.
     Here the board is a quorum and the ring is the set of nodes still willing
     to vote — stand outside it and you are partitioned, which costs you
     steadily rather than instantly.

     Everyone else in the match is an agent with the same objective, so the
     honest play is the one the genre is famous for: let them meet first. */
  function cabinetLastQuorum(random) {
    var game = { id: "last-quorum", score: 0, lives: 3, over: false };
    var you, rivals, ring, shots, match, message, messageAge, cooldown, hurt;

    function say(text) {
      message = text;
      messageAge = 0;
    }

    function startMatch() {
      you = { x: W / 2, y: H / 2, hp: 100, face: { x: 1, y: 0 } };
      rivals = [];
      var count = Math.min(9, 4 + match);
      for (var i = 0; i < count; i += 1) {
        var a = (i / count) * Math.PI * 2;
        rivals.push({
          x: W / 2 + Math.cos(a) * 120,
          y: H / 2 + Math.sin(a) * 90,
          hp: 40,
          cool: 1 + random() * 2,
          dead: false
        });
      }
      ring = { x: W / 2, y: H / 2, r: 150, target: 150, hold: 8 };
      shots = [];
      cooldown = 0;
      hurt = 0;
      say("MATCH " + match + " — " + (count + 1) + " IN THE QUORUM");
    }

    game.reset = function () {
      game.score = 0;
      game.lives = 3;
      game.over = false;
      match = 1;
      messageAge = 0;
      startMatch();
    };

    function alive() {
      return rivals.filter(function (r) { return !r.dead; });
    }

    function fire(from, dx, dy, mine) {
      var dist = Math.sqrt(dx * dx + dy * dy) || 1;
      shots.push({
        x: from.x,
        y: from.y,
        dx: (dx / dist) * 150,
        dy: (dy / dist) * 150,
        mine: mine,
        life: 1.4
      });
    }

    game.update = function (dt, input) {
      if (game.over) return;
      messageAge += dt;
      cooldown = Math.max(0, cooldown - dt);
      hurt = Math.max(0, hurt - dt);

      // ---- the ring -----------------------------------------------------
      ring.hold -= dt;
      if (ring.hold <= 0 && ring.target > 34) {
        ring.target = Math.max(34, ring.target - 26);
        ring.hold = 9;
        say("QUORUM SHRANK TO " + Math.round(ring.target));
      }
      ring.r += (ring.target - ring.r) * Math.min(1, dt * 0.6);

      var mx = (input.right ? 1 : 0) - (input.left ? 1 : 0);
      var my = (input.down ? 1 : 0) - (input.up ? 1 : 0);
      if (mx || my) {
        you.face = { x: mx, y: my };
        var speed = 70 * dt;
        you.x = clamp(you.x + mx * speed, 4, W - 4);
        you.y = clamp(you.y + my * speed, 20, H - 4);
      }

      if (input.fire && cooldown <= 0) {
        cooldown = 0.3;
        fire(you, you.face.x, you.face.y, true);
      }

      var outside = Math.sqrt(
        (you.x - ring.x) * (you.x - ring.x) + (you.y - ring.y) * (you.y - ring.y)
      ) > ring.r;
      if (outside) {
        you.hp -= 14 * dt;
        hurt = 0.2;
      }

      // ---- the field ----------------------------------------------------
      alive().forEach(function (r) {
        var dx = you.x - r.x;
        var dy = you.y - r.y;
        var dist = Math.sqrt(dx * dx + dy * dy) || 1;
        // Rivals want the middle of the ring and take a shot at whatever is
        // in front of them on the way, which is close enough to how a real
        // lobby behaves and cheaper than pathing to each other.
        var toRingX = ring.x - r.x;
        var toRingY = ring.y - r.y;
        var ringDist = Math.sqrt(toRingX * toRingX + toRingY * toRingY) || 1;
        var pull = ringDist > ring.r - 20 ? 1 : 0.25;
        var chase = dist < 90 ? 0.8 : 0;
        r.x += ((toRingX / ringDist) * pull + (dx / dist) * chase) * 44 * dt;
        r.y += ((toRingY / ringDist) * pull + (dy / dist) * chase) * 44 * dt;

        r.cool -= dt;
        if (r.cool <= 0 && dist < 120) {
          r.cool = 1.1 + random();
          fire(r, dx, dy, false);
        }
      });

      shots.forEach(function (s) {
        s.x += s.dx * dt;
        s.y += s.dy * dt;
        s.life -= dt;
        if (s.mine) {
          alive().forEach(function (r) {
            if (Math.abs(r.x - s.x) > 6 || Math.abs(r.y - s.y) > 6) return;
            s.life = 0;
            r.hp -= 20;
            if (r.hp <= 0) {
              r.dead = true;
              game.score += 60;
            }
          });
        } else if (Math.abs(you.x - s.x) < 6 && Math.abs(you.y - s.y) < 6) {
          s.life = 0;
          you.hp -= 12;
          hurt = 0.3;
        }
      });
      shots = shots.filter(function (s) {
        return s.life > 0 && s.x > -8 && s.x < W + 8 && s.y > -8 && s.y < H + 8;
      });

      if (you.hp <= 0) {
        game.lives -= 1;
        if (game.lives <= 0) {
          game.over = true;
          return;
        }
        say("PARTITIONED OUT — " + (alive().length + 1) + "th");
        startMatch();
        return;
      }

      if (!alive().length) {
        game.score += 300;
        match += 1;
        say("LAST IN THE QUORUM — NOBODY LEFT TO OUTVOTE YOU");
        startMatch();
      }
    };

    game.draw = function (ctx, ink) {
      ctx.fillStyle = ink.bg;
      ctx.fillRect(0, 0, W, H);

      // The ring, as a dotted circle of blocks. Everything outside it is
      // shaded, so "inside" is legible without a fill.
      ctx.fillStyle = ink.grid;
      for (var y = 20; y < H; y += 6) {
        for (var x = 0; x < W; x += 6) {
          var dx = x - ring.x;
          var dy = y - ring.y;
          if (dx * dx + dy * dy < ring.r * ring.r) continue;
          ctx.fillRect(x, y, 3, 3);
        }
      }
      ctx.fillStyle = ink.verify;
      for (var a = 0; a < Math.PI * 2; a += 0.09) {
        ctx.fillRect(
          Math.floor(ring.x + Math.cos(a) * ring.r) - 1,
          Math.floor(ring.y + Math.sin(a) * ring.r) - 1,
          2,
          2
        );
      }

      alive().forEach(function (r) {
        ctx.fillStyle = ink.danger;
        ctx.fillRect(Math.floor(r.x) - 4, Math.floor(r.y) - 4, 8, 8);
      });

      shots.forEach(function (s) {
        ctx.fillStyle = s.mine ? ink.bright : ink.brass;
        ctx.fillRect(Math.floor(s.x) - 1, Math.floor(s.y) - 1, 2, 2);
      });

      ctx.fillStyle = hurt > 0 ? ink.bright : ink.verify;
      ctx.fillRect(Math.floor(you.x) - 4, Math.floor(you.y) - 5, 8, 10);

      ctx.font = '8px "IBM Plex Mono", monospace';
      ctx.fillStyle = ink.grid;
      ctx.fillRect(6, 8, 90, 6);
      ctx.fillStyle = you.hp > 30 ? ink.verify : ink.danger;
      ctx.fillRect(6, 8, Math.max(0, Math.floor((you.hp / 100) * 90)), 6);
      ctx.fillStyle = ink.dim;
      ctx.fillText("ALIVE " + (alive().length + 1), W - 74, 14);
      if (messageAge < 2.4) {
        ctx.textAlign = "center";
        ctx.fillStyle = ink.bright;
        ctx.fillText(message, W / 2, 26);
        ctx.textAlign = "left";
      }
    };

    game.hud = function () {
      return "MATCH " + match + " · HP " + Math.max(0, Math.floor(you.hp));
    };
    return game;
  }

  /* ---- 23. HEARTBEAT -----------------------------------------------------

     The rhythm cabinet. Four lanes of health checks fall toward a judgement
     line and you answer each one on the beat: miss enough and the service is
     declared down. The chart is generated from the seeded generator against a
     fixed tempo, so the same seed is the same song — a rhythm game whose
     notes move is not a rhythm game.

     Silent by construction. The page never plays audio (the boot screen says
     so), so the beat is carried by a pulsing bar and by the notes themselves,
     which is how this genre worked on hardware with one sound channel. */
  function cabinetHeartbeat(random) {
    var LANES = 4;
    var LANE_W = 40;
    var OX = (W - LANES * LANE_W) / 2;
    var LINE = H - 44;
    var FALL = 118;      // px per second
    var WINDOW = 14;     // px of tolerance at the line
    var LANE_KEYS = ["left", "up", "down", "right"];
    var LANE_NAMES = ["PING", "READY", "LIVE", "SYNC"];

    var game = { id: "heartbeat", score: 0, lives: 3, over: false };
    var notes, beatTimer, beat, combo, bestCombo, health, tempo, bar,
      flashes, held, judgement, judgementAge;

    function judge(text) {
      judgement = text;
      judgementAge = 0;
    }

    game.reset = function () {
      game.score = 0;
      game.lives = 3;
      game.over = false;
      notes = [];
      beatTimer = 0;
      beat = 0;
      combo = 0;
      bestCombo = 0;
      health = 1;
      tempo = 0.42;
      bar = 1;
      flashes = [0, 0, 0, 0];
      held = [false, false, false, false];
      judgement = "READY";
      judgementAge = 0;
    };

    function spawnBeat() {
      // One note most beats, two on the downbeat of a later bar. Density
      // rises with the bar count rather than at random, so the chart has a
      // shape a player can learn instead of a difficulty that flickers.
      var density = Math.min(0.85, 0.45 + bar * 0.03);
      var placed = 0;
      for (var lane = 0; lane < LANES; lane += 1) {
        if (random() > density / LANES * 1.6) continue;
        notes.push({ lane: lane, y: -8, hit: false });
        placed += 1;
        if (placed >= (beat % 4 === 0 && bar > 3 ? 2 : 1)) break;
      }
      if (!placed) notes.push({ lane: Math.floor(random() * LANES), y: -8, hit: false });
    }

    function drop(reason) {
      combo = 0;
      health -= 0.14;
      judge(reason);
      if (health > 0) return;
      game.lives -= 1;
      health = 1;
      if (game.lives <= 0) game.over = true;
    }

    game.update = function (dt, input) {
      if (game.over) return;
      judgementAge += dt;

      beatTimer -= dt;
      if (beatTimer <= 0) {
        beatTimer += tempo;
        beat += 1;
        if (beat % 8 === 0) {
          bar += 1;
          // The tempo creeps, which is the only difficulty curve this genre
          // has ever needed.
          tempo = Math.max(0.22, tempo - 0.012);
          game.score += 20;
        }
        spawnBeat();
      }

      notes.forEach(function (n) { n.y += FALL * dt; });

      var pressed = [!!input.left, !!input.up, !!input.down, !!input.right];
      for (var lane = 0; lane < LANES; lane += 1) {
        if (!pressed[lane]) {
          held[lane] = false;
          continue;
        }
        if (held[lane]) continue;
        held[lane] = true;
        flashes[lane] = 0.16;

        // Nearest unhit note in this lane, and only if it is inside the
        // window: a lane press with nothing near it is a miss, or the game is
        // one where mashing all four keys wins.
        var best = null;
        notes.forEach(function (n) {
          if (n.hit || n.lane !== lane) return;
          var off = Math.abs(n.y - LINE);
          if (off > WINDOW * 2.2) return;
          if (!best || off < best.off) best = { note: n, off: off };
        });
        if (!best) {
          // Cheaper than a miss: hitting a lane early is a player learning
          // where the lanes are, and a miss is the service going unanswered.
          combo = 0;
          health -= 0.05;
          judge("EARLY — NOTHING THERE");
          continue;
        }
        best.note.hit = true;
        if (best.off <= WINDOW * 0.5) {
          combo += 1;
          game.score += 10 + Math.floor(combo / 5) * 2;
          judge("ON BEAT ×" + combo);
        } else if (best.off <= WINDOW) {
          combo += 1;
          game.score += 5;
          judge("LATE — STILL COUNTS");
        } else {
          drop("OFF BEAT");
        }
        if (combo > bestCombo) bestCombo = combo;
      }

      notes.forEach(function (n) {
        if (n.hit || n.y <= LINE + WINDOW) return;
        n.hit = true;
        drop("MISSED CHECK");
      });
      notes = notes.filter(function (n) { return n.y < H + 12 && !n.hit; });

      for (var f = 0; f < LANES; f += 1) flashes[f] = Math.max(0, flashes[f] - dt);
    };

    game.draw = function (ctx, ink) {
      ctx.fillStyle = ink.bg;
      ctx.fillRect(0, 0, W, H);

      for (var lane = 0; lane < LANES; lane += 1) {
        var x = OX + lane * LANE_W;
        // Every lane the same shade, separated by the gutter the width leaves.
        // Alternating lane against background read as two wide lanes rather
        // than four, which is the one thing this cabinet cannot afford to be
        // ambiguous about.
        ctx.fillStyle = ink.grid;
        ctx.fillRect(x, 18, LANE_W - 3, H - 30);
        ctx.fillStyle = flashes[lane] > 0 ? ink.bright : ink.wall[2];
        ctx.fillRect(x, LINE, LANE_W - 2, 4);
        ctx.font = '7px "IBM Plex Mono", monospace';
        ctx.fillStyle = ink.dim;
        ctx.textAlign = "center";
        ctx.fillText(LANE_NAMES[lane], x + LANE_W / 2 - 1, H - 26);
        ctx.fillText(["←", "↑", "↓", "→"][lane], x + LANE_W / 2 - 1, H - 14);
        ctx.textAlign = "left";
      }

      notes.forEach(function (n) {
        var x = OX + n.lane * LANE_W;
        var close = Math.abs(n.y - LINE) < WINDOW;
        ctx.fillStyle = close ? ink.verify : ink.brass;
        ctx.fillRect(x + 4, Math.floor(n.y) - 4, LANE_W - 10, 8);
      });

      // The beat, as a bar that pulses on the downbeat. This is the metronome
      // a silent cabinet has to give you instead of a click track.
      var pulse = 1 - beatTimer / tempo;
      ctx.fillStyle = ink.grid;
      ctx.fillRect(0, 0, W, 14);
      ctx.fillStyle = beat % 4 === 0 ? ink.bright : ink.brass;
      ctx.fillRect(0, 0, Math.floor(pulse * W), 3);

      ctx.font = '8px "IBM Plex Mono", monospace';
      ctx.fillStyle = ink.dim;
      ctx.fillText("BAR " + bar, 4, 11);
      ctx.fillStyle = health > 0.4 ? ink.verify : ink.danger;
      ctx.fillRect(W - 96, 4, 92, 6);
      ctx.fillStyle = ink.bg;
      ctx.fillRect(W - 96 + Math.floor(health * 92), 4, 92 - Math.floor(health * 92), 6);

      if (judgementAge < 1) {
        ctx.textAlign = "center";
        ctx.fillStyle = combo > 0 ? ink.verify : ink.danger;
        ctx.fillText(judgement, W / 2, LINE - 24);
        ctx.textAlign = "left";
      }
    };

    game.hud = function () {
      return "COMBO " + combo + " · BEST " + bestCombo;
    };
    return game;
  }

  /* ---- 24. BRUTE FORCE ---------------------------------------------------

     The belt-scrolling brawler: a shallow strip of floor, a crowd walking in
     from both edges, and one button. The depth axis is what separates this
     from a side-scroller — you line up on somebody's row before you can hit
     them, and the whole skill is not being surrounded while you do it.

     The crowd is a credential-stuffing run, which is the one attack in this
     product's domain that is literally a brawl: no cleverness, just volume,
     and the answer is to stand somewhere the volume cannot all reach you. */
  function cabinetBruteForce(random) {
    var TOP = 130;      // shallowest row of the belt
    var BOTTOM = H - 26;
    var REACH = 22;

    var game = { id: "brute-force", score: 0, lives: 3, over: false };
    var you, crowd, wave, spawnLeft, scroll, message, messageAge, hurt, swing, cooldown;

    function say(text) {
      message = text;
      messageAge = 0;
    }

    function startWave() {
      crowd = [];
      spawnLeft = 4 + wave * 2;
      say("WAVE " + wave + " — " + spawnLeft + " ATTEMPTS INBOUND");
    }

    game.reset = function () {
      game.score = 0;
      game.lives = 3;
      game.over = false;
      wave = 1;
      scroll = 0;
      hurt = 0;
      swing = 0;
      cooldown = 0;
      messageAge = 0;
      you = { x: W / 2, y: (TOP + BOTTOM) / 2, face: 1 };
      startWave();
    };

    function spawn() {
      var fromLeft = random() < 0.5;
      crowd.push({
        x: fromLeft ? -12 : W + 12,
        y: TOP + random() * (BOTTOM - TOP),
        hp: 2 + Math.floor(wave / 3),
        cool: 0,
        face: fromLeft ? 1 : -1
      });
    }

    game.update = function (dt, input) {
      if (game.over) return;
      messageAge += dt;
      hurt = Math.max(0, hurt - dt);
      swing = Math.max(0, swing - dt);
      cooldown = Math.max(0, cooldown - dt);
      scroll += 14 * dt;

      var speed = 62 * dt;
      if (input.left) { you.x -= speed; you.face = -1; }
      if (input.right) { you.x += speed; you.face = 1; }
      // The depth axis moves at half rate, the way this genre always did it:
      // it is a positioning axis, not a dodging one.
      if (input.up) you.y -= speed * 0.5;
      if (input.down) you.y += speed * 0.5;
      you.x = clamp(you.x, 8, W - 8);
      you.y = clamp(you.y, TOP, BOTTOM);

      if (input.fire && cooldown <= 0) {
        cooldown = 0.26;
        swing = 0.14;
        var landed = 0;
        crowd.forEach(function (c) {
          if (Math.abs(c.y - you.y) > 10) return;
          var gap = (c.x - you.x) * you.face;
          if (gap < 0 || gap > REACH) return;
          c.hp -= 1;
          c.x += you.face * 8;
          landed += 1;
          if (c.hp <= 0) {
            c.down = true;
            game.score += 20;
          }
        });
        if (landed > 1) game.score += 15; // a hit that caught two of them
      }

      if (spawnLeft > 0 && crowd.length < 5 && random() < dt * 1.6) {
        spawn();
        spawnLeft -= 1;
      }

      crowd.forEach(function (c) {
        if (c.down) return;
        var dx = you.x - c.x;
        var dy = you.y - c.y;
        c.face = dx > 0 ? 1 : -1;
        var pace = (26 + wave * 2) * dt;
        // Close the depth first, then the distance: a crowd that converges on
        // a diagonal all arrives at once and there is no play in that.
        if (Math.abs(dy) > 4) c.y += (dy > 0 ? 1 : -1) * pace * 0.6;
        else if (Math.abs(dx) > REACH - 6) c.x += (dx > 0 ? 1 : -1) * pace;

        c.cool -= dt;
        if (Math.abs(dx) <= REACH - 4 && Math.abs(dy) <= 10 && c.cool <= 0) {
          c.cool = 1.1;
          if (hurt > 0) return;
          hurt = 1;
          game.lives -= 1;
          if (game.lives <= 0) {
            game.over = true;
            return;
          }
          say("STUFFED — ONE GOT THROUGH");
        }
      });
      crowd = crowd.filter(function (c) { return !c.down; });

      if (!crowd.length && spawnLeft <= 0) {
        wave += 1;
        game.score += 90;
        startWave();
      }
    };

    game.draw = function (ctx, ink) {
      ctx.fillStyle = ink.bg;
      ctx.fillRect(0, 0, W, H);

      // Background wall with a scrolling repeat, so the belt reads as moving
      // even though the fight is stationary.
      ctx.fillStyle = ink.grid;
      ctx.fillRect(0, 20, W, TOP - 20);
      ctx.fillStyle = ink.wall[3];
      for (var d = -1; d < 12; d += 1) {
        ctx.fillRect((d * 34 - scroll % 34), 34, 20, TOP - 54);
      }
      ctx.fillStyle = ink.wall[2];
      ctx.fillRect(0, TOP - 4, W, 4);
      ctx.fillStyle = ink.wall[3];
      ctx.fillRect(0, TOP, W, H - TOP);

      var bodies = crowd.slice();
      bodies.push(you);
      // Painter's algorithm on the depth axis: whoever is further down the
      // belt is nearer the camera and draws last.
      bodies.sort(function (a, b) { return a.y - b.y; });

      bodies.forEach(function (b) {
        var mine = b === you;
        var x = Math.floor(b.x);
        var y = Math.floor(b.y);
        var scale = 0.8 + (b.y - TOP) / (BOTTOM - TOP) * 0.4;
        var hgt = Math.floor(22 * scale);
        ctx.fillStyle = mine
          ? (hurt > 0 && Math.floor(hurt * 10) % 2 === 0 ? ink.bright : ink.verify)
          : ink.danger;
        ctx.fillRect(x - 5, y - hgt, 10, hgt);
        ctx.fillStyle = ink.bg;
        ctx.fillRect(x - 3, y - hgt + 3, 2, 2);
        ctx.fillRect(x + 1, y - hgt + 3, 2, 2);
        if (mine && swing > 0) {
          ctx.fillStyle = ink.bright;
          ctx.fillRect(x + (you.face > 0 ? 5 : -5 - REACH), y - hgt + 6, REACH, 4);
        }
      });

      ctx.font = '8px "IBM Plex Mono", monospace';
      ctx.fillStyle = ink.dim;
      ctx.fillText("QUEUED " + spawnLeft, 4, 12);
      ctx.fillText("ON THE FLOOR " + crowd.length, W - 118, 12);
      if (messageAge < 2.2) {
        ctx.textAlign = "center";
        ctx.fillStyle = ink.bright;
        ctx.fillText(message, W / 2, 26);
        ctx.textAlign = "left";
      }
    };

    game.hud = function () {
      return "WAVE " + wave + " · " + (spawnLeft + crowd.length) + " LEFT";
    };
    return game;
  }

  /* ---- 25. CATALOG -------------------------------------------------------

     The creature-collector, which on a console is two games stitched
     together: walking around, and a capture that is decided in a moment. The
     walk is the unregistered half of a tool estate — every tall patch of
     shadow IT is a thing somebody is calling in production that nobody has
     written down. Meeting one opens the capture: a marker sweeps a bar, and
     the narrow band in the middle is the scope that actually fits the tool.

     Register the whole floor and the estate grows a new one, because it
     always does. */
  function cabinetCatalog(random) {
    var CELL = 16;
    var COLS = 20;
    var ROWS = 11;
    var OY = 34;
    var TOOLS = [
      "pdf-gen", "crm-sync", "s3-copy", "mailer", "geocode",
      "ocr", "invoice", "scraper", "tokenise", "webhook"
    ];

    var game = { id: "catalog", score: 0, lives: 3, over: false };
    var patches, you, mode, quarry, sweep, dir, band, registered, estate,
      moveCool, message, messageAge, held;

    function say(text) {
      message = text;
      messageAge = 0;
    }

    function buildEstate() {
      patches = [];
      for (var y = 0; y < ROWS; y += 1) {
        var row = [];
        for (var x = 0; x < COLS; x += 1) {
          row.push(x > 0 && y > 0 && x < COLS - 1 && y < ROWS - 1 && random() < 0.3 ? 1 : 0);
        }
        patches.push(row);
      }
      you = { x: 1, y: 1 };
      mode = "walk";
      quarry = null;
      registered = 0;
    }

    game.reset = function () {
      game.score = 0;
      game.lives = 3;
      game.over = false;
      estate = 1;
      moveCool = 0;
      messageAge = 0;
      held = false;
      buildEstate();
      say("ESTATE 1 — SIX TOOLS TO REGISTER");
    };

    function encounter() {
      mode = "capture";
      quarry = {
        name: TOOLS[Math.floor(random() * TOOLS.length)],
        // A rarer tool has a narrower scope that fits it, which is the only
        // difficulty dial this needs.
        tier: 1 + Math.floor(random() * 3)
      };
      sweep = 0;
      dir = 1;
      band = 0.3 - quarry.tier * 0.055 + estate * -0.01;
      band = Math.max(0.06, band);
    }

    game.update = function (dt, input) {
      if (game.over) return;
      messageAge += dt;
      moveCool -= dt;

      if (mode === "capture") {
        sweep += dir * dt * (0.85 + quarry.tier * 0.25 + estate * 0.08);
        if (sweep > 1) { sweep = 1; dir = -1; }
        if (sweep < 0) { sweep = 0; dir = 1; }

        if (!input.fire) {
          held = false;
          return;
        }
        if (held) return;
        held = true;

        var off = Math.abs(sweep - 0.5);
        if (off <= band / 2) {
          registered += 1;
          game.score += 40 + quarry.tier * 20;
          say(quarry.name + " REGISTERED — SCOPE FITS");
          mode = "walk";
          quarry = null;
          if (registered >= 6) {
            estate += 1;
            game.score += 180;
            buildEstate();
            say("ESTATE " + estate + " — MORE OF IT APPEARED");
          }
          return;
        }
        // A miss costs the encounter, not a life: the genre's failure is the
        // one that got away, and it is worse than a hit point.
        game.lives -= 1;
        mode = "walk";
        quarry = null;
        if (game.lives <= 0) {
          game.over = true;
          return;
        }
        say("SCOPE TOO " + (sweep < 0.5 ? "NARROW" : "WIDE") + " — IT STAYS UNREGISTERED");
        return;
      }

      held = !!input.fire;
      if (moveCool > 0) return;
      var mx = (input.right ? 1 : 0) - (input.left ? 1 : 0);
      var my = mx ? 0 : (input.down ? 1 : 0) - (input.up ? 1 : 0);
      if (!mx && !my) return;
      moveCool = 0.13;
      you.x = clamp(you.x + mx, 0, COLS - 1);
      you.y = clamp(you.y + my, 0, ROWS - 1);
      if (patches[you.y][you.x] && random() < 0.34) encounter();
    };

    game.draw = function (ctx, ink) {
      ctx.fillStyle = ink.bg;
      ctx.fillRect(0, 0, W, H);
      ctx.font = '8px "IBM Plex Mono", monospace';

      for (var y = 0; y < ROWS; y += 1) {
        for (var x = 0; x < COLS; x += 1) {
          var px = x * CELL;
          var py = OY + y * CELL;
          ctx.fillStyle = (x + y) % 2 === 0 ? ink.bg : ink.grid;
          ctx.fillRect(px, py, CELL, CELL);
          if (!patches[y][x]) continue;
          ctx.fillStyle = ink.wall[1];
          for (var blade = 0; blade < 3; blade += 1) {
            ctx.fillRect(px + 3 + blade * 4, py + 4 + (blade % 2) * 2, 2, CELL - 8);
          }
        }
      }

      ctx.fillStyle = ink.verify;
      ctx.fillRect(you.x * CELL + 4, OY + you.y * CELL + 3, CELL - 8, CELL - 6);

      ctx.fillStyle = ink.dim;
      ctx.fillText("REGISTERED " + registered + "/6", 4, 14);
      ctx.fillText("ESTATE " + estate, W - 74, 14);

      if (mode === "capture") {
        // The capture panel sits over the walk, the way an encounter screen
        // slid over the map on hardware that could not hold two scenes.
        ctx.fillStyle = ink.bg;
        ctx.fillRect(24, 62, W - 48, 116);
        ctx.fillStyle = ink.brass;
        ctx.fillRect(24, 62, W - 48, 2);
        ctx.fillRect(24, 176, W - 48, 2);
        ctx.textAlign = "center";
        ctx.fillStyle = ink.ink;
        ctx.fillText("UNREGISTERED TOOL", W / 2, 80);
        ctx.fillStyle = ink.bright;
        ctx.fillText(quarry.name + "  ·  TIER " + quarry.tier, W / 2, 96);
        ctx.fillStyle = ink.dim;
        ctx.fillText("STOP THE MARKER IN THE SCOPE", W / 2, 166);
        ctx.textAlign = "left";

        var barX = 44;
        var barW = W - 88;
        ctx.fillStyle = ink.grid;
        ctx.fillRect(barX, 122, barW, 14);
        ctx.fillStyle = ink.verify;
        ctx.fillRect(barX + barW * (0.5 - band / 2), 122, barW * band, 14);
        ctx.fillStyle = ink.danger;
        ctx.fillRect(barX + barW * sweep - 1, 116, 3, 26);
      }

      if (messageAge < 2.4) {
        ctx.textAlign = "center";
        ctx.fillStyle = ink.bright;
        ctx.fillText(message, W / 2, 26);
        ctx.textAlign = "left";
      }
    };

    game.hud = function () {
      return "ESTATE " + estate + " · " + registered + "/6";
    };
    return game;
  }

  var CABINETS = [
    {
      id: "blast-radius",
      name: "BLAST RADIUS",
      genre: "FPS",
      tagline: "Walk the permit boundary. Nothing unscoped reaches the tool.",
      controls: "← → turn · ↑ ↓ walk · SPACE fire",
      make: cabinetBlastRadius
    },
    {
      id: "hold-the-line",
      name: "HOLD THE LINE",
      genre: "FPS",
      tagline: "Four corridors. One post. Do not let a call through.",
      controls: "← → turn · ↑ ↓ step · SPACE fire",
      make: cabinetHoldTheLine
    },
    {
      id: "scope-creep",
      name: "SCOPE CREEP",
      genre: "SHOOTER",
      tagline: "Deny the permissions before they reach production.",
      controls: "← → move · SPACE deny",
      make: cabinetScopeCreep
    },
    {
      id: "retry-storm",
      name: "RETRY STORM",
      genre: "SHOOTER",
      tagline: "Shoot a duplicate and now there are two of them.",
      controls: "← → turn · ↑ thrust · SPACE fire",
      make: cabinetRetryStorm
    },
    {
      id: "token-bucket",
      name: "TOKEN BUCKET",
      genre: "ARCADE",
      tagline: "Drain the burst. The bucket refills. Forever.",
      controls: "← → limiter · SPACE serve",
      make: cabinetTokenBucket
    },
    {
      id: "double-spend",
      name: "DOUBLE SPEND",
      genre: "ARCADE",
      tagline: "Cross the settlement lanes. Get charged exactly once.",
      controls: "arrows step",
      make: cabinetDoubleSpend
    },
    {
      id: "backpressure",
      name: "BACKPRESSURE",
      genre: "PUZZLE",
      tagline: "Work arrives faster than it drains. Stack it anyway.",
      controls: "← → shift · SPACE rotate · ↓ drop",
      make: cabinetBackpressure
    },
    {
      id: "append-only",
      name: "APPEND-ONLY",
      genre: "PUZZLE",
      tagline: "The ledger grows. It may never cross itself.",
      controls: "arrows steer the write head",
      make: cabinetAppendOnly
    },
    {
      id: "nonce-burn",
      name: "NONCE BURN",
      genre: "REFLEX",
      tagline: "Each one is good once, and not for long.",
      controls: "arrows move · SPACE burn",
      make: cabinetNonceBurn
    },
    {
      id: "key-rotation",
      name: "KEY ROTATION",
      genre: "MAZE",
      tagline: "Collect the new key before the revocations reach you.",
      controls: "arrows move",
      make: cabinetKeyRotation
    },
    {
      id: "tail-latency",
      name: "TAIL LATENCY",
      genre: "RUNNER",
      tagline: "p50 is fine. p50 is not what your users get.",
      controls: "↑ jump · ↓ duck",
      make: cabinetTailLatency
    },
    {
      id: "race-condition",
      name: "RACE CONDITION",
      genre: "DUEL",
      tagline: "Rally against an agent that does not blink.",
      controls: "↑ ↓ move · first to 7",
      make: cabinetRaceCondition
    },
    {
      id: "countersign",
      name: "COUNTERSIGN",
      genre: "FPS",
      tagline: "The fuse is a TTL. Hold the key down and it never fires.",
      controls: "← → turn · ↑ ↓ walk · SPACE fire / hold to countersign",
      make: cabinetCountersign
    },
    {
      id: "happy-path",
      name: "HAPPY PATH",
      genre: "PLATFORM",
      tagline: "Run right. The gaps are the cases nobody wrote.",
      controls: "← → run · SPACE jump",
      make: cabinetHappyPath
    },
    {
      id: "least-privilege",
      name: "LEAST PRIVILEGE",
      genre: "ADVENTURE",
      tagline: "Nine rooms, two permits, one vault. Take only what opens it.",
      controls: "arrows move · SPACE revoke",
      make: cabinetLeastPrivilege
    },
    {
      id: "escalation",
      name: "ESCALATION",
      genre: "RPG",
      tagline: "Turn-based. The committee has more hit points than you.",
      controls: "↑ ↓ choose · SPACE commit",
      make: cabinetEscalation
    },
    {
      id: "arbitration",
      name: "ARBITRATION",
      genre: "FIGHTING",
      tagline: "Two parties, one dispute, best of three.",
      controls: "← → step · ↑ jump · ↓ block · SPACE strike",
      make: cabinetArbitration
    },
    {
      id: "throughput",
      name: "THROUGHPUT",
      genre: "RACING",
      tagline: "Off the road you are not crashed, only throttled.",
      controls: "← → steer · ↑ throttle · ↓ brake",
      make: cabinetThroughput
    },
    {
      id: "side-channel",
      name: "SIDE CHANNEL",
      genre: "STEALTH",
      tagline: "One observation is nothing. Enough of them is the leak.",
      controls: "arrows move · SPACE hold to crouch",
      make: cabinetSideChannel
    },
    {
      id: "cold-storage",
      name: "COLD STORAGE",
      genre: "HORROR",
      tagline: "Three shards, one torch, and not enough rounds.",
      controls: "arrows move · SPACE fire",
      make: cabinetColdStorage
    },
    {
      id: "block-store",
      name: "BLOCK STORE",
      genre: "SANDBOX",
      tagline: "Dig all day. Be behind a wall when the scan runs.",
      controls: "arrows move · SPACE mine or place",
      make: cabinetBlockStore
    },
    {
      id: "last-quorum",
      name: "LAST QUORUM",
      genre: "ROYALE",
      tagline: "The quorum shrinks. Outside it you are only partitioned.",
      controls: "arrows move · SPACE fire",
      make: cabinetLastQuorum
    },
    {
      id: "heartbeat",
      name: "HEARTBEAT",
      genre: "RHYTHM",
      tagline: "Four lanes of health checks. Answer them on the beat.",
      controls: "← ↑ ↓ → hit the lanes",
      make: cabinetHeartbeat
    },
    {
      id: "brute-force",
      name: "BRUTE FORCE",
      genre: "BRAWLER",
      tagline: "No cleverness, just volume. Do not get surrounded.",
      controls: "arrows move · SPACE strike",
      make: cabinetBruteForce
    },
    {
      id: "catalog",
      name: "CATALOG",
      genre: "COLLECT",
      tagline: "Every tool in the estate that nobody wrote down.",
      controls: "arrows move · SPACE bind the scope",
      make: cabinetCatalog
    }
  ];

  // Appended rather than written into the literal above, which is declared
  // before the roster exists. The line it replaces said "FOUR CABINETS READY"
  // and had already started lying by the time there were twelve.
  BOOT_LINES.push(CABINETS.length + " CABINETS READY. NONE OF THEM ARE LOAD-BEARING.");

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

  /* ---- best scores -------------------------------------------------------

     Per-cabinet bests, in localStorage next to the accessibility panel's own
     key. Every read and write is wrapped: a private window, a browser set to
     block site data, or a corrupted value all throw or return junk here, and
     none of those is a reason for the waiting room to fail to open. The score
     is a joke about metering — losing it costs nothing. */

  var BEST_KEY = "amw-arcade-best";

  function loadBest() {
    try {
      var raw = window.localStorage.getItem(BEST_KEY);
      var parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (error) {
      return {};
    }
  }

  /* Returns "" for a run that did not beat the stored best, "stored" when the
     new best was written, and "unstored" when it was a best but the write
     failed. The three are distinct because the run-complete screen tells the
     visitor their score was kept, and saying that after a quota error or in a
     window with storage blocked is simply untrue — the reload that loses it
     is coming either way, and the honest line costs nothing. */
  function recordBest(id, score) {
    var all = loadBest();
    if (typeof all[id] === "number" && all[id] >= score) return "";
    all[id] = score;
    try {
      window.localStorage.setItem(BEST_KEY, JSON.stringify(all));
    } catch (error) {
      return "unstored";
    }
    return "stored";
  }

  function inkPalette() {
    if (!contrastHigh()) return PALETTE;
    // Tracks the high-contrast block in styles.css. These had drifted: the
    // values here were still the retired charcoal-and-ember palette, so a
    // high-contrast visitor got a differently-coloured arcade to everyone
    // else's.
    return {
      bg: "#000000",
      grid: "#5b53a0",
      ink: "#ffffff",
      dim: "#ddd9ff",
      brass: "#ffd24d",
      bright: "#ffe680",
      verify: "#6cff9f",
      danger: "#ff8f85",
      wall: ["#ffffff", "#c9c4f0", "#8f86d6", "#413a7a"]
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

    var selectHead = el("div", "arcade-select-head");
    selectHead.appendChild(el("h2", "arcade-select-title", "SELECT A CABINET"));
    selectHead.appendChild(
      el("p", "arcade-credits", "CREDITS \u221e · FREE PLAY · ALSO METERED")
    );
    nodes.select.appendChild(selectHead);

    /* Genre filters. The roster is the source of truth for which ones exist,
       so adding a cabinet with a new genre grows this row on its own rather
       than needing a second list kept in step by hand. */
    var genres = ["ALL"];
    CABINETS.forEach(function (cabinet) {
      if (genres.indexOf(cabinet.genre) === -1) genres.push(cabinet.genre);
    });
    nodes.filters = el("div", "arcade-filters");
    nodes.filters.setAttribute("role", "group");
    nodes.filters.setAttribute("aria-label", "Filter cabinets by genre");
    genres.forEach(function (genre) {
      var chip = el("button", "arcade-filter", genre);
      chip.type = "button";
      chip.setAttribute("data-genre", genre);
      chip.setAttribute("aria-pressed", genre === "ALL" ? "true" : "false");
      chip.addEventListener("click", function () {
        applyFilter(genre);
      });
      nodes.filters.appendChild(chip);
    });
    nodes.select.appendChild(nodes.filters);

    nodes.grid = el("div", "arcade-cabinets");
    CABINETS.forEach(function (cabinet) {
      var button = el("button", "arcade-cabinet");
      button.type = "button";
      button.setAttribute("data-cabinet", cabinet.id);
      button.setAttribute("data-genre", cabinet.genre);

      // Decorative: the marquee is drawn by CSS off the genre, and a screen
      // reader announcing "image" for a gradient helps nobody.
      var art = el("span", "arcade-cabinet-art");
      art.setAttribute("aria-hidden", "true");
      button.appendChild(art);

      button.appendChild(el("span", "arcade-cabinet-genre", cabinet.genre));
      button.appendChild(el("span", "arcade-cabinet-name", cabinet.name));
      button.appendChild(el("span", "arcade-cabinet-tag", cabinet.tagline));
      button.appendChild(el("span", "arcade-cabinet-controls", cabinet.controls));
      button.appendChild(el("span", "arcade-cabinet-best", ""));
      button.addEventListener("click", function () {
        startGame(cabinet.id);
      });
      nodes.grid.appendChild(button);
    });
    nodes.select.appendChild(nodes.grid);

    /* Attract mode. A cabinet plays itself under the grid, which is the one
       piece of arcade furniture that cannot be faked with CSS: it has to be a
       real cabinet running real frames, or it is a video of a game rather than
       the game. Reduced motion gets a still frame instead. */
    nodes.attract = el("div", "arcade-attract");
    nodes.attractCanvas = el("canvas", "arcade-attract-canvas");
    nodes.attractCanvas.width = W;
    nodes.attractCanvas.height = H;
    nodes.attractCanvas.setAttribute("aria-hidden", "true");
    nodes.attract.appendChild(nodes.attractCanvas);
    nodes.attractLabel = el("p", "arcade-attract-label", "");
    nodes.attract.appendChild(nodes.attractLabel);
    nodes.select.appendChild(nodes.attract);

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
    // Lifting the pointer ends the gesture, so both the aim and any direction
    // the swipe latched have to go with it. Previously only pointerleave
    // cleared the aim and nothing ever cleared the latch, which left a
    // direction held down after the finger was gone — harmless on the
    // cabinets that latch a heading of their own, but on a first-person
    // cabinet it is a camera that never stops turning.
    input.pointerX = null;
    input.pointerY = null;
    clearDirections();
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

  /* ---- select screen behaviour ------------------------------------------ */

  var activeGenre = "ALL";

  function applyFilter(genre) {
    activeGenre = genre;
    Array.prototype.forEach.call(
      nodes.filters.querySelectorAll(".arcade-filter"),
      function (chip) {
        chip.setAttribute(
          "aria-pressed",
          chip.getAttribute("data-genre") === genre ? "true" : "false"
        );
      }
    );
    var shown = 0;
    visibleCabinets().forEach(function (button) {
      var match = genre === "ALL" || button.getAttribute("data-genre") === genre;
      // `hidden` rather than display:none in CSS: a filtered-out tile must
      // leave the tab order as well as the layout, and hidden does both
      // without the stylesheet having to know about filtering at all.
      button.hidden = !match;
      if (match) shown += 1;
    });
    // Repick immediately rather than letting the running demo finish. It draws
    // from the filtered pool, so leaving it alone shows a PUZZLE cabinet under
    // an FPS-only filter until it happens to die — and under reduced motion,
    // where no loop is running to cycle it, indefinitely.
    pickAttract();
    drawAttract();

    announce(
      shown + (shown === 1 ? " cabinet" : " cabinets") +
      (genre === "ALL" ? " available." : " in " + genre + ".")
    );
  }

  function visibleCabinets() {
    return Array.prototype.slice.call(nodes.grid.querySelectorAll(".arcade-cabinet"));
  }

  function refreshBests() {
    var best = loadBest();
    visibleCabinets().forEach(function (button) {
      var id = button.getAttribute("data-cabinet");
      var score = best[id];
      var label = button.querySelector(".arcade-cabinet-best");
      if (label) label.textContent = typeof score === "number" ? "BEST " + score : "UNPLAYED";
    });
  }

  /* Arrow keys walk the tile grid. The tiles are buttons, so Tab already
     works; this is the control an actual cabinet select would have, and it
     matters most on the twelve-tile grid where tabbing across three rows is
     tedious. Columns are read from layout rather than assumed, because the
     grid reflows to one column on a phone. */
  function onGridKey(event, slot) {
    if (screen !== "select") return;
    // Keyed off the resolved slot, not event.key: WASD aliases the arrows
    // everywhere else in the arcade, and reading the raw key here made this
    // the one screen where the two sets disagreed — W and S silently did
    // nothing, and the caller had already swallowed them.
    var dir = { left: -1, right: 1, up: -1, down: 1 }[slot];
    if (dir == null) return;
    var tiles = visibleCabinets().filter(function (b) { return !b.hidden; });
    var index = tiles.indexOf(doc.activeElement);
    if (index === -1) return;
    event.preventDefault();

    var step = 1;
    if (slot === "up" || slot === "down") {
      var top = tiles[0].offsetTop;
      var perRow = tiles.filter(function (b) { return b.offsetTop === top; }).length;
      step = Math.max(1, perRow);
    }
    var next = index + dir * step;
    if (next < 0 || next >= tiles.length) return;
    tiles[next].focus();
  }

  /* ---- attract mode ------------------------------------------------------

     A cabinet playing itself while nobody is at the controls. The demo hands
     are deliberately mediocre: inputs are re-rolled a few times a second, so
     it looks like someone is playing rather than like a scripted replay, and
     it dies often enough to cycle through the roster. */

  var attract = null;
  var attractTimer = 0;
  var attractInput = { left: false, right: false, up: false, down: false, fire: false, pointerX: null, pointerY: null };
  var attractRoll = 0;

  function pickAttract() {
    var pool = CABINETS.filter(function (c) {
      return activeGenre === "ALL" || c.genre === activeGenre;
    });
    if (!pool.length) pool = CABINETS;
    var cabinet = pool[Math.floor(random() * pool.length)];
    var instance = cabinet.make(random);
    instance.reset();
    attract = { cabinet: cabinet, game: instance };
    attractTimer = 0;
    if (nodes.attractLabel) {
      nodes.attractLabel.textContent = "ATTRACT MODE — " + cabinet.name + " · " + cabinet.genre;
    }
  }

  function drawAttract() {
    if (!attract || !nodes.attractCtx) return;
    var ctx = nodes.attractCtx;
    var ink = inkPalette();
    ctx.fillStyle = ink.bg;
    ctx.fillRect(0, 0, W, H);
    attract.game.draw(ctx, ink);
    ctx.fillStyle = ink.dim;
    ctx.font = '8px "IBM Plex Mono", monospace';
    ctx.textAlign = "center";
    ctx.fillText("DEMO", W / 2, H - 6);
    ctx.textAlign = "left";
  }

  function tickAttract(dt) {
    if (!attract) pickAttract();
    if (!attract) return;

    attractTimer += dt;
    attractRoll -= dt;
    if (attractRoll <= 0) {
      attractRoll = 0.18 + random() * 0.3;
      attractInput.left = random() < 0.3;
      attractInput.right = !attractInput.left && random() < 0.35;
      attractInput.up = random() < 0.45;
      attractInput.down = !attractInput.up && random() < 0.12;
      attractInput.fire = random() < 0.55;
    }

    if (!attract.game.over) attract.game.update(STEP, attractInput);
    drawAttract();

    // Cycle on death or on a timer, whichever comes first: some cabinets are
    // survivable enough for a demo hand to sit on one board indefinitely.
    if (attract.game.over || attractTimer > 14) pickAttract();
  }

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
    refreshBests();
    if (nodes.attractCanvas && !nodes.attractCtx) {
      nodes.attractCtx = nodes.attractCanvas.getContext("2d");
    }
    if (prefersStaticMotion()) {
      // One still frame rather than a running demo: an attract loop is exactly
      // the kind of unrequested motion this preference exists to stop.
      if (!attract) pickAttract();
      drawAttract();
    }

    var first = nodes.select.querySelector(".arcade-cabinet:not([hidden])");
    var active = doc.activeElement;
    var activeVisible =
      active &&
      active !== doc.body &&
      overlay.contains(active) &&
      active.offsetParent !== null;
    if (first && isOpen && !activeVisible) first.focus();
    announce(
      "Cabinet select. " + CABINETS.length + " cabinets available." +
      " Use arrow keys to move between cabinets."
    );
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
    if (cabinet.id === "heartbeat") return " · or swipe toward a lane";
    if (cabinet.id === "escalation") return " · or swipe to choose, tap to commit";
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
    var bestState = recordBest(current.id, game.score);
    nodes.over.appendChild(
      el("p", "arcade-over-score", game.score + " RECEIPTS SCORED. NONE OF THEM COUNT.")
    );
    if (bestState) {
      nodes.over.appendChild(
        el(
          "p",
          "arcade-over-best",
          bestState === "stored"
            ? "NEW BEST ON " + current.name + " — STORED IN THIS BROWSER ONLY"
            : "NEW BEST ON " + current.name + " — NOT SAVED, STORAGE IS UNAVAILABLE"
        )
      );
    }
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
    } else if (screen === "select") {
      if (!prefersStaticMotion()) tickAttract(dt);
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
    // On the select screen the arrows walk the tile grid instead. Space is
    // deliberately left alone here so it still activates the focused tile.
    if (screen === "select" && slot !== "fire") {
      onGridKey(event, slot);
      return;
    }
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
