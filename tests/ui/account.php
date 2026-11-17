<?php
/*
 * MY PAGE's account changes, as the site makes them (server/portal/me_lib.php), inside the running server on its own
 * database: tests/ui/run.sh runs this after the seed and the accounts (the owner's sign-in for the site is there by then).
 * Two accounts of its own, made here and removed at the end, and an address of its own for the sign-in's limit, so that
 * the browser's own sign-ins are never held back by what is tried here.
 *
 * - The password: a wrong current one refused and counted toward the sign-in's limit, the form's own faults not counted, the
 *   limit reached after as many wrong ones as a sign-in takes; changed, the old one signs in no more, every other sign-in
 *   (its cookie signed with the old one) ends, this browser's stays.
 * - The ID: another account's in any letter case refused, the owner's too, one the rules refuse, each only after the right
 *   password and counted as a try; changed, the game player and the API's tokens go with it (never the owner's), a
 *   sign-in made before ends, also when the ID comes back, this browser's stays.
 * - Two changes in one second (Sign out everywhere else, then a new password): this browser stays signed in.
 * - A new password the admin gives the account between the check and the write stands.
 * - Sign out everywhere else: every sign-in made before it ends, one made in that same second too, this browser's stays.
 * - The server's own account: no password changed here (the Server page does), its Sign out everywhere else kept in its file.
 * - Each change in the log of changes, by the account, with no password in it.
 *
 * Usage: docker exec -i <server container> php < account.php        (exit status 0 when every check passed)
 */

// The site's own code, as a page loads it; the server's code folder of the image (or a host install's, OPENDMTQ_APP).
$app = getenv('OPENDMTQ_APP') ?: '/opt/opendmtq';
// An address of this check's own, for the sign-in's limit, which counts each address apart.
$_SERVER['REMOTE_ADDR'] = '203.0.113.71';
$_SERVER['SCRIPT_NAME'] = '/opendmtq/me.php';
// What the pages print and the headers they set are not this check's: held back, and the check's own lines go to stdout.
ob_start();
require "$app/portal/lib.php";
require "$app/portal/me_lib.php";

$failures = 0;
/* One line per check, PASS or FAIL with what was found; the failures decide the exit status. */
function check(string $name, bool $ok, string $detail = ''): void
{
    global $failures;
    $failures += $ok ? 0 : 1;
    fwrite(STDOUT, ($ok ? 'PASS ' : 'FAIL ') . "account: $name" . ($ok || $detail === '' ? '' : " | $detail") . "\n");
}

/* The sign-in's limit's failures from one address, as its file holds them. */
function fails_from(string $ip): int
{
    $n = 0;
    dl_attempts(function (array $fails) use ($ip, &$n): array {
        $n = count(array_filter($fails, fn($f) => ($f[1] ?? '') === $ip));
        return $fails;
    });
    return $n;
}

/* This browser signed in as $name now (the cookie made as the sign-in makes it), and the signed-in account worked out anew. */
function as_browser(string $name, ?int $made = null): string
{
    dl_cookie($name, $made);
    site_user(true);
    return (string)$_COOKIE[DL_COOKIE];
}

/* Whom a cookie signs in as, now. */
function signs_in_as(string $cookie): ?string
{
    $_COOKIE[DL_COOKIE] = $cookie;
    return site_user(true);
}

$db = new SQLite3(DB);
$db->busyTimeout(5000);
$now = time();
// Its two accounts afresh (an earlier run may have stopped half way), each with the columns the server's start keeps.
$db->exec("DELETE FROM SiteUser WHERE name IN ('acct-check', 'acct-moved', 'acct-other', 'acct-away')");
$db->exec("DELETE FROM ApiToken WHERE id IN ('acctcheck001', 'acctcheck002')");
$add = $db->prepare('INSERT INTO SiteUser (name, pass, note, admin, created_at, guid) VALUES (:name, :pass, :note, :admin, :at, :guid)');
foreach ([['acct-check', 'first-pass-1', 'account check', 1, 2], ['acct-other', 'other-pass-1', '', 0, null]] as [$name, $pass, $note, $admin, $guid]) {
    $add->bindValue(':name', $name);
    $add->bindValue(':pass', me_hash($pass));
    $add->bindValue(':note', $note);
    $add->bindValue(':admin', $admin, SQLITE3_INTEGER);
    $add->bindValue(':at', $now - 3600, SQLITE3_INTEGER);
    $add->bindValue(':guid', $guid, $guid === null ? SQLITE3_NULL : SQLITE3_INTEGER);
    $add->execute();
    $add->reset();
}
// An API token of the account, as the admin pages keep one under their admin's ID.
$db->exec("INSERT INTO ApiToken (id, name, scope, hash, admin, owner, admin_since, created_at) VALUES ('acctcheck001', 'check', 'read', 'h', 'acct-check', 0, " . ($now - 3600) . ", $now)");
check('a password the site keeps as the admin pages do', site_check('acct-check', 'first-pass-1') === 'acct-check');

