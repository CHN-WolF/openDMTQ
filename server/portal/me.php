<?php
/* MY PAGE: the signed-in player's own page, reached from the name and badge at the top of every page. Four tabs: the
   profile (what the game knows of them, shown only: it changes in the game; their achievements, their places, their
   broadcasts), every play, every best record, and the account (everything the site keeps about it, and the three changes
   they may make: the password, the ID, signing out everywhere else). What other players see of them is their public
   page, one link away; nothing here is shown to anyone else.

   Its JSON twin, for a script with the site's cookie (docs/api.md, "The site's own JSON"):
     GET  me.php?json                    the account, the profile, the achievements, the places, the broadcasts
     GET  me.php?json&tab=plays&page=N   a page of the plays; tab=records a page of the best records
     POST me.php?json&do=password        current, password, password2 (form fields or a JSON body)
     POST me.php?json&do=id              id, current
     POST me.php?json&do=signout         nothing
   The page's forms send the same to me.php?tab=account&do=..., and come back to the account tab. */
require __DIR__ . '/lib.php';
require __DIR__ . '/me_lib.php';

// The JSON twin, or the page.
$json = isset($_GET['json']);
// The tabs, in the page's order, with the words of each; the profile when none is named.
const ME_TABS = ['profile' => 'me.tab_profile', 'plays' => 'me.tab_plays', 'records' => 'me.tab_records', 'account' => 'me.tab_account'];
$tab = isset(ME_TABS[(string)($_GET['tab'] ?? '')]) ? (string)$_GET['tab'] : 'profile';
// A page of a long list: the first when none is named.
$page = max(1, (int)($_GET['page'] ?? 1));
// The in-game items by the game's own names for them, which it shows in every language (me_game() keys them by its codes),
// the words of the four slots the game's MY PAGE shows, and of each change once it is done.
const ME_ITEMS = ['fp' => 'FEVER PLUS', 'gr' => 'GAUGE REFILL', 'ab' => 'ANTI BREAK'];
const ME_SLOTS = ['character' => 'me.slot_character', 'addon' => 'me.slot_addon', 'note' => 'me.slot_note', 'skin' => 'me.slot_skin'];
const ME_DONE = ['password' => 'me.done_password', 'id' => 'me.done_id', 'signout' => 'me.done_signout'];

/* One JSON answer with its status, and the end: never kept by a cache, as it is one account's own. */
function me_answer(int $status, array $body, array $headers = []): void
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    foreach ($headers as $name => $value) {
        header("$name: $value");
    }
    echo json_encode($body, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    exit;
}

// What each refusal answers on the JSON twin: its status and its code, by the words' key the change gave back.
const ME_REFUSALS = [
    'me.signed_out' => [403, 'signin'], 'me.owner_pw' => [409, 'owner_account'],
    'me.missing_current' => [400, 'missing_field'], 'me.missing_new' => [400, 'missing_field'], 'me.missing_id' => [400, 'missing_field'],
    'me.bad_password' => [400, 'bad_password'], 'me.bad_admin_password' => [400, 'bad_password'], 'me.mismatch' => [400, 'password_mismatch'],
    'me.wrong_current' => [401, 'wrong_password'], 'signin.throttled' => [429, 'throttled'],
    'me.bad_id' => [400, 'bad_id'], 'me.same_id' => [409, 'same_id'], 'me.id_taken' => [409, 'id_taken'], 'me.failed' => [503, 'not_saved'],
];

/* A refusal on the JSON twin: {"error": {"code", "message", "field"}} with its status (a throttle says when to try again,
   the sign-in's window). */
function me_refuse(string $key, string $field = ''): void
{
    [$status, $code] = ME_REFUSALS[$key] ?? [400, 'refused'];
    me_answer($status, ['error' => ['code' => $code, 'message' => tp($key), 'field' => $field]], $status === 429 ? ['Retry-After' => '600'] : []);
}

/* The account as the JSON twin gives it: what MY PAGE's account tab shows. */
function me_account_json(array $a, ?SQLite3 $db): array
{
    $player = null;
    if ($a['player'] !== null) {
        // The player's name as every page shows it, with the address of their public page.
        $fig = $db ? player_figures($db, $a['player']) : null;
        $player = ['id' => $a['player'], 'name' => $fig ? (string)$fig['name'] : null, 'page' => '/opendmtq/player.php?id=' . $a['player']];
    }
    return ['id' => $a['id'], 'owner' => $a['owner'], 'admin' => $a['admin'], 'note' => $a['note'], 'made' => $a['made'],
            'last_in' => $a['last_in'], 'this_in' => $a['this_in'], 'player' => $player, 'language' => lang()];
}

