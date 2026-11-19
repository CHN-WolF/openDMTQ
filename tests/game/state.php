<?php
/*
 * A player's game state as the game server keeps it and tells the game (src/player.php): tests/game/protocol.sh runs this
 * inside the throwaway server, after the contract, with the stand-in catalog it wrote (custom/catalog.json). The admin pages
 * write the same tables (tools/opendmtq_tools/admin/game.py); here they are written as those pages write them, and what the
 * game is told is read through its own calls, each player signed in as the game signs in and signing as the game signs:
 *
 *   - a player the server has kept nothing of has what a new player starts with (999,999 of each, level 99);
 *   - a kept state is what getUserAsset tells (the level worked out of the experience, Q as text);
 *   - unlimited, the player's own or the server's: the figure of no end, nothing taken, the purchase kept;
 *   - a purchase takes its price and is kept; one the player cannot pay for, or an owned item, changes nothing; a priced
 *     pack of MAX POINT gives its amount, a free one nothing;
 *   - a save earns 150 MAX POINT and 10 experience, the level going up past a level's end, within what the game shows;
 *   - a chart that costs MAX POINT is paid for as its play starts, never below 0;
 *   - items given and taken are what shop.getOwnItemList lists;
 *   - a ban refuses the game's sign-in and every call of the player's, with the notice that says why over the game, no
 *     broadcast, and the site's and the PC client's sign-ins refused with the reason; an ended ban lets them in;
 *   - the rankings and the achievements follow each player's level.
 *
 * Usage: php tests/game/state.php <database file> <base address of the server>      (exit status 0 when every check passed)
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
// Players no other check uses, each with an account as the game's login makes one: numbers far above the others'.
foreach ([9201 => 'Gina', 9202 => 'Hal', 9203 => 'Ike', 9204 => 'Jun'] as $id => $name) {
    $db->exec("INSERT INTO Member (id, nickname, guid, puid, udid, code) VALUES ($id, '$name', '$id', '$id', 'protocol-state-$id', 'statecode$id')");
}

// The key each player's game login gave, by player: the game signs every request after its login with it.
$KEYS = [];

/*
 * The calls of one request as the game sends them, signed with the key the game login gave the player the first call names
 * (an empty one for a player not signed in, as the game signs before its login): [HTTP status, the replies ({result, error,
 * id}) in order].
 */
function batch(string $base, array $calls): array
{
    global $KEYS;
    $list = [];
    foreach ($calls as $i => [$method, $params]) {
        $list[] = ['id' => $i, 'method' => $method, 'params' => $params];
    }
    $body = json_encode($list);
    $first = $calls[0][1][0] ?? null;
    $key = is_int($first) ? ($KEYS[$first] ?? '') : '';
    $context = stream_context_create(['http' => ['method' => 'POST', 'content' => $body, 'ignore_errors' => true, 'timeout' => 15,
        'header' => "Content-Type: application/json\r\nFp: " . md5($key . $body) . "\r\n"]]);
    $raw = @file_get_contents("$base/DMQ/rpc", false, $context);
    $status = isset($http_response_header[0]) ? (int)(explode(' ', $http_response_header[0])[1] ?? 0) : 0;
    return [$status, json_decode((string)$raw, true) ?: []];
}

/* True when a reply has the key and it is null: what ?? cannot tell from a missing key. */
function is_null_at(?array $reply, string $key): bool
{
    return is_array($reply) && array_key_exists($key, $reply) && $reply[$key] === null;
}

/* One call: its reply ({result, error, id}), or null. */
function call(string $base, string $method, array $params): ?array
{
    return batch($base, [[$method, $params]])[1][0] ?? null;
}

/* What the game's top bar would show of a player: [level, exp, MAX, Q] from getUserAsset. */
function asset(string $base, int $guid): array
{
    $a = call($base, 'game.getUserAsset', [$guid])['result'] ?? [];
    return [$a['lev'] ?? null, $a['exp'] ?? null, $a['mpoint'] ?? null, $a['amt_total'] ?? null];
}

