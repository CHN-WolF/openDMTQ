<?php
/* MY PAGE (me.php): a signed-in player's own page and their account. What the game knows of them, read through the
   game's own replies so that it shows what the game shows; their plays and best records, a page at a time; their
   broadcasts; and what the site keeps about the account, with the three changes its owner may make to it: the password,
   the ID, and signing out everywhere else. The page and its JSON twin (me.php?json) call the same functions here, so the
   two cannot differ. Loaded by me.php after lib.php; never a page of its own (server/apache/site.conf). */

// The game's own replies, for the player's profile as the game shows it: their level, points and items
// (game.getUserAsset, game.php), the items they own (shop.getOwnItemList, shop.php) and their achievements
// (game.getOwnAchievementList, achievement.php, which game.php loads).
require_once __DIR__ . '/../game/src/game.php';
require_once __DIR__ . '/../game/src/shop.php';

// Plays and best records a page holds: as many as the admin pages' Plays tab shows at once.
const ME_PER_PAGE = 50;
// An ID, as the admin pages' Accounts page makes one (ACCOUNT_NAME in tools/opendmtq_tools/admin/auth.py): Latin letters,
// digits and . _ -, which every phone's keyboard has and no address mangles.
const ME_ID = '/^[A-Za-z0-9._-]{3,20}$/';
// A password's length, as the Accounts page takes one; longer for an account with admin rights, whose password opens the
// admin pages too (ADMIN_PASSWORD_MIN in tools/opendmtq_tools/admin/accounts.py).
const ME_PASSWORD_MIN = 6;
const ME_PASSWORD_MAX = 64;
const ME_ADMIN_PASSWORD_MIN = 10;
// The note the admin pages' setup gives the accounts it makes, kept in English whatever the page's language was (and in
// Korean by an earlier version): shown in the reader's language, as the Accounts page shows it.
const ME_SETUP_NOTES = ['made in the setup', '설정에서 만듦'];

/* ---------------------------------------------------------------------- the account */

/* The signed-in account as MY PAGE shows it, or null when nobody is signed in: 'id' (as kept), 'owner' (the server's own
   account, from .env), 'admin', 'note' (the owner's note on it), 'made' and 'last_in' (Unix times, null when not known),
   'this_in' (when this browser signed in), 'player' (the game player it is linked to, null for none). */
function me_account(): ?array
{
    $who = site_user();
    if ($who === null) {
        return null;
    }
    // When this browser signed in: its cookie says, for any account.
    $this_in = dl_signed_in_at();
    // The server's own account: its ID and password live in .env, and the accounts' table has no row for it.
    $owner = site_owner();
    if ($owner !== null && strcasecmp($owner['name'], $who) === 0) {
        return ['id' => $owner['name'], 'owner' => true, 'admin' => true, 'note' => '', 'made' => null, 'last_in' => null,
                'this_in' => $this_in, 'player' => null];
    }
    // Every column the table keeps for it; a table from before the game player's column reads as not linked.
    $db = site_db();
    $q = $db ? @$db->prepare('SELECT * FROM SiteUser WHERE name = :name') : false;
    if ($q) {
        $q->bindValue(':name', $who, SQLITE3_TEXT);
    }
    $r = $q ? @$q->execute() : false;
    $row = $r ? $r->fetchArray(SQLITE3_ASSOC) : false;
    if (!$row) {
        return null;
    }
    // The setup's own note in the reader's language; any other as the owner typed it.
    $note = (string)($row['note'] ?? '');
    return ['id' => (string)$row['name'], 'owner' => false, 'admin' => !empty($row['admin']),
            'note' => in_array($note, ME_SETUP_NOTES, true) ? tp('me.setup_note') : $note,
            'made' => isset($row['created_at']) ? (int)$row['created_at'] : null,
            'last_in' => isset($row['signed_in_at']) ? (int)$row['signed_in_at'] : null,
            'this_in' => $this_in, 'player' => isset($row['guid']) ? (int)$row['guid'] : null];
}