// ---------------------------------------------------------------------------- the JSON twin's door, and the changes

// Nobody signed in: the JSON twin says so in its own shape; the page goes to the sign-in, which comes back here.
if (!dl_signed_in()) {
    if ($json) {
        header('Vary: Cookie');
        me_refuse('me.signed_out');
    }
    require_sign_in();
}

// A change: from this site's own pages only (a form on another site cannot change anyone's account), then the change the
// address names, with what was typed. The JSON twin takes a JSON body as well as form fields.
$said = null;
$form = '';
if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    if (from_another_site()) {
        if ($json) {
            me_answer(403, ['error' => ['code' => 'cross_site', 'message' => 'A change of an account comes from the site\'s own pages.', 'field' => '']]);
        }
        // Nothing done, nothing read: the account tab as it is.
        header('Location: /opendmtq/me.php?tab=account', true, 303);
        exit;
    }
    $body = $_POST;
    if ($json && stripos((string)($_SERVER['CONTENT_TYPE'] ?? ''), 'application/json') === 0) {
        // A body a few hundred bytes long at most: anything bigger is no change of an account.
        $raw = (string)file_get_contents('php://input', false, null, 0, 16384);
        $body = json_decode($raw, true);
        if (!is_array($body)) {
            me_answer(400, ['error' => ['code' => 'bad_json', 'message' => 'The body is no JSON object.', 'field' => '']]);
        }
    }
    // A field as text: what a JSON body holds that is no text counts as nothing typed.
    $field = fn(string $name): string => is_string($body[$name] ?? null) ? (string)$body[$name] : '';
    $form = (string)($_GET['do'] ?? '');
    if ($form === 'password') {
        $said = me_change_password($field('current'), $field('password'), $field('password2'));
    } elseif ($form === 'id') {
        // The ID as typed, without the space a phone's keyboard may add after a word.
        $said = me_change_id(trim($field('id')), $field('current'));
    } elseif ($form === 'signout') {
        $said = me_sign_out_others();
    } else {
        if ($json) {
            me_answer(404, ['error' => ['code' => 'unknown', 'message' => 'There is no such change: do is password, id or signout.', 'field' => '']]);
        }
        header('Location: /opendmtq/me.php?tab=account', true, 303);
        exit;
    }
    if ($json) {
        if ($said !== '') {
            me_refuse($said[1], $said[0]);
        }
        // Done: what was changed, and the account as it is now.
        me_answer(200, ['done' => $form, 'account' => me_account_json(me_account(), db())]);
    }
    // Done: the account tab again, saying so (a reload then sends nothing again). Refused: the page with the words under
    // the field they are about, and what was typed kept but the passwords.
    if ($said === '') {
        header('Location: /opendmtq/me.php?tab=account&done=' . $form, true, 303);
        exit;
    }
    $tab = 'account';
}

$account = me_account();
$db = db();
$guid = $account['player'];
// The player as every page shows them, with their figures; null for an account not linked to one (or one gone since).
$fig = ($guid !== null && $db) ? player_figures($db, $guid) : null;

// The JSON twin: the tab named, or the profile and the account.
if ($json) {
    $out = ['account' => me_account_json($account, $db)];
    if ($tab === 'plays' || $tab === 'records') {
        $list = $fig ? ($tab === 'plays' ? me_plays($db, $guid, $page) : me_records($db, $guid, $page)) : ['items' => [], 'page' => 1, 'pages' => 1, 'total' => 0];
        $out[$tab] = ['page' => $list['page'], 'pages' => $list['pages'], 'total' => $list['total'],
                      'items' => array_map(fn($r) => me_play_json($r, $tab === 'records'), $list['items'])];
    } elseif ($fig) {
        $casts = me_broadcasts($db, $guid);
        $out += ['player' => ['id' => $guid, 'name' => (string)$fig['name'], 'charts' => (int)$fig['charts'], 'total' => (int)$fig['total']],
                 'game' => me_game($guid), 'achievements' => me_achievements($guid), 'ranks' => me_ranks($db, $guid),
                 // Nothing of broadcasts while they are off for the server, as the site shows none.
                 'broadcasts' => $casts['on'] ? $casts : null];
    } else {
        $out += ['player' => null, 'game' => null, 'achievements' => null, 'ranks' => null, 'broadcasts' => null];
    }
    header('Vary: Cookie');
    me_answer(200, $out);
}