/* The player's items as shop.getOwnItemList lists them. */
function items(string $base, int $guid): array
{
    return array_map(fn($i) => $i['item_id'], call($base, 'shop.getOwnItemList', [$guid])['result'] ?? []);
}

/* The access token the platform's login hands a phone of device id $udid, as the game's SDK asks for it at each start. */
function platform_token(string $base, string $udid): string
{
    $context = stream_context_create(['http' => ['method' => 'POST', 'content' => "app_id=576&udid=$udid&device_cd=ANDROID",
        'ignore_errors' => true, 'timeout' => 15, 'header' => "Content-Type: application/x-www-form-urlencoded\r\n"]]);
    return (string)(json_decode((string)@file_get_contents("$base/api/accounts/v3/global/login_dmq", false, $context), true)['value']['access_token'] ?? '');
}

/* A phone's sign-in as the game makes it, the platform's login then the game's: the key it then signs with is kept. */
function sign_in(string $base, string $udid): void
{
    global $KEYS;
    $login = call($base, 'user.loginV2', [platform_token($base, $udid), ' ', '', '1.3.4', 'ANDROID', 'KR'])['result'] ?? [];
    $KEYS[(int)($login['guid'] ?? 0)] = (string)($login['SECRET_KEY'] ?? '');
}

/*
 * A play as the game makes one: START (getPreviewPlayInfo, which gives the play's token), then the save as the result screen
 * sends it, with that token: 100 notes at 100 % on $chart. The save's result, or null.
 */
function save(string $base, int $guid, int $chart): ?array
{
    $token = call($base, 'game.getPreviewPlayInfo', [$guid, $chart])['result']['game_token'] ?? '';
    $stat = array_fill(0, 13, 0);
    $stat[12] = 100;
    return call($base, 'game.savePlayResult', [$guid, $chart, $stat, 100, 0, [0, 0, 0], [0, 0, 0], $token])['result'] ?? null;
}

