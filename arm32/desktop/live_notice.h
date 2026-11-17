// What the PC player shows of the broadcast's answers (live_desktop.cpp): the server's notices, each once, and its own
// when the server stops answering while the PC broadcasts. Apart from the runtime's shared code (src/live_net.cpp, which
// a phone's runtime is built from too and which stays as it is), and from any window, so that a check
// (settingstest.cpp) takes answers through it.
#pragma once

#include <string>

namespace player::live_notice {

// The notice's number and kind in an answer to GET /live/state (a newer server's): -1 and "" without them. Its keys are
// found as keys (a quoted name followed by a colon): the kind's value "on" is no key on.
struct Fields {
    int id = -1;
    std::string kind;
};

// Where the value of "key" starts in a flat JSON answer, or npos.
inline std::size_t value_at(const std::string& json, const char* key) {
    const std::string quoted = std::string("\"") + key + "\"";
    for (std::size_t from = 0;;) {
        std::size_t at = json.find(quoted, from);
        if (at == std::string::npos) return at;
        from = at + quoted.size();
        at = from;
        // The white space JSON allows, then the colon: a key; else a string value of the same words.
        while (at < json.size() && (json[at] == ' ' || json[at] == '\t' || json[at] == '\n' || json[at] == '\r')) ++at;
        if (at >= json.size() || json[at] != ':') continue;
        ++at;
        while (at < json.size() && (json[at] == ' ' || json[at] == '\t' || json[at] == '\n' || json[at] == '\r')) ++at;
        return at < json.size() ? at : std::string::npos;
    }
}

inline Fields fields_of(const std::string& body) {
    Fields f;
    std::size_t at = value_at(body, "toast_id");
    if (at != std::string::npos) {
        // A whole number (the server sends no negative one); anything else: 0, a notice with no number.
        int n = 0;
        while (at < body.size() && body[at] >= '0' && body[at] <= '9' && n < 100000000) n = n * 10 + (body[at++] - '0');
        f.id = n;
    }
    at = value_at(body, "toast_kind");
    if (at != std::string::npos && body[at] == '"') {
        // The kinds are short ASCII words: up to the closing quote.
        const std::size_t end = body.find('"', at + 1);
        if (end != std::string::npos && end - at - 1 <= 16) f.kind = body.substr(at + 1, end - at - 1);
    }
    return f;
}

// What to show now: whether, the text ("title\ndetail") and whether it wears the LIVE tag.
struct Notice {
    bool show = false;
    std::string text;
    bool live = false;
};

// One answer's notice (`answered`, `on` air, its `toast` and `fields`): every notice the server hands out, on and off
// alike, each once: one numbered not above `last_id` (the number of the last one shown, which this keeps; 0 at first)
// is a repeat and left out, never one by its words (on, off and on again read the same). The LIVE tag on the on notice
// (by its kind; an older server's, while the answer is on air). The on notice is left out where this computer cannot
// send (`gave_up`): it would not be true.
inline Notice notice_of(bool answered, bool on, const std::string& toast, const Fields& fields, int& last_id, bool gave_up) {
    Notice n;
    if (!answered || toast.empty()) return n;
    if (fields.id > 0 && fields.id <= last_id) return n;
    if (fields.id > 0) last_id = fields.id;
    const bool on_notice = fields.kind.empty() ? on : fields.kind == "on";
    if (on_notice && gave_up) return n;
    n.show = true;
    n.text = toast;
    n.live = on_notice;
    return n;
}

// Asks in a row without an answer that make the broadcast's server lost (15 s at the PC's pace of one each 5 s).
constexpr int kLostAfter = 3;

// The player's own notice when the server stops answering while the PC broadcasts, and when it answers again (the server
// cannot say either itself): `misses` and `lost` are the poller's, kept between its asks (0 and false at first). kLostAfter
// asks in a row without an answer while the last answer was on air: "stopped", once; the next answer after that, if it
// is on air: "back", with the LIVE tag. Asks while off air count nothing. `korean` for the words.
inline Notice reach_notice(bool answered, bool on, bool was_on, int& misses, bool& lost, bool korean) {
    Notice n;
    if (!answered) {
        if (!was_on || lost) return n;
        if (++misses < kLostAfter) return n;
        lost = true;
        n.show = true;
        n.text = korean ? "\xeb\xb0\xa9\xec\x86\xa1\xec\x9d\xb4 \xeb\xa9\x88\xec\xb7\x84\xec\x96\xb4\xec\x9a\x94\n"
                          "\xec\x84\x9c\xeb\xb2\x84\xea\xb0\x80 \xec\x9d\x91\xeb\x8b\xb5\xed\x95\x98\xec\xa7\x80 \xec\x95\x8a\xec\x95\x84\xec\x9a\x94"
                        : "Your broadcast has stopped\nThe server is not answering";
        return n;
    }
    misses = 0;
    if (!lost) return n;
    lost = false;
    // Back: said only when the broadcast goes on (off air, the server's own notice says what it is).
    if (!on) return n;
    n.show = true;
    n.live = true;
    n.text = korean ? "\xeb\xb0\xa9\xec\x86\xa1\xec\x9d\xb4 \xeb\x8b\xa4\xec\x8b\x9c \xec\x9d\xb4\xec\x96\xb4\xec\xa0\xb8\xec\x9a\x94\n"
                      "\xec\x84\x9c\xeb\xb2\x84\xea\xb0\x80 \xeb\x8b\xa4\xec\x8b\x9c \xec\x9d\x91\xeb\x8b\xb5\xed\x95\xb4\xec\x9a\x94"
                    : "Your broadcast is back on\nThe server answers again";
    return n;
}

}  // namespace player::live_notice
