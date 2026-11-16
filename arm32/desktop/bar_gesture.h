// A press on the overlay's handle or at the game's top edge, read as the bar's or the game's (window_win32.cpp feeds it
// a finger's or the mouse's press, its moves and its release, and its long press's timer): plain arithmetic on a clock's
// nanoseconds and the game's pixels, apart from any window, so that a check (settingstest.cpp) can take made-up presses
// through it.
//
// A press that may be the bar's is held from the game until it says what it is:
// - drawn down past a small slop (more down than across): the bar follows it, its foot at the press, and when it is let
//   go the bar settles down (pulled at least half way, or flicked down) or back up (less, or flicked back up);
// - a finger's (a touch screen's, a pen's) held still for a long press: the bar comes down;
// - a finger's let go at once without moving: on the handle, a tap that brings the bar; at the top edge beside it, the
//   game's tap after all, handed to it from where and when it came down;
// - the mouse's let go without being drawn down, however long it was held: the game's click after all, from where it
//   came down (the mouse brings the bar by the pointer resting on the handle or at the edge, or by drawing it down; its
//   click on the handle's place and a press held still there stay the game's, as the PC client's end to end holds);
// - moved across or up past the slop, or another finger coming down: the game's after all, from where and when it came
//   down, and its moves from then on.
// A press the game may have (anywhere else, the bar may not come now: another finger down, the question up, a song
// being played and the game not quiet) is the game's at once and is never held.
#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>

namespace player::overlay {

// Where a press came down: on the game, at its top edge (beside the handle), or on the handle.
enum class Zone { kGame, kEdge, kHandle };

// What the window does with a press's event.
enum class Act {
    kNone,         // nothing more: held, or the bar's already (a press that brought it, swallowed to its end)
    kGame,         // the game's: hand it what was held of it (its press, from where and when it came down) and this
    kPull,         // the bar follows the press: its place is place()
    kOpen,         // the bar comes down (a tap on the handle, a long press)
    kSettleOpen,   // let go after a pull: the bar settles down from where it is
    kSettleClosed  // let go after a pull: the bar goes back up from where it is
};

// The rules' numbers: at the game's 720 lines, scaled by the area's height.
struct GestureSizes {
    // How far a press moves before it is a pull or the game's (10 at 720 lines, 6 at least).
    int slop = 10;
    // The bar's height in the game's pixels: a pull's foot at the press's y, its place that share of it.
    int bar = 74;
};
inline GestureSizes gesture_sizes(int area_h) {
    const float k = static_cast<float>(area_h) / 720.0f;
    GestureSizes s;
    s.slop = std::max(6, static_cast<int>(std::lround(10.0f * k)));
    s.bar = std::max(1, static_cast<int>(std::lround(74.0f * k)));
    return s;
}

// A long press: held this long without moving past the slop.
constexpr std::int64_t kLongPressNs = 450000000;
// A pull let go: down if at least this share of the bar is out, unless flicked back up; up if less, unless flicked down.
constexpr float kSettleShare = 0.5f;
// A flick: the press moving this many bars' heights a second over its last moments, either way.
constexpr float kFlickBars = 1.5f;
// The moments a flick is measured over.
constexpr std::int64_t kFlickNs = 80000000;

class BarGesture {
public:
    // A press at (x, y) of the game's area at `t`, in `zone`; `may`: the bar may come now; `finger`: a finger's or a
    // pen's (its tap on the handle and its long press are the bar's), else the mouse's (only its pull is). kNone while it
    // is held, kGame when the game has it at once.
    Act down(int x, int y, std::int64_t t, Zone zone, bool may, const GestureSizes& sizes, bool finger) {
        sizes_ = sizes;
        // Kept for the release and the timer: what a press held still is.
        finger_ = finger;
        if (!may || zone == Zone::kGame) {
            state_ = State::kGame;
            return Act::kGame;
        }
        state_ = State::kHeld;
        zone_ = zone;
        x0_ = x;
        y0_ = y;
        t0_ = t;
        samples_ = 0;
        remember(y, t);
        return Act::kNone;
    }

    // The press moved to (x, y) at `t`.
    Act move(int x, int y, std::int64_t t) {
        switch (state_) {
        case State::kIdle:
            return Act::kNone;
        case State::kGame:
            return Act::kGame;
        case State::kTaken:
            return Act::kNone;
        case State::kHeld: {
            const int dx = x - x0_, dy = y - y0_;
            if (dy > sizes_.slop && dy >= std::abs(dx)) {
                // Drawn down: the bar's.
                state_ = State::kPulling;
                remember(y, t);
                place_ = place_at(y);
                return Act::kPull;
            }
            if (std::abs(dx) > sizes_.slop || dy < -sizes_.slop) {
                // Across or up: the game's after all.
                state_ = State::kGame;
                return Act::kGame;
            }
            return Act::kNone;
        }
        case State::kPulling:
            remember(y, t);
            place_ = place_at(y);
            return Act::kPull;
        }
        return Act::kNone;
    }