/* A player's state as the admin pages keep it (game.py write_state): MAX, Q, experience, their own unlimited switch. */
function keep(SQLite3 $db, int $guid, int $mpoint, int $qpoint, int $exp, int $unlimited = 0): void
{
    $db->exec("INSERT INTO PlayerState (guid, mpoint, qpoint, exp, unlimited, changed_at) VALUES ($guid, $mpoint, $qpoint, $exp, $unlimited, " . time() . ")
               ON CONFLICT (guid) DO UPDATE SET mpoint = excluded.mpoint, qpoint = excluded.qpoint, exp = excluded.exp, unlimited = excluded.unlimited");
}

/* A GET of the server's own address: [status, body]. */
function get(string $url, array $headers = []): array
{
    $context = stream_context_create(['http' => ['method' => 'GET', 'ignore_errors' => true, 'timeout' => 15, 'header' => implode("\r\n", $headers)]]);
    $raw = @file_get_contents($url, false, $context);
    $status = isset($http_response_header[0]) ? (int)(explode(' ', $http_response_header[0])[1] ?? 0) : 0;
    return [$status, (string)$raw];
}

/* A POST of raw bytes with headers, as a phone's upload sends its video: the status. */
function post_raw(string $url, string $body, array $headers): int
{
    $context = stream_context_create(['http' => ['method' => 'POST', 'content' => $body, 'ignore_errors' => true, 'timeout' => 15,
        'header' => implode("\r\n", array_merge($headers, ['Content-Type: video/mp2t']))]]);
    @file_get_contents($url, false, $context);
    return isset($http_response_header[0]) ? (int)(explode(' ', $http_response_header[0])[1] ?? 0) : 0;
}

/* A form POST to the server's own address: [status, body, the reply's headers]. */
function post(string $url, array $fields): array
{
    $context = stream_context_create(['http' => ['method' => 'POST', 'content' => http_build_query($fields), 'ignore_errors' => true,
        'timeout' => 15, 'follow_location' => 0, 'header' => "Content-Type: application/x-www-form-urlencoded\r\n"]]);
    $raw = @file_get_contents($url, false, $context);
    $status = isset($http_response_header[0]) ? (int)(explode(' ', $http_response_header[0])[1] ?? 0) : 0;
    return [$status, (string)$raw, $http_response_header ?? []];
}

// Each player signs in as the game does, before any call of theirs.
foreach ([9201, 9202, 9203, 9204] as $id) {
    sign_in($base, "protocol-state-$id");
}

// ------------------------------------------------------------------ GAME-85: what a new player starts with

check('GAME-85 a player the server has kept nothing of has what a new player starts with: level 99 at its start, 999,999 of each',
    asset($base, 9201) === [99, 130408, 999999, '999999'], json_encode(asset($base, 9201)));

// ------------------------------------------------------------------ GAME-86: a kept state, as the game is told it

// Level 37 is 5,493 to 5,844 experience: half way, the top bar's gauge half full.
keep($db, 9201, 1234567, 4321, 5669);
check('GAME-86 a kept state is what getUserAsset tells: the level worked out of the experience, MAX as a number, Q as text',
    asset($base, 9201) === [37, 5669, 1234567, '4321'], json_encode(asset($base, 9201)));
// What another program might write past the game's range is read inside it.
keep($db, 9202, 500000000, -5, 999999);
check('GAME-86 a kept state past what the game shows is told within it: 99,999,999 and 0, level 99 at its start',
    asset($base, 9202) === [99, 130408, 99999999, '0'], json_encode(asset($base, 9202)));

// ------------------------------------------------------------------ GAME-88: purchases paid and kept

keep($db, 9202, 2500, 15, 644);
// A note for 2,000 MAX POINT, then a pack of 2,500 MAX POINT for 10 Q, in the request the game sends: the purchase (one
// with a MAX POINT price through buyFreeProduct, one with a Q price through buyProductByQPoint, as the client sends
// them), then the balance and the items it shows next.
[$status, $r] = batch($base, [['shop.buyFreeProduct', [9202, 90002]], ['game.getUserAsset', [9202]], ['shop.getOwnItemList', [9202]]]);
check('GAME-88 a purchase takes its price, and the reply in the same request shows the balance and the item',
    $status === 200 && is_null_at($r[0], 'error') && ($r[1]['result']['mpoint'] ?? null) === 500
    && in_array(90002, array_map(fn($i) => $i['item_id'], $r[2]['result'] ?? []), true), json_encode([$status, $r[0], $r[1]['result']['mpoint'] ?? null]));
$pack = call($base, 'shop.buyProductByQPoint', [9202, '50001', '']);
check('GAME-88 a pack of MAX POINT bought with Q gives its amount: 10 Q out, 2,500 MAX POINT in',
    is_null_at($pack, 'error') && asset($base, 9202) === [12, 644, 3000, '5'], json_encode([$pack, asset($base, 9202)]));
$short = call($base, 'shop.buyProductByQPoint', [9202, '50001', '']);
check('GAME-88 a purchase the player cannot pay for is handled without a popup and changes nothing',
    ($short['error']['code'] ?? null) === 'SVC.05008' && asset($base, 9202) === [12, 644, 3000, '5'], json_encode([$short, asset($base, 9202)]));
$twice = call($base, 'shop.buyFreeProduct', [9202, 90002]);
check('GAME-88 an item the player has already is not bought again',
    ($twice['error']['code'] ?? null) === 'SVC.05008' && asset($base, 9202)[2] === 3000, json_encode([$twice, asset($base, 9202)]));
$gift = call($base, 'shop.buyFreeProduct', [9202, 59001]);
check("GAME-88 a free pack of MAX POINT (a gift of the publisher's) gives nothing", asset($base, 9202)[2] === 3000, json_encode([$gift, asset($base, 9202)]));
// A product with a MAX POINT price sent through the Q call: its MAX POINT price all the same, no Q.
$other = call($base, 'shop.buyProductByQPoint', [9202, '90001', '']);
check('GAME-88 a MAX POINT product sent through the call for Q takes its MAX POINT price all the same',
    is_null_at($other, 'error') && asset($base, 9202) === [12, 644, 1000, '5'], json_encode([$other, asset($base, 9202)]));
$kept = $db->querySingle('SELECT COUNT(*) || \' \' || SUM(paid) FROM PlayerPurchase WHERE guid = 9202');
check('GAME-88 each purchase is kept with what was paid', $kept === '4 4010', (string)$kept);

// ------------------------------------------------------------------ GAME-87: unlimited, the player's own and the server's

keep($db, 9203, 100, 7, 0, 1);
check("GAME-87 a player's own unlimited switch: the game is told 99,999,999 of each", asset($base, 9203) === [1, 0, 99999999, '99999999'],
    json_encode(asset($base, 9203)));
$free = call($base, 'shop.buyFreeProduct', [9203, 90003]);
$row = $db->querySingle('SELECT mpoint || \' \' || qpoint FROM PlayerState WHERE guid = 9203');
check('GAME-87 unlimited: a purchase takes nothing and is kept as usual, the item theirs, the price noted with nothing paid',
    is_null_at($free, 'error') && $row === '100 7' && in_array(90003, items($base, 9203), true)
    && $db->querySingle('SELECT price || \' \' || paid FROM PlayerPurchase WHERE guid = 9203') === '2000 0', json_encode([$free, $row]));
$db->exec("UPDATE PlayerState SET unlimited = 0 WHERE guid = 9203");
check('GAME-87 unlimited off again: their own balance as it was before', asset($base, 9203) === [1, 0, 100, '7'], json_encode(asset($base, 9203)));
$db->exec("INSERT INTO GameSetting (name, value) VALUES ('unlimited', '1') ON CONFLICT (name) DO UPDATE SET value = excluded.value");
check("GAME-87 the server's unlimited switch: every player told 99,999,999 of each, whatever their own switch",
    asset($base, 9203)[2] === 99999999 && asset($base, 9201)[3] === '99999999', json_encode([asset($base, 9203), asset($base, 9201)]));
$db->exec("UPDATE GameSetting SET value = '0' WHERE name = 'unlimited'");

// ------------------------------------------------------------------ GAME-89: what a save earns

// Song 7's first 2LINE chart (make_content.php numbers nine charts a song): no other check plays it. Level 12 starts at 644
// and 13 at 748: 100 experience in, a save's 10 more passes the end.
keep($db, 9203, 99999950, 7, 740);
$saved = save($base, 9203, 55);
check("GAME-89 a save earns 150 MAX POINT and 10 experience, the level following past a level's end, never past what the game shows",
    ($saved['exp'] ?? null) === 10 && ($saved['mpoint'] ?? null) === 49 && ($saved['lev'] ?? null) === 13 && asset($base, 9203) === [13, 750, 99999999, '7'],
    json_encode([$saved['exp'] ?? null, $saved['mpoint'] ?? null, $saved['lev'] ?? null, asset($base, 9203)]));

// ------------------------------------------------------------------ GAME-90: a chart that costs MAX POINT

// Chart 61, song 7's 4LINE chart, costs 350 MAX POINT in the stand-in catalog.
keep($db, 9203, 1000, 7, 750);
call($base, 'game.getPreviewPlayInfo', [9203, 61]);
check('GAME-90 a chart that costs MAX POINT is paid for as its play starts', asset($base, 9203)[2] === 650, json_encode(asset($base, 9203)));
call($base, 'game.getPreviewPlayInfo', [9203, 55]);
check('GAME-90 a chart without a cost takes nothing', asset($base, 9203)[2] === 650, json_encode(asset($base, 9203)));
keep($db, 9203, 100, 7, 750);
call($base, 'game.getPreviewPlayInfo', [9203, 61]);
check('GAME-90 never below 0: a balance lowered meanwhile goes to 0, and the play starts', asset($base, 9203)[2] === 0, json_encode(asset($base, 9203)));
keep($db, 9203, 1000, 7, 750, 1);
call($base, 'game.getPreviewPlayInfo', [9203, 61]);
check('GAME-90 unlimited: the chart takes nothing', (int)$db->querySingle('SELECT mpoint FROM PlayerState WHERE guid = 9203') === 1000);

// ------------------------------------------------------------------ GAME-91: items given and taken

$db->exec("INSERT INTO PlayerItem (guid, item_id, owned, how, at) VALUES (9204, 90001, 1, 'given', " . time() . "), (9204, 30001, 0, 'taken', " . time() . ")");
$have = items($base, 9204);
check("GAME-91 an item given is listed as the player's, one taken is not, the rest as everyone has them",
    in_array(90001, $have, true) && !in_array(30001, $have, true) && in_array(30002, $have, true) && in_array(30001, items($base, 9201), true),
    json_encode($have));

// ------------------------------------------------------------------ GAME-94: rankings and achievements by level

// Gina's 2LINE play on song 7 puts her on the month's board; her level is 37 (GAME-86).
save($base, 9201, 56);
$ranks = call($base, 'game.getLineTopRankWithLevel', [0, 1, 50, [9201]])['result']['ranks'] ?? [];
$mine = array_values(array_filter($ranks, fn($row) => $row['guid'] === 9201));
check("GAME-94 a ranking row carries the player's own level", ($mine[0]['lev'] ?? null) === 37, json_encode($mine));
$held = array_map(fn($a) => $a['achievement_id'], call($base, 'game.getOwnAchievementList', [9204])['result']['own_achievements'] ?? []);
keep($db, 9204, 5000, 0, 644);
$after = array_map(fn($a) => $a['achievement_id'], call($base, 'game.getOwnAchievementList', [9204])['result']['own_achievements'] ?? []);
check('GAME-94 the level and MAX POINT achievements follow what the player has: level 12 holds the first, 5,000 MAX POINT none',
    array_slice($held, 0, 13) === [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 19, 20, 21] && $after === [1], json_encode([$held, $after]));

// ------------------------------------------------------------------ GAME-92: a ban, in the game

// Hal's account by the platform's login, as the game signs in: the token it hands his phone, naming his puid.
$token = platform_token($base, 'protocol-state-9202');
$db->exec("INSERT INTO PlayerBan (guid, reason, since, until, by) VALUES (9202, 'Made-up scores', " . time() . ', ' . (time() + 86400) . ", 'admin')");
$id_before = (int)$db->querySingle('SELECT COALESCE(MAX(toast_id), 0) FROM LiveSwitch WHERE guid = 9202');
$login = call($base, 'user.loginV2', [$token, ' ', '', '1.3.4', 'ANDROID', 'KR']);
check("GAME-92 a banned player's sign-in is refused with a code the game does not know: its own popup, whose CLOSE quits",
    is_null_at($login, 'result') && ($login['error']['code'] ?? null) === 'SVC.05403', json_encode($login));
[$status, $r] = batch($base, [['game.getUserAsset', [9202]], ['shop.getOwnItemList', [9202]], ['game.getSongList', []]]);
check("GAME-92 every call of the banned player's is refused the same way; a call that is no player's is answered",
    ($r[0]['error']['code'] ?? null) === 'SVC.05403' && ($r[1]['error']['code'] ?? null) === 'SVC.05403' && is_null_at($r[2], 'error'),
    json_encode([$r[0]['error'] ?? null, $r[1]['error'] ?? null, $r[2]['error'] ?? null]));
$saved = save($base, 9202, 57);
check("GAME-92 a banned player's save is not kept", $saved === null && (int)$db->querySingle('SELECT COUNT(*) FROM PlayLog WHERE user_id = 9202 AND pattern_id = 57') === 0);
// The notice the overlay and the phones show, once for that refused sign-in, in the player's language, and no broadcast:
// broadcasts on for the server and the player's own switch on, with its key, as the Broadcasts and Players pages leave them.
$db->exec("INSERT INTO LiveSetting (name, value) VALUES ('on', '1') ON CONFLICT (name) DO UPDATE SET value = '1'");
$db->exec("INSERT INTO LiveSwitch (guid, live, token) VALUES (9202, 1, 'stalekey') ON CONFLICT (guid) DO UPDATE SET live = 1, token = 'stalekey'");
[, $state] = get("$base/live/state?ids=protocol-state-9202&lang=en");
$s = json_decode($state, true) ?: [];
check('GAME-92 the refused sign-in leaves a notice with the reason and the end, and the player is not on air though switched on',
    ($s['toast_kind'] ?? null) === 'ban' && ($s['toast_id'] ?? 0) > $id_before && ($s['on'] ?? null) === false && !isset($s['token'])
    && strpos($s['toast'] ?? '', "You cannot play on this server\nMade-up scores · until ") === 0, $state);
[, $again] = get("$base/live/state?ids=protocol-state-9202&lang=ko");
check('GAME-92 the notice is handed out once; the next sign-in leaves a new one, in Korean too', (json_decode($again, true)['toast'] ?? 'x') === '',
    $again);
call($base, 'user.loginV2', [$token, ' ', '', '1.3.4', 'ANDROID', 'KR']);
[, $ko] = get("$base/live/state?ids=protocol-state-9202&lang=ko");
check('GAME-92 a second refused sign-in: a new notice', strpos(json_decode($ko, true)['toast'] ?? '', "이 서버에서 플레이할 수 없어요\nMade-up scores · ") === 0, $ko);
// Its key is right (set as the state hands one out, after the state was asked: a server that put the player on air would
// have made a new one) and its switch on: only the ban refuses it (403, which stops the phone), before anything is read.
$db->exec("INSERT INTO LiveSwitch (guid, live, token) VALUES (9202, 1, 'stalekey') ON CONFLICT (guid) DO UPDATE SET live = 1, token = 'stalekey'");
$up = post_raw("$base/live/upload?ids=protocol-state-9202&seq=0&dur=2000", "\x47" . str_repeat("\0", 187), ['X-Live-Token: stalekey']);
check("GAME-92 a banned player's upload is refused, which stops the phone", $up === 403, (string)$up);
$db->exec("UPDATE LiveSetting SET value = '0' WHERE name = 'on'");

// ------------------------------------------------------------------ GAME-93: a ban, on the site and the PC client

// An account linked to Hal, as the Accounts page makes one, with its password as the site keeps it: the table with the
// player's column the admin pages add (auth.py account_table()).
if (!in_array('guid', array_column(iterator_to_array((function () use ($db) {
    $r = $db->query('PRAGMA table_info(SiteUser)');
    while ($row = $r->fetchArray(SQLITE3_ASSOC)) {
        yield $row;
    }
})(), false), 'name'), true)) {
    $db->exec('ALTER TABLE SiteUser ADD COLUMN guid INTEGER');
}
$salt = bin2hex(random_bytes(16));
$hash = 'pbkdf2_sha256$1000$' . $salt . '$' . hash_pbkdf2('sha256', 'statepass', (string)hex2bin($salt), 1000, 64);
$db->exec("INSERT OR REPLACE INTO SiteUser (name, pass, note, admin, created_at, off, guid) VALUES ('halsite', '$hash', '', 0, " . time() . ", 0, 9202)");
[$status, $page] = post("$base/opendmtq/login.php", ['user' => 'halsite', 'password' => 'statepass']);
check("GAME-93 the site's sign-in refuses a banned player's account with the owner's reason",
    $status === 200 && strpos($page, 'This account cannot sign in until') !== false && strpos($page, 'Made-up scores') !== false, "$status");
[$status, $body] = post("$base/opendmtq/client.php?signin", ['user' => 'halsite', 'password' => 'statepass']);
$answer = json_decode($body, true) ?: [];
check("GAME-93 the PC client's sign-in refuses it too, with the reason and the end",
    $status === 403 && ($answer['error'] ?? null) === 'banned' && ($answer['reason'] ?? null) === 'Made-up scores' && is_int($answer['until'] ?? null), "$status $body");

// ------------------------------------------------------------------ GAME-92: a ban that has ended

$db->exec('UPDATE PlayerBan SET until = ' . (time() - 1) . ' WHERE guid = 9202');
$login = call($base, 'user.loginV2', [$token, ' ', '', '1.3.4', 'ANDROID', 'KR']);
check('GAME-92 a ban whose end has passed lets the player in again', is_null_at($login, 'error') && ($login['result']['guid'] ?? null) === '9202',
    json_encode($login));
[$status] = post("$base/opendmtq/client.php?signin", ['user' => 'halsite', 'password' => 'statepass']);
check('GAME-93 and their account signs in again', $status === 200, (string)$status);

exit($failures ? 1 : 0);