// ---------------------------------------------------------------------------- the page

/* A play's or a best's song and chart cells (as the public player page draws its lists), then its score with the keyboard's
   mark, a mark ($flag) and when. */
function me_row(array $r, string $flag, string $when): string
{
    return '<tr>' . chart_cells((int)$r['pattern_id'], charts(), songs_by_id(), $when) . '<td class="r">' . keys_mark($r) . number_format((int)$r['score'])
        . '</td><td class="flag">' . $flag . '</td><td class="meta-inline when">' . h($when) . '</td></tr>';
}

/* The way through a long list: Newer and Older about this page of it. */
function me_pager(string $tab, array $list): string
{
    if ($list['pages'] <= 1) {
        return '';
    }
    $at = fn(int $n): string => '/opendmtq/me.php?tab=' . $tab . '&amp;page=' . $n;
    return '<p class="pager">' . ($list['page'] > 1 ? '<a class="btn btn-sm" href="' . $at($list['page'] - 1) . '">' . t('me.newer') . '</a>' : '')
        . '<span class="meta-inline">' . t('me.page_of', ['n' => $list['page'], 'all' => $list['pages']]) . '</span>'
        . ($list['page'] < $list['pages'] ? '<a class="btn btn-sm" href="' . $at($list['page'] + 1) . '">' . t('me.older') . '</a>' : '') . '</p>';
}

/* A moment as the account tab says it: the day and the time, then how long ago, held together. */
function me_when(?int $at): string
{
    return $at ? h(date('Y-m-d H:i', $at)) . ' <span class="meta-inline">' . h(ago($at)) . '</span>' : '<span class="meta-inline">' . t('me.never') . '</span>';
}

/* A password field in the sign-in's look: its label, the lock in the field, Show at its end, and the words of what is
   wrong with it under it (from this answer, or the page's own check). */
function me_password_field(string $id, string $name, string $label, string $complete, array $said): string
{
    $wrong = $said && $said[0] === $name;
    $toggle = '<button type="button" class="pw-toggle" aria-controls="' . $id . '" aria-label="' . h(tp('signin.show') . ' ' . $label) . '" data-show="'
        . h(tp('signin.show')) . '" data-hide="' . h(tp('signin.hide')) . '" data-show-label="' . h(tp('signin.show') . ' ' . $label) . '" data-hide-label="'
        . h(tp('signin.hide') . ' ' . $label) . '" hidden>' . t('signin.show') . '</button>';
    return '<div class="field"><label for="' . $id . '">' . h($label) . '</label><span class="slot pw"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="10.5" width="14" height="10" rx="1.5"/><path d="M8.5 10.5V7.5a3.5 3.5 0 0 1 7 0v3"/></svg>'
        . '<input id="' . $id . '" name="' . $name . '" type="password" autocomplete="' . $complete . '" required data-missing="' . h(tp($name === 'current' ? 'me.missing_current' : 'me.missing_new')) . '"'
        . ($wrong ? ' aria-invalid="true" aria-describedby="' . $id . '-error" autofocus' : '') . '>' . $toggle . '</span>'
        . ($wrong ? '<span class="field-error" id="' . $id . '-error" role="alert">' . t($said[1]) . '</span>' : '') . '</div>';
}

// The page's own title, as the tab of the browser shows it.
page_header(tp('me.title'), 'me');
// The account's player, as the game shows them: their name, else the account's ID.
$name = $fig ? (string)$fig['name'] : (string)$account['id'];
?>
  <?= masthead('MY PAGE', t('me.line')) ?>
  <?php // The tabs: the lists of plays and records only for an account with a game player. ?>
  <p class="tabs">
    <?php foreach (ME_TABS as $key => $words): if (!$fig && ($key === 'plays' || $key === 'records')) { continue; } ?>
      <a href="?tab=<?= $key ?>"<?= $key === $tab ? ' class="on" aria-current="true"' : '' ?>><?= t($words) ?></a>
    <?php endforeach; ?>
  </p>
