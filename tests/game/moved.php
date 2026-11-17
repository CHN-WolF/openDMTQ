<?php
/*
 * A server moved to another address (another port, another PC): tests/game/protocol.sh runs this inside the throwaway
 * server. Each start notes the address it serves (bin/setup-db.php, odq_note_address()); a start at another address than
 * the last notes the move, and the site's download page says, for a month, that phones need the app built for the new
 * address (PAGE-47).
 *
 * Usage: php tests/game/moved.php <database file> <base address of the server>      (exit status 0 when every check passed)
 */

// The server's own code: the image's, or a host install's (OPENDMTQ_APP names its server/ folder).
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

// The noting itself, in a folder of its own: a first start, the same address again, then another one.
$dir = sys_get_temp_dir() . '/moved-' . getmypid();
@mkdir($dir);
check('a first start notes its address and no move', odq_note_address($dir, '192.168.1.10') === null
    && json_decode((string)file_get_contents("$dir/address.json"), true) === ['host' => '192.168.1.10']);
check('a start at the same address notes no move', odq_note_address($dir, '192.168.1.10') === null
    && !is_file("$dir/address-moved.json"));
$moved = odq_note_address($dir, '192.168.1.10:8792');
check('a start at another port notes the move, from where to where', ($moved['from'] ?? '') === '192.168.1.10'
    && ($moved['to'] ?? '') === '192.168.1.10:8792' && odq_address_moved($dir, '192.168.1.10:8792') !== null);
check('which the site reads only at the address moved to', odq_address_moved($dir, '192.168.1.11') === null);
// A month on: no longer said.
$old = json_decode((string)file_get_contents("$dir/address-moved.json"), true);
$old['at'] -= (ODQ_MOVED_DAYS + 1) * 86400;
file_put_contents("$dir/address-moved.json", json_encode($old));
check('and not after a month', odq_address_moved($dir, '192.168.1.10:8792') === null);
array_map('unlink', glob("$dir/*"));
@rmdir($dir);

// The download page of this server, as a player signed in sees it after a move to the address it serves now: an account
// of this check's own, made as the admin pages make one (PBKDF2-SHA256, auth.php).
$state = dirname($path);
$db = new SQLite3($path);
$db->busyTimeout(5000);
$salt = random_bytes(16);
$pass = 'pbkdf2_sha256$120000$' . bin2hex($salt) . '$' . hash_pbkdf2('sha256', 'moved-pass', $salt, 120000, 64);
$db->exec("DELETE FROM SiteUser WHERE name = 'movedcheck'");
$add = $db->prepare("INSERT INTO SiteUser (name, pass, note, admin, created_at) VALUES ('movedcheck', :pass, '', 0, :at)");
$add->bindValue(':pass', $pass, SQLITE3_TEXT);
$add->bindValue(':at', time(), SQLITE3_INTEGER);
$add->execute();
file_put_contents("$state/address-moved.json", json_encode(['from' => 'old.example.net:8790', 'to' => odq_host(), 'at' => time()]));

// Signed in as a browser is (the site's cookie), then the page.
$signin = stream_context_create(['http' => ['method' => 'POST', 'follow_location' => 0, 'ignore_errors' => true,
    'header' => "Content-Type: application/x-www-form-urlencoded\r\n",
    'content' => http_build_query(['user' => 'movedcheck', 'password' => 'moved-pass', 'next' => '/opendmtq/download.php'])]]);
@file_get_contents("$base/opendmtq/login.php", false, $signin);
$cookie = '';
foreach ($http_response_header ?? [] as $line) {
    if (preg_match('/^Set-Cookie:\s*([^;]+)/i', $line, $m)) {
        $cookie .= ($cookie !== '' ? '; ' : '') . $m[1];
    }
}
check('the check signs in to the site', $cookie !== '', implode(' / ', $http_response_header ?? []));
$page = (string)@file_get_contents("$base/opendmtq/download.php", false, stream_context_create(['http' => [
    'header' => "Cookie: $cookie; opendmtq_lang=en\r\n", 'ignore_errors' => true]]));
check('the download page says the server moved, from where to where, that phones and tablets need the new app, and what PCs do',
    str_contains($page, 'id="moved"') && str_contains($page, 'old.example.net:8790')
    && str_contains($page, h_like(odq_host())) && str_contains($page, 'Phones and tablets need the app built for the new address')
    && str_contains($page, 'On a Windows PC, run the installer from this page'),
    substr(strip_tags($page), 0, 300));
// The move goes again: the page, still signed in, says none. Then its own account goes: the rest of the run sees the
// server as it was.
@unlink("$state/address-moved.json");
$page = (string)@file_get_contents("$base/opendmtq/download.php", false, stream_context_create(['http' => [
    'header' => "Cookie: $cookie; opendmtq_lang=en\r\n", 'ignore_errors' => true]]));
check('without a move, the page says none', str_contains($page, 'id="install"') && !str_contains($page, 'id="moved"'));
$db->exec("DELETE FROM SiteUser WHERE name = 'movedcheck'");
$db->close();

/* An address as the page prints it (escaped). */
function h_like(string $text): string
{
    return htmlspecialchars($text, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

exit($failures > 0 ? 1 : 0);
