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

// A JSON string value whose opening quote is at `at` of a flat answer, as UTF-8, with the escapes PHP's json_encode
// writes read (\" \\ \/ \b \f \n \r \t, \uXXXX, and a pair of them for a character past U+FFFF); "" for one without its
// end. Half a pair alone is U+FFFD and NUL is left out, as the broadcast's own reader of the answer has them
// (src/live_net.cpp, which this header does not link: a check takes it alone). `whole`, when given, says whether the
// string had its end (an empty string "" has; a value cut short has not).
inline std::string string_at(const std::string& json, std::size_t at, bool* whole = nullptr) {
    if (whole) *whole = false;
    std::string out;
    // Not a string: nothing.
    if (at >= json.size() || json[at] != '"') return out;
    // A character's UTF-8 bytes.
    auto put = [&out](unsigned long c) {
        if (c < 0x80) {
            out += static_cast<char>(c);
        } else if (c < 0x800) {
            out += static_cast<char>(0xC0 | (c >> 6));
            out += static_cast<char>(0x80 | (c & 0x3F));
        } else if (c < 0x10000) {
            out += static_cast<char>(0xE0 | (c >> 12));
            out += static_cast<char>(0x80 | ((c >> 6) & 0x3F));
            out += static_cast<char>(0x80 | (c & 0x3F));
        } else {
            out += static_cast<char>(0xF0 | (c >> 18));
            out += static_cast<char>(0x80 | ((c >> 12) & 0x3F));
            out += static_cast<char>(0x80 | ((c >> 6) & 0x3F));
            out += static_cast<char>(0x80 | (c & 0x3F));
        }
    };
    // Four hex digits at `from` as a number, or -1.
    auto hex4 = [&json](std::size_t from) -> long {
        if (from + 4 > json.size()) return -1;
        long v = 0;
        for (std::size_t i = from; i < from + 4; ++i) {
            const char c = json[i];
            const int d = c >= '0' && c <= '9' ? c - '0' : c >= 'a' && c <= 'f' ? c - 'a' + 10 : c >= 'A' && c <= 'F' ? c - 'A' + 10 : -1;
            if (d < 0) return -1;
            v = v * 16 + d;
        }
        return v;
    };
    for (++at; at < json.size(); ++at) {
        // The string's end: all of it read.
        if (json[at] == '"') {
            if (whole) *whole = true;
            return out;
        }
        if (json[at] != '\\') {
            out += json[at];
            continue;
        }
        // An escape: the character after the backslash says which.
        if (++at >= json.size()) break;
        switch (json[at]) {
        case 'n': out += '\n'; break;
        case 't': out += '\t'; break;
        case 'r': out += '\r'; break;
        case 'b': out += '\b'; break;
        case 'f': out += '\f'; break;
        case 'u': {
            const long c = hex4(at + 1);
            // Not four hex digits: the backslash and the u left out, what follows read as it is.
            if (c < 0) break;
            at += 4;
            // A UTF-16 pair, as json_encode writes a character past U+FFFF: one character.
            if (c >= 0xD800 && c <= 0xDBFF && at + 2 < json.size() && json[at + 1] == '\\' && json[at + 2] == 'u') {
                const long low = hex4(at + 3);
                if (low >= 0xDC00 && low <= 0xDFFF) {
                    put(0x10000 + ((static_cast<unsigned long>(c) - 0xD800) << 10) + (static_cast<unsigned long>(low) - 0xDC00));
                    at += 6;
                    break;
                }
            }
            // Half a pair alone is no character: the replacement character. NUL would end the text as a C string: out.
            if (c >= 0xD800 && c <= 0xDFFF) put(0xFFFD);
            else if (c != 0) put(static_cast<unsigned long>(c));
            break;
        }
        // A quote, a backslash or a slash: itself.
        default: out += json[at];
        }
    }
    // No end: a string cut short is none.
    return {};
}

// What a newer server says of the player's ban in each answer to GET /live/state ("ban"): `given` where the answer has
// the key (an older server's answers have none, nor one whose ids name no player), with the ban's notice ("title\ndetail")
// in the player's language while the ban lasts, "" while there is none.
struct BanWord {
    bool given = false;
    std::string text;
};
inline BanWord ban_of(const std::string& body) {
    BanWord b;
    // Found as a key (a quoted name and a colon): the kind's value "ban" is no key ban.
    const std::size_t at = value_at(body, "ban");
    if (at == std::string::npos || body[at] != '"') return b;
    // Words cut short say nothing either way.
    bool whole = false;
    b.text = string_at(body, at, &whole);
    b.given = whole;
    return b;
}

// The ban's notice that stays over the game while the server refuses the player's game, for one answer: whether the
// notice held changes (`change`) and to what (`text`; "" lets it go), with the player's own notice to show as it goes
// (`over`: the ban is over). `held` is the text held now ("" for none), kept between answers.
struct Hold {
    bool change = false;
    std::string text;
    Notice over;
};

// One answer's part in the notice that stays (`answered`, the answer's `ban`): held while the answer carries the ban's
// words (taken again whenever they change: a ban made again with another reason or end), let go at the first answer
// that carries "" instead, with the player's own words that it can play again; no answer, or one that says nothing of a
// ban (an older server's, or one that names nobody), changes nothing. `korean` for the words.
inline Hold hold_of(bool answered, const BanWord& ban, std::string& held, bool korean) {
    Hold h;
    if (!answered || !ban.given) return h;
    if (!ban.text.empty()) {
        // The same words as held: nothing to do.
        if (ban.text == held) return h;
        held = ban.text;
        h.change = true;
        h.text = ban.text;
        return h;
    }
    // No ban, and none held: nothing to say.
    if (held.empty()) return h;
    held.clear();
    h.change = true;
    h.over.show = true;
    h.over.text = korean ? "\xec\x9d\xb4 \xec\x84\x9c\xeb\xb2\x84\xec\x97\x90\xec\x84\x9c \xeb\x8b\xa4\xec\x8b\x9c \xed\x94\x8c\xeb\xa0\x88\xec\x9d\xb4\xed\x95\xa0 \xec\x88\x98 \xec\x9e\x88\xec\x96\xb4\xec\x9a\x94\n"
                           "\xec\x9d\xb4\xec\x9a\xa9 \xec\xa0\x95\xec\xa7\x80\xea\xb0\x80 \xeb\x81\x9d\xeb\x82\xac\xec\x96\xb4\xec\x9a\x94"
                         : "You can play on this server again\nThe ban has ended";
    return h;
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