// ---------------------------------------------------------------------- the password
// Another browser of the account's, signed in before the change, and this one.
$other = as_browser('acct-check', $now - 60);
$mine = as_browser('acct-check');
check('signed in as the account', site_user(true) === 'acct-check');
$before = fails_from('203.0.113.71');
$said = me_change_password('not-my-password', 'second-pass-2', 'second-pass-2');
check('a wrong current password is said under its field', $said === ['current', 'me.wrong_current'], json_encode($said));
check("and counted toward the sign-in's limit", fails_from('203.0.113.71') === $before + 1, (string)fails_from('203.0.113.71'));
$said = me_change_password('first-pass-1', 'short', 'short');
check('a password too short for an account with admin rights is said, and not counted', $said === ['password', 'me.bad_admin_password'] && fails_from('203.0.113.71') === $before + 1, json_encode($said));
$said = me_change_password('first-pass-1', 'second-pass-2', 'second-pass-3');
check('two new passwords that differ are said', $said === ['password2', 'me.mismatch'], json_encode($said));
$said = me_change_password('first-pass-1', 'second-pass-2', 'second-pass-2');
check('the password changed', $said === '' && site_check('acct-check', 'second-pass-2') === 'acct-check', json_encode($said));
check('the old one signs in no more', site_check('acct-check', 'first-pass-1') === null);
$mine = (string)$_COOKIE[DL_COOKIE];
check('this browser stays signed in', signs_in_as($mine) === 'acct-check');
check("another browser's sign-in ends", signs_in_as($other) === null);

// The limit: as many wrong current passwords from one address as a sign-in takes, then refused before any is compared.
$_SERVER['REMOTE_ADDR'] = '203.0.113.72';
signs_in_as($mine);
for ($i = 0; $i < DL_PER_ADDRESS; $i++) {
    me_change_password('wrong-' . $i, 'third-pass-3', 'third-pass-3');
}
$said = me_change_password('second-pass-2', 'third-pass-3', 'third-pass-3');
check("past the sign-in's limit, even the right password waits", $said === ['', 'signin.throttled'] && site_check('acct-check', 'second-pass-2') === 'acct-check', json_encode($said));
$_SERVER['REMOTE_ADDR'] = '203.0.113.71';

// ---------------------------------------------------------------------- the ID
signs_in_as($mine);
$said = me_change_id('ACCT-OTHER', 'second-pass-2');
check("another account's ID, in other letters, is taken", $said === ['id', 'me.id_taken'], json_encode($said));
$owner = site_owner();
if ($owner !== null) {
    $said = me_change_id(strtoupper($owner['name']), 'second-pass-2');
    check("the owner's ID is taken too", $said === ['id', 'me.id_taken'], json_encode($said));
}
$said = me_change_id('a b', 'second-pass-2');
check('an ID the rules refuse is said', $said === ['id', 'me.bad_id'], json_encode($said));
$said = me_change_id('acct-moved', 'not-my-password');
check('a wrong current password changes no ID', $said === ['current', 'me.wrong_current'] && site_account('acct-check') !== null, json_encode($said));
$said = me_change_id('acct-moved', 'second-pass-2');
$moved = site_account('acct-moved');
check('the ID changed, its game player with it', $said === '' && $moved !== null && (int)$moved['guid'] === 2 && site_account('acct-check') === null, json_encode($said));
check('its API tokens follow it', $db->querySingle("SELECT admin FROM ApiToken WHERE id = 'acctcheck001'") === 'acct-moved');
check('this browser signs in as the new ID', signs_in_as((string)$_COOKIE[DL_COOKIE]) === 'acct-moved');
check('a sign-in that names the old ID ends', signs_in_as($mine) === null);
check('the new ID and the password sign in', site_check('acct-moved', 'second-pass-2') === 'acct-moved');

// ---------------------------------------------------------------------- sign out everywhere else
$mine = as_browser('acct-moved');
// Two other sign-ins: one made a while ago, one this very second.
$older = as_browser('acct-moved', time() - 30);
$same = as_browser('acct-moved', time());
signs_in_as($mine);
$said = me_sign_out_others();
$mine = (string)$_COOKIE[DL_COOKIE];
check('signed out everywhere else', $said === '', json_encode($said));
check('this browser stays signed in', signs_in_as($mine) === 'acct-moved');
check('a sign-in made before ends', signs_in_as($older) === null);
check('one made in that same second ends too', signs_in_as($same) === null);

// ---------------------------------------------------------------------- what an ID's change gives away
// Whether the owner or another account has an ID is said only after the right password, and such a try counts toward the
// sign-in's limit as a wrong password does.
signs_in_as($mine);
if ($owner !== null) {
    $said = me_change_id(strtoupper($owner['name']), '');
    check("the owner's ID is not said to be taken before the password", $said === ['current', 'me.missing_current'], json_encode($said));
}
$before = fails_from('203.0.113.71');
$said = me_change_id('ACCT-OTHER', 'second-pass-2');
check('a taken ID tried with the right password counts toward the limit', $said === ['id', 'me.id_taken'] && fails_from('203.0.113.71') === $before + 1,
    json_encode($said) . ' ' . (fails_from('203.0.113.71') - $before));

