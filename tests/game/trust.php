<?php
/*
 * What a call may change of a player's game state, and whose game may make it: tests/game/protocol.sh runs this inside the
 * throwaway server, after tests/game/state.php, with the stand-in catalog it wrote (custom/catalog.json: chart 61 costs 350
 * MAX POINT, product 50001 is a pack of 2,500 MAX POINT for 10 Q, the note 90002 nobody has at first). Each player signs in
 * as the game does (the platform's login by the phone's device id, then the game's own login) and signs its requests with
 * the key that login gave it:
 *
 *   - a banned player's call is refused whatever form its id takes ("9402x", " 9402", 9402.0), nothing bought.
 *
 * Usage: php tests/game/trust.php <database file> <base address of the server>      (exit status 0 when every check passed)
 */

$app = getenv('OPENDMTQ_APP') ?: '/opt/opendmtq';
require_once "$app/game/src/config.php";
[$_, $path, $base] = $argv;

// One line per check, as protocol.py prints them; the count of failures decides the exit status.
$failures = 0;
function check(string $name, bool $ok, string $detail = ''): void
{
    global $failures;
    if (!$ok) {
        $failures++;
    }
    echo ($ok ? 'PASS ' : 'FAIL ') . $name . ($detail !== '' && !$ok ? " | $detail" : '') . "\n";
}

$db = new SQLite3($path);
// The server is running on the same database: wait for its writers rather than fail.
$db->busyTimeout(5000);
// Players no other check uses, each with an account as the platform's login makes one, by a device id of its own.
foreach ([9401 => 'Ana', 9402 => 'Ben', 9403 => 'Cy', 9404 => 'Dee'] as $id => $name) {
    $db->exec("INSERT INTO Member (id, nickname, guid, puid, udid, code) VALUES ($id, '$name', '$id', '$id', 'trust-$id', 'trustcode$id')");
}

/* A POST of $body to the server's own address with $headers: [status, body]. */
function post(string $url, string $body, array $headers): array
{
    $context = stream_context_create(['http' => ['method' => 'POST', 'content' => $body, 'ignore_errors' => true, 'timeout' => 15,
        'header' => implode("\r\n", $headers) . "\r\n"]]);
    $raw = @file_get_contents($url, false, $context);
    // The status from the reply's first line ("HTTP/1.1 200 OK"), 0 when nothing came back.
    $status = isset($http_response_header[0]) ? (int)(explode(' ', $http_response_header[0])[1] ?? 0) : 0;
    return [$status, (string)$raw];
}

/*
 * A phone's sign-in as the game makes it: the platform's login with the phone's device id, then the game's own login with
 * the access token it gave. [the player id, the key the login reply gave the game to sign with], or [0, ''].
 */
function sign_in(string $base, string $udid): array
{
    [, $raw] = post("$base/api/accounts/v3/global/login_dmq", "app_id=576&udid=$udid&device_cd=ANDROID",
        ['Content-Type: application/x-www-form-urlencoded']);
    $token = json_decode($raw, true)['value']['access_token'] ?? '';
    // The game's login, signed with the empty key the game has before its first login, as the game sends it.
    [, $reply] = batch($base, '', [['user.loginV2', [$token, ' ', '', '1.3.4', 'ANDROID', 'KR']]]);
    $result = $reply[0]['result'] ?? [];
    return [(int)($result['guid'] ?? 0), (string)($result['SECRET_KEY'] ?? '')];
}

/* The calls of one request as the game sends them, signed with $key: [HTTP status, the replies ({result, error, id}) in order]. */
function batch(string $base, string $key, array $calls): array
{
    $list = [];
    foreach ($calls as $i => [$method, $params]) {
        $list[] = ['id' => $i, 'method' => $method, 'params' => $params];
    }
    $body = json_encode($list);
    [$status, $raw] = post("$base/DMQ/rpc", $body, ['Content-Type: application/json', 'Fp: ' . md5($key . $body)]);
    return [$status, json_decode($raw, true) ?: []];
}

/* One call, signed with $key: its reply ({result, error, id}), or null. */
function call(string $base, string $key, string $method, array $params): ?array
{
    return batch($base, $key, [[$method, $params]])[1][0] ?? null;
}

/* A player's state as the admin pages keep it (game.py write_state): MAX, Q, experience, their own unlimited switch. */
function keep(SQLite3 $db, int $guid, int $mpoint, int $qpoint, int $exp, int $unlimited = 0): void
{
    $db->exec("INSERT INTO PlayerState (guid, mpoint, qpoint, exp, unlimited, changed_at) VALUES ($guid, $mpoint, $qpoint, $exp, $unlimited, " . time() . ")
               ON CONFLICT (guid) DO UPDATE SET mpoint = excluded.mpoint, qpoint = excluded.qpoint, exp = excluded.exp, unlimited = excluded.unlimited");
}

/* What the player keeps, as the database has it: "MAX/Q". */
function kept(SQLite3 $db, int $guid): string
{
    return (string)$db->querySingle("SELECT mpoint || '/' || qpoint FROM PlayerState WHERE guid = $guid");
}

// The players' sign-ins, before any ban: each one's own key.
$keys = [];
foreach ([9401, 9402, 9403, 9404] as $guid) {
    [$got, $key] = sign_in($base, "trust-$guid");
    $keys[$guid] = $key;
    check("a player signs in as the game does, and the login gives the game a key to sign with ($guid)", $got === $guid && $key !== '',
        json_encode([$got, $key]));
}

// ------------------------------------------------------------------ GAME-100: a ban, whatever form the id takes

keep($db, 9402, 1000, 1000, 0);
$db->exec("INSERT INTO PlayerBan (guid, reason, since, until, by) VALUES (9402, 'Made-up scores', " . time() . ", NULL, 'admin')");
foreach (['9402x', ' 9402', 9402.0, '9402'] as $form) {
    // A purchase of the pack of MAX POINT for Q, then the balance, in one request as the game sends a purchase.
    [$status, $r] = batch($base, $keys[9402], [['shop.buyProductByQPoint', [$form, 50001, 0]], ['game.getUserAsset', [$form]]]);
    check('GAME-100 a banned player\'s call is refused with the id as ' . json_encode($form) . ': the purchase and the balance alike',
        $status === 200 && ($r[0]['error']['code'] ?? null) === 'SVC.05403' && ($r[1]['error']['code'] ?? null) === 'SVC.05403',
        json_encode([$status, $r[0]['error'] ?? $r[0]['result'] ?? null, $r[1]['error'] ?? null]));
}
check('GAME-100 nothing was bought for the banned player and nothing was paid', kept($db, 9402) === '1000/1000'
    && (int)$db->querySingle('SELECT COUNT(*) FROM PlayerPurchase WHERE guid = 9402') === 0,
    kept($db, 9402) . ' ' . $db->querySingle('SELECT COUNT(*) FROM PlayerPurchase WHERE guid = 9402'));

exit($failures ? 1 : 0);
