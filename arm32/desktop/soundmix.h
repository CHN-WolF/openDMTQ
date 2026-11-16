// The game's music and its effects apart (the sound panel's music and effects shares): the game plays every sound of
// its songs and menus through its own OpenAL (libopenal.so, reached from the game's C# by name), which mixes them into
// one AudioTrack, where they can no longer be told apart. So the player stands between the game and three of OpenAL's
// calls: each source's gain the game sets is kept, and OpenAL is given that gain times the share of the source's kind,
// which OpenAL itself says (a streaming source is music: the song's own stream, the menus' music, a song's preview; a
// source of one whole buffer is an effect: the notes' key sounds, the judgement's and the menus' sounds). The calls are
// the game's own by name (libopenal's symbol table points them at the player's stubs, which call the originals): no
// code of the game's is changed.
#pragma once

#include "thread.h"

#include <string>

namespace player {

// A library of the game's loaded (main.cpp): libopenal.so's calls are taken over at once, before the game looks any of
// them up.
void soundmix_library_loaded(const std::string& name, arm32::gaddr handle);
// On the game's render thread each frame: shares changed by the panel are given to every source the game has.
void soundmix_render(arm32::Thread& th);
// The music's and the effects' gains (sound_mix.h percent_gain) from now on.
void soundmix_shares(float music, float effects);

}  // namespace player
