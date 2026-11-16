// The display's refreshes, from the times DXGI wakes the refresh thread at them (window_win32.cpp's refresh_loop): where
// they fall (the grid the runtime paces by) and the interval they really keep. Apart from any window, so that a check
// (settingstest.cpp) can feed it the wakes of a display whose rate the system gave in whole hertz only, of one whose wakes
// come at a fraction of its rate (Windows 11's dynamic refresh rate keeps a program at 60 Hz on a 120, 180 or 240 Hz
// panel until it is boosted), and of a thread that missed some.
#pragma once

#include <algorithm>
#include <cstdint>
#include <cstdlib>

namespace player {

class RefreshMeter {
public:
    // A wake at `t` (nanoseconds on a steady clock), with `interval` the refresh interval in use. Returns the interval the
    // wakes keep when it is not the one in use (more than three in a thousand off), else 0.
    std::int64_t wake(std::int64_t t, std::int64_t interval) {
        if (phase_) {
            // Where the refreshes so far put this one, and the wake's difference from it.
            const std::int64_t k = (t - phase_ + interval / 2) / interval;
            const std::int64_t predicted = phase_ + k * interval;
            const std::int64_t off = t - predicted;
            if (std::llabs(off) < interval / 4) {
                // On the grid: followed slowly, an eighth of the difference.
                phase_ = predicted + off / 8;
                off_grid_ = 0;
            } else if (++off_grid_ >= 3) {
                // Three off it in a row: the grid starts over from this one.
                phase_ = t;
                off_grid_ = 0;
            }
        } else {
            phase_ = t;
        }
        // The interval the wakes keep, measured from the wakes themselves, apart from the grid: a grid laid at an
        // interval the wakes do not keep (a 160 Hz mode whose wakes come at 60 Hz) starts over every few wakes and would
        // never measure. Over a second at least, and 30 wakes: the gaps' lower quarter is one refresh (a missed wake makes
        // a gap of two or three, which may be half the gaps of a busy second; a late one a gap a little long and the next
        // a little short); each gap counts the refreshes it
        // holds at that, and the whole span over all of them is the interval, the lateness of its two ends spread over a
        // second's refreshes.
        if (!first_) {
            first_ = last_ = t;
            count_ = 0;
            return 0;
        }
        if (t <= last_) return 0;
        if (count_ < kGaps) gaps_[count_++] = t - last_;
        last_ = t;
        // A second, or as many gaps as there is room for (a display past 1000 Hz).
        if ((last_ - first_ < kSecond || count_ < 30) && count_ < kGaps) return 0;
        std::int64_t found = 0;
        const std::int64_t one = lower_quarter();
        if (one > 0) {
            std::int64_t refreshes = 0;
            for (int i = 0; i < count_; ++i) refreshes += std::max<std::int64_t>(1, (gaps_[i] + one / 2) / one);
            const std::int64_t real = (last_ - first_) / refreshes;
            if (std::llabs(real - interval) * 1000 > interval * 3) found = real;
        }
        first_ = last_;
        count_ = 0;
        return found;
    }
    // Where the last refresh fell (0: none yet).
    std::int64_t phase() const { return phase_; }
    // Starts over: another display.
    void restart() {
        phase_ = first_ = last_ = 0;
        off_grid_ = count_ = 0;
    }

private:
    static constexpr std::int64_t kSecond = 1000000000;
    // The gaps of a second's wakes: room for a 1000 Hz display's (when full, the second ends there).
    static constexpr int kGaps = 1024;
    // The gap a quarter of the way up from the shortest, by a partial sort of a copy (once a second).
    std::int64_t lower_quarter() const {
        std::int64_t copy[kGaps];
        std::copy(gaps_, gaps_ + count_, copy);
        std::nth_element(copy, copy + count_ / 4, copy + count_);
        return copy[count_ / 4];
    }
    std::int64_t phase_ = 0;
    int off_grid_ = 0;
    // The wakes measured: the first and last, and the gaps between them.
    std::int64_t first_ = 0, last_ = 0;
    std::int64_t gaps_[kGaps] = {};
    int count_ = 0;
};

}  // namespace player
