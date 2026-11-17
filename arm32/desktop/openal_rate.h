// The rate the game's OpenAL mixes at on the PC: a phone's.
//
// The game's OpenAL (OpenAL Soft 1.13) has two ways out, tried in that order when the game opens its default device:
// OpenSL ES, whose reset sets 44,100 Hz whatever the game asked (so every phone mixes the game's sound at 44,100 Hz),
// and android.media.AudioTrack ("Android Legacy"), whose open sets 22,050 Hz and whose mix runs at the rate the game's
// context asks for, else at that. The game asks for none. The player has no OpenSL ES, so the game's OpenAL opens its
// AudioTrack device, and at 22,050 Hz everything above 11 kHz of the game's 44.1 kHz samples was gone: the top octave
// of every song. The player gives the game's context on that device the rate a phone mixes at, so the PC mixes as a
// phone does and its own resampler takes the sound to the device's rate from there.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace player::audio {

// ALC's name for a device's mixing rate (alc.h), and the rate the game's OpenAL mixes at on a phone.
constexpr std::uint32_t kAlcFrequency = 0x1007;
constexpr std::uint32_t kPhoneOpenAlRate = 44100;
// The name OpenAL Soft gives its AudioTrack device.
inline const char* const kAudioTrackDevice = "Android Legacy";

// The attributes for the game's context on `device`, as pairs without the list's closing 0: on OpenAL's AudioTrack
// device the game's own with the phone's rate in place of a rate it asked for (or after them when it asked for none);
// on any other device (OpenSL ES sets its own rate) the game's own as they are.
inline std::vector<std::uint32_t> context_attributes(const std::string& device, const std::vector<std::uint32_t>& asked) {
    if (device != kAudioTrackDevice) return asked;
    std::vector<std::uint32_t> out;
    bool rate = false;
    for (std::size_t i = 0; i + 1 < asked.size(); i += 2) {
        out.push_back(asked[i]);
        // A rate the game asked for gives way to the phone's.
        if (asked[i] == kAlcFrequency) {
            out.push_back(kPhoneOpenAlRate);
            rate = true;
        } else {
            out.push_back(asked[i + 1]);
        }
    }
    if (!rate) {
        out.push_back(kAlcFrequency);
        out.push_back(kPhoneOpenAlRate);
    }
    return out;
}

}  // namespace player::audio
