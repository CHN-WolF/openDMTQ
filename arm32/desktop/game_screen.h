// The size the game renders at, as the game's own Screen says it, kept to the size the player gives it: the window's game
// area at the render scale. Unity takes its surface's size as it starts; a window resized or switched to full screen
// later kept the first size and stretched its layout over the new shape (at 21:9 after 16:9 its song cards twice as
// wide as tall, its words wide), where a start at that size lays the screens out for it. The game is told the new size
// (its own Screen.SetResolution) once the window has settled, and the log says the size the game renders at whenever it
// changes. On Unity's main thread at its native render calls, as keyboard play's look for the game is.
#pragma once

#include "thread.h"

#include <string>

namespace player {

// A library of the game's loaded (main.cpp): libil2cpp.so's handle, for Unity's Screen calls.
void game_screen_library_loaded(const std::string& name, arm32::gaddr handle);
// Each render call: every 10th, the game's Screen read and, after a resize, set.
void game_screen_render(arm32::Thread& th);

}  // namespace player