<?php if ($tab === 'profile'): ?>
  <?php // Who they are: the player's name big, the account's ID, their places, and the way to what others see of them. ?>
  <section class="card me-head">
    <span class="me-badge" aria-hidden="true"><?= h(mb_strtoupper(mb_substr($name, 0, 1)) ?: '?') ?></span>
    <div class="me-who">
      <h2><?= h($name) ?><?= $fig ? live_mark($db, $guid) : '' ?></h2>
      <p class="meta"><?= t('me.signed_as', ['id' => $account['id']]) ?></p>
    </div>
    <?php if ($fig): $ranks = me_ranks($db, $guid); ?>
      <div class="stats me-places">
        <div class="stat"><span class="lbl"><?= t('me.rank_all') ?></span><span class="num"><?= $ranks['all'] ? '#' . (int)$ranks['all'] : '–' ?></span></div>
        <div class="stat"><span class="lbl"><?= t('me.rank_month') ?></span><span class="num"><?= $ranks['month'] ? '#' . (int)$ranks['month'] : '–' ?></span></div>
        <div class="stat"><span class="lbl"><?= t('player.total') ?></span><span class="num"><?= number_format((int)$fig['total']) ?></span></div>
      </div>
      <p class="me-public"><a class="btn" href="/opendmtq/player.php?id=<?= (int)$guid ?>"><?= t('me.public') ?></a><span class="meta-inline"><?= t('me.public_note') ?></span></p>
    <?php else: ?>
      <p class="lead me-unlinked"><?= t($account['owner'] ? 'me.owner_player' : 'me.not_linked') ?></p>
    <?php endif; ?>
  </section>
  <?php if ($fig): $game = me_game($guid); $ach = me_achievements($guid); $casts = me_broadcasts($db, $guid); ?>
    <?php // What the game keeps for them, as the game shows it: it changes there, not here. ?>
    <section class="card">
      <h2><?= t('me.game') ?></h2>
      <div class="stats me-game">
        <div class="stat"><span class="lbl"><?= t('me.level') ?></span><span class="num"><?= (int)$game['level'] ?></span></div>
        <div class="stat"><span class="lbl">EXP</span><span class="num"><?= number_format($game['exp']) ?></span></div>
        <div class="stat"><span class="lbl">MAX POINT</span><span class="num"><?= number_format($game['mpoint']) ?></span></div>
        <div class="stat"><span class="lbl">Q POINT</span><span class="num"><?= number_format($game['q']) ?></span></div>
        <div class="stat"><span class="lbl"><?= t('me.owned') ?></span><span class="num"><?= number_format($game['owned']) ?></span></div>
      </div>
      <?php // The in-game items by the game's own names, each with its level; then what is in each of the four slots the game's
            // MY PAGE shows, by the item's number (the server has no names for them). ?>
      <ul class="me-items">
        <?php foreach ($game['items'] as $code => $level): ?>
          <li><span><?= ME_ITEMS[$code] ?></span><b><?= t('me.item_level', ['n' => $level]) ?></b></li>
        <?php endforeach; ?>
        <?php foreach ($game['equipped'] as $slot => $item): ?>
          <li><span><?= t(ME_SLOTS[$slot]) ?></span><b><?= $item ? t('me.item_no', ['n' => $item]) : t('me.item_none') ?></b></li>
        <?php endforeach; ?>
      </ul>
      <p class="meta"><?= t('me.game_note') ?></p>
    </section>
    <?php // The achievements the game gives them, newest first, each in words made from what it asks for. ?>
    <section class="card">
      <h2><?= t('me.ach') ?> <span class="meta-inline"><?= t('me.ach_sum', ['n' => count($ach['held']), 'all' => $ach['count']]) ?> · <?= t('me.ach_points', ['n' => number_format(array_sum(array_column($ach['held'], 'points'))), 'all' => number_format($ach['points'])]) ?></span></h2>
      <?php if (!$ach['held']): ?>
        <p class="empty"><?= t('me.ach_none') ?></p>
      <?php else: ?>
        <ul class="me-ach">
          <?php foreach ($ach['held'] as $a): ?>
            <li><span class="me-ach-words"><?= h($a['words']) ?></span><span class="me-ach-points"><?= t('me.ach_point', ['n' => $a['points']]) ?></span><span class="meta-inline"><?= $a['at'] ? h(date('Y-m-d', $a['at'])) : '' ?></span></li>
          <?php endforeach; ?>
        </ul>
      <?php endif; ?>
    </section>
  <?php // Their broadcasts, while the server has any: their switch, whether they are on air, their recordings, and the
        // live page narrowed to them. ?>
  <?php if ($casts['on']): ?>
  <section class="card me-casts">
    <h2><?= t('me.casts') ?></h2>
    <p class="me-state<?= $casts['on_air'] ? ' on' : ($casts['switch'] ? ' wait' : '') ?>"><i aria-hidden="true"></i><?= t($casts['on_air'] ? 'me.on_air' : ($casts['switch'] ? 'me.cast_on' : 'me.cast_off')) ?></p>
    <p class="meta"><?= t('me.cast_switch') ?></p>
    <p class="meta"><?= $casts['recordings'] ? t('me.recs', ['n' => $casts['recordings'], 'length' => clock_length($casts['seconds']), 'ago' => ago($casts['newest'])]) : t('me.recs_none') ?></p>
    <?php if ($casts['recordings'] || $casts['on_air']): ?>
      <div class="btn-line"><a class="btn" href="/opendmtq/live.php?who=<?= (int)$guid ?>"><?= t('me.recs_watch') ?></a></div>
    <?php endif; ?>
  </section>
  <?php endif; ?>
  <?php endif; ?>
