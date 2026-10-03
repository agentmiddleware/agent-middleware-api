// Run with: node --test tests/test_arcade_regressions.mjs
// Actual gameplay factories; Canvas recording and animation helpers are local stubs.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../site/arcade.js", import.meta.url), "utf8");
function extract(name) {
  const start = source.indexOf("  function " + name + "(");
  assert(start >= 0, name);
  const end = source.indexOf("\n  function ", start + 1);
  return source.slice(start, end < 0 ? undefined : end);
}
const effect = () => new Proxy({}, { get: () => () => {} });
const scope = { makeFx: effect, makeParticles: effect };
vm.runInNewContext("var W=320,H=240;\n" + [
  "makeRandom", "clamp", "cabinetKeyRotation", "cabinetHappyPath", "cabinetTapForge"
].map(extract).join("\n"), scope);

for (const seed of [2, 3, 5]) {
  test(`Key Rotation seed ${seed} grants invulnerability after one hit`, () => {
    const game = scope.cabinetKeyRotation(scope.makeRandom(seed));
    game.reset();
    let lastHit = -Infinity;
    for (let frame = 0; frame < 6000 && !game.over; frame++) {
      const before = game.lives;
      game.update(1 / 60, {});
      assert(before - game.lives <= 1, `multiple hits at frame ${frame}`);
      assert(game.lives >= 0);
      if (game.lives < before) {
        assert((frame - lastHit) / 60 >= 1.4 - 1e-9);
        lastHit = frame;
      }
    }
    assert.notEqual(lastHit, -Infinity, "simulation must exercise collisions");
    assert.equal(game.lives, 0);
    game.update(1 / 60, {});
    assert.equal(game.lives, 0);
  });
}

function playerRect(game) {
  const rects = [];
  const ctx = new Proxy({}, {
    get(target, key) {
      if (key === "fillRect") return (...rect) => rects.push({ colour: target.fillStyle, rect });
      return () => {};
    },
    set(target, key, value) { target[key] = value; return true; }
  });
  game.draw(ctx, { bg: "bg", grid: "grid", wall: ["w0", "w1", "w2"], brass: "brass", bright: "bright", danger: "danger", verify: "verify", dim: "dim" });
  return rects.find(({ colour, rect }) => colour === "verify" && rect[2] === 8 && rect[3] === 12).rect;
}

test("Happy Path visible feet meet the ground before and after a jump", () => {
  const game = scope.cabinetHappyPath(scope.makeRandom(1));
  game.reset();
  assert.deepEqual(playerRect(game), [26, 194, 8, 12]);
  game.update(1 / 60, { fire: true });
  assert(playerRect(game)[1] < 194, "jump rises above ground");
  for (let frame = 0; frame < 120; frame++) game.update(1 / 60, {});
  assert.deepEqual(playerRect(game), [26, 194, 8, 12]);
  assert.equal(game.lives, 3);
});

test("Happy Path uses the same visible origin on a platform landing", () => {
  // A constant random stream creates the first ledge at x=106, y=172.
  const game = scope.cabinetHappyPath(() => 0);
  game.reset();
  for (let frame = 0; frame < 17; frame++) game.update(1 / 60, { right: true });
  game.update(1 / 60, { right: true, fire: true });
  for (let frame = 0; frame < 30; frame++) game.update(1 / 60, { right: true });
  // Stop on the ledge; descending physics keeps the body at its top for each update.
  for (let frame = 0; frame < 5; frame++) {
    game.update(1 / 60, {});
    const body = playerRect(game);
    assert.equal(body[1] + body[3], 172);
  }
  assert.equal(game.lives, 3);
});

function buySigner() {
  const game = scope.cabinetTapForge(scope.makeRandom(1));
  game.reset();
  for (let tap = 0; tap < 26; tap++) {
    game.update(0, { fire: true });
    game.update(0, {});
  }
  assert.equal(game.score, 25, "buying a signer spends bank, not quota score");
  return game;
}

test("Tap Forge carries passive quota fractions across frame rates", () => {
  for (const hz of [1, 30, 60]) {
    const game = buySigner();
    for (let frame = 0; frame < 9 * hz; frame++) game.update(1 / hz, {});
    assert.equal(game.score, 35, `${hz}Hz must preserve 10.8 earned quota units`);
    assert.equal(game.lives, 3);
    game.update(0, { fire: true });
    assert.equal(game.score, 36, "manual mint still adds a whole unit");
    game.reset();
    game.update(1, {});
    assert.equal(game.score, 0, "reset clears all carried earnings");
  }
});
