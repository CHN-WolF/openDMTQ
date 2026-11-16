// Tests of the desktop player's mixer (mixer.h), on the host alone: the resampler's accuracy (a tone in the band comes
// out as the same tone with everything else far below it, a tone above the output's band does not fold back into it),
// a stream's formats, its write waiting while the buffer is full and its underrun counter, the mix of two streams and
// its clipping, and the null output keeping real time. Prints one line per check, then "ALL CHECKS PASSED".
#include "mixer.h"

#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <thread>
#include <vector>

using namespace player::audio;

namespace {

int g_checks = 0, g_failures = 0;

void check(bool ok, const char* what) {
    ++g_checks;
    if (!ok) ++g_failures;
    std::printf("%s %s\n", ok ? "ok  " : "FAIL", what);
}

constexpr double kPi = 3.14159265358979323846;

// A tone of `freq` Hz at `rate`, `seconds` long, as interleaved stereo.
std::vector<float> tone(double freq, int rate, double seconds, double amplitude) {
    std::size_t frames = static_cast<std::size_t>(rate * seconds);
    std::vector<float> v(frames * kChannels);
    for (std::size_t n = 0; n < frames; ++n) {
        float x = static_cast<float>(amplitude * std::sin(2 * kPi * freq * static_cast<double>(n) / rate));
        v[n * 2] = x;
        v[n * 2 + 1] = x;
    }
    return v;
}

// `input` through a resampler, a period of output at a time as the mixer asks for it.
std::vector<float> resample(const std::vector<float>& input, int in_rate, int out_rate) {
    Resampler r(in_rate, out_rate);
    std::size_t at = 0, in_frames = input.size() / kChannels;
    std::vector<float> out;
    std::vector<float> period(240 * kChannels);
    for (;;) {
        std::size_t made = r.run(period.data(), 240, [&](float* dst, std::size_t max) {
            std::size_t n = std::min(max, in_frames - at);
            std::memcpy(dst, input.data() + at * kChannels, n * kChannels * sizeof(float));
            at += n;
            return n;
        });
        out.insert(out.end(), period.begin(), period.begin() + static_cast<std::ptrdiff_t>(made * kChannels));
        if (made < 240) break;
    }
    return out;
}

// The ratio of a tone's power to that of everything else in `out` (the tone `freq` at `rate` it should be), in dB, left
// channel, away from the ends where the input starts and stops.
double snr_db(const std::vector<float>& out, double freq, int rate, double amplitude) {
    double signal = 0, noise = 0;
    std::size_t frames = out.size() / kChannels;
    for (std::size_t n = 500; n + 500 < frames; ++n) {
        double want = amplitude * std::sin(2 * kPi * freq * static_cast<double>(n) / rate);
        double got = out[n * 2];
        signal += want * want;
        noise += (got - want) * (got - want);
    }
    return 10 * std::log10(signal / std::max(noise, 1e-30));
}

// The level of `out` against `amplitude`, in dB, away from the ends.
double level_db(const std::vector<float>& out, double amplitude) {
    double power = 0;
    std::size_t frames = out.size() / kChannels, n0 = 500, count = 0;
    for (std::size_t n = n0; n + 500 < frames; ++n, ++count) power += static_cast<double>(out[n * 2]) * out[n * 2];
    double rms = std::sqrt(power / std::max<std::size_t>(count, 1));
    return 20 * std::log10(std::max(rms, 1e-30) / (amplitude / std::sqrt(2.0)));
}

// An output for the tests: keeps what the mixer writes, a period every millisecond. Made shut, it holds the mixer at
// its first write until the test opens it: what the test sets up meanwhile starts in one and the same period.
class Capture : public Output {
public:
    Capture(int rate, bool open) : rate_(rate), open_(open) {}
    const char* name() const override { return "capture"; }
    int rate() const override { return rate_; }
    double buffer_ms() const override { return 1000; }
    bool write(const float* data, std::size_t frames) override {
        std::unique_lock<std::mutex> l(lock_);
        frames_.insert(frames_.end(), data, data + frames * kChannels);
        opened_.wait(l, [this] { return open_; });
        l.unlock();
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
        return true;
    }
    void open() {
        {
            std::lock_guard<std::mutex> l(lock_);
            open_ = true;
        }
        opened_.notify_all();
    }
    std::vector<float> taken() {
        std::lock_guard<std::mutex> l(lock_);
        return frames_;
    }

private:
    int rate_;
    std::mutex lock_;
    std::condition_variable opened_;
    bool open_;
    std::vector<float> frames_;
};

}  // namespace

