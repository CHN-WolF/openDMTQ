// The display's refreshes, from the times DXGI wakes the refresh thread at them (window_win32.cpp's refresh_loop): where
// they fall (the grid the runtime paces by) and the interval they really keep. Apart from any window, so that a check
// (settingstest.cpp) can feed it the wakes of a display whose rate the system gave in whole hertz only, of one whose wakes
// come at a fraction of its rate (Windows 11's dynamic refresh rate keeps a program at 60 Hz on a 120, 180 or 240 Hz
// panel until it is boosted), and of a thread that missed some.
#pragma once

#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <vector>

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
        // The interval the wakes keep, measured from the wakes themselves over two seconds, apart from the grid: a grid
        // laid at an interval the wakes do not keep (a 160 Hz mode whose wakes come at 60 Hz) starts over every few wakes
        // and would never measure. The span of the wakes over the refreshes it held, counted gap by gap (below).
        if (!first_) {
            first_ = last_ = t;
            count_ = 0;
            return 0;
        }
        if (t <= last_) return 0;
        if (count_ < kGaps) gaps_[count_++] = t - last_;
        last_ = t;
        // Two seconds (a second's lateness at its ends weighs half as much), or as many gaps as there is room for.
        if ((last_ - first_ < 2 * kSecond || count_ < 30) && count_ < kGaps) return 0;
        std::int64_t found = 0;
        const std::int64_t one = lower_quarter();
        if (one > 0) {
            // The refreshes the span held. Near the interval in use (the gaps' median within a tenth of it): each gap in
            // whole intervals in use, a gap of nearly none counted as none, since a wake late by up to a whole refresh makes
            // its gap long and the next one short and the two count two between them (and a rate a few in a hundred off
            // still counts one a gap). Else the wakes keep another rate (a dynamic refresh rate's 60 Hz, its boost back
            // up): each gap in whole lower quarters, one at least (a missed wake's gap two or three).
            std::int64_t refreshes = 0;
            const std::int64_t span = last_ - first_;
            const std::int64_t middle = share_of_gaps(2);
            const bool at_rate = std::llabs(middle - interval) * 10 < interval;
            for (int i = 0; i < count_; ++i) {
                refreshes += at_rate ? (gaps_[i] + interval / 2) / interval : std::max<std::int64_t>(1, (gaps_[i] + one / 2) / one);
            }
            const std::int64_t real = refreshes > 0 ? span / refreshes : 0;
            // Another rate (a tenth off and more) at once; a small difference (a rate the system gave in whole hertz) only
            // when two measures in a row say the same, within a thousandth: one measure's lateness at its ends never moves
            // the interval (it did on a busy computer, a refresh miscounted in a second's 240: 241.07 Hz).
            if (real && std::llabs(real - interval) * 10 >= interval) {
                found = real;
                pending_ = 0;
            } else if (real && std::llabs(real - interval) * 1000 > interval * 3) {
                if (pending_ && std::llabs(real - pending_) * 1000 <= pending_) found = (real + pending_) / 2;
                pending_ = found ? 0 : real;
            } else {
                pending_ = 0;
            }
        }
        first_ = last_;
        count_ = 0;
        return found;
    }
    // Where the last refresh fell (0: none yet).
    std::int64_t phase() const { return phase_; }
    // Starts over: another display.
    void restart() {
        phase_ = first_ = last_ = pending_ = 0;
        off_grid_ = count_ = 0;
    }

private:
    static constexpr std::int64_t kSecond = 1000000000;
    // The gaps of two seconds' wakes: room for a 1000 Hz display's (when full, the measure ends there).
    static constexpr int kGaps = 2048;
    // The gap 1/`part` of the way up from the shortest (4: a quarter, 2: the median), by a partial sort of a copy (once
    // a measure).
    std::int64_t share_of_gaps(int part) const {
        std::vector<std::int64_t> copy(gaps_, gaps_ + count_);
        std::nth_element(copy.begin(), copy.begin() + count_ / part, copy.end());
        return copy[static_cast<std::size_t>(count_ / part)];
    }
    std::int64_t lower_quarter() const { return share_of_gaps(4); }
    std::int64_t phase_ = 0;
    int off_grid_ = 0;
    // A small difference one measure found, waiting for the next to say the same (0: none).
    std::int64_t pending_ = 0;
    // The wakes measured: the first and last, and the gaps between them.
    std::int64_t first_ = 0, last_ = 0;
    std::int64_t gaps_[kGaps] = {};
    int count_ = 0;
};

}  // namespace player
