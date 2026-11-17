// The mixer, its resampler and streams, and the null output (mixer.h says what each is for).
#include "mixer.h"

#include "jvm.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <string>
#include <sys/prctl.h>
#include <vector>

namespace player::audio {

namespace {

// The filter's table: phases between two input frames.
constexpr std::size_t kPhases = 256;
// Zero crossings of the filter each side of its centre: its length, and so how steep its cutoff is.
constexpr double kZeros = 32;
// The cutoff, as a part of the lower rate's Nyquist frequency: the filter falls from full to nothing around it, and is
// well down by the Nyquist frequency itself.
constexpr double kRolloff = 0.91;
// The Kaiser window's beta: about 90 dB down outside the band.
constexpr double kBeta = 9.0;
constexpr double kPi = 3.14159265358979323846;

// The modified Bessel function I0, which the Kaiser window is made of: its series converges fast for these arguments.
double bessel_i0(double x) {
    double sum = 1, term = 1;
    for (int k = 1; k < 64; ++k) {
        term *= (x / (2 * k)) * (x / (2 * k));
        sum += term;
        if (term < sum * 1e-17) break;
    }
    return sum;
}

}  // namespace

Resampler::Resampler(int in_rate, int out_rate)
    : in_rate_(in_rate > 0 ? in_rate : out_rate), out_rate_(out_rate), copy_(in_rate_ == out_rate_),
      step_(static_cast<double>(in_rate_) / out_rate_) {
    if (copy_) return;
    // The cutoff, relative to the input's Nyquist frequency: below the output's when the output is the lower rate.
    double cutoff = std::min(1.0, static_cast<double>(out_rate_) / in_rate_) * kRolloff;
    // The filter's half-length in input frames: its zero crossings are 1/cutoff frames apart.
    half_ = static_cast<std::size_t>(std::ceil(kZeros / cutoff));
    std::size_t taps = 2 * half_;
    table_.resize((kPhases + 1) * taps);
    double i0_beta = bessel_i0(kBeta);
    for (std::size_t p = 0; p <= kPhases; ++p) {
        // Row p: the output frame `p / kPhases` of the way from one input frame to the next.
        double frac = static_cast<double>(p) / kPhases;
        float* row = &table_[p * taps];
        double sum = 0;
        for (std::size_t k = 0; k < taps; ++k) {
            // Tap k is input frame (k - half_ + 1) from the one before the output frame: d frames from it.
            double d = static_cast<double>(k) - static_cast<double>(half_) + 1 - frac;
            double x = cutoff * d;
            double sinc = x == 0 ? 1 : std::sin(kPi * x) / (kPi * x);
            double t = d / static_cast<double>(half_);
            double window = std::abs(t) < 1 ? bessel_i0(kBeta * std::sqrt(1 - t * t)) / i0_beta : 0;
            double h = cutoff * sinc * window;
            row[k] = static_cast<float>(h);
            sum += h;
        }
        // Each row adds up to one: a steady input comes out at the same level whatever the phase.
        for (std::size_t k = 0; k < taps; ++k) row[k] = static_cast<float>(row[k] / sum);
    }
    reset();
}

void Resampler::reset() {
    if (copy_) return;
    // Silence before the first input frame, as far back as the filter reaches; the first output frame is the first
    // input frame's instant.
    in_.assign((half_ - 1) * kChannels, 0.0f);
    pos_ = static_cast<double>(half_ - 1);
}

void Resampler::make(float* out) const {
    std::size_t i = static_cast<std::size_t>(pos_);
    // Where the output frame falls between input frames i and i + 1, as a row of the table and the way to the next.
    double ph = (pos_ - static_cast<double>(i)) * kPhases;
    std::size_t p = std::min(static_cast<std::size_t>(ph), kPhases - 1);
    float w = static_cast<float>(ph - static_cast<double>(p));
    std::size_t taps = 2 * half_;
    const float* a = &table_[p * taps];
    const float* b = a + taps;
    // The first input frame the filter reaches.
    const float* x = &in_[(i + 1 - half_) * kChannels];
    float left = 0, right = 0;
    for (std::size_t k = 0; k < taps; ++k) {
        float c = a[k] + (b[k] - a[k]) * w;
        left += x[2 * k] * c;
        right += x[2 * k + 1] * c;
    }
    out[0] = left;
    out[1] = right;
}

void Resampler::trim() {
    // The first frame the next output frame's filter reaches; those before it are done with.
    std::size_t first = static_cast<std::size_t>(pos_) + 1 - half_;
    if (first == 0) return;
    in_.erase(in_.begin(), in_.begin() + static_cast<std::ptrdiff_t>(first * kChannels));
    pos_ -= static_cast<double>(first);
}

// ---------------------------------------------------------------------------------------------------------------------

Stream::Stream(int rate, int channels, Encoding encoding, std::size_t capacity, std::string name, int out_rate)
    : rate_(rate > 0 ? rate : out_rate), channels_(channels > 0 ? channels : 1), out_rate_(out_rate), encoding_(encoding), name_(std::move(name)),
      ring_(std::max<std::size_t>(capacity, 1) * kChannels), capacity_(std::max<std::size_t>(capacity, 1)),
      resampler_(rate_, out_rate) {}

std::size_t Stream::write(const void* data, std::size_t frames) {
    const auto* in = static_cast<const std::uint8_t*>(data);
    const std::size_t sample_bytes = encoding_ == Encoding::U8 ? 1 : encoding_ == Encoding::S16 ? 2 : 4;
    const std::size_t frame_bytes = sample_bytes * static_cast<std::size_t>(channels_);
    std::unique_lock<std::mutex> l(lock_);
    const std::uint64_t epoch = epoch_;
    std::size_t done = 0;
    while (done < frames) {
        // Full: wait for the mixer to take some, as AudioTrack.write waits; a stop or flush lets the write go.
        room_.wait(l, [&] { return size_ < capacity_ || epoch_ != epoch; });
        if (epoch_ != epoch) break;
        std::size_t n = std::min(frames - done, capacity_ - size_);
        for (std::size_t k = 0; k < n; ++k) {
            const std::uint8_t* f = in + (done + k) * frame_bytes;
            float s[2];
            // The first two channels; one channel is both.
            for (int c = 0; c < 2; ++c) {
                const std::uint8_t* v = f + static_cast<std::size_t>(std::min(c, channels_ - 1)) * sample_bytes;
                if (encoding_ == Encoding::U8) {
                    s[c] = (static_cast<float>(*v) - 128.0f) / 128.0f;
                } else if (encoding_ == Encoding::S16) {
                    std::int16_t x;
                    std::memcpy(&x, v, 2);
                    s[c] = static_cast<float>(x) / 32768.0f;
                } else {
                    std::memcpy(&s[c], v, 4);
                }
            }
            std::size_t at = ((head_ + size_ + k) % capacity_) * kChannels;
            ring_[at] = s[0];
            ring_[at + 1] = s[1];
        }
        size_ += n;
        done += n;
        fed_ = true;
        written_ += n;
    }
    return done;
}

std::size_t Stream::take(float* dst, std::size_t max) {
    std::size_t n = std::min(max, size_);
    for (std::size_t k = 0; k < n; ++k) {
        std::size_t at = ((head_ + k) % capacity_) * kChannels;
        dst[k * kChannels] = ring_[at];
        dst[k * kChannels + 1] = ring_[at + 1];
    }
    head_ = (head_ + n) % capacity_;
    size_ -= n;
    played_ += n;
    return n;
}

void Stream::play() {
    std::lock_guard<std::mutex> l(lock_);
    state_ = kPlaying;
}

void Stream::pause() {
    std::lock_guard<std::mutex> l(lock_);
    if (state_ == kPlaying) state_ = kPaused;
}

void Stream::stop() {
    {
        std::lock_guard<std::mutex> l(lock_);
        state_ = kStopped;
        // What was not played goes; the next play starts from what is written then, with nothing of the old.
        head_ = size_ = 0;
        fed_ = false;
        primed_ = false;
        waits_ = 0;
        ++epoch_;
        resampler_.reset();
    }
    room_.notify_all();
}

void Stream::flush() {
    {
        std::lock_guard<std::mutex> l(lock_);
        // As AudioTrack.flush: only a stream that is not playing drops its buffer.
        if (state_ == kPlaying) return;
        head_ = size_ = 0;
        fed_ = false;
        primed_ = false;
        waits_ = 0;
        ++epoch_;
        resampler_.reset();
    }
    room_.notify_all();
}

void Stream::volume(float left, float right) {
    std::lock_guard<std::mutex> l(lock_);
    gain_[0] = std::clamp(left, 0.0f, 1.0f);
    gain_[1] = std::clamp(right, 0.0f, 1.0f);
}

void Stream::mix_into(float* out, std::size_t frames) {
    std::size_t made;
    float gain[kChannels];
    {
        std::lock_guard<std::mutex> l(lock_);
        if (state_ != kPlaying) return;
        // The stream's start: a period's worth of its own frames there first, and the frames the resampler's filter
        // reaches past them, while more can come (the game's buffer not full yet), one period at most; nothing written
        // yet is no start at all.
        bool start = false;
        if (!primed_) {
            if (!fed_) return;
            const std::size_t need = (frames * static_cast<std::size_t>(rate_) + static_cast<std::size_t>(out_rate_) - 1) / static_cast<std::size_t>(out_rate_);
            const std::size_t reach = rate_ == out_rate_ ? 0 : resampler_.reach() + 1;
            if (size_ < need + reach && size_ < capacity_ && ++waits_ < 2) return;
            primed_ = true;
            start = true;
        }
        scratch_.resize(frames * kChannels);
        made = resampler_.run(scratch_.data(), frames, [this](float* dst, std::size_t max) { return take(dst, max); });
        if (made < frames && start) {
            // Short at the start (a game's buffer of one period holds no more than a period's worth, without the
            // filter's reach): the frames there go at the period's end, silence before them, and the next period goes on
            // from them. The stream begins that much later, with no gap after its first frames.
            std::copy_backward(scratch_.begin(), scratch_.begin() + static_cast<std::ptrdiff_t>(made * kChannels),
                               scratch_.begin() + static_cast<std::ptrdiff_t>(frames * kChannels));
            std::fill(scratch_.begin(), scratch_.begin() + static_cast<std::ptrdiff_t>((frames - made) * kChannels), 0.0f);
            made = frames;
        } else if (made < frames && fed_) {
            // Short after the game had begun writing: it fell behind, and the gap is silence.
            ++underruns_;
            short_frames_ += frames - made;
        }
        gain[0] = gain_[0];
        gain[1] = gain_[1];
    }
    // Room for the writer, which may be waiting.
    room_.notify_all();
    // The player's share of it on top (the effects' for Unity's own sound).
    const float share = share_.load(std::memory_order_relaxed);
    gain[0] *= share;
    gain[1] *= share;
    // Into the mix, the loudest of it kept for the trace.
    float loudest = 0.0f;
    for (std::size_t k = 0; k < made; ++k) {
        const float left = scratch_[k * kChannels] * gain[0], right = scratch_[k * kChannels + 1] * gain[1];
        out[k * kChannels] += left;
        out[k * kChannels + 1] += right;
        loudest = std::max({loudest, std::fabs(left), std::fabs(right)});
    }
    if (loudest > peak_.load(std::memory_order_relaxed)) peak_.store(loudest, std::memory_order_relaxed);
}

// ---------------------------------------------------------------------------------------------------------------------

Options& options() {
    static Options o;
    return o;
}

namespace {
// The mix's other taker (set_mix_tap), read once each period.
std::atomic<MixTap> g_tap{nullptr};
}  // namespace

void set_mix_tap(MixTap tap) { g_tap.store(tap, std::memory_order_release); }

namespace {
// The player's sound controls now (set_levels), from the settings at the start.
std::mutex g_levels_lock;
bool g_levels_set = false;
Levels g_levels;
}  // namespace

Levels levels() {
    std::lock_guard<std::mutex> l(g_levels_lock);
    if (!g_levels_set) {
        // The settings' own until the panel changes them.
        Levels from = options().levels;
        from.master = options().volume;
        return from;
    }
    return g_levels;
}

void set_levels(const Levels& l) {
    {
        std::lock_guard<std::mutex> g(g_levels_lock);
        g_levels = l;
        g_levels_set = true;
    }
    options().volume = l.master;
    if (Mixer* m = Mixer::started()) m->set_levels(l);
}

Mixer::Mixer(std::unique_ptr<Output> output)
    : output_(std::move(output)), rate_(output_->rate()),
      period_(output_->period() ? output_->period() : static_cast<std::size_t>(rate_) * kPeriodMs / 1000),
      // The square of the share: amplitude falls faster than the slider, as loudness is heard.
      gain_(percent_gain(options().volume)) {
    // The equaliser as the settings had it (set_levels before the mixer started keeps its own in levels()).
    const Levels start = levels();
    const EqBands bands = start.bands();
    eq_.set(rate_, bands);
    // The controls the game's sound starts with, all of them: the volume here, the music's and the effects' shares
    // where the game's OpenAL and Unity's own sound take them (soundmix.cpp, Mixer::open), the equaliser here.
    jvm::log("player: sound out through %s at %d Hz, %.2f ms a period, %.1f ms buffered, volume %d%%, music %d%%, effects %d%%, equaliser %s "
             "(%+d %+d %+d dB)",
             output_->name(), rate_, 1000.0 * static_cast<double>(period_) / rate_, output_->buffer_ms(), std::clamp(options().volume, 0, 100),
             std::clamp(start.music, 0, 100), std::clamp(start.effects, 0, 100), eq_name(start.eq), bands.low, bands.mid, bands.high);
    thread_ = std::thread([this] { run(); });
    reporter_ = std::thread([this] { look_back(); });
}

void Mixer::set_levels(const Levels& l) {
    gain_.store(percent_gain(l.master), std::memory_order_relaxed);
    {
        std::lock_guard<std::mutex> g(eq_lock_);
        eq_wanted_ = l.bands();
    }
    eq_changed_.store(true, std::memory_order_release);
    // Unity's own sound (menus' and buttons' sounds) is the effects'.
    std::lock_guard<std::mutex> g(lock_);
    for (const auto& s : streams_) {
        if (s->name() == "FMOD") s->share(percent_gain(l.effects));
    }
}

Mixer::~Mixer() {
    {
        std::lock_guard<std::mutex> l(look_lock_);
        running_ = false;
    }
    looked_.notify_all();
    if (thread_.joinable()) thread_.join();
    if (reporter_.joinable()) reporter_.join();
}

namespace {
// The player's mixer, once it is made.
std::atomic<Mixer*> g_mixer{nullptr};
}  // namespace

Mixer* Mixer::started() { return g_mixer.load(); }

Mixer& Mixer::get() {
    static Mixer* mixer = [] {
        // The rate a desktop's sound runs at.
        const int rate = 48000;
        const char* want = std::getenv("PLAYER_AUDIO");
        std::string name = want ? want : "";
        std::unique_ptr<Output> out;
#ifdef _WIN32
        const char* own = "wasapi";
        if (name.empty() || name == own) out = open_wasapi(rate);
#else
        const char* own = "pulse";
        if (name.empty() || name == own) out = open_pulse(rate);
#endif
        if (!out && name == own) jvm::log("player: PLAYER_AUDIO=%s, and it cannot start: no sound", own);
        if (!out && name.empty()) jvm::log("player: no sound output found: no sound");
        if (!out && !name.empty() && name != own && name != "null") jvm::log("player: PLAYER_AUDIO=%s: no such output here: no sound", name.c_str());
        if (!out) out = open_null(rate);
        // Never destroyed: the player leaves with _exit while the game's threads still write.
        auto* m = new Mixer(std::move(out));
        g_mixer = m;
        return m;
    }();
    return *mixer;
}

std::shared_ptr<Stream> Mixer::open(int rate, int channels, Encoding encoding, std::size_t capacity, const std::string& name) {
    auto s = std::make_shared<Stream>(rate, channels, encoding, capacity, name, rate_);
    // Unity's own sound is the effects' (set_levels).
    if (name == "FMOD") s->share(percent_gain(levels().effects));
    std::lock_guard<std::mutex> l(lock_);
    streams_.push_back(s);
    return s;
}

void Mixer::close(const std::shared_ptr<Stream>& stream) {
    if (!stream) return;
    // A write still waiting on it goes first.
    stream->stop();
    std::lock_guard<std::mutex> l(lock_);
    auto it = std::find(streams_.begin(), streams_.end(), stream);
    if (it == streams_.end()) return;
    streams_.erase(it);
    // Kept for the report while there are few; a game that opens streams without end keeps the last ones.
    closed_.push_back(stream);
    if (closed_.size() > 32) closed_.erase(closed_.begin());
}

namespace {

// The latency of `more` added to `into`: the counts and sums, the extremes of both.
void merge(Latency& into, const Latency& more) {
    if (!more.count) return;
    into.min_ms = into.count ? std::min(into.min_ms, more.min_ms) : more.min_ms;
    into.max_ms = into.count ? std::max(into.max_ms, more.max_ms) : more.max_ms;
    into.sum_ms += more.sum_ms;
    into.count += more.count;
}

// Where the last game's sound result goes (set_result_path), "" for nowhere.
std::mutex g_result_lock;
std::string g_result_path;

}  // namespace

void set_result_path(const std::string& path) {
    std::lock_guard<std::mutex> l(g_result_lock);
    g_result_path = path;
}

void Mixer::report() {
    // The lines made under the lock, then said out of it: the mixer's thread takes the lock every period, and a log line
    // may wait on the disk longer than a device alone's buffer of 3 ms lasts.
    std::vector<std::string> lines;
    const auto say = [&lines](const char* format, auto... values) {
        char line[512];
        std::snprintf(line, sizeof line, format, values...);
        lines.emplace_back(line);
    };
    {
        std::lock_guard<std::mutex> l(lock_);
        // The output's latency since the last look, into the game's.
        const Latency stretch = output_->take_latency();
        merge(latency_, stretch);
        say("audio: %s at %d Hz: %.1f s in periods of %.2f ms, %llu late", output_->name(), rate_,
            static_cast<double>(periods_.load() * period_) / rate_, 1000.0 * static_cast<double>(period_) / rate_,
            static_cast<unsigned long long>(late_.load()));
        if (stretch.count) {
            say("audio: %s %s, the device's period %.2f ms: %.1f ms out (%.1f to %.1f) over %llu writes, %.1f ms over the game", output_->name(),
                output_->mode(), output_->period_ms(), stretch.mean_ms(), stretch.min_ms, stretch.max_ms,
                static_cast<unsigned long long>(stretch.count), latency_.mean_ms());
        }
        // Seconds, whatever each stream's rate.
        const auto line = [&say](const Stream& s, const char* state) {
            say("audio: %s at %d Hz (%s): %.1f s written, %.1f s played, %llu underruns (%.1f ms short)", s.name().c_str(), s.rate(), state,
                static_cast<double>(s.written()) / s.rate(), static_cast<double>(s.played()) / s.rate(),
                static_cast<unsigned long long>(s.underruns()), 1000.0 * static_cast<double>(s.short_frames()) / s.out_rate());
        };
        for (const auto& s : streams_) line(*s, s->playing() ? "playing" : "not playing");
        for (const auto& s : closed_) line(*s, "closed");
    }
    // The equaliser's cost, where it ran.
    const std::uint64_t ran = eq_periods_.exchange(0), ns = eq_ns_.exchange(0);
    if (ran) {
        say("audio: the equaliser took %.2f us a period (%.3f %% of the mixer's time) over %llu periods", static_cast<double>(ns) / 1e3 / static_cast<double>(ran),
            100.0 * static_cast<double>(ns) / (static_cast<double>(ran) * 1e9 * static_cast<double>(period_) / rate_), static_cast<unsigned long long>(ran));
    }
    for (const std::string& l : lines) jvm::log("%s", l.c_str());
}

void Mixer::look_back() {
    // Its name for the stats and a debugger.
    prctl(PR_SET_NAME, "mixer report");
    // With ARM32_STATS=1 the counters go to the log every five seconds, beside the runtime's own; the last game's result
    // for the PC client every five seconds whatever the stats (a game that ends without the player's own end, a crash or
    // the process ended, still leaves its sound's result).
    const char* stats = std::getenv("ARM32_STATS");
    const bool report_often = stats && std::atoi(stats) > 0;
    std::unique_lock<std::mutex> l(look_lock_);
    while (running_.load()) {
        // Five seconds, or at once when the mixer goes.
        if (looked_.wait_for(l, std::chrono::seconds(5), [this] { return !running_.load(); })) break;
        l.unlock();
        if (report_often) report();
        write_result();
        l.lock();
    }
}

std::string Mixer::result() {
    std::lock_guard<std::mutex> l(lock_);
    merge(latency_, output_->take_latency());
    // The game's own streams' short periods: its threads behind the device, which the player hears as gaps too.
    std::uint64_t game_gaps = 0;
    for (const auto& s : streams_) game_gaps += s->underruns();
    for (const auto& s : closed_) game_gaps += s->underruns();
    const std::time_t now = std::time(nullptr);
    char when[32] = "";
    // The local time by the calls that keep their own copy (this runs on the reporter's thread beside the game's).
    std::tm local{};
#ifdef _WIN32
    const bool known = localtime_s(&local, &now) == 0;
#else
    const bool known = localtime_r(&now, &local) != nullptr;
#endif
    if (known) std::strftime(when, sizeof when, "%Y-%m-%dT%H:%M:%S", &local);
    const Options& asked = options();
    char text[1024];
    std::snprintf(text, sizeof text,
                  "# The last game's sound as the player measured it: how it had the device, the device's period and buffer, the time\n"
                  "# from the mix to the device's output (its own clock's), and the gaps: the device running dry, and the game's own\n"
                  "# sound falling behind. The PC client's Sound page shows it.\n"
                  "time=%s\noutput=%s\nmode=%s\nasked=%s %s\nrate=%d\nperiod_ms=%.2f\nbuffer_ms=%.1f\nlatency_ms=%.1f\nlatency_min_ms=%.1f\n"
                  "latency_max_ms=%.1f\nlatency_measures=%llu\nseconds=%.1f\ngaps=%llu\ngame_gaps=%llu\n",
                  when, output_->name(), output_->mode(), asked.exclusive ? "exclusive" : "shared",
                  asked.buffer == 0 ? "low" : asked.buffer == 2 ? "safe" : "normal", rate_, output_->period_ms(), output_->buffer_ms(),
                  latency_.mean_ms(), latency_.min_ms, latency_.max_ms, static_cast<unsigned long long>(latency_.count),
                  static_cast<double>(periods_.load() * period_) / rate_, static_cast<unsigned long long>(late_.load()),
                  static_cast<unsigned long long>(game_gaps));
    return text;
}

void Mixer::write_result() {
    std::string path;
    {
        std::lock_guard<std::mutex> l(g_result_lock);
        path = g_result_path;
    }
    if (path.empty()) return;
    const std::string text = result();
    // The path is UTF-8 (a Windows user's folder may have any letters): as such into the file system's own.
    const auto utf8 = [](const std::string& p) { return std::filesystem::path(std::u8string(p.begin(), p.end())); };
    // A temporary file beside it, then a rename over it (which replaces it, on Windows too): the PC client reads the old
    // file or the new one, never half.
    const std::filesystem::path temp = utf8(path + ".player.tmp"), final_path = utf8(path);
    {
        std::ofstream out(temp, std::ios::binary | std::ios::trunc);
        out << text;
        out.close();
        if (!out) {
            std::error_code ignored;
            std::filesystem::remove(temp, ignored);
            return;
        }
    }
    std::error_code error;
    std::filesystem::rename(temp, final_path, error);
    if (error) std::filesystem::remove(temp, error);
}

namespace {

// A check's copy of what goes out (PLAYER_CAPTURE_AUDIO=<file>): a WAV file of 32-bit float stereo at the output's rate,
// after the volume and the equaliser, as the device gets it. Its sizes are written again each second: the player
// leaves with _exit and never closes it, and a file cut there still reads to its last whole second.
class Capture {
public:
    Capture(const char* path, int rate) : rate_(rate) {
        file_ = std::fopen(path, "wb");
        if (!file_) {
            jvm::log("player: PLAYER_CAPTURE_AUDIO=%s cannot be written: no copy of the sound", path);
            return;
        }
        header();
        jvm::log("player: a copy of the sound in %s (32-bit floats, two channels at %d Hz)", path, rate);
    }
    // The period just made, then the sizes once a second's worth more is in.
    void add(const float* frames, std::size_t n) {
        if (!file_) return;
        std::fwrite(frames, sizeof(float) * kChannels, n, file_);
        frames_ += n;
        since_ += n;
        if (since_ >= static_cast<std::size_t>(rate_)) {
            since_ = 0;
            header();
            std::fseek(file_, 0, SEEK_END);
            std::fflush(file_);
        }
    }

private:
    // The RIFF header for the frames written so far: format 3 (IEEE floats), two channels.
    void header() {
        const std::uint32_t data = static_cast<std::uint32_t>(frames_ * kChannels * sizeof(float));
        const std::uint32_t riff = 36 + data, fmt = 16, rate = static_cast<std::uint32_t>(rate_);
        const std::uint32_t bytes = rate * kChannels * sizeof(float);
        const std::uint16_t tag = 3, channels = kChannels, align = kChannels * sizeof(float), bits = 32;
        std::fseek(file_, 0, SEEK_SET);
        std::fwrite("RIFF", 1, 4, file_);
        std::fwrite(&riff, 4, 1, file_);
        std::fwrite("WAVEfmt ", 1, 8, file_);
        std::fwrite(&fmt, 4, 1, file_);
        std::fwrite(&tag, 2, 1, file_);
        std::fwrite(&channels, 2, 1, file_);
        std::fwrite(&rate, 4, 1, file_);
        std::fwrite(&bytes, 4, 1, file_);
        std::fwrite(&align, 2, 1, file_);
        std::fwrite(&bits, 2, 1, file_);
        std::fwrite("data", 1, 4, file_);
        std::fwrite(&data, 4, 1, file_);
    }
    int rate_;
    std::FILE* file_ = nullptr;
    std::size_t frames_ = 0, since_ = 0;
};

}  // namespace

void Mixer::run() {
    // Its name for the stats and a debugger (the mixer's tests run without the player's thread helpers).
    prctl(PR_SET_NAME, "mixer");
    // A check's copy of the sound, when asked for.
    std::unique_ptr<Capture> capture;
    if (const char* path = std::getenv("PLAYER_CAPTURE_AUDIO"); path && *path) capture = std::make_unique<Capture>(path, rate_);
    std::vector<float> buf(period_ * kChannels);
    using Clock = std::chrono::steady_clock;
    Clock::time_point last{};
    // The counters and the last game's result are said by a thread of their own (look_back): nothing here waits on a
    // disk.
    // The level's trace (a check's): its sums over the second so far.
    const char* trace = std::getenv("PLAYER_TRACE_AUDIO");
    const bool trace_level = trace && *trace == '1';
    double level_sum = 0;
    float level_peak = 0;
    std::size_t level_frames = 0;
    while (running_.load()) {
        std::fill(buf.begin(), buf.end(), 0.0f);
        {
            std::lock_guard<std::mutex> l(lock_);
            for (const auto& s : streams_) s->mix_into(buf.data(), period_);
        }
        // The broadcast takes the mix as the game made it, whatever the player's volume.
        if (MixTap tap = g_tap.load(std::memory_order_acquire)) tap(buf.data(), period_, rate_);
        // The equaliser as last set (the panel's change from this period on).
        if (eq_changed_.exchange(false, std::memory_order_acquire)) {
            std::lock_guard<std::mutex> g(eq_lock_);
            eq_.set(rate_, eq_wanted_);
        }
        if (!eq_.flat()) {
            const Clock::time_point a = Clock::now();
            eq_.run(buf.data(), period_);
            eq_ns_ += static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now() - a).count());
            ++eq_periods_;
        }
        // The game's volume, then a sum louder than full scale held at full scale, as a phone's mixer holds it.
        const float gain = gain_.load(std::memory_order_relaxed);
        if (gain != 1.0f) {
            for (float& v : buf) v *= gain;
        }
        for (float& v : buf) v = std::clamp(v, -1.0f, 1.0f);
        // A check's trace of the level (PLAYER_TRACE_AUDIO=1): each second's RMS and peak of what goes out, in dBFS.
        if (trace_level) {
            for (const float v : buf) {
                level_sum += static_cast<double>(v) * static_cast<double>(v);
                level_peak = std::max(level_peak, std::fabs(v));
            }
            level_frames += period_;
            if (level_frames >= static_cast<std::size_t>(rate_)) {
                const double rms = std::sqrt(level_sum / static_cast<double>(level_frames * kChannels));
                // Each stream's loudest sample in the second too: what each of them carries.
                std::string streams;
                {
                    std::lock_guard<std::mutex> l(lock_);
                    for (const auto& s : streams_) {
                        const float p = s->take_peak();
                        char part[96];
                        std::snprintf(part, sizeof part, "; %s at %d Hz %.1f", s->name().c_str(), s->rate(), p > 0 ? 20 * std::log10(static_cast<double>(p)) : -200.0);
                        streams += part;
                    }
                }
                jvm::log("audio: level %.1f dBFS, peak %.1f dBFS%s", rms > 0 ? 20 * std::log10(rms) : -200.0,
                         level_peak > 0 ? 20 * std::log10(static_cast<double>(level_peak)) : -200.0, streams.c_str());
                level_sum = 0;
                level_peak = 0;
                level_frames = 0;
            }
        }
        // The check's copy, as the device gets it.
        if (capture) capture->add(buf.data(), period_);
        // Away from the output longer than its buffer lasts: it ran dry.
        Clock::time_point now = Clock::now();
        if (last != Clock::time_point{} && now - last > std::chrono::duration<double, std::milli>(output_->buffer_ms())) ++late_;
        if (!output_->write(buf.data(), period_)) {
            jvm::log("player: %s failed: no sound from here on", output_->name());
            // Under the lock: report() reads the output from another thread.
            std::lock_guard<std::mutex> l(lock_);
            output_ = open_null(rate_);
        }
        last = Clock::now();
        ++periods_;
    }
}

// ---------------------------------------------------------------------------------------------------------------------
// The null output: no sound, the time it would take. It keeps a sound card's buffer of 20 ms ahead of the clock.

namespace {

class NullOutput : public Output {
public:
    explicit NullOutput(int rate) : rate_(rate) {}
    const char* name() const override { return "no output"; }
    int rate() const override { return rate_; }
    double buffer_ms() const override { return kBufferMs; }
    bool write(const float*, std::size_t frames) override {
        auto now = std::chrono::steady_clock::now();
        // What was written plays out from where the last write ended, or from now when that is past (the mixer was away).
        if (due_ < now) due_ = now;
        due_ += std::chrono::nanoseconds(static_cast<long long>(1e9 * static_cast<double>(frames) / rate_));
        // Full: wait until the buffer has room for the next period.
        auto room_at = due_ - std::chrono::microseconds(static_cast<long long>(kBufferMs * 1000));
        if (room_at > now) std::this_thread::sleep_until(room_at);
        return true;
    }

private:
    static constexpr double kBufferMs = 20;
    int rate_;
    std::chrono::steady_clock::time_point due_{};
};

}  // namespace

std::unique_ptr<Output> open_null(int rate) { return std::make_unique<NullOutput>(rate); }

}  // namespace player::audio
