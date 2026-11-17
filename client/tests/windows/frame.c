// What Windows makes of the installer's window, for setup_e2e.sh under Wine, which has no taskbar and no screen reader
// (setup_e2e.sh builds it with the player's toolchain and runs it in the same Wine as the installer). The window is found
// by its title; each command prints one line and exits 1 when there is no such window.
//
//   frame.exe style TITLE         its styles as Windows keeps them: whether it has a caption (a title bar), a sizing frame,
//                                 a system menu, a minimise box, whether it is a pop-up and an application window
//                                 (a taskbar button), then both styles in hexadecimal
//   frame.exe rect TITLE          its place and size on the screen, and its own area's size: "X Y WIDTH HEIGHT W H"
//   frame.exe button TITLE NAME   the middle of its child window named NAME (the words a screen reader says for it, its
//                                 window's text) on the screen, and its size: "X Y WIDTH HEIGHT"
//   frame.exe state TITLE         "minimised", "shown" or "hidden"
//   frame.exe focus TITLE         the name of the window that has the keyboard in the window's thread, and whether the
//                                 window is the one in front: "focus=NAME front=yes|no"
//   frame.exe restore TITLE       a minimised window brought back as a click on its taskbar button does (its restore
//                                 command), waited for (10 s at most)
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>

// What the window named looks for among its children: a window with these words, and the one found.
static const wchar_t* g_name = NULL;
static HWND g_found = NULL;

// One child of the window: the one whose text is the name looked for ends the search.
static BOOL CALLBACK named(HWND child, LPARAM unused) {
    (void)unused;
    wchar_t text[256];
    if (GetWindowTextW(child, text, 256) > 0 && wcscmp(text, g_name) == 0) {
        g_found = child;
        return FALSE;
    }
    return TRUE;
}

// A window's text as UTF-8 for the console ("" when it has none).
static void print_text(HWND window) {
    wchar_t text[256] = L"";
    char utf8[1024] = "";
    if (window) GetWindowTextW(window, text, 256);
    WideCharToMultiByte(CP_UTF8, 0, text, -1, utf8, sizeof utf8, NULL, NULL);
    printf("%s", utf8);
}

int wmain(int argc, wchar_t** argv) {
    if (argc < 3) {
        printf("usage: frame.exe style|rect|button|state|focus|restore TITLE [NAME]\n");
        return 2;
    }
    // A top-level window of that title, shown or not.
    HWND window = FindWindowW(NULL, argv[2]);
    if (!window) {
        printf("none\n");
        return 1;
    }
    const wchar_t* command = argv[1];
    if (wcscmp(command, L"style") == 0) {
        const DWORD style = (DWORD)GetWindowLongW(window, GWL_STYLE), ex = (DWORD)GetWindowLongW(window, GWL_EXSTYLE);
        // A caption is both of its bits (a border and a dialog frame); a sizing frame is WS_THICKFRAME.
        printf("caption=%s sizeframe=%s sysmenu=%s minimize=%s popup=%s appwindow=%s style=%08lx exstyle=%08lx\n",
               (style & WS_CAPTION) == WS_CAPTION ? "yes" : "no", (style & WS_THICKFRAME) ? "yes" : "no",
               (style & WS_SYSMENU) ? "yes" : "no", (style & WS_MINIMIZEBOX) ? "yes" : "no", (style & WS_POPUP) ? "yes" : "no",
               (ex & WS_EX_APPWINDOW) ? "yes" : "no", (unsigned long)style, (unsigned long)ex);
        return 0;
    }
    if (wcscmp(command, L"rect") == 0) {
        RECT outer, inner;
        GetWindowRect(window, &outer);
        GetClientRect(window, &inner);
        printf("%ld %ld %ld %ld %ld %ld\n", outer.left, outer.top, outer.right - outer.left, outer.bottom - outer.top,
               inner.right, inner.bottom);
        return 0;
    }
    if (wcscmp(command, L"button") == 0 && argc >= 4) {
        g_name = argv[3];
        EnumChildWindows(window, named, 0);
        if (!g_found) {
            printf("none\n");
            return 1;
        }
        RECT r;
        GetWindowRect(g_found, &r);
        printf("%ld %ld %ld %ld\n", (r.left + r.right) / 2, (r.top + r.bottom) / 2, r.right - r.left, r.bottom - r.top);
        return 0;
    }
    if (wcscmp(command, L"state") == 0) {
        printf("%s\n", IsIconic(window) ? "minimised" : IsWindowVisible(window) ? "shown" : "hidden");
        return 0;
    }
    if (wcscmp(command, L"focus") == 0) {
        // The window's thread's own idea of the keyboard's place, as a screen reader asks it.
        GUITHREADINFO info;
        memset(&info, 0, sizeof info);
        info.cbSize = sizeof info;
        GetGUIThreadInfo(GetWindowThreadProcessId(window, NULL), &info);
        printf("focus=");
        print_text(info.hwndFocus);
        printf(" front=%s\n", GetForegroundWindow() == window ? "yes" : "no");
        return 0;
    }
    if (wcscmp(command, L"restore") == 0) {
        // Posted, as the taskbar's own click is: the installer hears it on its thread.
        PostMessageW(window, WM_SYSCOMMAND, SC_RESTORE, 0);
        // Back within 10 s, looked for every 10 ms.
        for (int waited = 0; waited < 1000 && IsIconic(window); ++waited) Sleep(10);
        printf("%s\n", IsIconic(window) ? "still minimised" : "restored");
        return 0;
    }
    printf("unknown command\n");
    return 2;
}
