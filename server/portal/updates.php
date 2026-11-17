<?php
/* The PC client's updates this server hands out (http://<server>/updates/<file>): the update feed, its packages and the
   release's checksums with their signature, of the version of the installer the site hands out, as the builder keeps
   them (tools/opendmtq_tools/client_updates.py: data/apk/out/updates, described by updates.json). A launcher that plays
   on this server asks here first (client/opendmtq_client/updates.py) and puts in nothing the OpenDMTQ project did not
   sign, so the files need no sign-in: they are the project's release files, the same bytes as on GitHub, and the
   launcher looks for them at each start, before anyone signs in. Only the files updates.json names, at the sizes it
   gives them; whole, or from where a broken download stopped. */
require __DIR__ . '/lib.php';

/* No such file here: a short answer, never a page (a launcher reads the status alone). */
function no_update(): void
{
    http_response_code(404);
    header('Content-Type: text/plain; charset=utf-8');
    header('Cache-Control: no-store');
    echo "not found\n";
    exit;
}

// The file's name, the last part of the address alone: /updates/releases.win.json.
$name = rawurldecode(basename((string)parse_url((string)($_SERVER['REQUEST_URI'] ?? ''), PHP_URL_PATH)));
$raw = @file_get_contents(APK_DIR . '/updates.json');
$made = $raw === false ? null : json_decode($raw, true);
$about = is_array($made) && is_array($made['files'] ?? null) ? ($made['files'][$name] ?? null) : null;
// A name updates.json gives, of one file in the folder (no other folder in it), there at the size it says: a file
// half copied, or one the builder is swapping in, is none to hand out.
$path = APK_DIR . '/updates/' . $name;
if (!is_array($about) || $name === '' || $name !== basename($name) || $name[0] === '.' || !is_file($path)
    || filesize($path) !== (int)($about['size'] ?? -1)) {
    no_update();
}
// Opened now: the length said and the bytes sent are the same file's, even if the builder swaps it meanwhile.
$f = @fopen($path, 'rb');
if (!$f) {
    no_update();
}
// The feed as JSON, the checksums as text, everything else as bytes.
$type = substr($name, -5) === '.json' ? 'application/json' : (substr($name, -4) === '.txt' ? 'text/plain; charset=utf-8'
    : 'application/octet-stream');
// Whole, or the part a broken download asks for to go on, while it is still this file (its SHA-256 says so).
send_download($f, $type, $name, download_tag($about, fstat($f)));