<?php elseif ($tab === 'plays' || $tab === 'records'): ?>
  <?php $list = $tab === 'plays' ? me_plays($db, $guid, $page) : me_records($db, $guid, $page); ?>
  <section class="card">
    <h2><?= t($tab === 'plays' ? 'me.plays' : 'me.records') ?> <span class="meta-inline"><?= t($tab === 'plays' ? 'me.plays_sum' : 'me.records_sum', ['n' => number_format($list['total'])]) ?></span></h2>
    <?php if (!$list['items']): ?>
      <p class="empty"><?= t($tab === 'plays' ? 'player.recent_empty' : 'player.best_empty') ?></p>
    <?php else: ?>
      <?php // The same columns as the public page's lists: jacket, song, chart, score with the keyboard's mark, a mark, when. ?>
      <div class="table-scroll"><table class="compact plays"><tbody>
      <?php foreach ($list['items'] as $r): ?>
        <?php if ($tab === 'plays'): ?>
          <?= me_row($r, $r['is_record'] ? '<span class="mark new" data-tip="' . h(tp('mark.new')) . '" tabindex="0">NEW</span>' : '', ago((int)$r['played_at'])) ?>
        <?php else: ?>
          <?= me_row($r, grade_cell($r), ago($r['set_at'])) ?>
        <?php endif; ?>
      <?php endforeach; ?>
      </tbody></table></div>
      <?= me_pager($tab, $list) ?>
    <?php endif; ?>
  </section>