    // The press let go at (x, y) at `t`. The gesture is over after it.
    Act up(int x, int y, std::int64_t t) {
        const State was = state_;
        state_ = State::kIdle;
        switch (was) {
        case State::kIdle:
        case State::kTaken:
            return Act::kNone;
        case State::kGame:
            return Act::kGame;
        case State::kHeld:
            // Let go where it came down (a move within the slop): a finger's tap on the handle is the bar's; a tap
            // beside it, and the mouse's click however long it was held, the game's.
            (void)x;
            return zone_ == Zone::kHandle && finger_ ? Act::kOpen : Act::kGame;
        case State::kPulling: {
            remember(y, t);
            place_ = place_at(y);
            const float speed = speed_now();
            // Flicked back up, or not pulled half way unless flicked down: back up. Else down.
            if (speed <= -kFlickBars) return Act::kSettleClosed;
            if (place_ >= kSettleShare || speed >= kFlickBars) return Act::kSettleOpen;
            return Act::kSettleClosed;
        }
        }
        return Act::kNone;
    }

    // The long press's timer, at `t`: a finger held still long enough, the bar comes (the rest of the press is the bar's
    // too). The mouse's press has no long press: held still, it waits to be drawn down or let go.
    Act tick(std::int64_t t) {
        if (state_ != State::kHeld || !finger_ || t - t0_ < kLongPressNs) return Act::kNone;
        state_ = State::kTaken;
        return Act::kOpen;
    }

    // Another finger came down: a press still held is the game's after all (kGame); a pull settles where it is
    // (kSettleOpen or kSettleClosed); the gesture is over.
    Act other_press() {
        const State was = state_;
        if (was == State::kHeld) {
            state_ = State::kGame;
            return Act::kGame;
        }
        if (was == State::kPulling) {
            state_ = State::kTaken;
            return place_ >= kSettleShare ? Act::kSettleOpen : Act::kSettleClosed;
        }
        return Act::kNone;
    }

    // The press taken away (the system's own gesture, the window gone): forgotten, nothing for the game. A pull settles
    // back up.
    Act cancel() {
        const State was = state_;
        state_ = State::kIdle;
        return was == State::kPulling ? Act::kSettleClosed : Act::kNone;
    }

    // Whether a press is held from the game now (waiting to say what it is).
    bool held() const { return state_ == State::kHeld; }
    // Whether the bar has the press (pulled, or brought by a long press): its events are no one else's.
    bool bars() const { return state_ == State::kPulling || state_ == State::kTaken; }
    // Whether any press is being read (held, pulled, taken or the game's), until its release.
    bool active() const { return state_ != State::kIdle; }
    // The bar's place during a pull: the share of it out, its foot at the press, never less than a sliver.
    float place() const { return place_; }
    // Where and when the press came down, for the game when it is the game's after all.
    int x0() const { return x0_; }
    int y0() const { return y0_; }
    std::int64_t t0() const { return t0_; }
    // Where the press came down.
    Zone zone() const { return zone_; }

private:
    enum class State { kIdle, kHeld, kPulling, kTaken, kGame };
    // The share of the bar out with its foot at `y`: a sliver at least, the whole at most.
    float place_at(int y) const {
        const float p = static_cast<float>(y) / static_cast<float>(std::max(1, sizes_.bar));
        return std::min(1.0f, std::max(0.02f, p));
    }
    // The press's last moments, for its speed when let go.
    void remember(int y, std::int64_t t) {
        // Kept in a ring of the last eight.
        ys_[samples_ % kSamples] = y;
        ts_[samples_ % kSamples] = t;
        ++samples_;
    }
    // Bars' heights a second over the last kFlickNs (from the oldest kept moment within it to the newest).
    float speed_now() const {
        if (samples_ < 2) return 0;
        const int newest = (samples_ - 1) % kSamples;
        int oldest = newest;
        for (int back = 1; back < std::min(samples_, kSamples); ++back) {
            const int i = (samples_ - 1 - back) % kSamples;
            if (ts_[newest] - ts_[i] > kFlickNs) break;
            oldest = i;
        }
        const std::int64_t dt = ts_[newest] - ts_[oldest];
        if (dt <= 0) return 0;
        const float bars = static_cast<float>(ys_[newest] - ys_[oldest]) / static_cast<float>(std::max(1, sizes_.bar));
        return bars / (static_cast<float>(dt) / 1e9f);
    }
    static constexpr int kSamples = 8;
    State state_ = State::kIdle;
    // A finger's or a pen's press (true), or the mouse's.
    bool finger_ = true;
    Zone zone_ = Zone::kGame;
    GestureSizes sizes_;
    int x0_ = 0, y0_ = 0;
    std::int64_t t0_ = 0;
    float place_ = 0;
    int ys_[kSamples] = {};
    std::int64_t ts_[kSamples] = {};
    int samples_ = 0;
};

// Where a press at (x, y) of the game's area comes down: on the handle (its reach while it is shown), at the top edge
// (the rows a finger's or the pointer's tip covers there: 18 at 720 lines, 8 at least), or on the game.
inline Zone zone_at(int x, int y, int area_h, bool handle_shown, bool on_handle) {
    (void)x;
    if (handle_shown && on_handle) return Zone::kHandle;
    if (y >= 0 && y < std::max(8, area_h / 40)) return Zone::kEdge;
    return Zone::kGame;
}

// Whether a press on the handle or the top edge may be the bar's now: nothing else down on the game, no question up, and
// the game not being played (`song`: 1 a song is being played, 0 none, -1 not known) unless it has been quiet (no press
// or release for 1.5 s), so that a player's taps at the top of a song stay the game's.
inline bool bar_may_come(bool alone, bool asking, int song, bool quiet) {
    if (!alone || asking) return false;
    return song == 0 || quiet;
}

}  // namespace player::overlay
