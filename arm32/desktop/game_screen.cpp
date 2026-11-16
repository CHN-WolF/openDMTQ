// The size the game renders at, kept to the size the player gives it (game_screen.h).
#include "game_screen.h"

#include "guest.h"
#include "host.h"
#include "jvm.h"
#include "player.h"

#include <map>
#include <string>

namespace player {

namespace {

using arm32::gaddr;
using arm32::Guest;
using arm32::Thread;

Guest& g() { return Guest::get(); }

// libil2cpp.so's handle, once loaded; Unity's Screen calls (0: not looked up yet, 1: not there).
gaddr g_il2cpp = 0;
gaddr g_width = 0, g_height = 0, g_set = 0;
// What the game's Screen said last (said in the log when it changes), the size it was last told, and how many looks in a
// row it has differed from the player's size (a resize settles over a few frames).
int g_said_w = -1, g_said_h = -1, g_told_w = 0, g_told_h = 0, g_differs = 0;
unsigned g_renders = 0;

// A guest copy of each name for the calls, which only read them: made once, kept.
gaddr name(const char* s) {
    static std::map<std::string, gaddr> kept;
    auto it = kept.find(s);
    if (it != kept.end()) return it->second;
    return kept[s] = g().strdup(s);
}

}  // namespace

void game_screen_library_loaded(const std::string& library, gaddr handle) {
    if (library == "libil2cpp.so") g_il2cpp = handle;
}

void game_screen_render(Thread& th) {
    // Every 10th render call: a few times a second, at a cost of two calls into the game.
    if (!g_il2cpp || g_renders++ % 10) return;
    if (!g_width) {
        const gaddr current = g().dlsym(g_il2cpp, "il2cpp_thread_current"), resolve = g().dlsym(g_il2cpp, "il2cpp_resolve_icall");
        // Before IL2CPP is up, or on a thread it does not know, its API must not be used.
        if (!current || !resolve || !th.call(current, {})) return;
        g_width = static_cast<gaddr>(th.call(resolve, {name("UnityEngine.Screen::get_width")}));
        g_height = static_cast<gaddr>(th.call(resolve, {name("UnityEngine.Screen::get_height")}));
        g_set = static_cast<gaddr>(th.call(resolve, {name("UnityEngine.Screen::SetResolution")}));
        if (!g_width || !g_height) {
            g_width = 1;
            jvm::log("player: the game's Screen size cannot be read: the size it renders at is not followed");
        }
    }
    if (g_width <= 1) return;
    const int w = static_cast<int>(th.call(g_width, {})), h = static_cast<int>(th.call(g_height, {}));
    if (w != g_said_w || h != g_said_h) {
        g_said_w = w;
        g_said_h = h;
        jvm::log("player: the game renders at %dx%d (its own Screen size)", w, h);
    }
    // The size the player gives it: the window's game area at the render scale.
    const int want_w = app().width, want_h = app().height;
    if (w == want_w && h == want_h) {
        g_differs = 0;
        return;
    }
    // Unity takes the surface's size only as it starts: a window resized or switched to full screen later kept its first
    // size and stretched its layout over the new shape. Told the new size once it has held for three looks (the frame
    // settles), and once only for each size.
    if (++g_differs < 3 || !g_set || (want_w == g_told_w && want_h == g_told_h) || want_w <= 0 || want_h <= 0) return;
    g_told_w = want_w;
    g_told_h = want_h;
    // SetResolution(width, height, fullScreen, preferredRefreshRate): the game's own window is the whole of its surface.
    th.call(g_set, {static_cast<std::uint32_t>(want_w), static_cast<std::uint32_t>(want_h), 1u, 0u});
    jvm::log("player: the game told its new size %dx%d (it rendered at %dx%d)", want_w, want_h, w, h);
}

}  // namespace player