int main() {
    char what[200];

    // Tones well inside the band, through each change of rate the game's streams need: FMOD at 24000 Hz and OpenAL at
    // 44100 Hz to the output's 48000 Hz, and a 48000 Hz stream to a 44100 Hz sound card.
    struct Case {
        int in, out;
        double freq;
    } cases[] = {{24000, 48000, 1000}, {24000, 48000, 9000}, {44100, 48000, 1000}, {44100, 48000, 17000},
                 {48000, 44100, 1000}, {48000, 44100, 17000}, {22050, 48000, 8000}};
    for (const Case& k : cases) {
        std::vector<float> out = resample(tone(k.freq, k.in, 1.0, 0.5), k.in, k.out);
        double snr = snr_db(out, k.freq, k.out, 0.5);
        std::snprintf(what, sizeof what, "%d Hz to %d Hz, a %.0f Hz tone: %.1f dB above the rest (want 80)", k.in, k.out, k.freq, snr);
        check(snr >= 80, what);
        // As long as the input says: a second in, a second out.
        std::size_t frames = out.size() / kChannels;
        std::snprintf(what, sizeof what, "%d Hz to %d Hz: %zu frames from a second (want %d, less the filter's reach)", k.in, k.out, frames, k.out);
        check(frames <= static_cast<std::size_t>(k.out) && frames + 100 >= static_cast<std::size_t>(k.out), what);
    }
    // Above the output's band: a 23000 Hz tone at 48000 Hz has no place at 44100 Hz, and must not fold back to 21100 Hz.
    {
        std::vector<float> out = resample(tone(23000, 48000, 1.0, 0.5), 48000, 44100);
        double level = level_db(out, 0.5);
        std::snprintf(what, sizeof what, "48000 Hz to 44100 Hz, a 23000 Hz tone: %.1f dB (want -80 or less)", level);
        check(level <= -80, what);
    }
    // The same rate in and out: the very samples.
    {
        std::vector<float> in = tone(440, 48000, 0.1, 0.5);
        std::vector<float> out = resample(in, 48000, 48000);
        check(out == in, "48000 Hz to 48000 Hz: the input as it is");
    }

    // A stream's formats: one channel is both, 8-bit is unsigned, 16-bit and float as they are. Streams of no mixer,
    // which the test mixes itself.
    {
        Stream s16(48000, 1, Encoding::S16, 1000, "s16", 48000), u8(48000, 2, Encoding::U8, 1000, "u8", 48000),
            f32(48000, 2, Encoding::F32, 1000, "f32", 48000);
        const std::int16_t mono[2] = {16384, -32768};
        const std::uint8_t bytes[4] = {192, 64, 128, 255};
        const float floats[4] = {0.25f, -0.5f, 0.0f, 1.0f};
        check(s16.write(mono, 2) == 2 && u8.write(bytes, 2) == 2 && f32.write(floats, 2) == 2, "writes of each format take every frame");
        std::vector<float> out(2 * kChannels, 0.0f);
        s16.play();
        s16.mix_into(out.data(), 2);
        check(out[0] == 0.5f && out[1] == 0.5f && out[2] == -1.0f && out[3] == -1.0f, "16-bit mono: each sample on both channels");
        std::fill(out.begin(), out.end(), 0.0f);
        u8.play();
        u8.mix_into(out.data(), 2);
        check(out[0] == 0.5f && out[1] == -0.5f && out[2] == 0.0f && out[3] == 127.0f / 128.0f, "8-bit stereo: 128 is silence");
        std::fill(out.begin(), out.end(), 0.0f);
        f32.play();
        f32.volume(0.5f, 1.0f);
        f32.mix_into(out.data(), 2);
        check(out[0] == 0.125f && out[1] == -0.5f && out[2] == 0.0f && out[3] == 1.0f, "float stereo, with each channel's gain");
    }

    // A write waits while the buffer is full, and goes on as the mixer takes frames; a stop lets it go.
    {
        Mixer mixer(std::make_unique<Capture>(48000, true));
        auto s = mixer.open(48000, 2, Encoding::F32, 100, "blocking");
        std::vector<float> data(300 * kChannels, 0.25f);
        std::atomic<std::size_t> taken{0};
        std::thread writer([&] { taken = s->write(data.data(), 300); });
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        std::snprintf(what, sizeof what, "a write of 300 frames into a buffer of 100 waits: %zu frames in", static_cast<std::size_t>(s->written()));
        check(taken.load() == 0 && s->written() == 100, what);
        // Playing: the mixer takes a period at a time, and the rest goes in.
        s->play();
        writer.join();
        check(taken.load() == 300, "once the stream plays, the write takes all 300");
        // A stop lets a waiting write go with what it got in.
        auto t = mixer.open(48000, 2, Encoding::F32, 100, "stopped");
        std::thread second([&] { taken = t->write(data.data(), 300); });
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        t->stop();
        second.join();
        std::snprintf(what, sizeof what, "a stop lets a waiting write go: %zu frames taken (want 100)", taken.load());
        check(taken.load() == 100, what);
        mixer.close(s);
        mixer.close(t);
    }

    // Underruns: a playing stream that had frames and runs out counts the period and the frames it was short; one
    // that never had any does not. A stream's start waits one period for a period's worth (as Android's mixer waits for
    // a track's first buffer), and what its first period lacks is silence before its first frames: a first write
    // shorter than a period is a later start, not a gap.
    {
        Stream fed(48000, 2, Encoding::F32, 1000, "fed", 48000), empty(48000, 2, Encoding::F32, 1000, "never fed", 48000);
        std::vector<float> data(100 * kChannels, 0.25f);
        fed.write(data.data(), 100);
        std::vector<float> out(240 * kChannels, 0.0f);
        fed.play();
        empty.play();
        fed.mix_into(out.data(), 240);
        check(fed.underruns() == 0 && fed.played() == 0, "a start with less than a period waits a period, no underrun");
        fed.mix_into(out.data(), 240);
        check(fed.underruns() == 0 && fed.played() == 100 && out[0] == 0.0f && out[139 * kChannels] == 0.0f && out[140 * kChannels] == 0.25f &&
                  out[239 * kChannels] == 0.25f,
              "the start's period: 140 frames of silence, then the 100 written, to the period's end");
        fed.mix_into(out.data(), 240);
        empty.mix_into(out.data(), 240);
        std::snprintf(what, sizeof what, "then a period with nothing: %llu underrun, %llu frames short", static_cast<unsigned long long>(fed.underruns()),
                      static_cast<unsigned long long>(fed.short_frames()));
        check(fed.underruns() == 1 && fed.short_frames() == 240 && fed.played() == 100, what);
        check(empty.underruns() == 0, "a stream nothing was written to is not short");
        // The game's second write coming while the start waited: the whole period from it, no gap at all.
        Stream later(48000, 2, Encoding::F32, 1000, "later", 48000);
        later.write(data.data(), 100);
        later.play();
        later.mix_into(out.data(), 240);
        std::vector<float> more(300 * kChannels, 0.25f);
        later.write(more.data(), 300);
        later.mix_into(out.data(), 240);
        std::snprintf(what, sizeof what, "a first write shorter than the period, the next one before it is needed: %llu underruns, %llu played",
                      static_cast<unsigned long long>(later.underruns()), static_cast<unsigned long long>(later.played()));
        check(later.underruns() == 0 && later.played() == 240, what);
        // A stream at a rate of its own (22050 Hz into 192 kHz, as the game's AudioTrack on a 192 kHz device with 20 ms
        // periods): its start waits for 20 ms of its own frames, then plays without a gap.
        Stream song(22050, 2, Encoding::F32, 4096, "song", 192000);
        std::vector<float> song_data(400 * kChannels, 0.25f);
        song.write(song_data.data(), 400);
        song.play();
        std::vector<float> period(3840 * kChannels, 0.0f);
        song.mix_into(period.data(), 3840);
        check(song.played() == 0 && song.underruns() == 0, "22050 Hz into 20 ms periods at 192 kHz: 400 frames wait for the 441 a period takes");
        song.write(song_data.data(), 400);
        song.mix_into(period.data(), 3840);
        std::snprintf(what, sizeof what, "then a whole period from the next write: %llu underruns, %llu played", static_cast<unsigned long long>(song.underruns()),
                      static_cast<unsigned long long>(song.played()));
        check(song.underruns() == 0 && song.played() > 400, what);
        // The game's AudioTrack at 22050 Hz with the smallest buffer it is given (20 ms, 441 frames: getMinBufferSize)
        // on a 192 kHz device alone with 20 ms periods, the game filling the buffer again as soon as there is room: the
        // buffer can never hold a period's worth with the filter's reach beside it. The stream starts the filter's
        // reach into its first period, with silence before it, and no period after it is short.
        Stream track(22050, 2, Encoding::F32, 441, "track", 192000);
        std::vector<float> fill(441 * kChannels, 0.25f);
        track.write(fill.data(), 441);
        track.play();
        std::vector<float> first(3840 * kChannels, 0.0f);
        track.mix_into(first.data(), 3840);
        std::size_t silent = 0;
        while (silent < 3840 && first[silent * kChannels] == 0.0f) ++silent;
        bool ends_in_sound = std::abs(first[3839 * kChannels] - 0.25f) < 1e-3f;
        bool gapless = track.underruns() == 0;
        for (int p = 0; p < 50; ++p) {
            // What the mix took, written again (the game's write waits for room, then fills it).
            const std::size_t room = 441 - static_cast<std::size_t>(track.written() - track.played());
            track.write(fill.data(), room);
            std::vector<float> next(3840 * kChannels, 0.0f);
            track.mix_into(next.data(), 3840);
            for (std::size_t k = 0; k < 3840; ++k) gapless = gapless && std::abs(next[k * kChannels] - 0.25f) < 1e-3f;
        }
        std::snprintf(what, sizeof what,
                      "a 22050 Hz track with a 441-frame buffer into 20 ms periods at 192 kHz: %zu frames of silence first (want 300 to 330), "
                      "%llu underruns in 51 periods, every frame after the start sound",
                      silent, static_cast<unsigned long long>(track.underruns()));
        check(silent >= 300 && silent <= 330 && ends_in_sound && gapless && track.underruns() == 0, what);
        // A sound shorter than a period, and nothing after it: it waits one period, then plays (short, as it is).
        Stream click(48000, 2, Encoding::F32, 1000, "click", 48000);
        click.write(data.data(), 100);
        click.play();
        click.mix_into(out.data(), 240);
        click.mix_into(out.data(), 240);
        check(click.played() == 100, "a sound shorter than a period still plays, one period later");
        // After a stop the next start waits again.
        click.stop();
        click.write(data.data(), 100);
        click.play();
        click.mix_into(out.data(), 240);
        check(click.played() == 100, "after a stop, the next start waits a period again");
    }

    // The mix: two streams add up, and a sum beyond full scale is held at it.
    {
        // Shut until both streams play, so that they start in the same period.
        auto capture = std::make_unique<Capture>(48000, false);
        Capture* cap = capture.get();
        Mixer mixer(std::move(capture));
        auto a = mixer.open(48000, 2, Encoding::F32, 4800, "a");
        auto b = mixer.open(48000, 2, Encoding::F32, 4800, "b");
        std::vector<float> quarter(2400 * kChannels, 0.25f), loud(2400 * kChannels, 0.9f);
        a->write(quarter.data(), 2400);
        b->write(quarter.data(), 2400);
        b->write(loud.data(), 2400);
        a->write(loud.data(), 2400);
        a->play();
        b->play();
        cap->open();
        // Until both have been mixed whole.
        for (int k = 0; k < 400 && (a->played() < 4800 || b->played() < 4800); ++k) std::this_thread::sleep_for(std::chrono::milliseconds(5));
        std::vector<float> got = cap->taken();
        // Somewhere in the first half both quarters, in the second both loud ones.
        std::size_t halves = 0, clipped = 0;
        for (std::size_t n = 0; n < got.size(); ++n) {
            if (got[n] == 0.5f) ++halves;
            if (got[n] == 1.0f) ++clipped;
        }
        std::snprintf(what, sizeof what, "two streams mixed: %zu samples at 0.25 + 0.25, %zu at 0.9 + 0.9 held at 1 (want 4800 each)", halves, clipped);
        check(halves == 4800 && clipped == 4800, what);
        mixer.close(a);
        mixer.close(b);
    }

    // The null output keeps real time: a second of periods in a second, give or take its 20 ms buffer and a period.
    {
        Mixer mixer(open_null(48000));
        auto s = mixer.open(48000, 2, Encoding::F32, 96000, "timed");
        std::vector<float> data(96000 * kChannels, 0.0f);
        s->write(data.data(), 96000);
        auto t0 = std::chrono::steady_clock::now();
        s->play();
        std::this_thread::sleep_for(std::chrono::milliseconds(1000));
        double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - t0).count();
        double mixed_s = static_cast<double>(s->played()) / 48000;
        std::snprintf(what, sizeof what, "the null output: %.3f s of sound in %.3f s (want the same, give or take 40 ms)", mixed_s, seconds);
        check(std::abs(mixed_s - seconds) < 0.04, what);
        mixer.close(s);
    }

    // The sound panel's controls while the mix runs (set_levels): the master at once, the effects' share on Unity's own
    // stream (FMOD) and not on the game's AudioTrack (its OpenAL's music and effects are shared out inside it).
    {
        auto capture = std::make_unique<Capture>(48000, false);
        Capture* cap = capture.get();
        Mixer mixer(std::move(capture));
        auto fmod = mixer.open(48000, 2, Encoding::F32, 9600, "FMOD");
        auto track = mixer.open(48000, 2, Encoding::F32, 9600, "AudioTrack 1");
        std::vector<float> half(4800 * kChannels, 0.5f), none(4800 * kChannels, 0.0f);
        // Unity's stream at 0.5 in the first 4800 frames, the game's track at 0.5 in the next 4800.
        fmod->write(half.data(), 4800);
        fmod->write(none.data(), 4800);
        track->write(none.data(), 4800);
        track->write(half.data(), 4800);
        Levels l;
        l.master = 50;
        l.effects = 50;
        l.music = 0;
        mixer.set_levels(l);
        fmod->play();
        track->play();
        cap->open();
        for (int k = 0; k < 400 && (fmod->played() < 9600 || track->played() < 9600); ++k) std::this_thread::sleep_for(std::chrono::milliseconds(5));
        std::vector<float> got = cap->taken();
        // Master 50 % is 0.25 of amplitude; effects 50 % another 0.25 on Unity's stream: 0.5 x 0.25 x 0.25; the track
        // 0.5 x 0.25 (its music share is OpenAL's own, not the mixer's).
        std::size_t unity = 0, game = 0;
        for (const float v : got) {
            if (std::fabs(v - 0.5f * 0.25f * 0.25f) < 1e-6f) ++unity;
            if (std::fabs(v - 0.5f * 0.25f) < 1e-6f) ++game;
        }
        std::snprintf(what, sizeof what, "master 50 %% and effects 50 %% at run time: %zu samples of Unity's stream at 1/32, %zu of the game's track at 1/8 (want 9600 each)",
                      unity, game);
        check(unity == 9600 && game == 9600, what);
        mixer.close(fmod);
        mixer.close(track);
    }

    // The equaliser (sound_mix.h): flat passes the mix as it is; each preset lifts its band against the others by its
    // dB; a raised band takes its headroom first, so a full scale tone there never clips; custom bands as chosen.
    {
        const int rate = 48000;
        auto through = [&](EqBands bands, double freq, double amplitude) {
            Equalizer eq;
            eq.set(rate, bands);
            std::vector<float> v = tone(freq, rate, 1.0, amplitude);
            eq.run(v.data(), v.size() / kChannels);
            // The last half second, settled: its level against the tone's in.
            std::vector<float> tail(v.begin() + static_cast<std::ptrdiff_t>(v.size() / 2), v.end());
            float most = 0;
            for (const float x : tail) most = std::max(most, std::fabs(x));
            return std::make_pair(level_db(tail, amplitude), most);
        };
        const auto flat = through({0, 0, 0}, 1000, 0.5);
        check(std::fabs(flat.first) < 0.01, "flat leaves a 1 kHz tone as it is");
        Equalizer eq;
        eq.set(rate, {0, 0, 0});
        check(eq.flat(), "flat is no filter at all");
        const auto bass_low = through(preset_bands(EqPreset::kBass, {}), 50, 0.5), bass_high = through(preset_bands(EqPreset::kBass, {}), 10000, 0.5);
        std::snprintf(what, sizeof what, "bass: 50 Hz %.2f dB against 10 kHz %.2f dB (want 6 dB more, within 0.7)", bass_low.first, bass_high.first);
        check(std::fabs((bass_low.first - bass_high.first) - 6) < 0.7, what);
        const auto treble_low = through(preset_bands(EqPreset::kTreble, {}), 50, 0.5), treble_high = through(preset_bands(EqPreset::kTreble, {}), 14000, 0.5);
        std::snprintf(what, sizeof what, "treble: 14 kHz %.2f dB against 50 Hz %.2f dB (want 6 dB more, within 0.7)", treble_high.first, treble_low.first);
        check(std::fabs((treble_high.first - treble_low.first) - 6) < 0.7, what);
        const auto vocal_mid = through(preset_bands(EqPreset::kVocal, {}), 1000, 0.5), vocal_low = through(preset_bands(EqPreset::kVocal, {}), 50, 0.5);
        std::snprintf(what, sizeof what, "vocal: 1 kHz %.2f dB against 50 Hz %.2f dB (want 6 dB more, within 0.7)", vocal_mid.first, vocal_low.first);
        check(std::fabs((vocal_mid.first - vocal_low.first) - 6) < 0.7, what);
        // Full scale at the raised band: its headroom keeps it within full scale.
        const auto loud = through({12, 0, 0}, 50, 1.0);
        std::snprintf(what, sizeof what, "+12 dB at the low end with a full scale 50 Hz tone: peak %.3f (want 1.05 at most)", static_cast<double>(loud.second));
        check(loud.second <= 1.05f, what);
        const auto cut = through({0, -12, 0}, 1000, 0.5);
        std::snprintf(what, sizeof what, "custom -12 dB in the middle: a 1 kHz tone %.2f dB (want -12, within 1)", cut.first);
        check(std::fabs(cut.first + 12) < 1.0, what);
        // What it costs: a 5 ms period of 48 kHz stereo, a thousand times.
        Equalizer timed;
        timed.set(rate, {6, -3, 4});
        std::vector<float> period = tone(440, rate, 0.005, 0.5);
        // Each period's output summed, so that none of the work can be left out.
        volatile float sink = 0;
        const auto t0 = std::chrono::steady_clock::now();
        for (int i = 0; i < 1000; ++i) {
            timed.run(period.data(), period.size() / kChannels);
            sink = sink + period[static_cast<std::size_t>(i) % period.size()];
        }
        const double us = std::chrono::duration<double, std::micro>(std::chrono::steady_clock::now() - t0).count() / 1000;
        std::snprintf(what, sizeof what, "the equaliser costs %.2f us for a 5 ms period (want under 100 us: 2 %% of the period)", us);
        check(us < 100 && std::isfinite(static_cast<float>(sink)), what);
    }

    std::printf("%d checks\n", g_checks);
    if (g_failures == 0) std::printf("ALL CHECKS PASSED\n");
    return g_failures == 0 ? 0 : 1;
}
