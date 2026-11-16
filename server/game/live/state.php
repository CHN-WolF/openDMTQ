<?php
/*
 * GET /live/state?ids=<id1>,<id2>,...&lang=ko|en: what the phone's runtime and the PC player poll. Whether this player
 * is on air (their own switch and the server's), the upload key and settings while so, and a two-line notice to show once,
 * between songs, after every change of either switch. See docs/live.md.
 */
require __DIR__ . '/../../portal/live_lib.php';

// The notices, by what changed, in the phone's own language: a short title, then where the broadcast and its recording can
// be watched (the site's LIVE page, named by the server's name as the site shows it), or what the server's switch means
// for it. A player hears of every change of their own switch, and of every change of the server's while their own is on:
// "on" and "off" are their own switch flipped while broadcasts are on for the server; "wait" and "held" the same while
// they are off (nothing goes out until the server's are on again); "end" is the server's switch turned off under a player
// switched on. The server's switch turned on under a player switched on is "on" too. Phones show both lines in their
// toast; the PC player draws the first as the title of its card and the second under it.
const TOASTS = [
    'ko' => ['on' => "이 플레이를 방송하고 있어요\n%s 사이트 LIVE에서 지금도, 끝난 뒤에도 볼 수 있어요",
             'off' => "방송을 마쳤어요\n%s 사이트 LIVE에서 다시 볼 수 있어요",
             'end' => "방송을 마쳤어요\n이 서버의 방송이 꺼졌어요",
             'wait' => "방송을 켜 두었어요\n이 서버의 방송이 켜지면 시작해요",
             'held' => "방송을 꺼 두었어요\n이 서버의 방송이 켜져도 방송하지 않아요"],
    'en' => ['on' => "Broadcasting your play\nWatch it now or later under LIVE on %s",
             'off' => "Your broadcast has ended\nWatch the replay under LIVE on %s",
             'end' => "Your broadcast has ended\nBroadcasts are off on this server",
             'wait' => "Your broadcast is switched on\nIt starts once broadcasts are on for this server",
             'held' => "Your broadcast is switched off\nIt stays off when broadcasts come back on for this server"],
];

// Broadcasts on or off for the whole server: while off, nobody is on, whatever their own switch says.
$enabled = live_enabled();
// What the stream should be, for the phone's encoder, by the owner's quality; the same whether on or off. Then what the
// player's own switch and the server's say, and the notice waiting, if any: its words, its number (higher for each new
// one, so a player can tell a new notice from one it showed, even with the same words) and its kind (a key of TOASTS).
$reply = ['on' => false] + live_stream_settings()
    + ['switch' => false, 'broadcasts' => $enabled, 'toast' => '', 'toast_id' => 0, 'toast_kind' => ''];

/*
 * Hands out the player's waiting notice once, in the phone's language, as [words, number, kind]: only the request whose
 * update really cleared it returns it, also when two polls cross. A newer notice written meanwhile (another number) stays
 * for the next poll. It waits while the player is in a song.
 */
function live_take_toast(array $row): array
{
    if ($row['toast'] === '' || live_in_song($row)) {
        return ['', 0, ''];
    }
    $rw = live_db(true);
    $q = $rw ? @$rw->prepare("UPDATE LiveSwitch SET toast = '' WHERE guid = :g AND toast = :t AND toast_id = :n") : false;
    if (!$q) {
        return ['', 0, ''];
    }
    $q->bindValue(':g', (int)$row['guid'], SQLITE3_INTEGER);
    $q->bindValue(':t', $row['toast'], SQLITE3_TEXT);
    $q->bindValue(':n', (int)$row['toast_id'], SQLITE3_INTEGER);
    if (!@$q->execute() || $rw->changes() !== 1) {
        return ['', 0, ''];
    }
    $lang = ($_GET['lang'] ?? '') === 'ko' ? 'ko' : 'en';
    if (!isset(TOASTS[$lang][$row['toast']])) {
        return ['', 0, ''];
    }
    // The server's name as the site shows it, from the site's own server_name(): its library is loaded for a notice
    // handed out alone, which is rare, and not for every poll.
    require_once __DIR__ . '/../../portal/lib.php';
    return [sprintf(TOASTS[$lang][$row['toast']], server_name()), (int)$row['toast_id'], (string)$row['toast']];
}

$db = live_db();
$row = $db ? live_player($db, live_ids((string)($_GET['ids'] ?? ''))) : null;
// New players start switched on when the owner says so (the Broadcasts page, or LIVE_DEFAULT=on before the owner chose),
// with broadcasts on for the server or off: a player whose switch nobody has touched yet has it on, and hears so ("on",
// or "wait" while the server's are off). A row can exist before that, from song tracking; only the admin pages set
// changed_at, and what they set stays.
if ($row && !$row['live'] && live_settings()['new_players']) {
    $rw = live_db(true);
    $token = bin2hex(random_bytes(16));
    $kind = $enabled ? 'on' : 'wait';
    $q = $rw ? @$rw->prepare("INSERT INTO LiveSwitch (guid, live, token, toast, toast_id, changed_at) VALUES (:g, 1, :t, :k, 1, :now)
                              ON CONFLICT (guid) DO UPDATE SET live = 1, token = excluded.token, toast = excluded.toast,
                                  toast_id = LiveSwitch.toast_id + 1, changed_at = excluded.changed_at
                              WHERE LiveSwitch.live = 0 AND LiveSwitch.changed_at IS NULL") : false;
    if ($q) {
        $q->bindValue(':g', (int)$row['guid'], SQLITE3_INTEGER);
        $q->bindValue(':t', $token, SQLITE3_TEXT);
        $q->bindValue(':k', $kind, SQLITE3_TEXT);
        $q->bindValue(':now', time(), SQLITE3_INTEGER);
        if (@$q->execute() && $rw->changes() === 1) {
            // The row as written, its notice's number included.
            $row = live_player($rw, live_ids((string)($_GET['ids'] ?? ''))) ?? $row;
        }
    }
}
if ($row) {
    $reply['switch'] = (bool)$row['live'];
    // On air only with both switches on; the key goes with it.
    if ($enabled && $row['live'] && (string)$row['token'] !== '') {
        $reply['on'] = true;
        $reply['token'] = $row['token'];
    }
    // The notice waiting for this player, if any, once.
    [$reply['toast'], $reply['toast_id'], $reply['toast_kind']] = live_take_toast($row);
}
// Leftovers of stopped streams go now and then; phones poll even when nobody watches.
live_sweep();

header('Content-Type: application/json');
header('Cache-Control: no-store');
// The Korean stays readable in the reply.
echo json_encode($reply, JSON_UNESCAPED_UNICODE);