<?php else: ?>
  <?php // What was just done, said once at the top (the address says it, so a reload says it again, not does it). ?>
  <?php $done = (string)($_GET['done'] ?? ''); if (isset(ME_DONE[$done]) && $said === null): ?>
    <p class="done" role="status"><?= t(ME_DONE[$done], ['id' => $account['id']]) ?></p>
  <?php endif; ?>
  <?php // Everything the site keeps about the account, in one place; what the owner decides is shown, not changed. ?>
  <section class="card">
    <h2><?= t('me.account') ?></h2>
    <dl class="facts">
      <dt><?= t('me.id') ?></dt><dd><code><?= h($account['id']) ?></code></dd>
      <?php if (!$account['owner']): ?>
        <dt><?= t('me.made') ?></dt><dd><?= me_when($account['made']) ?></dd>
        <dt><?= t('me.last_in') ?></dt><dd><?= me_when($account['last_in']) ?></dd>
      <?php endif; ?>
      <dt><?= t('me.this_in') ?></dt><dd><?= me_when($account['this_in']) ?></dd>
      <?php if (!$account['owner']): ?>
        <dt><?= t('me.player') ?></dt><dd><?= $fig ? '<a href="/opendmtq/player.php?id=' . (int)$guid . '">' . h((string)$fig['name']) . '</a>' : t('me.player_none') ?></dd>
        <dt><?= t('me.note') ?></dt><dd><?= $account['note'] !== '' ? h($account['note']) : '<span class="meta-inline">' . t('me.note_none') . '</span>' ?></dd>
      <?php endif; ?>
      <dt><?= t('me.rights') ?></dt><dd><?= t($account['owner'] ? 'me.rights_owner' : ($account['admin'] ? 'me.rights_yes' : 'me.rights_no')) ?></dd>
      <dt><?= t('me.language') ?></dt><dd><?= t('me.language_now') ?></dd>
    </dl>
    <?php if (!$account['owner']): ?>
      <p class="meta"><?= t('me.decided') ?></p>
    <?php endif; ?>
  </section>
  <?php if ($account['owner']): ?>
    <?php // The server's own account: its ID and password are the server's, changed on the admin pages' Server page. ?>
    <section class="card">
      <h2><?= t('me.pw') ?></h2>
      <p class="lead"><?= t('me.owner_line') ?></p>
      <div class="btn-line"><a class="btn" href="/opendmtq/admin/server#password"><?= t('me.owner_go') ?></a></div>
    </section>
  <?php else: ?>
    <?php // The two changes that ask for the current password side by side where there is room, one under the other on a
          // phone. ?>
    <div class="two">
    <?php // The password: the current one, then the new one twice. The page's one main button: what one comes here for. ?>
    <?php $said_here = ($form === 'password' && is_array($said)) ? $said : []; ?>
    <section class="card" id="password">
      <h2><?= t('me.pw') ?></h2>
      <p class="lead"><?= t('me.pw_lead') ?></p>
      <?php if ($said_here && $said_here[0] === ''): ?><p class="error" role="alert"><?= t($said_here[1]) ?></p><?php endif; ?>
      <form method="post" action="/opendmtq/me.php?tab=account&amp;do=password" class="me-form" novalidate>
        <?php // The ID for the browser's password manager, which keeps the new password under it. ?>
        <input type="text" name="username" value="<?= h($account['id']) ?>" autocomplete="username" hidden>
        <?= me_password_field('me-current', 'current', tp('me.pw_current'), 'current-password', $said_here) ?>
        <?= me_password_field('me-new', 'password', tp('me.pw_new'), 'new-password', $said_here) ?>
        <?= me_password_field('me-new2', 'password2', tp('me.pw_again'), 'new-password', $said_here) ?>
        <p class="meta"><?= t($account['admin'] ? 'me.pw_rule_admin' : 'me.pw_rule') ?></p>
        <div class="btn-line"><button class="btn btn-primary"><?= t('me.pw_button') ?></button></div>
      </form>
    </section>
    <?php // The ID: the new one, and the current password for it. ?>
    <?php $said_here = ($form === 'id' && is_array($said)) ? $said : []; ?>
    <section class="card" id="id">
      <h2><?= t('me.idc') ?></h2>
      <p class="lead"><?= t($account['admin'] ? 'me.id_lead_admin' : 'me.id_lead') ?></p>
      <?php if ($said_here && $said_here[0] === ''): ?><p class="error" role="alert"><?= t($said_here[1]) ?></p><?php endif; ?>
      <form method="post" action="/opendmtq/me.php?tab=account&amp;do=id" class="me-form" novalidate>
        <?php $wrong = $said_here && $said_here[0] === 'id'; ?>
        <div class="field">
          <label for="me-id"><?= t('me.id_new') ?></label>
          <?php // In Latin letters, as an ID is: the email keyboard, no capitals or corrections, as the sign-in's field. ?>
          <span class="slot"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="8" r="4"/><path d="M4.5 20c1.4-3.7 4.3-5.6 7.5-5.6s6.1 1.9 7.5 5.6"/></svg><input id="me-id" name="id" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" inputmode="email" lang="en" required pattern="[A-Za-z0-9._\-]{3,20}" data-missing="<?= h(tp('me.missing_id')) ?>" data-invalid="<?= h(tp('me.bad_id')) ?>" value="<?= h($form === 'id' ? trim((string)($_POST['id'] ?? '')) : '') ?>"<?= $wrong ? ' aria-invalid="true" aria-describedby="me-id-error" autofocus' : '' ?>></span>
          <?php if ($wrong): ?><span class="field-error" id="me-id-error" role="alert"><?= t($said_here[1]) ?></span><?php endif; ?>
        </div>
        <?= me_password_field('me-id-current', 'current', tp('me.pw_current'), 'current-password', $said_here) ?>
        <div class="btn-line"><button class="btn"><?= t('me.id_button') ?></button></div>
      </form>
    </section>
    </div>
  <?php endif; ?>
  <?php // Every other sign-in of the account ended; this browser's stays. ?>
  <section class="card" id="signout">
    <h2><?= t('me.out') ?></h2>
    <p class="lead"><?= t('me.out_lead') ?></p>
    <?php if ($form === 'signout' && is_array($said)): ?><p class="error" role="alert"><?= t($said[1]) ?></p><?php endif; ?>
    <form method="post" action="/opendmtq/me.php?tab=account&amp;do=signout"><div class="btn-line"><button class="btn"><?= t('me.out_button') ?></button></div></form>
  </section>
  <?php // The forms' own check before they go, and Show in the password fields. ?>
  <script src="<?= asset_url('forms.js') ?>" defer></script>
<?php endif; ?>
<?php page_footer();
