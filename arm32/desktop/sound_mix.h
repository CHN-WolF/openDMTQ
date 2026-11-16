// The player's own sound controls over the game's (the settings file's volume, music_volume, effects_volume, eq,
// eq_low, eq_mid and eq_high; the in-game sound panel changes them as the game plays): the gains they make and the
// equaliser on the whole mix. Plain arithmetic apart from any device, so that a check (audiotest.cpp) runs tones
// through it.
//
// - Master (volume), music and effects in percent, each a gain of the square of its share (half way is about half as
//   loud, as the master always was). Music and effects are shares of the master: the game's music (the song's own
//   stream, the menus' music, a song's preview) and its effects (the notes' key sounds, the judgement's and the menus'
//   sounds).
// - The equaliser: three bands, a low shelf at 120 Hz, a peak at 1 kHz an octave and a half wide, a high shelf at 6 kHz
//   (RBJ's biquads, Audio EQ Cookbook), each -12 to +12 dB; presets for flat, bass, vocal and treble, or the bands as
//   chosen (custom). A band raised takes the same off the whole first, so that a raised band never clips where the mix
//   was full. Flat is no filter at all: the mix passes as it is.
#pragma once

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <string>

namespace player::audio {

// The equaliser's presets, as the settings file names them, and the bands each sets (dB: low, mid, high).
enum class EqPreset { kFlat, kBass, kVocal, kTreble, kCustom };
struct EqBands {
    int low = 0, mid = 0, high = 0;
};
inline const char* eq_name(EqPreset p) {
    switch (p) {
    case EqPreset::kFlat: return "flat";
    case EqPreset::kBass: return "bass";
    case EqPreset::kVocal: return "vocal";
    case EqPreset::kTreble: return "treble";
    case EqPreset::kCustom: return "custom";
    }
    return "flat";
}
// A preset by its name, false for none.
inline bool eq_from_name(const std::string& name, EqPreset& out) {
    for (EqPreset p : {EqPreset::kFlat, EqPreset::kBass, EqPreset::kVocal, EqPreset::kTreble, EqPreset::kCustom}) {
        if (name == eq_name(p)) {
            out = p;
            return true;
        }
    }
    return false;
}
// The bands a preset sets: bass lifts the low end, vocal the voices' middle (a little off the low end so that the voice
// stands out), treble the top; custom keeps the bands chosen.
inline EqBands preset_bands(EqPreset p, EqBands custom) {
    switch (p) {
    case EqPreset::kFlat: return {0, 0, 0};
    case EqPreset::kBass: return {6, 0, 0};
    case EqPreset::kVocal: return {-2, 4, 1};
    case EqPreset::kTreble: return {0, 0, 6};
    case EqPreset::kCustom: return custom;
    }
    return {0, 0, 0};
}
// The band limits, in dB.
constexpr int kEqMost = 12;
inline int clamp_band(int db) { return std::clamp(db, -kEqMost, kEqMost); }

// A share in percent as a gain: its square, 0 to 1 (the master's rule since it began).
inline float percent_gain(int percent) {
    const float share = static_cast<float>(std::clamp(percent, 0, 100)) / 100.0f;
    return share * share;
}

// What the controls are now: the master, music and effects in percent, and the equaliser.
struct Levels {
    int master = 100, music = 100, effects = 100;
    EqPreset eq = EqPreset::kFlat;
    // The bands as chosen for custom (presets set their own).
    EqBands custom;
    // The bands in use: the preset's, or the custom ones.
    EqBands bands() const { return preset_bands(eq, custom); }
};

// One biquad's coefficients (normalised: a0 is 1) and its two samples of state per channel.
struct Biquad {
    float b0 = 1, b1 = 0, b2 = 0, a1 = 0, a2 = 0;
    // Direct form I's past: x[n-1], x[n-2], y[n-1], y[n-2] for each of two channels.
    float x1[2] = {}, x2[2] = {}, y1[2] = {}, y2[2] = {};
    float run(int c, float x) {
        const float y = b0 * x + b1 * x1[c] + b2 * x2[c] - a1 * y1[c] - a2 * y2[c];
        x2[c] = x1[c];
        x1[c] = x;
        y2[c] = y1[c];
        y1[c] = y;
        return y;
    }
};

// RBJ's shelves and peak (the Audio EQ Cookbook), at `rate` frames a second: `low` for the low shelf, else the high,
// with a shelf slope of 1; the peak with the bandwidth `octaves`. Gains in dB; 0 dB is a pass-through.
inline Biquad shelf(double rate, double freq, double db, bool low) {
    const double A = std::pow(10.0, db / 40.0);
    const double w0 = 2.0 * 3.14159265358979323846 * freq / rate;
    const double cw = std::cos(w0), sw = std::sin(w0);
    // Slope S = 1: alpha = sin(w0)/2 * sqrt(2).
    const double alpha = sw / 2.0 * std::sqrt(2.0);
    const double sa = 2.0 * std::sqrt(A) * alpha;
    double b0, b1, b2, a0, a1, a2;
    if (low) {
        b0 = A * ((A + 1) - (A - 1) * cw + sa);
        b1 = 2 * A * ((A - 1) - (A + 1) * cw);
        b2 = A * ((A + 1) - (A - 1) * cw - sa);
        a0 = (A + 1) + (A - 1) * cw + sa;
        a1 = -2 * ((A - 1) + (A + 1) * cw);
        a2 = (A + 1) + (A - 1) * cw - sa;
    } else {
        b0 = A * ((A + 1) + (A - 1) * cw + sa);
        b1 = -2 * A * ((A - 1) + (A + 1) * cw);
        b2 = A * ((A + 1) + (A - 1) * cw - sa);
        a0 = (A + 1) - (A - 1) * cw + sa;
        a1 = 2 * ((A - 1) - (A + 1) * cw);
        a2 = (A + 1) - (A - 1) * cw - sa;
    }
    Biquad q;
    q.b0 = static_cast<float>(b0 / a0);
    q.b1 = static_cast<float>(b1 / a0);
    q.b2 = static_cast<float>(b2 / a0);
    q.a1 = static_cast<float>(a1 / a0);
    q.a2 = static_cast<float>(a2 / a0);
    return q;
}
inline Biquad peak(double rate, double freq, double db, double octaves) {
    const double A = std::pow(10.0, db / 40.0);
    const double w0 = 2.0 * 3.14159265358979323846 * freq / rate;
    const double cw = std::cos(w0), sw = std::sin(w0);
    const double alpha = sw * std::sinh(std::log(2.0) / 2.0 * octaves * w0 / sw);
    const double a0 = 1 + alpha / A;
    Biquad q;
    q.b0 = static_cast<float>((1 + alpha * A) / a0);
    q.b1 = static_cast<float>((-2 * cw) / a0);
    q.b2 = static_cast<float>((1 - alpha * A) / a0);
    q.a1 = static_cast<float>((-2 * cw) / a0);
    q.a2 = static_cast<float>((1 - alpha / A) / a0);
    return q;
}

// The equaliser's corners: the low shelf's, the peak's centre and width, the high shelf's.
constexpr double kLowHz = 120, kMidHz = 1000, kMidOctaves = 1.5, kHighHz = 6000;

// The three bands over interleaved stereo frames, with the headroom a raised band takes first. Set again on any change
// (its state kept, so that a change mid-sound makes no click beyond the curve's own change).
class Equalizer {
public:
    // At `rate` frames a second, the bands in dB. Flat leaves the frames as they are.
    void set(int rate, EqBands b) {
        b = {clamp_band(b.low), clamp_band(b.mid), clamp_band(b.high)};
        flat_ = b.low == 0 && b.mid == 0 && b.high == 0;
        const Biquad low = shelf(rate, kLowHz, b.low, true), mid = peak(rate, kMidHz, b.mid, kMidOctaves), high = shelf(rate, kHighHz, b.high, false);
        // The coefficients new, the past kept.
        copy_coefficients(low_, low);
        copy_coefficients(mid_, mid);
        copy_coefficients(high_, high);
        // The most a band raises, taken off the whole first.
        const int most = std::max({0, b.low, b.mid, b.high});
        pre_ = static_cast<float>(std::pow(10.0, -most / 20.0));
        bands_ = b;
    }
    // Runs `frames` stereo frames in place.
    void run(float* stereo, std::size_t frames) {
        if (flat_) return;
        for (std::size_t i = 0; i < frames; ++i) {
            for (int c = 0; c < 2; ++c) {
                float x = stereo[i * 2 + static_cast<std::size_t>(c)] * pre_;
                x = low_.run(c, x);
                x = mid_.run(c, x);
                x = high_.run(c, x);
                stereo[i * 2 + static_cast<std::size_t>(c)] = x;
            }
        }
    }
    bool flat() const { return flat_; }
    EqBands bands() const { return bands_; }
    float headroom() const { return pre_; }

private:
    static void copy_coefficients(Biquad& to, const Biquad& from) {
        to.b0 = from.b0;
        to.b1 = from.b1;
        to.b2 = from.b2;
        to.a1 = from.a1;
        to.a2 = from.a2;
    }
    bool flat_ = true;
    float pre_ = 1;
    EqBands bands_;
    Biquad low_, mid_, high_;
};

}  // namespace player::audio