// ---------------------------------------------------------------------- two changes in one second
// Sign out everywhere else, then a new password, in one second: this browser stays signed in (its cookie made from the
// moment the sign-out set, not a second before it).
$t = time();
while (time() === $t) {
    usleep(2000);
}
signs_in_as($mine);
$first = me_sign_out_others();
$said = me_change_password('second-pass-2', 'fourth-pass-4', 'fourth-pass-4');
$mine = (string)$_COOKIE[DL_COOKIE];
check('a Sign out everywhere else and a new password in one second leave this browser signed in',
    $first === '' && $said === '' && signs_in_as($mine) === 'acct-moved' && me_account() !== null, json_encode([$first, $said, time() - $t]));

// ---------------------------------------------------------------------- an ID changed away and back
// A sign-in made before the change stays ended when the ID comes back; the owner's tokens kept under an ID like this one's
// (a former ADMIN_USER) never move with the account.
// Each part of this check from a sign-in of its own, whatever the one before it left.
$db->exec("UPDATE SiteUser SET pass = '" . me_hash('fourth-pass-4') . "' WHERE name = 'acct-moved'");
$older = as_browser('acct-moved', time() - 30);
$mine = as_browser('acct-moved', time() + 1);
$db->exec("INSERT INTO ApiToken (id, name, scope, hash, admin, owner, admin_since, created_at) VALUES ('acctcheck002', 'owner check', 'read', 'h', 'acct-moved', 1, NULL, $now)");
signs_in_as($mine);
$away = me_change_id('acct-away', 'fourth-pass-4');
check("the owner's token kept under that ID stays under it", $db->querySingle("SELECT admin FROM ApiToken WHERE id = 'acctcheck002'") === 'acct-moved');
signs_in_as((string)$_COOKIE[DL_COOKIE]);
$back = me_change_id('acct-moved', 'fourth-pass-4');
$mine = (string)$_COOKIE[DL_COOKIE];
check('an ID changed away and back gives a sign-in made before no new life', $away === '' && $back === '' && signs_in_as($older) === null,
    json_encode([$away, $back]));
check('and this browser still signs in', signs_in_as($mine) === 'acct-moved');

// ---------------------------------------------------------------------- a new password from the admin in between
// The admin gives the account a new password on the Accounts page between the check of the current one and the write:
// the admin's stands, and nothing is written.
$checked = (string)(site_account('acct-moved')['pass'] ?? '');
$reset = me_hash('reset-pass-9');
$db->exec("UPDATE SiteUser SET pass = '$reset' WHERE name = 'acct-moved'");
$written = me_write_password('acct-moved', $checked, me_hash('mine-pass-5'));
check("a new password the admin gave in between stands", $written === false && site_check('acct-moved', 'reset-pass-9') === 'acct-moved'
    && site_check('acct-moved', 'mine-pass-5') === null);

// ---------------------------------------------------------------------- the server's own account
if ($owner !== null) {
    $owners = as_browser($owner['name']);
    $said = me_change_password('anything', 'second-pass-2', 'second-pass-2');
    check("the server's own account changes its password on the Server page, not here", $said === ['', 'me.owner_pw'], json_encode($said));
    $said = me_sign_out_others();
    check('and signs out everywhere else, kept in a file of its own', $said === '' && owner_signed_out_at() !== null, json_encode($said));
}

// ---------------------------------------------------------------------- the log of changes
$lines = array_map(fn($l) => json_decode($l, true), @file(odq_state_dir() . '/changes.log', FILE_IGNORE_NEW_LINES) ?: []);
// This run's lines alone: an earlier run on the same data wrote its own.
$mine_lines = array_values(array_filter($lines, fn($l) => is_array($l) && (int)($l['at'] ?? 0) >= $now && in_array($l['who'] ?? '', ['acct-check', 'acct-moved'], true)));
$whats = array_column($mine_lines, 'what');
check('each change in the log of changes, by the account', array_slice($whats, 0, 3) === ['site:password', 'site:id', 'site:signout'], json_encode($whats));
check("with the ID's change from the old to the new", ($mine_lines[1]['target'] ?? '') === 'acct-check > acct-moved', json_encode($mine_lines[1] ?? null));
check('and no password in it', strpos((string)@file_get_contents(odq_state_dir() . '/changes.log'), 'second-pass-2') === false);

// What it made goes: its accounts, its token, its failures, and the owner's moment (the pages' tests sign in as the owner).
$db->exec("DELETE FROM SiteUser WHERE name IN ('acct-check', 'acct-moved', 'acct-other', 'acct-away')");
$db->exec("DELETE FROM ApiToken WHERE id IN ('acctcheck001', 'acctcheck002')");
dl_attempts(fn(array $fails): array => array_filter($fails, fn($f) => !in_array($f[1] ?? '', ['203.0.113.71', '203.0.113.72'], true)));
@unlink(odq_state_dir() . '/' . OWNER_SIGNED_OUT);
ob_end_clean();
exit($failures ? 1 : 0);