/* A handle on the database that writes, for MY PAGE's changes, or null while it cannot be opened. */
function me_db_write(): ?SQLite3
{
    try {
        $db = new SQLite3(DB, SQLITE3_OPEN_READWRITE);
        // A game's save may hold the database for a moment: waited out, as the game's own writers wait for each other.
        $db->busyTimeout(5000);
        return $db;
    } catch (Exception $e) {
        return null;
    }
}

/* A line in the admin pages' log of changes (their Logs page, Changes tab), as insights.audit_note() writes one there:
   when, what (the page and action, which the Logs page turns into words: logs.py CHANGE_WORDS), on what, by whom. Under
   a lock, so that a line never goes in half; a folder that cannot be written does not stop the change itself. */
function me_note(string $what, string $target, string $who): void
{
    $line = json_encode(['at' => time(), 'what' => $what, 'target' => mb_substr($target, 0, 100), 'named' => true, 'who' => $who],
        JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    @file_put_contents(odq_state_dir() . '/changes.log', $line . "\n", FILE_APPEND | LOCK_EX);
}

/* The current password checked as the sign-in checks one: under the sign-in's own limit on wrong passwords (the attempt
   counted before the password is compared, and a right one gives its place back), a wrong one taking a second. Returns ''
   when it is right, else the words' key: signin.throttled or me.wrong_current. */
function me_check_current(array $row, string $current): string
{
    $attempt = dl_attempt_begin((string)$row['name']);
    if ($attempt === null) {
        return 'signin.throttled';
    }
    if (!site_pass_ok((string)$row['pass'], $current)) {
        // The attempt stays counted as a failure. Slow down guessing, as the sign-in page does.
        sleep(1);
        return 'me.wrong_current';
    }
    dl_attempt_succeeded($attempt);
    return '';
}

/* A password as the accounts' table keeps one, the same way the admin pages write it (account_hash() in
   tools/opendmtq_tools/admin/auth.py): pbkdf2_sha256$<rounds>$<salt, hex>$<hash, hex>, which site_pass_ok() reads. */
function me_hash(string $password): string
{
    $salt = random_bytes(16);
    return 'pbkdf2_sha256$' . SITE_ROUNDS . '$' . bin2hex($salt) . '$' . hash_pbkdf2('sha256', $password, $salt, SITE_ROUNDS, 64);
}

/* What stands in the way of a change of the signed-in account, before anything is checked: the key of the words, or ''.
   The server's own account changes on the admin pages' Server page; a visitor not signed in has nothing to change. */
function me_changeable(?array $account): string
{
    if ($account === null) {
        return 'me.signed_out';
    }
    return $account['owner'] ? 'me.owner_pw' : '';
}

/* The signed-in account's password changed to $new (typed twice, $again), its current one ($current) checked first.
   The other browsers' sign-ins end with the old password (their cookies were signed with it); this browser's cookie is
   made again with the new one, so it stays signed in. Returns '' when done, else [field, key]: the field the words go
   under (current, password, password2, or '' for above the form) and the key of the words. */
function me_change_password(string $current, string $new, string $again)
{
    $account = me_account();
    $stop = me_changeable($account);
    if ($stop !== '') {
        return ['', $stop];
    }
    // What is missing or wrong in the form itself first: nothing is counted for those.
    if ($current === '') {
        return ['current', 'me.missing_current'];
    }
    if ($new === '') {
        return ['password', 'me.missing_new'];
    }
    $min = $account['admin'] ? ME_ADMIN_PASSWORD_MIN : ME_PASSWORD_MIN;
    if (mb_strlen($new) < $min || mb_strlen($new) > ME_PASSWORD_MAX) {
        return ['password', $account['admin'] ? 'me.bad_admin_password' : 'me.bad_password'];
    }
    if ($again !== $new) {
        return ['password2', 'me.mismatch'];
    }
    $row = site_account($account['id']);
    if (!$row) {
        return ['', 'me.signed_out'];
    }
    $wrong = me_check_current($row, $current);
    if ($wrong !== '') {
        return [$wrong === 'signin.throttled' ? '' : 'current', $wrong];
    }
    $db = me_db_write();
    $q = $db ? @$db->prepare('UPDATE SiteUser SET pass = :pass WHERE name = :name') : false;
    if (!$q) {
        return ['', 'me.failed'];
    }
    $q->bindValue(':pass', me_hash($new), SQLITE3_TEXT);
    $q->bindValue(':name', (string)$row['name'], SQLITE3_TEXT);
    // Saved, or the database could not take it now (another writer past the wait, a read-only disk): said so.
    if (!@$q->execute() || $db->changes() !== 1) {
        return ['', 'me.failed'];
    }
    $db->close();
    // This browser signed in with the new password; the rest of this request reads it so.
    dl_cookie((string)$row['name']);
    site_user(true);
    me_note('site:password', (string)$row['name'], (string)$row['name']);
    return '';
}

/* The signed-in account's ID changed to $new, its current password ($current) checked first. The ID is unique whatever
   the letter case, and never the owner's (theirs lives in .env). What the account is linked to goes by the game player,
   not the ID: its plays, records, broadcasts and recordings stay; its API tokens (an account with admin rights) follow
   it. Other browsers' sign-ins name the old ID and end; this browser's cookie is made again for the new one. Returns ''
   when done, else [field, key] as me_change_password() does (fields: id, current). */
function me_change_id(string $new, string $current)
{
    $account = me_account();
    $stop = me_changeable($account);
    if ($stop !== '') {
        return ['', $stop];
    }
    if ($new === '') {
        return ['id', 'me.missing_id'];
    }
    if (!preg_match(ME_ID, $new)) {
        return ['id', 'me.bad_id'];
    }
    // The same ID, letter for letter: nothing to change.
    if ($new === $account['id']) {
        return ['id', 'me.same_id'];
    }
    // The owner's ID opens the server's own account: no account may have it, whatever its letter case.
    $owner = site_owner();
    if ($owner !== null && strcasecmp($owner['name'], $new) === 0) {
        return ['id', 'me.id_taken'];
    }
    if ($current === '') {
        return ['current', 'me.missing_current'];
    }
    $row = site_account($account['id']);
    if (!$row) {
        return ['', 'me.signed_out'];
    }
    $wrong = me_check_current($row, $current);
    if ($wrong !== '') {
        return [$wrong === 'signin.throttled' ? '' : 'current', $wrong];
    }
    $db = me_db_write();
    if (!$db || !@$db->exec('BEGIN IMMEDIATE')) {
        return ['', 'me.failed'];
    }
    // Another account with that ID in any letter case (this one's own, in other letters, is the same account).
    $taken = @$db->prepare('SELECT COUNT(*) FROM SiteUser WHERE name = :new AND name <> :old');
    $rename = @$db->prepare('UPDATE SiteUser SET name = :new WHERE name = :old');
    // The API's tokens are kept under their admin's ID (tokens.py): a table from before them has none to move.
    $tokens = @$db->prepare('UPDATE ApiToken SET admin = :new WHERE admin = :old');
    $found = false;
    if ($taken) {
        $taken->bindValue(':new', $new, SQLITE3_TEXT);
        $taken->bindValue(':old', (string)$row['name'], SQLITE3_TEXT);
        $answer = @$taken->execute();
        $found = $answer ? $answer->fetchArray(SQLITE3_NUM) : false;
    }
    if (!$rename || !$found) {
        @$db->exec('ROLLBACK');
        return ['', 'me.failed'];
    }
    if ((int)$found[0] > 0) {
        @$db->exec('ROLLBACK');
        return ['id', 'me.id_taken'];
    }
    $rename->bindValue(':new', $new, SQLITE3_TEXT);
    $rename->bindValue(':old', (string)$row['name'], SQLITE3_TEXT);
    $moved = @$rename->execute() && $db->changes() === 1;
    if ($moved && $tokens) {
        $tokens->bindValue(':new', $new, SQLITE3_TEXT);
        $tokens->bindValue(':old', (string)$row['name'], SQLITE3_TEXT);
        $moved = (bool)@$tokens->execute();
    }
    // Both or neither: an account under its new ID with its tokens left under the old one would lose them.
    if (!$moved || !@$db->exec('COMMIT')) {
        @$db->exec('ROLLBACK');
        return ['', 'me.failed'];
    }
    $db->close();
    dl_cookie($new);
    site_user(true);
    me_note('site:id', $row['name'] . ' > ' . $new, $new);
    return '';
}

/* Every sign-in of the signed-in account but this browser's ended: the moment from which its sign-ins count is now, and
   this browser's cookie is made again from now. The server's own account keeps that moment in a file of its own beside
   the database (auth.php, OWNER_SIGNED_OUT). Returns '' when done, else ['', key]. */
function me_sign_out_others()
{
    $account = me_account();
    if ($account === null) {
        return ['', 'me.signed_out'];
    }
    // The moment first, then the cookie: this browser's is made at that second or later, and so it counts.
    $now = time();
    if ($account['owner']) {
        $path = odq_state_dir() . '/' . OWNER_SIGNED_OUT;
        // A new file moved over the old one: the sign-in never reads half of one.
        if (@file_put_contents("$path.new", (string)$now) === false || !@rename("$path.new", $path)) {
            return ['', 'me.failed'];
        }
    } else {
        $db = me_db_write();
        $q = $db ? @$db->prepare('UPDATE SiteUser SET signed_out_at = :at WHERE name = :name') : false;
        if (!$q) {
            return ['', 'me.failed'];
        }
        $q->bindValue(':at', $now, SQLITE3_INTEGER);
        $q->bindValue(':name', $account['id'], SQLITE3_TEXT);
        if (!@$q->execute() || $db->changes() !== 1) {
            return ['', 'me.failed'];
        }
        $db->close();
    }
    dl_cookie($account['id']);
    site_user(true);
    me_note('site:signout', $account['id'], $account['id']);
    return '';
}

/* ---------------------------------------------------------------------- the player, as the game knows them */

/* The player's profile as the game's own replies give it (the same functions the game's requests are answered by, so
   that MY PAGE shows what the game shows): 'level', 'exp', 'mpoint' (MAX POINT), 'points' and 'cash' (the reply's
   amt_point and amt_cash), 'items' (the three in-game items by the reply's codes: fp the fever plus, gr the gauge refill,
   ab the anti break, game.getPreviewPlayInfo, each with its level), 'owned' (how many items they own) and 'equipped' (the
   item numbers in their four slots, 0 for an empty one). */
function me_game(int $guid): array
{
    $asset = odq_game_user_asset([$guid]);
    // As numbers, whatever shape the reply gives them in (text for the amounts, as the client reads them).
    $int = fn(string $key): int => (int)($asset[$key] ?? 0);
    return ['level' => $int('lev'), 'exp' => $int('exp'), 'mpoint' => $int('mpoint'), 'points' => $int('amt_point'),
            'cash' => $int('amt_cash'),
            'items' => ['fp' => $int('in_game_item1'), 'gr' => $int('in_game_item2'), 'ab' => $int('in_game_item3')],
            'owned' => count(odq_shop_own_items([$guid])),
            'equipped' => [$int('slot_item1'), $int('slot_item2'), $int('slot_item3'), $int('slot_item4')]];
}

/* The words for one of the game's achievements, made from its condition (OPENDMTQ_ACHIEVEMENTS in achievement.php): the
   server has no names for them, only what each asks for. Plain text. */
function me_achievement_words(int $id): string
{
    [$type, $value, $count] = OPENDMTQ_ACHIEVEMENTS[$id] ?? ['', 0, 0];
    switch ($type) {
        case 'QUEST':
            return tp('me.ach_level', ['n' => $value]);
        case 'LINE':
            // The song list's line codes 3 and 4 are the game's 2 LINE and 3 LINE (chart_label() in lib.php).
            return tp('me.ach_line', ['line' => ($value - 1) . ' LINE']);
        case 'ALL_COMBO':
            return tp('me.ach_combo');
        case 'PERFECT':
            return tp('me.ach_perfect');
        case 'TOTAL_MPOINT':
            return tp('me.ach_mpoint', ['n' => number_format($value)]);
        case 'SIGNATURE':
            // The difficulty by the game's own word for it (1 Normal, 2 Hard, 3 Expert).
            return tp('me.ach_clears', ['n' => $count, 'kind' => strtoupper(difficulty_name((int)$value))]);
        case 'TOTAL_SCORE':
            return tp('me.ach_total', ['n' => number_format($value)]);
    }
    // What the server never sees (effectors, items used, breaks): by its number.
    return tp('me.ach_other', ['n' => $id]);
}

/* The player's achievements as the game gives them (game.getOwnAchievementList): 'held', newest first, each with 'id',
   'words', 'points' and 'at' (when it was earned, Unix time); 'count' and 'points' of all the game has. */
function me_achievements(int $guid): array
{
    $held = [];
    foreach (odq_own_achievements([$guid])['own_achievements'] as $a) {
        $id = (int)$a['achievement_id'];
        // The date as the game reads it, in the server's zone: YYYYmmddHHMMSS.
        $at = DateTime::createFromFormat('YmdHis', (string)$a['reg_date']);
        $held[] = ['id' => $id, 'words' => me_achievement_words($id), 'points' => (int)(OPENDMTQ_ACHIEVEMENTS[$id][4] ?? 0),
                   'at' => $at ? $at->getTimestamp() : null];
    }
    // The newest first; the game's own order (by id) among those of one moment.
    usort($held, fn($a, $b) => [$b['at'] ?? 0, $a['id']] <=> [$a['at'] ?? 0, $b['id']]);
    return ['held' => $held, 'count' => count(OPENDMTQ_ACHIEVEMENTS), 'points' => array_sum(array_column(OPENDMTQ_ACHIEVEMENTS, 4))];
}

/* Where the player stands: 'all' (their place by total best score, as the rankings and their public page give it) and
   'month' with 'score' (this month's place and score, as the game's own monthly board ranks it); null where they have no
   place. */
function me_ranks(SQLite3 $db, int $guid): array
{
    $figures = player_figures($db, $guid);
    $out = ['all' => $figures['rank'] ?? null, 'total' => (int)($figures['total'] ?? 0), 'month' => null, 'score' => null];
    if (has_playlog($db)) {
        // This month's board, the one the rankings' This month tab shows: their place on it, by position.
        foreach (month_players($db, odq_month_start(), PHP_INT_MAX) as $i => $p) {
            if ((int)$p['id'] === $guid) {
                $out['month'] = $i + 1;
                $out['score'] = (int)$p['score'];
                break;
            }
        }
    }
    return $out;
}

/* The player's broadcasts as the server has them: 'on' (broadcasts on for the server; nothing of them shows otherwise),
   'switch' (their own switch, which the owner sets on the admin pages: what new players start with when it was never
   set), 'on_air', and their recordings players may watch: 'recordings' (how many), 'seconds' (their length in all),
   'newest' (when the newest began). */
function me_broadcasts(SQLite3 $db, int $guid): array
{
    $out = ['on' => live_enabled(), 'switch' => false, 'on_air' => false, 'recordings' => 0, 'seconds' => 0, 'newest' => null];
    if (!$out['on']) {
        return $out;
    }
    // Their row of the switches; none yet reads as what new players start with, as the server goes by it.
    $q = @$db->prepare('SELECT live FROM LiveSwitch WHERE guid = :g');
    if ($q) {
        $q->bindValue(':g', $guid, SQLITE3_INTEGER);
        $r = @$q->execute();
        $row = $r ? $r->fetchArray(SQLITE3_NUM) : false;
        $out['switch'] = $row ? (bool)$row[0] : live_settings()['new_players'];
    }
    $out['on_air'] = isset(live_on_air($db)[$guid]);
    // Their own folders alone, closed and not hidden, as the live page lists them; each one's length from its notes.
    foreach (glob(LIVE_REC_DIR . '/' . $guid . '/*', GLOB_ONLYDIR) ?: [] as $rec) {
        if (!preg_match('#/(\d+)$#', $rec, $m) || is_file("$rec/.open") || is_file("$rec/.hidden")) {
            continue;
        }
        $meta = live_rec_read($rec, $guid, (int)$m[1]);
        $out['recordings']++;
        $out['seconds'] += (int)round((int)$meta['duration_ms'] / 1000);
        $out['newest'] = max((int)$out['newest'], (int)$meta['started']);
    }
    return $out;
}

/* ---------------------------------------------------------------------- plays and records, a page at a time */

/* A page of the player's plays, newest first: 'items' (PlayLog rows), 'page', 'pages' and 'total'. */
function me_plays(SQLite3 $db, int $guid, int $page): array
{
    if (!has_playlog($db)) {
        return ['items' => [], 'page' => 1, 'pages' => 1, 'total' => 0];
    }
    $total = (int)(rows($db, 'SELECT COUNT(*) AS n FROM PlayLog WHERE user_id = :id', [':id' => $guid])[0]['n'] ?? 0);
    $pages = max(1, (int)ceil($total / ME_PER_PAGE));
    // A page past the last is the last.
    $page = min(max(1, $page), $pages);
    $items = rows($db, 'SELECT * FROM PlayLog WHERE user_id = :id ORDER BY played_at DESC, id DESC LIMIT :n OFFSET :o',
        [':id' => $guid, ':n' => ME_PER_PAGE, ':o' => ($page - 1) * ME_PER_PAGE]);
    return ['items' => $items, 'page' => $page, 'pages' => $pages, 'total' => $total];
}

/* A page of the player's best records, best score first as their public page orders them: 'items' (Play rows, each with
   'set_at', when the play that set it was, null for one older than the play log), 'page', 'pages' and 'total'. */
function me_records(SQLite3 $db, int $guid, int $page): array
{
    $total = (int)(rows($db, 'SELECT COUNT(*) AS n FROM Play WHERE user_id = :id', [':id' => $guid])[0]['n'] ?? 0);
    $pages = max(1, (int)ceil($total / ME_PER_PAGE));
    $page = min(max(1, $page), $pages);
    $items = rows($db, 'SELECT * FROM Play WHERE user_id = :id ORDER BY score DESC, pattern_id LIMIT :n OFFSET :o',
        [':id' => $guid, ':n' => ME_PER_PAGE, ':o' => ($page - 1) * ME_PER_PAGE]);
    // When each was set: the newest play that set a record on its chart, for this page's charts alone.
    $set = [];
    if ($items && has_playlog($db)) {
        $charts = implode(',', array_map(fn($r) => (int)$r['pattern_id'], $items));
        foreach (rows($db, "SELECT pattern_id, MAX(played_at) AS at FROM PlayLog WHERE user_id = :id AND is_record = 1
                             AND pattern_id IN ($charts) GROUP BY pattern_id", [':id' => $guid]) as $r) {
            $set[(int)$r['pattern_id']] = (int)$r['at'];
        }
    }
    foreach ($items as &$r) {
        $r['set_at'] = $set[(int)$r['pattern_id']] ?? null;
    }
    unset($r);
    return ['items' => $items, 'page' => $page, 'pages' => $pages, 'total' => $total];
}

/* A play or a best as the JSON twin gives it: its chart, song and score, the keyboard's mark, and its time. */
function me_play_json(array $r, bool $best): array
{
    [$sid, $line, $diff, $sig] = charts()[(int)$r['pattern_id']] ?? [0, 0, 0, 0];
    $song = songs_by_id()[$sid] ?? null;
    $out = ['chart' => (int)$r['pattern_id'], 'song' => $song ? (int)$sid : null, 'title' => $song ? song_title($song) : null,
            'chart_name' => $song ? chart_label($line, $diff, $sig) : null, 'score' => (int)$r['score'], 'grade' => (string)$r['grade'],
            'keys' => !empty($r['keys'])];
    if ($best) {
        return $out + ['all_combo' => ($r['isAllCombo'] ?? 'N') === 'Y', 'perfect' => ($r['isPerfectPlay'] ?? 'N') === 'Y',
                       'accuracy' => (int)$r['judgement'] / 10, 'set_at' => $r['set_at']];
    }
    return $out + ['accuracy' => (int)$r['judgement'] / 10, 'record' => !empty($r['is_record']), 'at' => (int)$r['played_at']];
}
